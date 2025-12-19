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
    # Default RHB coordinates as fallback if header detection fails
    date_x = (40, 85) 
    debit_x = (330, 410)
    credit_x = (420, 500)
    balance_x = (510, 600)
    
    words = page.extract_words()
    for w in words:
        t = w["text"].lower()
        if t in ("date", "tarikh"):
            date_x = (w["x0"] - 10, w["x1"] + 15)
        elif t == "debit":
            debit_x = (w["x0"] - 15, w["x1"] + 45)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 15, w["x1"] + 45)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 15, w["x1"] + 80)

    return date_x, debit_x, credit_x, balance_x

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # Detect year from statement period header [cite: 6, 130]
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Detect column X positions from the first page 
    date_x, debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words()
        lines_data = {}
        for w in words:
            y = round(w["top"])
            lines_data.setdefault(y, []).append(w)

        for y in sorted(lines_data.keys()):
            line_words = sorted(lines_data[y], key=lambda x: x["x0"])
            line_text = " ".join([w["text"] for w in line_words])

            if is_summary_row(line_text) or any(x in line_text for x in ["Page No", "Statement Period", "Tarikh"]):
                continue

            # COORDINATE DATE DETECTION 
            # Looks for a word in the 'Date' column x-range that is a 1-2 digit number
            date_word = None
            for w in line_words:
                mid_x = (w["x0"] + w["x1"]) / 2
                if date_x[0] <= mid_x <= date_x[1]:
                    if w["text"].isdigit() and len(w["text"]) <= 2:
                        date_word = w
                        break
            
            if date_word:
                if current:
                    transactions.append(current)
                    prev_balance = current["balance"]

                day = date_word["text"]
                # The month is typically the next word in the list 
                idx = line_words.index(date_word)
                mon = line_words[idx+1]["text"] if idx+1 < len(line_words) else "Jan"

                try:
                    tx_date = datetime.datetime.strptime(f"{day}{mon[:3]}{year}", "%d%b%Y").date().isoformat()
                except:
                    tx_date = f"{day} {mon} {year}"

                nums = []
                for w in line_words:
                    clean_num = w["text"].replace(",", "")
                    if num_re.fullmatch(clean_num):
                        nums.append({"val": float(clean_num), "x": w["x0"], "x1": w["x1"]})
                
                nums.sort(key=lambda x: x["x"])
                
                # Logic for RHB: Rightmost is balance, others are Debit or Credit 
                balance = nums[-1]["val"] if nums else None
                debit = credit = 0.0
                
                for n in nums[:-1]:
                    mid = (n["x"] + n["x1"]) / 2
                    if debit_x[0] <= mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x[0] <= mid <= credit_x[1]:
                        credit = n["val"]

                # Arithmetic check to ensure accuracy 
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0: credit, debit = diff, 0.0
                    elif diff < 0: debit, credit = abs(diff), 0.0

                # Extract only Line 1 description 
                # Exclude words that are part of the date or amount
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
                continue

    if current:
        transactions.append(current)

    return transactions
