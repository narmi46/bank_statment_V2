import re
from datetime import datetime

# ---------------------------------------------------
# Bank Islam Parser (FIXED: recovery from description)
# ---------------------------------------------------
def parse_bank_islam(pdf, source_file):
    transactions = []

    def extract_amount_anywhere(text):
        if not text:
            return None
        s = re.sub(r"\s+", "", str(text))
        m = re.search(r"(-?[\d,]+\.\d{2})", s)
        return float(m.group(1).replace(",", "")) if m else None

    for page_num, page in enumerate(pdf.pages, start=1):
        table = page.extract_table()
        if not table:
            continue

        for row in table:

            row = list(row) if row else []
            while len(row) < 12:
                row.append(None)

            (
                no,
                txn_date,
                customer_eft,
                txn_code,
                description,
                ref_no,
                branch,
                debit_raw,
                credit_raw,
                balance_raw,
                sender_recipient,
                payment_details,
            ) = row[:12]

            # ---------------------------------------------
            # Must contain a valid transaction date
            # ---------------------------------------------
            if not txn_date or not re.search(r"\d{2}/\d{2}/\d{4}", str(txn_date)):
                continue

            try:
                date_str = re.search(r"\d{2}/\d{2}/\d{4}", txn_date).group()
                parsed_date = datetime.strptime(date_str, "%d/%m/%Y").date().isoformat()
            except Exception:
                continue

            # ---------------------------------------------
            # Extract amounts from columns first
            # ---------------------------------------------
            debit = extract_amount_anywhere(debit_raw) or 0.0
            credit = extract_amount_anywhere(credit_raw) or 0.0
            balance = extract_amount_anywhere(balance_raw) or 0.0

            # ---------------------------------------------
            # 🔥 RECOVERY LOGIC (KEY FIX)
            # ---------------------------------------------
            if debit == 0.0 and credit == 0.0:
                recovered_amount = extract_amount_anywhere(description)
                if recovered_amount:
                    desc_upper = str(description).upper()

                    if any(k in desc_upper for k in ["INW", "CR", "CREDIT"]):
                        credit = recovered_amount
                    elif any(k in desc_upper for k in ["DR", "DEBIT", "REVERSE"]):
                        debit = recovered_amount

            # ---------------------------------------------
            # Clean description
            # ---------------------------------------------
            desc_parts = [
                str(no) if no else "",
                str(txn_code) if txn_code else "",
                str(description) if description else "",
                str(sender_recipient) if sender_recipient else "",
                str(payment_details) if payment_details else "",
            ]

            description_clean = " ".join(
                p.replace("\n", " ").strip()
                for p in desc_parts
                if p and p.lower() != "nan"
            )

            # ---------------------------------------------
            # Append transaction
            # ---------------------------------------------
            transactions.append({
                "date": parsed_date,
                "description": description_clean,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_num,
                "bank": "Bank Islam",
                "source_file": source_file,
            })

    return transactions

    # =========================================================
    # BANK ISLAM – FORMAT 2 (TEXT / STATEMENT-BASED)
    # 100% BALANCE DELTA DR/CR LOGIC
    # =========================================================
    
    import re
    from datetime import datetime
    
    # Money must be currency-looking
    MONEY_RE = re.compile(r"\(?-?[\d,]+\.\d{2}\)?")
    
    # Date can be 1–2 digit day/month
    DATE_AT_START_RE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\b")
    
    BAL_BF_RE = re.compile(r"BAL\s+B/F", re.IGNORECASE)
    
    
    def _to_float(val):
        if not val:
            return None
        neg = val.startswith("(") and val.endswith(")")
        val = val.strip("()").replace(",", "")
        try:
            num = float(val)
            return -num if neg else num
        except ValueError:
            return None
    
    
    def _parse_date(d):
        for fmt in ("%d/%m/%y", "%d/%m/%Y"):
            try:
                return datetime.strptime(d.strip(), fmt).date().isoformat()
            except ValueError:
                pass
        return None
    
    
    def parse_bank_islam_format2(pdf, source_file):
        transactions = []
    
        opening_balance = None
        prev_balance = None
    
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines() if l.strip()]
    
            for line in lines:
                upper = line.upper()
    
                # -------------------------------------------------
                # 1️⃣ OPENING BALANCE (BAL B/F)
                # -------------------------------------------------
                if BAL_BF_RE.search(upper):
                    money = MONEY_RE.findall(line)
                    if money:
                        opening_balance = _to_float(money[-1])
                        prev_balance = opening_balance
                    continue
    
                # -------------------------------------------------
                # 2️⃣ TRANSACTION LINES (must start with date)
                # -------------------------------------------------
                m_date = DATE_AT_START_RE.match(line)
                if not m_date or prev_balance is None:
                    continue
    
                date = _parse_date(m_date.group(1))
                if not date:
                    continue
    
                money_raw = MONEY_RE.findall(line)
                money_vals = [_to_float(x) for x in money_raw if _to_float(x) is not None]
    
                # Must have at least a balance
                if not money_vals:
                    continue
    
                # Last number is always the balance
                balance = money_vals[-1]
    
                # -------------------------------------------------
                # 3️⃣ BALANCE DELTA LOGIC (THE CORE)
                # -------------------------------------------------
                delta = round(balance - prev_balance, 2)
    
                if delta > 0:
                    credit = delta
                    debit = 0.0
                else:
                    debit = abs(delta)
                    credit = 0.0
    
                prev_balance = balance
    
                # -------------------------------------------------
                # 4️⃣ DESCRIPTION (cleaned, multiline-safe)
                # -------------------------------------------------
                desc = line[len(m_date.group(1)):].strip()
                for tok in money_raw:
                    desc = desc.replace(tok, "").strip()
    
                transactions.append({
                    "date": date,
                    "description": desc,
                    "debit": round(debit, 2),
                    "credit": round(credit, 2),
                    "balance": round(balance, 2),
                    "page": page_num,
                    "bank": "Bank Islam",
                    "source_file": source_file,
                    "format": "format2_balance_delta"
                })
    
        return transactions


    # =========================================================
    # WRAPPER (USED BY app.py)
    # =========================================================
    def parse_bank_islam(pdf, source_file):
        """
        Try FORMAT 1 first (table).
        If nothing extracted, fallback to FORMAT 2 (text).
        """
        tx = parse_bank_islam_format1(pdf, source_file)
        if tx:
            return tx
        return parse_bank_islam_format2(pdf, source_file)
