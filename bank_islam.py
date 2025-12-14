# bank_islam.py
# FINAL – Bank Islam Ledger-Based Parser (BAL B/F anchored)

import re
import fitz  # PyMuPDF
from datetime import datetime

# ---------------------------------------------------------
# Regex
# ---------------------------------------------------------

DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})")
AMT_RE = re.compile(r"[\d,]+\.\d{2}")


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_amount(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def parse_date(raw):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


# ---------------------------------------------------------
# Extract BAL B/F (OPENING BALANCE)
# ---------------------------------------------------------

def extract_opening_balance(pdf):
    for page in pdf.pages[:1]:
        text = page.extract_text() or ""
        m = re.search(r"BAL\s+B/F\s*([\d,]+\.\d{2})", text, re.I)
        if m:
            return clean_amount(m.group(1))
        m = re.search(r"Opening Balance\s*\(MYR\)\s*([\d,]+\.\d{2})", text, re.I)
        if m:
            return clean_amount(m.group(1))
    return None


# ---------------------------------------------------------
# PHASE 1 — Extract FACTS ONLY (no debit/credit logic)
# ---------------------------------------------------------

def extract_rows(pdf, source_filename):
    rows = []

    pdf.stream.seek(0)
    doc = fitz.open(stream=pdf.stream.read(), filetype="pdf")

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        # rebuild lines by Y position
        lines = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            lines.setdefault(y, []).append((x0, text))

        for y in sorted(lines):
            line = " ".join(t[1] for t in sorted(lines[y], key=lambda x: x[0]))

            date_match = DATE_RE.search(line)
            amounts = AMT_RE.findall(line)

            if not date_match or not amounts:
                continue

            balance = clean_amount(amounts[-1])
            date = parse_date(date_match.group())

            if balance is None or not date:
                continue

            desc = line.replace(date_match.group(), "")
            desc = desc.replace(amounts[-1], "")
            desc = " ".join(desc.split())

            rows.append({
                "date": date,
                "description": desc,
                "balance": balance,
                "page": page_index + 1,
                "bank": "Bank Islam",
                "source_file": source_filename,
                "debit": 0.0,
                "credit": 0.0,
            })

    return rows


# ---------------------------------------------------------
# PHASE 2 — Inject BAL B/F as virtual ledger row
# ---------------------------------------------------------

def inject_opening_balance(rows, opening_balance):
    if opening_balance is None or not rows:
        return rows

    virtual = {
        "date": rows[0]["date"],
        "description": "BAL B/F",
        "balance": opening_balance,
        "debit": 0.0,
        "credit": 0.0,
        "page": rows[0]["page"],
        "bank": rows[0]["bank"],
        "source_file": rows[0]["source_file"],
        "_virtual": True,
    }

    return [virtual] + rows


# ---------------------------------------------------------
# PHASE 3 — Ledger engine (THE TRUTH)
# ---------------------------------------------------------

def apply_ledger_rules(rows):
    for i in range(1, len(rows)):
        prev_bal = rows[i - 1]["balance"]
        curr_bal = rows[i]["balance"]
        delta = round(curr_bal - prev_bal, 2)

        if delta > 0:
            rows[i]["credit"] = delta
        elif delta < 0:
            rows[i]["debit"] = abs(delta)

    return rows


# ---------------------------------------------------------
# PHASE 4 — Remove virtual row
# ---------------------------------------------------------

def remove_virtual_rows(rows):
    return [r for r in rows if not r.get("_virtual")]


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    # 1️⃣ Extract raw rows
    rows = extract_rows(pdf, source_filename)

    if not rows:
        return rows

    # 2️⃣ Extract opening balance
    opening_balance = extract_opening_balance(pdf)

    # 3️⃣ Inject BAL B/F as ledger anchor
    rows = inject_opening_balance(rows, opening_balance)

    # 4️⃣ Apply accounting truth
    rows = apply_ledger_rules(rows)

    # 5️⃣ Remove virtual BAL B/F row
    rows = remove_virtual_rows(rows)

    return rows
