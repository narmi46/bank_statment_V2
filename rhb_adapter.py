import re
import datetime


def parse_transactions_rhb(pdf, source_file):
    transactions = []
    bank_name = "RHB Bank"

    # Matches both "07Mar" and "07 Mar"
    date_re = re.compile(r'^(\d{2})\s*([A-Za-z]{3})\b')
    amount_re = re.compile(r'\d[\d,]*\.\d{2}')

    # --------------------------------------------------
    # 1️⃣ Detect YEAR from "Statement Period"
    # --------------------------------------------------
    year = None
    for page in pdf.pages[:1]:
        text = page.extract_text() or ""
        m = re.search(
            r'Statement Period.*?(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]\s*(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})',
            text,
            re.S
        )
        if m:
            year = int("20" + m.group(2))
            break

    if not year:
        year = datetime.date.today().year

    prev_balance = None
    current = None
    pending_desc = []

    # --------------------------------------------------
    # 2️⃣ Main Parsing Loop
    # --------------------------------------------------
    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        for line in lines:

            # Skip headers / noise
            if any(x in line for x in [
                "ACCOUNT ACTIVITY", "ORDINARY CURRENT", "QARD CURRENT",
                "Date", "Tarikh", "Debit", "Credit", "Balance",
                "IMPORTANT NOTES", "IMPORTANT ANNOUNCEMENTS",
                "Member of PIDM", "Total Count"
            ]):
                continue

            # --------------------------------------------------
            # Detect date (new transaction)
            # --------------------------------------------------
            dm = date_re.match(line)
            if dm:
                # Flush previous transaction
                if current:
                    transactions.append(current)
                    prev_balance = current.get("balance", prev_balance)

                day, mon = dm.group(1), dm.group(2)

                try:
                    tx_date = datetime.datetime.strptime(
                        f"{day}{mon}{year}", "%d%b%Y"
                    ).date().isoformat()
                except Exception:
                    tx_date = f"{day} {mon} {year}"

                # --------------------------------------------------
                # B/F BALANCE → opening balance only
                # --------------------------------------------------
                if "B/F BALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in amount_re.findall(line)]
                    if amts:
                        prev_balance = amts[-1]
                    current = None
                    pending_desc = []
                    continue

                # --------------------------------------------------
                # C/F BALANCE → closing balance only
                # --------------------------------------------------
                if "C/F BALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in amount_re.findall(line)]
                    if amts:
                        prev_balance = amts[-1]
                    current = None
                    pending_desc = []
                    continue

                # --------------------------------------------------
                # Extract amounts
                # --------------------------------------------------
                amts = [float(a.replace(",", "")) for a in amount_re.findall(line)]

                debit = credit = 0.0
                balance = None

                if len(amts) == 3:
                    debit, credit, balance = amts
                elif len(amts) == 2:
                    amt, balance = amts
                    if prev_balance is not None:
                        if abs(prev_balance + amt - balance) < 0.02:
                            credit = amt
                        elif abs(prev_balance - amt - balance) < 0.02:
                            debit = amt
                        else:
                            debit = amt
                    else:
                        debit = amt
                elif len(amts) == 1:
                    balance = amts[0]

                # --------------------------------------------------
                # Build description
                # --------------------------------------------------
                desc = line
                for a in amount_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "").replace(mon, "").strip()

                if pending_desc:
                    desc = " ".join(pending_desc) + " " + desc
                    pending_desc = []

                current = {
                    "date": tx_date,
                    "description": " ".join(desc.split()),
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2) if balance is not None else None,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                }

            # --------------------------------------------------
            # Non-date lines
            # --------------------------------------------------
            else:
                # Ignore SC DR fee rows (0.50)
                if "SC DR" in line and amount_re.search(line):
                    continue

                if current:
                    current["description"] = " ".join(
                        (current["description"] + " " + line).split()
                    )
                else:
                    pending_desc.append(line)

        # Flush at end of page
        if current:
            transactions.append(current)
            prev_balance = current.get("balance", prev_balance)
            current = None

    return transactions
