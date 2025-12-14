# rhb.py - Standalone RHB Bank Parser
import re

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from RHB Bank statement.
    Handles both 4-digit (2024) and 2-digit (24) year formats.
    """
    patterns = [
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        r'Statement\s+(?:Date|Period)[:\s]+\d{1,2}\s+[A-Za-z]+\s+(\d{4})',
        r'FOR\s+THE\s+PERIOD[:\s]+\d{1,2}\s+[A-Za-z]+\s+(\d{4})',
        r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{2,4})',
        r'(\d{2})/(\d{2})/(\d{2,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            for group in groups:
                if not group or not group.isdigit():
                    continue
                
                # Handle 4-digit year
                if len(group) == 4:
                    year = int(group)
                    if 2000 <= year <= 2100:
                        return str(year)
                
                # Handle 2-digit year
                elif len(group) == 2:
                    year_2digit = int(group)
                    if 0 <= year_2digit <= 99:
                        year = 2000 + year_2digit
                        return str(year)
    
    return None


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MONTH_MAP = {
    'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
    'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
    'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
}

SKIP_KEYWORDS = ['B/F BALANCE', 'C/F BALANCE', 'Total Count', 'Date', 
                 'Tarikh', 'Description', 'Debit', 'Credit', 'Balance']


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------

def clean_text(text):
    """Clean and normalize text"""
    if not text:
        return ""
    return ' '.join(text.split()).strip()


def parse_numbers(parts):
    """Extract numeric values from text parts"""
    numbers = []
    desc_parts = []
    
    for part in parts:
        clean = part.replace(',', '')
        if re.match(r'^\d+(\.\d{2})?$', clean):
            numbers.append(float(clean))
        else:
            desc_parts.append(part)
    
    return numbers, desc_parts


def determine_debit_credit(numbers, description):
    """
    Determine debit and credit amounts from numbers and description.
    
    Args:
        numbers: List of numeric values found
        description: Transaction description
    
    Returns:
        tuple: (debit, credit, balance)
    """
    if len(numbers) < 1:
        return 0.0, 0.0, 0.0
    
    balance = numbers[-1]
    debit = 0.0
    credit = 0.0
    
    upper_desc = description.upper()
    
    if len(numbers) >= 4:
        # Format: serial, debit, credit, balance
        debit = numbers[-3]
        credit = numbers[-2]
    elif len(numbers) >= 3:
        # Format: serial, amount, balance
        amount = numbers[-2]
        
        # Determine type based on keywords
        if any(kw in upper_desc for kw in ['CR', 'CREDIT', 'DEPOSIT', 'INWARD', 'CDT', 'P2P CR']):
            credit = amount
        elif any(kw in upper_desc for kw in ['DR', 'DEBIT', 'WITHDRAWAL', 'FEES', 'TRF DR']):
            debit = amount
        else:
            # Default based on description pattern
            if 'TRF DR' in upper_desc or upper_desc.endswith(' DR'):
                debit = amount
            else:
                credit = amount
    elif len(numbers) == 2:
        # Format: amount, balance
        amount = numbers[-2]
        
        if any(kw in upper_desc for kw in ['CR', 'CREDIT', 'DEPOSIT', 'INWARD']):
            credit = amount
        else:
            debit = amount
    
    return debit, credit, balance


# ---------------------------------------------------------
# Main Parser
# ---------------------------------------------------------

def parse_transactions_rhb(pdf, source_filename=""):
    """
    Main parser for RHB Bank statements.
    Automatically extracts year and parses all transactions.
    
    Args:
        pdf: pdfplumber PDF object
        source_filename: Name of the source file
    
    Returns:
        List of transaction dictionaries
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
    
    # Process all pages
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Match transaction line: DD Mon DESCRIPTION...
            date_match = re.match(
                r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(.+)',
                line,
                re.IGNORECASE
            )
            
            if not date_match:
                i += 1
                continue
            
            day = date_match.group(1).zfill(2)
            month = date_match.group(2).capitalize()
            month_num = MONTH_MAP.get(month, '01')
            rest = date_match.group(3).strip()
            
            # Skip control lines
            if any(skip in rest for skip in SKIP_KEYWORDS):
                i += 1
                continue
            
            # Parse the rest of the line
            parts = rest.split()
            numbers, desc_parts = parse_numbers(parts)
            
            if len(numbers) < 1:
                i += 1
                continue
            
            # Build initial description
            description = ' '.join(desc_parts)
            
            # Look ahead for continuation lines
            j = i + 1
            continuation_lines = []
            
            while j < len(lines) and j < i + 10:
                next_line = lines[j].strip()
                
                # Stop if we hit another date line
                if re.match(r'^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)',
                           next_line, re.IGNORECASE):
                    break
                
                # Stop on empty lines
                if not next_line:
                    j += 1
                    continue
                
                # Stop on table headers
                if any(h in next_line for h in SKIP_KEYWORDS):
                    break
                
                # Stop if line is all numbers
                if re.match(r'^[\d,.\s]+$', next_line):
                    j += 1
                    continue
                
                # Add as continuation
                continuation_lines.append(next_line)
                j += 1
            
            # Combine description with continuations
            if continuation_lines:
                full_desc = description + ' ' + ' '.join(continuation_lines)
            else:
                full_desc = description
            
            full_desc = clean_text(full_desc)
            
            # Determine debit/credit/balance
            debit, credit, balance = determine_debit_credit(numbers, full_desc)
            
            # Format date
            iso_date = f"{year}-{month_num}-{day}"
            
            # Add transaction
            if full_desc:
                all_transactions.append({
                    "date": iso_date,
                    "description": full_desc,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_num,
                    "source_file": source_filename,
                    "bank": "RHB Bank"
                })
            
            # Move to next transaction
            i = j if j > i else i + 1
    
    return all_transactions
