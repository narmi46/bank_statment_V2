# maybank.py
# Compatible with existing app.py (NO app changes needed)

import re

# ============================================================
# YEAR EXTRACTION
# ============================================================

def extract_year_from_text(text):
    if not text:
        return None

    patterns = [
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        r'\d{1,2}/\d{1,2}/(\d{4})\s*-\s*\d{1,2}/\d{1,2}/\d{4}',
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
        r'(JANUARI|FEBRUARI|MAC|APRIL|MEI|JUN|JULAI|OGOS|SEPTEMBER|OKTOBER|NOVEMBER|DISEMBER)\s+(\d{4})',
    ]

    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            y = m.groups()[-1]
            return str(2000 + int(y)) if len(y) == 2 else y

    return None


# ============================================================
# CLEANER
# ============================================================

def clean_line(line):
    if not line:
        return ""
    for ch in ["\u200b", "\u200e", "\u200f", "\ufeff", "\xa0"]:
        line = line.replace(ch, " ")
    return re.sub(r"\s+", " ", line).strip()


# ============================================================
# REGEX (FIXED: SUPPORTS < RM1)
# ============================================================

AMOUNT = r"((?:\d{1,3}(?:,\d{3})*|\d*)\.\d{2})"

PATTERN_MTASB = re.compile(
    rf"(\d{{2}}/\d{{2}})\s+(.+?)\s+{AMOUNT}\s*([+-])\s*{AMOUNT}"
)

PATTERN_MBB = re.compile(
    rf"(\d{{2}})\s+([A-Za-z]{{3}})\s+(\d{{4}})\s+(.+?)\s+{AMOUNT}\s*([+-])\s*{AMOUNT}"
)

MONTH_MAP = {
    "Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
    "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12",
}


# ============================================================
# BROKEN LINE RECONSTRUCTION
# ============================================================

def reconstruct_lines(lines):
    out, buf = [], ""
    for line in lines:
        line = clean_line(line)
        if not line:
            continue
        if re.match(r"^\d{2}/\d{2}", line) or re.match(r"^\d{2}\s+[A-Za-z]{3}\s+\d{4}", line):
            if buf:
                out.append(buf)
            buf = line
        else:
            buf += " " + line
    if buf:
        out.append(buf)
    return out


# ============================================================
# LINE PARSERS
# ============================================================

def parse_mtasb(line, page, year):
    m = PATTERN_MTASB.search(line)
    if not m:
        return None

    date_raw, desc, amt, sign, bal = m.groups()
    d, mth = date_raw.split("/")

    amount = float(amt.replace(",", ""))
    balance = float(bal.replace(",", ""))

    return {
        "date": f"{year}-{mth}-{d}",
        "description": desc.strip(),
        "debit": amount if sign == "-" else 0.0,
        "credit": amount if sign == "+" else 0.0,
        "balance": balance,
        "page": page,
        "month": int(mth),
    }


def parse_mbb(line, page):
    m = PATTERN_MBB.search(line)
    if not m:
        return None

    d, mon, y, desc, amt, sign, bal = m.groups()
    mth = MONTH_MAP.get(mon.title())
    if not mth:
        return None

    amount = float(amt.replace(",", ""))
    balance = float(bal.replace(",", ""))

    return {
        "date": f"{y}-{mth}-{d}",
        "description": desc.strip(),
        "debit": amount if sign == "-" else 0.0,
        "credit": amount if sign == "+" else 0.0,
        "balance": balance,
        "page": page,
    }


# ============================================================
# MAIN ENTRY (USED BY app.py)
# ============================================================

def parse_transactions_maybank(pdf, source_file=""):
    transactions = []
    year = None

    for p in pdf.pages:
        year = extract_year_from_text(p.extract_text() or "")
        if year:
            break

    if not year:
        raise ValueError("Year not detected")

    year = int(year)
    last_month = None

    for page_num, page in enumerate(pdf.pages, start=1):
        lines = reconstruct_lines((page.extract_text() or "").splitlines())

        for line in lines:
            tx = parse_mtasb(line, page_num, year)
            if tx:
                if last_month and tx["month"] < last_month:
                    year += 1
                last_month = tx["month"]
                tx["date"] = f"{year}-{tx['date'][5:]}"
                tx.pop("month")
            else:
                tx = parse_mbb(line, page_num)

            if tx:
                tx["bank"] = "Maybank"
                tx["source_file"] = source_file
                transactions.append(tx)

    return transactions
