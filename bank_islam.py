import re
from datetime import datetime

# =========================================================
# BANK ISLAM – FORMAT 1 (TABLE-BASED)
# =========================================================
def parse_bank_islam_format1(pdf, source_file):
    transactions = []

    def extract_amount(text):
        if not text:
            return None
        s = re.sub(r"\s+", "", str(text))
        m = re.search(r"(-?[\d,]+\.\d{2})", s)
        return float(m.group(1).replace(",", "")) if m else None

    for page_num, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:
            row = list(row) if row else []
            while len(row) < 12:
                row.append(None)

            (
                no, txn_date, customer_eft, txn_code, description,
                ref_no, branch, debit_raw, credit_raw,
                balance_raw, sender_recipient, payment_details
            ) = row[:12]

            if not txn_date or not re.search(r"\d{2}/\d{2}/\d{4}", str(txn_date)):
                continue

            try:
                date = datetime.strptime(
                    re.search(r"\d{2}/\d{2}/\d{4}", txn_date).group(),
                    "%d/%m/%Y"
                ).date().isoformat()
            except Exception:
                continue

            debit = extract_amount(debit_raw) or 0.0
            credit = extract_amount(credit_raw) or 0.0
            balance = extract_amount(balance_raw) or 0.0

            # Recovery from description
            if debit == 0.0 and credit == 0.0:
                recovered = extract_amount(description)
                if recovered:
                    desc = str(description).upper()
                    if "CR" in desc or "CREDIT" in desc or "IN" in desc:
                        credit = recovered
                    else:
                        debit = recovered

            description_clean = " ".join(
                str(x).replace("\n", " ").strip()
                for x in [no, txn_code, description, sender_recipient, payment_details]
                if x and str(x).lower() != "nan"
            )

            transactions.append({
                "date": date,
                "description": description_clean,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format1"
            })

    return transactions


# =========================================================
# BANK ISLAM – FORMAT 2 (TEXT / STATEMENT-BASED)
# =========================================================
AMOUNT_RE = re.compile(r"\(?-?[\d,]+(?:\.\d{1,2})?\)?")
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{2,4})\b")

def _to_float(val):
    if not val:
        return None
    neg = val.startswith("(") and val.endswith(")")
    val = val.strip("()").replace(",", "")
    try:
        num = float(val)
        return -num if neg else num
    except ValueError:
        return None

def parse_bank_islam_format2(pdf, source_file):
    transactions = []

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]

        for line in lines:
            m_date = DATE_RE.search(line)
            if not m_date:
                continue

            try:
                date = datetime.strptime(
                    m_date.group(1),
                    "%d/%m/%y" if len(m_date.group(1)) == 8 else "%d/%m/%Y"
                ).date().isoformat()
            except Exception:
                continue

            amounts_raw = AMOUNT_RE.findall(line)
            amounts = [_to_float(a) for a in amounts_raw if _to_float(a) is not None]

            if not amounts:
                continue

            if len(amounts) >= 2:
                amount = amounts[-2]
                balance = amounts[-1]
            else:
                amount = amounts[-1]
                balance = 0.0

            desc = line.replace(m_date.group(1), "")
            for a in amounts_raw[-2:]:
                desc = desc.replace(a, "")
            desc = desc.strip()

            desc_upper = desc.upper()
            debit = credit = 0.0

            if amount < 0:
                debit = abs(amount)
            elif any(k in desc_upper for k in ["PROFIT", "CR", "CREDIT", "IN"]):
                credit = amount
            else:
                debit = amount

            transactions.append({
                "date": date,
                "description": desc,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
                "format": "format2"
            })

    return transactions


# =========================================================
# WRAPPER (USED BY app.py)
# =========================================================
def parse_bank_islam(pdf, source_file):
    """
    Try FORMAT 1 first (table).
    If nothing extracted, fallback to FORMAT 2 (text).
    """
    tx = parse_bank_islam_format1(pdf, source_file)
    if tx:
        return tx

    return parse_bank_islam_format2(pdf, source_file)
