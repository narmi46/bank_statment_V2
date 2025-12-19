import re
import pdfplumber
from datetime import datetime


def parse_transactions_rhb(pdf_input, source_filename):
    """
    Unified RHB Bank PDF parser with auto-detection
    - Supports both Conventional and Islamic statements
    - Streamlit-safe
    - Auto-detects statement type
    - Handles both date formats: "DD Mon" and "DD-MM-YYYY"
    """

    # ============================================================
    # HELPER: Detect Statement Type
    # ============================================================
    def detect_statement_type(pdf_input):
        """
        Detect if the statement is Conventional or Islamic
        Returns: 'conventional' or 'islamic'
        """
        try:
            # Open with pdfplumber to read text
            if hasattr(pdf_input, "stream"):
                pdf_input.stream.seek(0)
                with pdfplumber.open(pdf_input.stream) as pdf:
                    first_page_text = pdf.pages[0].extract_text() or ""
            else:
                with pdfplumber.open(pdf_input) as pdf:
                    first_page_text = pdf.pages[0].extract_text() or ""
            
            # Check for Islamic indicators
            islamic_keywords = [
                "ISLAMIC", "SHARIAH", "MUDHARABAH", "QARD",
                "WADIAH", "MURABAHAH", "TAWARRUQ", "HIBAH"
            ]
            
            if any(keyword in first_page_text.upper() for keyword in islamic_keywords):
                return 'islamic'
            
            return 'conventional'
        except:
            # Default to conventional if detection fails
            return 'conventional'

    # ============================================================
    # UNIFIED PARSER (works for both Islamic and Conventional)
    # ============================================================
    def parse_unified(pdf_input, source_filename, is_islamic=False):
        """
        Unified PDFplumber-based parser for both statement types
        """
        transactions = []
        previous_balance = None

        # Patterns
        balance_pattern = re.compile(r"(-?\d{1,3}(?:,\d{3})*\.\d{2})$")
        txn_date_pattern = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
        
        # Open PDF with pdfplumber
        if hasattr(pdf_input, "stream"):
            pdf_input.stream.seek(0)
            pdf = pdfplumber.open(pdf_input.stream)
        else:
            pdf = pdfplumber.open(pdf_input)

        try:
            # ===============================
            # 1️⃣ Extract YEAR from header
            # ===============================
            header_text = pdf.pages[0].extract_text()

            # Try multiple patterns for year extraction
            # Pattern 1: "1 Jan 25 – 31 Jan 25" or "7 Mar 24 – 31 Mar 24"
            year_matches = re.findall(r"(\d{1,2})\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2})", header_text)
            
            if year_matches:
                # Take the last year found (usually the end date)
                year = int("20" + year_matches[-1][1])
            else:
                # Fallback: try to find any 2-digit year
                year_matches = re.findall(r"\b(\d{2})\b", header_text)
                if year_matches:
                    year = int("20" + year_matches[0])
                else:
                    raise ValueError("Could not extract year from statement header")

            # ===============================
            # 2️⃣ Extract Opening Balance
            # ===============================
            opening_balance_match = re.search(
                r"(?:Opening Balance|Baki Pembukaan).*?(\d{1,3}(?:,\d{3})*\.\d{2})",
                header_text,
                re.IGNORECASE | re.DOTALL
            )
            
            if opening_balance_match:
                previous_balance = float(opening_balance_match.group(1).replace(",", ""))

            # ===============================
            # 3️⃣ Parse all pages
            # ===============================
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text:
                    continue

                lines = text.split("\n")

                for line in lines:
                    line = line.strip()

                    # Must end with balance
                    balance_match = balance_pattern.search(line)
                    if not balance_match:
                        continue

                    balance = float(balance_match.group(1).replace(",", ""))

                    # B/F or C/F balance → initialise only
                    if re.search(r"\bB/F\b|\bC/F\b", line):
                        if previous_balance is None:
                            previous_balance = balance
                        continue

                    # Transaction date like "01 Jan" or "07 Mar"
                    date_match = txn_date_pattern.search(line)
                    if not date_match:
                        continue

                    day, month = date_match.groups()
                    
                    # Parse date
                    try:
                        date_obj = datetime.strptime(f"{day} {month} {year}", "%d %b %Y")
                        date_iso = date_obj.strftime("%Y-%m-%d")
                    except:
                        continue

                    # Clean description
                    desc = line
                    # Remove balance
                    desc = desc.replace(balance_match.group(1), "")
                    # Remove date
                    desc = desc.replace(f"{day} {month}", "")
                    # Remove any other money amounts
                    desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                    # Remove serial numbers
                    desc = re.sub(r"\d{10,}", "", desc)
                    # Clean whitespace
                    desc = re.sub(r"\s+", " ", desc).strip()

                    # Skip until opening balance is known
                    if previous_balance is None:
                        previous_balance = balance
                        continue

                    # Debit / Credit calculation
                    change = balance - previous_balance
                    debit = abs(change) if change < 0 else 0
                    credit = change if change > 0 else 0

                    bank_name = "RHB Bank (Islamic)" if is_islamic else "RHB Bank"

                    transactions.append({
                        "date": date_iso,
                        "description": desc[:200],
                        "debit": round(debit, 2),
                        "credit": round(credit, 2),
                        "balance": round(balance, 2),
                        "page": page_num + 1,
                        "bank": bank_name,
                        "source_file": source_filename
                    })

                    previous_balance = balance

        finally:
            pdf.close()

        return transactions

    # ============================================================
    # MAIN ROUTER
    # ============================================================
    statement_type = detect_statement_type(pdf_input)
    
    # Reset stream if needed for second read
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
    
    is_islamic = (statement_type == 'islamic')
    return parse_unified(pdf_input, source_filename, is_islamic)
