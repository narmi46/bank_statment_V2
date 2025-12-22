# bank_islam_v3_column_based.py
# Bank Islam – Column-Based Parser with Overdraft Support
# - Reads Debit/Credit amounts directly from statement columns
# - Handles negative balances (overdraft)
# - More accurate than delta-based calculation

import re
import fitz
from datetime import datetime


# ---------------------------------------------------------
# helpers
# ---------------------------------------------------------

def clean_amount(val):
    """Parse amount, handling commas and negatives."""
    try:
        if val is None or val == '':
            return 0.0
        cleaned = str(val).replace(",", "").strip()
        is_negative = '-' in cleaned
        cleaned = cleaned.replace('-', '').replace('+', '')
        amount = float(cleaned) if cleaned else 0.0
        return -amount if is_negative else amount
    except Exception:
        return 0.0


def parse_date(raw):
    """Parse date in various formats."""
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_opening_balance(text):
    """Extract opening balance from statement header."""
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


def is_negative_balance(row_text, balance_str):
    """Check if balance is negative by looking for minus sign near it."""
    balance_pos = row_text.rfind(balance_str)
    if balance_pos > 0:
        # Check 15 chars before and after for minus
        start = max(0, balance_pos - 15)
        end = min(len(row_text), balance_pos + len(balance_str) + 15)
        context = row_text[start:end]
        # Check if minus is close to balance (not part of other amounts)
        if '-' in context:
            # Make sure minus is within 3 chars of balance
            balance_context = row_text[max(0, balance_pos-3):balance_pos+len(balance_str)+3]
            if '-' in balance_context:
                return True
    return False


# ---------------------------------------------------------
# COLUMN-BASED TABLE PARSER
# ---------------------------------------------------------

def parse_with_tables(pdf, source_filename):
    """
    Parse statement by reading debit/credit columns directly.
    Bank Islam format typically has columns:
    No | Date | Ref | Code | Desc | Ref2 | Branch | Debit | Credit | Balance | Name | Details
    """
    rows = []

    # Extract opening balance
    first_page_text = pdf.pages[0].extract_text() or ""
    opening_balance = extract_opening_balance(first_page_text)

    for page_no, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        if not tables:
            continue

        for table in tables:
            for row in table:
                if not row or len(row) < 5:
                    continue

                row_text = " ".join(str(c) if c else "" for c in row)

                # Skip header rows and BAL B/F
                if re.search(r"\b(Transaction Date|BAL\s*B/F)\b", row_text, re.IGNORECASE):
                    continue

                # Find date
                date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", row_text)
                if not date_match:
                    continue

                iso_date = parse_date(date_match.group())
                if not iso_date:
                    continue

                # Extract all amounts from row
                amounts = re.findall(r"[\d,]+\.\d{2}", row_text)
                if len(amounts) < 1:
                    continue

                # Bank Islam typical structure:
                # Last amount = Balance
                # Second last = Credit (if exists)
                # Third last = Debit (if exists)
                
                balance_str = amounts[-1]
                balance = clean_amount(balance_str)
                
                # Check for negative balance
                if is_negative_balance(row_text, balance_str):
                    balance = -abs(balance)

                # Determine debit and credit
                debit = 0.0
                credit = 0.0

                # Look for debit/credit in remaining amounts
                if len(amounts) >= 3:
                    # Could have both debit and credit columns
                    # Typically: [..., debit, credit, balance]
                    potential_credit = clean_amount(amounts[-2])
                    potential_debit = clean_amount(amounts[-3])
                    
                    # Heuristic: larger amount is usually the transaction amount
                    if potential_credit > potential_debit:
                        credit = potential_credit
                    elif potential_debit > 0:
                        debit = potential_debit
                    
                elif len(amounts) >= 2:
                    # Only one transaction amount
                    transaction_amount = clean_amount(amounts[-2])
                    
                    # Determine if debit or credit by checking balance change
                    if opening_balance is not None:
                        # Simple check: if transaction amount + previous = new balance, it's credit
                        # This is still a heuristic but better than nothing
                        pass
                    
                    # Look for keywords to determine debit/credit
                    if re.search(r"\b(DR|DEBIT|CHARGE|PAYMENT|TRANSFER TO)\b", row_text, re.IGNORECASE):
                        debit = transaction_amount
                    else:
                        credit = transaction_amount

                # Build description (remove date and amounts)
                desc = row_text
                desc = desc.replace(date_match.group(), "")
                for amt in amounts:
                    desc = desc.replace(amt, "")
                desc = desc.replace('-', '')
                desc = " ".join(desc.split())

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
# IMPROVED PYMUPDF PARSER
# ---------------------------------------------------------

def parse_with_pymupdf(pdf, source_filename):
    """PyMuPDF fallback with column-based approach."""
    results = []

    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Extract opening balance
    first_page_text = doc[0].get_text()
    opening_balance = extract_opening_balance(first_page_text)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        # Group words by row (y-coordinate)
        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_words = sorted(rows[y], key=lambda x: x[0])
            row_text = " ".join(t[1] for t in row_words)

            if re.search(r"\b(Transaction Date|BAL\s*B/F)\b", row_text, re.IGNORECASE):
                continue

            date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", row_text)
            if not date_match:
                continue

            amounts = re.findall(r"[\d,]+\.\d{2}", row_text)
            if not amounts:
                continue

            iso_date = parse_date(date_match.group())
            if not iso_date:
                continue

            # Extract balance (last amount)
            balance_str = amounts[-1]
            balance = clean_amount(balance_str)
            if is_negative_balance(row_text, balance_str):
                balance = -abs(balance)

            # Extract debit/credit
            debit = credit = 0.0
            if len(amounts) >= 3:
                potential_credit = clean_amount(amounts[-2])
                potential_debit = clean_amount(amounts[-3])
                if potential_credit > potential_debit:
                    credit = potential_credit
                elif potential_debit > 0:
                    debit = potential_debit
            elif len(amounts) >= 2:
                transaction_amount = clean_amount(amounts[-2])
                if re.search(r"\b(DR|DEBIT|CHARGE|PAYMENT)\b", row_text, re.IGNORECASE):
                    debit = transaction_amount
                else:
                    credit = transaction_amount

            # Clean description
            desc = row_text
            desc = desc.replace(date_match.group(), "")
            for amt in amounts:
                desc = desc.replace(amt, "")
            desc = desc.replace('-', '')
            desc = " ".join(desc.split())

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
    """Main parser entry point."""
    # Try table-based parsing first
    rows = parse_with_tables(pdf, source_filename)

    # Fallback to PyMuPDF if tables fail
    if not rows:
        rows = parse_with_pymupdf(pdf, source_filename)

    return rows
