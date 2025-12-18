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
    DATE_RE = re.compile(r"^\d{2}/\d{2}$")
    MONEY_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")

    def parse_money(t):
        return float(t.replace(",", ""))

    def norm_date(token):
        try:
            return datetime.strptime(
                f"{token}/{statement_year}", "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
        except:
            return None

    # ---------------- MAIN PARSER ----------------
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

            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc_parts = []
            amounts = []

            for w in line:
                if w["text"] == token:
                    continue
                if MONEY_RE.match(w["text"]):
                    amounts.append(w["text"])
                else:
                    desc_parts.append(w["text"])

            if not amounts:
                continue

            balance = parse_money(amounts[-1])
            debit = credit = 0.0

            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)
            else:
                # FIRST ROW fallback: printed transaction amount
                if len(amounts) >= 2:
                    txn_amt = parse_money(amounts[-2])
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

    doc.close()
    return transactions
