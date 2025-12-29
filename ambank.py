import pdfplumber
import re

def parse_ambank(pdf, filename):
    """
    Parses AmBank Islamic bank statements.
    Target Columns: Date, Transaction, Cheque No, Debit, Credit, Balance
    """
    transactions = []
    
    # Process pages that contain transaction tables (typically pages 1-6)
    # The provided document has transaction data from page 1 to 6 [cite: 15, 89]
    for page_idx, page in enumerate(pdf.pages):
        # Extract tables using horizontal and vertical line strategies
        # AmBank statements use clear lines for their tables [cite: 15, 22, 36]
        tables = page.extract_table({
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
        })
        
        if not tables:
            # Fallback for pages where lines might not be perfectly detected
            tables = page.extract_table()

        if tables:
            for row in tables:
                # Clean the row data
                clean_row = [str(cell).strip() if cell else "" for cell in row]
                
                # Validation: Skip header rows or summary rows 
                # Headers usually contain 'DATE', 'TRANSACTION', or 'BALANCE' [cite: 15]
                if "DATE" in clean_row[0].upper() or "TARIKH" in clean_row[0].upper():
                    continue
                if "OPENING BALANCE" in clean_row[1].upper() or "TOTAL DEBITS" in clean_row[1].upper():
                    continue
                if "BALANCE BAWA KE HADAPAN" in clean_row[1].upper() or "Baki Bawa Ke Hadapan" in clean_row[1]:
                    continue
                
                # Ensure the row has enough columns (AmBank uses 6) 
                if len(clean_row) >= 6:
                    date = clean_row[0]
                    description = clean_row[1].replace('\n', ' ')
                    cheque_no = clean_row[2]
                    debit = clean_row[3].replace(',', '')
                    credit = clean_row[4].replace(',', '')
                    balance = clean_row[5].replace(',', '')

                    # Final check: A valid transaction usually has a date and a description 
                    if date and description:
                        transactions.append({
                            "date": date,
                            "description": description,
                            "cheque_no": cheque_no,
                            "debit": debit if debit else "0.00",
                            "credit": credit if credit else "0.00",
                            "balance": balance,
                            "page": page_idx + 1,
                            "bank": "AmBank",
                            "source_file": filename
                        })
                        
    return transactions
