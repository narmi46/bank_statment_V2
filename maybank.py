import re
from datetime import datetime

# =====================================================
# REGEX
# =====================================================

DATE_ISLAMIC = re.compile(r"^\d{2}\s[A-Za-z]{3}\s\d{4}")
DATE_CURRENT = re.compile(r"^\d{2}/\d{2}")

OPENING_BAL = re.compile(
    r"BEGINNING BALANCE\s*:?\s*([\d,]+\.\d{2})", re.I
)

STATEMENT_MONTH_YEAR = re.compile(
    r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{4})",
    re.I
)

AMOUNT_ISLAMIC = re.compile(
    r"([\d,]+\.\d{2})\s*([+-])\s*([\d,]+\.\d{2})$"
)

AMOUNT_SIGNED = re.compile(
    r"([\d,]+\.\d{2})([+-])"
)

BALANCE_AT_END = re.compile(
    r"([\d,]+\.\d{2})$"
)


# =====================================================
# MAIN PARSER
# =====================================================

def parse_transactions_maybank(pdf, source_file):
    transactions = []
    lines = []

    opening_balance = None
    previous_balance = None
    statement_year = None
    first_tx = True

    # -------------------------------------------------
    # Extract all lines
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                lines.append((line, page_no))

    # -------------------------------------------------
    # Detect STATEMENT YEAR (from document or filename)
    # -------------------------------------------------
    for line, _ in lines:
        m = STATEMENT_MONTH_YEAR.search(line)
        if m:
            statement_year = int(m.group(2))
            break

    if not statement_year:
        m = STATEMENT_MONTH_YEAR.search(source_file)
        if m:
            statement_year = int(m.group(2))

    if not statement_year:
        raise ValueError("Statement year not found")

    # -------------------------------------------------
    # Extract OPENING BALANCE FIRST
    # -------------------------------------------------
    for line, _ in lines:
        m = OPENING_BAL.search(line)
        if m:
            opening_balance = float(m.group(1).replace(",", ""))
            previous_balance = opening_balance
            break

    if opening_balance is None:
        raise ValueError("Opening balance not found")

    current_tx = None

    # -------------------------------------------------
    # Parse TRANSACTIONS
    # -------------------------------------------------
    for line, page_no in lines:

        is_islamic = DATE_ISLAMIC.match(line)
        is_current = DATE_CURRENT.match(line)

        if not (is_islamic or is_current):
            continue

        # Save previous valid transaction
        if current_tx and current_tx["balance"] is not None:
            transactions.append(current_tx)

        # -------------------------------------------------
        # Parse DATE
        # -------------------------------------------------
        if is_islamic:
            date_str = " ".join(line.split()[:3])
            tx_date = datetime.strptime(
                date_str, "%d %b %Y"
            ).strftime("%Y-%m-%d")
            rest = line.replace(date_str, "").strip()

        else:
            # DD/MM format → FORCE statement year
            dd = line[0:2]
            mm = line[3:5]
            tx_date = f"{statement_year}-{mm}-{dd}"
            rest = line[5:].strip()

        # -------------------------------------------------
        # Parse AMOUNT & BALANCE
        # -------------------------------------------------
        debit = credit = 0.0
        amount = None
        sign = None
        balance = None

        m_islamic = AMOUNT_ISLAMIC.search(line)
        m_signed = AMOUNT_SIGNED.search(line)
        m_balance = BALANCE_AT_END.search(line)

        if m_islamic:
            amount = float(m_islamic.group(1).replace(",", ""))
            sign = m_islamic.group(2)
            balance = float(m_islamic.group(3).replace(",", ""))

        elif m_signed and m_balance:
            amount = float(m_signed.group(1).replace(",", ""))
            sign = m_signed.group(2)
            balance = float(m_balance.group(1).replace(",", ""))

        # ❌ Skip invalid / broken lines
        if amount is None or balance is None:
            current_tx = None
            continue

        # -------------------------------------------------
        # CLEAN DESCRIPTION (FIRST LINE ONLY)
        # -------------------------------------------------
        description = rest

        # remove amount+sign
        description = re.sub(r"[\d,]+\.\d{2}[+-]", "", description)

        # remove trailing balance
        description = re.sub(r"[\d,]+\.\d{2}$", "", description)

        description = description.strip()

        # -------------------------------------------------
        # Debit / Credit logic
        # -------------------------------------------------
        if first_tx:
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

    # Append last transaction
    if current_tx and current_tx["balance"] is not None:
        transactions.append(current_tx)

    return transactions
