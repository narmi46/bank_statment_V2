import re
import datetime

BANK_NAME = "RHB Bank"

# -------------------------------------------------
# Regex
# -------------------------------------------------
date_re = re.compile(r"^(\d{2})\s*([A-Za-z]{3})")
num_re = re.compile(r"\d[\d,]*\.\d{2}")

SUMMARY_KEYWORDS = [
    "B/F BALANCE",
    "C/F BALANCE",
    "ACCOUNT SUMMARY",
    "RINGKASAN AKAUN",
    "IMPORTANT NOTES",
    "MEMBER OF PIDM",
    "TOTAL COUNT",
]


# -------------------------------------------------
# Helpers
# -------------------------------------------------
def is_summary_row(text: str) -> bool:
    text = text.upper()
    return any(k in text for k in SUMMARY_KEYWORDS)


def detect_year_from_coords(pdf):
    """
    Detect year using top header coordinates.
    Works even when text has no spaces: 7Mar24–31Mar24
    """
    page = pdf.pages[0]
    words = page.extract_words()

    header_words = [w["text"] for w in words if w["top"] < 120]
    header_text = " ".join(header_words)

    print("DEBUG HEADER:", header_text)

    # Match Mar24, Apr24, etc (with or without spaces)
    m = re.search(r"[A-Za-z]{3}(\d{2})", header_text)
    if m:
        return int("20" + m.group(1))

    return datetime.date.today().year


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


def group_words_by_line(words, y_tol=4):
    """
    Group words into visual lines using Y coordinate
    """
    lines = []
    for w in sorted(words, key=lambda x: -x["top"]):
        placed = False
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= y_tol:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    return lines


# -------------------------------------------------
# MAIN PARSER
# -------------------------------------------------
def parse_transactions_rhb(pdf, source_file):
    transactions = []
    prev_balance = None
    current = None

    year = detect_year_from_coords(pdf)
    print("DETECTED YEAR:", year)

    for page_no, page in enumerate(pdf.pages, start=1):
        debit_x, credit_x, balance_x = detect_columns(page)

        words = page.extract_words()
        visual_lines = group_words_by_line(words)

        for line_words in visual_lines:
            line_words.sort(key=lambda w: w["x0"])
            line_text = " ".join(w["text"] for w in line_words)

            # Skip headers & summaries
            if is_summary_row(line_text):
                continue

            if any(h in line_text for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh",
                "Debit", "Credit", "Balance", "PageNo"
            ]):
                continue

            dm = date_re.match(line_text)
            if not dm:
                continue  # 🔒 ignore continuation lines

            # Save previous transaction
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

            # Extract numeric values with X positions
            nums = []
            for w in line_words:
                txt = w["text"].replace(",", "")
                if num_re.fullmatch(txt):
                    nums.append({
                        "val": float(txt),
                        "x_mid": (w["x0"] + w["x1"]) / 2
                    })

            debit = credit = 0.0
            balance = None

            if nums:
                balance = nums[-1]["val"]
                txn_nums = nums[:-1]
            else:
                txn_nums = []

            # Assign debit / credit by X-axis
            for n in txn_nums:
                if debit_x and debit_x[0] <= n["x_mid"] <= debit_x[1]:
                    debit = n["val"]
                elif credit_x and credit_x[0] <= n["x_mid"] <= credit_x[1]:
                    credit = n["val"]

            # 🔒 Balance difference is final authority
            if prev_balance is not None and balance is not None:
                diff = round(balance - prev_balance, 2)
                if diff > 0:
                    credit = diff
                    debit = 0.0
                elif diff < 0:
                    debit = abs(diff)
                    credit = 0.0

            # FIRST LINE DESCRIPTION ONLY
            desc = line_text
            desc = re.sub(num_re, "", desc)
            desc = desc.replace(day, "").replace(mon, "").strip()
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

    print("TOTAL TRANSACTIONS:", len(transactions))
    return transactions
