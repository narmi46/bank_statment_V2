import re
import pdfplumber
from datetime import datetime

DATE_RE = re.compile(r"^(\d{2}[A-Za-z]{3})\s+(.*)$")
BALANCE_RE = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})$")

OPENING_BALANCE_RE = re.compile(
    r"OPENING BALANCE.*?([\d,]+\.\d{2})", re.IGNORECASE
)

STATEMENT_YEAR_RE = re.compile(
    r"STATEMENT DATE.*?\d{2}/\d{2}/(\d{4})", re.IGNORECASE
)

def parse_ambank(pdf_input, source_file: str = ""):
    bank_name = "AmBank"
    tx = []

    with pdfplumber.open(pdf_input) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""

        year = int(STATEMENT_YEAR_RE.search(first_page_text).group(1))
        opening_balance = float(
            OPENING_BALANCE_RE.search(first_page_text).group(1).replace(",", "")
        )

        prev_balance = opening_balance

        for page_idx, page in enumerate(pdf.pages, start=1):
            lines = page.extract_text().splitlines()

            for ln in lines:
                ln = ln.strip()
                if not ln:
                    continue

                date_match = DATE_RE.match(ln)
                if not date_match:
                    continue

                date_raw, rest = date_match.groups()

                if re.search(r"balance b/f|baki bawa", rest, re.IGNORECASE):
                    continue

                bal_match = BALANCE_RE.search(ln)
                if not bal_match:
                    continue

                balance = float(bal_match.group(1).replace(",", ""))

                delta = round(balance - prev_balance, 2)
                if delta == 0:
                    continue  # ignore noise

                debit = credit = 0.0
                if delta > 0:
                    credit = delta
                else:
                    debit = abs(delta)

                try:
                    date_norm = datetime.strptime(
                        f"{date_raw}{year}", "%d%b%Y"
                    ).strftime("%Y-%m-%d")
                except Exception:
                    date_norm = date_raw

                description = rest.strip()

                tx.append({
                    "date": date_norm,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                })

                prev_balance = balance

    return tx
