# bank_islam.py
# Bank Islam – Inclusive, Future-Proof Parser

import re
from datetime import datetime


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_amount(val):
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return None


def format_date(date_raw, year):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return f"{year}-01-01"


def detect_year(text):
    match = re.search(
        r'(STATEMENT DATE|TARIKH PENYATA).*?(\d{2}/\d{2}/(\d{2,4}))',
        text,
        re.IGNORECASE
    )
    if match:
        y = match.group(3)
        return y if len(y) == 4 else str(2000 + int(y))
    return str(datetime.now().year)


# ---------------------------------------------------------
# WORD-BASED ROW RECONSTRUCTION
# ---------------------------------------------------------

def extract_rows_from_words(page):
    """
    Rebuild logical rows using word positions.
    This works on BAD PDFs.
    """
    words = page.extract_words(use_text_flow=True)
    rows = {}

    for w in words:
        y = round(w["top"], 1)
        rows.setdefault(y, []).append(w)

    reconstructed = []
    for y in sorted(rows):
        row = sorted(rows[y], key=lambda x: x["x0"])
        reconstructed.append(" ".join(w["text"] for w in row))

    return reconstructed


# ---------------------------------------------------------
# CLASSIFICATION LOGIC (NO DROPPING)
# ---------------------------------------------------------

def classify_row(text):
    text_upper = text.upper()

    if "BAL B/F" in text_upper:
        return "opening_balance"

    if "SUMMARY" in text_upper or "TOTAL" in text_upper:
        return "summary"

    if any(k in text_upper for k in ["PROFIT", "INTEREST"]):
        return "interest"

    if re.search(r"\d{2}/\d{2}/\d{2}", text):
        return "transaction"

    return "unknown"


# ---------------------------------------------------------
# PARSE A SINGLE ROW
# ---------------------------------------------------------

def parse_row(text, year, page_num, source_filename, method):
    """
    Parse a reconstructed row into a transaction-like dict.
    NEVER returns None — always returns a row.
    """

    row_type = classify_row(text)

    date_match = re.search(r"\d{2}/\d{2}/\d{2,4}", text)
    date = format_date(date_match.group(), year) if date_match else f"{year}-01-01"

    amounts = re.findall(r"[\d,]+\.\d{2}", text)
    amounts = [clean_amount(a) for a in amounts if clean_amount(a) is not None]

    credit = debit = balance = None

    if len(amounts) == 1:
        credit = amounts[0]
    elif len(amounts) >= 2:
        credit = amounts[-2]
        balance = amounts[-1]

    # Description = remove date & amounts
    description = text
    if date_match:
        description = description.replace(date_match.group(), "")
    for a in re.findall(r"[\d,]+\.\d{2}", text):
        description = description.replace(a, "")
    description = " ".join(description.split())

    return {
        "date": date,
        "description": description,
        "debit": debit or 0.0,
        "credit": credit or 0.0,
        "balance": balance,
        "page": page_num,
        "bank": "Bank Islam",
        "source_file": source_filename,

        # 🔑 metadata (this is the key improvement)
        "row_type": row_type,
        "parse_method": method,
        "confidence": "high" if row_type in ("transaction", "interest") else "medium"
    }


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    all_rows = []

    first_page_text = pdf.pages[0].extract_text() or ""
    year = detect_year(first_page_text)

    for page_num, page in enumerate(pdf.pages, start=1):

        # 1️⃣ Try tables (best quality)
        tables = page.extract_tables()
        if tables:
            for table in tables:
                for row in table:
                    row_text = " ".join(str(c) for c in row if c)
                    all_rows.append(
                        parse_row(
                            row_text,
                            year,
                            page_num,
                            source_filename,
                            method="table"
                        )
                    )
            continue

        # 2️⃣ Word-based fallback (bad PDFs)
        rows = extract_rows_from_words(page)
        for r in rows:
            all_rows.append(
                parse_row(
                    r,
                    year,
                    page_num,
                    source_filename,
                    method="word"
                )
            )

    return all_rows
