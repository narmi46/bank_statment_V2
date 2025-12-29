import re
import pdfplumber


def _clean_amount(x: str):
    """Convert common money strings to float-like string, or None."""
    if x is None:
        return None

    x = x.strip()
    if not x:
        return None

    x = x.replace(",", "").replace(" ", "")

    if x.startswith("(") and x.endswith(")"):
        x = "-" + x[1:-1]

    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", x):
        return None

    return x


SUMMARY_DEBIT_RE = re.compile(
    r"TOTAL DEBITS.*?([\d,]+\.\d{2})", re.IGNORECASE
)

SUMMARY_CREDIT_RE = re.compile(
    r"TOTAL CREDITS.*?([\d,]+\.\d{2})", re.IGNORECASE
)


def _compare_or_mark(manual, summary):
    """
    If manual == summary -> return manual
    If mismatch -> return '*summary'
    """
    if summary is None:
        return manual

    if round(manual, 2) == round(summary, 2):
        return manual

    return f"*{summary:.2f}"


def parse_ambank(pdf_input, source_file: str = ""):
    """
    AmBank statement parser.

    Accepts:
      - pdfplumber.PDF
      - file-like object (e.g. Streamlit UploadedFile)

    Returns:
      list[dict]
    """

    bank_name = "AmBank"
    tx = []

    summary_debit = None
    summary_credit = None

    # Example: 06Sep, 9Sep
    date_re = re.compile(r"^(?P<date>\d{1,2}[A-Za-z]{3})\s+(?P<rest>.+)$")
    amount_re = re.compile(r"\(?[\d,]+\.\d{2}\)?")

    def flush_tx(buf, page_idx):
        if not buf:
            return

        text = " ".join(buf["lines"])

        amounts = amount_re.findall(text)
        amounts = [_clean_amount(a) for a in amounts if _clean_amount(a)]

        debit = credit = balance = None

        if len(amounts) >= 2:
            balance = amounts[-1]
            main_amt = amounts[-2]

            if "CR" in text or "CREDIT" in text:
                credit = main_amt
            else:
                debit = main_amt

        tx.append({
            "date": buf["date"],
            "description": text.strip(),
            "debit": float(debit) if debit else 0.0,
            "credit": float(credit) if credit else 0.0,
            "balance": float(balance) if balance else None,
            "page": page_idx,
            "bank": bank_name,
            "source_file": source_file or ""
        })

    def parse_pdf(pdf):
        nonlocal summary_debit, summary_credit

        # ---------- SUMMARY EXTRACTION (PAGE 1) ----------
        first_page_text = pdf.pages[0].extract_text() or ""

        m = SUMMARY_DEBIT_RE.search(first_page_text)
        if m:
            summary_debit = float(_clean_amount(m.group(1)))

        m = SUMMARY_CREDIT_RE.search(first_page_text)
        if m:
            summary_credit = float(_clean_amount(m.group(1)))

        # ---------- TRANSACTION PARSING ----------
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            current = None

            for ln in lines:
                m = date_re.match(ln)
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

    # ---------- TOTAL VALIDATION ----------
    manual_debit = round(sum(t["debit"] for t in tx), 2)
    manual_credit = round(sum(t["credit"] for t in tx), 2)

    final_debit = _compare_or_mark(manual_debit, summary_debit)
    final_credit = _compare_or_mark(manual_credit, summary_credit)

    # ---------- OPTION B: INJECT TOTALS ----------
    for t in tx:
        t["total_debit"] = final_debit
        t["total_credit"] = final_credit

    return tx
