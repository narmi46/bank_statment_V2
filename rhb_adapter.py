import re

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    bank_name = "RHB Bank"

    for page_idx, page in enumerate(pdf.pages, start=1):

        words = page.extract_words(
            use_text_flow=False,
            keep_blank_chars=False
        )

        if not words:
            continue

        # ---- Column buckets (based on visual alignment)
        rows = {}

        for w in words:
            y = round(w["top"], 1)  # group by row height
            rows.setdefault(y, []).append(w)

        for y in sorted(rows.keys()):
            row_words = sorted(rows[y], key=lambda x: x["x0"])
            row_text = " ".join(w["text"] for w in row_words)

            # Detect transaction start by date
            if not re.match(r"^\d{2}\s[A-Za-z]{3}", row_text):
                continue

            # Extract amounts
            amounts = re.findall(r"[\d,]+\.\d{2}", row_text)

            debit = credit = balance = 0.0

            if len(amounts) == 2:
                credit = float(amounts[0].replace(",", ""))
                balance = float(amounts[1].replace(",", ""))
            elif len(amounts) >= 3:
                debit = float(amounts[0].replace(",", ""))
                credit = float(amounts[1].replace(",", ""))
                balance = float(amounts[-1].replace(",", ""))

            # Remove amounts from description
            desc = row_text
            for amt in amounts:
                desc = desc.replace(amt, "")
            desc = desc.strip()

            date_part = desc[:6]
            description = desc[6:].strip()

            transactions.append({
                "date": f"{date_part} 2024",
                "description": description,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_idx,
                "bank": bank_name,
                "source_file": source_file
            })

    return transactions
