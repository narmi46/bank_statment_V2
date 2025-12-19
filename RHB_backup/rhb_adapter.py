import re
from datetime import datetime

def parse_transactions_rhb(pdf, source_filename):
    """
    Parses RHB transactions using a pdfplumber object.
    Fixes the missing first credit by accurately locating the 'Beginning Balance'.
    """
    # ---------------- REGEX ----------------
    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    # Matches money like 1,234.56 or 1,234.56-
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")

    # ---------------- HELPERS ----------------
    def parse_money(t: str) -> float:
        if not t: return 0.0
        t = t.strip()
        neg = t.endswith("-")
        # Remove suffix and commas
        clean_t = t[:-1] if neg or t.endswith("+") else t
        try:
            v = float(clean_t.replace(",", ""))
            return -v if neg else v
        except ValueError:
            return 0.0

    def norm_date(t: str) -> str:
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # ==========================================================
    # STEP 1: FIND OPENING BALANCE
    # ==========================================================
    opening_balance = None
    first_page = pdf.pages[0]
    words = first_page.extract_words()
    
    # Sort words to reconstruct lines
    words.sort(key=lambda w: (round(w['top'], 1), w['x0']))

    for i, w in enumerate(words):
        text = w['text'].upper()
        if "BEGINNING" in text:
            # Check context for "BEGINNING BALANCE"
            context = " ".join([word['text'].upper() for word in words[i:i+5]])
            if "BEGINNING BALANCE" in context:
                # Look ahead for the first money string (the balance amount)
                for search_idx in range(i, min(i + 15, len(words))):
                    item_text = words[search_idx]['text']
                    if MONEY_RE.match(item_text):
                        opening_balance = parse_money(item_text)
                        break
                if opening_balance is not None:
                    break

    # ==========================================================
    # STEP 2: TRANSACTION PARSER
    # ==========================================================
    transactions = []
    previous_balance = opening_balance

    for page in pdf.pages:
        page_words = page.extract_words()
        # Group words by line (using 'top' coordinate)
        lines_dict = {}
        for w in page_words:
            y = round(w['top'], 1)
            lines_dict.setdefault(y, []).append(w)
        
        sorted_y = sorted(lines_dict.keys())

        for y in sorted_y:
            line = sorted(lines_dict[y], key=lambda w: w['x0'])
            first_word = line[0]['text'].strip()

            if not DATE_RE.match(first_word):
                continue

            date_iso = norm_date(first_word)
            
            # Extract values from line
            description_parts = []
            money_vals = []
            
            for w in line[1:]:
                txt = w['text'].strip()
                if MONEY_RE.match(txt):
                    money_vals.append(w)
                elif not txt.isdigit():
                    description_parts.append(txt)

            if not money_vals:
                continue

            # Rightmost money is always the balance in RHB statements
            balance_text = max(money_vals, key=lambda m: m['x0'])['text']
            balance = parse_money(balance_text)

            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": date_iso,
                "description": " ".join(description_parts)[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page.page_number,
                "bank": "RHB Bank",
                "source_file": source_filename
            })
            
            previous_balance = balance

    return transactions
    
