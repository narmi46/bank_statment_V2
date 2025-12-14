# maybank.py - Standalone Maybank Parser
import re

# ============================================================
# YEAR EXTRACTION FROM PDF
# ============================================================

def extract_year_from_text(text):
    """
    Extract year from Maybank statement text.
    Looks for common patterns like 'Statement Date', 'Period', etc.
    Handles both 4-digit (2024) and 2-digit (24) year formats.
    """
    patterns = [
        # Pattern for "STATEMENT DATE : 30/09/24" or "TARIKH PENYATA : 30/09/24"
        r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})',
        # Pattern for "Statement Date: DD Mon YYYY" 
        r'Statement\s+(?:Date|Period)[:\s]+\d{1,2}\s+[A-Za-z]+\s+(\d{4})',
        # Pattern for "YYYY Statement"
        r'(\d{4})\s+Statement',
        # Pattern for "Mon YYYY"
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
        # Pattern for DD/MM/YYYY format
        r'(\d{2})/(\d{2})/(\d{4})',
        # Pattern for DD/MM/YY format (2-digit year)
        r'(\d{2})/(\d{2})/(\d{2})(?!\d)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            # Find the year in groups
            for group in groups:
                if not group or not group.isdigit():
                    continue
                
                # Handle 4-digit year
                if len(group) == 4:
                    year = int(group)
                    if 2000 <= year <= 2100:
                        return str(year)
                
                # Handle 2-digit year (assume 2000s)
                elif len(group) == 2:
                    year_2digit = int(group)
                    # Convert 2-digit to 4-digit (00-99 -> 2000-2099)
                    if 0 <= year_2digit <= 99:
                        year = 2000 + year_2digit
                        return str(year)
    
    return None


# ============================================================
# UNIVERSAL CLEANER FOR MAYBANK TEXT
# ============================================================

def clean_maybank_line(line):
    """Remove invisible unicode and normalize spaces"""
    if not line:
        return ""
    
    # Remove invisible unicode junk
    line = line.replace("\u200b", "")   # zero-width space
    line = line.replace("\u200e", "")   # LTR mark
    line = line.replace("\u200f", "")   # RTL mark
    line = line.replace("\ufeff", "")   # BOM
    line = line.replace("\xa0", " ")    # non-breaking space
    
    # Collapse multiple spaces
    line = re.sub(r"\s+", " ", line)
    
    return line.strip()


# ============================================================
# MAYBANK MTASB PATTERN (NO YEAR FORMAT: DD/MM)
# ============================================================

PATTERN_MAYBANK_MTASB = re.compile(
    r"(\d{2}/\d{2})\s+"                 # Date: 01/08
    r"(.+?)\s+"                         # Description
    r"([0-9,]+\.\d{2})\s*([+-])\s*"     # Amount + Sign (tolerant spacing)
    r"([0-9,]+\.\d{2})"                 # Balance
)

def parse_line_maybank_mtasb(line, page_num, year):
    """Parse MTASB format: DD/MM DESCRIPTION AMOUNT +/- BALANCE"""
    m = PATTERN_MAYBANK_MTASB.search(line)
    if not m:
        return None
    
    date_raw, desc, amount_raw, sign, balance_raw = m.groups()
    day, month = date_raw.split("/")
    
    amount = float(amount_raw.replace(",", ""))
    balance = float(balance_raw.replace(",", ""))
    
    credit = amount if sign == "+" else 0.0
    debit = amount if sign == "-" else 0.0
    
    # Format: YYYY-MM-DD
    full_date = f"{year}-{month}-{day}"
    
    return {
        "date": full_date,
        "description": desc.strip(),
        "debit": debit,
        "credit": credit,
        "balance": balance,
        "page": page_num,
    }


# ============================================================
# MAYBANK MBB PATTERN (FULL DATE FORMAT: DD Mon YYYY)
# ============================================================

PATTERN_MAYBANK_MBB = re.compile(
    r"(\d{2})\s+([A-Za-z]{3})\s+(\d{4})\s+"  # Date
    r"(.+?)\s+"                               # Description
    r"([0-9,]+\.\d{2})\s*([+-])\s*"          # Amount + Sign
    r"([0-9,]+\.\d{2})"                      # Balance
)

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}

def parse_line_maybank_mbb(line, page_num):
    """Parse MBB format: DD Mon YYYY DESCRIPTION AMOUNT +/- BALANCE"""
    m = PATTERN_MAYBANK_MBB.search(line)
    if not m:
        return None
    
    day, mon_abbr, year, desc, amount_raw, sign, balance_raw = m.groups()
    month = MONTH_MAP.get(mon_abbr.title(), "01")
    
    amount = float(amount_raw.replace(",", ""))
    balance = float(balance_raw.replace(",", ""))
    
    credit = amount if sign == "+" else 0.0
    debit = amount if sign == "-" else 0.0
    
    # Format: YYYY-MM-DD
    full_date = f"{year}-{month}-{day}"
    
    return {
        "date": full_date,
        "description": desc.strip(),
        "debit": debit,
        "credit": credit,
        "balance": balance,
        "page": page_num,
    }


# ============================================================
# LINE RECONSTRUCTOR FOR BROKEN DESCRIPTIONS
# ============================================================

def reconstruct_broken_lines(lines):
    """
    Fixes broken DUITNOW / long descriptions that span multiple lines.
    Merges continuation lines with the main transaction line.
    """
    rebuilt = []
    buffer_line = ""
    
    for line in lines:
        line = clean_maybank_line(line)
        
        if not line:
            continue
        
        # If line begins with date, flush buffer and start new
        if re.match(r"^\d{2}/\d{2}", line) or re.match(r"^\d{2}\s+[A-Za-z]{3}\s+\d{4}", line):
            if buffer_line:
                rebuilt.append(buffer_line)
                buffer_line = ""
            buffer_line = line
        else:
            # Continuation of previous description
            buffer_line += " " + line
    
    if buffer_line:
        rebuilt.append(buffer_line)
    
    return rebuilt


# ============================================================
# MAIN PARSER ENTRY POINT
# ============================================================

def parse_transactions_maybank(pdf, source_filename=""):
    """
    Main parser for Maybank statements.
    Automatically extracts year from PDF and parses all transactions.
    
    Args:
        pdf: pdfplumber PDF object
        source_filename: Name of the source file for reference
    
    Returns:
        List of transaction dictionaries
    """
    all_transactions = []
    detected_year = None
    
    # Try to extract year from first few pages
    for page in pdf.pages[:3]:  # Check first 3 pages
        text = page.extract_text() or ""
        detected_year = extract_year_from_text(text)
        if detected_year:
            break
    
    # Fallback to current year if not detected
    if not detected_year:
        from datetime import datetime
        detected_year = str(datetime.now().year)
    
    # Process all pages
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        
        raw_lines = text.splitlines()
        cleaned_lines = [clean_maybank_line(l) for l in raw_lines]
        
        # Reconstruct broken lines
        lines = reconstruct_broken_lines(cleaned_lines)
        
        for line in lines:
            # Try MTASB format (DD/MM)
            tx = parse_line_maybank_mtasb(line, page_num, detected_year)
            if tx:
                tx["source_file"] = source_filename
                tx["bank"] = "Maybank"
                all_transactions.append(tx)
                continue
            
            # Try MBB format (DD Mon YYYY)
            tx = parse_line_maybank_mbb(line, page_num)
            if tx:
                tx["source_file"] = source_filename
                tx["bank"] = "Maybank"
                all_transactions.append(tx)
                continue
    
    return all_transactions
