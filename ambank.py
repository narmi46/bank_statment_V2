def parse_ambank(pdf_input, source_file: str = ""):
    """
    AmBank statement parser.
    Uses statement SUMMARY totals as source of truth.
    Compatible with app.py (returns list of transactions).
    """

    bank_name = "AmBank"
    tx = []

    summary_debit = None
    summary_credit = None
    statement_year = None

    def flush_tx(buf, page_idx):
        if not buf:
            return

        text = " ".join(buf["lines"])

        amounts = AMOUNT_RE.findall(text)
        amounts = [_clean_amount(a) for a in amounts if _clean_amount(a)]

        debit = credit = balance = None

        if len(amounts) >= 2:
            balance = amounts[-1]
            main_amt = amounts[-2]

            if re.search(r"\bCR\b|\bCREDIT\b", text):
                credit = main_amt
            else:
                debit = main_amt

        # ---- DATE NORMALIZATION ----
        try:
            if statement_year:
                normalized_date = datetime.strptime(
                    f"{buf['date']}{statement_year}",
                    "%d%b%Y"
                ).strftime("%Y-%m-%d")
            else:
                normalized_date = buf["date"]
        except Exception:
            normalized_date = buf["date"]

        tx.append({
            "date": normalized_date,
            "description": text.strip(),
            "debit": float(debit) if debit else 0.0,
            "credit": float(credit) if credit else 0.0,
            "balance": float(balance) if balance else None,
            "page": page_idx,
            "bank": bank_name,
            "source_file": source_file or ""
        })

    def parse_pdf(pdf):
        nonlocal summary_debit, summary_credit, statement_year

        # ---------- FIRST PAGE (SUMMARY) ----------
        first_page_text = pdf.pages[0].extract_text() or ""

        m = STATEMENT_YEAR_RE.search(first_page_text)
        if m:
            statement_year = int(m.group("year"))

        m = SUMMARY_DEBIT_RE.search(first_page_text)
        if m:
            summary_debit = float(_clean_amount(m.group(1)))

        m = SUMMARY_CREDIT_RE.search(first_page_text)
        if m:
            summary_credit = float(_clean_amount(m.group(1)))

        # ---------- TRANSACTIONS ----------
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            current = None

            for ln in lines:
                m = DATE_RE.match(ln)
                if m:
                    flush_tx(current, page_idx)
                    current = {
                        "date": m.group("date"),
                        "lines": [m.group("rest")]
                    }
                elif current:
                    current["lines"].append(ln)

            flush_tx(current, page_idx)

    # ---------- OPEN PDF ----------
    if hasattr(pdf_input, "pages"):
        parse_pdf(pdf_input)
    else:
        try:
            pdf_input.seek(0)
        except Exception:
            pass

        try:
            with pdfplumber.open(pdf_input) as pdf:
                parse_pdf(pdf)
        except Exception:
            return []

    # ---------- INJECT SUMMARY TOTALS (SOURCE OF TRUTH) ----------
    for t in tx:
        t["total_debit"] = summary_debit
        t["total_credit"] = summary_credit

    return tx
