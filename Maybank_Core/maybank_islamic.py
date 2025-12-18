import fitz
import re
from datetime import datetime


# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

MONTHS = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}

def is_day(t):
    return t.isdigit() and 1 <= int(t) <= 31

def is_month(t):
    return t.capitalize() in MONTHS

def is_year(t):
    return t.isdigit() and t.startswith("20")

def parse_amount(v):
    return float(v.replace(",", ""))

def looks_like_money(t):
    tt = t.replace(",", "")
    if "." not in tt:
        return False
    try:
        float(tt)
        return True
    except:
        return False


def extract_statement_year(text):
    """
    Extract year from:
    STATEMENT DATE : 30/09/24
    STATEMENT DATE : 30/09/2024
    """
    m = re.search(
        r"STATEMENT\s+DATE\s*:?\s*\d{2}/\d{2}/(\d{2,4})",
        text,
        re.IGNORECASE
    )
    if m:
        y = m.group(1)
        return int("20" + y) if len(y) == 2 else int(y)
    return None


# ---------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------

def parse_transactions_maybank_islamic(pdf_input, source_filename):

    # ---------- Open PDF safely (Streamlit compatible)
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        doc = fitz.open(stream=pdf_input.stream.read(), filetype="pdf")
    else:
        doc = fitz.open(pdf_input)

    # ---------- Extract statement year (MANDATORY)
    first_page_text = doc[0].get_text("text")
    statement_year = extract_statement_year(first_page_text)

    if not statement_year:
        doc.close()
        raise ValueError("❌ STATEMENT DATE not found — cannot determine year safely")

    transactions = []
    previous_balance = None
    bank_name = "Maybank Islamic"

    # ---------- Parse pages
    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": str(w[4]).strip()
        } for w in words if str(w[4]).strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))

        used_y = set()

        for i in range(len(rows) - 2):
            w1, w2, w3 = rows[i], rows[i + 1], rows[i + 2]

            # ---------- Detect split date: 01 Feb 2025
            if not (is_day(w1["text"]) and is_month(w2["text"]) and is_year(w3["text"])):
                continue

            y_key = w1["y"]
            if y_key in used_y:
                continue

            try:
                date_iso = datetime.strptime(
                    f"{w1['text']} {w2['text']} {statement_year}",
                    "%d %b %Y"
                ).strftime("%Y-%m-%d")
            except:
                continue

            # ---------- Collect full transaction row
            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc_parts = []
            amounts = []

            for w in line:
                if w is w1 or w is w2 or w is w3:
                    continue
                if looks_like_money(w["text"]):
                    amounts.append(w["text"])
                else:
                    desc_parts.append(w["text"])

            if not amounts:
                continue

            balance = parse_amount(amounts[-1])
            debit = credit = 0.0
            desc_up = " ".join(desc_parts).upper()

            # ---------- Debit / Credit logic
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta < 0:
                    debit = abs(delta)
                elif delta > 0:
                    credit = delta
            else:
                # FIRST transaction → use printed amount
                if len(amounts) >= 2:
                    txn_amt = parse_amount(amounts[-2])
                    if "CR" in desc_up or "CREDIT" in desc_up:
                        credit = txn_amt
                    else:
                        debit = txn_amt

            transactions.append({
                "date": date_iso,
                "description": " ".join(desc_parts).strip()[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": bank_name,
                "source_file": source_filename
            })

            previous_balance = balance
            used_y.add(y_key)

    doc.close()
    return transactions
