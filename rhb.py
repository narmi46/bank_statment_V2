import re
import fitz
import pdfplumber
from datetime import datetime


# ==========================================================
# 🔹 CONVENTIONAL RHB PARSER (UNCHANGED CORE LOGIC)
# ==========================================================
def _parse_rhb_conventional(pdf_input, source_filename):
    """
    Layout-based RHB Conventional parser (existing logic)
    """

    # ---------------- OPEN PDF ----------------
    def open_doc(inp):
        if hasattr(inp, "stream"):  # Streamlit upload
            inp.stream.seek(0)
            return fitz.open(stream=inp.stream.read(), filetype="pdf")
        return fitz.open(inp)

    doc = open_doc(pdf_input)

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

    # ==========================================================
    # STEP 1: OPENING BALANCE
    # ==========================================================
    opening_balance = None
    first_page = doc[0]
    words = first_page.get_text("words")

    rows = [{
        "x": w[0],
        "y": round(w[1], 1),
        "text": w[4].strip()
    } for w in words if w[4].strip()]

    for r in rows:
        text = r["text"].upper()
        if "BEGINNING" in text and "BALANCE" in text:
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

    # ==========================================================
    # STEP 2: TRANSACTIONS
    # ==========================================================
    transactions = []
    previous_balance = opening_balance

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
# 🔹 RHB ISLAMIC PARSER (TEXT-BASED)
# ==========================================================
def _parse_rhb_islamic(pdf_input, source_filename):
    transactions = []
    previous_balance = None

    balance_pattern = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})$")
    date_pattern = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(pdf_input) as pdf:
        header = pdf.pages[0].extract_text() or ""
        year_match = re.search(r"\d{1,2}\s+Jan\s+(\d{2})", header)
        year = int("20" + year_match.group(1)) if year_match else datetime.now().year

        for page_index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                bal = balance_pattern.search(line)
                date = date_pattern.search(line)

                if not bal or not date:
                    continue

                balance = float(bal.group(1).replace(",", ""))
                day, month = date.groups()

                date_iso = datetime.strptime(
                    f"{day} {month} {year}", "%d %b %Y"
                ).strftime("%Y-%m-%d")

                if previous_balance is None:
                    previous_balance = balance
                    continue

                delta = round(balance - previous_balance, 2)
                debit = abs(delta) if delta < 0 else 0
                credit = delta if delta > 0 else 0

                desc = line.replace(bal.group(1), "").replace(date.group(0), "")
                desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                transactions.append({
                    "date": date_iso,
                    "description": desc[:200],
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_index + 1,
                    "bank": "RHB Bank",
                    "source_file": source_filename
                })

                previous_balance = balance

    return transactions


# ==========================================================
# 🔹 AUTO-DETECT WRAPPER (USED BY app.py)
# ==========================================================
def parse_transactions_rhb(pdf_input, source_filename):
    """
    AUTO-DETECT RHB Statement Type
    - Islamic → text-based parser
    - Conventional → layout-based parser
    """

    try:
        with pdfplumber.open(pdf_input) as pdf:
            header = pdf.pages[0].extract_text() or ""
    except Exception:
        header = ""

    if "STATEMENT PERIOD" in header.upper() or "ISLAMIC" in header.upper():
        return _parse_rhb_islamic(pdf_input, source_filename)

    return _parse_rhb_conventional(pdf_input, source_filename)
