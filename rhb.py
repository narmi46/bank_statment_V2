import re
import fitz
import pdfplumber
from datetime import datetime
from io import BytesIO


# ======================================================
# Helper: read PDF bytes safely
# ======================================================
def _read_pdf_bytes(pdf_input) -> bytes:
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
# 1️⃣ RHB ISLAMIC (TEXT-BASED)
# ======================================================
def _parse_rhb_islamic_text(pdf_bytes, source_filename):
    transactions = []
    previous_balance = None

    bal_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    year_re = re.compile(r"Statement Period.*?(\d{2})\s*[–-]\s*\d{1,2}\s+\w+\s+(\d{2})")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""
        year = int("20" + re.search(r"\bJan\s+(\d{2})\b", header).group(1))

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal = bal_re.search(line)
                date = date_re.search(line)
                if not bal or not date:
                    continue

                if re.search(r"\bB/F\b|\bC/F\b", line):
                    previous_balance = float(bal.group(1).replace(",", ""))
                    continue

                balance = float(bal.group(1).replace(",", ""))
                day, month = date.groups()
                date_iso = datetime.strptime(
                    f"{day} {month} {year}", "%d %b %Y"
                ).strftime("%Y-%m-%d")

                if previous_balance is None:
                    previous_balance = balance
                    continue

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
                    "balance": round(balance, 2),
                    "page": page_idx + 1,
                    "bank": "RHB Bank",
                    "source_file": source_filename
                })

                previous_balance = balance

    return transactions


# ======================================================
# 2️⃣ RHB CONVENTIONAL (TEXT-BASED, NON-REFLEX)
# ======================================================
def _parse_rhb_conventional_text(pdf_bytes, source_filename):
    # This is basically your extract_rhb_statement_auto logic
    return _parse_rhb_islamic_text(pdf_bytes, source_filename)


# ======================================================
# 3️⃣ RHB REFLEX / CASH MANAGEMENT (LAYOUT-BASED)
# ======================================================
def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    from rhb_reflex import parse_transactions_rhb
    return parse_transactions_rhb(pdf_bytes, source_filename)


# ======================================================
# 🚦 AUTO ROUTER (ONLY ENTRYPOINT)
# ======================================================
def parse_transactions_rhb(pdf_input, source_filename):
    pdf_bytes = _read_pdf_bytes(pdf_input)

    # Detect format using first page text
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = (pdf.pages[0].extract_text() or "").upper()

    # Reflex / Cash Management
    if re.search(r"\d{2}-\d{2}-\d{4}", header):
        return _parse_rhb_reflex_layout(pdf_bytes, source_filename)

    # Islamic
    if "RHB ISLAMIC" in header or "PENYATA AKAUN" in header:
        return _parse_rhb_islamic_text(pdf_bytes, source_filename)

    # Conventional fallback
    return _parse_rhb_conventional_text(pdf_bytes, source_filename)
