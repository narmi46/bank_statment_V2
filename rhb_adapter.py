import re
import datetime

def parse_transactions_rhb(pdf, source_file):
    """
    RHB statements (like your PDF) have dates formatted as '07Mar' (no space).
    This parser extracts transactions across all pages using pdfplumber.extract_text().
    """
    transactions = []
    bank_name = "RHB Bank"

    # Date at start of line: 07Mar, 31Mar, etc.
    date_re = re.compile(r'^(\d{2}[A-Za-z]{3})\b')
    num_re = re.compile(r'\d[\d,]*\.\d{2}')

    year = 2024  # Your statement period is Mar 2024 :contentReference[oaicite:3]{index=3}
    prev_balance = None
    current = None

    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        for line in lines:
            # Skip headers/noise
            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "ORDINARYCURRENTACCOUNT",
                "Date Description", "Tarikh", "Total Count",
                "Debit Credit Balance", "Debit Kredit Baki"
            ]):
                continue

            m = date_re.match(line)

            if m:
                # flush previous transaction
                if current:
                    transactions.append(current)
                    prev_balance = current.get("balance", prev_balance)

                code = m.group(1)

                # Skip B/F and C/F balance rows (not transactions)
                if "B/FBALANCE" in line or "C/FBALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in num_re.findall(line)]
                    if amts:
                        prev_balance = amts[-1]
                    current = None
                    continue

                # Parse date (07Mar -> 2024-03-07)
                try:
                    dt = datetime.datetime.strptime(f"{code}{year}", "%d%b%Y").date()
                    date_out = dt.isoformat()
                except Exception:
                    date_out = f"{code} {year}"

                # Extract amounts on that line
                amts = [float(a.replace(",", "")) for a in num_re.findall(line)]
                debit = 0.0
                credit = 0.0
                balance = None

                if len(amts) == 3:
                    debit, credit, balance = amts[0], amts[1], amts[2]
                elif len(amts) == 2:
                    amt, balance = amts[0], amts[1]

                    # Decide if amt is debit or credit using DR/CR hint or balance math
                    if "DR" in line and "CR" not in line:
                        debit = amt
                    elif "CR" in line and "DR" not in line:
                        credit = amt
                    else:
                        # infer using previous balance if available
                        if prev_balance is not None:
                            if abs((prev_balance + amt) - balance) < 0.02:
                                credit = amt
                            elif abs((prev_balance - amt) - balance) < 0.02:
                                debit = amt
                            else:
                                debit = amt
                        else:
                            debit = amt
                elif len(amts) == 1:
                    balance = amts[0]

                # Build description from line (remove date + amounts)
                desc = line[len(code):].strip()
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = " ".join(desc.split())

                current = {
                    "date": date_out,
                    "description": desc,
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                }

            else:
                # Continuation lines (names, "FundTransfer", "pay", etc.)
                if current:
                    current["description"] = " ".join((current["description"] + " " + line).split())

    if current:
        transactions.append(current)

    return transactions
