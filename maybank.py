def parse_transactions_maybank(pdf_input, source_filename):
    import re
    import fitz
    import os
    from datetime import datetime

    # ---------------- REGEX ----------------
    YEAR_RE = re.compile(r"\b(20\d{2})\b")

    # numbers like 50,405.76 or 78.00
    NUM_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$")

    # month tokens we expect in these statements
    MONTHS = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }

    # ---------------- HELPERS ----------------
    def open_doc(inp):
        if isinstance(inp, str):
            if not os.path.exists(inp):
                raise FileNotFoundError(f"PDF not found on disk: {inp}")
            return fitz.open(inp)
        if hasattr(inp, "stream"):
            inp.stream.seek(0)
            data = inp.stream.read()
            if not data:
                raise ValueError("PDF stream is empty")
            return fitz.open(stream=data, filetype="pdf")
        raise ValueError("Unsupported PDF input type")

    def to_float(s):
        return float(s.replace(",", ""))

    def parse_sign_after(tokens, idx):
        """
        Maybank Islamic often prints: 78.00 -
        where '-' is its own token (same for '+').
        Returns sign (+/-/None).
        """
        if idx + 1 < len(tokens):
            nxt = tokens[idx + 1]
            if nxt in ("-", "+"):
                return nxt
            if nxt.upper() in ("DR", "CR"):
                # DR treated as negative, CR as positive
                return "-" if nxt.upper() == "DR" else "+"
        return None

    def try_parse_dd_mmm_yyyy(tokens):
        """
        Detects date split as: ['01','Feb','2025'] (case-insensitive)
        Returns (iso_date, consumed_token_count) or (None,0)
        """
        if len(tokens) < 2:
            return None, 0

        d = tokens[0]
        m = tokens[1].upper()[:3]
        y = tokens[2] if len(tokens) >= 3 and tokens[2].isdigit() and len(tokens[2]) == 4 else None

        if d.isdigit() and 1 <= int(d) <= 31 and m in MONTHS:
            year = int(y) if y else None
            return (d, m, year), (3 if y else 2)

        return None, 0

    def norm_date_from_parts(day_str, mon3, year):
        dt = datetime(year, MONTHS[mon3], int(day_str))
        return dt.strftime("%Y-%m-%d")

    # ---------------- OPEN ----------------
    doc = open_doc(pdf_input)

    bank_name = "Maybank"
    statement_year = None

    # detect year + bank (first 2 pages)
    for p in range(min(2, len(doc))):
        txt = doc[p].get_text("text").upper()
        if "MAYBANK ISLAMIC" in txt:
            bank_name = "Maybank Islamic"
        elif "MAYBANK" in txt:
            bank_name = "Maybank"

        m = YEAR_RE.search(txt)
        if m:
            statement_year = int(m.group(1))
            break

    if not statement_year:
        statement_year = datetime.now().year

    transactions = []

    # --------- MODE DETECT (Feb-style table) ---------
    def is_islamic_table(page_text_upper):
        return ("ACCOUNT TRANSACTIONS" in page_text_upper and
                "TRANSACTION AMOUNT" in page_text_upper and
                "STATEMENT BALANCE" in page_text_upper)

    # ---------------- PARSE ----------------
    for page_index in range(len(doc)):
        page = doc[page_index]
        page_text_upper = page.get_text("text").upper()

        words = page.get_text("words")
        rows = [{
            "x0": w[0],
            "y0": w[1],
            "x1": w[2],
            "y1": w[3],
            "text": str(w[4]).strip()
        } for w in words if str(w[4]).strip()]

        # sort reading order
        rows.sort(key=lambda r: (round(r["y0"], 1), r["x0"]))

        Y_TOL = 2.0

        # group into lines by y
        lines = []
        current = []
        last_y = None
        for r in rows:
            if last_y is None or abs(r["y0"] - last_y) <= Y_TOL:
                current.append(r)
                last_y = r["y0"] if last_y is None else last_y
            else:
                current.sort(key=lambda x: x["x0"])
                lines.append(current)
                current = [r]
                last_y = r["y0"]
        if current:
            current.sort(key=lambda x: x["x0"])
            lines.append(current)

        # --------- PARSER A: Maybank Islamic Feb-style table ---------
        if is_islamic_table(page_text_upper):
            current_txn = None

            def flush_current():
                nonlocal current_txn
                if current_txn:
                    # clean desc
                    desc = " ".join(current_txn["desc"]).strip()
                    desc = " ".join(desc.split())[:200]
                    current_txn["description"] = desc
                    del current_txn["desc"]
                    transactions.append(current_txn)
                    current_txn = None

            for line in lines:
                tokens = [w["text"] for w in line]
                # remove junk separators
                tokens_clean = [t for t in tokens if t not in (":",)]

                # find date at start (split tokens)
                date_parts, consumed = try_parse_dd_mmm_yyyy(tokens_clean)
                if date_parts:
                    # new transaction starts
                    flush_current()

                    day, mon3, y = date_parts
                    year = y if y else statement_year
                    date_iso = norm_date_from_parts(day, mon3, year)

                    # find numeric tokens on this line (amount + balance)
                    num_positions = []
                    for i, t in enumerate(tokens_clean):
                        if NUM_RE.match(t):
                            num_positions.append(i)

                    if not num_positions:
                        # sometimes date line has no amounts, still start txn and accumulate desc
                        current_txn = {
                            "date": date_iso,
                            "description": "",
                            "debit": 0.0,
                            "credit": 0.0,
                            "balance": 0.0,
                            "page": page_index + 1,
                            "bank": bank_name,
                            "source_file": source_filename,
                            "desc": tokens_clean[consumed:]  # rest of line is desc
                        }
                        continue

                    # last number is balance, previous (if exists) is txn amount
                    bal_idx = num_positions[-1]
                    balance_val = to_float(tokens_clean[bal_idx])

                    txn_val = None
                    txn_sign = None
                    if len(num_positions) >= 2:
                        txn_idx = num_positions[-2]
                        txn_val = to_float(tokens_clean[txn_idx])
                        txn_sign = parse_sign_after(tokens_clean, txn_idx)

                    # description tokens are between date and amount column (best-effort)
                    # take everything after date tokens, excluding numeric block and its sign tokens
                    exclude = set()
                    for i in num_positions:
                        exclude.add(i)
                        # exclude sign token if present
                        if i + 1 < len(tokens_clean) and tokens_clean[i + 1] in ("-", "+"):
                            exclude.add(i + 1)
                        if i + 1 < len(tokens_clean) and tokens_clean[i + 1].upper() in ("DR", "CR"):
                            exclude.add(i + 1)

                    desc = [t for i, t in enumerate(tokens_clean[consumed:]) if (i + consumed) not in exclude]

                    debit = credit = 0.0
                    if txn_val is not None:
                        if txn_sign == "-":
                            debit = txn_val
                        elif txn_sign == "+":
                            credit = txn_val
                        else:
                            # no explicit sign: assume debit unless it increases vs balance logic not available here
                            # (Maybank Islamic commonly marks debits with "-")
                            debit = txn_val

                    current_txn = {
                        "date": date_iso,
                        "description": "",
                        "debit": round(debit, 2),
                        "credit": round(credit, 2),
                        "balance": round(balance_val, 2),
                        "page": page_index + 1,
                        "bank": bank_name,
                        "source_file": source_filename,
                        "desc": desc
                    }
                else:
                    # continuation line: add more description while we are inside a txn
                    if current_txn:
                        # stop if we hit totals / ending balance section
                        joined = " ".join(tokens_clean).upper()
                        if any(k in joined for k in ("ENDING BALANCE", "LEDGER BALANCE", "TOTAL DEBITS", "TOTAL CREDITS", "END OF STATEMENT")):
                            continue
                        current_txn["desc"].extend(tokens_clean)

            flush_current()
            continue  # done with Feb-style pages

        # --------- PARSER B: your original (classic Maybank format) ---------
        # keep your old logic mostly unchanged, but it’s limited.
        # (Leaving it here as fallback for other PDFs.)

        DATE_RE_CLASSIC = re.compile(
            r"^(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}|\d{2}-\d{2}|\d{2}\s+[A-Z]{3})$",
            re.IGNORECASE
        )
        AMOUNT_RE_CLASSIC = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}[+-]?$")

        previous_balance = None
        processed_y_buckets = set()

        def norm_date_classic(token, year):
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

        def parse_amt_classic(t):
            t = t.strip()
            sign = "+" if t.endswith("+") else "-" if t.endswith("-") else None
            v = float(t.replace(",", "").rstrip("+-"))
            return v, sign

        for r in rows:
            token = r["text"]
            if not DATE_RE_CLASSIC.match(token):
                continue

            y_ref = r["y0"]
            y_bucket = round(y_ref, 1)
            if y_bucket in processed_y_buckets:
                continue

            line = [w for w in rows if abs(w["y0"] - y_ref) <= Y_TOL]
            line.sort(key=lambda w: w["x0"])

            date_iso = norm_date_classic(token, statement_year)
            if not date_iso:
                continue

            desc_parts = []
            amounts = []
            for w in line:
                if w["text"] == token:
                    continue
                if AMOUNT_RE_CLASSIC.match(w["text"]):
                    amounts.append((w["x0"], w["text"]))
                else:
                    desc_parts.append(w["text"])

            if not amounts:
                continue

            amounts.sort(key=lambda a: a[0])
            balance_val, _ = parse_amt_classic(amounts[-1][1])

            txn_val = None
            txn_sign = None
            if len(amounts) > 1:
                txn_val, txn_sign = parse_amt_classic(amounts[-2][1])

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
                if txn_sign == "+" and txn_val is not None:
                    credit = txn_val
                elif txn_sign == "-" and txn_val is not None:
                    debit = txn_val

            processed_y_buckets.add(y_bucket)

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

    doc.close()
    return transactions
