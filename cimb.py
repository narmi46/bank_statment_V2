# cimb.py - CIMB Parser (LAST TRANSACTION BALANCE MODE)

import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    if not text:
        return None

    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if match:
        y = match.group(1)
        return y if len(y) == 4 else str(2000 + int(y))

    return None


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def parse_float(value):
    if not value:
        return 0.0
    clean = str(value).replace(",", "").replace(" ", "").replace("\n", "")
    return float(clean) if re.match(r'^-?\d+(\.\d+)?$', clean) else 0.0


def clean_text(text):
    return text.replace("\n", " ").strip() if text else ""


def format_date(date_str, year):
    if not date_str:
        return f"{year}-01-01"

    date_str = clean_text(date_str)

    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', date_str)
    if m:
        d, mth, y = m.groups()
        return f"{y}-{mth}-{d}"

    m = re.match(r'(\d{2})/(\d{2})', date_str)
    if m:
        d, mth = m.groups()
        return f"{year}-{mth}-{d}"

    return f"{year}-01-01"


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_transactions_cimb(pdf, source_filename=""):
    transactions = []
    detected_year = None
    row_counter = 0

    # Detect year
    for page in pdf.pages[:3]:
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    # Parse tables
    for page_no, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:
            row_counter += 1

            if not row or len(row) < 6:
                continue

            # Skip headers
            if row[0] and str(row[0]).lower() in ("date", "tarikh"):
                continue

            desc = clean_text(row[1]).lower()

            # Skip opening balance
            if "opening balance" in desc:
                continue

            debit = parse_float(row[3])
            credit = parse_float(row[4])
            balance = parse_float(row[5])

            if debit == 0.0 and credit == 0.0:
                continue

            if balance == 0.0:
                continue

            transactions.append({
                "date": format_date(row[0], detected_year),
                "description": clean_text(row[1]),
                "ref_no": clean_text(row[2]),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_no,
                "row_index": row_counter,
                "source_file": source_filename,
                "bank": "CIMB Bank"
            })

    # -------------------------------------------------
    # FORCE CLOSING BALANCE = LAST TRANSACTION BALANCE
    # -------------------------------------------------

    if transactions:
        # Sort properly before choosing "last"
        transactions.sort(
            key=lambda x: (x["date"], x["page"], x["row_index"])
        )

        last_tx = transactions[-1]

        transactions.append({
            "date": last_tx["date"],
            "description": "CLOSING BALANCE (FROM LAST TRANSACTION)",
            "ref_no": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": last_tx["balance"],
            "page": last_tx["page"],
            "source_file": source_filename,
            "bank": "CIMB Bank",
            "is_statement_balance": True
        })

    return transactions
