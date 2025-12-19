import re
import datetime


def parse_transactions_rhb(pdf, source_file):
    transactions = []
    bank_name = "RHB Bank"

    # Match: "07Mar" or "07 Mar"
    date_re = re.compile(r'^(\d{2})\s*([A-Za-z]{3})\b')
    num_re = re.compile(r'\d[\d,]*\.\d{2}')

    # -------------------------------------------------
    # 1️⃣ Detect YEAR from statement header
    # -------------------------------------------------
    year = None
    for page in pdf.pages[:1]:
        text = page.extract_text() or ""
        m = re.search(
            r'(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})\s*[–-]\s*(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})',
            text
        )
        if m:
            year = int("20" + m.group(2))

    if not year:
        year = datetime.date.today().year

    prev_balance = None
    current = None
    pending_desc = []

    # -------------------------------------------------
    # 2️⃣ Main parsing
    # -------------------------------------------------
    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        for line in lines:

            # 🚫 Skip headers / footers / noise
            if any(h in line for h in [
                "ACCOUNT ACTIVITY", "Date", "Tarikh", "Debit", "Credit",
                "Balance", "ORDINARY CURRENT", "QARD CURRENT",
                "Total Count", "IMPORTANT", "Account Statement",
                "Penyata Akaun", "Member of PIDM", "Page No"
            ]):
                continue

            # ------------------------------
            # DATE LINE
            # ------------------------------
            dm = date_re.match(line)
            if dm:

                # 🚫 HARD SKIP opening & closing balance rows
                if "B/F BALANCE" in line or "C/F BALANCE" in line:
                    amts = [float(a.replace(",", "")) for a in num_re.findall(line)]
                    if amts:
                        prev_balance = amts[-1]
                    current = None
                    pending_desc = []
                    continue

                # Flush previous transaction
                if current:
                    transactions.append(current)
                    prev_balance = current.get("balance", prev_balance)

                day, mon = dm.group(1), dm.group(2)
                try:
                    dt = datetime.datetime.strptime(
                        f"{day}{mon}{year}", "%d%b%Y"
                    ).date()
                    date_out = dt.isoformat()
                except Exception:
                    date_out = f"{day} {mon} {year}"

                # Extract amounts
                amts = [float(a.replace(",", "")) for a in num_re.findall(line)]

                debit = credit = 0.0
                balance = None

                if len(amts) == 3:
                    debit, credit, balance = amts
                elif len(amts) == 2:
                    amt, balance = amts
                    if prev_balance is not None:
                        if abs(prev_balance + amt - balance) < 0.02:
                            credit = amt
                        else:
                            debit = amt
                    else:
                        debit = amt

                # Clean description
                desc = line
                for a in num_re.findall(desc):
                    desc = desc.replace(a, "")
                desc = desc.replace(day, "").replace(mon, "").strip()

                if pending_desc:
                    desc = " ".join(pending_desc) + " " + desc
                    pending_desc = []

                current = {
                    "date": date_out,
                    "description": " ".join(desc.split()),
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_idx,
                    "bank": bank_name,
                    "source_file": source_file
                }

            # ------------------------------
            # NON-DATE LINE
            # ------------------------------
            else:
                # Skip fee helper rows like "SC DR 0.50"
                if "SC DR" in line and num_re.search(line):
                    continue

                if current:
                    current["description"] = " ".join(
                        (current["description"] + " " + line).split()
                    )
                else:
                    pending_desc.append(line)

        # Flush last transaction on page
        if current:
            transactions.append(current)
            prev_balance = current.get("balance", prev_balance)
            current = None

    # -------------------------------------------------
    # 3️⃣ Final cleanup (safety net)
    # -------------------------------------------------
    transactions = [
        t for t in transactions
        if t["debit"] > 0 or t["credit"] > 0
    ]

    return transactions
