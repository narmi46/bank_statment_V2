def parse_transactions_maybank(pdf_input, source_filename):
    import re
    import fitz
    from datetime import datetime

    # ---------------- REGEX ----------------
    DATE_RE = re.compile(r"^\d{2}\s+[A-Z][a-z]{2}$")  # 01 Feb
    YEAR_RE = re.compile(r"\b(20\d{2})\b")
    AMOUNT_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")

    def parse_amount(v):
        return float(v.replace(",", ""))

    def normalize_date(day_month, year):
        return datetime.strptime(
            f"{day_month} {year}", "%d %b %Y"
        ).strftime("%Y-%m-%d")

    # ---------------- OPEN PDF (Streamlit-safe) ----------------
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        doc = fitz.open(stream=pdf_input.stream.read(), filetype="pdf")
    else:
        doc = fitz.open(pdf_input)

    bank_name = "Maybank Islamic"
    statement_year = str(datetime.now().year)

    first_page_text = doc[0].get_text("text")
    year_match = YEAR_RE.search(first_page_text)
    if year_match:
        statement_year = year_match.group(1)

    transactions = []
    previous_balance = None

    # ---------------- PARSE ----------------
    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": w[1],
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        rows.sort(key=lambda r: (round(r["y"], 1), r["x"]))

        Y_TOL = 2.0
        processed_rows = set()

        for r in rows:
            if not DATE_RE.match(r["text"]):
                continue

            y_key = round(r["y"], 1)
            if y_key in processed_rows:
                continue

            line = [w for w in rows if abs(w["y"] - r["y"]) <= Y_TOL]
            line.sort(key=lambda w: w["x"])

            try:
                date_iso = normalize_date(r["text"], statement_year)
            except:
                continue

            desc_parts = []
            amounts = []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if AMOUNT_RE.match(w["text"]):
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
            processed_rows.add(y_key)

    doc.close()
    return transactions

