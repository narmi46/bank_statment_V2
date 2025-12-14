# bank_muamalat.py

def parse_transactions_bank_muamalat(pdf, source_file):
    """
    Dummy parser for Bank Muamalat.
    Returns empty list for now.
    Implement real parsing logic later.
    """

    transactions = []

    # Placeholder loop (kept for future expansion)
    for page_num, page in enumerate(pdf.pages, start=1):
        _ = page.extract_text()  # intentionally unused for now
        pass

    return transactions

