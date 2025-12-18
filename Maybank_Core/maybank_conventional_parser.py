def parse_transactions_maybank_conventional(pdf_input, source_filename):
    import re
    import fitz
    import os
    from datetime import datetime

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
    AMOUNT_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})*|\d+)?\.\d{2}[+-]?$")

    def open_doc(inp):
        if isinstance(inp, str):
            if not os.path.exists(inp):
                raise FileNotFoundError(f"PDF not found: {inp}")
            return fitz.open(inp)
        if hasattr(inp, "stream"):
            inp.stream.seek(0)
            return fitz.open(stream=inp.stream.read(), filetype="pdf")
        raise ValueError("Unsupported PDF input type")

    def norm_date(token, year):
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

    def parse_amt(t):
        t = t.strip()
        sign = "+" if t.endswith("+") else "-" if t.endswith("-") else None
        v = float(t.replace(",", "").rstrip("+-"))
        return v, sign

    doc = open_doc(pdf_input)

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
            if not DATE_RE.match(token):
                continue

            y_ref = r["y0"]
            y_bucket = round(y_ref, 1)
            if y_bucket in processed_y:
                continue

            line = [w for w in rows if abs(w["y0"] - y_ref) <= Y_TOL]
            line.sort(key=lambda w: w["x0"])

            date_iso = norm_date(token, statement_year)
            if not date_iso:
                continue

            desc_parts = []
            amounts = []

            for w in line:
                if w["text"] == token:
                    continue
                if AMOUNT_RE.match(w["text"]):
                    amounts.append((w["x0"], w["text"]))
                else:
                    desc_parts.append(w["text"])

            if not amounts:
                continue

            amounts.sort(key=lambda a: a[0])
            balance_val, _ = parse_amt(amounts[-1][1])

            txn_val = None
            txn_sign = None
            if len(amounts) > 1:
                txn_val, txn_sign = parse_amt(amounts[-2][1])

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

    doc.close()
    return transactions
