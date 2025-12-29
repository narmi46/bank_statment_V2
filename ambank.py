"""
AmBank Statement Parser
Extracts transactions from AmBank Islamic Berhad statements

Features:
---------
- Extracts date, description, debit, credit, and balance for each transaction
- Handles cheque numbers (6-digit format)
- Automatically determines debit vs credit based on transaction type keywords
- Cleans up descriptions by removing numbers and extra formatting
- Supports multi-page statements
- Sorts transactions chronologically

Transaction Format:
------------------
AmBank statements use the format: DDMon [cheque] description [amount] balance
Examples:
  - 01Mar Fund Transfer /DEBIT TRANSFER, PALANIAPPAN..., 300.00 501,857.62
  - 01Mar DuitNow CR TRF /MISC CREDIT, USAHA MAJU..., 11,764.88 513,622.50
  - 04Mar INW AMI CHQ /CHQ PRESENTED, , 702058, 702058 275,900.72 39,453.80

Usage:
------
    import pdfplumber
    from ambank import parse_ambank
    
    with pdfplumber.open('statement.pdf') as pdf:
        transactions = parse_ambank(pdf, 'statement.pdf')
    
    for tx in transactions:
        print(f"{tx['date']}: {tx['description']} - "
              f"Debit: {tx['debit']}, Credit: {tx['credit']}, Balance: {tx['balance']}")

Output Format:
-------------
Each transaction is a dictionary with:
    {
        'date': 'DD/MM/YYYY',
        'description': 'Transaction description',
        'debit': float,
        'credit': float,
        'balance': float,
        'page': int,
        'bank': 'AmBank Islamic',
        'source_file': 'filename.pdf',
        'cheque_no': 'XXXXXX' (optional, only if cheque involved)
    }
"""

import re
from datetime import datetime
import pdfplumber


def parse_ambank(pdf, filename):
    """
    Parse AmBank statement and extract all transactions.
    
    Args:
        pdf: pdfplumber PDF object
        filename: Source filename for tracking
        
    Returns:
        List of transaction dictionaries
    """
    transactions = []
    
    # Extract statement period and account info from first page
    statement_info = extract_statement_info(pdf)
    
    for page_num, page in enumerate(pdf.pages, start=1):
        page_text = page.extract_text()
        
        if not page_text:
            continue
            
        # Extract transactions from this page
        page_transactions = extract_transactions_from_page(
            page_text, 
            page_num, 
            filename,
            statement_info
        )
        
        transactions.extend(page_transactions)
    
    # Sort by date
    transactions = sort_transactions(transactions)
    
    return transactions


def extract_statement_info(pdf):
    """Extract account number and statement period from first page."""
    info = {
        'account_number': None,
        'statement_period': None,
        'currency': 'MYR'
    }
    
    try:
        first_page = pdf.pages[0].extract_text()
        
        # Extract account number
        acc_match = re.search(r'ACCOUNT NO\..*?:\s*(\d+)', first_page)
        if acc_match:
            info['account_number'] = acc_match.group(1)
        
        # Extract statement date range
        date_match = re.search(r'STATEMENT DATE.*?:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})', first_page)
        if date_match:
            info['statement_period'] = f"{date_match.group(1)} to {date_match.group(2)}"
            
    except Exception as e:
        print(f"Warning: Could not extract statement info: {e}")
    
    return info


def extract_transactions_from_page(page_text, page_num, filename, statement_info):
    """Extract all transactions from a single page."""
    transactions = []
    
    # Split into lines
    lines = page_text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip headers, footers, and irrelevant lines
        if should_skip_line(line):
            i += 1
            continue
        
        # Try to parse transaction starting at this line
        transaction, lines_consumed = parse_transaction_block(
            lines[i:], 
            page_num, 
            filename,
            statement_info
        )
        
        if transaction:
            transactions.append(transaction)
            i += lines_consumed
        else:
            i += 1
    
    return transactions


def should_skip_line(line):
    """Check if line should be skipped."""
    skip_patterns = [
        r'^ACCOUNT NO\.',
        r'^STATEMENT DATE',
        r'^CURRENCY',
        r'^PAGE',
        r'^ACCOUNT STATEMENT',
        r'^PENYATA AKAUN',
        r'^Protected by PIDM',
        r'^Dilindungi oleh PIDM',
        r'^AmBank Islamic',
        r'^A member of',
        r'^P\.O\. Box',
        r'^Tel :',
        r'^Email :',
        r'^\d{4}_\d{4}$',
        r'^DATE$',
        r'^TARIKH$',
        r'^CHEQUE NO\.$',
        r'^NO\. CEK$',
        r'^TRANSACTION$',
        r'^TRANSAKSI$',
        r'^DEBIT$',
        r'^CREDIT$',
        r'^KREDIT$',
        r'^BALANCE$',
        r'^BAKI$',
        r'^CATEGORY$',
        r'^KATEGORI$',
        r'^OPENING BALANCE',
        r'^BAKI PEMBUKAAN',
        r'^TOTAL DEBITS',
        r'^TOTAL CREDITS',
        r'^CLOSING BALANCE',
        r'^CHEQUES NOT CLEARED',
        r'^Baki Bawa Ke Hadapan',
        r'^Balance b/f',
        r'^\s*$'
    ]
    
    for pattern in skip_patterns:
        if re.match(pattern, line):
            return True
    
    return False


