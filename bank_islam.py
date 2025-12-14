# bank_islam.py
# Bank Islam – Ledger-Driven, Balance-First Parser (FINAL)

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
# PHASE 1 — EXTRACT FACTS ONLY (date, desc, balance)
# ---------------------------------------------------------

def extract_rows(pdf, source_filename):
    rows = []

    pdf.stream.seek(0)
    doc = fitz.open(stream=pdf.stream.read(), filetype="pdf")

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        # rebuild rows by Y-position
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
                # placeholders
                "debit": 0.0,
                "credit": 0.0,
            })

    return rows


# ---------------------------------------------------------
# PHASE 2 — LEDGER ENGINE (THE IMPORTANT PART)
# ---------------------------------------------------------

def apply_ledger_rules(rows):
    if not rows:
        return rows

    # --- Rule 1: Balance Delta (normal case)
    for i in range(1, len(rows)):
        prev = rows[i - 1]["balance"]
        curr = rows[i]["balance"]
        delta = round(curr - prev, 2)

        if delta > 0:
            rows[i]["credit"] = delta
        elif delta < 0:
            rows[i]["debit"] = abs(delta)

    # --- Rule 2: First row inference (BAL B/F not present)
    if len(rows) >= 2:
        first = rows[0]
        second = rows[1]

        if first["debit"] == 0.0 and first["credit"] == 0.0:
            delta = round(second["balance"] - first["balance"], 2)
            if delta > 0:
                first["credit"] = abs(delta)
            elif delta < 0:
                first["debit"] = abs(delta)

    # --- Rule 3: Single-transaction statement
    if len(rows) == 1:
        row = rows[0]
        m = AMT_RE.search(row["description"])
        if m:
            amt = clean_amount(m.group())
            if amt is not None:
                # service charges & advice are debit
                if any(k in row["description"].upper()
                       for k in ["CHARGE", "SERVICE", "ADVICE", "FEE"]):
                    row["debit"] = amt
                else:
                    row["credit"] = amt

    return rows


# ---------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    # Phase 1: extract facts only
    rows = extract_rows(pdf, source_filename)

    # Phase 2: apply accounting rules
    rows = apply_ledger_rules(rows)

    return rows
