import re
import fitz
import pdfplumber
from datetime import datetime
from io import BytesIO


# ======================================================
# Helper: read PDF bytes safely
# ======================================================
def _read_pdf_bytes(pdf_input):
    if isinstance(pdf_input, (bytes, bytearray)):
        return bytes(pdf_input)

    if hasattr(pdf_input, "stream"):  # Streamlit UploadedFile
        pdf_input.stream.seek(0)
        return pdf_input.stream.read()

    if hasattr(pdf_input, "read"):
        pdf_input.seek(0)
        return pdf_input.read()

    with open(pdf_input, "rb") as f:
        return f.read()


# ======================================================
# 1️⃣ RHB ISLAMIC — TEXT BASED
# ======================================================
def _parse_rhb_islamic_text(pdf_bytes, source_filename):
    transactions = []
    previous_balance = None

    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""

        period_match = re.search(
            r"Statement Period.*?:\s*\d{1,2}\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2})",
            header,
            re.IGNORECASE
        )

        if not period_match:
            return []

        year = int("20" + period_match.group(2))

        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal_match = balance_re.search(line)
                date_match = date_re.search(line)
                if not bal_match or not date_match:
                    continue

                balance = float(bal_match.group(1).replace(",", ""))

                if re.search(r"\bB/F\b|\bC/F\b", line):
                    previous_balance = balance
                    continue

                if previous_balance is None:
                    previous_balance = balance
                    continue

                day, month = date_match.groups()
                date_iso = datetime.strptime(
                    f"{day} {month} {year}", "%d %b %Y"
                ).strftime("%Y-%m-%d")

                delta = balance - previous_balance
                debit = abs(delta) if delta < 0 else 0.0
                credit = delta if delta > 0 else 0.0

                desc = line
                desc = desc.replace(bal_match.group(1), "")
                desc = desc.replace(date_match.group(0), "")
                desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_index + 1,
                    "bank": "RHB Islamic Bank",
                    "source_file": source_filename
                })

                previous_balance = balance

    return transactions


# ======================================================
# 2️⃣ RHB CONVENTIONAL — TEXT BASED
# ======================================================
def _parse_rhb_conventional_text(pdf_bytes, source_filename):
    transactions = []
    previous_balance = None

    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""
        ym = re.search(r"[A-Za-z]{3}(\d{2})", header)
        if not ym:
            return []

        year = int("20" + ym.group(1))

        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal = balance_re.search(line)
                date = date_re.search(line)
                if not bal or not date:
                    continue

                balance = float(bal.group(1).replace(",", ""))

                if previous_balance is None:
                    previous_balance = balance
                    continue

                day, month = date.groups()
                date_iso = datetime.strptime(
                    f"{day}{month}{year}", "%d%b%Y"
                ).strftime("%Y-%m-%d")

                delta = balance - previous_balance
                debit = abs(delta) if delta < 0 else 0.0
                credit = delta if delta > 0 else 0.0

                desc = line.replace(bal.group(1), "").replace(date.group(0), "")
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_index + 1,
                    "bank": "RHB Bank",
                    "source_file": source_filename
                })

                previous_balance = balance

    return transactions


# ======================================================
# 3️⃣ RHB REFLEX / CASH MANAGEMENT — LAYOUT BASED (FIXED)
# ======================================================
def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    transactions = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")

    # Supports: 0.50, .50, 1,425.00, trailing +/- for overdraft
    MONEY_RE = re.compile(
        r"^(?:\d{1,3}(?:,\d{3})*|\d)?\.\d{2}[+-]?$"
    )

    def parse_money(t):
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        try:
            v = float(t.replace(",", ""))
            return -v if neg else v
        except ValueError:
            return 0.0

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # ==================================================
    # Opening Balance (page 1 header)
    # ==================================================
    opening_balance = None
    first_page = doc[0]
    words = first_page.get_text("words")

    rows = [{
        "x": w[0],
        "y": round(w[1], 1),
        "text": w[4].strip()
    } for w in words if w[4].strip()]

    for r in rows:
        txt = r["text"].upper()
        if "BEGINNING" in txt and "BALANCE" in txt:
            y_ref = r["y"]
            x_ref = r["x"]

            same_line_money = [
                w for w in rows
                if abs(w["y"] - y_ref) <= 1.5
                and w["x"] > x_ref
                and MONEY_RE.match(w["text"])
            ]

            if same_line_money:
                same_line_money.sort(key=lambda w: w["x"])
                opening_balance = parse_money(same_line_money[-1]["text"])
            break

    previous_balance = opening_balance
    is_first_txn = True  # 🔥 critical flag

    # ==================================================
    # Transactions (ALL pages)
    # ==================================================
    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))
        used_y = set()

        for r in rows:
            if not DATE_RE.match(r["text"]):
                continue

            y_key = r["y"]
            if y_key in used_y:
                continue

            date_iso = norm_date(r["text"])

            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            description = []
            money_vals = []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if MONEY_RE.match(w["text"]):
                    money_vals.append(w)
                elif not w["text"].isdigit():
                    description.append(w["text"])

            if not money_vals:
                continue

            # Balance = rightmost money
            balance = parse_money(
                max(money_vals, key=lambda m: m["x"])["text"]
            )

            debit = credit = 0.0

            # ==================================================
            # 🔥 FIRST TRANSACTION — USE LAYOUT, NOT DELTA
            # ==================================================
            if is_first_txn:
                if len(money_vals) >= 2:
                    txn_amt = parse_money(money_vals[-2]["text"])
                    if txn_amt < 0:
                        debit = abs(txn_amt)
                    else:
                        credit = txn_amt
                is_first_txn = False

            # ==================================================
            # ALL OTHER TRANSACTIONS — SAFE DELTA
            # ==================================================
            elif previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": date_iso,
                "description": " ".join(description)[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Bank",
                "source_file": source_filename
            })

            previous_balance = balance
            used_y.add(y_key)

    doc.close()
    return transactions