def parse_transaction_block(lines, page_num, filename, statement_info):
    """
    Parse a transaction block that may span multiple lines.
    
    Returns:
        (transaction_dict or None, lines_consumed)
    """
    if not lines or len(lines) == 0:
        return None, 0
    
    first_line = lines[0].strip()
    
    # Transaction line pattern: starts with date (DDMar format)
    date_match = re.match(r'^(\d{2})(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(.+)$', first_line)
    
    if not date_match:
        return None, 1
    
    day = date_match.group(1)
    month = date_match.group(2)
    rest_of_line = date_match.group(3).strip()
    
    # Parse the rest of the transaction
    transaction = parse_transaction_details(
        day, month, rest_of_line, lines, 
        page_num, filename, statement_info
    )
    
    if transaction:
        # Determine how many lines this transaction consumed
        description = transaction.get('description', '')
        lines_consumed = 1
        
        # Multi-line descriptions are rare but possible
        # Most transactions are single line in AmBank format
        
        return transaction, lines_consumed
    
    return None, 1


def parse_transaction_details(day, month, rest_of_line, lines, page_num, filename, statement_info):
    """Parse transaction details from the line components."""
    
    # Extract year from statement info (use 2024 as default based on the sample)
    year = "2024"
    if statement_info.get('statement_period'):
        year_match = re.search(r'/(\d{4})', statement_info['statement_period'])
        if year_match:
            year = year_match.group(1)
    
    # Convert date to standard format
    month_map = {
        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
    }
    
    date_str = f"{day}/{month_map[month]}/{year}"
    
    # Extract all monetary amounts (format: 123,456.78 or 456.78)
    numbers = re.findall(r'[\d,]+\.\d{2}', rest_of_line)
    
    # Clean and prepare description
    description = rest_of_line
    
    # Remove all numbers from description
    for num in numbers:
        description = description.replace(num, '').strip()
    
    # Extract and store cheque number if present (6-digit number)
    cheque_match = re.search(r'\b(\d{6})\b', description)
    cheque_no = cheque_match.group(1) if cheque_match else None
    
    # Remove cheque numbers from description
    if cheque_no:
        description = re.sub(r'\b\d{6}\b', '', description).strip()
    
    # Clean up description
    description = re.sub(r'\s+', ' ', description)  # Multiple spaces to single
    description = re.sub(r',+\s*,+', ',', description)  # Multiple commas to single
    description = re.sub(r',\s*$', '', description)  # Trailing commas
    description = re.sub(r'^\s*,\s*', '', description)  # Leading commas
    description = description.strip()
    
    # Parse amounts based on transaction type
    # AmBank format analysis:
    # - Balance is ALWAYS the last number on the line
    # - If 2 numbers: [amount] [balance] - amount is either debit or credit
    # - If 3 numbers: [debit] [credit] [balance] - rare case
    # - If 1 number: [balance] only - opening balance or special entry
    
    debit = 0.0
    credit = 0.0
    balance = None
    
    if len(numbers) >= 1:
        # Last number is always the balance
        balance = float(numbers[-1].replace(',', ''))
        
        if len(numbers) == 3:
            # Rare case: debit, credit, balance
            debit = float(numbers[0].replace(',', ''))
            credit = float(numbers[1].replace(',', ''))
        elif len(numbers) == 2:
            # Most common: [transaction_amount] [balance]
            # Determine if it's debit or credit based on keywords
            amount = float(numbers[0].replace(',', ''))
            
            # Credit transaction indicators
            credit_keywords = [
                'CR TRF', 'CREDIT', 'KREDIT', 'INWARD IBG', 'INWARD AMI',
                'HIBAH', 'PROFIT', 'OUTWARD CLEARING', 'CHQ DEPOSIT',
                'MISC CREDIT', 'LOCAL CHQ DEPOSIT', 'CTL OUTWARD'
            ]
            
            # Check if this is a credit transaction
            desc_upper = description.upper()
            is_credit = any(keyword in desc_upper for keyword in credit_keywords)
            
            if is_credit:
                credit = amount
            else:
                debit = amount
        # else: len(numbers) == 1, which means only balance (opening balance, etc.)
    
    # Build transaction dictionary
    transaction = {
        'date': date_str,
        'description': description,
        'debit': round(debit, 2),
        'credit': round(credit, 2),
        'balance': round(balance, 2) if balance is not None else None,
        'page': page_num,
        'bank': 'AmBank Islamic',
        'source_file': filename
    }
    
    # Add cheque number if present
    if cheque_no:
        transaction['cheque_no'] = cheque_no
    
    return transaction


def sort_transactions(transactions):
    """Sort transactions by date."""
    try:
        for tx in transactions:
            # Parse date for sorting
            tx['_date_obj'] = datetime.strptime(tx['date'], '%d/%m/%Y')
        
        # Sort by date
        transactions = sorted(transactions, key=lambda x: x['_date_obj'])
        
        # Remove temporary date object
        for tx in transactions:
            del tx['_date_obj']
            
    except Exception as e:
        print(f"Warning: Could not sort transactions: {e}")
    
    return transactions


def parse_amount(amount_str):
    """Parse amount string to float."""
    if not amount_str or amount_str.strip() == '':
        return 0.0
    
    try:
        # Remove commas and convert
        cleaned = amount_str.replace(',', '').strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0
