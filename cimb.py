# cimb.py - Standalone CIMB Bank Parser (BANK-GRADE)

import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from CIMB Bank statement.
    Handles both 4-digit (2024) and 2-digit (24) year formats.
    """
    if not text:
        return None

    # Pattern 1: STATEMENT DATE : 30/09/24
    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if match:
        year = match.group(1)
        return year if len(year) == 4 else str(2000 + int(year))

    # Pattern 2: Statement Date: DD/MM/YYYY
    match = re.search(
        r'Statement\s+(?:Date|Period)[:\s]+\d{1,2}/\d{1,2}/(\d{4})',
        text,
        re.IGNORECASE
    )
    if match:
        return match.group(1)

    # Pattern 3: FOR THE PERIOD : DD/MM/YYYY
    match = re.search(
        r'FOR\s+THE\s+PERIOD[:\s]+\d{1,2}/\d{1,2}/(\d{4})',
        text,
        re.IGNORECASE
    )
    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------
# CLOSING BALANCE EXTRACTION (AUTHORITATIVE)
# ---------------------------------------------------------

def extract_closing_balance_from_text(text):
    """
    Extracts CIMB closing balance (Baki Penutup).
    Example:
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
    """Converts string '1,234.56' to float."""
    if not value:
        return 0.0

    clean = str(value).replace(",", "").replace(" ", "").replace("\n", "")
    if not re.match(r'^-?\d+(\.\d+)?$', clean):
        return 0.0

    return float(clean)


def clean_text(text):
    """Normalize description text."""
    if not text:
        return ""
    return text.replace("\n", " ").strip()


def format_date(date_str, year):
    """Convert CIMB date to YYYY-MM-DD."""
    if not date_str:
        return f"{year}-01-01"

    date_str = clean_text(date_str)

    # DD/MM/YYYY
    m = re.match(r'(\d{2})/(\d{2})/(\d{4})', date_str)
    if m:
        d, mth, y = m.groups()
        return f"{y}-{mth}-{d}"

    # DD/MM
    m = re.match(r'(\d{2})/(\d{2})', date_str)
    if m:
        d, mth = m.groups()
        return f"{year}-{mth}-{d}"

    return f"{year}-01-01"


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_transactions_cimb(pdf, source_filename=""):
    """
    Parses CIMB Bank statements safely.
    Returns list of transaction dictionaries.
    """
    transactions = []
    detected_year = None
    closing_balance = None

    # --- Scan first pages for year & closing balance ---
    for page in pdf.pages[:3]:
        text = page.extract_text() or ""

        if not detected_year:
            detected_year = extract_year_from_text(text)

        if closing_balance is None:
            closing_balance = extract_closing_balance_from_text(text)

        if detected_year and closing_balance is not None:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    # --- Parse transactions ---
    for page_no, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:
            if not row or len(row) < 6:
                continue

            # Skip headers
            if row[0] and str(row[0]).lower() in ("date", "tarikh"):
                continue

            desc = clean_text(row[1]).lower()

            # Opening balance
            if "opening balance" in desc:
                transactions.append({
                    "date": "",
                    "description": "OPENING BALANCE",
                    "ref_no": "",
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": parse_float(row[5]),
                    "page": page_no,
                    "source_file": source_filename,
                    "bank": "CIMB Bank"
                })
                continue

            balance = parse_float(row[5])
            if balance == 0.0:
                continue

            debit = parse_float(row[3])
            credit = parse_float(row[4])

            if debit == 0.0 and credit == 0.0:
                continue

            transactions.append({
                "date": format_date(row[0], detected_year),
                "description": clean_text(row[1]),
                "ref_no": clean_text(row[2]),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_no,
                "source_file": source_filename,
                "bank": "CIMB Bank"
            })

    # --- Append authoritative closing balance ---
    if closing_balance is not None:
        transactions.append({
            "date": "",
            "description": "CLOSING BALANCE",
            "ref_no": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": closing_balance,
            "page": None,
            "source_file": source_filename,
            "bank": "CIMB Bank",
            "is_statement_balance": True
        })

    return transactions
