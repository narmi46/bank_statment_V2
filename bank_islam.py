# bank_islam.py
# Bank Islam – Integrated v2
# - Robust opening balance extraction
# - Correct first debit/credit
# - Table parser + PyMuPDF fallback

import re
import fitz
from datetime import datetime


# ---------------------------------------------------------
# helpers
# ---------------------------------------------------------

def clean_amount(val):
    """Parse amounts like 1,234.56, -1,234.56, (1,234.56), and values split by whitespace."""
    try:
        s = str(val).strip()
        if not s:
            return None

        # normalize: "2,798,424. 00" -> "2,798,424.00"
        s = re.sub(r"(\d)\.\s+(\d{2})\b", r"\1.\2", s)

        neg = False
        if s.startswith("(") and s.endswith(")"):
            neg = True
            s = s[1:-1].strip()

        # keep a leading '-' sign (or a '-' anywhere before digits)
        if "-" in s:
            neg = True
        s = s.replace("-", "")

        s = s.replace(",", "").strip()
        if not s:
            return None

        val_f = float(s)
        return -val_f if neg else val_f
    except Exception:
        return None


def parse_date(raw):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None

def normalize_amount_text(s: str) -> str:
    """Fix PDF text quirks that break amount regex matching."""
    if not s:
        return ""
    # collapse whitespace/newlines
    s = " ".join(str(s).split())
    # normalize split decimals: "2,798,424. 00" -> "2,798,424.00"
    s = re.sub(r"(\d)\.\s+(\d{2})\b", r"\1.\2", s)
    return s


def pdf_has_negative_amount(pdf) -> bool:
    """Detect if statement contains negative amounts (common in overdraft)."""
    try:
        for pg in pdf.pages:
            t = normalize_amount_text(pg.extract_text() or "")
            if re.search(r"-\d{1,3}(?:,\d{3})*\.\d{2}\b", t):
                return True
    except Exception:
        pass
    return False


def extract_opening_balance(text):
    """
    Supports:
    - Opening Balance (MYR) 55,142.10
    - BAL B/F 12,289.62
    """
    patterns = [
        r"Opening Balance\s*\(MYR\)\s*(-?[\d,]+\.\d{2})",
        r"BAL\s*B/F\s*(-?[\d,]+\.\d{2})",
        r"BALANCE\s*B/F\s*(-?[\d,]+\.\d{2})",
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return clean_amount(m.group(1))

    return None


# ---------------------------------------------------------
# v1-style TABLE PARSER (balance-driven)
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    rows = []

    # --- extract opening balance from FIRST PAGE ---
    first_page_text = normalize_amount_text(pdf.pages[0].extract_text() or "")
    opening_balance = extract_opening_balance(first_page_text)
    prev_balance = opening_balance

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row or len(row) < 3:
                    continue

                row_text = normalize_amount_text(" ".join(str(c) for c in row if c))

                # Skip BAL B/F row (already used as opening balance)
                if re.search(r"\bBAL\s*B/F\b", row_text, re.IGNORECASE):
                    continue

                date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", row_text)
                if not date_match:
                    continue

                amounts = re.findall(r"-?[\d,]+\.\d{2}", row_text)
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
                    "bank": "Bank Islam",
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

    # --- opening balance from first page ---
    first_page_text = normalize_amount_text(doc[0].get_text())
    prev_balance = extract_opening_balance(first_page_text)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_text = normalize_amount_text(" ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0])))

            if re.search(r"\bBAL\s*B/F\b", row_text, re.IGNORECASE):
                continue

            date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", row_text)
            if not date_match:
                continue

            amounts = re.findall(r"-?[\d,]+\.\d{2}", row_text)
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
                "bank": "Bank Islam",
                "source_file": source_filename,
            })

    return results


# ---------------------------------------------------------
# MAIN ENTRY
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    # 1️⃣ Try table-based parsing first
    rows = parse_with_tables(pdf, source_filename)

    # If the PDF contains negative amounts (overdraft), table extraction sometimes drops the
    # negative-balance cell. In that case, prefer the PyMuPDF word-based parser.
    if rows and pdf_has_negative_amount(pdf) and not any(r.get("balance", 0) < 0 for r in rows):
        rows = []

    # 2️⃣ Fallback to PyMuPDF if tables fail / look incomplete
    if not rows:
        rows = parse_with_pymupdf(pdf, source_filename)

    return rows
