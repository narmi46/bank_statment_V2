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
    Sets coordinate lanes based on standard RHB layouts.
    """
    # Standard RHB coordinates (wide lanes for stability)
    date_lane = (30, 100) 
    debit_lane = (320, 415)
    credit_lane = (420, 510)
    balance_lane = (515, 615)
    
    words = page.extract_words()
    for w in words:
        t = w["text"].lower()
        if t in ("date", "tarikh"):
            date_lane = (w["x0"] - 15, w["x1"] + 30)
        elif t in ("debit", "debil"): # 'debil' handles Islamic OCR 
            debit_lane = (w["x0"] - 25, w["x1"] + 55)
        elif t in ("credit", "kredit"):
            credit_lane = (w["x0"] - 25, w["x1"] + 55)
        elif t in ("balance", "baki"):
            balance_lane = (w["x0"] - 25, w["x1"] + 95)

    return date_lane, debit_lane, credit_lane, balance_lane

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # Detect year from the Statement Period header [cite: 6, 130]
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Set column lanes using Page 1
    date_lane, debit_lane, credit_lane, balance_lane = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        
        # Group words by vertical position
        lines_data = {}
        for w in words:
            y = round(w["top"])
            lines_data.setdefault(y, []).append(w)

        for y in sorted(lines_data.keys()):
            line_words = sorted(lines_data[y], key=lambda x: x["x0"])
            line_text = " ".join([w["text"] for w in line_words])

            # Skip summary rows and table headers 
            if is_summary_row(line_text) or any(x in line_text for x in ["Page No", "Statement Period", "Tarikh", "Diskripsi"]):
                continue

            # 1. Coordinate-Based Date Search
            date_word = None
            for w in line_words:
                mid_x = (w["x0"] + w["x1"]) / 2
                # Look for the day (e.g., '07' or '1') in the left lane 
                if date_lane[0] <= mid_x <= date_lane[1]:
                    if w["text"].isdigit() and 1 <= len(w["text"]) <= 2:
                        date_word = w
                        break
            
            if date_word:
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day = date_word["text"]
                # The month word is immediately following the day
                idx = line_words.index(date_word)
                mon = line_words[idx+1]["text"] if idx+1 < len(line_words) else "Jan"

                try:
                    tx_date = datetime.datetime.strptime(f"{day}{mon[:3]}{year}", "%d%b%Y").date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                # 2. Coordinate-Based Amount Search
                nums = []
                for w in line_words:
                    clean_val = w["text"].replace(",", "")
                    if num_re.fullmatch(clean_val):
                        nums.append({"val": float(clean_val), "mid": (w["x0"] + w["x1"]) / 2})
                
                nums.sort(key=lambda x: x["mid"])
                
                # RHB rightmost column is always balance [cite: 22, 38, 54]
                balance = nums[-1]["val"] if nums else None
                debit = credit = 0.0
                
                for n in nums[:-1]:
                    if debit_lane[0] <= n["mid"] <= debit_lane[1]:
                        debit = n["val"]
                    elif credit_lane[0] <= n["mid"] <= credit_lane[1]:
                        credit = n["val"]

                # 3. Arithmetic Safety Net
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0: 
                        credit, debit = diff, 0.0
                    elif diff < 0: 
                        debit, credit = abs(diff), 0.0

                # 4. Strictly Extract Line 1 Description
                # Filter out the date words and the transaction amounts
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
                # No date in the left lane; this is a continuation line [cite: 38, 166]
                continue

    if current:
        transactions.append(current)

    return transactions
