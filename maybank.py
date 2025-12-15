import re
import fitz  # PyMuPDF
from datetime import datetime
import os

def parse_transactions_maybank(pdf_input, source_filename):
    """
    PyMuPDF-only extraction.
    pdf_input can be:
    - pdfplumber PDF object
    - file path string
    """

    # ------------------------------
    # Resolve PDF PATH (critical fix)
    # ------------------------------
    if isinstance(pdf_input, str):
        pdf_path = pdf_input
    else:
        # pdfplumber object → extract real path
        if hasattr(pdf_input, "stream") and hasattr(pdf_input.stream, "name"):
            pdf_path = pdf_input.stream.name
        else:
            raise ValueError("Cannot resolve PDF file path for PyMuPDF")

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # ------------------------------
    # Open with PyMuPDF ONLY
    # ------------------------------
    doc = fitz.open(pdf_path)

    transactions = []
    seen_signatures = set()

    opening_balance = None
    previous_balance = None
    statement_year = None
    bank_name = "Maybank"

    # ------------------------------
    # Iterate pages
    # ------------------------------
    for page_index in range(len(doc)):
        page = doc[page_index]

        # ---- LAYOUT-SAFE EXTRACTION ----
        blocks = page.get_text("blocks")
        blocks = sorted(blocks, key=lambda b: (round(b[1]), round(b[0])))

        lines = []
        for b in blocks:
            text = b[4].strip()
            if text:
                lines.extend(text.split('\n'))

        lines = [l.strip() for l in lines if l.strip()]
        page_num = page_index + 1

        # ------------------------------
        # HEADER
        # ------------------------------
        if page_num == 1:
            for line in lines[:25]:
                up = line.upper()
                if "MAYBANK ISLAMIC" in up:
                    bank_name = "Maybank Islamic"
                elif "MAYBANK" in up:
                    bank_name = "Maybank"

                year_match = re.search(r'20\d{2}', line)
                if year_match:
                    statement_year = year_match.group(0)

        if not statement_year:
            statement_year = "2025"

        # ------------------------------
        # OPENING BALANCE
        # ------------------------------
        if page_num == 1 and opening_balance is None:
            for line in lines:
                if any(k in line.upper() for k in [
                    "OPENING BALANCE",
                    "BEGINNING BALANCE",
                    "BAKI PERMULAAN"
                ]):
                    bal = re.search(r'([\d,]+\.\d{2})', line)
                    if bal:
                        opening_balance = float(bal.group(1).replace(',', ''))
                        previous_balance = opening_balance
                        transactions.append({
                            "date": "",
                            "description": "BEGINNING BALANCE",
                            "debit": 0.00,
                            "credit": 0.00,
                            "balance": round(opening_balance, 2),
                            "page": page_num,
                            "bank": bank_name,
                            "source_file": source_filename
                        })
                    break

        # ------------------------------
        # TRANSACTIONS
        # ------------------------------
        i = 0
        while i < len(lines):
            line = lines[i]

            match = re.match(r'^(\d{2}/\d{2})\s+(.*)', line)
            if not match:
                i += 1
                continue

            date_str, rest = match.groups()
            numbers = re.findall(r'[\d,]+\.\d{2}', rest)
            if not numbers:
                i += 1
                continue

            balance = float(numbers[-1].replace(',', ''))
            description = rest[:rest.find(numbers[0])].strip()

            # multiline description
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if not re.match(r'^\d{2}/\d{2}', nxt):
                    description += " " + nxt
                    i += 1

            description = " ".join(description.split())[:120]

            # date normalize
            try:
                dt = datetime.strptime(f"{date_str}/{statement_year}", "%d/%m/%Y")
                formatted_date = dt.strftime("%Y-%m-%d")
            except:
                formatted_date = date_str

            # skip pure reversals
            if description.upper().startswith("REV "):
                i += 1
                continue

            # debit / credit by balance delta
            debit = credit = 0.00
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            previous_balance = balance

            sig = (formatted_date, debit, credit, balance)
            if sig not in seen_signatures:
                seen_signatures.add(sig)
                transactions.append({
                    "date": formatted_date,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": round(balance, 2),
                    "page": page_num,
                    "bank": bank_name,
                    "source_file": source_filename
                })

            i += 1

    doc.close()
    return transactions
