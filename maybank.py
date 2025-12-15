# maybank.py
# Maybank parser – description ONLY from the same line as balance

import re

# ============================================================
# YEAR EXTRACTION
# ============================================================

def extract_year_from_text(text):
    if not text:
        return None

    patterns = [
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        r'\d{1,2}/\d{1,2}/(\d{4})\s*-\s*\d{1,2}/\d{1,2}/\d{4}',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
    ]

    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            y = m.groups()[-1]
            return str(2000 + int(y)) if len(y) == 2 else y

    return None


# ============================================================
# CLEAN LINE
# ============================================================

def clean_line(line):
    if not line:
        return ""
    line = line.replace("\xa0", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


# ============================================================
# REGEX
# Supports: .30 0.30 1,234.56
# ============================================================

AMOUNT = r"(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}"

PATTERN_MAYBANK = re.compile(
    rf"^(\d{{2}}/\d{{2}})\s+(.+?)\s+({AMOUNT})\s*([+-])\s+({AMOUNT})$"
)


# ============================================================
# MAIN PARSER
# ============================================================

def parse_transactions_maybank(pdf, source_file=""):
    transactions = []

    year = None
    for p in pdf.pages:
        year = extract_year_from_text(p.extract_text() or "")
        if year:
            break
    if not year:
        raise ValueError("Year not found")

    year = int(year)

    for page_no, page in enumerate(pdf.pages, start=1):
        lines = (page.extract_text() or "").splitlines()

        for raw_line in lines:
            line = clean_line(raw_line)

            # ✅ ONLY parse lines that contain balance
            m = PATTERN_MAYBANK.match(line)
            if not m:
                continue

            date_raw, desc, amt_raw, sign, bal_raw = m.groups()
            day, month = date_raw.split("/")

            def norm(x):
                x = x.replace(",", "")
                if x.startswith("."):
                    x = "0" + x
                return float(x)

            amount = norm(amt_raw)
            balance = norm(bal_raw)

            transactions.append({
                "date": f"{year}-{month}-{day}",
                "description": desc.strip(),   # ✅ FIRST LINE ONLY
                "debit": amount if sign == "-" else 0.0,
                "credit": amount if sign == "+" else 0.0,
                "balance": balance,
                "page": page_no,
                "bank": "Maybank",
                "source_file": source_file,
            })

    return transactions
