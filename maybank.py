import re
from datetime import datetime
import fitz  # PyMuPDF

def parse_transactions_maybank(pdf_input, source_filename):
    """
    Accepts:
    - pdfplumber PDF object (backward compatible)
    - file path string (PyMuPDF)
    """

    transactions = []
    seen_signatures = set()

    opening_balance = None
    previous_balance = None
    statement_year = None
    bank_name = "Maybank"

    # ------------------------------
    # Detect input type
    # ------------------------------
    if isinstance(pdf_input, str):
        # PyMuPDF path
        doc = fitz.open(pdf_input)
        pages = [(i + 1, doc[i].get_text("text")) for i in range(len(doc))]
        close_doc = True
    else:
        # Assume pdfplumber PDF object
        pages = [(i + 1, p.extract_text()) for i, p in enumerate(pdf_input.pages)]
        close_doc = False

    # ------------------------------
    # Parse pages
    # ------------------------------
    for page_num, text in pages:
        if not text:
            continue

        lines = [l.strip() for l in text.split('\n') if l.strip()]

        # ---- HEADER ----
        if page_num == 1:
            for line in lines[:20]:
                up = line.upper()
                if 'MAYBANK ISLAMIC' in up:
                    bank_name = "Maybank Islamic"
                elif 'MAYBANK' in up:
                    bank_name = "Maybank"

                year_match = re.search(r'20\d{2}', line)
                if year_match:
                    statement_year = year_match.group(0)

        if not statement_year:
            statement_year = "2025"

        # ---- OPENING BALANCE ----
        if page_num == 1 and opening_balance is None:
            for line in lines:
                if any(k in line.upper() for k in [
                    'OPENING BALANCE',
                    'BEGINNING BALANCE',
                    'BAKI PERMULAAN'
                ]):
                    bal = re.search(r'([\d,]+\.\d{2})', line)
                    if bal:
                        opening_balance = float(bal.group(1).replace(',', ''))
                        previous_balance = opening_balance
                        transactions.append({
                            'date': '',
                            'description': 'BEGINNING BALANCE',
                            'debit': 0.00,
                            'credit': 0.00,
                            'balance': round(opening_balance, 2),
                            'page': page_num,
                            'bank': bank_name,
                            'source_file': source_filename
                        })
                    break

        # ---- TRANSACTIONS ----
        i = 0
        while i < len(lines):
            line = lines[i]

            match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
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

            # Multiline description
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if not re.match(r'^\d{2}/\d{2}', next_line):
                    description += ' ' + next_line
                    i += 1

            description = ' '.join(description.split())[:100]

            # Date
            try:
                dt = datetime.strptime(f"{date_str}/{statement_year}", "%d/%m/%Y")
                formatted_date = dt.strftime("%Y-%m-%d")
            except:
                formatted_date = date_str

            # Safe REV filter
            if description.upper().startswith('REV ') or description.upper() == 'REV':
                i += 1
                continue

            # Debit / Credit by balance delta
            debit = credit = 0.00
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            previous_balance = balance

            txn_signature = (formatted_date, debit, credit, balance)
            if txn_signature not in seen_signatures:
                seen_signatures.add(txn_signature)
                transactions.append({
                    'date': formatted_date,
                    'description': description,
                    'debit': debit,
                    'credit': credit,
                    'balance': round(balance, 2),
                    'page': page_num,
                    'bank': bank_name,
                    'source_file': source_filename
                })

            i += 1

    if close_doc:
        doc.close()

    return transactions
