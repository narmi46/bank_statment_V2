# maybank.py - Robust Standalone Maybank Parser
import re
from datetime import datetime

# ============================================================
# YEAR EXTRACTION FROM PDF (ROBUST)
# ============================================================

def extract_year_from_text(text):
    """
    Extract year from Maybank statement text.
    Supports English + Malay formats and date ranges.
    """
    if not text:
        return None

    # 1️⃣ STATEMENT DATE : 30/09/24 or 30/09/2024
    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        text,
        re.IGNORECASE,
    )
    if match:
        y = match.group(1)
        return str(2000 + int(y)) if len(y) == 2 else y

    # 2️⃣ STATEMENT PERIOD : 01/08/2024 - 31/08/2024
    match = re.search(
        r'\d{1,2}/\d{1,2}/(\d{4})\s*-\s*\d{1,2}/\d{1,2}/\d{4}',
        text,
    )
    if match:
        return match.group(1)

    # 3️⃣ Statement Date: 30 Sep 2024
    match = re.search(
        r'Statement\s+(?:Date|Period)[:\s]+\d{1,2}\s+[A-Za-z]+\s+(\d{4})',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    # 4️⃣ English month YYYY
    match = re.search(
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(2)

    # 5️⃣ Malay month YYYY
    match = re.search(
        r'(JANUARI|FEBRUARI|MAC|APRIL|MEI|JUN|JULAI|OGOS|SEPTEMBER|OKTOBER|NOVEMBER|DISEMBER)\s+(\d{4})',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(2)

    return None


# ============================================================
# UNIVERSAL CLEANER
# ============================================================

def clean_maybank_line(line):
    if not line:
        return ""

    for ch in ["\u200b", "\u200e", "\u200f", "\ufeff"]:
        line = line.replace(ch, "")
    line = line.replace("\xa0", " ")

    line = re.sub(r"\s+", " ", line)
    return line.strip()


# ============================================================
# REGEX PATTERNS
# ============================================================

PATTERN_MAYBANK_MTASB = re.compile(
    r"(\d{2}/\d{2})\s+"
    r"(.+?)\s+"
    r"([0-9,]+\.\d{2})\s*([+-])\s*"
    r"([0-9,]+\.\d{2})"
)

PATTERN_MAYBANK_MBB = re.compile(
    r"(\d{2})\s+([A-Za-z]{3})\s+(\d{4})\s+"
    r"(.+?)\s+"
    r"([0-9,]+\.\d{2})\s*([+-])\s*"
    r"([0-9,]+\.\d{2})"
)

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


# ============================================================
# PARSERS
# ============================================================

def parse_line_maybank_mtasb(line, page_num, year):
    m = PATTERN_MAYBANK_MTASB.search(line)
    if not m:
        return None

    date_raw, desc, amount_raw, sign, balance_raw = m.groups()
    day, month = date_raw.split("/")

    try:
        amount = float(amount_raw.replace(",", ""))
        balance = float(balance_raw.replace(",", ""))
    except ValueError:
        return None

    return {
        "date": f"{year}-{month}-{day}",
        "description": desc.strip(),
        "debit": amount if sign == "-" else 0.0,
        "credit": amount if sign == "+" else 0.0,
        "balance": balance,
        "page": page_num,
        "month": int(month),
    }


def parse_line_maybank_mbb(line, page_num):
    m = PATTERN_MAYBANK_MBB.search(line)
    if not m:
        return None

    day, mon, year, desc, amount_raw, sign, balance_raw = m.groups()
    month = MONTH_MAP.get(mon.title())
    if not month:
        return None

    try:
        amount = float(amount_raw.replace(",", ""))
        balance = float(balance_raw.replace(",", ""))
    except ValueError:
        return None

    return {
        "date": f"{year}-{month}-{day}",
        "description": desc.strip(),
        "debit": amount if sign == "-" else 0.0,
        "credit": amount if sign == "+" else 0.0,
        "balance": balance,
        "page": page_num,
    }


# ============================================================
# BROKEN LINE RECONSTRUCTION
# ============================================================

def reconstruct_broken_lines(lines):
    rebuilt = []
    buffer = ""

    for line in lines:
        line = clean_maybank_line(line)
        if not line:
            continue

        if re.match(r"^\d{2}/\d{2}", line) or re.match(r"^\d{2}\s+[A-Za-z]{3}\s+\d{4}", line):
            if buffer:
                rebuilt.append(buffer)
            buffer = line
        else:
            buffer += " " + line

    if buffer:
        rebuilt.append(buffer)

    return rebuilt


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def parse_transactions_maybank(pdf, source_filename=""):
    all_transactions = []
    detected_year = None

    # 🔍 Scan ALL pages for year (safe & cheap)
    for page in pdf.pages:
        detected_year = extract_year_from_text(page.extract_text() or "")
        if detected_year:
            break

    if not detected_year:
        raise ValueError("❌ Year could not be detected from Maybank statement")

    current_year = int(detected_year)
    last_month = None

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = reconstruct_broken_lines(text.splitlines())

        for line in lines:
            tx = parse_line_maybank_mtasb(line, page_num, current_year)
            if tx:
                # ✅ Year rollover handling (Dec → Jan)
                if last_month and tx["month"] < last_month:
                    current_year += 1
                last_month = tx["month"]

                tx["date"] = f"{current_year}-{tx['date'][5:]}"
                tx["bank"] = "Maybank"
                tx["source_file"] = source_filename
                tx.pop("month", None)
                all_transactions.append(tx)
                continue

            tx = parse_line_maybank_mbb(line, page_num)
            if tx:
                tx["bank"] = "Maybank"
                tx["source_file"] = source_filename
                all_transactions.append(tx)

    return all_transactions
