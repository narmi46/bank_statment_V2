import re
import pdfplumber
from datetime import datetime

# ---------------------------------------------------
# Bank Islam Parser
# ---------------------------------------------------
def parse_bank_islam(pdf, source_file):
    transactions = []

    for page_num, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:

            # Safety: normalize row length
            row = list(row) if row else []
            while len(row) < 12:
                row.append(None)

            (
                no,
                txn_date,
                customer_eft,
                txn_code,
                description,
                ref_no,
                branch,
                debit_raw,
                credit_raw,
                balance_raw,
                sender_recipient,
                payment_details,
            ) = row[:12]

            # ---------------------------------------------------
            # Filter valid transaction rows (must contain date)
            # ---------------------------------------------------
            if not txn_date or not re.search(r"\d{2}/\d{2}/\d{4}", str(txn_date)):
                continue

            # ---------------------------------------------------
            # Parse date
            # ---------------------------------------------------
            try:
                date_str = re.search(r"\d{2}/\d{2}/\d{4}", txn_date).group()
                parsed_date = datetime.strptime(date_str, "%d/%m/%Y").date().isoformat()
            except Exception:
                continue

            # ---------------------------------------------------
            # Amount extractor (newline + overdraft safe)
            # ---------------------------------------------------
            def extract_amount(cell):
                if cell is None:
                    return 0.0
                s = re.sub(r"\s+", "", str(cell))  # remove \n and spaces
                m = re.search(r"(-?[\d,]+\.\d{2})", s)
                return float(m.group(1).replace(",", "")) if m else 0.0

            debit = extract_amount(debit_raw)
            credit = extract_amount(credit_raw)
            balance = extract_amount(balance_raw)

            # ---------------------------------------------------
            # Build description (bank-style, robust)
            # ---------------------------------------------------
            desc_parts = [
                str(no) if no else "",
                str(txn_code) if txn_code else "",
                str(description) if description else "",
                str(sender_recipient) if sender_recipient else "",
                str(payment_details) if payment_details else "",
            ]

            description_clean = " ".join(
                p.replace("\n", " ").strip()
                for p in desc_parts
                if p and p.lower() != "nan"
            )

            # ---------------------------------------------------
            # Append transaction
            # ---------------------------------------------------
            transactions.append({
                "date": parsed_date,
                "description": description_clean,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
            })

    return transactions
