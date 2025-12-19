import re
from datetime import datetime

# =====================
# Helpers (shared)
# =====================

def extract_year_from_pdf(pdf):
    ...

# =====================
# Main entry point
# =====================

def parse_transactions_rhb(pdf, source_filename=""):
    first_page_text = pdf.pages[0].extract_text() or ""

    if "REFLEX" in first_page_text.upper():
        # FORMAT 1
        ...
        return transactions

    # FORMAT 2 (Ordinary Current Account)
    ...
    return transactions



# =========================================================================
# OPTION 1: REFLEX FORMAT (e.g., Clear Water Services)
# =========================================================================


def _parse_rhb_reflex(pdf, source_filename):
    import re
    from datetime import datetime

    MONEY = re.compile(r'[0-9,]+\.\d{2}')
    DATE = re.compile(r'^\d{2}-\d{2}-\d{4}')

    tx = []
    prev_balance = None

    for page_num, page in enumerate(pdf.pages, 1):
        words = page.extract_words()
        lines = {}
        for w in words:
            y = round(w["top"], 1)
            lines.setdefault(y, []).append(w)

        for y in sorted(lines):
            line = sorted(lines[y], key=lambda w: w["x0"])
            if not line or not DATE.match(line[0]["text"]):
                continue

            text = " ".join(w["text"] for w in line)
            nums = MONEY.findall(text)
            if not nums:
                continue

            balance = float(nums[-1].replace(",", ""))

            debit = credit = 0.0
            if prev_balance is not None:
                diff = round(balance - prev_balance, 2)
                if diff > 0:
                    credit = diff
                elif diff < 0:
                    debit = abs(diff)

            tx.append({
                "date": datetime.strptime(line[0]["text"], "%d-%m-%Y").strftime("%Y-%m-%d"),
                "description": text,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_num,
                "bank": "RHB Bank (Reflex)",
                "source_file": source_filename
            })


            
            prev_balance = balance

    return tx

    # =========================================================================
    # OPTION 2: CURRENT ACCOUNT FORMAT (e.g., Azlan Boutique)
    # =========================================================================

def _parse_rhb_current_account(pdf, source_filename):
    import re
    from datetime import datetime

    MONTH_MAP = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
    }

    def clean(s):
        return " ".join(s.split())

    year = extract_year_from_pdf(pdf)
    tx = []
    prev_balance = None
    current_tx = None

    DATE_START = re.compile(r'^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', re.I)
    MONEY = re.compile(r'[0-9,]+\.\d{2}')
    SKIP = re.compile(r'B/F BALANCE|C/F BALANCE|TOTAL COUNT', re.I)

    for page_num, page in enumerate(pdf.pages, 1):
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            if not line:
                continue

            # ---------- new transaction ----------
            if DATE_START.match(line):
                if SKIP.search(line):
                    current_tx = None
                    continue

                nums = MONEY.findall(line)
                if len(nums) < 2:
                    continue

                amount = float(nums[-2].replace(",", ""))
                balance = float(nums[-1].replace(",", ""))

                day, mon = DATE_START.match(line).groups()
                desc = line[DATE_START.match(line).end():]
                desc = re.sub(r'\d{4,20}', '', desc)
                desc = re.sub(MONEY, '', desc)

                debit = credit = 0.0
                if prev_balance is None:
                    credit = amount if "CR" in desc.upper() else 0.0
                    debit = 0.0 if credit else amount
                else:
                    diff = round(balance - prev_balance, 2)
                    debit = abs(diff) if diff < 0 else 0.0
                    credit = diff if diff > 0 else 0.0

                current_tx = {
                    "date": f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}",
                    "description": clean(desc),
                    "debit": debit,
                    "credit": credit,
                    "balance": balance,
                    "page": page_num,
                    "bank": "RHB Bank (Current)",
                    "source_file": source_filename
                }

                tx.append(current_tx)
                prev_balance = balance
                continue

            # ---------- continuation ----------
            if current_tx:
                current_tx["description"] += " " + line

    for t in tx:
        t["description"] = clean(t["description"])

    return tx
