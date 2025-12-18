"""
RHB Adapter
-----------
Allows rhb_v1 (page-level parser) to be used in app_v2 (PDF-level parser)
WITHOUT modifying rhb_v1.

Fix: seed opening balance AND prevent rhb_v1 from resetting globals on page 1
by calling it with a non-1 page number for the first page.
"""

import regex as re

import rhb
from rhb import parse_transactions_rhb as rhb_v1_parser


# ============================================================
# OPENING BALANCE EXTRACTION (STATEMENT HEADER)
# ============================================================

# Tries to find: "Beginning Balance ..." followed (somewhere soon after) by "840,813.71-"
OPENING_BAL_RE = re.compile(
    r"Beginning\s+Balance.*?([0-9,]+\.\d{2})-",
    re.IGNORECASE | re.DOTALL
)

def extract_opening_balance(text: str):
    """
    Returns opening balance as float (negative if trailing '-'), else None.
    """
    m = OPENING_BAL_RE.search(text or "")
    if not m:
        return None
    return -float(m.group(1).replace(",", ""))


# ============================================================
# ADAPTER FUNCTION (app_v2 INTERFACE)
# ============================================================

def parse_transactions_rhb(pdf, source_file):
    """
    app_v2 interface:
        parse_transactions_rhb(pdf, source_file)

    Calls rhb_v1:
        parse_transactions_rhb(text, page_num, year)
    """
    all_tx = []

    # -------------------------------------------
    # Detect year from filename (fallback = 2025)
    # -------------------------------------------
    year = 2025
    for y in range(2015, 2031):
        if str(y) in (source_file or ""):
            year = y
            break

    # -------------------------------------------
    # IMPORTANT: reset rhb_v1 global ourselves
    # -------------------------------------------
    rhb._prev_balance_global = None

    # -------------------------------------------
    # Loop through PDF pages
    # -------------------------------------------
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        # Seed opening balance from page 1 header
        if page_num == 1:
            opening_balance = extract_opening_balance(text)
            rhb._prev_balance_global = opening_balance

            # CRITICAL TRICK:
            # rhb_v1 resets global when page_num == 1
            # so we call it with 0 to prevent that reset
            v1_page_num = 0
        else:
            v1_page_num = page_num

        # Call ORIGINAL rhb_v1 parser
        page_tx = rhb_v1_parser(text, v1_page_num, year)

        # Add app_v2 required metadata + fix page number
        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            tx["page"] = page_num  # restore real page number for app_v2
            all_tx.append(tx)

    return all_tx
