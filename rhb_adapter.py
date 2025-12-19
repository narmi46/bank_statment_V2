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
    Detects column X-axis ranges. 
    Standard RHB layout: Date(left), Description(mid-left), Debit/Credit(mid-right), Balance(right).
    """
    # Default fallbacks for RHB statements [cite: 22, 151, 181]
    date_x = (35, 90) 
    debit_x = (340, 420)
    credit_x = (425, 510)
    balance_x = (515, 610)
    
    words = page.extract_words()
    for w in words:
        t = w["text"].lower()
        # Look for headers to refine coordinates
        if t in ("date", "tarikh"):
            date_x = (w["x0"] - 10, w["x1"] + 20)
        elif t in ("debit", "debil"): # Handles OCR typos like 'Debil' [cite: 166, 181]
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

    # Detect year from the Statement Period header [cite: 6, 130]
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Set column maps once based on page 1
    date_lane, debit_lane, credit_lane, balance_lane = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        
        # Group words into physical lines based on 'top' coordinate
        lines_data = {}
        for w in words:
            y = round(w["top"])
            lines_data.setdefault(y, []).append(w)

        for y in sorted(lines_data.keys()):
            line_words = sorted(lines_data[y], key=lambda x: x["x0"])
            line_text = " ".join([w["text"] for w in line_words])

            # Skip common header/footer noise
            if is_summary_row(line_text) or any(x in line_text for x in ["Page No", "Statement Period", "Tarikh", "Diskripsi"]):
                continue

            # 1. DATE DETECTION VIA COORDINATE LANE
            # Find a word in the 'Date' lane that is a 1-2 digit number (the Day)
            date_word = None
            for w in line_words:
                mid_x = (w["x0"] + w["x1"]) / 2
                if date_lane[0] <= mid_x <= date_lane[1]:
                    if w["text"].isdigit() and 1 <= len(w["text"]) <= 2:
                        date_word = w
                        break
            
            if date_word:
                # Save the transaction gathered from the previous iteration
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day = date_word["text"]
                # The Month word follows the Day word 
                idx = line_words.index(date_word)
                mon = line_words[idx+1]["text"] if idx+1 < len(line_words) else "Jan"

                try:
                    tx_date = datetime.datetime.strptime(f"{day}{mon[:3]}{year}", "%d%b%Y").date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                # 2. AMOUNT DETECTION VIA COORDINATE LANES
                nums = []
                for w in line_words:
                    clean_val = w["text"].replace(",", "")
                    if num_re.fullmatch(clean_val):
                        nums.append({"val": float(clean_val), "mid": (w["x0"] + w["x1"]) / 2})
                
                nums.sort(key=lambda x: x["mid"])
                
                # In RHB format, the last number is the Balance [cite: 22, 151, 211]
                balance = nums[-1]["val"] if nums else None
                debit = credit = 0.0
                
                # Check mid-range numbers for Debit or Credit columns
                for n in nums[:-1]:
                    if debit_lane[0] <= n["mid"] <= debit_lane[1]:
                        debit = n["val"]
                    elif credit_lane[0] <= n["mid"] <= credit_lane[1]:
                        credit = n["val"]

                # 3. MATH VALIDATION (Prevents OCR column mis-assignment)
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0: 
                        credit, debit = diff, 0.0
                    elif diff < 0: 
                        debit, credit = abs(diff), 0.0

                # 4. FIRST LINE DESCRIPTION ONLY
                # Collect words that aren't the day, month, or formatted amounts
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
                # No date found in the designated lane; skip this line (continuation line)
                continue

    if current:
        transactions.append(current)

    return transactions
