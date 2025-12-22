# cimb.py - Standalone CIMB Bank Parser
import re

# ---------------------------------------------------------
# YEAR EXTRACTION
# ---------------------------------------------------------

def extract_year_from_text(text):
    """
    Extract year from CIMB Bank statement.
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

def parse_float(value):
    """Converts string '1,234.56' to float 1234.56. Returns 0.0 if empty."""
    if not value:
        return 0.0
    clean_val = str(value).replace("\n", "").replace(" ", "").replace(",", "")
    if not re.match(r'^-?\d+(\.\d+)?$', clean_val):
        return 0.0
    return float(clean_val)


def clean_text(text):
    """Removes excess newlines from descriptions."""
    if not text:
        return ""
    return text.replace("\n", " ").strip()


def format_date(date_str, year):
    """
    Format date string to YYYY-MM-DD.
    Handles various CIMB date formats.
    """
    if not date_str:
        return f"{year}-01-01"
    
    date_str = clean_text(date_str)
    
    # Try DD/MM/YYYY format
    match = re.match(r'(\d{2})/(\d{2})/(\d{4})', date_str)
    if match:
        dd, mm, yyyy = match.groups()
        return f"{yyyy}-{mm}-{dd}"
    
    # Try DD/MM format (no year)
    match = re.match(r'(\d{2})/(\d{2})', date_str)
    if match:
        dd, mm = match.groups()
        return f"{year}-{mm}-{dd}"
    
    # Return as-is if already in YYYY-MM-DD format
    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        return date_str
    
    return f"{year}-01-01"


# ---------------------------------------------------------
# Main Parser
# ---------------------------------------------------------

def parse_transactions_cimb(pdf, source_filename=""):
    """
    Main parser for CIMB Bank statements.
    Automatically extracts year and parses all transactions.
    
    Args:
        pdf: pdfplumber PDF object
        source_filename: Name of the source file
    
    Returns:
        List of transaction dictionaries
    """
    all_transactions = []
    detected_year = None
    closing_balance = None
    
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
        # Extract table using grid lines
        table = page.extract_table()
        
        if not table:
            continue
        
        for row in table:
            # CIMB Structure: [Date, Desc, Ref, Withdrawal, Deposit, Balance]
            if not row or len(row) < 6:
                continue
            
            # Skip headers
            first_col = str(row[0]).lower() if row[0] else ""
            if "date" in first_col or "tarikh" in first_col:
                continue
            
            # Handle Opening Balance
            desc_text = str(row[1]).lower() if row[1] else ""
            if "opening balance" in desc_text:
                all_transactions.append({
                    "date": "",
                    "description": "OPENING BALANCE",
                    "ref_no": "",
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": parse_float(row[5]),
                    "page": page_num,
                    "source_file": source_filename,
                    "bank": "CIMB Bank"
                })
                continue
            
            # Capture Closing Balance
            if "closing balance" in desc_text or "baki penutup" in desc_text:
                closing_balance = parse_float(row[5])
                continue
            
            # Ensure valid balance exists
            if not row[5]:
                continue
            
            # Strict Column Mapping
            debit_val = parse_float(row[3])   # Col 3 is Withdrawal
            credit_val = parse_float(row[4])  # Col 4 is Deposit
            
            # Skip empty rows (sometimes descriptions spill over without money)
            if debit_val == 0.0 and credit_val == 0.0:
                continue
            
            # Format date
            date_formatted = format_date(row[0], detected_year)
            
            tx = {
                "date": date_formatted,
                "description": clean_text(row[1]),
                "ref_no": clean_text(row[2]),
                "debit": debit_val,
                "credit": credit_val,
                "balance": parse_float(row[5]),
                "page": page_num,
                "source_file": source_filename,
                "bank": "CIMB Bank"
            }
            all_transactions.append(tx)
    
    # Add closing balance as a special transaction for reference
    if closing_balance is not None and all_transactions:
        all_transactions.append({
            "date": "",
            "description": "CLOSING BALANCE",
            "ref_no": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": closing_balance,
            "page": page_num,
            "source_file": source_filename,
            "bank": "CIMB Bank"
        })
    
    return all_transactions
