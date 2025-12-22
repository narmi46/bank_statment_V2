# cimb.py - Standalone CIMB Bank Parser
# Strategy:
# - Transactions: table-based parsing
# - Ending balance: layout/text regex parsing (authoritative)

import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION (layout-based)
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
# CLOSING BALANCE EXTRACTION (layout-based, authoritative)
# ---------------------------------------------------------

def extract_closing_balance_from_text(text):
    """
    Extracts:
    CLOSING BALANCE / BAKI PENUTUP 51.79
    """
    if not text:
        return None

    match = re.search(
        r'CLOSING\s+BALANCE\s*/\s*BAKI\s+PENUTUP\s+([\d,]+\.\d{2})',
        text,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1).replace(",", ""))

    return None


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def parse_float(value):
    if not value:
        return 0.0
    clean = str(value).replace(",", "").replace(" ", "").replace("\n", "")
    if not re.match(r'^-?\d+(\.\d+)?$', clean):
        return 0.0
    return float(clean)


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
    closing_balance = None

    # ---------------------------------------------
    # PASS 1: Layout scan (year + closing balance)
    # ---------------------------------------------
    for page in pdf.pages:
        text = page.extract_text() or ""

        if not detected_year:
            detected_year = extract_year_from_text(text)

        if closing_balance is None:
            closing_balance = extract_closing_balance_from_text(text)

        if detected_year and closing_balance is not None:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    # ---------------------------------------------
    # PASS 2: Table-based transaction parsing
    # ---------------------------------------------
    row_index = 0

    for page_no, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:
            row_index += 1

            if not row or len(row) < 6:
                continue

            # Skip headers
            first_col = str(row[0]).lower() if row[0] else ""
            if "date" in first_col or "tarikh" in first_col:
                continue

            desc_lower = clean_text(row[1]).lower()

            # Skip opening balance rows
            if "opening balance" in desc_lower:
                continue

            debit = parse_float(row[3])
            credit = parse_float(row[4])
            balance = parse_float(row[5])

            # Skip non-transaction spill rows
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
                "row_index": row_index,
                "source_file": source_filename,
                "bank": "CIMB Bank"
            })

    # ---------------------------------------------
    # FINAL: Append authoritative closing balance
    # ---------------------------------------------
    if closing_balance is not None:
        transactions.append({
            "date": "",
            "description": "CLOSING BALANCE / BAKI PENUTUP",
            "ref_no": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": closing_balance,
            "page": None,
            "row_index": None,
            "source_file": source_filename,
            "bank": "CIMB Bank",
            "is_statement_balance": True
        })

    return transactions
