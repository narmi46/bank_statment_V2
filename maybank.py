import re
import fitz  # PyMuPDF
from datetime import datetime
import os

DATE_DDMM_RE = re.compile(r"^\d{2}/\d{2}$")  # Maybank often prints date as DD/MM (no year)
YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Money formats like:
#  0.10, .10, 10.00, 1,234.56
AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}$")
ZERO_RE = re.compile(r"^0?\.00$")

def _open_pymupdf_doc(pdf_input):
    """Open PDF robustly from file path OR pdfplumber object with .stream"""
    if isinstance(pdf_input, str):
        if os.path.exists(pdf_input):
            return fitz.open(pdf_input)
        raise FileNotFoundError(f"PDF not found on disk: {pdf_input}")

    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        pdf_bytes = pdf_input.stream.read()
        if not pdf_bytes:
            raise ValueError("PDF stream is empty after seek()")
        return fitz.open(stream=pdf_bytes, filetype="pdf")

    raise ValueError("Unsupported PDF input type (expected file path or pdfplumber PDF with .stream)")

def _is_amount(token: str) -> bool:
    token = token.strip()
    return bool(AMOUNT_RE.match(token)) and not bool(ZERO_RE.match(token))

def _to_float(token: str) -> float:
    return float(token.replace(",", ""))

def _normalize_date_ddmm(ddmm: str, year: str) -> str:
    """Return ISO date YYYY-MM-DD from DD/MM + year."""
    try:
        dt = datetime.strptime(f"{ddmm}/{year}", "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ddmm  # fallback

def parse_transactions_maybank(pdf_input, source_filename):
    """
    Maybank parser using the SAME robust method as Muamalat:
    - Extract words with coordinates (PyMuPDF)
    - Date = anchor
    - Same Y-line = same transaction row
    - Right-most amount = balance
    - Debit/Credit decided by balance delta
    - ISO date output for correct monthly summary in app.py
    """

    doc = _open_pymupdf_doc(pdf_input)

    transactions = []
    seen = set()

    previous_balance = None
    statement_year = None
    bank_name = "Maybank"

    # -------- Pass 1: detect year & bank name (header scan) --------
    # We scan a few first pages for a year; if none, fallback to current year.
    for p in range(min(2, len(doc))):
        header_text = doc[p].get_text("text")[:3000].upper()
        if "MAYBANK ISLAMIC" in header_text:
            bank_name = "Maybank Islamic"
        elif "MAYBANK" in header_text:
            bank_name = "Maybank"

        m = YEAR_RE.search(header_text)
        if m:
            statement_year = m.group(1)
            break

    if not statement_year:
        statement_year = str(datetime.now().year)

    # -------- Main parsing: word-level row extraction --------
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1

        words = page.get_text("words")
        # (x0, y0, x1, y1, text, block_no, line_no, word_no)
        rows = []
        for w in words:
            x0, y0, x1, y1, text, *_ = w
            text = str(text).strip()
            if not text:
                continue
            rows.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text})

        # Sort top->bottom, left->right
        rows.sort(key=lambda r: (round(r["y0"], 1), r["x0"]))

        # Find anchors (DD/MM). We’ll parse row-by-row using y grouping.
        Y_TOL = 2.0

        i = 0
        while i < len(rows):
            token = rows[i]["text"]

            if not DATE_DDMM_RE.match(token):
                i += 1
                continue

            date_ddmm = token
            y_ref = rows[i]["y0"]

            # Collect all words on the same line
            same_line = [r for r in rows if abs(r["y0"] - y_ref) <= Y_TOL]
            same_line.sort(key=lambda r: r["x0"])

            # Build description: take non-amount tokens excluding the date itself
            desc_tokens = []
            amount_items = []  # (x0, amount_str)

            for r in same_line:
                t = r["text"]
                if t == date_ddmm:
                    continue

                if _is_amount(t):
                    amount_items.append((r["x0"], t))
                else:
                    # keep non-numeric tokens (words, refs, etc.)
                    desc_tokens.append(t)

            # If we can’t find any amount tokens, it might be a broken row; skip.
            if not amount_items:
                i += 1
                continue

            # Most reliable: right-most amount = balance
            amount_items.sort(key=lambda x: x[0])
            balance_str = amount_items[-1][1]
            balance = _to_float(balance_str)

            # Candidate txn amount: the closest amount left of balance (if exists)
            txn_amount = None
            if len(amount_items) >= 2:
                txn_amount = _to_float(amount_items[-2][1])

            # Clean description
            description = " ".join(desc_tokens)
            description = " ".join(description.split()).strip()
            if not description:
                description = "UNKNOWN"

            # Skip summary-ish lines if any (common in statements)
            up = description.upper()
            if any(k in up for k in ["MONTHLY SUMMARY", "TOTAL", "SUBTOTAL", "BALANCE B/F", "BALANCE C/F"]):
                i += 1
                continue

            iso_date = _normalize_date_ddmm(date_ddmm, statement_year)

            # Decide debit/credit by balance delta (authoritative)
            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = abs(delta)
                elif delta < 0:
                    debit = abs(delta)
                else:
                    # If balance didn't change, fallback to txn_amount (rare, but happens with display quirks)
                    if txn_amount is not None:
                        # If statement prints "CR" in text, treat as credit; else debit.
                        if up.startswith("CR") or "CREDIT" in up:
                            credit = txn_amount
                        else:
                            debit = txn_amount
            else:
                # First transaction on first encountered balance
                if txn_amount is not None:
                    if up.startswith("CR") or "CREDIT" in up:
                        credit = txn_amount
                    else:
                        debit = txn_amount

            previous_balance = balance

            sig = (iso_date, description[:60], round(debit, 2), round(credit, 2), round(balance, 2))
            if sig in seen:
                i += 1
                continue
            seen.add(sig)

            transactions.append({
                "date": iso_date,
                "description": description[:120],
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
