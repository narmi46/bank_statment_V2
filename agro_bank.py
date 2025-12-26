import re
from datetime import datetime

DATE_RE = re.compile(r"\d{1,2}/\d{2}/\d{2}")
AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}-?")
ZERO_RE = re.compile(r"^0?\.00-?$")


# -------------------------------------------------
# Extract TOTAL DEBIT / TOTAL CREDIT from PDF
# -------------------------------------------------
def extract_agrobank_summary_totals(pdf):
    total_debit = None
    total_credit = None

    # Agrobank summary is always near the end
    for page in reversed(pdf.pages):
        text = page.extract_text() or ""

        for line in text.splitlines():
            u = line.upper()

            if "TOTAL DEBIT" in u:
                m = re.search(r"([\d,]+\.\d{2})", line)
                if m:
                    total_debit = float(m.group(1).replace(",", ""))

            if "TOTAL CREDIT" in u:
                m = re.search(r"([\d,]+\.\d{2})", line)
                if m:
                    total_credit = float(m.group(1).replace(",", ""))

        if total_debit is not None and total_credit is not None:
            break

    return total_debit, total_credit


# -------------------------------------------------
# MAIN PARSER (MANDATED FUNCTION NAME)
# -------------------------------------------------
def parse_agro_bank(pdf, source_file):
    """
    Agrobank statement parser

    Features:
    - Date anchor + same-line grouping
    - Right-most amount = balance
    - Debit / Credit inferred by balance delta
    - Handles trailing '-' debit format
    - Overdraft-safe
    - ISO date output
    - Cross-checks TOTAL DEBIT / TOTAL CREDIT
    - Marks transactions with '#' on mismatch
    """

    transactions = []
    previous_balance = None

    # Extract official summary totals
    summary_debit, summary_credit = extract_agrobank_summary_totals(pdf)

    for page_num, page in enumerate(pdf.pages, start=1):

        words = page.extract_words(
            use_text_flow=True,
            keep_blank_chars=False
        )

        # Visual order: top → bottom, left → right
        words = sorted(words, key=lambda w: (w["top"], w["x0"]))

        i = 0
        while i < len(words):

            text = words[i]["text"]

            # -------------------------
            # DATE ANCHOR
            # -------------------------
            if DATE_RE.fullmatch(text):

                y_ref = words[i]["top"]

                same_line = [
                    w for w in words
                    if abs(w["top"] - y_ref) <= 2
                ]

                # -------------------------
                # DESCRIPTION
                # -------------------------
                description = " ".join(
                    w["text"] for w in same_line
                    if not DATE_RE.fullmatch(w["text"])
                    and not AMOUNT_RE.fullmatch(w["text"])
                    and not ZERO_RE.fullmatch(w["text"])
                ).strip()

                # -------------------------
                # AMOUNTS
                # -------------------------
                amounts = [
                    (w["x0"], w["text"])
                    for w in same_line
                    if AMOUNT_RE.fullmatch(w["text"])
                    and not ZERO_RE.fullmatch(w["text"])
                ]

                if not amounts:
                    i += 1
                    continue

                amounts.sort(key=lambda x: x[0])

                def to_float(val):
                    val = val.replace(",", "")
                    if val.endswith("-"):
                        return -float(val[:-1])
                    return float(val)

                # Agrobank invariant:
                # Right-most amount = balance
                current_balance = to_float(amounts[-1][1])

                txn_amount = None
                if len(amounts) > 1:
                    txn_amount = to_float(amounts[-2][1])

                debit = credit = None

                # -------------------------
                # DEBIT / CREDIT LOGIC
                # -------------------------
                if previous_balance is not None:
                    delta = current_balance - previous_balance

                    if delta > 0.0001:
                        credit = abs(delta)
                    elif delta < -0.0001:
                        debit = abs(delta)
                else:
                    # First row fallback
                    if txn_amount is not None:
                        if txn_amount < 0:
                            debit = abs(txn_amount)
                        else:
                            credit = txn_amount

                # -------------------------
                # ISO DATE OUTPUT
                # -------------------------
                iso_date = datetime.strptime(
                    text, "%d/%m/%y"
                ).strftime("%Y-%m-%d")

                transactions.append({
                    "date": iso_date,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": current_balance,
                    "page": page_num,
                    "bank": "Agrobank",
                    "source_file": source_file
                })

                previous_balance = current_balance

            i += 1

    # -------------------------------------------------
    # SUMMARY VALIDATION
    # -------------------------------------------------
    computed_debit = round(
        sum(t["debit"] or 0 for t in transactions), 2
    )
    computed_credit = round(
        sum(t["credit"] or 0 for t in transactions), 2
    )

    summary_mismatch = False

    if summary_debit is not None:
        if abs(computed_debit - summary_debit) > 0.01:
            summary_mismatch = True

    if summary_credit is not None:
        if abs(computed_credit - summary_credit) > 0.01:
            summary_mismatch = True

    # Mark all rows if mismatch
    for t in transactions:
        t["summary_check"] = "#" if summary_mismatch else ""

    return transactions
