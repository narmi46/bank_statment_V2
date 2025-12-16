# bank_muamalat.py

import re

DATE_RE = re.compile(r"\d{1,2}/\d{2}/\d{2}")

# Matches:
#  .10 | 0.10 | 10.00 | 1,234.56
AMOUNT_RE = re.compile(r"(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}")

ZERO_RE = re.compile(r"^0?\.00$")


def parse_transactions_bank_muamalat(pdf, source_file):
    """
    Correct Bank Muamalat parser (pdfplumber).

    FIXES:
    - Correct debit vs credit detection
    - Ignores .00 filler values
    - Handles 0.xx charges
    - Right-most amount = balance
    """

    transactions = []

    for page_num, page in enumerate(pdf.pages, start=1):

        words = page.extract_words(
            use_text_flow=True,
            keep_blank_chars=False
        )

        # Sort visually
        words = sorted(words, key=lambda w: (w["top"], w["x0"]))

        i = 0
        while i < len(words):

            text = words[i]["text"]

            # --------------------
            # DATE ANCHOR
            # --------------------
            if DATE_RE.fullmatch(text):

                y_ref = words[i]["top"]

                same_line = [
                    w for w in words
                    if abs(w["top"] - y_ref) <= 2
                ]

                texts = [w["text"] for w in same_line]

                description = " ".join(
                    t for t in texts
                    if not DATE_RE.fullmatch(t)
                    and not AMOUNT_RE.fullmatch(t)
                    and not ZERO_RE.fullmatch(t)
                ).strip()

                # Extract numeric amounts with x position
                amounts = [
                    (w["x0"], w["text"])
                    for w in same_line
                    if AMOUNT_RE.fullmatch(w["text"])
                    and not ZERO_RE.fullmatch(w["text"])
                ]

                if not amounts:
                    i += 1
                    continue

                amounts = sorted(amounts, key=lambda x: x[0])

                # --------------------
                # BALANCE (right-most)
                # --------------------
                balance = float(amounts[-1][1].replace(",", ""))
                txn_amounts = amounts[:-1]

                debit = credit = None

                if txn_amounts:
                    txn_value = float(txn_amounts[-1][1].replace(",", ""))

                    desc_upper = description.upper()

                    # --------------------
                    # CREDIT DETECTION
                    # --------------------
                    if (
                        desc_upper.startswith("CR")
                        or "PROFIT PAID" in desc_upper
                    ):
                        credit = txn_value
                    else:
                        debit = txn_value

                transactions.append({
                    "date": text,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_num,
                    "bank": "Bank Muamalat",
                    "source_file": source_file
                })

            i += 1

    return transactions
