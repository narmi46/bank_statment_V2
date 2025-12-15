import re
from datetime import datetime

# -----------------------------
# Regex
# -----------------------------
DATE_ISLAMIC = re.compile(r"^\d{2}\s[A-Za-z]{3}\s\d{4}")
DATE_CURRENT = re.compile(r"^\d{2}/\d{2}")

OPENING_BAL = re.compile(r"BEGINNING BALANCE\s*:?\s*([\d,]+\.\d{2})")
STATEMENT_DATE = re.compile(r"STATEMENT DATE\s*:?\s*(\d{2}/\d{2}/\d{2,4})")

AMOUNT_SIGNED = re.compile(r"([\d,]+\.\d{2})([+-])$")
AMOUNT_ISLAMIC = re.compile(r"([\d,]+\.\d{2})\s*([+-])\s*([\d,]+\.\d{2})$")


# -----------------------------
# Main parser
# -----------------------------
def parse_transactions_maybank(pdf, source_file):
    transactions = []
    lines = []

    opening_balance = None
    previous_balance = None
    statement_year = None
    first_tx = True

    # -----------------------------
    # Extract all lines
    # -----------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        for l in text.splitlines():
            lines.append((l.strip(), page_no))

    # -----------------------------
    # Find statement year (for current acct)
    # -----------------------------
    for line, _ in lines:
        m = STATEMENT_DATE.search(line)
        if m:
            dt = datetime.strptime(m.group(1), "%d/%m/%y" if len(m.group(1)) == 8 else "%d/%m/%Y")
            statement_year = dt.year
            break

    # -----------------------------
    # Find opening balance FIRST
    # -----------------------------
    for line, _ in lines:
        m = OPENING_BAL.search(line)
        if m:
            opening_balance = float(m.group(1).replace(",", ""))
            previous_balance = opening_balance
            break

    if opening_balance is None:
        raise ValueError("Opening balance not found")

    current_tx = None

    # -----------------------------
    # Parse transactions
    # -----------------------------
    for line, page_no in lines:

        is_islamic = DATE_ISLAMIC.match(line)
        is_current = DATE_CURRENT.match(line)

        if not (is_islamic or is_current):
            continue

        # Save previous
        if current_tx:
            transactions.append(current_tx)

        # -----------------------------
        # DATE
        # -----------------------------
        if is_islamic:
            date_str = " ".join(line.split()[:3])
            tx_date = datetime.strptime(date_str, "%d %b %Y").strftime("%Y-%m-%d")
            rest = line.replace(date_str, "").strip()

        else:
            date_part = line[:5]  # DD/MM
            if not statement_year:
                raise ValueError("Statement year not found for DD/MM format")
            tx_date = datetime.strptime(
                f"{date_part}/{statement_year}", "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
            rest = line[5:].strip()

        # -----------------------------
        # Amount & balance
        # -----------------------------
        debit = credit = 0.0
        balance = None

        m_islamic = AMOUNT_ISLAMIC.search(line)
        m_signed = AMOUNT_SIGNED.search(line)

        if m_islamic:
            amount = float(m_islamic.group(1).replace(",", ""))
            sign = m_islamic.group(2)
            balance = float(m_islamic.group(3).replace(",", ""))

        elif m_signed:
            amount = float(m_signed.group(1).replace(",", ""))
            sign = m_signed.group(2)
            balance_match = re.search(r"([\d,]+\.\d{2})$", line)
            balance = float(balance_match.group(1).replace(",", "")) if balance_match else None
        else:
            amount = None
            sign = None

        # -----------------------------
        # Description (FIRST LINE ONLY)
        # -----------------------------
        desc = rest
        if amount:
            desc = desc.replace(m_signed.group(0), "").strip() if m_signed else desc
        description = desc

        # -----------------------------
        # Debit / Credit logic
        # -----------------------------
        if first_tx and balance is not None:
            if balance < previous_balance:
                debit = round(previous_balance - balance, 2)
            else:
                credit = round(balance - previous_balance, 2)
            first_tx = False
        else:
            if sign == "-":
                debit = amount
            elif sign == "+":
                credit = amount

        current_tx = {
            "date": tx_date,
            "description": description,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "page": page_no,
            "bank": "Maybank",
            "source_file": source_file
        }

        previous_balance = balance

    if current_tx:
        transactions.append(current_tx)

    return transactions
