import re
import fitz  # PyMuPDF
import os
from datetime import datetime

# -----------------------------
# REGEX (Kept from your code)
# -----------------------------
DATE_RE = re.compile(
    r"^("
    r"\d{2}/\d{2}/\d{4}|"
    r"\d{2}/\d{2}|"
    r"\d{2}-\d{2}|"
    r"\d{2}\s+[A-Z]{3}"
    r")$",
    re.IGNORECASE
)

YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Accept: 0.10, .10, 10.00, 1,234.56
AMOUNT_CORE_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}$")
# Maybank adds trailing sign: 1,980.00+ / 1,500.00-
AMOUNT_WITH_SIGN_RE = re.compile(r"^(.*?)([+-])$")

# -----------------------------
# HELPERS (Kept & Optimized)
# -----------------------------
def open_pymupdf(pdf_input):
    if isinstance(pdf_input, str):
        if not os.path.exists(pdf_input):
            raise FileNotFoundError(pdf_input)
        return fitz.open(pdf_input)
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        data = pdf_input.stream.read()
        if not data:
            raise ValueError("PDF stream empty")
        return fitz.open(stream=data, filetype="pdf")
    raise ValueError("Unsupported PDF input")

def normalize_maybank_date(token, year):
    token = token.upper().strip()
    for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m", "%d %b"):
        try:
            if fmt == "%d/%m/%Y":
                dt = datetime.strptime(token, fmt)
            else:
                # Handle edge case where year crossing happens (Dec -> Jan)
                # But simple appending works for most monthly statements
                dt = datetime.strptime(f"{token}/{year}", fmt + "/%Y")
            return dt.strftime("%Y-%m-%d")
        except:
            pass
    return None

def split_amount_and_sign(text):
    t = text.strip()
    m = AMOUNT_WITH_SIGN_RE.match(t)
    if m:
        return m.group(1).strip(), m.group(2)
    return t, None

def is_amount_token(text):
    amt, _ = split_amount_and_sign(text)
    # Remove all commas before checking regex
    clean_amt = amt.replace(",", "")
    return bool(AMOUNT_CORE_RE.match(clean_amt))

def amount_to_float(text):
    amt, _ = split_amount_and_sign(text)
    try:
        return float(amt.replace(",", ""))
    except:
        return 0.0

def decide_debit_credit(txn_amount, txn_sign, prev_balance, balance):
    debit = credit = 0.0

    # 1. Sign-based (Strongest signal in Maybank PDFs)
    if txn_amount is not None and txn_sign in ("+", "-"):
        if txn_sign == "+":
            return 0.0, round(abs(txn_amount), 2)  # Credit
        else:
            return round(abs(txn_amount), 2), 0.0  # Debit

    # 2. Delta-based (Fallback)
    if prev_balance is not None:
        delta = round(balance - prev_balance, 2)
        if delta > 0:
            return 0.0, abs(delta)
        elif delta < 0:
            return abs(delta), 0.0
        # If delta is 0, assumes no movement or parsing error, 
        # but if we have a txn_amount, we might default to Debit
        
    # 3. Fallback: If we have an amount but no sign and no prev balance,
    # In banking statements, debit columns usually come first, but it's risky.
    # However, Reversals usually have signs. 
    if txn_amount is not None:
        return round(abs(txn_amount), 2), 0.0
        
    return 0.0, 0.0

# -----------------------------
# NEW HELPER: Row Clustering
# -----------------------------
def cluster_words_into_lines(words, y_tolerance=3.0):
    """
    Groups PyMuPDF words into horizontal lines based on Y-coordinate.
    Returns a list of lines, where each line is a list of word-tuples.
    """
    # Sort words by Y (top to bottom), then X (left to right)
    # w structure: (x0, y0, x1, y1, text, block_no, line_no, word_no)
    words.sort(key=lambda w: (round(w[1], 1), w[0]))
    
    lines = []
    if not words:
        return lines

    current_line = [words[0]]
    last_y = words[0][1]

    for w in words[1:]:
        y = w[1]
        # If the word is on the same vertical level (within tolerance)
        if abs(y - last_y) <= y_tolerance:
            current_line.append(w)
        else:
            # New line detected
            lines.append(current_line)
            current_line = [w]
            last_y = y
            
    if current_line:
        lines.append(current_line)
        
    return lines

