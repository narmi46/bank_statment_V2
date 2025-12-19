import re
import fitz
import pdfplumber
from datetime import datetime
from io import BytesIO


# ==========================================================
# 🔹 RHB CONVENTIONAL PARSER (LAYOUT-BASED, FITZ)
# ==========================================================
def _parse_rhb_conventional(pdf_bytes, source_filename):

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")

    def parse_money(t):
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        try:
            v = float(t.replace(",", ""))
            return -v if neg else v
        except:
            return 0.0

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # ---------------- OPENING BALANCE ----------------
    opening_balance = None
    words = doc[0].get_text("words")

    rows = [{
        "x": w[0],
        "y": round(w[1], 1),
        "text": w[4].strip()
    } for w in words if w[4].strip()]

    for r in rows:
        txt = r["text"].upper()
        if "BEGINNING" in txt and "BALANCE" in txt:
            y_ref, x_ref = r["y"], r["x"]
            same_line_money = [
                w for w in rows
                if abs(w["y"] - y_ref) <= 1.5
                and w["x"] > x_ref
                and MONEY_RE.match(w["text"])
            ]
            if same_line_money:
                opening_balance = parse_money(
                    max(same_line_money, key=lambda w: w["x"])["text"]
                )
            break

    # ---------------- TRANSACTIONS ----------------
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

            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            money_vals = []
            desc = []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if MONEY_RE.match(w["text"]):
                    money_vals.append(w)
                elif not w["text"].isdigit():
                    desc.append(w["text"])

            if not money_vals:
                continue

            balance = parse_money(max(money_vals, key=lambda w: w["x"])["text"])
            debit = credit = 0.0

            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": norm_date(r["text"]),
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


# ==========================================================
# 🔹 RHB ISLAMIC PARSER (TEXT-BASED, PDFPLUMBER)
# ==========================================================
def _parse_rhb_islamic(pdf_bytes, source_filename):

    transactions = []
    previous_balance = None

    balance_re = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})$")
    date_re = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        header = pdf.pages[0].extract_text() or ""
        year_match = re.search(r"\d{1,2}\s+Jan\s+(\d{2})", header)
        year = int("20" + year_match.group(1)) if year_match else datetime.now().year

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
# 🔹 AUTO-DETECT WRAPPER (USED BY app.py)
# ==========================================================
def parse_transactions_rhb(pdf_input, source_filename):
    """
    Auto-detect RHB Islamic vs Conventional
    SAFE for Streamlit
    """

    # ---------- READ PDF ONCE ----------
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        pdf_bytes = pdf_input.stream.read()
    else:
        with open(pdf_input, "rb") as f:
            pdf_bytes = f.read()

    # ---------- DETECT TYPE ----------
    header = ""
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            header = pdf.pages[0].extract_text() or ""
    except:
        pass

    if "STATEMENT PERIOD" in header.upper() or "ISLAMIC" in header.upper():
        tx = _parse_rhb_islamic(pdf_bytes, source_filename)
        if tx:
            return tx

    # fallback to conventional
    return _parse_rhb_conventional(pdf_bytes, source_filename)
