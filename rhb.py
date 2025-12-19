import re
import fitz
import pdfplumber
from datetime import datetime


def parse_transactions_rhb(pdf_input, source_filename):
    """
    Unified RHB Bank PDF parser with auto-detection
    - Supports both Conventional and Islamic statements
    - Streamlit-safe
    - Auto-detects statement type
    - Accurate Beginning Balance detection
    - Balance-delta based debit/credit calculation
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
                "ISLAMIC", "SHARIAH", "MUDHARABAH", 
                "WADIAH", "MURABAHAH", "TAWARRUQ"
            ]
            
            if any(keyword in first_page_text.upper() for keyword in islamic_keywords):
                return 'islamic'
            
            return 'conventional'
        except:
            # Default to conventional if detection fails
            return 'conventional'

    # ============================================================
    # PARSER 1: Conventional RHB (Original PyMuPDF-based)
    # ============================================================
    def parse_conventional(pdf_input, source_filename):
        """
        Original PyMuPDF-based parser for conventional statements
        """
        # ---------------- OPEN PDF ----------------
        def open_doc(inp):
            if hasattr(inp, "stream"):  # Streamlit upload
                inp.stream.seek(0)
                return fitz.open(stream=inp.stream.read(), filetype="pdf")
            return fitz.open(inp)

        doc = open_doc(pdf_input)

        # ---------------- REGEX ----------------
        DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
        MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")

        # ---------------- HELPERS ----------------
        def parse_money(t: str) -> float:
            neg = t.endswith("-")
            pos = t.endswith("+")
            t = t[:-1] if neg or pos else t
            try:
                v = float(t.replace(",", ""))
                return -v if neg else v
            except ValueError:
                return 0.0

        def norm_date(t: str) -> str:
            return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

        # ==========================================================
        # STEP 1: FIND OPENING BALANCE (X + Y AXIS BASED)
        # ==========================================================
        opening_balance = None
        first_page = doc[0]
        words = first_page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        for r in rows:
            text = r["text"].upper()
            if "BEGINNING" in text and "BALANCE" in text:
                y_ref = r["y"]
                x_ref = r["x"]

                same_line_money = [
                    w for w in rows
                    if abs(w["y"] - y_ref) <= 1.5
                    and w["x"] > x_ref
                    and MONEY_RE.match(w["text"])
                ]

                if same_line_money:
                    same_line_money.sort(key=lambda w: w["x"])
                    opening_balance = parse_money(same_line_money[-1]["text"])
                break

        # ==========================================================
        # STEP 2: TRANSACTION PARSER
        # ==========================================================
        transactions = []
        previous_balance = opening_balance

        for page_index, page in enumerate(doc):
            words = page.get_text("words")

            rows = [{
                "x": w[0],
                "y": round(w[1], 1),
                "text": w[4].strip()
            } for w in words if w[4].strip()]

            rows.sort(key=lambda r: (r["y"], r["x"]))
            used_y = set()

            for r in rows:
                if not DATE_RE.match(r["text"]):
                    continue

                y_key = r["y"]
                if y_key in used_y:
                    continue

                date_iso = norm_date(r["text"])

                line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
                line.sort(key=lambda w: w["x"])

                description = []
                money_vals = []

                for w in line:
                    if w["text"] == r["text"]:
                        continue
                    if MONEY_RE.match(w["text"]):
                        money_vals.append(w)
                    elif not w["text"].isdigit():
                        description.append(w["text"])

                if not money_vals:
                    continue

                # Rightmost money = balance
                balance = parse_money(max(money_vals, key=lambda m: m["x"])["text"])

                debit = credit = 0.0
                if previous_balance is not None:
                    delta = round(balance - previous_balance, 2)
                    if delta > 0:
                        credit = delta
                    elif delta < 0:
                        debit = abs(delta)

                transactions.append({
                    "date": date_iso,
                    "description": " ".join(description)[:200],
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_index + 1,
                    "bank": "RHB Bank",
                    "source_file": source_filename
                })

                previous_balance = balance
                used_y.add(y_key)

        doc.close()
        return transactions

    # ============================================================
    # PARSER 2: Islamic RHB (pdfplumber-based)
    # ============================================================
    def parse_islamic(pdf_input, source_filename):
        """
        PDFplumber-based parser for Islamic statements
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
            year_matches = re.findall(r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{2})", header_text)
            if not year_matches:
                # Try alternative pattern: "Statement Period 1Jan25"
                year_matches = re.findall(r"(\d{2})(?=\s*[-–]|\s+to\s+)", header_text)
            
            if not year_matches:
                raise ValueError("Could not extract year from Islamic statement header")

            year = int("20" + year_matches[0])

            # ===============================
            # 2️⃣ Parse all pages
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
                        previous_balance = balance
                        continue

                    # Transaction date like "01 Jan"
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
                    desc = desc.replace(balance_match.group(1), "")
                    desc = desc.replace(f"{day} {month}", "")
                    desc = re.sub(r"\d{1,3}(?:,\d{3})*\.\d{2}", "", desc)
                    desc = re.sub(r"\s+", " ", desc).strip()

                    # Skip until opening balance is known
                    if previous_balance is None:
                        previous_balance = balance
                        continue

                    # Debit / Credit calculation
                    change = balance - previous_balance
                    debit = abs(change) if change < 0 else 0
                    credit = change if change > 0 else 0

                    transactions.append({
                        "date": date_iso,
                        "description": desc[:200],
                        "debit": round(debit, 2),
                        "credit": round(credit, 2),
                        "balance": round(balance, 2),
                        "page": page_num + 1,
                        "bank": "RHB Bank (Islamic)",
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
    
    if statement_type == 'islamic':
        return parse_islamic(pdf_input, source_filename)
    else:
        return parse_conventional(pdf_input, source_filename)
