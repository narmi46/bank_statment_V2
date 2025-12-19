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

def detect_columns(page):
    """
    Dynamically detects column X-ranges. 
    RHB Date is usually around x=45, Debit x=370, Credit x=460, Balance x=550.
    """
    # Default fallback ranges for RHB
    date_x = (30, 95) 
    debit_x = (330, 420)
    credit_x = (425, 510)
    balance_x = (515, 610)
    
    words = page.extract_words()
    for w in words:
        t = w["text"].lower()
        # Anchor on Date header
        if t in ("date", "tarikh"):
            date_x = (w["x0"] - 15, w["x1"] + 25)
        # Anchor on Debit/Credit/Balance headers
        elif t in ("debit", "debil"): # 'debil' handles potential OCR errors in Islamic statement
            debit_x = (w["x0"] - 20, w["x1"] + 50)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 20, w["x1"] + 50)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 20, w["x1"] + 90)

    return date_x, debit_x, credit_x, balance_x

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # Detect year from statement period: "1 Jan 25-31 Jan 25" or "7 Mar 24-31 Mar 24"
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Get coordinate mapping from page 1
    date_x, debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        
        # Group words by vertical 'top' coordinate to form lines
        lines_data = {}
        for w in words:
            y = round(w["top"])
            lines_data.setdefault(y, []).append(w)

        for y in sorted(lines_data.keys()):
            line_words = sorted(lines_data[y], key=lambda x: x["x0"])
            line_text = " ".join([w["text"] for w in line_words])

            # Skip noise and headers
            if is_summary_row(line_text) or any(x in line_text for x in ["Page No", "Statement Period", "Tarikh"]):
                continue

            # 1. Identify Date via Coordinates
            # Looks for a number (Day) in the Date column zone
            date_word = None
            for w in line_words:
                mid_x = (w["x0"] + w["x1"]) / 2
                if date_x[0] <= mid_x <= date_x[1]:
                    # Must be a 1 or 2 digit number (the day)
                    if w["text"].isdigit() and 1 <= len(w["text"]) <= 2:
                        date_word = w
                        break
            
            if date_word:
                # Save the finished transaction from the previous block
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day = date_word["text"]
                # Month is typically the word immediately following the Day
                idx = line_words.index(date_word)
                mon = line_words[idx+1]["text"] if idx+1 < len(line_words) else "Jan"

                try:
                    tx_date = datetime.datetime.strptime(f"{day}{mon[:3]}{year}", "%d%b%Y").date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                # 2. Identify Numbers via Coordinates
                nums = []
                for w in line_words:
                    clean_val = w["text"].replace(",", "")
                    if num_re.fullmatch(clean_val):
                        nums.append({"val": float(clean_val), "x_mid": (w["x0"] + w["x1"]) / 2})
                
                nums.sort(key=lambda x: x["x_mid"])
                
                # In RHB, the rightmost number is always the Balance
                balance = nums[-1]["val"] if nums else None
                debit = credit = 0.0
                
                # Assign remaining numbers to Debit or Credit columns
                for n in nums[:-1]:
                    if debit_x[0] <= n["x_mid"] <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x[0] <= n["x_mid"] <= credit_x[1]:
                        credit = n["val"]

                # 3. Mathematical Cross-Check
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0: 
                        credit, debit = diff, 0.0
                    elif diff < 0: 
                        debit, credit = abs(diff), 0.0

                # 4. Extract First Line Description
                # Exclude Day/Month words and any amount numbers
                desc_parts = [w["text"] for w in line_words if w != date_word and w["text"] != mon]
                final_desc = " ".join([p for p in desc_parts if not num_re.fullmatch(p.replace(",", ""))])

                current = {
                    "date": tx_date,
                    "description": final_desc.strip(),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }
            else:
                # This row has no date in the date column; skip as continuation line
                continue

    # Append final transaction
    if current:
        transactions.append(current)

    return transactions
