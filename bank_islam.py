# bank_islam.py - Standalone Bank Islam Parser
import re

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from Bank Islam statement.
    Handles both 4-digit (2024) and 2-digit (24) year formats.
    """
    # Try specific patterns first (most reliable)
    
    # Pattern 1: STATEMENT DATE : 30/09/24
    match = re.search(r'(?:STATEMENT DATE|TARIKH PENYATA)\s*[:\s]+\d{1,2}/\d{1,2}/(\d{2,4})', text, re.IGNORECASE)
    if match:
        year_str = match.group(1)
        if len(year_str) == 4:
            return year_str
        elif len(year_str) == 2:
            return str(2000 + int(year_str))
    
    # Pattern 2: Statement Date: DD/MM/YYYY
    match = re.search(r'Statement\s+(?:Date|Period)[:\s]+\d{1,2}/\d{1,2}/(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Pattern 3: FOR THE PERIOD : DD/MM/YYYY
    match = re.search(r'FOR\s+THE\s+PERIOD[:\s]+\d{1,2}/\d{1,2}/(\d{4})', text, re.IGNORECASE)
    if match:
        return match.group(1)
    
    # Pattern 4: YYYY Statement
    match = re.search(r'(\d{4})\s+Statement', text, re.IGNORECASE)
    if match:
        year = int(match.group(1))
        if 2000 <= year <= 2100:
            return str(year)
    
    return None


# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------

def clean_amount(value):
    """Convert string amount to float, handle empty values"""
    if not value or value == "-":
        return 0.0
    # Remove commas and convert to float
    clean_val = str(value).replace(",", "").strip()
    try:
        return float(clean_val)
    except ValueError:
        return 0.0


def format_date(date_raw, year):
    """
    Normalize date format to YYYY-MM-DD.
    Handles DD/MM/YYYY and DD/MM formats.
    """
    if not date_raw:
        return f"{year}-01-01"
    
    # Handle DD/MM/YYYY format
    if re.match(r"\d{2}/\d{2}/\d{4}", date_raw):
        dd, mm, yyyy = date_raw.split("/")
        return f"{yyyy}-{mm}-{dd}"
    
    # Handle DD/MM format (no year)
    if re.match(r"\d{2}/\d{2}", date_raw):
        dd, mm = date_raw.split("/")
        return f"{year}-{mm}-{dd}"
    
    # Return as-is if already formatted
    return date_raw


# ---------------------------------------------------------
# Main Parser
# ---------------------------------------------------------

def parse_bank_islam(pdf, source_filename=""):
    """
    Main parser for Bank Islam statements.
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
    
    # Process all pages
    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        
        if not tables:
            continue
        
        for table in tables:
            # Skip malformed tables
            if not table or len(table) < 2:
                continue
            
            # Skip header row
            for row in table[1:]:
                if len(row) < 10:
                    continue
                
                (
                    no,
                    date_raw,
                    eft_no,
                    code,
                    desc,
                    ref_no,
                    branch,
                    debit_raw,
                    credit_raw,
                    balance_raw
                ) = row[:10]
                
                # Skip invalid rows
                if not date_raw or "Total" in str(no):
                    continue
                
                # Format date
                date_fmt = format_date(date_raw, detected_year)
                
                # Clean description
                description = " ".join(str(desc).split())
                
                # Parse amounts
                debit = clean_amount(debit_raw)
                credit = clean_amount(credit_raw)
                balance = clean_amount(balance_raw)
                
                all_transactions.append({
                    "date": date_fmt,
                    "description": description,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_num,
                    "source_file": source_filename,
                    "bank": "Bank Islam"
                })
    
    return all_transactions
