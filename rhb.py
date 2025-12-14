# rhb.py - Comprehensive RHB Bank Parser (FIXED)
import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    if not text:
        return None

    # "Statement Period : 7 Mar 24 – 31 Mar 24"
    m = re.search(
        r'Statement Period[^:]*:\s*\d{1,2}\s+[A-Za-z]{3,9}\s+(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if m:
        y = m.group(1)
        return str(2000 + int(y)) if len(y) == 2 else y

    # "01 February 2025"
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
        val = float(s)
        return -val if neg else val
    except:
        return 0.0


def classify_amount(desc, amount):
    """RHB-specific debit / credit logic"""
    desc_u = desc.upper()

    debit_keywords = [
        ' DR', 'FEE', 'FEES', 'CHG', 'CHARGE',
        'WITHDRAWAL', 'MYDEBIT', 'AUTODEBIT',
        'ATM', 'PAY', 'TRANSFER DR'
    ]

    credit_keywords = [
        ' CR', 'DEPOSIT', 'INWARD',
        'DUITNOW', 'QR', 'IBG', 'CASH DEPOSIT'
    ]

    if any(k in desc_u for k in debit_keywords):
        return abs(amount), 0.0
    if any(k in desc_u for k in credit_keywords):
        return 0.0, abs(amount)

    # fallback
    return (abs(amount), 0.0) if amount < 0 else (0.0, abs(amount))


# ---------------------------------------------------------
# FORMAT 1 — REFLEX
# ---------------------------------------------------------

def parse_reflex_format(text, page, source):
    txs = []
    for line in text.splitlines():
        m = re.match(r'^(\d{2})-(\d{2})-(\d{4})\s+(.*)', line)
        if not m:
            continue

        day, month, year, rest = m.groups()
        parts = rest.split()

        nums = [parse_amount(p) for p in parts if re.match(r'^[\d,.-]+$', p)]
        if len(nums) < 2:
            continue

        balance = nums[-1]
        amount = nums[-2]

        desc = ' '.join(p for p in parts if not re.match(r'^[\d,.-]+$', p))
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
# FORMAT 2 — STANDARD RHB
# ---------------------------------------------------------

def parse_standard_format(text, page, year, source):
    txs = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        m = re.match(
            r'^\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b\s*(.*)',
            line,
            re.IGNORECASE
        )
        if not m:
            i += 1
            continue

        day, mon, rest = m.groups()
        day = day.zfill(2)
        month = MONTH_MAP[mon.capitalize()]

        if 'B/F BALANCE' in rest or 'C/F BALANCE' in rest:
            i += 1
            continue

        desc_parts = []
        numbers = []

        # parse current line
        for p in rest.split():
            if re.match(r'^\d+[\d,]*\.?\d*$', p.replace(',', '')):
                numbers.append(float(p.replace(',', '')))
            else:
                desc_parts.append(p)

        # continuation lines
        j = i + 1
        while j < len(lines):
            nl = lines[j].strip()
            if re.match(r'^\d{1,2}\s+(Jan|Feb|Mar)', nl, re.IGNORECASE):
                break

            has_num = False
            for p in nl.split():
                if re.match(r'^\d+[\d,]*\.?\d*$', p.replace(',', '')):
                    numbers.append(float(p.replace(',', '')))
                    has_num = True
                else:
                    desc_parts.append(p)

            if has_num:
                break
            j += 1

        if len(numbers) >= 2:
            balance = numbers[-1]
            amount = numbers[-2]
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
# MAIN
# ---------------------------------------------------------

def parse_transactions_rhb(pdf, source_filename=""):
    all_tx = []

    detected_year = None
    for p in pdf.pages[:3]:
        detected_year = extract_year_from_text(p.extract_text() or "")
        if detected_year:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    first_text = pdf.pages[0].extract_text() or ""
    is_reflex = 'Reflex Cash Management' in first_text or 'TRANSACTION STATEMENT' in first_text

    for idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        if is_reflex:
            tx = parse_reflex_format(text, idx, source_filename)
        else:
            tx = parse_standard_format(text, idx, detected_year, source_filename)

        all_tx.extend(tx)

    return all_tx
