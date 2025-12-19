import re
import datetime


# ============================================================
# MAIN PARSER — MATCHES app.py SIGNATURE
# ============================================================

def parse_transactions_rhb(pdf, source_file):
    """
    pdf          : pdfplumber.open(...) object (already opened by app.py)
    source_file  : filename string
    """

    transactions = []
    bank_name = "RHB Bank"

    date_re = re.compile(r'^(\d{2})\s*([A-Za-z]{3})\b')
    amount_re = re.compile(r'\d[\d,]*\.\d{2}')

    # ------------------------------------------------------------
    # Detect year from statement header (best effort)
    # ------------------------------------------------------------
    year = datetime.date.today().year
    header_text = pdf.pages[0].extract_text() or ""
    m = re.search(
        r'Statement Period.*?(\d{1,2})\s+[A-Za-z]{3}\s+(\d{2})',
        header_text,
        re.S
    )
    if m:
        year = int("20" + m.group(2))

    pending_desc = []
    current = None

    # ------------------------------------------------------------
    # Parse pages
    # ------------------------------------------------------------
    for page_idx, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        for line in lines:

            # ---- must contain a money amount to matter
            amounts = amount_re.findall(line)
            if not amounts:
                pending_desc.append(line)
                continue

            # ---- must start with a date to start a transaction
            dm = date_re.match(line)
            if not dm:
                if current:
                    current["description"] += " " + line
                continue

            # ---- flush previous transaction
            if current:
                transactions.append(current)

            day, mon = dm.group(1), dm.group(2)
            try:
                tx_date = datetime.datetime.strptime(
                    f"{day}{mon}{year}", "%d%b%Y"
                ).date().isoformat()
            except Exception:
                tx_date = f"{day} {mon} {year}"

            nums = [float(a.replace(",", "")) for a in amounts]

            debit = credit = 0.0
            balance = nums[-1]

            # Simple, stable rules
            if len(nums) == 3:
                debit, credit = nums[0], nums[1]
            elif len(nums) == 2:
                debit = nums[0]  # movement exists → count it

            desc = line
            for a in amounts:
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
                "balance": round(balance, 2),
                "page": page_idx,
                "bank": bank_name,
                "source_file": source_file
            }

        if current:
            transactions.append(current)
            current = None

    return transactions


# ============================================================
# STRICT NORMALIZATION (ONLY REAL TRANSACTIONS)
# ============================================================

def normalize_transactions(transactions):
    return [
        tx for tx in transactions
        if tx.get("debit", 0) != 0 or tx.get("credit", 0) != 0
    ]


# ============================================================
# TOTAL CALCULATION (SOURCE OF TRUTH)
# ============================================================

def calculate_totals(transactions):
    valid_tx = normalize_transactions(transactions)

    total_debit = sum(tx["debit"] for tx in valid_tx)
    total_credit = sum(tx["credit"] for tx in valid_tx)
    net_change = total_credit - total_debit

    return {
        "transaction_count": len(valid_tx),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "net_change": round(net_change, 2),
    }
