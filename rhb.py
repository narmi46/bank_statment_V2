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
# STRONG B/F & C/F SKIP (ALL FORMATS)
# ============================================================

PATTERN_BF_CF = re.compile(
    r"\b(B/F\s+BALANCE|C/F\s+BALANCE)\b",
    re.IGNORECASE
)


# ============================================================
# FORMAT C – RHB ISLAMIC PDF
# ============================================================

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

    # ---- SKIP B/F & C/F ALWAYS ----
    if PATTERN_BF_CF.search(line):
        return {"type": "bf_cf"}

    # ---- FORMAT C (Islamic) ----
    m = PATTERN_TX_C.match(line)
    if m:
        day, mon, desc, serial, amt, bal = m.groups()
        date_fmt = f"{year}-{MONTH_MAP.get(mon, '01')}-{day.zfill(2)}"
        return {
            "type": "tx",
            "date": date_fmt,
            "description": fix_description(desc),
            "amount_raw": float(amt.replace(",", "")),
            "balance": float(bal.replace(",", "")),
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
