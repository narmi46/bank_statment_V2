import re
import fitz
import pdfplumber
from datetime import datetime
from io import BytesIO


# ======================================================
# Helper: read PDF bytes safely (Streamlit / file / bytes)
# ======================================================
def _read_pdf_bytes(pdf_input):
    if isinstance(pdf_input, (bytes, bytearray)):
        return bytes(pdf_input)

    if hasattr(pdf_input, "stream"):  # Streamlit UploadedFile
        pdf_input.stream.seek(0)
        return pdf_input.stream.read()

    if hasattr(pdf_input, "read"):  # file-like
        pdf_input.seek(0)
        return pdf_input.read()

    with open(pdf_input, "rb") as f:
        return f.read()


# ======================================================
# 1️⃣ RHB ISLAMIC — TEXT BASED
# Date: 01 Jan
# Balance: end of line
# ======================================================
def _parse_rhb_islamic_text(pdf_bytes):
    transactions = []
    previous_balance = None

    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""

        # ---- Safe year detection ----
        year = None
        y1 = re.search(r"\b(20\d{2})\b", header)
        y2 = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2})\b", header)

        if y1:
            year = int(y1.group(1))
        elif y2:
            year = int("20" + y2.group(2))
        else:
            return []  # fail cleanly

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal = balance_re.search(line)
                date = date_re.search(line)

                if not bal or not date:
                    continue

                balance = float(bal.group(1).replace(",", ""))

                if re.search(r"\bB/F\b|\bC/F\b", line):
                    previous_balance = balance
                    continue

                if previous_balance is None:
                    previous_balance = balance
                    continue

                day, month = date.groups()
                date_iso = datetime.strptime(
                    f"{day} {month} {year}", "%d %b %Y"
                ).strftime("%Y-%m-%d")

                delta = balance - previous_balance
                debit = abs(delta) if delta < 0 else 0
                credit = delta if delta > 0 else 0

                desc = line.replace(bal.group(1), "").replace(date.group(0), "")
                desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2)
                })

                previous_balance = balance

    return transactions


# ======================================================
# 2️⃣ RHB CONVENTIONAL — TEXT BASED (NON-REFLEX)
# Date: 01Apr
# ======================================================
def _parse_rhb_conventional_text(pdf_bytes):
    transactions = []
    previous_balance = None

    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""
        ym = re.search(r"[A-Za-z]{3}(\d{2})", header)
        if not ym:
            return []

        year = int("20" + ym.group(1))

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal = balance_re.search(line)
                date = date_re.search(line)

                if not bal or not date:
                    continue

                balance = float(bal.group(1).replace(",", ""))

                if previous_balance is None:
                    previous_balance = balance
                    continue

                day, month = date.groups()
                date_iso = datetime.strptime(
                    f"{day}{month}{year}", "%d%b%Y"
                ).strftime("%Y-%m-%d")

                delta = balance - previous_balance
                debit = abs(delta) if delta < 0 else 0
                credit = delta if delta > 0 else 0

                desc = line.replace(bal.group(1), "").replace(date.group(0), "")
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2)
                })

                previous_balance = balance

    return transactions


# ======================================================
# 3️⃣ RHB REFLEX / CASH MANAGEMENT — LAYOUT BASED
# Date: 05-02-2025
# ======================================================
def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    from rhb_reflex import parse_transactions_rhb
    return parse_transactions_rhb(pdf_bytes, source_filename)


# ======================================================
# 🚦 FINAL ENTRYPOINT (USED BY app.py)
# ======================================================
def parse_transactions_rhb(pdf_input, source_filename=None):
    pdf_bytes = _read_pdf_bytes(pdf_input)

    # Try parsers one by one (INDEPENDENT)
    for parser in (
        _parse_rhb_islamic_text,
        _parse_rhb_conventional_text,
    ):
        tx = parser(pdf_bytes)
        if tx:
            return tx

    # Last resort: Reflex layout parser
    try:
        tx = _parse_rhb_reflex_layout(pdf_bytes, source_filename)
        return tx or []
    except Exception:
        return []
