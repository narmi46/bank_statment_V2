import re
import datetime

BANK_NAME = "RHB Bank"

# Matches "DD MMM" at the start of a line (e.g., "07 Mar") 
date_re = re.compile(r"^(\d{2})\s+([A-Za-z]{3})")
# Matches currency formatted numbers (e.g., 1,000.00) 
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

def detect_columns(page):
    debit_x = credit_x = balance_x = None
    words = page.extract_words()
    
    for w in words:
        t = w["text"].lower()
        if t == "debit":
            debit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 20, w["x1"] + 100)

    return debit_x, credit_x, balance_x

def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # -------------------------------------------------
    # Robust Year Detection
    # -------------------------------------------------
    header_text = pdf.pages[0].extract_text() or ""
    # Matches 'Mar 24'  or 'Jan 25' [cite: 130] in the statement period
    m = re.search(r"([A-Za-z]{3})\s+(\d{2})[\s\-–]", header_text)
    year = int("20" + m.group(2)) if m else datetime.date.today().year

    # Detect column X positions from the first page
    debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        words = page.extract_words()

        # Map line → words based on vertical alignment
        line_words = {}
        for w in words:
            y_coord = round(w["top"])
            line_words.setdefault(y_coord, []).append(w)

        for line in lines:
            # Skip non-transaction rows [cite: 12, 133]
            if is_summary_row(line):
                continue
            
            # Skip Table Headers 
            if any(h in line for h in ["Date", "Tarikh", "Description", "Diskripsi", "Debit", "Credit", "Balance"]):
                continue

            dm = date_re.match(line)

            # ==============================
            # DATE LINE → New Transaction
            # ==============================
            if dm:
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

                # Find words for the current line to verify column positions
                current_line_words = []
                for y in line_words:
                    line_str = " ".join([w["text"] for w in sorted(line_words[y], key=lambda x: x["x0"])])
                    if line in line_str or line_str in line:
                        current_line_words = line_words[y]
                        break

                nums = []
                for w in current_line_words:
                    txt = w["text"].replace(",", "")
                    if num_re.fullmatch(txt):
                        nums.append({
                            "val": float(txt),
                            "x": w["x0"],
                            "x1": w["x1"]
                        })

                nums.sort(key=lambda x: x["x"])

                if nums:
                    balance = nums[-1]["val"]
                    txn_nums = nums[:-1]
                else:
                    txn_nums = []

                for n in txn_nums:
                    x_mid = (n["x"] + n["x1"]) / 2
                    if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                        credit = n["val"]

                # Arithmetic Validation 
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0:
                        credit, debit = diff, 0.0
                    elif diff < 0:
                        debit, credit = abs(diff), 0.0

                # Extract only the first line of the description 
                desc = line
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "", 1).replace(mon, "", 1).strip()

                current = {
                    "date": tx_date,
                    "description": " ".join(desc.split()),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }

            else:
                # Ignore continuation lines to keep only line 1 of description
                continue

    if current:
        transactions.append(current)

    return transactions
