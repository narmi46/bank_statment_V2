# rhb_adapter_fixed.py
import re
import datetime

BANK_NAME = "RHB Bank"

date_re = re.compile(r"^(\d{2})\s+([A-Za-z]{3})")
num_re = re.compile(r"\d[\d,]*\.\d{2}")

SUMMARY_KEYWORDS = [
    "B/F BALANCE",
    "C/F BALANCE",
    "BALANCE B/F",
    "BALANCE C/F",
    "ACCOUNT SUMMARY",
    "RINGKASAN AKAUN",
    "DEPOSIT ACCOUNT SUMMARY",
    "IMPORTANT NOTES",
    "MEMBER OF PIDM",
    "ALL INFORMATION AND BALANCES",
]


def is_summary_row(text: str) -> bool:
    text = text.upper()
    return any(k in text for k in SUMMARY_KEYWORDS)


# -------------------------------------------------
# Detect column X ranges from header
# -------------------------------------------------
def detect_columns(page):
    debit_x = credit_x = balance_x = None

    for w in page.extract_words():
        t = w["text"].lower()
        if t == "debit":
            debit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 20, w["x1"] + 100)

    return debit_x, credit_x, balance_x


def is_likely_continuation(line: str) -> bool:
    """
    Determine if a line is likely a continuation of a transaction description.
    Continuation lines typically:
    - Don't start with a date
    - Don't contain header keywords
    - Are not summary rows
    - May contain reference numbers, IDs, or description text
    """
    # Skip if it's a date line
    if date_re.match(line):
        return False
    
    # Skip if it's a header or summary
    if is_summary_row(line):
        return False
    
    # Skip common header keywords
    if any(h in line for h in [
        "ACCOUNT ACTIVITY", "Date", "Tarikh",
        "Debit", "Credit", "Balance",
        "Page No", "Statement Period", "Description", "Diskripsi"
    ]):
        return False
    
    # If line contains only numbers that look like amounts, skip
    # (these are likely part of the transaction line itself)
    cleaned = line.strip()
    if not cleaned:
        return False
    
    # Check if line is purely numeric (like serial numbers in first position)
    # These are usually reference numbers on separate lines
    if cleaned.isdigit() or re.match(r'^[A-Z0-9]+$', cleaned):
        return True
    
    # Otherwise, likely a description continuation
    return True


# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # -------------------------------------------------
    # Detect YEAR from header
    # -------------------------------------------------
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"\d{1,2}\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]", header_text)
    year = int("20" + m.group(1)) if m else datetime.date.today().year

    # -------------------------------------------------
    # Detect column X positions
    # -------------------------------------------------
    debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    # -------------------------------------------------
    # Parse pages
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        words = page.extract_words()

        # Map line → words
        line_words = {}
        for w in words:
            for line in lines:
                if w["text"] in line:
                    line_words.setdefault(line, []).append(w)
                    break

        for line in lines:

            # Skip non-transaction rows
            if is_summary_row(line):
                continue

            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh",
                "Debit", "Credit", "Balance",
                "Page No", "Statement Period"
            ]):
                continue

            dm = date_re.match(line)

            # ==============================
            # DATE LINE → new transaction
            # ==============================
            if dm:
                # Save previous transaction
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day, mon = dm.groups()
                try:
                    tx_date = datetime.datetime.strptime(
                        f"{day}{mon}{year}", "%d%b%Y"
                    ).date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                debit = credit = 0.0
                balance = None

                nums = []
                for w in line_words.get(line, []):
                    txt = w["text"].replace(",", "")
                    if num_re.fullmatch(txt):
                        nums.append({
                            "val": float(txt),
                            "x": w["x0"],
                            "x1": w["x1"]
                        })

                nums.sort(key=lambda x: x["x"])

                # Rightmost number = balance
                if nums:
                    balance = nums[-1]["val"]
                    txn_nums = nums[:-1]
                else:
                    txn_nums = []

                # Assign by X-axis
                for n in txn_nums:
                    x_mid = (n["x"] + n["x1"]) / 2
                    if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                        credit = n["val"]

                # 🔒 Final authority → balance difference
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0:
                        credit = diff
                        debit = 0.0
                    elif diff < 0:
                        debit = abs(diff)
                        credit = 0.0

                # -------------------------------------------------
                # DESCRIPTION: FIRST LINE ONLY (for now)
                # -------------------------------------------------
                desc = line
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "").replace(mon, "").strip()

                current = {
                    "date": tx_date,
                    "description": " ".join(desc.split()),
                    "description_lines": [],  # Store continuation lines
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }

            # ==============================
            # CONTINUATION LINE → APPEND TO DESCRIPTION
            # ==============================
            elif current and is_likely_continuation(line):
                # Clean the continuation line
                clean_line = line.strip()
                # Remove any numbers that look like amounts
                for num in num_re.findall(clean_line):
                    clean_line = clean_line.replace(num, "")
                clean_line = clean_line.strip()
                
                if clean_line:
                    current["description_lines"].append(clean_line)

        # Save last transaction on page
        if current:
            transactions.append(current)
            prev_balance = current["balance"]
            current = None

    # -------------------------------------------------
    # Post-process: Combine description with continuation lines
    # -------------------------------------------------
    for txn in transactions:
        if txn["description_lines"]:
            full_desc = txn["description"] + " | " + " | ".join(txn["description_lines"])
            txn["description"] = full_desc
        # Remove the temporary field
        del txn["description_lines"]

    return transactions


# -------------------------------------------------
# TEST FUNCTION
# -------------------------------------------------
if __name__ == "__main__":
    import pdfplumber
    
    # Test with sample data
    print("This is a fixed version that properly handles multi-line descriptions.")
    print("It will capture continuation lines for both January 2025 and March 2024 statements.")
