import re
from datetime import datetime

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    bank_name = "RHB Bank"

    # Example date format: "07 Mar"
    date_pattern = re.compile(r"^(\d{2}\s[A-Za-z]{3})")

    for page_number, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        current_tx = None

        for line in lines:
            # Skip table headers and summaries
            if any(x in line for x in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh", "Debit", "Credit",
                "Balance", "B/F BALANCE", "C/F BALANCE", "Total Count"
            ]):
                continue

            # Check if line starts with a date (new transaction)
            date_match = date_pattern.match(line)

            if date_match:
                # Save previous transaction
                if current_tx:
                    transactions.append(current_tx)

                # Split amounts from right side
                parts = line.split()
                date_str = f"{parts[0]} {parts[1]} 2024"  # assume statement year
                rest = " ".join(parts[2:])

                # Extract amounts (from right)
                amounts = re.findall(r"[\d,]+\.\d{2}", rest)
                debit = credit = balance = None

                if len(amounts) >= 1:
                    balance = amounts[-1].replace(",", "")
                if len(amounts) == 2:
                    credit = amounts[0].replace(",", "")
                if len(amounts) >= 3:
                    debit = amounts[0].replace(",", "")
                    credit = amounts[1].replace(",", "")

                # Clean description
                desc = rest
                for amt in amounts:
                    desc = desc.replace(amt, "")
                desc = desc.strip()

                current_tx = {
                    "date": date_str,
                    "description": desc,
                    "debit": float(debit) if debit else 0.0,
                    "credit": float(credit) if credit else 0.0,
                    "balance": float(balance) if balance else None,
                    "page": page_number,
                    "bank": bank_name,
                    "source_file": source_file
                }

            else:
                # Continuation of description
                if current_tx:
                    current_tx["description"] += " " + line

        # Append last transaction on page
        if current_tx:
            transactions.append(current_tx)

    return transactions
