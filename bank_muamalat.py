# bank_muamalat.py

import re

DATE_RE = re.compile(r"\d{1,2}/\d{2}/\d{2}")
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d{2})")

def parse_transactions_bank_muamalat(pdf, source_file):
    """
    Bank Muamalat parser using pdfplumber.

    Strategy:
    - Extract words with coordinates
    - Use DATE as anchor
    - Same Y-line = same transaction row
    - Right-most amount = balance
    - Merge SERVICE CHARGE into previous transaction
    """

    transactions = []
    pending_tx = None  # for merging service charges

    for page_num, page in enumerate(pdf.pages, start=1):

        words = page.extract_words(
            use_text_flow=True,
            keep_blank_chars=False
        )

        # sort top → bottom, left → right
        words = sorted(words, key=lambda w: (w["top"], w["x0"]))

        i = 0
        while i < len(words):

            word = words[i]["text"]

            # ------------------------------
            # DATE ANCHOR
            # ------------------------------
            if DATE_RE.fullmatch(word):

                y_ref = words[i]["top"]

                # collect same line
                same_line = [
                    w for w in words
                    if abs(w["top"] - y_ref) <= 2
                ]

                texts = [w["text"] for w in same_line]

                # description = non-numeric, non-date
                description_parts = [
                    t for t in texts
                    if not DATE_RE.fullmatch(t)
                    and not AMOUNT_RE.fullmatch(t)
                ]

                description = " ".join(description_parts).strip()

                # numeric amounts with x
                amounts = [
                    (w["x0"], w["text"])
                    for w in same_line
                    if AMOUNT_RE.fullmatch(w["text"])
                ]

                if not amounts:
                    i += 1
                    continue

                amounts = sorted(amounts, key=lambda x: x[0])

                # right-most = balance
                balance = float(amounts[-1][1].replace(",", ""))
                remaining = amounts[:-1]

                debit = credit = None
                if len(remaining) == 1:
                    debit = float(remaining[0][1].replace(",", ""))
                elif len(remaining) >= 2:
                    debit = float(remaining[0][1].replace(",", ""))
                    credit = float(remaining[1][1].replace(",", ""))

                # ------------------------------
                # SERVICE CHARGE MERGE LOGIC
                # ------------------------------
                if "SERVICE CHARGE" in description.upper() and pending_tx:
                    pending_tx["service_charge"] += debit or 0.10
                    pending_tx["balance"] = balance

                else:
                    tx = {
                        "date": word,
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

    # remove service_charge column if unused
    for tx in transactions:
        if tx.get("service_charge") == 0:
            tx.pop("service_charge", None)

    return transactions
