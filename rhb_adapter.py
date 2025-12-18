"""
RHB Adapter
-----------
Allows rhb_v1 (page-level parser) to be used in app_v2 (PDF-level parser)
WITHOUT modifying rhb_v1.

Fixes first-transaction misclassification by seeding opening balance.
"""

import regex as re

# Import rhb module AND parser
import rhb
from rhb import parse_transactions_rhb as rhb_v1_parser


# ============================================================
# OPENING BALANCE EXTRACTION (STATEMENT HEADER)
# ============================================================

OPENING_BAL_RE = re.compile(
    r"Beginning Balance.*?\n\s*([0-9,]+\.\d{2})-",
    re.IGNORECASE | re.DOTALL
)

def extract_opening_balance(text):
    """
    Extract opening balance from RHB statement header.
    Returns float or None.
    """
    m = OPENING_BAL_RE.search(text)
    if not m:
        return None

    # RHB uses trailing "-" to indicate negative
    return -float(m.group(1).replace(",", ""))


# ============================================================
# ADAPTER FUNCTION (app_v2 INTERFACE)
# ============================================================

def parse_transactions_rhb(pdf, source_file):
    """
    Adapter function matching app_v2 interface:
        parse_transactions_rhb(pdf, source_file)

    Internally calls rhb_v1:
        parse_transactions_rhb(text, page_num, year)
    """

    all_tx = []

    # -------------------------------------------
    # Detect year from filename (fallback = 2025)
    # -------------------------------------------
    year = 2025
    for y in range(2015, 2031):
        if str(y) in source_file:
            year = y
            break

    # -------------------------------------------
    # Loop through PDF pages
    # -------------------------------------------
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        # -------------------------------------------
        # Seed opening balance BEFORE page 1 parsing
        # -------------------------------------------
        if page_num == 1:
            opening_balance = extract_opening_balance(text)
            rhb._prev_balance_global = opening_balance

        # -------------------------------------------
        # Call ORIGINAL rhb_v1 parser
        # -------------------------------------------
        page_tx = rhb_v1_parser(
            text,
            page_num,
            year
        )

        # -------------------------------------------
        # Add app_v2 required metadata
        # -------------------------------------------
        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            all_tx.append(tx)

    return all_tx
