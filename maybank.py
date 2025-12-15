"""
Maybank / Maybank Islamic Bank Statement Parser
Extracts: Balance and First Line Description Only
Compatible with app.py structure
"""

import re
from datetime import datetime


def parse_transactions_maybank(pdf, source_filename):
    """
    Parse Maybank/Maybank Islamic statement.
    Only extracts balance and first line of description.
    Determines debit/credit based on +/- indicators in transaction amount.
    
    Args:
        pdf: pdfplumber PDF object
        source_filename: Name of the source PDF file
        
    Returns:
        List of transaction dictionaries
    """
    
    transactions = []
    opening_balance = None
    statement_year = None
    bank_name = "Maybank"
    
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        
        lines = text.split('\n')
        
        # Detect bank name from header
        if page_num == 1:
            for line in lines[:10]:
                if 'MAYBANK ISLAMIC' in line.upper():
                    bank_name = "Maybank Islamic"
                    break
                elif 'MALAYAN BANKING' in line.upper() or 'MAYBANK' in line.upper():
                    bank_name = "Maybank"
                    break
        
        # Extract statement year from first page header
        if page_num == 1 and statement_year is None:
            for line in lines[:30]:
                # Look for statement date pattern
                if 'STATEMENT DATE' in line.upper() or 'TARIKH PENYATA' in line.upper():
                    year_match = re.search(r'20\d{2}', line)
                    if year_match:
                        statement_year = year_match.group(0)
                        break
                    # Look for DD/MM/YY format
                    date_match = re.search(r'\d{2}/\d{2}/(\d{2})', line)
                    if date_match:
                        statement_year = f"20{date_match.group(1)}"
                        break
                
                # Alternative: look for any 4-digit year in header
                if not statement_year:
                    year_match = re.search(r'20\d{2}', line)
                    if year_match:
                        statement_year = year_match.group(0)
                        break
        
        if not statement_year:
            statement_year = "2025"  # Default fallback
        
        # Extract opening balance from first page
        if page_num == 1 and opening_balance is None:
            for i, line in enumerate(lines):
                # Look for beginning/opening balance keywords
                if any(keyword in line.upper() for keyword in [
                    'BEGINNING BALANCE', 'OPENING BALANCE', 'BAKI PERMULAAN'
                ]):
                    # Try to extract balance from same line
                    balance_match = re.search(r'([\d,]+\.\d{2})', line)
                    if balance_match:
                        opening_balance = float(balance_match.group(1).replace(',', ''))
                    else:
                        # Check next few lines
                        for j in range(i+1, min(i+5, len(lines))):
                            balance_match = re.search(r'([\d,]+\.\d{2})', lines[j])
                            if balance_match:
                                opening_balance = float(balance_match.group(1).replace(',', ''))
                                break
                    
                    if opening_balance:
                        # Add opening balance as first transaction
                        transactions.append({
                            'date': '',
                            'description': 'BEGINNING BALANCE',
                            'debit': 0.00,
                            'credit': 0.00,
                            'balance': round(opening_balance, 2),
                            'page': page_num,
                            'bank': bank_name,
                            'source_file': source_filename
                        })
                    break
        
        # Parse transaction lines
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines, headers, and footer text
            skip_patterns = [
                'ENTRY DATE', 'VALUE DATE', 'TRANSACTION DESCRIPTION',
                'TRANSACTION AMOUNT', 'STATEMENT BALANCE', 'TARIKH MASUK',
                'TARIKH NILAI', 'BUTIR URUSNIAGA', 'JUMLAH URUSNIAGA',
                'BAKI PENYATA', 'PAGE', 'MUKA', 'ACCOUNT NUMBER', 
                'NOMBOR AKAUN', 'PROTECTED BY PIDM', 'LEDGER BALANCE',
                'ENDING BALANCE', 'TOTAL DEBIT', 'TOTAL CREDIT',
                'PROFIT OUTSTANDING', 'FCN'
            ]
            
            if not line or any(skip in line.upper() for skip in skip_patterns):
                i += 1
                continue
            
            # Match transaction pattern: DD/MM followed by content
            # Format: DD/MM description amount+/- balance
            match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
            
            if match:
                date_str = match.group(1)
                rest_of_line = match.group(2).strip()
                
                # Extract all monetary values with optional +/- signs
                # Pattern: 1,234.56+ or 1,234.56- or just 1,234.56 or .30-
                # Note: * allows zero or more digits before decimal (for amounts like .30)
                numbers = re.findall(r'([\d,]*\.\d{2})([+-])?', rest_of_line)
                
                if len(numbers) >= 1:
                    # Last number is always the statement balance (no sign)
                    balance_str = numbers[-1][0].replace(',', '')
                    balance = float(balance_str)
                    
                    # Extract description FIRST - everything before the first number
                    # This is critical to capture "REV" in "TRANSFER FR A/C REV"
                    first_num_pos = rest_of_line.find(numbers[0][0])
                    description = rest_of_line[:first_num_pos].strip()
                    
                    # Initialize transaction amounts
                    debit = 0.00
                    credit = 0.00
                    
                    # Check if there's a transaction amount (second-to-last number with +/- sign)
                    if len(numbers) >= 2:
                        transaction_amount_str = numbers[-2][0].replace(',', '')
                        transaction_amount = float(transaction_amount_str)
                        sign = numbers[-2][1]  # Will be '+', '-', or None
                        
                        if sign == '+':
                            # Explicit credit (money in)
                            credit = transaction_amount
                        elif sign == '-':
                            # Explicit debit (money out)
                            debit = transaction_amount
                        else:
                            # No sign - shouldn't happen in Maybank format, but handle it
                            # Use description keywords as fallback
                            desc_upper = description.upper()
                            
                            credit_keywords = [
                                'DEPOSIT', 'TRANSFER TO', 'TRANSFER INTO', 'CREDIT',
                                'PAYMENT INTO', 'INTER-BANK PAYMENT INTO', 
                                'CDM CASH DEPOSIT', 'CASH DEPOSIT', 'CR PYMT', 'CMS - CR'
                            ]
                            debit_keywords = [
                                'TRANSFER FR', 'TRANSFER FROM', 'PAYMENT FR',
                                'PAYMENT FROM', 'WITHDRAWAL', 'CHARGE', 'DEBIT',
                                'PAYMENT DEBIT', 'CASH WITHDRAWAL', 'DR DIRECT DEBIT',
                                'CMS - DR', 'ESI PAYMENT DEBIT', 'MAS PAYMENT',
                                'FOREIGN TT DR', 'NOSTRO CHARGE', 'CABLE CHARGE'
                            ]
                            
                            if any(kw in desc_upper for kw in credit_keywords):
                                credit = transaction_amount
                            elif any(kw in desc_upper for kw in debit_keywords):
                                debit = transaction_amount
                            else:
                                # Default: treat as debit if unclear
                                debit = transaction_amount
                    
                    # If description is too short/empty, check next line(s)
                    if len(description) < 5 and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        
                        # Check if next line is a continuation (not a new transaction)
                        if not re.match(r'^\d{2}/\d{2}', next_line) and next_line:
                            # Take only the FIRST line of description
                            desc_candidate = next_line.split('\n')[0].strip()
                            
                            # Make sure it's not just numbers or skip patterns
                            if (not re.match(r'^[\d,]+\.\d{2}', desc_candidate) and 
                                not any(skip in desc_candidate.upper() for skip in skip_patterns)):
                                # Clean any trailing amounts
                                desc_candidate = re.sub(r'\s*[\d,]+\.\d{2}[+-]?\s*$', '', desc_candidate)
                                if desc_candidate and len(desc_candidate) > 2:
                                    description = desc_candidate
                                    i += 1  # Skip the description line we just consumed
                    
                    # Clean description: remove any embedded amounts and normalize whitespace
                    description = re.sub(r'[\d,]+\.\d{2}[+-]?', '', description)
                    description = ' '.join(description.split())
                    
                    # Take only first line if somehow multi-line got through
                    if '\n' in description:
                        description = description.split('\n')[0].strip()
                    
                    # Limit description length
                    description = description[:100].strip() if description else 'TRANSACTION'
                    
                    # Convert date to full format (YYYY-MM-DD)
                    try:
                        full_date_str = f"{date_str}/{statement_year}"
                        date_obj = datetime.strptime(full_date_str, "%d/%m/%Y")
                        formatted_date = date_obj.strftime("%Y-%m-%d")
                    except Exception:
                        # Manual fallback parsing
                        try:
                            day, month = date_str.split('/')
                            formatted_date = f"{statement_year}-{month.zfill(2)}-{day.zfill(2)}"
                        except:
                            formatted_date = date_str  # Last resort
                    
                    # Add transaction to list
                    transactions.append({
                        'date': formatted_date,
                        'description': description,
                        'debit': round(debit, 2),
                        'credit': round(credit, 2),
                        'balance': round(balance, 2),
                        'page': page_num,
                        'bank': bank_name,
                        'source_file': source_filename
                    })
            
            i += 1
    
    return transactions
