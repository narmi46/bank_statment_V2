# rhb_adapter.py
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
    """Check if a line is a summary row that should be skipped."""
    text = text.upper()
    return any(k in text for k in SUMMARY_KEYWORDS)


def is_header_row(line: str) -> bool:
    """Check if a line is a header row that should be skipped."""
    return any(h in line for h in [
        "ACCOUNT ACTIVITY", "AKTIVITI AKAUN",
        "Date", "Tarikh",
        "Debit", "Credit", "Balance",
        "Page No", "Statement Period",
        "Description", "Diskripsi",
        "Cheque", "Serial No"
    ])


def detect_columns(page):
    """
    Detect column X ranges from header to help identify debit/credit/balance positions.
    """
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


def parse_transactions_rhb(pdf, source_file):
    """
    Parse RHB bank statement PDF and extract transactions.
    Only captures the first line of descriptions.
    """
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

        # Map line → words (for X-axis position detection)
        line_words = {}
        for w in words:
            for line in lines:
                if w["text"] in line:
                    line_words.setdefault(line, []).append(w)
                    break

        for line in lines:
            # Skip summary rows
            if is_summary_row(line):
                continue

            # Skip header rows
            if is_header_row(line):
                continue

            dm = date_re.match(line)

            # ==============================
            # DATE LINE → new transaction
            # ==============================
            if dm:
                # Save previous transaction before starting new one
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day, mon = dm.groups()
                
                # Parse date
                try:
                    tx_date = datetime.datetime.strptime(
                        f"{day}{mon}{year}", "%d%b%Y"
                    ).date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                # Initialize amounts
                debit = credit = 0.0
                balance = None

                # Extract all numbers from the line with their X positions
                nums = []
                for w in line_words.get(line, []):
                    txt = w["text"].replace(",", "")
                    if num_re.fullmatch(txt):
                        nums.append({
                            "val": float(txt),
                            "x": w["x0"],
                            "x1": w["x1"]
                        })

                # Sort numbers by X position (left to right)
                nums.sort(key=lambda x: x["x"])

                # Rightmost number is always the balance
                if nums:
                    balance = nums[-1]["val"]
                    txn_nums = nums[:-1]  # Everything except balance
                else:
                    txn_nums = []

                # Assign debit/credit by X-axis position
                for n in txn_nums:
                    x_mid = (n["x"] + n["x1"]) / 2
                    if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                        credit = n["val"]

                # 🔒 FINAL AUTHORITY: Use balance difference to determine debit/credit
                # This overrides the X-axis detection for accuracy
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0:
                        credit = diff
                        debit = 0.0
                    elif diff < 0:
                        debit = abs(diff)
                        credit = 0.0

                # -------------------------------------------------
                # DESCRIPTION: Extract from first line only
                # -------------------------------------------------
                desc = line
                # Remove all numbers
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                # Remove date parts
                desc = desc.replace(day, "").replace(mon, "").strip()
                # Clean up extra spaces
                desc = " ".join(desc.split())

                # Create transaction record
                current = {
                    "date": tx_date,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }

            # ==============================
            # CONTINUATION LINE → Skip (as requested)
            # ==============================
            else:
                # Ignore continuation lines - we only want first line description
                continue

        # Save last transaction on the page
        if current:
            transactions.append(current)
            prev_balance = current["balance"]
            current = None

    return transactions


# -------------------------------------------------
# USAGE EXAMPLE
# -------------------------------------------------
if __name__ == "__main__":
    import pdfplumber
    import json
    
    # Example usage
    pdf_file = "path/to/your/statement.pdf"
    
    with pdfplumber.open(pdf_file) as pdf:
        transactions = parse_transactions_rhb(pdf, pdf_file)
        
        # Print results
        print(f"Found {len(transactions)} transactions")
        print("\nFirst 3 transactions:")
        for txn in transactions[:3]:
            print(json.dumps(txn, indent=2))
