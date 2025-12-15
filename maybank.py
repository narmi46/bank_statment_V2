import re
from datetime import datetime

# =====================================================
# REGEX DEFINITIONS
# =====================================================

DATE_ISLAMIC = re.compile(r"^\d{2}\s[A-Za-z]{3}\s\d{4}")
DATE_CURRENT = re.compile(r"^\d{2}/\d{2}")

OPENING_BAL = re.compile(r"BEGINNING BALANCE\s*:?\s*([\d,]+\.\d{2})", re.I)

STATEMENT_DATE_NUM = re.compile(
    r"STATEMENT DATE.*?(\d{2}/\d{2}/\d{2,4})", re.I
)

STATEMENT_MONTH_YEAR = re.compile(
    r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{4})",
    re.I
)

AMOUNT_ISLAMIC = re.compile(
    r"([\d,]+\.\d{2})\s*([+-])\s*([\d,]+\.\d{2})$"
)

AMOUNT_SIGNED = re.compile(
    r"([\d,]+\.\d{2})([+-])$"
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
    # Extract all lines from PDF
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        for line in text.splitlines():
            lines.append((line.strip(), page_no))

    # -------------------------------------------------
    # Detect STATEMENT YEAR (3-level fallback)
    # -------------------------------------------------
    # 1️⃣ Numeric statement date
    for line, _ in lines:
        m = STATEMENT_DATE_NUM.search(line)
        if m:
            dt = datetime.strptime(
                m.group(1),
                "%d/%m/%y" if len(m.group(1)) == 8 else "%d/%m/%Y"
            )
            statement_year = dt.year
            break

    # 2️⃣ Month + Year in document
    if not statement_year:
        for line, _ in lines:
            m = STATEMENT_MONTH_YEAR.search(line)
            if m:
                statement_year = int(m.group(2))
                break

    # 3️⃣ Filename fallback
    if not statement_year:
        m = STATEMENT_MONTH_YEAR.search(source_file)
        if m:
            statement_year = int(m.group(2))

    if not statement_year:
        raise ValueError("Statement year not found (date/month/filename)")

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
    # Parse transactions
    # -------------------------------------------------
    for line, page_no in lines:

        is_islamic = DATE_ISLAMIC.match(line)
        is_current = DATE_CURRENT.match(line)

        if not (is_islamic or is_current):
            continue

        # Save previous transaction
        if current_tx:
            transactions.append(current_tx)

        # -------------------------------------------------
        # Parse DATE
        # -------------------------------------------------
        if is_islamic:
            date_str = " ".join(line.split()[:3])
            tx_date = datetime.strptime(date_str, "%d %b %Y").strftime("%Y-%m-%d")
            rest = line.replace(date_str, "").strip()
        else:
            date_part = line[:5]  # DD/MM
            tx_date = datetime.strptime(
                f"{date_part}/{statement_year}", "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
            rest = line[5:].strip()

        # -------------------------------------------------
        # Parse AMOUNT & BALANCE
        # -------------------------------------------------
        debit = credit = 0.0
        balance = None
        amount = None
        sign = None

        m_islamic = AMOUNT_ISLAMIC.search(line)
        m_signed = AMOUNT_SIGNED.search(line)

        if m_islamic:
            amount = float(m_islamic.group(1).replace(",", ""))
            sign = m_islamic.group(2)
            balance = float(m_islamic.group(3).replace(",", ""))

        elif m_signed:
            amount = float(m_signed.group(1).replace(",", ""))
            sign = m_signed.group(2)
            bal_match = re.search(r"([\d,]+\.\d{2})$", line)
            if bal_match:
                balance = float(bal_match.group(1).replace(",", ""))

        # -------------------------------------------------
        # FIRST-LINE DESCRIPTION ONLY
        # -------------------------------------------------
        description = rest
        if m_signed:
            description = description.replace(m_signed.group(0), "").strip()

        # -------------------------------------------------
        # Debit / Credit decision
        # -------------------------------------------------
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
