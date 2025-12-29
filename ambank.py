import re
import pdfplumber
from datetime import datetime

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def _clean_amount(x: str):
    if not x:
        return None
    x = x.strip().replace(",", "").replace(" ", "")
    if not x:
        return None
    if x.startswith("(") and x.endswith(")"):
        x = "-" + x[1:-1]
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", x):
        return None
    return x

def _compare_or_mark(manual, summary):
    if summary is None:
        return manual
    if round(manual, 2) == round(summary, 2):
        return manual
    return f"*{summary:.2f}"

# ---------------------------------------------------
# Regex
# ---------------------------------------------------
DATE_RE = re.compile(r"^(?P<date>\d{1,2}[A-Za-z]{3})\s+(?P<rest>.+)$")
AMOUNT_RE = re.compile(r"\(?[\d,]+\.\d{2}\)?")

STATEMENT_YEAR_RE = re.compile(
    r"STATEMENT DATE.*?\d{2}/\d{2}/(?P<year>\d{4})",
    re.IGNORECASE
)

OPENING_BALANCE_RE = re.compile(
    r"OPENING BALANCE.*?([\d,]+\.\d{2})",
    re.IGNORECASE
)

SUMMARY_DEBIT_RE = re.compile(
    r"TOTAL DEBITS.*?([\d,]+\.\d{2})",
    re.IGNORECASE
)

SUMMARY_CREDIT_RE = re.compile(
    r"TOTAL CREDITS.*?([\d,]+\.\d{2})",
    re.IGNORECASE
)

# ---------------------------------------------------
# Main Parser
# ---------------------------------------------------
def parse_ambank(pdf_input, source_file: str = ""):
    """
    AmBank statement parser.
    - Opening balance from ACCOUNT SUMMARY only
    - Debit/Credit via balance delta
    - Output date format: YYYY-MM-DD
    """

    bank_name = "AmBank"
    tx = []

    summary_debit = None
    summary_credit = None
    opening_balance = None
    statement_year = None

    def flush_tx(buf, page_idx, prev_balance):
        if not buf:
            return prev_balance

        text = " ".join(buf["lines"]).strip()

        # Skip Balance B/F rows completely (NOT a transaction)
        if re.search(r"\b(balance b/f|baki bawa ke hadapan)\b", text, re.IGNORECASE):
            return prev_balance

        amounts = AMOUNT_RE.findall(text)
        amounts = [_clean_amount(a) for a in amounts if _clean_amount(a)]

        if not amounts:
            return prev_balance

        try:
            balance = float(amounts[-1])
        except Exception:
            return prev_balance

        debit = credit = 0.0

        if prev_balance is not None:
            delta = round(balance - prev_balance, 2)
            if delta > 0:
                credit = delta
            elif delta < 0:
                debit = -delta

        # ---- DATE NORMALIZATION ----
        try:
            normalized_date = datetime.strptime(
                f"{buf['date']}{statement_year}",
                "%d%b%Y"
            ).strftime("%Y-%m-%d")
        except Exception:
            normalized_date = buf["date"]

        tx.append({
            "date": normalized_date,
            "description": text,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "page": page_idx,
            "bank": bank_name,
            "source_file": source_file or ""
        })

        return balance

    def parse_pdf(pdf):
        nonlocal summary_debit, summary_credit, opening_balance, statement_year

        # ---------- FIRST PAGE (ACCOUNT SUMMARY) ----------
        first_page_text = pdf.pages[0].extract_text() or ""

        m = STATEMENT_YEAR_RE.search(first_page_text)
        if m:
            statement_year = int(m.group("year"))

        m = OPENING_BALANCE_RE.search(first_page_text)
        if m:
            opening_balance = float(_clean_amount(m.group(1)))

        m = SUMMARY_DEBIT_RE.search(first_page_text)
        if m:
            summary_debit = float(_clean_amount(m.group(1)))

        m = SUMMARY_CREDIT_RE.search(first_page_text)
        if m:
            summary_credit = float(_clean_amount(m.group(1)))

        # ---------- TRANSACTIONS ----------
        prev_balance = opening_balance

        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

            current = None

            for ln in lines:
                m = DATE_RE.match(ln)
                if m:
                    prev_balance = flush_tx(current, page_idx, prev_balance)
                    current = {
                        "date": m.group("date"),
                        "lines": [m.group("rest")]
                    }
                elif current:
                    current["lines"].append(ln)

            prev_balance = flush_tx(current, page_idx, prev_balance)

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

    for t in tx:
        t["total_debit"] = final_debit
        t["total_credit"] = final_credit

    return tx
