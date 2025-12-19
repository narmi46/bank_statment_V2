"""
RHB Bank Statement Parser - Improved Version with Coordinate-Based Detection
=============================================================================

This module integrates with the Streamlit app.py and uses:
1. X-axis coordinate detection for Debit/Credit columns
2. Y-axis (date line) as reference point
3. Balance calculation as fallback verification
4. Opening balance (B/F BALANCE) as first transaction

Compatible with app.py interface: parse_transactions_rhb(pdf, source_file)
"""

import re
import datetime


def parse_transactions_rhb(pdf, source_file):
    """
    Parse RHB bank statements using coordinate-based column detection.
    
    This improved version uses X-Y coordinates from the PDF to accurately
    determine which column (Debit/Credit/Balance) each amount belongs to,
    with balance calculation as fallback.
    
    Args:
        pdf: pdfplumber PDF object (already opened)
        source_file (str): Source filename for reference
        
    Returns:
        list: List of transaction dictionaries with keys:
            - date: ISO format date string
            - description: Transaction description
            - debit: Debit amount (float)
            - credit: Credit amount (float)
            - balance: Account balance (float)
            - page: Page number
            - bank: Bank name ("RHB Bank")
            - source_file: Source PDF filename
    """
    transactions = []
    bank_name = "RHB Bank"

    # Regex patterns
    date_re = re.compile(r'^(\d{2})\s*([A-Za-z]{3})\b')
    num_re = re.compile(r'\d[\d,]*\.\d{2}')

    # -------------------------------------------------
    # Step 1: Detect YEAR from statement header
    # -------------------------------------------------
    year = None
    for page in pdf.pages[:1]:
        text = page.extract_text() or ""
        # Match patterns like "1 Jan 25 - 31 Jan 25" or "7 Mar 24 – 31 Mar 24"
        m = re.search(r'(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]\s*(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})', text)
        if m:
            year = int("20" + m.group(2))
    if not year:
        year = datetime.date.today().year

    # -------------------------------------------------
    # Step 2: Analyze column positions from headers
    # -------------------------------------------------
    debit_x_range = None
    credit_x_range = None
    balance_x_range = None
    date_x_max = 0
    
    # Extract words with coordinates from first page
    first_page = pdf.pages[0]
    words = first_page.extract_words()
    
    for word in words:
        text = word['text'].strip()
        x0, x1 = word['x0'], word['x1']
        
        # Find "Date"/"Tarikh" column position (for reference)
        if text.lower() in ['date', 'tarikh']:
            date_x_max = max(date_x_max, x1)
        
        # Find "Debit" column position
        if text.lower() == 'debit':
            debit_x_range = (x0 - 20, x1 + 80)  # Add tolerance
            
        # Find "Credit"/"Kredit" column position  
        elif text.lower() in ['credit', 'kredit']:
            credit_x_range = (x0 - 20, x1 + 80)
            
        # Find "Balance"/"Baki" column position
        elif text.lower() in ['balance', 'baki']:
            balance_x_range = (x0 - 20, x1 + 120)

    # -------------------------------------------------
    # Step 3: Parse transactions with coordinate detection
    # -------------------------------------------------
    prev_balance = None
    current = None
    pending_desc = []

    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        
        # Get words with coordinates for this page
        words = page.extract_words()
        
        # Build lookup: line text -> words in that line
        line_to_words = {}
        for word in words:
            word_text = word['text']
            # Find which line this word belongs to
            for line in lines:
                if word_text in line:
                    if line not in line_to_words:
                        line_to_words[line] = []
                    line_to_words[line].append(word)
                    break

        for line in lines:
            # Skip headers and footers
            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh", "Debit", "Credit",
                "Balance", "Baki", "ORDINARY CURRENT", "QARD CURRENT",
                "Total Count", "IMPORTANT NOTES", "Account Statement",
                "Page No", "Statement Period", "RHB"
            ]):
                continue

            # ------------------------------
            # DATE LINE (new transaction)
            # ------------------------------
            dm = date_re.match(line)
            if dm:
                # Flush previous transaction
                if current:
                    transactions.append(current)
                    prev_balance = current.get("balance", prev_balance)

                day, mon = dm.group(1), dm.group(2)
                try:
                    dt = datetime.datetime.strptime(f"{day}{mon}{year}", "%d%b%Y").date()
                    date_out = dt.isoformat()
                except Exception:
                    date_out = f"{day} {mon} {year}"

                # Handle B/F BALANCE (opening balance) - CREATE AS TRANSACTION
                if "B/F BALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in num_re.findall(line)]
                    if amts:
                        balance = amts[-1]
                        current = {
                            "date": date_out,
                            "description": "B/F BALANCE (Opening Balance)",
                            "debit": 0.0,
                            "credit": 0.0,
                            "balance": balance,
                            "page": page_idx,
                            "bank": bank_name,
                            "source_file": source_file
                        }
                        prev_balance = balance
                    pending_desc = []
                    continue
                    
                # Handle C/F BALANCE (closing balance) - UPDATE prev_balance only
                elif "C/F BALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in num_re.findall(line)]
                    if amts:
                        prev_balance = amts[-1]
                    current = None
                    pending_desc = []
                    continue

                # ------------------------------
                # Extract amounts using COORDINATES
                # ------------------------------
                debit = 0.0
                credit = 0.0
                balance = None
                
                # Get words for this specific line
                line_words = line_to_words.get(line, [])
                
                # Find all numeric amounts with X coordinates
                amounts_with_coords = []
                for word in line_words:
                    word_text = word['text'].replace(",", "")
                    if num_re.match(word_text):
                        try:
                            amt_value = float(word_text)
                            amounts_with_coords.append({
                                'value': amt_value,
                                'x': word['x0'],
                                'x1': word['x1'],
                                'text': word['text']
                            })
                        except:
                            pass
                
                # Sort by X coordinate (left to right)
                amounts_with_coords.sort(key=lambda x: x['x'])
                
                # Balance is ALWAYS the rightmost amount - extract it first
                if amounts_with_coords:
                    balance = amounts_with_coords[-1]['value']
                    # Remove balance from the list for debit/credit detection
                    transaction_amounts = amounts_with_coords[:-1] if len(amounts_with_coords) > 1 else []
                else:
                    transaction_amounts = []
                
                # METHOD 1: Assign based on X-coordinate ranges
                for amt_data in transaction_amounts:
                    x_mid = (amt_data['x'] + amt_data['x1']) / 2
                    val = amt_data['value']
                    
                    # Match to column based on X position
                    if debit_x_range and debit_x_range[0] <= x_mid <= debit_x_range[1]:
                        if debit == 0.0:  # Only assign first match
                            debit = val
                    elif credit_x_range and credit_x_range[0] <= x_mid <= credit_x_range[1]:
                        if credit == 0.0:
                            credit = val
                
                # METHOD 2 (Fallback): Check for CR/DR indicators in description
                if debit == 0.0 and credit == 0.0:
                    # Look for "CR" (credit) or "DR" (debit) indicators in the line
                    line_upper = line.upper()
                    has_cr_indicator = bool(re.search(r'\bCR\b', line_upper))
                    has_dr_indicator = bool(re.search(r'\bDR\b', line_upper))
                    
                    # If we have amounts and indicators, use them
                    if transaction_amounts and (has_cr_indicator or has_dr_indicator):
                        # Use first transaction amount (balance already extracted above)
                        amount_value = transaction_amounts[0]['value']
                        
                        if has_cr_indicator:
                            credit = amount_value
                        elif has_dr_indicator:
                            debit = amount_value
                
                # METHOD 3 (Final Fallback): Use balance calculation
                if debit == 0.0 and credit == 0.0 and balance is not None and prev_balance is not None:
                    diff = balance - prev_balance
                    if abs(diff) > 0.01:  # Tolerance for floating point
                        if diff > 0:
                            credit = abs(diff)
                        else:
                            debit = abs(diff)

                # Build description (remove date and amounts)
                desc = line
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "").replace(mon, "").strip()

                # Prepend buffered description (lines before date)
                if pending_desc:
                    desc = " ".join(pending_desc) + " " + desc
                    pending_desc = []

                current = {
                    "date": date_out,
                    "description": " ".join(desc.split()),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                }

            # ------------------------------
            # NON-DATE LINE (continuation)
            # ------------------------------
            else:
                # Skip service charge indicator rows
                if "SC DR" in line and num_re.search(line):
                    continue

                if current:
                    # Add to current transaction description
                    current["description"] = " ".join((current["description"] + " " + line).split())
                else:
                    # Buffer description lines before date (Islamic format)
                    pending_desc.append(line)

        # Flush last transaction on this page
        if current:
            transactions.append(current)
            prev_balance = current.get("balance", prev_balance)
            current = None

    return transactions
