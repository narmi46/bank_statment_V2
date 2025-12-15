import regex as re

# ============================================================
# MTASB PATTERN (Maybank Variant)
# Example: "01/05 TRANSFER TO A/C 320.00+ 43,906.52"
# ============================================================

PATTERN_MAYBANK_MTASB = re.compile(
    r"(\d{2}/\d{2})\s+"             # 01/05
    r"(.+?)\s+"                     # description
    r"([0-9,]+\.\d{2})([+-])\s+"    # amount + sign
    r"([0-9,]+\.\d{2})"             # balance
)


def parse_line_maybank_mtasb(line, page_num, default_year="2025"):
    m = PATTERN_MAYBANK_MTASB.search(line)
    if not m:
        return None

    date_raw, desc, amount_raw, sign, balance_raw = m.groups()
    day, month = date_raw.split("/")
    year = default_year

    amount = float(amount_raw.replace(",", ""))
    balance = float(balance_raw.replace(",", ""))

    credit = amount if sign == "+" else 0.0
    debit  = amount if sign == "-" else 0.0

    full_date = f"{year}-{month}-{day}"

    return {
        "date": full_date,
        "description": desc.strip(),
        "debit": debit,
        "credit": credit,
        "balance": balance,
        "page": page_num,
    }


# ============================================================
# MBB PATTERN (Balance-Driven)
# Example:
# "01 Feb 2025 CMS - DR CORP CHG 78.00 - 50,405.76"
# ============================================================

PATTERN_MAYBANK_MBB = re.compile(
    r"(\d{2})\s+([A-Za-z]{3})\s+(\d{4})\s+"  # 01 Feb 2025
    r"(.+?)\s+"                              # description
    r"[0-9,]+\.\d{2}\s+[+-]\s+"              # ignore amount & sign
    r"([0-9,]+\.\d{2})"                      # balance
)

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def parse_line_maybank_mbb(line, page_num, prev_balance):
    m = PATTERN_MAYBANK_MBB.search(line)
    if not m:
        return None, prev_balance

    day, mon_abbr, year, desc, balance_raw = m.groups()
    month = MONTH_MAP.get(mon_abbr.title(), "01")
    balance = float(balance_raw.replace(",", ""))

    # First balance seen → cannot infer debit/credit yet
    if prev_balance is None:
        return None, balance

    diff = balance - prev_balance

    credit = diff if diff > 0 else 0.0
    debit  = abs(diff) if diff < 0 else 0.0

    full_date = f"{year}-{month}-{day}"

    tx = {
        "date": full_date,
        "description": desc.strip(),
        "debit": debit,
        "credit": credit,
        "balance": balance,
        "page": page_num,
    }

    return tx, balance


# ============================================================
# MAIN ENTRY: PARSE ALL MAYBANK TRANSACTIONS
# ============================================================

def parse_transactions_maybank(text, page_num, default_year="2025"):
    tx_list = []
    prev_mbb_balance = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # --- MTASB ---
        tx = parse_line_maybank_mtasb(line, page_num, default_year)
        if tx:
            tx_list.append(tx)
            continue

        # --- MBB (balance-based) ---
        tx, prev_mbb_balance = parse_line_maybank_mbb(
            line, page_num, prev_mbb_balance
        )
        if tx:
            tx_list.append(tx)

    return tx_list
