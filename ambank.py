import re
import pdfplumber
from datetime import datetime

# ---------------------------------------------------
# Regex (only what we still need)
# ---------------------------------------------------
OPENING_BALANCE_RE = re.compile(
    r"OPENING BALANCE.*?([\d,]+\.\d{2})", re.IGNORECASE
)

STATEMENT_YEAR_RE = re.compile(
    r"STATEMENT DATE.*?\d{2}/\d{2}/(\d{4})", re.IGNORECASE
)

AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")
DATE_RE = re.compile(r"^(\d{2}[A-Za-z]{3})\s+(.*)$")

# ---------------------------------------------------
# Main Parser (REPLACED)
# ---------------------------------------------------
def parse_ambank(pdf_input, source_file: str = ""):
    """
    AmBank statement parser
    - Opening balance from ACCOUNT SUMMARY
    - Debit / Credit derived from balance delta
    - First transaction uses opening balance
    """

    bank_name = "AmBank"
    tx = []

    with pdfplumber.open(pdf_input) as pdf:
        # ---------- READ SUMMARY ----------
        first_page_text = pdf.pages[0].extract_text() or ""

        year_match = STATEMENT_YEAR_RE.search(first_page_text)
        statement_year = int(year_match.group(1)) if year_match else None

        opening_match = OPENING_BALANCE_RE.search(first_page_text)
        if not opening_match:
            raise ValueError("Opening balance not found")

        opening_balance = float(opening_match.group(1).replace(",", ""))
        prev_balance = opening_balance

        # ---------- READ TRANSACTIONS ----------
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            for ln in lines:
                m = DATE_RE.match(ln)
                if not m:
                    continue

                date_raw, rest = m.groups()

                # Ignore Balance B/F
                if re.search(r"balance b/f|baki bawa", rest, re.IGNORECASE):
                    continue

                amounts = AMOUNT_RE.findall(ln)
                if not amounts:
                    continue

                balance = float(amounts[-1].replace(",", ""))

                delta = round(balance - prev_balance, 2)
                debit = credit = 0.0

                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

                # Normalize date
                try:
                    date_norm = datetime.strptime(
                        f"{date_raw}{statement_year}", "%d%b%Y"
                    ).strftime("%Y-%m-%d")
                except Exception:
                    date_norm = date_raw

                description = rest
                description = re.sub(r"\s+[\d,]+\.\d{2}", "", description).strip()

                tx.append({
                    "date": date_norm,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file or ""
                })

                prev_balance = balance

    return tx

