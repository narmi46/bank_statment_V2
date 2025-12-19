# =================================================
    # STEP 1: OPENING BALANCE (RELIABLE FLOW SEARCH)
    # =================================================
    opening_balance = None
    first_page = doc[0]
    words = first_page.get_text("words")

    # Get words and sort them by their natural reading order (Y then X)
    rows = [{
        "x": w[0],
        "y": round(w[1], 1),
        "text": w[4].strip()
    } for w in words if w[4].strip()]
    rows.sort(key=lambda r: (r["y"], r["x"]))

    for i, r in enumerate(rows):
        t = r["text"].upper()
        # Look for the start of the "Beginning Balance" phrase
        if "BEGINNING" in t:
            # Check the next few words to confirm it's the balance header
            context = " ".join([w["text"].upper() for w in rows[i:i+5]])
            if "BEGINNING BALANCE" in context:
                # Search forward for the first valid money amount
                for search_idx in range(i, min(i + 15, len(rows))):
                    item_text = rows[search_idx]["text"]
                    if MONEY_RE.match(item_text):
                        opening_balance = parse_money(item_text)
                        break
                if opening_balance is not None:
                    break
