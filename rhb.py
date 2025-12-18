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
# INTERNAL STATE
# ============================================================

_prev_balance_global = None


# ============================================================
# HELPERS
# ============================================================

def fix_description(desc):
    return " ".join(desc.split()) if desc else desc


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
# SKIP B/F & C/F (ALL FORMATS)
# ============================================================

PATTERN_BF_CF = re.compile(
    r"\b(B/F\s+BALANCE|C/F\s+BALANCE)\b",
    re.IGNORECASE
)

# ============================================================
# FORMAT C – ISLAMIC (2025+)
# ============================================================

PATTERN_TX_C = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]{3})\s+"
    r"(.+?)\s+"
    r"(\d{4,20})\s+"
    r"([0-9,]+\.\d{2})\s+"
    r"([0-9,]+\.\d{2})"
)

# ============================================================
# FORMAT A – OLD RETAIL (PRE-2024)
# ============================================================

PATTERN_TX_A = re.compile(
    r"^(\d{1,2})\s+([A-Za-z]{3})\s+"
    r"(.+?)\s+"
    r"(\d{4,20})\s+"
    r"([0-9,]+\.\d{2})\s+"
    r"([0-9,]+\.\d{2})"
)

# ============================================================
# FORMAT B – REFLEX / ONLINE
# ============================================================

PATTERN_TX_B = re.compile(
    r"(\d{2}-\d{2}-\d{4})\s+"
    r"\d{3}\s+"
    r"(.+?)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2}|-)\s+"
    r"([0-9,]+\.\d{2})(-?)"
)


# ============================================================
# PARSE SINGLE LINE
# ============================================================

def parse_line_rhb(line, page_num, year):
    line = line.strip()
    if not line:
        return None

    # ---- Skip B/F & C/F ----
    if PATTERN_BF_CF.search(line):
        return {"type": "bf_cf"}

    # ---- Format C (Islamic) ----
    m = PATTERN_TX_C.match(line)
    if m:
        day, mon, desc, _, _, bal = m.groups()
        date_fmt = f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}"
        return {
            "type": "tx",
            "date": date_fmt,
            "description": fix_description(desc),
            "balance": float(bal.replace(",", "")),
            "page": page_num,
        }

    # ---- Format A (Old Retail) ----
    m = PATTERN_TX_A.match(line)
    if m:
        day, mon, desc, _, _, bal = m.groups()
        date_fmt = f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}"
        return {
            "type": "tx",
            "date": date_fmt,
            "description": fix_description(desc),
            "balance": float(bal.replace(",", "")),
            "page": page_num,
        }

    # ---- Format B (Online / Reflex) ----
    m = PATTERN_TX_B.search(line)
    if m:
        date_raw, desc, _, _, bal, minus = m.groups()
        dd, mm, yyyy = date_raw.split("-")
        bal_val = float(bal.replace(",", ""))
        if minus == "-":
            bal_val = -bal_val

        return {
            "type": "tx",
            "date": f"{yyyy}-{mm}-{dd}",
            "description": fix_description(desc),
            "balance": bal_val,
            "page": page_num,
        }

    return None


# ============================================================
# MAIN PARSER
# ============================================================

def parse_transactions_rhb(text, page_num, year=2025):
    global _prev_balance_global

    if page_num == 1:
        _prev_balance_global = None

    tx_list = []

    for line in (text or "").splitlines():
        parsed = parse_line_rhb(line, page_num, year)
        if not parsed or parsed["type"] == "bf_cf":
            continue

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
