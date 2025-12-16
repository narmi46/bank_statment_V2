import re
import fitz  # PyMuPDF
import os
from datetime import datetime

# -----------------------------
# REGEX
# -----------------------------

# Maybank date formats:
# 01/01/2025 | 01/01 | 01-01 | 01 JAN
DATE_RE = re.compile(
    r"^("
    r"\d{2}/\d{2}/\d{4}|"
    r"\d{2}/\d{2}|"
    r"\d{2}-\d{2}|"
    r"\d{2}\s+[A-Z]{3}"
    r")$",
    re.IGNORECASE
)

YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Money formats:
# 0.10 | .10 | 10.00 | 1,234.56
AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}$")
ZERO_RE = re.compile(r"^0?\.00$")


# -----------------------------
# HELPERS
# -----------------------------

def open_pymupdf(pdf_input):
    """Open PDF safely from file path OR pdfplumber object"""
    if isinstance(pdf_input, str):
        if not os.path.exists(pdf_input):
            raise FileNotFoundError(pdf_input)
        return fitz.open(pdf_input)

    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        data = pdf_input.stream.read()
        if not data:
            raise ValueError("PDF stream empty")
        return fitz.open(stream=data, filetype="pdf")

    raise ValueError("Unsupported PDF input")


def normalize_maybank_date(token, year):
    token = token.upper().strip()

    for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m", "%d %b"):
        try:
            if fmt == "%d/%m/%Y":
                dt = datetime.strptime(token, fmt)
            else:
                dt = datetime.strptime(f"{token}/{year}", fmt + "/%Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass

    return None


def is_amount(text):
    return bool(AMOUNT_RE.match(text)) and not ZERO_RE.match(text)


def to_float(text):
    return float(text.replace(",", ""))


# -----------------------------
# MAIN PARSER
# -----------------------------

def parse_transactions_maybank(pdf_input, source_filename):
    """
    Robust Maybank parser (Muamalat-style)

    - Word-level extraction (PyMuPDF)
    - Date anchor + same Y-line grouping
    - Right-most amount = balance
    - Debit / credit via balance delta
    - ISO date output
    """

    doc = open_pymupdf(pdf_input)

    transactions = []
    seen = set()
    previous_balance = None

    bank_name = "Maybank"
    statement_year = None

    # -------- HEADER SCAN --------
    for p in range(min(2, len(doc))):
        text = doc[p].get_text("text").upper()

        if "MAYBANK ISLAMIC" in text:
            bank_name = "Maybank Islamic"
        elif "MAYBANK" in text:
            bank_name = "Maybank"

        m = YEAR_RE.search(text)
        if m:
            statement_year = m.group(1)
            break

    if not statement_year:
        statement_year = str(datetime.now().year)

    # -------- PAGE LOOP --------
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1

        words = page.get_text("words")
        rows = []

        for w in words:
            x0, y0, x1, y1, text, *_ = w
            text = str(text).strip()
            if not text:
                continue
            rows.append({
                "x0": x0,
                "y0": y0,
                "text": text
            })

        rows.sort(key=lambda r: (round(r["y0"], 1), r["x0"]))

        Y_TOL = 2.0
        i = 0

        while i < len(rows):
            token = rows[i]["text"]

            if not DATE_RE.match(token):
                i += 1
                continue

            iso_date = normalize_maybank_date(token, statement_year)
            if not iso_date:
                i += 1
                continue

            y_ref = rows[i]["y0"]
            same_line = [r for r in rows if abs(r["y0"] - y_ref) <= Y_TOL]
            same_line.sort(key=lambda r: r["x0"])

            desc_parts = []
            amounts = []

            for r in same_line:
                t = r["text"]
                if t == token:
                    continue
                if is_amount(t):
                    amounts.append((r["x0"], t))
                else:
                    desc_parts.append(t)

            if not amounts:
                i += 1
                continue

            amounts.sort(key=lambda x: x[0])

            balance = to_float(amounts[-1][1])
            txn_amount = to_float(amounts[-2][1]) if len(amounts) > 1 else None

            description = " ".join(desc_parts)
            description = " ".join(description.split())[:120]

            # Skip summaries
            if any(k in description.upper() for k in [
                "MONTHLY SUMMARY", "TOTAL", "SUBTOTAL",
                "BALANCE B/F", "BALANCE C/F"
            ]):
                i += 1
                continue

            debit = credit = 0.0

            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = abs(delta)
                elif delta < 0:
                    debit = abs(delta)
                elif txn_amount:
                    debit = txn_amount
            else:
                if txn_amount:
                    debit = txn_amount

            previous_balance = balance

            sig = (iso_date, round(debit, 2), round(credit, 2), round(balance, 2))
            if sig not in seen:
                seen.add(sig)
                transactions.append({
                    "date": iso_date,
                    "description": description or "UNKNOWN",
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_num,
                    "bank": bank_name,
                    "source_file": source_filename
                })

            i += 1

    doc.close()
    return transactions
