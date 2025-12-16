import re
import fitz  # PyMuPDF
import os
from datetime import datetime

# -----------------------------
# REGEX
# -----------------------------
DATE_RE = re.compile(
    r"^("
    r"\d{2}/\d{2}/\d{4}|"
    r"\d{2}/\d{2}|"
    r"\d{2}-\d{2}|"
    r"\d{2}\s+[A-Z]{3}"
    r")$",
    re.IGNORECASE
)

YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Accept:
# 0.10, .10, 10.00, 1,234.56
AMOUNT_CORE_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}$")
# Maybank adds trailing sign: 1,980.00+ / 1,500.00-
AMOUNT_WITH_SIGN_RE = re.compile(r"^(.*?)([+-])$")


# -----------------------------
# HELPERS
# -----------------------------
def open_pymupdf(pdf_input):
    if isinstance(pdf_input, str):
        if not os.path.exists(pdf_input):
            raise FileNotFoundError(pdf_input)
        return fitz.open(pdf_input)

    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        data = pdf_input.stream.read()
        if not data:
            raise ValueError("PDF stream empty")
        return fitz.open(stream=data, filetype="pdf")

    raise ValueError("Unsupported PDF input")


def normalize_maybank_date(token, year):
    token = token.upper().strip()
    for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m", "%d %b"):
        try:
            if fmt == "%d/%m/%Y":
                dt = datetime.strptime(token, fmt)
            else:
                dt = datetime.strptime(f"{token}/{year}", fmt + "/%Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    return None


def split_amount_and_sign(text):
    """
    Returns (amount_text_without_sign, sign or None)
    Examples:
      "1,980.00+" -> ("1,980.00", "+")
      "150.00-"   -> ("150.00", "-")
      "0.10"      -> ("0.10", None)
      ".10"       -> (".10", None)
    """
    t = text.strip()
    m = AMOUNT_WITH_SIGN_RE.match(t)
    if m:
        return m.group(1).strip(), m.group(2)
    return t, None


def is_amount_token(text):
    amt, _ = split_amount_and_sign(text)
    return bool(AMOUNT_CORE_RE.match(amt))


def amount_to_float(text):
    amt, _ = split_amount_and_sign(text)
    return float(amt.replace(",", ""))


def decide_debit_credit(txn_amount, txn_sign, prev_balance, balance):
    """
    Two-way decision:
    A) Sign-based (preferred if exists)
    B) Balance delta-based (fallback)

    Returns (debit, credit)
    """
    debit = credit = 0.0

    # B) Delta-based
    delta_debit = delta_credit = None
    if prev_balance is not None:
        delta = round(balance - prev_balance, 2)
        if delta > 0:
            delta_credit = abs(delta)
            delta_debit = 0.0
        elif delta < 0:
            delta_debit = abs(delta)
            delta_credit = 0.0
        else:
            delta_debit = 0.0
            delta_credit = 0.0

    # A) Sign-based (Maybank style: amount token often ends with + or -)
    sign_debit = sign_credit = None
    if txn_amount is not None and txn_sign in ("+", "-"):
        if txn_sign == "+":
            sign_credit = round(abs(txn_amount), 2)
            sign_debit = 0.0
        else:
            sign_debit = round(abs(txn_amount), 2)
            sign_credit = 0.0

    # Reconcile
    if sign_debit is not None and sign_credit is not None:
        debit, credit = sign_debit, sign_credit
        # If delta exists and conflicts a lot, keep sign but you can log/debug it if you want.
        return debit, credit

    # fallback to delta if available
    if delta_debit is not None and delta_credit is not None:
        return round(delta_debit, 2), round(delta_credit, 2)

    # last resort (no prev balance + no sign): treat txn_amount as debit
    if txn_amount is not None:
        return round(abs(txn_amount), 2), 0.0

    return 0.0, 0.0


# -----------------------------
# MAIN PARSER
# -----------------------------
def parse_transactions_maybank(pdf_input, source_filename):
    doc = open_pymupdf(pdf_input)

    transactions = []
    seen = set()
    previous_balance = None

    bank_name = "Maybank"
    statement_year = None

    # header scan
    for p in range(min(2, len(doc))):
        text = doc[p].get_text("text").upper()
        if "MAYBANK ISLAMIC" in text:
            bank_name = "Maybank Islamic"
        elif "MAYBANK" in text:
            bank_name = "Maybank"

        m = YEAR_RE.search(text)
        if m:
            statement_year = m.group(1)
            break

    if not statement_year:
        statement_year = str(datetime.now().year)

    # parse pages
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1

        words = page.get_text("words")
        rows = []
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            text = str(text).strip()
            if not text:
                continue
            rows.append({"x0": x0, "y0": y0, "text": text})

        rows.sort(key=lambda r: (round(r["y0"], 1), r["x0"]))

        Y_TOL = 2.0
        i = 0
        while i < len(rows):
            token = rows[i]["text"]

            if not DATE_RE.match(token):
                i += 1
                continue

            iso_date = normalize_maybank_date(token, statement_year)
            if not iso_date:
                i += 1
                continue

            y_ref = rows[i]["y0"]
            same_line = [r for r in rows if abs(r["y0"] - y_ref) <= Y_TOL]
            same_line.sort(key=lambda r: r["x0"])

            desc_parts = []
            amounts = []  # (x0, value_float, sign)

            for r in same_line:
                t = r["text"]
                if t == token:
                    continue
                if is_amount_token(t):
                    signless, sign = split_amount_and_sign(t)
                    amounts.append((r["x0"], amount_to_float(t), sign))
                else:
                    desc_parts.append(t)

            if not amounts:
                i += 1
                continue

            # right-most numeric = balance
            amounts.sort(key=lambda a: a[0])
            balance = float(amounts[-1][1])

            # txn amount = second right-most (if exists)
            txn_amount = None
            txn_sign = None
            if len(amounts) > 1:
                txn_amount = float(amounts[-2][1])
                txn_sign = amounts[-2][2]

            description = " ".join(desc_parts)
            description = " ".join(description.split())[:160]

            # skip summary-ish rows
            if any(k in description.upper() for k in [
                "MONTHLY SUMMARY", "TOTAL", "SUBTOTAL",
                "BALANCE B/F", "BALANCE C/F"
            ]):
                i += 1
                continue

            debit, credit = decide_debit_credit(txn_amount, txn_sign, previous_balance, balance)
            previous_balance = balance

            sig = (iso_date, round(debit, 2), round(credit, 2), round(balance, 2), page_num)
            if sig not in seen:
                seen.add(sig)
                transactions.append({
                    "date": iso_date,
                    "description": description or "UNKNOWN",
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_num,
                    "bank": bank_name,
                    "source_file": source_filename
                })

            i += 1

    doc.close()
    return transactions
