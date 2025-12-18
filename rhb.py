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
# FIRST TRANSACTION SCAN METHOD
# ============================================================

def classify_first_tx(desc, amount):
    s = re.sub(r"\s+", "", desc or "").upper()
    if (
        "DEPOSIT" in s or
        "CDT" in s or
        "INWARD" in s or
        s.endswith("CR")
    ):
        return 0.0, amount
    return amount, 0.0


# ============================================================
# REGEX PATTERNS FOR ALL RHB FORMATS
# ============================================================

# -------- FORMAT A (Old RHB PDF: 3 March 2024) --------
PATTERN_TX_A = re.compile(
    r"^(\d{1,2})([A-Za-z]{3})\s+"        # 07 Mar
    r"(.+?)\s+"                          # description
    r"(\d{4,20})\s+"                     # serial (4–20 digits)
    r"([0-9,]+\.\d{2})\s+"               # amount
    r"([0-9,]+\.\d{2})"                  # balance
)

PATTERN_BF_CF = re.compile(
    r"^\d{1,2}[A-Za-z]{3}\s+(B/F BALANCE|C/F BALANCE)\s+([0-9,]+\.\d{2})$"
)

# -------- FORMAT B (Internet banking after export) --------
PATTERN_TX_B = re.compile(
    r"(\d{2}-\d{2}-\d{4})\s+"
    r"(\d{3})\s+"
    r"(.+?)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2})([+-])"
)

# -------- FORMAT C (New Islamic PDF: Jan 2025) --------
PATTERN_TX_C = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]{3})\s+"     # 06 Jan
    r"(.+?)\s+"                          # description (multi-word)
    r"(\d{4,20})\s+"                     # serial
    r"([0-9,]+\.\d{2})\s+"               # amount
    r"([0-9,]+\.\d{2})"                  # balance
)


# ============================================================
# PARSE A SINGLE LINE (TRY FORMAT C → A → B)
# ============================================================

def parse_line_rhb(line, page_num, year=2025):

    line = line.strip()
    if not line:
        return None

    # -------- FORMAT C: Islamic PDF (Jan 2025) --------
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

    # -------- FORMAT A: Old RHB PDF --------
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

    # -------- FORMAT B: Online Banking --------
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

    # Restart on page 1
    if page_num == 1:
        _prev_balance_global = None

    tx_list = []

    for raw_line in text.splitlines():
        parsed = parse_line_rhb(raw_line, page_num, year)
        if not parsed:
            continue

        if parsed["type"] == "bf_cf":
            continue

        curr_balance = parsed["balance"]
        amount = parsed["amount_raw"]

        # First TX = scan method
        if _prev_balance_global is None:
            debit, credit = classify_first_tx(parsed["description"], amount)
        else:
            debit, credit = compute_debit_credit(_prev_balance_global, curr_balance)

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
