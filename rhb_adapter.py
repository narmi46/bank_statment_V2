# rhb_adapter.py
import re
import datetime

BANK_NAME = "RHB Bank"

# 🔧 FIXED: allow glued dates like 11Mar
date_re = re.compile(r"^(\d{2})\s*([A-Za-z]{3})")

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
    text = text.upper()
    return any(k in text for k in SUMMARY_KEYWORDS)


# -------------------------------------------------
# Detect column X ranges from header
# -------------------------------------------------
def detect_columns(page):
    debit_x = credit_x = balance_x = None

    for w in page.extract_words():
        t = w["text"].lower()
        if t == "debit":
            debit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 20, w["x1"] + 60)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 20, w["x1"] + 100)

    return debit_x, credit_x, balance_x


# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    # -------------------------------------------------
    # Detect YEAR from header (supports BOTH formats)
    # -------------------------------------------------
    header_text = pdf.pages[0].extract_text() or ""

    # 1️⃣ spaced: "7 Mar 24 – 31 Mar 24"
    m = re.search(r"\d{1,2}\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]", header_text)

    # 2️⃣ glued: "7Mar24–31Mar24"
    if not m:
        m = re.search(r"[A-Za-z]{3}(\d{2})", header_text)

    year = int("20" + m.group(1)) if m else datetime.date.today().year

    # -------------------------------------------------
    # Detect column X positions (first page is enough)
    # -------------------------------------------------
    debit_x, credit_x, balance_x = detect_columns(pdf.pages[0])

    # -------------------------------------------------
    # Parse pages
    # -------------------------------------------------
    for page_no, page in enumerate(pdf.pages, start=1):
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

            # Skip summaries & disclaimers
            if is_summary_row(line):
                continue

            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh",
                "Debit", "Credit", "Balance",
                "Page No", "Statement Period"
            ]):
                continue

            dm = date_re.match(line)

            # ==============================
            # DATE LINE → new transaction
            # ==============================
            if dm:
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
                        nums.append({
                            "val": float(txt),
                            "x": w["x0"],
                            "x1": w["x1"]
                        })

                nums.sort(key=lambda x: x["x"])

                # Rightmost number = balance
                if nums:
                    balance = nums[-1]["val"]
                    txn_nums = nums[:-1]
                else:
                    txn_nums = []

                # Assign debit / credit by X-axis
                for n in txn_nums:
                    x_mid = (n["x"] + n["x1"]) / 2
                    if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                        debit = n["val"]
                    elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                        credit = n["val"]

                # 🔒 Balance difference fallback
                if prev_balance is not None and balance is not None:
                    diff = round(balance - prev_balance, 2)
                    if diff > 0:
                        credit = diff
                        debit = 0.0
                    elif diff < 0:
                        debit = abs(diff)
                        credit = 0.0

                # DESCRIPTION: first line only
                desc = line
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "").replace(mon, "").strip()

                current = {
                    "date": tx_date,
                    "description": " ".join(desc.split()),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_no,
                    "bank": BANK_NAME,
                    "source_file": source_file
                }

            # ==============================
            # CONTINUATION LINE → IGNORE
            # ==============================
            else:
                continue

        if current:
            transactions.append(current)
            prev_balance = current["balance"]
            current = None

    return transactions
