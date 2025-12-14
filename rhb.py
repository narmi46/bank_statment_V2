import regex as re
from datetime import datetime

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
# INTERNAL STATE (CROSS-PAGE)
# ============================================================

_prev_balance = None

# ============================================================
# HELPERS
# ============================================================

def clean_desc(text):
    return " ".join(text.split()) if text else ""

def extract_year_from_pdf(pdf):
    """
    Extract year from:
    Statement Period : 7 Mar 24 – 31 Mar 24
    """
    for page in pdf.pages[:2]:
        text = page.extract_text() or ""
        m = re.search(
            r'Statement\s+Period.*?(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2,4})',
            text,
            re.IGNORECASE
        )
        if m:
            y = m.group(3)
            return int("20" + y if len(y) == 2 else y)

    return datetime.now().year

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
    s = (desc or "").upper()
    if any(k in s for k in ["CR", "CREDIT", "DEPOSIT", "INWARD", "CDT"]):
        return 0.0, amount
    return amount, 0.0

# ============================================================
# REGEX (RHB PDF FORMAT – WORKS FOR MAR 2024)
# ============================================================

RHB_TX = re.compile(
    r'^(\d{1,2})\s+'
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
    r'(.+?)\s+'
    r'(\d{4,20})\s+'
    r'([0-9,]+\.\d{2})\s+'
    r'([0-9,]+\.\d{2})$'
)

RHB_BF_CF = re.compile(
    r'^\d{1,2}\s+[A-Za-z]{3}\s+(B/F BALANCE|C/F BALANCE)',
    re.IGNORECASE
)

# ============================================================
# MAIN PARSER (PDF INPUT – v2 SAFE)
# ============================================================

def parse_transactions_rhb(pdf, source_filename=""):
    """
    FIXED v2:
    - Accepts pdf object
    - Handles pagination internally
    """
    global _prev_balance
    _prev_balance = None

    transactions = []
    year = extract_year_from_pdf(pdf)

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # Skip B/F & C/F
            if RHB_BF_CF.match(line):
                continue

            m = RHB_TX.match(line)
            if not m:
                continue

            day, mon, desc, serial, amt_raw, bal_raw = m.groups()

            amount = float(amt_raw.replace(",", ""))
            balance = float(bal_raw.replace(",", ""))

            date_iso = f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}"
            description = clean_desc(desc)

            if _prev_balance is None:
                debit, credit = classify_first_tx(description, amount)
            else:
                debit, credit = compute_debit_credit(_prev_balance, balance)

            transactions.append({
                "date": date_iso,
                "description": description,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "RHB Bank",
                "source_file": source_filename
            })

            _prev_balance = balance

    return transactions
