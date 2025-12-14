# bank_islam.py - Standalone Bank Islam Parser (Pandas-safe)
import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from Bank Islam statement.
    Handles both 4-digit (2025) and 2-digit (25) year formats.
    """

    # Pattern 1: STATEMENT DATE : 30/09/25
    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if match:
        year_str = match.group(1)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return str(2000 + int(year_str))

    # Pattern 2: Date 03/04/2025
    match = re.search(r'Date\s+(\d{2}/\d{2}/\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1).split("/")[-1]

    # Pattern 3: From 01/03/2025 To 31/03/2025
    match = re.search(r'From\s+\d{2}/\d{2}/(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def clean_amount(value):
    """Convert string amount to float safely"""
    if value in (None, "", "-"):
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def format_date(date_raw, year):
    """
    ALWAYS return ISO date (YYYY-MM-DD)
    Guaranteed pandas-safe for .dt accessor
    """
    if not date_raw:
        return f"{year}-01-01"

    date_raw = str(date_raw).strip()

    # DD/MM/YYYY
    try:
        return datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    # DD/MM (missing year)
    try:
        return datetime.strptime(f"{date_raw}/{year}", "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Already ISO?
    try:
        return datetime.fromisoformat(date_raw).strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Absolute fallback (never crash app)
    return f"{year}-01-01"


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    """
    Parse Bank Islam PDF statements.
    Returns list of transaction dictionaries.
    """

    all_transactions = []
    detected_year = None

    # Extract year from first few pages
    for page in pdf.pages[:3]:
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break

    # Fallback to current year
    if not detected_year:
        detected_year = str(datetime.now().year)

    # Process pages
    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            if not table or len(table) < 2:
                continue

            # Skip header
            for row in table[1:]:
                if len(row) < 10:
                    continue

                (
                    no,
                    date_raw,
                    eft_no,
                    code,
                    desc,
                    ref_no,
                    branch,
                    debit_raw,
                    credit_raw,
                    balance_raw
                ) = row[:10]

                # Skip totals / invalid rows
                if not date_raw or "Total" in str(no):
                    continue

                date_fmt = format_date(date_raw, detected_year)

                description = " ".join(str(desc).split()) if desc else ""

                debit = clean_amount(debit_raw)
                credit = clean_amount(credit_raw)
                balance = clean_amount(balance_raw)

                all_transactions.append({
                    "date": date_fmt,                  # ✅ ISO date
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_num,
                    "source_file": source_filename,
                    "bank": "Bank Islam"
                })

    return all_transactions
