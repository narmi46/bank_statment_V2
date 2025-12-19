import re

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    bank_name = "RHB Bank"

    date_regex = re.compile(r"^(\d{2})\s([A-Za-z]{3})")

    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue

        lines = [l.strip() for l in text.split("\n") if l.strip()]

        current_tx = None

        for line in lines:

            # Skip noise
            if any(x in line for x in [
                "ACCOUNT ACTIVITY", "ORDINARY CURRENT ACCOUNT",
                "Date", "Tarikh", "Debit", "Credit", "Balance",
                "B/F BALANCE", "C/F BALANCE", "Total Count"
            ]):
                continue

            date_match = date_regex.match(line)

            # --------------------------------------------------
            # NEW TRANSACTION LINE
            # --------------------------------------------------
            if date_match:
                # Save previous transaction
                if current_tx:
                    transactions.append(current_tx)

                parts = line.split()

                day = parts[0]
                month = parts[1]
                date_str = f"{day} {month} 2024"  # statement year

                # Extract numbers from right
                amounts = re.findall(r"[\d,]+\.\d{2}", line)

                debit = credit = balance = 0.0

                if len(amounts) == 1:
                    balance = float(amounts[0].replace(",", ""))
                elif len(amounts) == 2:
                    credit = float(amounts[0].replace(",", ""))
                    balance = float(amounts[1].replace(",", ""))
                elif len(amounts) >= 3:
                    debit = float(amounts[0].replace(",", ""))
                    credit = float(amounts[1].replace(",", ""))
                    balance = float(amounts[-1].replace(",", ""))

                # Remove amounts from description
                desc = line
                for amt in amounts:
                    desc = desc.replace(amt, "")
                desc = desc.replace(day, "").replace(month, "").strip()

                current_tx = {
                    "date": date_str,
                    "description": desc,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                }

            # --------------------------------------------------
            # DESCRIPTION CONTINUATION
            # --------------------------------------------------
            else:
                if current_tx:
                    current_tx["description"] += " " + line

        # Save last tx on page
        if current_tx:
            transactions.append(current_tx)

    return transactions
