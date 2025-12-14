# rhb.py — FINAL WORKING RHB BANK PARSER
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

    m = re.search(
        r'\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
        text,
        re.IGNORECASE
    )
    if m:
        return m.group(2)

    return None


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------

MONTH_MAP = {
    'Jan': '01', 'January': '01',
    'Feb': '02', 'February': '02',
    'Mar': '03', 'March': '03',
    'Apr': '04', 'April': '04',
    'May': '05',
    'Jun': '06', 'June': '06',
    'Jul': '07', 'July': '07',
    'Aug': '08', 'August': '08',
    'Sep': '09', 'September': '09',
    'Oct': '10', 'October': '10',
    'Nov': '11', 'November': '11',
    'Dec': '12', 'December': '12'
}


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_text(text):
    return ' '.join(text.split()).strip() if text else ""


def parse_amount(s):
    if not s:
        return 0.0
    s = s.replace(',', '').strip()
    neg = s.endswith('-')
    s = s.rstrip('-')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return 0.0


def classify_amount(desc, amount):
    d = desc.upper()

    debit_keys = [
        ' DR', 'FEE', 'FEES', 'CHG', 'CHARGE',
        'WITHDRAWAL', 'MYDEBIT', 'AUTODEBIT',
        'ATM', 'PAY', 'TRANSFER DR'
    ]

    credit_keys = [
        ' CR', 'DEPOSIT', 'INWARD', 'IBG',
        'DUITNOW', 'QR', 'CASH DEPOSIT'
    ]

    if any(k in d for k in debit_keys):
        return abs(amount), 0.0
    if any(k in d for k in credit_keys):
        return 0.0, abs(amount)

    return (abs(amount), 0.0) if amount < 0 else (0.0, abs(amount))


# ---------------------------------------------------------
# FORMAT 1 — REFLEX CASH MANAGEMENT
# ---------------------------------------------------------

def parse_reflex_format(text, page, source):
    txs = []
    money_re = re.compile(r'^\d{1,3}(?:,\d{3})*\.\d{2}-?$')

    for line in text.splitlines():
        m = re.match(r'^(\d{2})-(\d{2})-(\d{4})\s+(.*)', line)
        if not m:
            continue

        day, month, year, rest = m.groups()
        tokens = rest.split()

        amounts = [parse_amount(t) for t in tokens if money_re.match(t)]
        if len(amounts) < 2:
            continue

        balance = amounts[-1]
        amount = amounts[-2]

        desc = ' '.join(t for t in tokens if not money_re.match(t))
        debit, credit = classify_amount(desc, amount)

        txs.append({
            "date": f"{year}-{month}-{day}",
            "description": clean_text(desc),
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "page": page,
            "source_file": source,
            "bank": "RHB Bank"
        })

    return txs


# ---------------------------------------------------------
# FORMAT 2 — STANDARD RHB STATEMENTS (3 MAR 2024 FIXED)
# ---------------------------------------------------------

def parse_standard_format(text, page, year, source):
    txs = []
    lines = [l.rstrip() for l in text.splitlines()]

    date_re = re.compile(
        r'^\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',
        re.IGNORECASE
    )
    money_re = re.compile(r'^\d{1,3}(?:,\d{3})*\.\d{2}$')

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = date_re.match(line)

        if not m:
            i += 1
            continue

        day, mon = m.groups()
        day = day.zfill(2)
        month = MONTH_MAP[mon.capitalize()]
        rest = line[m.end():].strip()

        if 'B/F BALANCE' in rest or 'C/F BALANCE' in rest:
            i += 1
            continue

        desc_parts = []
        amounts = []

        # parse current line
        for t in rest.split():
            if money_re.match(t):
                amounts.append(parse_amount(t))
            else:
                desc_parts.append(t)

        # look ahead for wrapped OCR lines
        j = i + 1
        while j < len(lines):
            nl = lines[j].strip()
            if date_re.match(nl):
                break

            for t in nl.split():
                if money_re.match(t):
                    amounts.append(parse_amount(t))
                else:
                    desc_parts.append(t)

            if len(amounts) >= 2:
                break

            j += 1

        if len(amounts) < 2:
            i += 1
            continue

        balance = amounts[-1]
        amount = amounts[-2]
        desc = clean_text(' '.join(desc_parts))

        debit, credit = classify_amount(desc, amount)

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

        i = j if j > i else i + 1

    return txs


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_transactions_rhb(pdf, source_filename=""):
    all_tx = []

    year = None
    for p in pdf.pages[:3]:
        year = extract_year_from_text(p.extract_text() or "")
        if year:
            break

    if not year:
        year = str(datetime.now().year)

    first_text = pdf.pages[0].extract_text() or ""
    is_reflex = (
        'Reflex Cash Management' in first_text or
        'TRANSACTION STATEMENT' in first_text
    )

    for idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        if is_reflex:
            tx = parse_reflex_format(text, idx, source_filename)
        else:
            tx = parse_standard_format(text, idx, year, source_filename)
        all_tx.extend(tx)

    return all_tx
