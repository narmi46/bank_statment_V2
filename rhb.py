import regex as re
from datetime import datetime

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03",
    "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09",
    "Oct": "10", "Nov": "11", "Dec": "12"
}

_prev_balance = None

def clean_desc(s):
    return " ".join(s.split()) if s else ""

def extract_year_from_pdf(pdf):
    for p in pdf.pages[:2]:
        t = p.extract_text() or ""
        m = re.search(r'Statement Period.*?(\d{1,2})\s+\w+\s+(\d{2,4})', t)
        if m:
            y = m.group(2)
            return int("20" + y if len(y) == 2 else y)
    return datetime.now().year

def compute_debit_credit(prev, curr):
    if prev is None:
        return 0.0, 0.0
    diff = round(curr - prev, 2)
    if diff > 0:
        return 0.0, diff
    elif diff < 0:
        return abs(diff), 0.0
    return 0.0, 0.0

def classify_first(desc, amt):
    s = desc.upper()
    if any(k in s for k in ["CR", "DEPOSIT", "INWARD", "CDT"]):
        return 0.0, amt
    return amt, 0.0

RHB_TX = re.compile(
    r'(\d{1,2})\s+'
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
    r'(.+?)\s+'
    r'(\d{4,20})\s+'
    r'([0-9,]+\.\d{2})\s+'
    r'([0-9,]+\.\d{2})',
    re.IGNORECASE
)

RHB_SKIP = re.compile(r'B/F BALANCE|C/F BALANCE', re.IGNORECASE)

def parse_transactions_rhb(pdf, source_filename=""):
    global _prev_balance
    _prev_balance = None

    tx = []
    year = extract_year_from_pdf(pdf)

    for page_num, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""

        for line in text.splitlines():
            if RHB_SKIP.search(line):
                continue

            m = RHB_TX.search(line)
            if not m:
                continue

            day, mon, desc, serial, amt, bal = m.groups()

            amount = float(amt.replace(",", ""))
            balance = float(bal.replace(",", ""))

            if _prev_balance is None:
                debit, credit = classify_first(desc, amount)
            else:
                debit, credit = compute_debit_credit(_prev_balance, balance)

            tx.append({
                "date": f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}",
                "description": clean_desc(desc),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "RHB Bank",
                "source_file": source_filename
            })

            _prev_balance = balance

    return tx
