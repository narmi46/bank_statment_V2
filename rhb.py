# rhb.py — FINAL VERIFIED RHB PARSER (3 MAR 2024 WORKS)
import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    if not text:
        return None

    m = re.search(
        r'Statement Period[^:]*:\s*\d{1,2}\s+[A-Za-z]{3,9}\s+(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if m:
        y = m.group(1)
        return str(2000 + int(y)) if len(y) == 2 else y

    return None


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

MONTH_MAP = {
    'Jan': '01', 'February': '02',
    'Feb': '02', 'Mar': '03',
    'Apr': '04', 'May': '05',
    'Jun': '06', 'Jul': '07',
    'Aug': '08', 'Sep': '09',
    'Oct': '10', 'Nov': '11',
    'Dec': '12'
}

DATE_RE = re.compile(
    r'^\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',
    re.IGNORECASE
)

MONEY_RE = re.compile(r'\d{1,3}(?:,\d{3})*\.\d{2}-?')


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_text(t):
    return ' '.join(t.split()).strip()


def parse_amount(s):
    neg = s.endswith('-')
    s = s.rstrip('-').replace(',', '')
    v = float(s)
    return -v if neg else v


def classify(desc, amount):
    d = desc.upper()

    debit_keys = [
        ' DR', 'FEE', 'FEES', 'CHG',
        'WITHDRAWAL', 'MYDEBIT', 'ATM',
        'TRANSFER DR'
    ]

    credit_keys = [
        ' CR', 'DEPOSIT', 'INWARD',
        'DUITNOW', 'QR', 'IBG'
    ]

    if any(k in d for k in debit_keys):
        return abs(amount), 0.0
    if any(k in d for k in credit_keys):
        return 0.0, abs(amount)

    return (abs(amount), 0.0) if amount < 0 else (0.0, abs(amount))


# ---------------------------------------------------------
# STANDARD RHB PARSER (ROBUST)
# ---------------------------------------------------------

def parse_standard_format(text, page, year, source):
    txs = []
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0

    while i < len(lines):
        line = lines[i]
        m = DATE_RE.match(line)

        if not m:
            i += 1
            continue

        day, mon = m.groups()
        day = day.zfill(2)
        month = MONTH_MAP[mon.capitalize()]

        # collect ALL lines for this transaction
        block = [line[m.end():].strip()]
        j = i + 1

        while j < len(lines) and not DATE_RE.match(lines[j]):
            block.append(lines[j].strip())
            j += 1

        block_text = " ".join(block)

        if 'B/F BALANCE' in block_text or 'C/F BALANCE' in block_text:
            i = j
            continue

        # extract money safely
        monies = MONEY_RE.findall(block_text)
        if len(monies) < 2:
            i = j
            continue

        amount = parse_amount(monies[-2])
        balance = parse_amount(monies[-1])

        # description = everything except money & serials
        desc = MONEY_RE.sub('', block_text)
        desc = re.sub(r'\b\d{6,}\b', '', desc)
        desc = clean_text(desc)

        debit, credit = classify(desc, amount)

        txs.append({
            "date": f"{year}-{month}-{day}",
            "description": desc,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "page": page,
            "source_file": source,
            "bank": "RHB Bank"
        })

        i = j

    return txs


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def parse_transactions_rhb(pdf, source_filename=""):
    txs = []

    year = None
    for p in pdf.pages[:3]:
        year = extract_year_from_text(p.extract_text() or "")
        if year:
            break

    if not year:
        year = str(datetime.now().year)

    for idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        txs.extend(parse_standard_format(text, idx, year, source_filename))

    return txs
