def parse_standard_format(text, page, year, source):
    transactions = []
    lines = [l.rstrip() for l in text.splitlines()]
    i = 0

    date_re = re.compile(
        r'^\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b',
        re.IGNORECASE
    )

    money_re = re.compile(r'^\d{1,3}(?:,\d{3})*\.\d{2}$')  # STRICT money only

    while i < len(lines):
        line = lines[i].strip()
        m = date_re.match(line)

        if not m:
            i += 1
            continue

        day, mon = m.groups()
        day = day.zfill(2)
        month = MONTH_MAP[mon.capitalize()]

        rest = line[m.end():].strip()

        # Skip balances
        if 'B/F BALANCE' in rest or 'C/F BALANCE' in rest:
            i += 1
            continue

        desc_parts = []
        amounts = []

        # ---- parse current line ----
        for token in rest.split():
            if money_re.match(token):
                amounts.append(parse_amount(token))
            else:
                desc_parts.append(token)

        # ---- lookahead lines (VERY IMPORTANT) ----
        j = i + 1
        while j < len(lines):
            nl = lines[j].strip()

            if date_re.match(nl):
                break

            for token in nl.split():
                if money_re.match(token):
                    amounts.append(parse_amount(token))
                else:
                    desc_parts.append(token)

            # stop once we have at least amount + balance
            if len(amounts) >= 2:
                break

            j += 1

        if len(amounts) < 2:
            i += 1
            continue

        balance = amounts[-1]
        amount = amounts[-2]

        description = clean_text(" ".join(desc_parts))
        debit, credit = classify_amount(description, amount)

        transactions.append({
            "date": f"{year}-{month}-{day}",
            "description": description,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "page": page,
            "source_file": source,
            "bank": "RHB Bank"
        })

        i = j if j > i else i + 1

    return transactions
