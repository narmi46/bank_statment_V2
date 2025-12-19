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
        "Cheque", "Serial No", "Cek", "Nombor"
    ])


def detect_date_column_x(page):
    """
    Detect the X-coordinate range where dates appear by finding the 'Date' header.
    This helps us identify transaction lines more reliably.
    """
    for w in page.extract_words():
        if w["text"].lower() in ("date", "tarikh"):
            # Date column typically spans from header x0 to x1 + some margin
            return (w["x0"] - 5, w["x1"] + 50)
    return None


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


def is_date_line_by_coordinate(line, line_words, date_x_range):
    """
    Use coordinate-based detection to determine if a line is a transaction date line.
    A date line has text in the date column area that matches the date pattern.
    """
    if not date_x_range:
        # Fallback to regex-only detection
        return date_re.match(line) is not None
    
    # Check if any word in the date column matches the date pattern
    for word in line_words.get(line, []):
        x_mid = (word["x0"] + word["x1"]) / 2
        if date_x_range[0] <= x_mid <= date_x_range[1]:
            # Check if this word or the line starts with a date pattern
            if date_re.match(word["text"]) or date_re.match(line):
                return True
    
    return False


def parse_transactions_rhb(pdf, source_file):
    """
    Parse RHB bank statement PDF and extract transactions.
    Uses coordinate-based date detection for better accuracy.
    Only captures the first line of descriptions.
    """
    transactions = []
    prev_balance = None
    current = None

    # -------------------------------------------------
    # Detect YEAR from header
    # -------------------------------------------------
    header_text = pdf.pages[0].extract_text() or ""
    # Try to find statement period like "1 Jan 25 – 31 Jan 25" or "7 Mar 24 – 31 Mar 24"
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2})\s*[–-]", header_text)
    year = int("20" + m.group(3)) if m else datetime.date.today().year

    # -------------------------------------------------
    # Detect column X positions
    # -------------------------------------------------
    date_x = detect_date_column_x(pdf.pages[0])
    debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    # -------------------------------------------------
    # Parse pages
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        words = page.extract_words()

        # Map line → words (for coordinate-based detection)
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

            # Check if this is a date line using both regex AND coordinates
            is_date_line = False
            dm = date_re.match(line)
            
            if dm:
                # If regex matches, verify with coordinates (if available)
                if date_x:
                    is_date_line = is_date_line_by_coordinate(line, line_words, date_x)
                else:
                    is_date_line = True
            
            # ==============================
            # DATE LINE → new transaction
            # ==============================
            if is_date_line and dm:
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
                    tx_date = f"{year}-{mon}-{day}"

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
                        credit = abs(diff)
                        debit = 0.0
                    elif diff < 0:
                        debit = abs(diff)
                        credit = 0.0
                    else:
                        # No change in balance - keep the amounts we found
                        pass

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
            # CONTINUATION LINE → Skip (only capture first line)
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
    import sys
    
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    else:
        print("Usage: python rhb_adapter.py <path_to_pdf>")
        print("Example: python rhb_adapter.py statement.pdf")
        sys.exit(1)
    
    try:
        with pdfplumber.open(pdf_file) as pdf:
            transactions = parse_transactions_rhb(pdf, pdf_file)
            
            # Print results
            print(f"Found {len(transactions)} transactions\n")
            print("=" * 100)
            
            for i, txn in enumerate(transactions, 1):
                print(f"{i:3d}. {txn['date']} | {txn['description'][:50]:<50} | "
                      f"DR: {txn['debit']:>10.2f} | CR: {txn['credit']:>10.2f} | "
                      f"BAL: {txn['balance']:>10.2f}")
            
            print("=" * 100)
            print(f"\nTotal: {len(transactions)} transactions")
            
            # Optionally save to JSON
            output_file = pdf_file.replace('.pdf', '_transactions.json')
            with open(output_file, 'w') as f:
                json.dump(transactions, f, indent=2)
            print(f"Saved to: {output_file}")
            
    except FileNotFoundError:
        print(f"Error: File '{pdf_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