# -----------------------------
# IMPROVED MAIN PARSER
# -----------------------------
def parse_transactions_maybank(pdf_input, source_filename):
    doc = open_pymupdf(pdf_input)

    transactions = []
    seen = set()
    previous_balance = None
    
    # State tracking
    current_active_date = None
    
    bank_name = "Maybank"
    statement_year = str(datetime.now().year)

    # 1. Extract Year from Header
    for p in range(min(2, len(doc))):
        text = doc[p].get_text("text").upper()
        if "MAYBANK ISLAMIC" in text:
            bank_name = "Maybank Islamic"
        
        m = YEAR_RE.search(text)
        if m:
            statement_year = m.group(1)
            break

    # 2. Process Pages
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_num = page_index + 1

        # Extract words: (x0, y0, x1, y1, "text", block_no, line_no, word_no)
        raw_words = page.get_text("words")
        
        # Cluster raw words into logical visual lines
        lines = cluster_words_into_lines(raw_words)

        for line in lines:
            # Check the first token of the line for a Date
            first_token_text = line[0][4].strip()
            
            # Try to normalize potential date
            found_date = None
            if DATE_RE.match(first_token_text):
                found_date = normalize_maybank_date(first_token_text, statement_year)

            # UPDATE STATE: If we found a date, update current_active_date
            if found_date:
                current_active_date = found_date
                
            # IDENTIFY AMOUNTS: Find all tokens in this line that look like money
            # (x0, value, sign)
            line_amounts = []
            desc_tokens = []
            
            # We iterate tokens in the line
            # If a token is the date we just found, skip it in description
            start_idx = 0
            if found_date:
                start_idx = 1 # Skip the first token (the date)

            for w in line[start_idx:]:
                text = w[4].strip()
                if is_amount_token(text):
                    amt_val = amount_to_float(text)
                    _, sign = split_amount_and_sign(text)
                    line_amounts.append({
                        "x0": w[0],
                        "val": amt_val,
                        "sign": sign,
                        "text": text
                    })
                else:
                    desc_tokens.append(text)

            # LOGIC: Is this a Transaction line?
            # It must have at least one numeric amount OR be a continuation.
            # However, for "Reversals", they usually have an Amount.
            
            if len(line_amounts) > 0 and current_active_date:
                # -------------------------------------------------
                # CASE A: It is a Transaction Line (Start or Reversal)
                # -------------------------------------------------
                
                # Sort amounts by X position (Left to Right)
                line_amounts.sort(key=lambda x: x["x0"])
                
                # Heuristic: Right-most is usually Balance
                # Second Right-most is Transaction Amount
                
                balance = line_amounts[-1]["val"]
                
                txn_amount = 0.0
                txn_sign = None
                
                if len(line_amounts) > 1:
                    txn_amount = line_amounts[-2]["val"]
                    txn_sign = line_amounts[-2]["sign"]
                else:
                    # Rare case: Only one number found on line. 
                    # If prev_balance exists, check if this number is likely the balance
                    # or the transaction amount.
                    # Usually in Maybank, if one number, it's the balance? 
                    # Or a wrapper line with just an amount. 
                    # We will assume it is balance and calc delta.
                    pass

                description = " ".join(desc_tokens)
                description = " ".join(description.split())[:200]

                # Filter out headers/footers based on keywords in description
                if any(k in description.upper() for k in ["TOTAL", "BALANCE B/F", "BALANCE C/F", "MONTHLY SUMMARY"]):
                    continue

                # Calculate Debit/Credit
                debit, credit = decide_debit_credit(txn_amount, txn_sign, previous_balance, balance)
                
                # Update previous balance tracking
                previous_balance = balance

                # Dedup check
                sig = (current_active_date, debit, credit, balance, page_num, description) # Added desc to sig to prevent squashing
                if sig not in seen:
                    seen.add(sig)
                    transactions.append({
                        "date": current_active_date,
                        "description": description or "NO DESCRIPTION",
                        "debit": debit,
                        "credit": credit,
                        "balance": balance,
                        "page": page_num,
                        "bank": bank_name,
                        "source_file": source_filename
                    })

            elif len(line_amounts) == 0 and transactions:
                # -------------------------------------------------
                # CASE B: No amounts, likely text wrapping
                # -------------------------------------------------
                # Append this text to the description of the *last recorded transaction*
                # This helps fix truncated descriptions.
                
                extra_text = " ".join(desc_tokens)
                
                # Basic filter to ensure we don't append page footers
                if "PAGE" not in extra_text.upper() and "MAYBANK" not in extra_text.upper():
                    last_txn = transactions[-1]
                    # Only append if on same page (safety)
                    if last_txn["page"] == page_num:
                        last_txn["description"] += " " + extra_text
                        last_txn["description"] = " ".join(last_txn["description"].split())

    doc.close()
    return transactions
