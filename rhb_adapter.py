# rhb_adapter.py
import re
import datetime

# =================================================
# REGEX (PDF-SAFE)
# =================================================
DATE_RE = re.compile(r"^(\d{2})\s*([A-Za-z]{3})")
NUM_RE = re.compile(r"\d[\d,]*\.\d{2}")

# =================================================
# SUMMARY / NON-TRANSACTION FILTER
# =================================================
SUMMARY_KEYWORDS = [
    "B/F BALANCE", "C/F BALANCE",
    "BALANCE B/F", "BALANCE C/F",
    "ACCOUNT SUMMARY", "DEPOSIT ACCOUNT SUMMARY",
    "TOTAL COUNT", "IMPORTANT NOTES",
    "ALL INFORMATION AND BALANCES",
    "MEMBER OF PIDM",
]

def is_summary_row(text: str) -> bool:
    t = text.upper().replace(" ", "")
    return any(k.replace(" ", "") in t for k in SUMMARY_KEYWORDS)

# =================================================
# YEAR DETECTION (STRICT)
# =================================================
def detect_year(pdf):
    """
    Robust year detection for RHB statements (Islamic & Conventional).
    Handles:
    - '7 Mar 24 – 31 Mar 24'
    - '7 Mar24–31 Mar24'
    - '01/03/2024 - 31/03/2024'
    """

    text = pdf.pages[0].extract_text() or ""
    text_upper = text.upper()

    # 1️⃣ Narrow search to Statement Period line (most reliable)
    for line in text_upper.splitlines():
        if "STATEMENT PERIOD" in line or "TEMPOH PENYATA" in line:
            # Try full year first (2024)
            m = re.search(r"(20\d{2})", line)
            if m:
                return int(m.group(1))

            # Fallback: short year (24)
            m = re.search(r"\b(\d{2})\b", line)
            if m:
                return int("20" + m.group(1))

    # 2️⃣ Global fallback (last resort)
    m = re.search(r"(20\d{2})", text)
    if m:
        return int(m.group(1))

    # ❌ If everything fails
    raise ValueError("❌ Statement year not detected – unsupported statement format")

# =================================================
# COLUMN DETECTORS
# =================================================
def detect_columns_islamic(page):
    return _detect_columns(page, pad_left=20, pad_right=60, bal_pad=100)

def detect_columns_conventional(page):
    return _detect_columns(page, pad_left=30, pad_right=40, bal_pad=80)

def _detect_columns(page, pad_left, pad_right, bal_pad):
    debit_x = credit_x = balance_x = None
    for w in page.extract_words():
        t = w["text"].lower()
        if t == "debit":
            debit_x = (w["x0"] - pad_left, w["x1"] + pad_right)
        elif t in ("credit", "kredit"):
            credit_x = (w["x0"] - pad_left, w["x1"] + pad_right)
        elif t in ("balance", "baki"):
            balance_x = (w["x0"] - pad_left, w["x1"] + bal_pad)
    return debit_x, credit_x, balance_x

# =================================================
# CORE PARSER (HARD-GUARDED)
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

            # ❌ skip summaries / headers
            if is_summary_row(line):
                continue

            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh",
                "Debit", "Credit", "Balance",
                "Page No", "Statement Period"
            ]):
                continue

            # ❌ must start with date
            dm = DATE_RE.match(line)
            if not dm:
                continue

            day, mon = dm.groups()
            try:
                tx_date = datetime.datetime.strptime(
                    f"{day}{mon}{year}", "%d%b%Y"
                ).date().isoformat()
            except:
                continue

            # -------------------------------------------------
            # Extract numbers with coordinates
            # -------------------------------------------------
            nums = []
            for w in line_words.get(line, []):
                txt = w["text"].replace(",", "")
                if NUM_RE.fullmatch(txt):
                    nums.append({"val": float(txt), "x": w["x0"], "x1": w["x1"]})

            if not nums:
                continue

            nums.sort(key=lambda x: x["x"])
            balance = nums[-1]["val"]
            txn_nums = nums[:-1]

            if balance is None:
                continue  # ❌ never allow NaN balance

            debit = credit = 0.0

            # -------------------------------------------------
            # Tentative assignment by X-axis
            # -------------------------------------------------
            for n in txn_nums:
                x_mid = (n["x"] + n["x1"]) / 2
                if debit_x and debit_x[0] <= x_mid <= debit_x[1]:
                    debit = n["val"]
                elif credit_x and credit_x[0] <= x_mid <= credit_x[1]:
                    credit = n["val"]

            # -------------------------------------------------
            # 🔒 FINAL AUTHORITY → BALANCE DIFFERENCE
            # -------------------------------------------------
            if prev_balance is not None:
                diff = round(balance - prev_balance, 2)
                if diff > 0:
                    credit = diff
                    debit = 0.0
                elif diff < 0:
                    debit = abs(diff)
                    credit = 0.0

            # ❌ invalid financial row
            if debit > 0 and credit > 0:
                continue
            if debit == 0 and credit == 0:
                continue

            # -------------------------------------------------
            # FIRST-LINE DESCRIPTION ONLY
            # -------------------------------------------------
            desc = line
            for a in NUM_RE.findall(desc):
                desc = desc.replace(a, "")
            desc = desc.replace(day, "").replace(mon, "").strip()

            transactions.append({
                "date": tx_date,
                "description": " ".join(desc.split()),
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_no,
                "bank": bank_name,
                "source_file": source_file
            })

            prev_balance = balance

    return transactions

# =================================================
# PUBLIC ENTRY POINT (USED BY app.py)
# =================================================
def parse_transactions_rhb(pdf, source_file):
    header = pdf.pages[0].extract_text() or ""
    if "RHB ISLAMIC BANK" in header.upper():
        return _parse_rhb_core(pdf, source_file, "RHB Islamic Bank", detect_columns_islamic)
    else:
        return _parse_rhb_core(pdf, source_file, "RHB Bank", detect_columns_conventional)
