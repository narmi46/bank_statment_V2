import regex as re
import rhb

# ============================================================
# OPENING BALANCE (B/F FIRST, SUMMARY SECOND)
# ============================================================

BF_BAL_RE = re.compile(
    r"\d{1,2}\s+[A-Za-z]{3}\s+B/F\s+BALANCE\s+([0-9,]+\.\d{2})(-?)",
    re.IGNORECASE
)

OPENING_BAL_RE = re.compile(
    r"Opening\s+Balance.*?([0-9,]+\.\d{2})(-?)",
    re.IGNORECASE | re.DOTALL
)

def _signed(val, minus):
    v = float(val.replace(",", ""))
    return -v if minus == "-" else v


def extract_opening_balance(text):
    if not text:
        return None

    m = BF_BAL_RE.search(text)
    if m:
        return _signed(*m.groups())

    m = OPENING_BAL_RE.search(text)
    if m:
        return _signed(*m.groups())

    return None


# ============================================================
# ADAPTER ENTRY POINT
# ============================================================

def parse_transactions_rhb(pdf, source_file):
    all_tx = []

    # ---- Detect year ----
    year = 2025
    for y in range(2015, 2031):
        if str(y) in (source_file or ""):
            year = y
            break

    rhb._prev_balance_global = None

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        if page_num == 1:
            rhb._prev_balance_global = extract_opening_balance(text)
            v1_page_num = 0
        else:
            v1_page_num = page_num

        page_tx = rhb.parse_transactions_rhb(text, v1_page_num, year)

        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            tx["page"] = page_num
            all_tx.append(tx)

    return all_tx
