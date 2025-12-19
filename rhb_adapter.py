# rhb_adapter.py
import re
import datetime

# =================================================
# COMMON CONFIG
# =================================================
date_re = re.compile(r"^(\d{2})\s*([A-Za-z]{3})")
num_re = re.compile(r"\d[\d,]*\.\d{2}")

SUMMARY_KEYWORDS = [
    "B/F BALANCE", "C/F BALANCE",
    "ACCOUNT SUMMARY", "DEPOSIT ACCOUNT SUMMARY",
    "IMPORTANT NOTES", "MEMBER OF PIDM",
    "TOTAL COUNT", "ALL INFORMATION AND BALANCES",
]

# =================================================
# HELPERS
# =================================================
def is_summary_row(text: str) -> bool:
    return any(k in text.upper() for k in SUMMARY_KEYWORDS)


def detect_year(pdf):
    txt = pdf.pages[0].extract_text() or ""
    m = re.search(r"\d{1,2}\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]", txt)
    return int("20" + m.group(1)) if m else datetime.date.today().year


# =================================================
# COLUMN DETECTORS
# =================================================
def detect_columns_islamic(page):
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


def detect_columns_conventional(page):
    debit_x = credit_x = balance_x = None
    for w in page.extract_words():
        t = w["text"].lower()
        if t == "debit":
            debit_x = (w["x0"] - 30, w["x1"] + 40)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - 30, w["x1"] + 40)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - 30, w["x1"] + 80)
    return debit_x, credit_x, balance_x


# =================================================
# CORE PARSER (FIXED)
# =================================================
def _parse_rhb_core(pdf, source_file, bank_name, column_detector):
    transactions = []
    prev_balance = None
    year = detect_year(pdf)

    debit_x, credit_x, balance_x = column_detector(pdf.pages[0])

    for page_no, page in enumerate(pdf.pages, start=1):
        lines = [l.strip() for l in (page.extract_text() or "").splitlines() if l.strip()]
        words = page.extract_words()

        line_words = {}
        for w in words:
            for line in lines:
                if w["text"] in line:
                    line_words.setdefault(line, []).append(w)
                    break

        for line in lines:

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
                continue   # <-- THIS IS NOW SAFE

            day, mon = dm.groups()
            try:
                tx_date = datetime.datetime.strptime(
                    f"{day}{mon}{year}", "%d%b%Y"
                ).date().isoformat()
            except:
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
            if nums:
                balance = nums[-1]["val"]
                txn_nums = nums[:-1]
            else:
                txn_nums = []

            for n in txn_nums:
                x_mid = (n["x"] + n["x1"]) / 2
                if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                    debit = n["val"]
                elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                    credit = n["val"]

            # 🔒 BALANCE DIFF = TRUTH
            if prev_balance is not None and balance is not None:
                diff = round(balance - prev_balance, 2)
                if diff > 0:
                    credit = diff
                    debit = 0.0
                elif diff < 0:
                    debit = abs(diff)
                    credit = 0.0

            # FIRST LINE DESCRIPTION ONLY
            desc = line
            for a in num_re.findall(desc):
                desc = desc.replace(a, "")
            desc = desc.replace(day, "").replace(mon, "").strip()

            transactions.append({
                "date": tx_date,
                "description": " ".join(desc.split()),
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2) if balance is not None else None,
                "page": page_no,
                "bank": bank_name,
                "source_file": source_file
            })

            prev_balance = balance

    return transactions


# =================================================
# PUBLIC ENTRY
# =================================================
def parse_transactions_rhb(pdf, source_file):
    header = pdf.pages[0].extract_text() or ""
    if "RHB ISLAMIC BANK" in header.upper():
        return _parse_rhb_core(
            pdf, source_file, "RHB Islamic Bank", detect_columns_islamic
        )
    else:
        return _parse_rhb_core(
            pdf, source_file, "RHB Bank", detect_columns_conventional
        )
