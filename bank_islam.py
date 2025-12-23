import re
from datetime import datetime

# =========================================================
# COMMON HELPERS
# =========================================================

DATE_AT_START_RE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\b")
BAL_BF_RE = re.compile(r"BAL\s+B/F", re.IGNORECASE)
MONEY_RE = re.compile(r"[\d,]+\.\d{2}")


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
# FORMAT 1 – TABLE BASED (LEGACY / OPTIONAL)
# =========================================================
def parse_bank_islam_format1(pdf, source_file):
    transactions = []

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

            desc = " ".join(str(x) for x in row[1:] if x)

            transactions.append({
                "date": date,
                "description": desc,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format1_table"
            })

    return transactions


# =========================================================
# FORMAT 2 – TEXT STATEMENT (BALANCE DELTA)
# =========================================================
def parse_bank_islam_format2(pdf, source_file):
    transactions = []
    prev_balance = None

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

        for line in lines:
            upper = line.upper()

            # Opening balance
            if BAL_BF_RE.search(upper):
                nums = MONEY_RE.findall(line)
                if nums:
                    prev_balance = to_float(nums[-1])
                continue

            # Transaction line
            m_date = DATE_AT_START_RE.match(line)
            if not m_date or prev_balance is None:
                continue

            date = parse_date(m_date.group(1))
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

            desc = line[len(m_date.group(1)):].strip()
            for n in nums:
                desc = desc.replace(n, "").strip()

            transactions.append({
                "date": date,
                "description": desc,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format2_balance_delta"
            })

    return transactions


# =========================================================
# FORMAT 3 – eSTATEMENT (BALANCE DELTA, DIFFERENT LAYOUT)
# =========================================================
def parse_bank_islam_format3(pdf, source_file):
    transactions = []
    prev_balance = None

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

        for line in lines:
            upper = line.upper()

            # Opening balance
            if BAL_BF_RE.search(upper):
                nums = MONEY_RE.findall(line)
                if nums:
                    prev_balance = to_float(nums[-1])
                continue

            m_date = DATE_AT_START_RE.match(line)
            if not m_date or prev_balance is None:
                continue

            date = parse_date(m_date.group(1))
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

            desc = line[len(m_date.group(1)):].strip()
            for n in nums:
                desc = desc.replace(n, "").strip()

            transactions.append({
                "date": date,
                "description": desc,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format3_estatement"
            })

    return transactions


# =========================================================
# PUBLIC ENTRY POINT (USED BY app.py)
# =========================================================
def parse_bank_islam(pdf, source_file):
    """
    Try all 3 formats, in order.
    This function MUST exist for app.py.
    """

    tx1 = parse_bank_islam_format1(pdf, source_file)
    if tx1:
        return tx1

    tx2 = parse_bank_islam_format2(pdf, source_file)
    if tx2:
        return tx2

    return parse_bank_islam_format3(pdf, source_file)
