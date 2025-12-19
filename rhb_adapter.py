import re
import datetime

BANK_NAME = "RHB Bank"

# Matches currency formatted numbers (e.g., 1,000.00)
num_re = re.compile(r"\d[\d,]*\.\d{2}")

SUMMARY_KEYWORDS = [
    "B/F BALANCE", "C/F BALANCE", "BALANCE B/F", "BALANCE C/F",
    "ACCOUNT SUMMARY", "RINGKASAN AKAUN", "DEPOSIT ACCOUNT SUMMARY",
    "IMPORTANT NOTES", "MEMBER OF PIDM", "ALL INFORMATION AND BALANCES",
]

def is_summary_row(text: str) -> bool:
    text = text.upper()
    return any(k in text for k in SUMMARY_KEYWORDS)

# -------------------------------------------------
# Detect X-axis ranges for ALL columns
# -------------------------------------------------
def detect_columns(page):
    date_x = debit_x = credit_x = balance_x = None
    words = page.extract_words()
    
    for w in words:
        t = w["text"].lower()
        # Detect Date Column range 
        if t in ("date", "tarikh"):
            date_x = (w["x0"] - 5, w["x1"] + 10)
        elif t == "debit":
            debit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 20, w["x1"] + 100)

    return date_x, debit_x, credit_x, balance_x

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # Detect year from the statement period [cite: 6, 130]
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Get coordinate mapping from the first page 
    date_x, debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        
        # Group words into physical lines by their 'top' coordinate
        lines_data = {}
        for w in words:
            y = round(w["top"])
            lines_data.setdefault(y, []).append(w)

        # Sort lines from top to bottom
        sorted_y = sorted(lines_data.keys())

        for y in sorted_y:
            line_words = sorted(lines_data[y], key=lambda x: x["x0"])
            line_text = " ".join([w["text"] for w in line_words])

            # Skip headers and summaries [cite: 12, 149]
            if is_summary_row(line_text) or "Page No" in line_text or "Date" in line_text:
                continue

            # -------------------------------------------------
            # COORDINATE DATE DETECTION
            # Check if any word exists in the 'Date' column X-range 
            # -------------------------------------------------
            date_word = None
            for w in line_words:
                if date_x and date_x[0] <= (w["x0"] + w["x1"])/2 <= date_x[1]:
                    # Validate it looks like a day (e.g., "07" or "31") 
                    if w["text"].isdigit() and len(w["text"]) <= 2:
                        date_word = w
                        break
            
            # If we found a day digit in the date column, it's a new transaction
            if date_word:
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                # The month usually follows the day word 
                day = date_word["text"]
                # Heuristic: find the next word to the right for the month
                idx = line_words.index(date_word)
                mon = line_words[idx+1]["text"] if idx+1 < len(line_words) else "Jan"

                try:
                    tx_date = datetime.datetime.strptime(
                        f"{day}{mon[:3]}{year}", "%d%b%Y"
                    ).date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                # Parse numbers based on coordinates
                nums = []
                for w in line_words:
                    txt = w["text"].replace(",", "")
                    if num_re.fullmatch(txt):
                        nums.append({"val": float(txt), "x0": w["x0"], "x1": w["x1"]})

                nums.sort(key=lambda x: x["x0"])
                
                balance = nums[-1]["val"] if nums else None
                debit = credit = 0.0
                
                # Assign Debit/Credit by X-position
                for n in nums[:-1]:
                    mid = (n["x0"] + n["x1"]) / 2
                    if debit_x and debit_x[0] <= mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x and credit_x[0] <= mid <= credit_x[1]:
                        credit = n["val"]

                # Arithmetic cross-check [cite: 13, 134]
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0: credit, debit = diff, 0.0
                    elif diff < 0: debit, credit = abs(diff), 0.0

                # Extract first line description (everything not a date or amount)
                desc_parts = [w["text"] for w in line_words if w != date_word and w["text"] != mon]
                desc = " ".join([p for p in desc_parts if not num_re.fullmatch(p.replace(",", ""))])

                current = {
                    "date": tx_date,
                    "description": desc.strip(),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }
            else:
                # Coordinate didn't match a date; ignore continuation lines 
                continue

    if current:
        transactions.append(current)

    return transactions
