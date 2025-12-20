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

    if hasattr(pdf_input, "stream"):
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
            r"Statement Period.*?(\d{2})",
            header,
            re.IGNORECASE
        )
        if not period_match:
            return []

        year = int("20" + period_match.group(1))

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

                desc = re.sub(balance_re, "", line)
                desc = desc.replace(date_match.group(0), "")
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

                desc = re.sub(balance_re, "", line)
                desc = desc.replace(date.group(0), "")
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
# 3️⃣ RHB REFLEX — LAYOUT BASED (LAYOUT = TRUTH)
# ======================================================
def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    transactions = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"(?:\d{1,3}(?:,\d{3})*|\d)?\.\d{2}")

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

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

            y = r["y"]
            if y in used_y:
                continue

            # collect full visual row
            line = [w for w in rows if abs(w["y"] - y) <= 1.5]
            line.sort(key=lambda w: w["x"])

            texts = [w["text"] for w in line]

            amounts = [t for t in texts if MONEY_RE.match(t)]
            if len(amounts) < 2:
                continue

            # last amount is always balance
            balance_text = amounts[-1]
            balance = float(balance_text.replace(",", "").replace("-", ""))
            if balance_text.endswith("-"):
                balance = -balance

            # transaction amount is the first amount
            amt = float(amounts[0].replace(",", ""))

            # layout-based DR / CR decision (POSITIONAL)
            remainder = " ".join(texts)
            before_amt, _ = remainder.split(amounts[0], 1)

            debit = credit = 0.0
            if "-" in before_amt:
                # "- 30,000.00" → CREDIT
                credit = amt
            else:
                # "27,286.00 -" → DEBIT
                debit = amt

            description = [
                t for t in texts
                if t not in amounts
                and not DATE_RE.match(t)
                and not t.isdigit()
            ]

            transactions.append({
                "date": norm_date(r["text"]),
                "description": " ".join(description)[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Bank",
                "source_file": source_filename
            })

            used_y.add(y)

    doc.close()
    return transactions


# ======================================================
# 🚦 PUBLIC ENTRYPOINT — DO NOT RENAME
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
