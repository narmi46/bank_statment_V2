"""
RHB Adapter
-----------
Allows rhb_v1 (page-level parser) to be used in app_v2 (PDF-level parser)
WITHOUT modifying rhb_v1.
"""

# Import the ORIGINAL rhb_v1 parser
from rhb import parse_transactions_rhb as rhb_v1_parser


def parse_transactions_rhb(pdf, source_file):
    """
    Adapter function that matches app_v2's expected interface:
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
    # Loop through PDF pages (app_v2 style)
    # -------------------------------------------
    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""

        # Call ORIGINAL rhb_v1 parser
        page_tx = rhb_v1_parser(
            text,
            page_num,
            year
        )

        # Add app_v2 required metadata
        for tx in page_tx:
            tx["bank"] = "RHB Bank"
            tx["source_file"] = source_file
            all_tx.append(tx)

    return all_tx
