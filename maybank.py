from Maybank_Core.conventional import parse_transactions_maybank_conventional
from Maybank_Core.islamic import parse_transactions_maybank_islamic


def parse_transactions_maybank(pdf_input, source_filename):
    """
    Wrapper function required by app.py
    Tries both Maybank formats and returns best result
    """

    tx_conventional = parse_transactions_maybank_conventional(
        pdf_input, source_filename
    )

    tx_islamic = parse_transactions_maybank_islamic(
        pdf_input, source_filename
    )

    # Prefer parser with more transactions
    if tx_conventional and tx_islamic:
        return merge_and_dedupe(tx_conventional, tx_islamic)

    return tx_conventional if len(tx_conventional) >= len(tx_islamic) else tx_islamic


def merge_and_dedupe(a, b):
    seen = set()
    merged = []

    for t in a + b:
        key = (
            t.get("date"),
            t.get("description"),
            t.get("debit"),
            t.get("credit"),
            t.get("balance"),
            t.get("page"),
            t.get("source_file"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(t)

    return merged
