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

    # ---------------- HELPERS ----------------
    DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}[+-]?$")

    def parse_money(t: str) -> float:
        neg = t.endswith("-")
        pos = t.endswith("+")
        t = t[:-1] if neg or pos else t
        v = float(t.replace(",", ""))
        return -v if neg else v

    def norm_date(t):
        return datetime.strptime(t, "%d-%m-%Y").strftime("%Y-%m-%d")

    # ==========================================================
    # STEP 1: OPENING BALANCE (X-AXIS SAME LINE EXTRACTION)
    # ==========================================================
    opening_balance = None
    first_page = doc[0]
    words = first_page.get_text("words")

    rows = [{
        "x": w[0],
        "y": round(w[1], 1),
        "text": w[4].strip()
    } for w in words if w[4].strip()]

    for r in rows:
        t = r["text"].upper()
        if "BEGINNING" in t and "BALANCE" in t:
            y_ref = r["y"]
            x_ref = r["x"]

            same_line = [
                w for w in rows
                if abs(w["y"] - y_ref) <= 1.5
                and w["x"] > x_ref
                and MONEY_RE.match(w["text"])
            ]

            if same_line:
                same_line.sort(key=lambda w: w["x"])
                opening_balance = parse_money(same_line[-1]["text"])
            break

    # ---------------- MAIN PARSER ----------------
    transactions = []
    previous_balance = opening_balance  # ✅ critical

    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))
        used_y = set()

        for r in rows:
            if not DATE_RE.match(r["text"]):
                continue

            y_key = r["y"]
            if y_key in used_y:
                continue

            date_iso = norm_date(r["text"])

            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc = []
            money = []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if MONEY_RE.match(w["text"]):
                    money.append(w)
                else:
                    if not w["text"].isdigit():
                        desc.append(w["text"])

            if not money:
                continue

            # rightmost money = balance
            balance = parse_money(max(money, key=lambda m: m["x"])["text"])

            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": date_iso,
                "description": " ".join(desc)[:200],
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
