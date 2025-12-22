import re
from datetime import datetime

# ---------------------------------------------------
# Bank Islam Parser (FIXED: recovery from description)
# ---------------------------------------------------
def parse_bank_islam(pdf, source_file):
    transactions = []

    def extract_amount_anywhere(text):
        if not text:
            return None
        s = re.sub(r"\s+", "", str(text))
        m = re.search(r"(-?[\d,]+\.\d{2})", s)
        return float(m.group(1).replace(",", "")) if m else None

    for page_num, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:

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

            # ---------------------------------------------
            # Must contain a valid transaction date
            # ---------------------------------------------
            if not txn_date or not re.search(r"\d{2}/\d{2}/\d{4}", str(txn_date)):
                continue

            try:
                date_str = re.search(r"\d{2}/\d{2}/\d{4}", txn_date).group()
                parsed_date = datetime.strptime(date_str, "%d/%m/%Y").date().isoformat()
            except Exception:
                continue

            # ---------------------------------------------
            # Extract amounts from columns first
            # ---------------------------------------------
            debit = extract_amount_anywhere(debit_raw) or 0.0
            credit = extract_amount_anywhere(credit_raw) or 0.0
            balance = extract_amount_anywhere(balance_raw) or 0.0

            # ---------------------------------------------
            # 🔥 RECOVERY LOGIC (KEY FIX)
            # ---------------------------------------------
            if debit == 0.0 and credit == 0.0:
                recovered_amount = extract_amount_anywhere(description)
                if recovered_amount:
                    desc_upper = str(description).upper()

                    if any(k in desc_upper for k in ["INW", "CR", "CREDIT"]):
                        credit = recovered_amount
                    elif any(k in desc_upper for k in ["DR", "DEBIT", "REVERSE"]):
                        debit = recovered_amount

            # ---------------------------------------------
            # Clean description
            # ---------------------------------------------
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

            # ---------------------------------------------
            # Append transaction
            # ---------------------------------------------
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
