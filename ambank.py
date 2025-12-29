import re
import pdfplumber


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


def parse_ambank(pdf_input, source_file: str = ""):
    bank_name = "AmBank"
    tx = []

    # 06Sep, 9Sep, etc
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

    if hasattr(pdf_input, "pages"):
        parse_pdf(pdf_input)
        return tx

    try:
        pdf_input.seek(0)
    except Exception:
        pass

    try:
        with pdfplumber.open(pdf_input) as pdf:
            parse_pdf(pdf)
    except Exception:
        return []

    return tx
