# rhb_adapter.py
import re
import datetime

BANK_NAME = "RHB Bank"

# ---------------------------
# Regex
# ---------------------------
date_re = re.compile(r"^(\d{2})\s*([A-Za-z]{3})")  # 11Mar or 11 Mar
num_re = re.compile(r"\d[\d,]*\.\d{2}")

SUMMARY_KEYWORDS = [
    "B/F BALANCE",
    "C/F BALANCE",
    "BALANCE B/F",
    "BALANCE C/F",
    "ACCOUNT SUMMARY",
    "RINGKASAN AKAUN",
    "DEPOSIT ACCOUNT SUMMARY",
    "IMPORTANT NOTES",
    "MEMBER OF PIDM",
    "ALL INFORMATION AND BALANCES",
]


def is_summary_row(text: str) -> bool:
    return any(k in text.upper() for k in SUMMARY_KEYWORDS)


# -------------------------------------------------
# Detect column X ranges (wide)
# -------------------------------------------------
def detect_columns(page):
    debit_x = credit_x = balance_x = None

    for w in page.extract_words():
        t = w["text"].lower()

        if t == "debit":
            debit_x = (w["x0"] - 80, w["x1"] + 140)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 80, w["x1"] + 140)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 120, w["x1"] + 260)

    return debit_x, credit_x, balance_x


# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None
    first_tx = True  # 🔑 key flag

    # -------------------------------------------------
    # Detect YEAR (spaced & glued)
    # -------------------------------------------------
    header_text = pdf.pages[0].extract_text() or ""

    m = re.search(r"\d{1,2}\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]", header_text)
    if not m:
        m = re.search(r"[A-Za-z]{3}(\d{2})", header_text)

    year = int("20" + m.group(1)) if m else datetime.date.today().year

    # -------------------------------------------------
    # Parse pages
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
        debit_x, credit_x, balance_x = detect_columns(page)

        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        words = page.extract_words()

        # Map line → words
        line_words = {}
        for w in words:
            for line in lines:
                if w["text"] in line:
                    line_words.setdefault(line, []).append(w)
                    break

        for line in lines:

            # Skip summaries & headers
            if is_summary_row(line):
                continue

            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh",
                "Debit", "Credit", "Balance",
                "Page No", "Statement Period"
            ]):
                continue

            dm = date_re.match(line)
            if not dm:
                continue

            # Skip B/F and C/F
            up = line.upper()
            if "B/F" in up or "C/F" in up:
                continue

            if current:
                transactions.append(current)
                prev_balance = current["balance"]

            day, mon = dm.groups()

            try:
                tx_date = datetime.datetime.strptime(
                    f"{day}{mon}{year}", "%d%b%Y"
                ).date().isoformat()
            except Exception:
                tx_date = f"{day} {mon} {year}"

            debit = credit = 0.0
            balance = None

            nums = []
            for w in line_words.get(line, []):
                txt = w["text"].replace(",", "")
                if num_re.fullmatch(txt):
                    x_mid = (w["x0"] + w["x1"]) / 2
                    nums.append((float(txt), x_mid))

            # -------------------------------------------------
            # FIRST TRANSACTION → USE COORDINATES
            # -------------------------------------------------
            if first_tx:
                for val, x_mid in nums:
                    if balance_x and balance_x[0] <= x_mid <= balance_x[1]:
                        balance = val
                    elif debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                        debit = val
                    elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                        credit = val

                first_tx = False

            # -------------------------------------------------
            # ALL OTHER TRANSACTIONS → USE BALANCE DIFF ONLY
            # -------------------------------------------------
            else:
                # extract balance only (rightmost in range)
                for val, x_mid in nums:
                    if balance_x and balance_x[0] <= x_mid <= balance_x[1]:
                        balance = val

                if balance is not None and prev_balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0:
                        credit = diff
                    elif diff < 0:
                        debit = abs(diff)

            # Clean description
            desc = line
            desc = re.sub(num_re, "", desc)
            desc = desc.replace(day, "").replace(mon, "")
            desc = " ".join(desc.split())

            current = {
                "date": tx_date,
                "description": desc,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2) if balance is not None else None,
                "page": page_no,
                "bank": BANK_NAME,
                "source_file": source_file
            }

        if current:
            transactions.append(current)
            prev_balance = current["balance"]
            current = None

    return transactions
