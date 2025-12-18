def parse_transactions_rhb(pdf_input, source_filename):
    import re
    import fitz
    from datetime import datetime

    # ---------------- OPEN PDF (Streamlit-safe) ----------------
    def open_doc(inp):
        if hasattr(inp, "stream"):
            inp.stream.seek(0)
            data = inp.stream.read()
            return fitz.open(stream=data, filetype="pdf")
        return fitz.open(inp)

    doc = open_doc(pdf_input)

    # ---------------- BANK NAME / YEAR DETECT ----------------
    YEAR_RE = re.compile(r"\b(20\d{2})\b")
    bank_name = "RHB Bank"
    statement_year = None

    for p in range(min(2, len(doc))):
        txt = doc[p].get_text("text").upper()
        if "RHB" in txt:
            bank_name = "RHB Bank"
        m = YEAR_RE.search(txt)
        if m:
            statement_year = m.group(1)
            break

    if not statement_year:
        statement_year = str(datetime.now().year)

    # ---------------- REGEX ----------------
    # RHB dates are like 02-04-2025
    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")

    # Money like: 1,000.00 or 833,810.21- (trailing minus = negative)
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}-?$")

    def parse_money(t: str) -> float:
        t = t.strip()
        neg = t.endswith("-")
        if neg:
            t = t[:-1]
        v = float(t.replace(",", ""))
        return -v if neg else v

    def norm_date(token: str):
        try:
            return datetime.strptime(token, "%d-%m-%Y").strftime("%Y-%m-%d")
        except:
            return None

    # ---------------- MAIN PARSER ----------------
    transactions = []
    previous_balance = None
    first_row_done = False

    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        # --- Find header x positions for (DR) and (CR) ---
        # Header is often split into tokens, so we search for "(DR)" and "(CR)".
        dr_x = None
        cr_x = None
        for w in words:
            txt = str(w[4]).upper()
            if "(DR)" in txt and dr_x is None:
                dr_x = w[0]
            if "(CR)" in txt and cr_x is None:
                cr_x = w[0]
            if dr_x is not None and cr_x is not None:
                break

        # Fallbacks if header tokens not found
        if dr_x is None:
            dr_x = page.rect.width * 0.50
        if cr_x is None:
            cr_x = page.rect.width * 0.70

        # Use midpoint between DR and CR headers
        dr_cr_split_x = (dr_x + cr_x) / 2.0

        # Build sortable row tokens
        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": str(w[4]).strip()
        } for w in words if str(w[4]).strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))
        used_y = set()

        for r in rows:
            token = r["text"]
            if not DATE_RE.match(token):
                continue

            y_key = r["y"]
            if y_key in used_y:
                continue

            date_iso = norm_date(token)
            if not date_iso:
                continue

            # Grab the entire visual line by Y tolerance
            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc_parts = []
            money_words = []

            for w in line:
                if w["text"] == token:
                    continue
                if MONEY_RE.match(w["text"]):
                    money_words.append(w)
                else:
                    desc_parts.append(w["text"])

            # Need at least balance (and ideally txn amount)
            if not money_words:
                continue

            # Balance is almost always the RIGHTMOST money token
            money_words_sorted = sorted(money_words, key=lambda w: w["x"])
            balance_word = money_words_sorted[-1]
            balance = parse_money(balance_word["text"])

            debit = credit = 0.0

            # ---------------- ALL NON-FIRST ROWS (delta logic) ----------------
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            # ---------------- FIRST ROW ONLY (coordinate logic) ----------------
            else:
                # txn amount is typically the money token immediately left of balance
                # if present; otherwise no txn amount available.
                txn_word = money_words_sorted[-2] if len(money_words_sorted) >= 2 else None

                if txn_word is not None:
                    txn_amt = abs(parse_money(txn_word["text"]))

                    # Decide by X coordinate relative to DR/CR split
                    # left side => DR (debit), right side => CR (credit)
                    if txn_word["x"] >= dr_cr_split_x:
                        credit = txn_amt
                    else:
                        debit = txn_amt

            transactions.append({
                "date": date_iso,
                "description": " ".join(desc_parts).strip()[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": bank_name,
                "source_file": source_filename
            })

            previous_balance = balance
            used_y.add(y_key)
            first_row_done = True

    doc.close()
    return transactions
