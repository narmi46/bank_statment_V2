import re
from datetime import datetime

# =========================================================
# HELPERS
# =========================================================

MONEY_RE = re.compile(r"[\d,]+\.\d{2}")
DATE_AT_START_RE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\b")
BAL_BF_RE = re.compile(r"BAL\s+B/F", re.IGNORECASE)


def to_float(x):
    return float(x.replace(",", ""))


def parse_date(d):
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(d.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


    # =========================================================
    # FORMAT 1 – TABLE (fallback, unchanged logic)
    # =========================================================
def parse_bank_islam_format1(pdf, source_file):
    tx = []

    for page_num, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:
            if not row or not row[0]:
                continue

            date = parse_date(str(row[0]))
            if not date:
                continue

            debit = to_float(row[2]) if row[2] else 0.0
            credit = to_float(row[3]) if row[3] else 0.0
            balance = to_float(row[4]) if row[4] else None

            tx.append({
                "date": date,
                "description": " ".join(str(x) for x in row[1:] if x),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format1"
            })

    return tx


# =========================================================
# FORMAT 2 – TEXT (BALANCE DELTA)
# =========================================================
def parse_bank_islam_format2(pdf, source_file):
    tx = []
    prev_balance = None

    for page_num, page in enumerate(pdf.pages, start=1):
        lines = (page.extract_text() or "").splitlines()

        for line in lines:
            line = re.sub(r"\s+", " ", line).strip()

            if BAL_BF_RE.search(line):
                nums = MONEY_RE.findall(line)
                if nums:
                    prev_balance = to_float(nums[-1])
                continue

            m = DATE_AT_START_RE.match(line)
            if not m or prev_balance is None:
                continue

            date = parse_date(m.group(1))
            if not date:
                continue

            nums = MONEY_RE.findall(line)
            if not nums:
                continue

            balance = to_float(nums[-1])
            delta = round(balance - prev_balance, 2)

            debit = abs(delta) if delta < 0 else 0.0
            credit = delta if delta > 0 else 0.0
            prev_balance = balance

            desc = line[len(m.group(1)):].strip()
            for n in nums:
                desc = desc.replace(n, "").strip()

            tx.append({
                "date": date,
                "description": desc,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format2"
            })

    return tx


# =========================================================
# FORMAT 3 – eSTATEMENT (BALANCE DELTA)
# =========================================================
def parse_bank_islam_format3(pdf, source_file):
    # identical logic, separate format label
    tx = parse_bank_islam_format2(pdf, source_file)
    for t in tx:
        t["format"] = "format3_estatement"
    return tx


# =========================================================
# PUBLIC ENTRY POINT (USED BY app.py)
# =========================================================
def parse_bank_islam(pdf, source_file):
    """
    This is what app.py imports.
    Order matters.
    """
    tx = parse_bank_islam_format1(pdf, source_file)
    if tx:
        return tx

    tx = parse_bank_islam_format2(pdf, source_file)
    if tx:
        return tx

    return parse_bank_islam_format3(pdf, source_file)
