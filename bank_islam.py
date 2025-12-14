# bank_islam.py
# Bank Islam – Integrated v1 (table) + simple balance parser

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


# ---------------------------------------------------------
# v1-style TABLE PARSER (but balance-driven)
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    rows = []

    # detect year + opening balance
    full_text = ""
    for p in pdf.pages[:2]:
        full_text += (p.extract_text() or "") + "\n"

    opening_balance = None
    m = re.search(r"Opening Balance\s*\(MYR\)\s*([\d,]+\.\d{2})", full_text)
    if m:
        opening_balance = clean_amount(m.group(1))

    prev_balance = opening_balance

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row or len(row) < 5:
                    continue

                row_text = " ".join(str(c) for c in row if c)

                date_match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", row_text)
                if not date_match:
                    continue

                amounts = re.findall(r"[\d,]+\.\d{2}", row_text)
                if not amounts:
                    continue

                balance = clean_amount(amounts[-1])
                if balance is None:
                    continue

                iso_date = parse_date(date_match.group())
                if not iso_date:
                    continue

                desc = row_text.replace(date_match.group(), "")
                desc = desc.replace(amounts[-1], "")
                desc = " ".join(desc.split())

                debit = credit = 0.0
                if prev_balance is not None:
                    delta = round(balance - prev_balance, 2)
                    if delta > 0:
                        credit = delta
                    elif delta < 0:
                        debit = abs(delta)

                prev_balance = balance

                rows.append({
                    "date": iso_date,
                    "description": desc,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_no,
                    "bank": "Bank Islam",
                    "source_file": source_filename,
                })

    return rows


# ---------------------------------------------------------
# PyMuPDF FALLBACK (simple version)
# ---------------------------------------------------------

def parse_with_pymupdf(pdf, source_filename):
    results = []

    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    prev_balance = None

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_text = " ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0]))

            date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", row_text)
            if not date_match:
                continue

            amounts = re.findall(r"[\d,]+\.\d{2}", row_text)
            if not amounts:
                continue

            balance = clean_amount(amounts[-1])
            iso_date = parse_date(date_match.group())

            if balance is None or not iso_date:
                continue

            desc = row_text.replace(date_match.group(), "")
            desc = desc.replace(amounts[-1], "")
            desc = " ".join(desc.split())

            debit = credit = 0.0
            if prev_balance is not None:
                delta = round(balance - prev_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            prev_balance = balance

            results.append({
                "date": iso_date,
                "description": desc,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_index + 1,
                "bank": "Bank Islam",
                "source_file": source_filename,
            })

    return results


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    # 1️⃣ try v1-style table parsing
    rows = parse_with_tables(pdf, source_filename)

    # 2️⃣ fallback if table parsing fails
    if not rows:
        rows = parse_with_pymupdf(pdf, source_filename)

    return rows
