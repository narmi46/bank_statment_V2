"""
Maybank Islamic Bank Statement Parser
Extracts: Balance and First Line Description Only
Compatible with existing app.py structure
"""

import re
from datetime import datetime


def parse_transactions_maybank_islamic(pdf, source_filename):
    """
    Parse Maybank Islamic statement.
    Only extracts balance and first line of description.
    Determines debit/credit based on balance changes from opening balance.
    
    Args:
        pdf: pdfplumber PDF object
        source_filename: Name of the source PDF file
        
    Returns:
        List of transaction dictionaries
    """
    
    transactions = []
    opening_balance = None
    previous_balance = None
    statement_year = None
    
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        
        lines = text.split('\n')
        
        # Extract statement year from first page header
        if page_num == 1 and statement_year is None:
            for line in lines[:30]:
                # Look for date pattern in header (e.g., "31/01/25" or "January 2025")
                year_match = re.search(r'20\d{2}', line)
                if year_match:
                    statement_year = year_match.group(0)
                    break
                # Look for short year format
                date_match = re.search(r'/(\d{2})\s*$', line)
                if date_match and int(date_match.group(1)) <= 99:
                    year_short = date_match.group(1)
                    statement_year = f"20{year_short}"
                    break
        
        if not statement_year:
            statement_year = "2025"  # Default fallback
        
        # Extract opening balance from first page
        if page_num == 1 and opening_balance is None:
            for i, line in enumerate(lines):
                if 'BEGINNING BALANCE' in line.upper():
                    # Try to extract balance from same line
                    balance_match = re.search(r'([\d,]+\.\d{2})', line)
                    if balance_match:
                        opening_balance = float(balance_match.group(1).replace(',', ''))
                    else:
                        # Check next few lines
                        for j in range(i+1, min(i+3, len(lines))):
                            balance_match = re.search(r'([\d,]+\.\d{2})', lines[j])
                            if balance_match:
                                opening_balance = float(balance_match.group(1).replace(',', ''))
                                break
                    
                    if opening_balance:
                        previous_balance = opening_balance
                        
                        # Add opening balance as first transaction
                        transactions.append({
                            'date': '',
                            'description': 'BEGINNING BALANCE',
                            'debit': 0.00,
                            'credit': 0.00,
                            'balance': round(opening_balance, 2),
                            'page': page_num,
                            'bank': 'Maybank Islamic',
                            'source_file': source_filename
                        })
                    break
        
        # Parse transaction lines
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines, headers, and footer text
            if not line or any(skip in line.upper() for skip in [
                'ENTRY DATE', 'VALUE DATE', 'TRANSACTION DESCRIPTION',
                'TRANSACTION AMOUNT', 'STATEMENT BALANCE', 'TARIKH',
                'BUTIR URUSNIAGA', 'JUMLAH', 'BAKI', 'PAGE', 'MUKA',
                'ACCOUNT NUMBER', 'NOMBOR AKAUN', 'PROTECTED BY PIDM'
            ]):
                i += 1
                continue
            
            # Match transaction pattern: DD/MM followed by content
            match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
            
            if match:
                date_str = match.group(1)
                rest_of_line = match.group(2).strip()
                
                # Extract all monetary values (amounts with 2 decimal places)
                numbers = re.findall(r'([\d,]+\.\d{2})([+-])?', rest_of_line)
                
                if len(numbers) >= 1:
                    # Last number is always the balance
                    balance_str = numbers[-1][0].replace(',', '')
                    balance = float(balance_str)
                    
                    # Transaction amount (if present, it's second-to-last number)
                    transaction_amount = 0.00
                    has_explicit_amount = False
                    
                    if len(numbers) >= 2:
                        transaction_amount = float(numbers[-2][0].replace(',', ''))
                        has_explicit_amount = True
                    
                    # Extract description - everything before the first number
                    first_num_pos = rest_of_line.find(numbers[0][0])
                    description = rest_of_line[:first_num_pos].strip()
                    
                    # If description is too short, check next line(s) for continuation
                    if len(description) < 5 and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        
                        # Check if next line is a continuation (not a new transaction)
                        if not re.match(r'^\d{2}/\d{2}', next_line) and next_line:
                            # Take only the FIRST line of description
                            desc_candidate = next_line.split('\n')[0].strip()
                            
                            # Make sure it's not a number or amount
                            if not re.match(r'^[\d,]+\.\d{2}', desc_candidate):
                                # Clean any trailing amounts from description
                                desc_candidate = re.sub(r'\s*[\d,]+\.\d{2}[+-]?\s*$', '', desc_candidate)
                                if desc_candidate:
                                    description = desc_candidate
                                    i += 1  # Skip the description line we just used
                    
                    # Clean description: remove any embedded amounts
                    description = re.sub(r'[\d,]+\.\d{2}[+-]?', '', description)
                    description = ' '.join(description.split())  # Normalize whitespace
                    
                    # Truncate to first line if multi-line somehow got through
                    if '\n' in description:
                        description = description.split('\n')[0].strip()
                    
                    # Limit length
                    description = description[:100] if description else 'TRANSACTION'
                    
                    # Determine debit or credit based on balance change
                    debit = 0.00
                    credit = 0.00
                    
                    if previous_balance is not None:
                        balance_change = balance - previous_balance
                        
                        if balance_change > 0:
                            # Balance increased = Credit (money in)
                            credit = transaction_amount if has_explicit_amount else abs(balance_change)
                        elif balance_change < 0:
                            # Balance decreased = Debit (money out)
                            debit = transaction_amount if has_explicit_amount else abs(balance_change)
                        # If balance_change == 0, both remain 0.00
                    else:
                        # Fallback: use explicit amount if available
                        if has_explicit_amount:
                            # Check for +/- indicator
                            if len(numbers) >= 2 and numbers[-2][1] == '+':
                                credit = transaction_amount
                            elif len(numbers) >= 2 and numbers[-2][1] == '-':
                                debit = transaction_amount
                            else:
                                # Use keywords in description
                                desc_upper = description.upper()
                                credit_keywords = ['DEPOSIT', 'TRANSFER TO', 'CREDIT', 'PAYMENT INTO', 
                                                 'INTER-BANK PAYMENT INTO', 'CDM CASH DEPOSIT']
                                debit_keywords = ['TRANSFER FR', 'PAYMENT FR', 'WITHDRAWAL', 'CHARGE',
                                                'DEBIT', 'PAYMENT DEBIT']
                                
                                if any(kw in desc_upper for kw in credit_keywords):
                                    credit = transaction_amount
                                elif any(kw in desc_upper for kw in debit_keywords):
                                    debit = transaction_amount
                                else:
                                    # Default: assume debit for safety
                                    debit = transaction_amount
                    
                    # Convert date to full format (DD/MM/YYYY)
                    try:
                        full_date_str = f"{date_str}/{statement_year}"
                        date_obj = datetime.strptime(full_date_str, "%d/%m/%Y")
                        formatted_date = date_obj.strftime("%Y-%m-%d")
                    except Exception:
                        # Fallback to manual parsing
                        day, month = date_str.split('/')
                        formatted_date = f"{statement_year}-{month.zfill(2)}-{day.zfill(2)}"
                    
                    # Add transaction to list
                    transactions.append({
                        'date': formatted_date,
                        'description': description,
                        'debit': round(debit, 2),
                        'credit': round(credit, 2),
                        'balance': round(balance, 2),
                        'page': page_num,
                        'bank': 'Maybank Islamic',
                        'source_file': source_filename
                    })
                    
                    # Update previous balance for next iteration
                    previous_balance = balance
            
            i += 1
    
    return transactions
