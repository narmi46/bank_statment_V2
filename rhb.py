import re
import fitz
import pdfplumber
from datetime import datetime
from io import BytesIO


# ==========================================================
# Helpers
# ==========================================================
def _read_pdf_bytes(pdf_input) -> bytes:
    """
    Read PDF bytes safely from:
    - Streamlit UploadedFile (has .stream)
    - pdfplumber.PDF object (has .stream)
    - file path (str/pathlike)
    - file-like objects
    - raw bytes
    """
    if isinstance(pdf_input, (bytes, bytearray)):
        return bytes(pdf_input)

    # Streamlit UploadedFile OR pdfplumber.PDF exposes .stream
    if hasattr(pdf_input, "stream") and pdf_input.stream is not None:
        try:
            pdf_input.stream.seek(0)
        except Exception:
            pass
        return pdf_input.stream.read()

    # file-like object
    if hasattr(pdf_input, "read"):
        try:
            pdf_input.seek(0)
        except Exception:
            pass
        return pdf_input.read()

    # path
    with open(pdf_input, "rb") as f:
        return f.read()


# ==========================================================
# RHB Conventional / Reflex Cash Management (layout-based, fitz)
# Date looks like: 05-02-2025
# Balances may end with '-' or '+'
# ==========================================================
def _parse_rhb_conventional(pdf_bytes: bytes, source_filename: str):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")

    def parse_money(t: str) -> float:
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        try:
            v = float(t.replace(",", ""))
            return -v if neg else v
        except ValueError:
            return 0.0

    def norm_date(t: str) -> str:
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # ---- Opening balance (best-effort) ----
    opening_balance = None
    try:
        words = doc[0].get_text("words")
        rows = [{"x": w[0], "y": round(w[1], 1), "text": w[4].strip()} for w in words if w[4].strip()]
        for r in rows:
            text = r["text"].upper()
            if "BEGINNING" in text and "BALANCE" in text:
                y_ref = r["y"]
                x_ref = r["x"]
                same_line_money = [
                    w for w in rows
                    if abs(w["y"] - y_ref) <= 1.5 and w["x"] > x_ref and MONEY_RE.match(w["text"])
                ]
                if same_line_money:
                    same_line_money.sort(key=lambda w: w["x"])
                    opening_balance = parse_money(same_line_money[-1]["text"])
                break
    except Exception:
        opening_balance = None

    transactions = []
    previous_balance = opening_balance

    for page_index, page in enumerate(doc):
        words = page.get_text("words")
        rows = [{"x": w[0], "y": round(w[1], 1), "text": w[4].strip()} for w in words if w[4].strip()]
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

            balance = parse_money(max(money_vals, key=lambda m: m["x"])["text"])

            debit = credit = 0.0
            if previous_balance is not None:
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


# ==========================================================
# RHB Islamic (text-based, pdfplumber)
# Date looks like: 01 Jan
# Balance is at end of line
# ==========================================================
def _parse_rhb_islamic(pdf_bytes: bytes, source_filename: str):
    transactions = []
    previous_balance = None

    balance_pattern = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})\s*$")
    txn_date_pattern = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    year_pattern = re.compile(r"Statement Period.*?:\s*\d{1,2}\s+\w+\s+(\d{2})", re.IGNORECASE)

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header_text = (pdf.pages[0].extract_text() or "")
        year_match = year_pattern.search(header_text)
        if not year_match:
            ym2 = re.search(r"\bJan\s+(\d{2})\b", header_text)
            year = int("20" + ym2.group(1)) if ym2 else datetime.now().year
        else:
            year = int("20" + year_match.group(1))

        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                bal_m = balance_pattern.search(line)
                if not bal_m:
                    continue

                date_m = txn_date_pattern.search(line)
                if not date_m:
                    continue

                # B/F or C/F rows: set previous_balance and skip
                if re.search(r"\bB/F\b|\bC/F\b", line, flags=re.IGNORECASE):
                    previous_balance = float(bal_m.group(1).replace(",", ""))
                    continue

                balance = float(bal_m.group(1).replace(",", ""))
                day, month = date_m.groups()
                date_iso = datetime.strptime(f"{day} {month} {year}", "%d %b %Y").strftime("%Y-%m-%d")

                if previous_balance is None:
                    previous_balance = balance
                    continue

                delta = round(balance - previous_balance, 2)
                debit = abs(delta) if delta < 0 else 0.0
                credit = delta if delta > 0 else 0.0

                desc = line.replace(bal_m.group(1), "").replace(date_m.group(0), "")
                desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc[:200],
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_index + 1,
                    "bank": "RHB Bank",
                    "source_file": source_filename
                })

                previous_balance = balance

    return transactions


# ==========================================================
# AUTO-DETECT ENTRYPOINT (what app.py should call)
# ==========================================================
def parse_transactions_rhb(pdf_input, source_filename):
    pdf_bytes = _read_pdf_bytes(pdf_input)

    header = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            header = pdf.pages[0].extract_text() or ""
    except Exception:
        header = ""

    header_u = header.upper()

    # Islamic statements contain these indicators (your 012025.pdf has them)
    is_islamic = (
        "RHB ISLAMIC" in header_u
        or "PENYATA AKAUN" in header_u
        or "ACCOUNT STATEMENT /" in header_u
    )

    if is_islamic:
        tx = _parse_rhb_islamic(pdf_bytes, source_filename)
        if tx:
            return tx

    return _parse_rhb_conventional(pdf_bytes, source_filename)
