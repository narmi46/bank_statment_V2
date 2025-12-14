import re

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
# REGEXES
# ============================================================

DATE_RE = re.compile(
    r'^\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',
    re.IGNORECASE
)

MONEY_RE = re.compile(r'\d{1,3}(?:,\d{3})*\.\d{2}-?')
SERIAL_RE = re.compile(r'\b\d{6,}\b')

# ============================================================
# HELPERS
# ============================================================

def clean_text(text):
    return " ".join(text.split()).strip() if text else ""


def parse_amount(s):
    neg = s.endswith("-")
    s = s.rstrip("-").replace(",", "")
    v = float(s)
    return -v if neg else v


def compute_debit_credit(prev_balance, curr_balance):
    if prev_balance is None:
        return 0.0, 0.0

    diff = round(curr_balance - prev_balance, 2)

    if diff > 0:
        return 0.0, diff
    elif diff < 0:
        return abs(diff), 0.0
    return 0.0, 0.0


def classify_first_tx(desc, amount):
    d = desc.upper()
    if (
        "DEPOSIT" in d or
        "CDT" in d or
        "INWARD" in d or
        " CR" in d or
        "DUITNOW" in d
    ):
        return 0.0, amount
    return amount, 0.0


# ============================================================
# PARSE ONE TRANSACTION BLOCK
# ============================================================

def parse_block(block_lines, page_num, year):
    global _prev_balance_global

    block_text = " ".join(block_lines)

    # Skip balance rows
    if "B/F BALANCE" in block_text or "C/F BALANCE" in block_text:
        return None

    # Extract date
    m = DATE_RE.match(block_lines[0])
    if not m:
        return None

    day, mon = m.groups()
    date = f"{year}-{MONTH_MAP[mon.capitalize()]}-{day.zfill(2)}"

    # Extract money values (amount + balance)
    monies = MONEY_RE.findall(block_text)
    if len(monies) < 2:
        return None

    amount = parse_amount(monies[-2])
    balance = parse_amount(monies[-1])

    # Clean description
    desc = MONEY_RE.sub("", block_text)
    desc = SERIAL_RE.sub("", desc)
    desc = clean_text(desc)

    # Debit / Credit
    if _prev_balance_global is None:
        debit, credit = classify_first_tx(desc, amount)
    else:
        debit, credit = compute_debit_credit(_prev_balance_global, balance)

    _prev_balance_global = balance

    return {
        "date": date,
        "description": desc,
        "debit": debit,
        "credit": credit,
        "balance": balance,
        "page": page_num
    }


# ============================================================
# MAIN PARSER (NO YEAR REQUIRED)
# ============================================================

def parse_transactions_rhb(text, page_num, year=2024):
    """
    Parse ONE page of RHB statement text.
    Year defaults to 2024 so caller does not need to pass it.
    """
    global _prev_balance_global

    if page_num == 1:
        _prev_balance_global = None

    transactions = []
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Look for start of transaction
        if not DATE_RE.match(line):
            i += 1
            continue

        block = [line]
        j = i + 1

        # Collect ALL lines until next date
        while j < len(lines) and not DATE_RE.match(lines[j]):
            block.append(lines[j].strip())
            j += 1

        tx = parse_block(block, page_num, year)
        if tx:
            transactions.append(tx)

        i = j

    return transactions
