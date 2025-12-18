def parse_transactions_maybank(pdf_input, source_filename):
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
    bank_name = "Maybank"
    statement_year = None

    for p in range(min(2, len(doc))):
        txt = doc[p].get_text("text").upper()
        if "MAYBANK ISLAMIC" in txt:
            bank_name = "Maybank Islamic"
        elif "MAYBANK" in txt:
            bank_name = "Maybank"

        m = YEAR_RE.search(txt)
        if m:
            statement_year = m.group(1)
            break

    if not statement_year:
        statement_year = str(datetime.now().year)

    # =========================================================
    # PARSER A: "Classic" Maybank token date formats (old style)
    # =========================================================
    DATE_RE_A = re.compile(
        r"^("
        r"\d{2}/\d{2}/\d{4}|"
        r"\d{2}/\d{2}|"
        r"\d{2}-\d{2}|"
        r"\d{2}\s+[A-Z]{3}"
        r")$",
        re.IGNORECASE
    )
    AMOUNT_RE_A = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}[+-]?$")

    def norm_date_a(token, year):
        token = token.strip().upper()
        for fmt in ("%d/%m/%Y", "%d/%m", "%d-%m", "%d %b"):
            try:
                if fmt == "%d/%m/%Y":
                    dt = datetime.strptime(token, fmt)
                else:
                    dt = datetime.strptime(f"{token}/{year}", fmt + "/%Y")
                return dt.strftime("%Y-%m-%d")
            except:
                pass
        return None

    def parse_amt_a(t):
        t = t.strip()
        sign = "+" if t.endswith("+") else "-" if t.endswith("-") else None
        v = float(t.replace(",", "").rstrip("+-"))
        return v, sign

    def parse_classic():
        transactions = []
        previous_balance = None

        for page_index in range(len(doc)):
            page = doc[page_index]
            words = page.get_text("words")

            rows = [{
                "x0": w[0],
                "y0": w[1],
                "text": str(w[4]).strip()
            } for w in words if str(w[4]).strip()]

            rows.sort(key=lambda r: (round(r["y0"], 1), r["x0"]))
            Y_TOL = 1.8
            processed_y = set()

            for r in rows:
                token = r["text"]
                if not DATE_RE_A.match(token):
                    continue

                y_ref = r["y0"]
                y_bucket = round(y_ref, 1)
                if y_bucket in processed_y:
                    continue

                line = [w for w in rows if abs(w["y0"] - y_ref) <= Y_TOL]
                line.sort(key=lambda w: w["x0"])

                date_iso = norm_date_a(token, statement_year)
                if not date_iso:
                    continue

                desc_parts, amounts = [], []
                for w in line:
                    if w["text"] == token:
                        continue
                    if AMOUNT_RE_A.match(w["text"]):
                        amounts.append((w["x0"], w["text"]))
                    else:
                        desc_parts.append(w["text"])

                if not amounts:
                    continue

                amounts.sort(key=lambda a: a[0])
                balance_val, _ = parse_amt_a(amounts[-1][1])

                txn_val = txn_sign = None
                if len(amounts) > 1:
                    txn_val, txn_sign = parse_amt_a(amounts[-2][1])

                description = " ".join(desc_parts).strip()
                description = " ".join(description.split())[:200]

                debit = credit = 0.0
                if previous_balance is not None:
                    delta = round(balance_val - previous_balance, 2)
                    if delta > 0:
                        credit = abs(delta)
                    elif delta < 0:
                        debit = abs(delta)
                    else:
                        if txn_sign == "+" and txn_val is not None:
                            credit = txn_val
                        elif txn_sign == "-" and txn_val is not None:
                            debit = txn_val
                else:
                    # first row fallback (if +/- printed)
                    if txn_sign == "+" and txn_val is not None:
                        credit = txn_val
                    elif txn_sign == "-" and txn_val is not None:
                        debit = txn_val

                processed_y.add(y_bucket)
                transactions.append({
                    "date": date_iso,
                    "description": description,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance_val, 2),
                    "page": page_index + 1,
                    "bank": bank_name,
                    "source_file": source_filename
                })
                previous_balance = balance_val

        return transactions

    # =========================================================
    # PARSER B: Islamic-style split-date rows: "01" "Feb" "2025"
    # + first-row printed amount fallback
    # =========================================================
    MONTHS = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}

    def is_day(t): return t.isdigit() and 1 <= int(t) <= 31
    def is_month(t): return t.capitalize() in MONTHS
    def is_year(t): return t.isdigit() and t.startswith("20")

    def parse_amount(v):
        return float(v.replace(",", ""))

    def looks_like_money(t):
        # strict enough to avoid IDs; must contain '.' and be numeric after cleanup
        tt = t.replace(",", "")
        if "." not in tt:
            return False
        try:
            float(tt)
            return True
        except:
            return False

    def parse_split_date():
        transactions = []
        previous_balance = None

        for page_index, page in enumerate(doc):
            words = page.get_text("words")
            rows = [{
                "x": w[0],
                "y": round(w[1], 1),
                "text": str(w[4]).strip()
            } for w in words if str(w[4]).strip()]

            rows.sort(key=lambda r: (r["y"], r["x"]))
            used_y = set()

            for i in range(len(rows) - 2):
                w1, w2, w3 = rows[i], rows[i+1], rows[i+2]
                if not (is_day(w1["text"]) and is_month(w2["text"]) and is_year(w3["text"])):
                    continue

                y_key = w1["y"]
                if y_key in used_y:
                    continue

                try:
                    date_iso = datetime.strptime(
                        f"{w1['text']} {w2['text']} {w3['text']}",
                        "%d %b %Y"
                    ).strftime("%Y-%m-%d")
                except:
                    continue

                line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
                line.sort(key=lambda w: w["x"])

                desc_parts, amounts = [], []
                for w in line:
                    # skip the 3 date tokens
                    if w is w1 or w is w2 or w is w3:
                        continue
                    if looks_like_money(w["text"]):
                        amounts.append(w["text"])
                    else:
                        desc_parts.append(w["text"])

                if not amounts:
                    continue

                balance = parse_amount(amounts[-1])
                debit = credit = 0.0

                if previous_balance is not None:
                    delta = round(balance - previous_balance, 2)
                    if delta < 0:
                        debit = abs(delta)
                    elif delta > 0:
                        credit = delta
                else:
                    # FIRST ROW: use printed txn amount if present
                    if len(amounts) >= 2:
                        txn_amt = parse_amount(amounts[-2])
                        desc_up = " ".join(desc_parts).upper()
                        # Islamic statements often show DR/DEBIT; credits would be CR/CREDIT
                        if ("CR" in desc_up) or ("CREDIT" in desc_up):
                            credit = txn_amt
                        else:
                            debit = txn_amt

                transactions.append({
                    "date": date_iso,
                    "description": " ".join(desc_parts)[:200],
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_index + 1,
                    "bank": bank_name,
                    "source_file": source_filename
                })

                previous_balance = balance
                used_y.add(y_key)

        return transactions

    # ---------------- RUN BOTH + CHOOSE BEST ----------------
    tx_a = parse_classic()
    tx_b = parse_split_date()

    # Prefer the one that found more transactions
    tx = tx_a if len(tx_a) >= len(tx_b) else tx_b

    # If both found some, merge and dedupe safely
    if tx_a and tx_b:
        seen = set()
        merged = []
        for t in (tx_a + tx_b):
            key = (
                t.get("date"),
                t.get("description"),
                t.get("debit"),
                t.get("credit"),
                t.get("balance"),
                t.get("page"),
                t.get("source_file"),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)
        tx = merged

    doc.close()
    return tx
