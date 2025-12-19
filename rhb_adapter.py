import re
from datetime import datetime

def parse_transactions_rhb(pdf, source_filename):
    # ---------------- REGEX & HELPERS ----------------
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")
    REFLEX_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    # Matches "07 Mar" style dates found in the Boutique statement
    CURRENT_DATE_RE = re.compile(r"^\d{2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")

    def parse_money(t: str) -> float:
        if not t: return 0.0
        t = t.strip()
        neg = t.endswith("-")
        clean_t = t[:-1] if neg or t.endswith("+") else t
        try:
            v = float(clean_t.replace(",", ""))
            return -v if neg else v
        except ValueError: return 0.0

    # ---------------- DETECTION ----------------
    # Extract text from the first page to determine the format
    first_page_text = pdf.pages[0].extract_text()
    is_reflex = "REFLEX" in first_page_text.upper() or "21413800157991" in first_page_text

    # =========================================================================
    # FORMAT 1: REFLEX (e.g., Clear Water Services)
    # =========================================================================
    if is_reflex:
        opening_balance = None
        words = pdf.pages[0].extract_words()
        words.sort(key=lambda w: (round(w['top'], 1), w['x0']))
        
        # Search for Beginning Balance anchor to fix the missing April 2nd credit
        for i, w in enumerate(words):
            if "BEGINNING" in w['text'].upper():
                context = " ".join([word['text'].upper() for word in words[i:i+5]])
                if "BEGINNING BALANCE" in context:
                    for search_idx in range(i, min(i + 15, len(words))):
                        if MONEY_RE.match(words[search_idx]['text']):
                            opening_balance = parse_money(words[search_idx]['text'])
                            break
                    if opening_balance is not None: break

        transactions = []
        previous_balance = opening_balance
        for page in pdf.pages:
            page_words = page.extract_words()
            lines = {}
            for w in page_words:
                y = round(w['top'], 1)
                lines.setdefault(y, []).append(w)
            
            for y in sorted(lines.keys()):
                line = sorted(lines[y], key=lambda w: w['x0'])
                if not REFLEX_DATE_RE.match(line[0]['text'].strip()): continue
                
                date_iso = datetime.strptime(line[0]['text'].strip(), "%d-%m-%Y").strftime("%Y-%m-%d")
                money_vals = [w for w in line if MONEY_RE.match(w['text'])]
                desc = " ".join([w['text'] for w in line if not MONEY_RE.match(w['text']) and not REFLEX_DATE_RE.match(w['text'])])
                
                if not money_vals: continue
                # In Reflex, the rightmost money value is the running balance
                balance = parse_money(max(money_vals, key=lambda m: m['x0'])['text'])
                
                debit = credit = 0.0
                if previous_balance is not None:
                    delta = round(balance - previous_balance, 2)
                    if delta > 0: credit = delta
                    elif delta < 0: debit = abs(delta)

                transactions.append({
                    "date": date_iso, "description": desc[:200], "debit": round(debit, 2),
                    "credit": round(credit, 2), "balance": round(balance, 2),
                    "page": page.page_number, "bank": "RHB Bank (Reflex)", "source_file": source_filename
                })
                previous_balance = balance
        return transactions

    # =========================================================================
    # FORMAT 2: ORDINARY CURRENT ACCOUNT (e.g., Azlan Boutique)
    # =========================================================================
    else:
        # Detect year from statement header (e.g., "7 Mar 24") 
        year_match = re.search(r"Tempoh Penyata:.*?\s(\d{2})$", first_page_text, re.MULTILINE)
        year_val = "20" + year_match.group(1) if year_match else "2024"

        transactions = []
        for page in pdf.pages:
            page_words = page.extract_words()
            lines = {}
            for w in page_words:
                y = round(w['top'], 1)
                lines.setdefault(y, []).append(w)
            
            for y in sorted(lines.keys()):
                line = sorted(lines[y], key=lambda w: w['x0'])
                if not line or not CURRENT_DATE_RE.match(line[0]['text']): continue
                
                date_raw = line[0]['text']
                desc_upper = " ".join([w['text'].upper() for w in line])
                if "B/F BALANCE" in desc_upper or "C/F BALANCE" in desc_upper: continue

                # Position-based column detection for Debit/Credit/Balance
                debit = credit = balance = 0.0
                for w in line:
                    if MONEY_RE.match(w['text']):
                        x = w['x0']
                        val = parse_money(w['text'])
                        if x > 500: balance = val # Balance column [cite: 52]
                        elif 410 < x <= 500: credit = val # Credit column [cite: 52]
                        elif 320 < x <= 410: debit = val # Debit column [cite: 52]

                try:
                    date_iso = datetime.strptime(f"{date_raw} {year_val}", "%d %b %Y").strftime("%Y-%m-%d")
                    transactions.append({
                        "date": date_iso,
                        "description": " ".join([w['text'] for w in line if not MONEY_RE.match(w['text']) and not CURRENT_DATE_RE.match(w['text'])])[:200],
                        "debit": abs(debit), "credit": abs(credit), "balance": balance,
                        "page": page.page_number, "bank": "RHB Bank (Current)", "source_file": source_filename
                    })
                except: continue
        return transactions
