import re
import pdfplumber
from datetime import datetime

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def _clean_amount(x: str):
    if x is None:
        return None
    # Remove commas, currency symbols, and spaces
    x = x.strip().replace(",", "").replace(" ", "").replace("MYR", "")
    if not x:
        return None
    # Handle negative amounts in parentheses
    if x.startswith("(") and x.endswith(")"):
        x = "-" + x[1:-1]
    # Validate it is a valid decimal number
    try:
        float(x)
        return x
    except ValueError:
        return None

# ---------------------------------------------------
# Regex for Summary Data
# ---------------------------------------------------
SUMMARY_DEBIT_RE = re.compile(r"TOTAL DEBITS.*?([\d,]+\.\d{2})", re.IGNORECASE)
SUMMARY_CREDIT_RE = re.compile(r"TOTAL CREDITS.*?([\d,]+\.\d{2})", re.IGNORECASE)
STATEMENT_YEAR_RE = re.compile(r"STATEMENT DATE.*?\d{2}/\d{2}/(?P<year>\d{4})", re.IGNORECASE)

# ---------------------------------------------------
# Main Parser
# ---------------------------------------------------
def parse_ambank(pdf_input, source_file: str = ""):
    bank_name = "AmBank"
    all_transactions = []
    
    summary_debit = None
    summary_credit = None
    statement_year = None

    with pdfplumber.open(pdf_input) as pdf:
        # 1. Extract Metadata from First Page
        first_page_text = pdf.pages[0].extract_text() or ""
        year_match = STATEMENT_YEAR_RE.search(first_page_text)
        if year_match:
            statement_year = year_match.group("year")
        
        # 2. Extract Official Summary for Validation
        deb_match = SUMMARY_DEBIT_RE.search(first_page_text)
        if deb_match:
            summary_debit = float(_clean_amount(deb_match.group(1)))
        
        cred_match = SUMMARY_CREDIT_RE.search(first_page_text)
        if cred_match:
            summary_credit = float(_clean_amount(cred_match.group(1)))

        # 3. Process All Pages Using Table Extraction
        for page_idx, page in enumerate(pdf.pages, start=1):
            # AmBank statements typically have clear horizontal/vertical lines
            tables = page.extract_tables()
            
            for table in tables:
                for row in table:
                    # Filter for rows that start with a date (e.g., "01 Mar")
                    if not row or not row[0]:
                        continue
                        
                    date_str = row[0].strip()
                    # Match "DD Mon" format
                    if not re.match(r"^\d{1,2}\s?[A-Za-z]{3}$", date_str):
                        continue
                    
                    # Normalize Date
                    try:
                        clean_date = date_str.replace(" ", "")
                        normalized_date = datetime.strptime(
                            f"{clean_date}{statement_year}", "%d%b%Y"
                        ).strftime("%Y-%m-%d")
                    except:
                        normalized_date = date_str

                    # Column mapping based on AmBank layout:
                    # 0: Date, 1: Transaction, 2: Cheque No, 3: Debit, 4: Credit, 5: Balance
                    description = row[1].replace("\n", " ") if row[1] else ""
                    debit_val = _clean_amount(row[3]) if len(row) > 3 else None
                    credit_val = _clean_amount(row[4]) if len(row) > 4 else None
                    balance_val = _clean_amount(row[5]) if len(row) > 5 else None

                    all_transactions.append({
                        "date": normalized_date,
                        "description": description.strip(),
                        "debit": float(debit_val) if debit_val else 0.0,
                        "credit": float(credit_val) if credit_val else 0.0,
                        "balance": float(balance_val) if balance_val else None,
                        "page": page_idx,
                        "bank": bank_name,
                        "source_file": source_file
                    })

    # 4. Final Validation
    calc_debit = round(sum(t["debit"] for t in all_transactions), 2)
    calc_credit = round(sum(t["credit"] for t in all_transactions), 2)

    # Output verification to console
    print(f"Extraction Complete for {source_file}")
    print(f"Calculated Debit: {calc_debit} | Statement Summary: {summary_debit}")
    print(f"Calculated Credit: {calc_credit} | Statement Summary: {summary_credit}")

    return all_transactions
