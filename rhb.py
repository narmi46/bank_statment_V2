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
        # OPTION 2: ORDINARY CURRENT ACCOUNT FORMAT (MATCHES PDF)
        # =========================================================================
        else:
            # Detect year from header: "7 Mar 24 – 31 Mar 24"
            year_match = re.search(r"Tempoh Penyata\s*:\s*\d{1,2}\s+\w{3}\s+(\d{2})", first_page_text)
            year_val = "20" + year_match.group(1) if year_match else "2024"
        
            transactions = []
            last_txn = None
        
            for page in pdf.pages:
                words = page.extract_words()
                lines = {}
                for w in words:
                    y = round(w["top"], 1)
                    lines.setdefault(y, []).append(w)
        
                for y in sorted(lines.keys()):
                    line = sorted(lines[y], key=lambda w: w["x0"])
                    text_line = " ".join(w["text"] for w in line)
        
                    # ---------------- START OF NEW TRANSACTION ----------------
                    if line and CURRENT_DATE_RE.match(line[0]["text"]):
                        if any(x in text_line.upper() for x in ["B/F BALANCE", "C/F BALANCE", "TOTAL COUNT"]):
                            continue
        
                        date_raw = line[0]["text"]
                        try:
                            date_iso = datetime.strptime(f"{date_raw} {year_val}", "%d %b %Y").strftime("%Y-%m-%d")
                        except:
                            continue
        
                        money_words = [w for w in line if MONEY_RE.match(w["text"])]
                        if not money_words:
                            continue
        
                        # Rightmost money is balance
                        money_words.sort(key=lambda w: w["x0"])
                        balance = parse_money(money_words[-1]["text"])
        
                        debit = credit = 0.0
                        if len(money_words) == 2:
                            # one movement + balance
                            movement = parse_money(money_words[0]["text"])
                            if " DR " in f" {text_line.upper()} ":
                                debit = abs(movement)
                            else:
                                credit = abs(movement)
                        elif len(money_words) >= 3:
                            debit = abs(parse_money(money_words[-3]["text"]))
                            credit = abs(parse_money(money_words[-2]["text"]))
        
                        desc_parts = [
                            w["text"]
                            for w in line
                            if not MONEY_RE.match(w["text"])
                            and not CURRENT_DATE_RE.match(w["text"])
                            and not w["text"].isdigit()
                        ]
        
                        last_txn = {
                            "date": date_iso,
                            "description": " ".join(desc_parts),
                            "debit": debit,
                            "credit": credit,
                            "balance": balance,
                            "page": page.page_number,
                            "bank": "RHB Bank (Current)",
                            "source_file": source_filename,
                        }
                        transactions.append(last_txn)
        
                    # ---------------- CONTINUATION LINE (DESCRIPTION WRAP) ----------------
                    elif last_txn:
                        extra = " ".join(w["text"] for w in line if not MONEY_RE.match(w["text"]))
                        if extra.strip():
                            last_txn["description"] += " " + extra
        
            # Final cleanup
            for t in transactions:
                t["description"] = t["description"].replace("\n", " ").strip()[:200]
        
            return transactions
