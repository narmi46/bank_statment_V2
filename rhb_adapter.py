"""
RHB Adapter (PDF-level)
Fixes:
- Opening balance
- First transaction debit/credit
- Page reset bug
"""

import regex as re
import rhb


# ============================================================
# OPENING BALANCE (ISLAMIC + CONVENTIONAL SAFE)
# ============================================================

OPENING_BAL_RE = re.compile(
    r"Opening\s+Balance.*?\n.*?([0-9,]+\.\d{2})(-?)",
    re.IGNORECASE | re.DOTALL
)

def extract_opening_balance(text):
    if not text:
        return None

    m = OPENING_BAL_RE.search(text)
    if not m:
        return None

    amount, minus = m.groups()
    val = float(amount.replace(",", ""))
    return -val if minus == "-" else val


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

    # ---- Reset v1 state manually ----
    rhb._prev_balance_global = None

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        # ---- Seed opening balance on page 1 ----
        if page_num == 1:
            rhb._prev_balance_global = extract_opening_balance(text)
            v1_page_num = 0   # PREVENT reset in v1
        else:
            v1_page_num = page_num

        page_tx = rhb.parse_transactions_rhb(text, v1_page_num, year)

        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            tx["page"] = page_num
            all_tx.append(tx)

    return all_tx
