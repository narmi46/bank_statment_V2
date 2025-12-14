# bank_islam.py
# FINAL – Bank Islam balance-driven parser (first row FIXED)

import re
import fitz
from datetime import datetime

DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})")
AMT_RE = re.compile(r"[\d,]+\.\d{2}")


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
# TABLE PARSER (v1-style, balance-based)
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    results = []
    prev_balance = None

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                row_text = " ".join(str(c) for c in row if c)

                date_match = DATE_RE.search(row_text)
                if not date_match:
                    continue

                amounts = AMT_RE.findall(row_text)
                if not amounts:
                    continue

                balance = clean_amount(amounts[-1])
                date = parse_date(date_match.group())
                if balance is None or not date:
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
                    "date": date,
                    "description": desc,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_no,
                    "bank": "Bank Islam",
                    "source_file": source_filename,
                })

    return results


# ---------------------------------------------------------
# PyMuPDF FALLBACK PARSER
# ---------------------------------------------------------

def parse_with_pymupdf(pdf, source_filename):
    results = []

    pdf.stream.seek(0)
    doc = fitz.open(stream=pdf.stream.read(), filetype="pdf")

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

            date_match = DATE_RE.search(row_text)
            if not date_match:
                continue

            amounts = AMT_RE.findall(row_text)
            if not amounts:
                continue

            balance = clean_amount(amounts[-1])
            date = parse_date(date_match.group())
            if balance is None or not date:
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
                "date": date,
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
# 🔥 FINAL FIX – FIRST TRANSACTION PATCH
# ---------------------------------------------------------

def fix_first_transaction(results):
    if len(results) < 2:
        return

    first = results[0]
    second = results[1]

    if first["debit"] == 0.0 and first["credit"] == 0.0:
        delta = round(second["balance"] - first["balance"], 2)
        if delta > 0:
            first["credit"] = abs(delta)
        elif delta < 0:
            first["debit"] = abs(delta)


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    results = parse_with_tables(pdf, source_filename)

    if not results:
        results = parse_with_pymupdf(pdf, source_filename)

    # 🔧 APPLY FINAL FIX
    fix_first_transaction(results)

    return results
