import regex as re
from datetime import datetime

# ============================================================
# MONTH MAP
# ============================================================

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03",
    "Apr": "04", "May": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09",
    "Oct": "10", "Nov": "11", "Dec": "12"
}

# ============================================================
# GLOBAL STATE (PERSIST ACROSS PAGES)
# ============================================================

_prev_balance = None

# ============================================================
# HELPERS
# ============================================================

def clean_desc(text):
    return " ".join(text.split()) if text else ""

def extract_year_from_text(text):
    m = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2,4})', text)
    if not m:
        return datetime.now().year
    y = m.group(3)
    return int("20" + y if len(y) == 2 else y)

def compute_debit_credit(prev_balance, curr_balance):
    if prev_balance is None:
        return 0.0, 0.0

    diff = round(curr_balance - prev_balance, 2)

    if diff > 0:
        return 0.0, diff
    elif diff < 0:
        return abs(diff), 0.0
    return 0.0, 0.0

def classify_first_tx(desc, amount):
    s = (desc or "").upper()
    if any(k in s for k in ["CR", "CREDIT", "DEPOSIT", "INWARD", "CDT"]):
        return 0.0, amount
    return amount, 0.0

# ============================================================
# REGEX PATTERNS (ALL RHB FORMATS)
# ============================================================

# --- Format A & C (PDF statements) ---
RHB_PDF_TX = re.compile(
    r'^(\d{1,2})\s+'
    r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+'
    r'(.+?)\s+'
    r'(\d{4,20})\s+'
    r'([0-9,]+\.\d{2})\s+'
    r'([0-9,]+\.\d{2})$'
)

# --- B/F & C/F ---
RHB_BF_CF = re.compile(
    r'^\d{1,2}\s+[A-Za-z]{3}\s+(B/F BALANCE|C/F BALANCE)'
)

# --- Internet Banking Export ---
RHB_ONLINE = re.compile(
    r'(\d{2}-\d{2}-\d{4})\s+'
    r'(\d{3})\s+'
    r'(.+?)\s+'
    r'([0-9,]+\.\d{2}|-)\s+'
    r'([0-9,]+\.\d{2}|-)\s+'
    r'([0-9,]+\.\d{2})([+-])'
)

# ============================================================
# LINE PARSER
# ============================================================

def parse_line(line, page_num, year):
    line = line.strip()
    if not line:
        return None

    # Skip BF / CF
    if RHB_BF_CF.match(line):
        return {"type": "skip"}

    # --- PDF FORMAT ---
    m = RHB_PDF_TX.match(line)
    if m:
        day, mon, desc, serial, amt, bal = m.groups()
        return {
            "type": "tx",
            "date": f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}",
            "description": clean_desc(desc),
            "amount": float(amt.replace(",", "")),
            "balance": float(bal.replace(",", "")),
            "page": page_num
        }

    # --- ONLINE FORMAT ---
    m = RHB_ONLINE.search(line)
    if m:
        date_raw, branch, desc, dr, cr, bal, sign = m.groups()
        dd, mm, yyyy = date_raw.split("-")
        bal_val = float(bal.replace(",", ""))
        if sign == "-":
            bal_val = -bal_val

        return {
            "type": "tx",
            "date": f"{yyyy}-{mm}-{dd}",
            "description": clean_desc(f"{branch} {desc}"),
            "amount": (
                float(dr.replace(",", "")) if dr != "-"
                else float(cr.replace(",", "")) if cr != "-"
                else 0.0
            ),
            "balance": bal_val,
            "page": page_num
        }

    return None

# ============================================================
# MAIN PARSER (PAGE BY PAGE)
# ============================================================

def parse_transactions_rhb(pdf, source_file=""):
    global _prev_balance
    _prev_balance = None

    all_tx = []

    # Detect year
    year = None
    for p in pdf.pages[:2]:
        year = extract_year_from_text(p.extract_text() or "")
        if year:
            break
    year = year or datetime.now().year

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        for raw_line in text.splitlines():
            parsed = parse_line(raw_line, page_num, year)
            if not parsed or parsed["type"] == "skip":
                continue

            curr_balance = parsed["balance"]
            amount = parsed["amount"]

            if _prev_balance is None:
                debit, credit = classify_first_tx(parsed["description"], amount)
            else:
                debit, credit = compute_debit_credit(_prev_balance, curr_balance)

            all_tx.append({
                "date": parsed["date"],
                "description": parsed["description"],
                "debit": debit,
                "credit": credit,
                "balance": curr_balance,
                "page": page_num,
                "bank": "RHB Bank",
                "source_file": source_file
            })

            _prev_balance = curr_balance

    return all_tx
