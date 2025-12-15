import re
from datetime import datetime

def parse_transactions_maybank(pdf, source_filename):
    """
    Parse Maybank/Maybank Islamic statement.
    FIX 2.0:
    1. Stricter Deduplication: Ignores description, checks only (Date, Amount, Balance).
    2. Reversal Filter: Skips transactions labeled 'REV' to match Bank Totals.
    """
    
    transactions = []
    # Set to track unique financial signatures (date, debit, credit, balance)
    seen_signatures = set()
    
    opening_balance = None
    statement_year = None
    bank_name = "Maybank"
    
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue
        
        lines = text.split('\n')
        
        # --- Header Parsing (Bank Name, Year, Opening Balance) ---
        if page_num == 1:
            for line in lines[:10]:
                if 'MAYBANK ISLAMIC' in line.upper():
                    bank_name = "Maybank Islamic"
                    break
                elif 'MALAYAN BANKING' in line.upper() or 'MAYBANK' in line.upper():
                    bank_name = "Maybank"
                    break
        
        if page_num == 1 and statement_year is None:
            for line in lines[:30]:
                if 'STATEMENT DATE' in line.upper() or 'TARIKH PENYATA' in line.upper():
                    year_match = re.search(r'20\d{2}', line)
                    if year_match:
                        statement_year = year_match.group(0)
                        break
                    date_match = re.search(r'\d{2}/\d{2}/(\d{2})', line)
                    if date_match:
                        statement_year = f"20{date_match.group(1)}"
                        break
                if not statement_year:
                    year_match = re.search(r'20\d{2}', line)
                    if year_match:
                        statement_year = year_match.group(0)
                        break
        
        if not statement_year:
            statement_year = "2025"

        if page_num == 1 and opening_balance is None:
            for i, line in enumerate(lines):
                if any(keyword in line.upper() for keyword in ['BEGINNING BALANCE', 'OPENING BALANCE', 'BAKI PERMULAAN']):
                    balance_match = re.search(r'([\d,]+\.\d{2})', line)
                    if balance_match:
                        opening_balance = float(balance_match.group(1).replace(',', ''))
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
        
        # --- Transaction Parsing ---
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
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
            
            # Match Line starting with DD/MM
            match = re.match(r'^(\d{2}/\d{2})\s+(.+)', line)
            
            if match:
                date_str = match.group(1)
                rest_of_line = match.group(2).strip()
                
                # Extract all numbers (amounts and balance)
                numbers = re.findall(r'([\d,]*\.\d{2})([+-])?', rest_of_line)
                
                if len(numbers) >= 1:
                    balance_str = numbers[-1][0].replace(',', '')
                    balance = float(balance_str)
                    
                    # Extract description
                    first_num_pos = rest_of_line.find(numbers[0][0])
                    description = rest_of_line[:first_num_pos].strip()
                    
                    debit = 0.00
                    credit = 0.00
                    
                    if len(numbers) >= 2:
                        # Standard case: Transaction Amount + Balance
                        transaction_amount_str = numbers[-2][0].replace(',', '')
                        transaction_amount = float(transaction_amount_str)
                        sign = numbers[-2][1]
                        
                        if sign == '+':
                            credit = transaction_amount
                        elif sign == '-':
                            debit = transaction_amount
                        else:
                            # Fallback to keywords if no sign
                            desc_upper = description.upper()
                            credit_keywords = ['DEPOSIT', 'TRANSFER TO', 'TRANSFER INTO', 'CREDIT', 'PAYMENT INTO']
                            debit_keywords = ['TRANSFER FR', 'TRANSFER FROM', 'PAYMENT FR', 'WITHDRAWAL', 'DEBIT']
                            
                            if any(kw in desc_upper for kw in credit_keywords):
                                credit = transaction_amount
                            elif any(kw in desc_upper for kw in debit_keywords):
                                debit = transaction_amount
                            else:
                                debit = transaction_amount # Default
                    
                    # Handle multi-line descriptions
                    if len(description) < 5 and i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if not re.match(r'^\d{2}/\d{2}', next_line) and next_line:
                            desc_candidate = next_line.split('\n')[0].strip()
                            if not re.match(r'^[\d,]+\.\d{2}', desc_candidate):
                                desc_candidate = re.sub(r'\s*[\d,]+\.\d{2}[+-]?\s*$', '', desc_candidate)
                                if len(desc_candidate) > 2:
                                    description = desc_candidate
                                    i += 1
                    
                    # Cleanup Description
                    description = re.sub(r'[\d,]+\.\d{2}[+-]?', '', description)
                    description = ' '.join(description.split())[:100].strip() or 'TRANSACTION'
                    
                    # Date Formatting
                    try:
                        full_date_str = f"{date_str}/{statement_year}"
                        date_obj = datetime.strptime(full_date_str, "%d/%m/%Y")
                        formatted_date = date_obj.strftime("%Y-%m-%d")
                    except:
                        formatted_date = date_str

                    # --- FILTER: Skip 'REV' (Reversal) Transactions ---
                    # Reversals inflate totals and are usually ignored in Bank Summary
                    if "REV" in description.upper():
                        i += 1
                        continue

                    # --- FIX: STRICT DEDUPLICATION ---
                    # Signature excludes description. 
                    # Use (Date, Debit, Credit, Balance) as unique ID.
                    txn_signature = (formatted_date, debit, credit, balance)
                    
                    if txn_signature not in seen_signatures:
                        seen_signatures.add(txn_signature)
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
