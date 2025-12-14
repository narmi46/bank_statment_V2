# bank_islam.py - Bank Islam (Word-based PDF parser)
import re
from datetime import datetime

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_amount(val):
    try:
        return float(val.replace(",", ""))
    except Exception:
        return 0.0


def format_date(date_raw, year):
    try:
        return datetime.strptime(date_raw, "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        return datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass
    return f"{year}-01-01"


def extract_year(text):
    match = re.search(r"(STATEMENT DATE|TARIKH PENYATA).*(\d{2}/\d{2}/(\d{2,4}))", text)
    if match:
        y = match.group(3)
        return y if len(y) == 4 else str(2000 + int(y))
    return str(datetime.now().year)


# ---------------------------------------------------------
# WORD-BASED PARSER (🔥 THIS ONE WORKS)
# ---------------------------------------------------------

def parse_words(page, year, page_num, source_filename):
    transactions = []

    words = page.extract_words(use_text_flow=True)

    if not words:
        return transactions

    # Group words by row (y-coordinate)
    rows = {}
    for w in words:
        y = round(w["top"], 1)
        rows.setdefault(y, []).append(w)

    # Sort rows top to bottom
    for y in sorted(rows.keys()):
        row_words = sorted(rows[y], key=lambda x: x["x0"])
        row_text = " ".join(w["text"] for w in row_words)

        # Look for transaction rows
        # Example:
        # 31/01/25 0160 PROFIT PAID 2.61 12,292.23
        if re.search(r"\d{2}/\d{2}/\d{2}", row_text) and re.search(r"\d+\.\d{2}", row_text):
            parts = row_text.split()

            date_raw = parts[0]

            amounts = [p for p in parts if re.match(r"[\d,]+\.\d{2}", p)]
            if len(amounts) < 1:
                continue

            credit = clean_amount(amounts[0])
            balance = clean_amount(amounts[1]) if len(amounts) > 1 else None

            # Description = text between code and first amount
            desc_parts = []
            for p in parts[1:]:
                if re.match(r"[\d,]+\.\d{2}", p):
                    break
                if not p.isdigit():
                    desc_parts.append(p)

            transactions.append({
                "date": format_date(date_raw, year),
                "description": " ".join(desc_parts),
                "debit": 0.0,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "source_file": source_filename,
                "bank": "Bank Islam"
            })

    return transactions


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    all_tx = []

    # Detect year from first page text
    first_text = pdf.pages[0].extract_text() or ""
    year = extract_year(first_text)

    for page_num, page in enumerate(pdf.pages, start=1):
        all_tx.extend(parse_words(page, year, page_num, source_filename))

    return all_tx

