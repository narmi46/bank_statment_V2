# bank_islam.py - Bank Islam Universal Parser
import re
from datetime import datetime

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    match = re.search(
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{2}/\d{2}/(\d{2,4})',
        text,
        re.IGNORECASE
    )
    if match:
        y = match.group(1)
        return y if len(y) == 4 else str(2000 + int(y))

    match = re.search(r'From\s+\d{2}/\d{2}/(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def clean_amount(val):
    if val in (None, "", "-"):
        return 0.0
    try:
        return float(str(val).replace(",", "").strip())
    except ValueError:
        return 0.0


def format_date(date_raw, year):
    try:
        return datetime.strptime(date_raw, "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        return datetime.strptime(date_raw, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    return f"{year}-01-01"


# ---------------------------------------------------------
# TOKEN-BASED TEXT PARSER (🔥 THIS FIXES IT)
# ---------------------------------------------------------

def parse_text_tokens(text, year, page_num, source_filename):
    """
    Parse extremely broken Bank Islam PDFs using token stream logic
    """
    transactions = []

    # Split ALL tokens (not lines)
    tokens = re.split(r"\s+", text)

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Detect date token
        if re.match(r"\d{2}/\d{2}/\d{2}", token):
            date_raw = token

            description_parts = []
            credit = None
            balance = None

            j = i + 1

            # Skip numeric codes (0160, etc.)
            while j < len(tokens) and tokens[j].isdigit():
                j += 1

            # Collect description until we hit a money value
            while j < len(tokens):
                if re.match(r"[\d,]+\.\d{2}", tokens[j]):
                    credit = clean_amount(tokens[j])
                    break
                description_parts.append(tokens[j])
                j += 1

            # Next money token = balance
            if credit is not None and j + 1 < len(tokens):
                if re.match(r"[\d,]+\.\d{2}", tokens[j + 1]):
                    balance = clean_amount(tokens[j + 1])

            transactions.append({
                "date": format_date(date_raw, year),
                "description": " ".join(description_parts).strip(),
                "debit": 0.0,
                "credit": credit or 0.0,
                "balance": balance,
                "page": page_num,
                "source_file": source_filename,
                "bank": "Bank Islam"
            })

            i = j + 2
        else:
            i += 1

    return transactions


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    all_transactions = []
    detected_year = None

    # Detect year
    for page in pdf.pages[:2]:
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break

    if not detected_year:
        detected_year = str(datetime.now().year)

    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        text = page.extract_text() or ""

        # -------------------------------
        # TABLE MODE (OLD FORMAT)
        # -------------------------------
        if tables:
            for table in tables:
                if not table or len(table) < 2:
                    continue

                for row in table[1:]:
                    if len(row) < 10:
                        continue

                    (
                        no,
                        date_raw,
                        _,
                        _,
                        desc,
                        _,
                        _,
                        debit_raw,
                        credit_raw,
                        balance_raw
                    ) = row[:10]

                    if not date_raw or "Total" in str(no):
                        continue

                    all_transactions.append({
                        "date": format_date(date_raw, detected_year),
                        "description": " ".join(str(desc).split()),
                        "debit": clean_amount(debit_raw),
                        "credit": clean_amount(credit_raw),
                        "balance": clean_amount(balance_raw),
                        "page": page_num,
                        "source_file": source_filename,
                        "bank": "Bank Islam"
                    })

        # -------------------------------
        # TOKEN MODE (NEW FORMAT)
        # -------------------------------
        else:
            all_transactions.extend(
                parse_text_tokens(
                    text,
                    detected_year,
                    page_num,
                    source_filename
                )
            )

    return all_transactions
