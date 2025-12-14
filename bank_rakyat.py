# bank_rakyat.py
# Bank Rakyat – Balance-driven parser (Bank Islam style)

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
    """
    Bank Rakyat formats:
    - Opening Balance -243,353.66
    - Baki Permulaan -452,862.83
    """
    patterns = [
        r"Opening Balance\s*([\-]?\d[\d,]*\.\d{2})",
        r"Baki Permulaan\s*([\-]?\d[\d,]*\.\d{2})",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return clean_amount(m.group(1))

    return None


# ---------------------------------------------------------
# TABLE PARSER (balance-driven)
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    rows = []

    # --- opening balance from first page ---
    first_page_text = pdf.pages[0].extract_text() or ""
    prev_balance = extract_opening_balance(first_page_text)

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row:
                    continue

                row_text = " ".join(str(c) for c in row if c)

                # skip summary rows
                if re.search(r"(Baki Permulaan|Opening Balance|Baki Penutup)", row_text, re.I):
                    continue

                date_match = re.search(r"\d{2}/\d{2}/\d{4}", row_text)
                if not date_match:
                    continue

                amounts = re.findall(r"[+-]?\d[\d,]*\.\d{2}", row_text)
                if not amounts:
                    continue

                balance = clean_amount(amounts[-1])
                if balance is None:
                    continue

                iso_date = parse_date(date_match.group())
                if not iso_date:
                    continue

                desc = row_text
                desc = desc.replace(date_match.group(), "")
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
                    "bank": "Bank Rakyat",
                    "source_file": source_filename,
                })

    return rows


# ---------------------------------------------------------
# PyMuPDF FALLBACK (balance-driven)
# ---------------------------------------------------------

def parse_with_pymupdf(pdf, source_filename):
    results = []

    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    prev_balance = extract_opening_balance(doc[0].get_text())

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_text = " ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0]))

            if re.search(r"(Baki Permulaan|Opening Balance|Baki Penutup)", row_text, re.I):
                continue

            date_match = re.search(r"\d{2}/\d{2}/\d{4}", row_text)
            if not date_match:
                continue

            amounts = re.findall(r"[+-]?\d[\d,]*\.\d{2}", row_text)
            if not amounts:
                continue

            balance = clean_amount(amounts[-1])
            iso_date = parse_date(date_match.group())

            if balance is None or not iso_date:
                continue

            desc = row_text
            desc = desc.replace(date_match.group(), "")
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
                "bank": "Bank Rakyat",
                "source_file": source_filename,
            })

    return results


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_rakyat(pdf, source_filename=""):
    rows = parse_with_tables(pdf, source_filename)

    if not rows:
        rows = parse_with_pymupdf(pdf, source_filename)

    return rows
