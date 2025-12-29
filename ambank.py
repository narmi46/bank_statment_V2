import re
import pdfplumber
from datetime import datetime

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def _clean_amount(x: str):
    if x is None:
        return None
    x = x.strip().replace(",", "").replace(" ", "")
    if not x:
        return None
    if x.startswith("(") and x.endswith(")"):
        x = "-" + x[1:-1]
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", x):
        return None
    return x

# ---------------------------------------------------
# Regex (MODULE LEVEL!)
# ---------------------------------------------------
DATE_RE = re.compile(r"^(?P<date>\d{1,2}[A-Za-z]{3})\s+(?P<rest>.+)$")
AMOUNT_RE = re.compile(r"\(?[\d,]+\.\d{2}\)?")

SUMMARY_DEBIT_RE = re.compile(r"TOTAL DEBITS.*?([\d,]+\.\d{2})", re.IGNORECASE)
SUMMARY_CREDIT_RE = re.compile(r"TOTAL CREDITS.*?([\d,]+\.\d{2})", re.IGNORECASE)

# More robust for your PDF: "STATEMENT DATE : 01/03/2024 - 31/03/2024"
STATEMENT_YEAR_RE = re.compile(
    r"STATEMENT DATE.*?(\d{2})/(\d{2})/(?P<year>\d{4})",
    re.IGNORECASE
)

# ---------------------------------------------------
# Main Parser
# ---------------------------------------------------
def parse_ambank(pdf_input, source_file: str = ""):
    """
    AmBank statement parser.
    Uses statement SUMMARY totals as source of truth.
    Returns list[dict] compatible with app.py :contentReference[oaicite:1]{index=1}
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

        first_page_text = pdf.pages[0].extract_text() or ""

        # Year (from statement date range on page 1)
        m = STATEMENT_YEAR_RE.search(first_page_text)
        if m:
            statement_year = int(m.group("year"))

        # Summary totals on page 1
        m = SUMMARY_DEBIT_RE.search(first_page_text)
        if m:
            summary_debit = float(_clean_amount(m.group(1)))

        m = SUMMARY_CREDIT_RE.search(first_page_text)
        if m:
            summary_credit = float(_clean_amount(m.group(1)))

        # Transactions
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            current = None
            for ln in lines:
                m = DATE_RE.match(ln)
                if m:
                    flush_tx(current, page_idx)
                    current = {"date": m.group("date"), "lines": [m.group("rest")]}
                elif current:
                    current["lines"].append(ln)

            flush_tx(current, page_idx)

    # Open handling
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

    # Inject summary totals (source of truth)
    for t in tx:
        t["total_debit"] = summary_debit
        t["total_credit"] = summary_credit

    return tx
