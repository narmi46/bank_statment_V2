import regex as re

# ============================================================
# MONTH MAP
# ============================================================

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03",
    "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09",
    "Oct": "10", "Nov": "11", "Dec": "12"
}

# ============================================================
# INTERNAL STATE (PERSISTS ACROSS PAGES)
# ============================================================

_prev_balance_global = None

# ============================================================
# SIMPLE DESCRIPTION CLEANER
# ============================================================

def fix_description(desc):
    if not desc:
        return desc
    return " ".join(desc.split())

# ============================================================
# BALANCE → DEBIT / CREDIT LOGIC
# ============================================================

def compute_debit_credit(prev_balance, curr_balance):
    if prev_balance is None:
        return 0.0, 0.0

    diff = round(curr_balance - prev_balance, 2)

    if diff > 0:
        return 0.0, diff
    elif diff < 0:
        return abs(diff), 0.0
    return 0.0, 0.0

# ============================================================
# REGEX PATTERNS
# ============================================================

# -------- OPENING BALANCE --------
PATTERN_OPENING_BAL = re.compile(
    r"Beginning Balance as of .*?([0-9,]+\.\d{2})(-?)",
    re.IGNORECASE
)

# -------- FORMAT A (Old RHB PDF) --------
PATTERN_TX_A = re.compile(
    r"^(\d{1,2})([A-Za-z]{3})\s+"
    r"(.+?)\s+"
    r"(\d{4,20})\s+"
    r"([0-9,]+\.\d{2})\s+"
    r"([0-9,]+\.\d{2})"
)

PATTERN_BF_CF = re.compile(
    r"^\d{1,2}[A-Za-z]{3}\s+(B/F BALANCE|C/F BALANCE)\s+([0-9,]+\.\d{2})$"
)

# -------- FORMAT B (Internet Banking) --------
PATTERN_TX_B = re.compile(
    r"(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{3})\s+"
    r"(.+?)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2})([+-])"
)

# -------- FORMAT C (Islamic PDF) --------
PATTERN_TX_C = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]{3})\s+"
    r"(.+?)\s+"
    r"(\d{4,20})\s+"
    r"([0-9,]+\.\d{2})\s+"
    r"([0-9,]+\.\d{2})"
)

# ============================================================
# PARSE A SINGLE LINE
# ============================================================

def parse_line_rhb(line, page_num, year=2025):
    line = line.strip()
    if not line:
        return None

    # -------- OPENING BALANCE --------
    mOB = PATTERN_OPENING_BAL.search(line)
    if mOB:
        amt, neg = mOB.groups()
        bal = float(amt.replace(",", ""))
        if neg:
            bal = -bal
        return {
            "type": "opening_balance",
            "balance": bal
        }

    # -------- FORMAT C --------
    mC = PATTERN_TX_C.match(line)
    if mC:
        day, mon, desc, serial, amt1, amt2 = mC.groups()
        date_fmt = f"{year}-{MONTH_MAP.get(mon, '01')}-{day.zfill(2)}"
        return {
            "type": "tx",
            "date": date_fmt,
            "description": fix_description(desc),
            "amount_raw": float(amt1.replace(",", "")),
            "balance": float(amt2.replace(",", "")),
            "page": page_num,
        }

    # -------- FORMAT A --------
    mA = PATTERN_TX_A.match(line)
    if mA:
        day, mon, desc, serial, amt1, amt2 = mA.groups()
        date_fmt = f"{year}-{MONTH_MAP.get(mon, '01')}-{day.zfill(2)}"
        return {
            "type": "tx",
            "date": date_fmt,
            "description": fix_description(desc),
            "amount_raw": float(amt1.replace(",", "")),
            "balance": float(amt2.replace(",", "")),
            "page": page_num,
        }

    # -------- B/F or C/F --------
    if PATTERN_BF_CF.match(line):
        return {"type": "bf_cf"}

    # -------- FORMAT B --------
    mB = PATTERN_TX_B.search(line)
    if mB:
        date_raw, branch, desc, dr_raw, cr_raw, balance_raw, sign = mB.groups()
        dd, mm, yyyy = date_raw.split("-")
        date_fmt = f"{yyyy}-{mm}-{dd}"

        debit = float(dr_raw.replace(",", "")) if dr_raw != "-" else 0.0
        credit = float(cr_raw.replace(",", "")) if cr_raw != "-" else 0.0

        bal = float(balance_raw.replace(",", ""))
        if sign == "-":
            bal = -bal

        return {
            "type": "tx",
            "date": date_fmt,
            "description": f"{branch} {desc}",
            "amount_raw": debit + credit,
            "balance": bal,
            "page": page_num,
        }

    return None

# ============================================================
# MAIN PARSER
# ============================================================

def parse_transactions_rhb(text, page_num, year=2025):
    global _prev_balance_global

    # Reset on first page
    if page_num == 1:
        _prev_balance_global = None

    tx_list = []

    for raw_line in text.splitlines():
        parsed = parse_line_rhb(raw_line, page_num, year)
        if not parsed:
            continue

        # -------- OPENING BALANCE --------
        if parsed["type"] == "opening_balance":
            _prev_balance_global = parsed["balance"]
            continue

        # -------- SKIP B/F & C/F --------
        if parsed["type"] == "bf_cf":
            continue

        # -------- TRANSACTION --------
        curr_balance = parsed["balance"]

        debit, credit = compute_debit_credit(
            _prev_balance_global,
            curr_balance
        )

        tx_list.append({
            "date": parsed["date"],
            "description": parsed["description"],
            "debit": debit,
            "credit": credit,
            "balance": curr_balance,
            "page": page_num,
        })

        _prev_balance_global = curr_balance

    return tx_list
