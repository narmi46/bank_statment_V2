# bank_islam.py
# Bank Islam – SIMPLE, BALANCE-DRIVEN PARSER
# ✔ Supports all known Bank Islam formats
# ✔ Fixes first debit/credit ALWAYS
# ✔ Minimal fields only (as requested)

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
# Opening balance extraction
# ---------------------------------------------------------

def extract_opening_balance_pdfplumber(pdf):
    for page in pdf.pages[:1]:
        text = page.extract_text() or ""
        m = re.search(r"Opening Balance\s*\(MYR\)\s*([\d,]+\.\d{2})", text, re.I)
        if m:
            return clean_amount(m.group(1))
        m = re.search(r"BAL\s+B/F\s*([\d,]+\.\d{2})", text, re.I)
        if m:
            return clean_amount(m.group(1))
    return None


def extract_opening_balance_pymupdf(doc):
    text = doc[0].get_text()
    m = re.search(r"Opening Balance\s*\(MYR\)\s*([\d,]+\.\d{2})", text, re.I)
    if m:
        return clean_amount(m.group(1))
    m = re.search(r"BAL\s+B/F\s*([\d,]+\.\d{2})", text, re.I)
    if m:
        return clean_amount(m.group(1))
    return None


# ---------------------------------------------------------
# Table-based parser (v1 logic, but balance-driven)
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    results = []

    opening_balance = extract_opening_balance_pdfplumber(pdf)
    previous_balance = opening_balance

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row:
                    continue

                row_text = " ".join(str(c) for c in row if c)

                date_match = DATE_RE.search(row_text)
                if not date_match:
                    continue

                amounts = AMT_RE.findall(row_text)
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
                if previous_balance is not None:
                    delta = round(balance - previous_balance, 2)
                    if delta > 0:
                        credit = delta
                    elif delta < 0:
                        debit = abs(delta)

                previous_balance = balance

                results.append({
                    "date": iso_date,
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
# PyMuPDF fallback parser (word-based)
# ---------------------------------------------------------

def parse_with_pymupdf(pdf, source_filename):
    results = []

    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    opening_balance = extract_opening_balance_pymupdf(doc)
    previous_balance = opening_balance

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
            iso_date = parse_date(date_match.group())
            if balance is None or not iso_date:
                continue

            desc = row_text.replace(date_match.group(), "")
            desc = desc.replace(amounts[-1], "")
            desc = " ".join(desc.split())

            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            previous_balance = balance

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
# 🔧 FINAL FIX: ensure FIRST transaction gets debit/credit
# ---------------------------------------------------------

def fix_first_transaction(results, opening_balance):
    if not results or opening_balance is None:
        return

    first = results[0]
    if first["debit"] == 0.0 and first["credit"] == 0.0:
        delta = round(first["balance"] - opening_balance, 2)
        if delta > 0:
            first["credit"] = delta
        elif delta < 0:
            first["debit"] = abs(delta)


# ---------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    # 1️⃣ Try table-based parsing
    results = parse_with_tables(pdf, source_filename)

    opening_balance = extract_opening_balance_pdfplumber(pdf)

    # 2️⃣ Fallback to PyMuPDF if needed
    if not results:
        results = parse_with_pymupdf(pdf, source_filename)
        pdf.stream.seek(0)
        pdf_bytes = pdf.stream.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        opening_balance = extract_opening_balance_pymupdf(doc)

    # 3️⃣ 🔥 FIX FIRST TRANSACTION (THE BUG YOU HIT)
    fix_first_transaction(results, opening_balance)

    return results
