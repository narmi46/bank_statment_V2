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
# 1️⃣ RHB ISLAMIC — TEXT BASED (UNCHANGED)
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
# 2️⃣ RHB CONVENTIONAL — TEXT BASED (UNCHANGED)
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
# 3️⃣ RHB REFLEX — LAYOUT BASED (FIXED)
# ======================================================
def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    transactions = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d)?\.\d{2}[+-]?$")

    def parse_money(t):
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        v = float(t.replace(",", ""))
        return -v if neg else v

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    previous_balance = None
    first_txn = True

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

            desc = []
            money = []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if MONEY_RE.match(w["text"]):
                    money.append(w)
                elif not w["text"].isdigit():
                    desc.append(w["text"])

            if not money:
                continue

            balance = parse_money(max(money, key=lambda m: m["x"])["text"])
            debit = credit = 0.0

            if first_txn:
                if len(money) >= 2:
                    amt = parse_money(money[-2]["text"])
                    debit = abs(amt) if amt < 0 else 0.0
                    credit = amt if amt > 0 else 0.0
                first_txn = False
            elif previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                debit = abs(delta) if delta < 0 else 0.0
                credit = delta if delta > 0 else 0.0

            transactions.append({
                "date": date_iso,
                "description": " ".join(desc)[:200],
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


# ======================================================
# 🚦 PUBLIC ENTRYPOINT (UNCHANGED)
# ======================================================
def parse_transactions_rhb(pdf_input, source_filename):
    pdf_bytes = _read_pdf_bytes(pdf_input)

    for parser in (
        _parse_rhb_islamic_text,
        _parse_rhb_conventional_text,
        _parse_rhb_reflex_layout,
    ):
        tx = parser(pdf_bytes, source_filename)
        if tx:
            return tx

    return []
