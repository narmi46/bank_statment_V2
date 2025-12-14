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
# INTERNAL STATE (RESETS PER FILE)
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
# REGEX PATTERNS
# ============================================================

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
# PARSE SINGLE LINE
# ============================================================

def parse_line_rhb(line, page_num, year):
    line = line.strip()
    if not line:
        return None

    # --- FORMAT C ---
    mC = PATTERN_TX_C.match(line)
    if mC:
        day, mon, desc, serial, amt, bal = mC.groups()
        return {
            "date": f"{year}-{MONTH_MAP.get(mon,'01')}-{day.zfill(2)}",
            "description": fix_description(desc),
            "amount_raw": float(amt.replace(",", "")),
            "balance": float(bal.replace(",", "")),
            "page": page_num
        }

    # --- FORMAT A ---
    mA = PATTERN_TX_A.match(line)
    if mA:
        day, mon, desc, serial, amt, bal = mA.groups()
        return {
            "date": f"{year}-{MONTH_MAP.get(mon,'01')}-{day.zfill(2)}",
            "description": fix_description(desc),
            "amount_raw": float(amt.replace(",", "")),
            "balance": float(bal.replace(",", "")),
            "page": page_num
        }

    # --- B/F or C/F ---
    if PATTERN_BF_CF.match(line):
        return "SKIP"

    # --- FORMAT B ---
    mB = PATTERN_TX_B.search(line)
    if mB:
        date_raw, branch, desc, dr, cr, bal, sign = mB.groups()
        dd, mm, yyyy = date_raw.split("-")
        bal = float(bal.replace(",", ""))
        if sign == "-":
            bal = -bal

        return {
            "date": f"{yyyy}-{mm}-{dd}",
            "description": f"{branch} {desc}",
            "amount_raw": (
                float(dr.replace(",", "")) if dr != "-" else
                float(cr.replace(",", "")) if cr != "-" else 0.0
            ),
            "balance": bal,
            "page": page_num
        }

    return None

# ============================================================
# PAGE-LEVEL PARSER
# ============================================================

def parse_transactions_rhb_page(text, page_num, year):
    global _prev_balance_global
    tx_list = []

    for line in text.splitlines():
        parsed = parse_line_rhb(line, page_num, year)
        if not parsed or parsed == "SKIP":
            continue

        curr_balance = parsed["balance"]
        amount = parsed["amount_raw"]

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
            "page": page_num
        })

        _prev_balance_global = curr_balance

    return tx_list

# ============================================================
# APP v2 ENTRY POINT
# ============================================================

def parse_transactions_rhb(pdf, source_file):
    """
    App v2 compatible RHB parser
    """
    global _prev_balance_global
    _prev_balance_global = None

    all_tx = []

    # Detect year from filename
    year = 2025
    for y in range(2015, 2031):
        if str(y) in source_file:
            year = y
            break

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue

        page_tx = parse_transactions_rhb_page(text, page_num, year)

        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            all_tx.append(tx)

    return all_tx
