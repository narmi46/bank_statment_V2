# bank_islam.py - Bank Islam Parser (Table + Text Formats)
import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    # TARIKH PENYATA : 31/01/25
    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{2}/\d{2}/(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if match:
        y = match.group(1)
        return y if len(y) == 4 else str(2000 + int(y))

    # From 01/01/2025
    match = re.search(r'From\s+\d{2}/\d{2}/(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_amount(val):
    if val in (None, "", "-"):
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except ValueError:
        return 0.0


def format_date(date_raw, year):
    if not date_raw:
        return f"{year}-01-01"

    date_raw = str(date_raw).strip()

    # DD/MM/YYYY
    try:
        return datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    # DD/MM/YY
    try:
        return datetime.strptime(date_raw, "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    return f"{year}-01-01"


# ---------------------------------------------------------
# TEXT MODE PARSER (NEW FORMAT)
# ---------------------------------------------------------

def parse_text_transactions(text, year, page_num, source_filename):
    """
    Parse summary-style Bank Islam statements (no tables)
    """
    transactions = []

    # Example line:
    # 31/01/25 0160 PROFIT PAID 2.61 12,292.23
    pattern = re.compile(
        r'(\d{2}/\d{2}/\d{2})\s+\d+\s+(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'
    )

    for match in pattern.finditer(text):
        date_raw, desc, credit_raw, balance_raw = match.groups()

        transactions.append({
            "date": format_date(date_raw, year),
            "description": desc.strip(),
            "debit": 0.0,
            "credit": clean_amount(credit_raw),
            "balance": clean_amount(balance_raw),
            "page": page_num,
            "source_file": source_filename,
            "bank": "Bank Islam"
        })

    return transactions


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    all_transactions = []
    detected_year = None

    # Detect year
    for page in pdf.pages[:2]:
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        page_text = page.extract_text() or ""

        # -------------------------------------------------
        # TABLE MODE (OLD FORMAT)
        # -------------------------------------------------
        if tables:
            for table in tables:
                if not table or len(table) < 2:
                    continue

                for row in table[1:]:
                    if len(row) < 10:
                        continue

                    (
                        no,
                        date_raw,
                        _,
                        _,
                        desc,
                        _,
                        _,
                        debit_raw,
                        credit_raw,
                        balance_raw
                    ) = row[:10]

                    if not date_raw or "Total" in str(no):
                        continue

                    all_transactions.append({
                        "date": format_date(date_raw, detected_year),
                        "description": " ".join(str(desc).split()),
                        "debit": clean_amount(debit_raw),
                        "credit": clean_amount(credit_raw),
                        "balance": clean_amount(balance_raw),
                        "page": page_num,
                        "source_file": source_filename,
                        "bank": "Bank Islam"
                    })

        # -------------------------------------------------
        # TEXT MODE (NEW FORMAT)
        # -------------------------------------------------
        else:
            all_transactions.extend(
                parse_text_transactions(
                    page_text,
                    detected_year,
                    page_num,
                    source_filename
                )
            )

    return all_transactions
