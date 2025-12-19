import re
from datetime import datetime

def parse_transactions_rhb(pdf, source_filename):
    """
    Detects and parses two distinct RHB statement formats:
    1. 'Reflex' (Cash Management) - Uses coordinate-based line grouping.
    2. 'Current Account' (Standard) - Uses table extraction strategy.
    """
    # ---------------- COMMON REGEX & HELPERS ----------------
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")
    REFLEX_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    CURRENT_DATE_RE = re.compile(r"^\d{2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")

    def parse_money(t: str) -> float:
        if not t: return 0.0
        t = t.strip()
        neg = t.endswith("-")
        clean_t = t[:-1] if neg or t.endswith("+") else t
        try:
            v = float(clean_t.replace(",", ""))
            return -v if neg else v
        except ValueError:
            return 0.0

    # ---------------- FORMAT DETECTION ----------------
    first_page_text = pdf.pages[0].extract_text()
    # Check for keywords specific to the 'Reflex' format
    is_reflex = "REFLEX" in first_page_text.upper() or "21413800157991" in first_page_text

    # =========================================================================
    # OPTION 1: REFLEX CASH MANAGEMENT FORMAT (e.g., Clear Water Services)
    # =========================================================================
    if is_reflex:
        opening_balance = None
        words = pdf.pages[0].extract_words()
        words.sort(key=lambda w: (round(w['top'], 1), w['x0']))

        # Anchor search for Beginning Balance
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
            lines_dict = {}
            for w in page_words:
                y = round(w['top'], 1)
                lines_dict.setdefault(y, []).append(w)
            
            for y in sorted(lines_dict.keys()):
                line = sorted(lines_dict[y], key=lambda w: w['x0'])
                if not line or not REFLEX_DATE_RE.match(line[0]['text'].strip()): 
                    continue
                
                date_iso = datetime.strptime(line[0]['text'].strip(), "%d-%m-%Y").strftime("%Y-%m-%d")
                
                # Extract description and money values
                desc_parts = []
                money_vals = []
                for w in line[1:]:
                    txt = w['text'].strip()
                    if MONEY_RE.match(txt):
                        money_vals.append(w)
                    elif not txt.isdigit():
                        desc_parts.append(txt)
                
                if not money_vals: continue
                
                # Rightmost money is always the balance
                balance = parse_money(max(money_vals, key=lambda m: m['x0'])['text'])
                
                # Calculate movement based on balance change
                debit = credit = 0.0
                if previous_balance is not None:
                    delta = round(balance - previous_balance, 2)
                    if delta > 0: credit = delta
                    elif delta < 0: debit = abs(delta)

                transactions.append({
                    "date": date_iso,
                    "description": " ".join(desc_parts)[:200],
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page.page_number,
                    "bank": "RHB Bank (Reflex)",
                    "source_file": source_filename
                })
                previous_balance = balance
        return transactions

    # =========================================================================
    # OPTION 2: ORDINARY CURRENT ACCOUNT FORMAT (e.g., Azlan Boutique)
    # =========================================================================
    else:
        # Improved Year Detection: Looks for '7 Mar 24' or similar in the header
        year_val = "2024" 
        header_match = re.search(r"Tempoh Penyata:\s+\d{1,2}\s+\w{3}\s+(\d{2})", first_page_text)
        if header_match:
            year_val = "20" + header_match.group(1)

        transactions = []
        for page in pdf.pages:
            # Using a more robust table extraction setting for grid layouts
            table = page.extract_table({
                "vertical_strategy": "text", 
                "horizontal_strategy": "lines",
                "intersection_y_tolerance": 10 # Helps catch multi-line descriptions
            })
            
            if not table: continue
            
            for row in table:
                # Filter out None/empty and strip whitespace
                row = [str(c).strip() if c else "" for c in row]
                
                # Check for the date format "07 Mar" [cite: 52]
                if len(row) < 6 or not CURRENT_DATE_RE.match(row[0]): 
                    continue
                
                # Skip summary lines [cite: 52, 113]
                desc_upper = row[1].upper()
                if any(x in desc_upper for x in ["B/F BALANCE", "C/F BALANCE", "TOTAL COUNT"]):
                    continue
                
                try:
                    # Normalize date using detected year 
                    date_obj = datetime.strptime(f"{row[0]} {year_val}", "%d %b %Y")
                    date_iso = date_obj.strftime("%Y-%m-%d")
                    
                    transactions.append({
                        "date": date_iso,
                        "description": row[1].replace("\n", " ")[:200],
                        "debit": parse_money(row[3]), # [cite: 52]
                        "credit": parse_money(row[4]), # [cite: 52]
                        "balance": parse_money(row[5]), # [cite: 52]
                        "page": page.page_number,
                        "bank": "RHB Bank (Current)",
                        "source_file": source_filename
                    })
                except Exception:
                    continue
                    
        return transactions
