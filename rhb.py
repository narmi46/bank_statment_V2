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
# RHB ISLAMIC — TEXT BASED (FIXED & SAFE)
# ======================================================
def _parse_rhb_islamic_text(pdf_bytes, source_filename):
    transactions = []
    previous_balance = None

    # --- regex helpers ---
    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    date_re = re.compile(r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:

        # ======================================================
        # 1️⃣ Extract header & safely detect YEAR
        # ======================================================
        header = pdf.pages[0].extract_text() or ""

        # 🔒 STRICT: only read year from "Statement Period"
        period_match = re.search(
            r"Statement Period.*?:\s*\d{1,2}\s+"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2})",
            header,
            re.IGNORECASE
        )

        if not period_match:
            return []  # fail safely if year cannot be trusted

        year = int("20" + period_match.group(2))  # e.g. 25 → 2025

        # ======================================================
        # 2️⃣ Parse transactions page by page
        # ======================================================
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

                # --- skip B/F and C/F lines ---
                if re.search(r"\bB/F\b|\bC/F\b", line):
                    previous_balance = balance
                    continue

                if previous_balance is None:
                    previous_balance = balance
                    continue

                # --- build full date ---
                day, month = date_match.groups()
                date_iso = datetime.strptime(
                    f"{day} {month} {year}",
                    "%d %b %Y"
                ).strftime("%Y-%m-%d")

                # --- compute debit / credit ---
                delta = balance - previous_balance
                debit = abs(delta) if delta < 0 else 0.0
                credit = delta if delta > 0 else 0.0

                # --- clean description ---
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
# 2️⃣ RHB CONVENTIONAL — TEXT BASED (NON-REFLEX)
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
                debit = abs(delta) if delta < 0 else 0
                credit = delta if delta > 0 else 0

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
# 3️⃣ RHB REFLEX / CASH MANAGEMENT — LAYOUT BASED
# ======================================================
import fitz
import re
from datetime import datetime

def _parse_rhb_reflex_layout(pdf_bytes, source_filename):
    transactions = []

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")
    OPEN_BAL_RE = re.compile(r"Beginning Balance.*?([\d,]+\.\d{2}[+-])")

    def parse_money(t):
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        v = float(t.replace(",", ""))
        return -v if neg else v

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # --------------------------------------------------
    # 1️⃣ Extract opening balance (from first page)
    # --------------------------------------------------
    previous_balance = None
    first_page_text = doc[0].get_text()

    m = OPEN_BAL_RE.search(first_page_text.replace("\n", " "))
    if m:
        previous_balance = parse_money(m.group(1))

    # --------------------------------------------------
    # 2️⃣ Parse transaction rows
    # --------------------------------------------------
    for page_index, page in enumerate(doc):
        words = page.get_text("words")
        rows = [{"x": w[0], "y": round(w[1], 1), "text": w[4]} for w in words if w[4].strip()]
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

            money_vals = [w for w in line if MONEY_RE.match(w["text"])]
            if not money_vals:
                continue

            balance = parse_money(max(money_vals, key=lambda m: m["x"])["text"])

            # --------------------------------------------------
            # 3️⃣ Debit / Credit calculation
            # --------------------------------------------------
            if previous_balance is None:
                delta = 0.0
            else:
                delta = balance - previous_balance

            debit = abs(delta) if delta < 0 else 0.0
            credit = delta if delta > 0 else 0.0

            desc = " ".join(
                w["text"] for w in line
                if w["text"] != r["text"] and not MONEY_RE.match(w["text"])
            )

            transactions.append({
                "date": date_iso,
                "description": desc.strip(),
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
# 🚦 FINAL ENTRYPOINT — INDEPENDENT FALLBACK
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
