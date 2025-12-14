# bank_islam.py
# Bank Islam parser using PyMuPDF (fitz)

import fitz  # PyMuPDF
import re
from datetime import datetime


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_amount(val):
    try:
        return float(val.replace(",", ""))
    except Exception:
        return None


def format_date(raw, year):
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return f"{year}-01-01"


def detect_year(text):
    m = re.search(
        r"(STATEMENT DATE|TARIKH PENYATA).*?(\d{2}/\d{2}/(\d{2,4}))",
        text,
        re.IGNORECASE,
    )
    if m:
        y = m.group(3)
        return y if len(y) == 4 else str(2000 + int(y))
    return str(datetime.now().year)


# ---------------------------------------------------------
# WORD-BASED ROW RECONSTRUCTION
# ---------------------------------------------------------

def extract_rows(page):
    """
    Group words by Y coordinate to reconstruct rows
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, text, ...)
    rows = {}

    for x0, y0, x1, y1, text, *_ in words:
        y = round(y0, 1)
        rows.setdefault(y, []).append((x0, text))

    reconstructed = []
    for y in sorted(rows):
        row = " ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0]))
        reconstructed.append(row)

    return reconstructed


# ---------------------------------------------------------
# ROW CLASSIFICATION
# ---------------------------------------------------------

def classify_row(text):
    t = text.upper()

    if "BAL B/F" in t:
        return "opening_balance"
    if "SUMMARY" in t or "TOTAL" in t:
        return "summary"
    if "PROFIT" in t or "INTEREST" in t:
        return "interest"
    if re.search(r"\d{1,2}/\d{1,2}/\d{2}", text):
        return "transaction"

    return "unknown"


# ---------------------------------------------------------
# PARSE ROW
# ---------------------------------------------------------

def parse_row(text, year, page_num, source_file):
    row_type = classify_row(text)

    date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2}", text)
    date = format_date(date_match.group(), year) if date_match else f"{year}-01-01"

    amounts = re.findall(r"[\d,]+\.\d{2}", text)
    amounts = [clean_amount(a) for a in amounts if clean_amount(a) is not None]

    debit = credit = balance = None

    if len(amounts) == 1:
        credit = amounts[0]
    elif len(amounts) >= 2:
        credit = amounts[-2]
        balance = amounts[-1]

    desc = text
    if date_match:
        desc = desc.replace(date_match.group(), "")
    for a in re.findall(r"[\d,]+\.\d{2}", text):
        desc = desc.replace(a, "")
    desc = " ".join(desc.split())

    return {
        "date": date,
        "description": desc,
        "debit": debit or 0.0,
        "credit": credit or 0.0,
        "balance": balance,
        "page": page_num,
        "bank": "Bank Islam",
        "source_file": source_file,

        # metadata (future-proof)
        "row_type": row_type,
        "parse_method": "pymupdf",
        "confidence": "high" if row_type in ("transaction", "interest") else "medium",
    }


# ---------------------------------------------------------
# MAIN ENTRY (called by app.py)
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    """
    pdf argument is ignored — we reopen using PyMuPDF
    """
    doc = fitz.open(stream=pdf.stream.read(), filetype="pdf")
    all_rows = []

    year = detect_year(doc[0].get_text())

    for i, page in enumerate(doc, start=1):
        rows = extract_rows(page)
        for r in rows:
            all_rows.append(parse_row(r, year, i, source_filename))

    return all_rows
