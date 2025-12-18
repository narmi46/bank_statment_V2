def parse_transactions_maybank(pdf_input, source_filename):
    import fitz
    from datetime import datetime

    def is_day(t): return t.isdigit() and 1 <= int(t) <= 31
    def is_month(t): return t.capitalize() in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    def is_year(t): return t.isdigit() and t.startswith("20")

    def parse_amount(v):
        return float(v.replace(",", ""))

    # ---------------- OPEN PDF ----------------
    if hasattr(pdf_input, "stream"):
        pdf_input.stream.seek(0)
        doc = fitz.open(stream=pdf_input.stream.read(), filetype="pdf")
    else:
        doc = fitz.open(pdf_input)

    transactions = []
    previous_balance = None
    bank_name = "Maybank Islamic"

    # ---------------- PARSE ----------------
    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))

        used_rows = set()

        for i in range(len(rows) - 2):
            w1, w2, w3 = rows[i], rows[i+1], rows[i+2]

            # ✅ Detect split date: 01 Feb 2025
            if not (is_day(w1["text"]) and is_month(w2["text"]) and is_year(w3["text"])):
                continue

            y_key = w1["y"]
            if y_key in used_rows:
                continue

            try:
                date_iso = datetime.strptime(
                    f"{w1['text']} {w2['text']} {w3['text']}",
                    "%d %b %Y"
                ).strftime("%Y-%m-%d")
            except:
                continue

            # Collect full row
            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc_parts = []
            amounts = []

            for w in line:
                if w in (w1, w2, w3):
                    continue
                if w["text"].replace(",", "").replace(".", "").isdigit():
                    if "." in w["text"]:
                        amounts.append(w["text"])
                else:
                    desc_parts.append(w["text"])

            if len(amounts) == 0:
                continue

            balance = parse_amount(amounts[-1])
            debit = credit = 0.0
            
            # CASE 1: Use balance delta when possible (most reliable)
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta < 0:
                    debit = abs(delta)
                elif delta > 0:
                    credit = delta
            
            # CASE 2: FIRST ROW → fallback to printed transaction amount
            elif len(amounts) >= 2:
                txn_amt = parse_amount(amounts[-2])
            
                # Maybank prints DR / minus as debit
                if "DR" in " ".join(desc_parts).upper() or "DEBIT" in " ".join(desc_parts).upper():
                    debit = txn_amt
                else:
                    debit = txn_amt   # Maybank fees are always debit


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
            used_rows.add(y_key)

    doc.close()
    return transactions
