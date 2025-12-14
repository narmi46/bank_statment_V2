# rhb.py - Comprehensive RHB Bank Parser
import re

# ---------------------------------------------------------
# YEAR EXTRACTION - IMPROVED
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from RHB Bank statement.
    Handles multiple formats found in different RHB statements.
    """
    # Pattern 1: "Statement Period / Tempoh Penyata : 7 Mar 24 – 31 Mar 24"
    match = re.search(r'Statement Period[^:]*:\s*\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2,4})', text, re.IGNORECASE)
    if match:
        year_str = match.group(2)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return str(2000 + int(year_str))
    
    # Pattern 2: "1 Jan 25 – 31 Jan 25"
    match = re.search(r'\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2,4})\s*[–-]', text, re.IGNORECASE)
    if match:
        year_str = match.group(2)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return str(2000 + int(year_str))
    
    # Pattern 3: "01 February 2025 28 February 2025" (for Reflex statements)
    match = re.search(r'\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(2)
    
    # Pattern 4: Statement date in header
    match = re.search(r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})', text, re.IGNORECASE)
    if match:
        year_str = match.group(1)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return str(2000 + int(year_str))
    
    return None


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MONTH_MAP = {
    'Jan': '01', 'January': '01',
    'Feb': '02', 'February': '02',
    'Mar': '03', 'March': '03',
    'Apr': '04', 'April': '04',
    'May': '05',
    'Jun': '06', 'June': '06',
    'Jul': '07', 'July': '07',
    'Aug': '08', 'August': '08',
    'Sep': '09', 'September': '09',
    'Oct': '10', 'October': '10',
    'Nov': '11', 'November': '11',
    'Dec': '12', 'December': '12'
}


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------

def clean_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    return ' '.join(text.split()).strip()


def parse_amount(amount_str):
    """Parse amount string, handling negative balances with - suffix"""
    if not amount_str:
        return 0.0
    
    amount_str = str(amount_str).strip()
    
    # Handle amounts with trailing minus (like "845,425.30-")
    is_negative = amount_str.endswith('-')
    amount_str = amount_str.rstrip('-').strip()
    
    # Remove commas and parse
    amount_str = amount_str.replace(',', '')
    
    try:
        amount = float(amount_str)
        return -amount if is_negative else amount
    except ValueError:
        return 0.0


# ---------------------------------------------------------
# FORMAT 1: Reflex Cash Management (Table format like FEB 2025)
# ---------------------------------------------------------

def parse_reflex_format(text, page_num, year, source_filename):
    """
    Parse Reflex Cash Management format.
    Example: "02. FEB 2025-RHB.pdf"
    """
    transactions = []
    lines = text.split('\n')
    
    # Find lines that start with dates in DD-MM-YYYY format
    for i, line in enumerate(lines):
        # Match pattern: 05-02-2025 or similar date formats
        date_match = re.match(r'^(\d{2})-(\d{2})-(\d{4})\s+(.+)', line)
        if not date_match:
            continue
        
        day, month, year_in_line, rest = date_match.groups()
        
        # Skip header lines
        if 'Date' in rest or 'Branch' in rest:
            continue
        
        # Parse the rest of the line
        parts = rest.split()
        
        # Try to find amounts in the line
        amounts = []
        for part in parts:
            clean = part.replace(',', '').rstrip('-')
            if re.match(r'^\d+(\.\d{2})?$', clean):
                amounts.append(parse_amount(part))
        
        if len(amounts) >= 2:
            # Last amount is balance, second-to-last might be DR/CR
            balance = amounts[-1]
            amount = amounts[-2] if len(amounts) >= 2 else 0.0
            
            # Determine debit/credit based on keywords
            upper_line = rest.upper()
            debit = 0.0
            credit = 0.0
            
            if 'PAYMENT' in upper_line or 'AUTODEBIT' in upper_line or 'CHGS' in upper_line or 'CHG' in upper_line or 'FEE' in upper_line or 'CHARGED' in upper_line:
                debit = abs(amount)
            elif 'INWARD' in upper_line or 'AUTOCREDIT' in upper_line:
                credit = abs(amount)
            else:
                # Default logic based on amount sign
                if amount < 0:
                    debit = abs(amount)
                else:
                    credit = abs(amount)
            
            # Extract description (everything before amounts)
            desc_parts = []
            for part in parts:
                if not re.match(r'^[\d,.-]+$', part):
                    desc_parts.append(part)
                else:
                    break
            
            description = ' '.join(desc_parts)
            
            transactions.append({
                "date": f"{year_in_line}-{month}-{day}",
                "description": clean_text(description),
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "source_file": source_filename,
                "bank": "RHB Bank"
            })
    
    return transactions


# ---------------------------------------------------------
# FORMAT 2: Standard Account Statement (like 3 March 2024)
# ---------------------------------------------------------

def parse_standard_format(text, page_num, year, source_filename):
    """
    Parse standard RHB account statement format.
    Example: "3 March 2024 Statement.pdf"
    Uses table with columns: Date, Description, Cheque/Serial No, Debit, Credit, Balance
    """
    transactions = []
    lines = text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Match date at start: "07 Mar" or "07 Mar B/F BALANCE"
        date_match = re.match(r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(.+)', line, re.IGNORECASE)
        
        if not date_match:
            i += 1
            continue
        
        day = date_match.group(1).zfill(2)
        month_abbr = date_match.group(2).capitalize()
        month_num = MONTH_MAP.get(month_abbr, '01')
        rest = date_match.group(3).strip()
        
        # Skip B/F BALANCE and C/F BALANCE
        if 'B/F BALANCE' in rest or 'C/F BALANCE' in rest:
            i += 1
            continue
        
        # Parse description and amounts
        parts = rest.split()
        
        # Find all numbers in the line
        numbers = []
        desc_parts = []
        found_numbers = False
        
        for part in parts:
            clean = part.replace(',', '')
            if re.match(r'^\d+(\.\d{2})?$', clean):
                numbers.append(float(clean))
                found_numbers = True
            elif not found_numbers:
                desc_parts.append(part)
        
        # Look ahead for continuation lines
        j = i + 1
        continuation_lines = []
        while j < len(lines) and j < i + 5:
            next_line = lines[j].strip()
            
            # Stop if we hit another date line
            if re.match(r'^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', next_line, re.IGNORECASE):
                break
            
            # Stop on empty lines or table headers
            if not next_line or 'Date' in next_line or 'Tarikh' in next_line:
                j += 1
                continue
            
            # Check if this line has numbers (amounts)
            line_parts = next_line.split()
            has_amount = False
            for part in line_parts:
                clean = part.replace(',', '')
                if re.match(r'^\d+(\.\d{2})?$', clean):
                    if not has_amount:  # First number found
                        numbers.append(float(clean))
                        has_amount = True
                    else:
                        numbers.append(float(clean))
            
            if has_amount:
                # Extract description from this line (before numbers)
                for part in line_parts:
                    clean = part.replace(',', '')
                    if not re.match(r'^\d+(\.\d{2})?$', clean):
                        continuation_lines.append(part)
                    else:
                        break
                j += 1
                break
            else:
                continuation_lines.append(next_line)
            
            j += 1
        
        # Build full description
        full_desc = ' '.join(desc_parts + continuation_lines)
        full_desc = clean_text(full_desc)
        
        # Determine debit, credit, balance
        if len(numbers) >= 2:
            # Last is balance
            balance = numbers[-1]
            
            # Check if we have 3 numbers (serial, amount, balance) or 4 (serial, debit, credit, balance)
            if len(numbers) >= 3:
                amount = numbers[-2]
                
                # Determine if debit or credit based on keywords
                upper_desc = full_desc.upper()
                debit = 0.0
                credit = 0.0
                
                if 'DR' in upper_desc or 'TRF DR' in upper_desc or 'WITHDRAWAL' in upper_desc or 'MYDEBIT' in upper_desc:
                    debit = amount
                elif 'CR' in upper_desc or 'TRF CR' in upper_desc or 'DEPOSIT' in upper_desc or 'INWARD' in upper_desc:
                    credit = amount
                else:
                    # Default: assume credit for positive flow
                    credit = amount
                
                if full_desc:
                    transactions.append({
                        "date": f"{year}-{month_num}-{day}",
                        "description": full_desc,
                        "debit": debit,
                        "credit": credit,
                        "balance": balance,
                        "page": page_num,
                        "source_file": source_filename,
                        "bank": "RHB Bank"
                    })
        
        i = j if j > i else i + 1
    
    return transactions


# ---------------------------------------------------------
# MAIN PARSER
# ---------------------------------------------------------

def parse_transactions_rhb(pdf, source_filename=""):
    """
    Main parser for RHB Bank statements.
    Detects format and routes to appropriate parser.
    """
    all_transactions = []
    detected_year = None
    
    # Extract year from first few pages
    for page in pdf.pages[:3]:
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break
    
    # Fallback to current year
    if not detected_year:
        from datetime import datetime
        detected_year = str(datetime.now().year)
    
    year = int(detected_year)
    
    # Detect format by checking first page
    first_page_text = pdf.pages[0].extract_text() or ""
    
    # Check for Reflex format
    is_reflex = 'Reflex Cash Management' in first_page_text or 'TRANSACTION STATEMENT' in first_page_text
    
    # Check for standard format
    is_standard = 'ACCOUNT ACTIVITY / AKTIVITI AKAUN' in first_page_text or 'Statement Period' in first_page_text
    
    # Process all pages
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        
        if is_reflex:
            tx = parse_reflex_format(text, page_num, year, source_filename)
        else:
            tx = parse_standard_format(text, page_num, detected_year, source_filename)
        
        all_transactions.extend(tx)
    
    return all_transactions
