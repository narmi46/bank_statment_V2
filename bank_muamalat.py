# bank_muamalat.py

import re

# ----------------------------
# REGEX (FIXED)
# ----------------------------
DATE_RE = re.compile(r"\d{1,2}/\d{2}/\d{2}")

# Detects:
#  - 0.10
#  - .10
#  - 10.00
#  - 1,234.56
AMOUNT_RE = re.compile(r"(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}")

def parse_transactions_bank_muamalat(pdf, source_file):
    """
    Bank Muamalat parser using pdfplumber.

    Features:
    - Detects 0.XX amounts correctly
    - Uses date as anchor
    - Same Y-line logic
    - Right-most amount = balance
    - Merges SERVICE CHARGE rows
    """

    transactions = []
    pending_tx = None  # for merging service charges

    for page_num, page in enumerate(pdf.pages, start=1):

        words = page.extract_words(
            use_text_flow=True,
            keep_blank_chars=False
        )

        # Sort top → bottom, left → right
        words = sorted(words, key=lambda w: (w["top"], w["x0"]))

        i = 0
        while i < len(words):

            text = words[i]["text"]

            # ----------------------------
            # DATE ANCHOR
            # ----------------------------
            if DATE_RE.fullmatch(text):

                y_ref = words[i]["top"]

                same_line = [
                    w for w in words
                    if abs(w["top"] - y_ref) <= 2
                ]

                texts = [w["text"] for w in same_line]

                # Description = non-date, non-amount
                description_parts = [
                    t for t in texts
                    if not DATE_RE.fullmatch(t)
                    and not AMOUNT_RE.fullmatch(t)
                ]
                description = " ".join(description_parts).strip()

                # Amounts with X position
                amounts = [
                    (w["x0"], w["text"])
                    for w in same_line
                    if AMOUNT_RE.fullmatch(w["text"])
                ]

                if not amounts:
                    i += 1
                    continue

                amounts = sorted(amounts, key=lambda x: x[0])

                # Right-most = balance
                balance = float(amounts[-1][1].replace(",", ""))
                remaining = amounts[:-1]

                debit = credit = None

                if len(remaining) == 1:
                    debit = float(remaining[0][1].replace(",", ""))
                elif len(remaining) >= 2:
                    debit = float(remaining[0][1].replace(",", ""))
                    credit = float(remaining[1][1].replace(",", ""))

                # ----------------------------
                # SERVICE CHARGE MERGE
                # ----------------------------
                if "SERVICE CHARGE" in description.upper() and pending_tx:
                    pending_tx["service_charge"] += debit or 0.0
                    pending_tx["balance"] = balance

                else:
                    tx = {
                        "date": text,
                        "description": description,
                        "debit": debit,
                        "credit": credit,
                        "service_charge": 0.0,
                        "balance": balance,
                        "page": page_num,
                        "bank": "Bank Muamalat",
                        "source_file": source_file
                    }
                    transactions.append(tx)
                    pending_tx = tx

            i += 1

    # Remove service_charge column if unused
    for tx in transactions:
        if tx.get("service_charge") == 0:
            tx.pop("service_charge", None)

    return transactions
