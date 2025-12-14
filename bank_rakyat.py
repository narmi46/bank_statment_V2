# bank_rakyat.py
# Bank Rakyat – Balance-driven parser (2-pass, production safe)

import re
import fitz
from datetime import datetime


# ---------------------------------------------------------
# helpers
# ---------------------------------------------------------

def clean_amount(val):
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return None


def parse_date(raw):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_opening_balance(text):
    patterns = [
        r"Opening Balance\s*([\-]?\d[\d,]*\.\d{2})",
        r"Baki Permulaan\s*([\-]?\d[\d,]*\.\d{2})",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return clean_amount(m.group(1))
    return None


# ---------------------------------------------------------
# PASS 1 — Extract RAW rows (date + desc + balance)
# ---------------------------------------------------------

def extract_raw_rows(pdf):
    raw = []

    for page_no, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        for line in lines:
            date_match = re.search(r"\d{2}/\d{2}/\d{4}", line)
            if not date_match:
                continue

            amounts = re.findall(r"[+-]?\d[\d,]*\.\d{2}", line)
            if not amounts:
                continue

            balance = clean_amount(amounts[-1])
            if balance is None:
                continue

            iso_date = parse_date(date_match.group())
            if not iso_date:
                continue

            desc = line.replace(date_match.group(), "")
            desc = desc.replace(amounts[-1], "")
            desc = " ".join(desc.split())

            raw.append({
                "date": iso_date,
                "description": desc,
                "balance": balance,
                "page": page_no,
            })

    return raw


# ---------------------------------------------------------
# PASS 2 — Compute debit / credit safely
# ---------------------------------------------------------

def apply_balance_delta(raw_rows, opening_balance, source_filename):
    if not raw_rows:
        return []

    # Sort by date then page
    raw_rows.sort(key=lambda x: (x["date"], x["page"]))

    results = []
    prev_balance = opening_balance

    for row in raw_rows:
        debit = credit = 0.0

        if prev_balance is not None:
            delta = round(row["balance"] - prev_balance, 2)
            if delta > 0:
                credit = delta
            elif delta < 0:
                debit = abs(delta)

        prev_balance = row["balance"]

        results.append({
            "date": row["date"],
            "description": row["description"],
            "debit": debit,
            "credit": credit,
            "balance": row["balance"],
            "page": row["page"],
            "bank": "Bank Rakyat",
            "source_file": source_filename,
        })

    return results


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_rakyat(pdf, source_filename=""):
    # Extract opening balance from FULL document
    full_text = ""
    for p in pdf.pages:
        full_text += (p.extract_text() or "") + "\n"

    opening_balance = extract_opening_balance(full_text)

    raw_rows = extract_raw_rows(pdf)

    return apply_balance_delta(raw_rows, opening_balance, source_filename)
