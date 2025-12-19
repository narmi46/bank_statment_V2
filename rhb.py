import re
import fitz
from datetime import datetime


def parse_transactions_rhb(pdf_input, source_filename):
    """
    Unified RHB Bank + RHB Islamic PDF parser
    - Streamlit-safe
    - Auto year detection
    - Uses B/F balance only as opening
    - Balance-delta debit/credit
    - Supports both Ordinary & Islamic formats
    """

    # ---------------- OPEN PDF ----------------
    def open_doc(inp):
        if hasattr(inp, "stream"):  # Streamlit upload
            inp.stream.seek(0)
            return fitz.open(stream=inp.stream.read(), filetype="pdf")
        return fitz.open(inp)

    doc = open_doc(pdf_input)

    # ---------------- REGEX ----------------
    DATE_ISO_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    DATE_TXN_RE = re.compile(r"(\d{2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")
    HEADER_YEAR_RE = re.compile(r"\d{1,2}\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*(\d{2})")

    # ---------------- HELPERS ----------------
    def parse_money(t: str) -> float:
        try:
            return float(t.replace(",", ""))
        except Exception:
            return 0.0

    # ==========================================================
    # STEP 1: AUTO-DETECT YEAR FROM PAGE 1
    # ==========================================================
    first_page_text = doc[0].get_text()
    year_match = HEADER_YEAR_RE.search(first_page_text)

    if not year_match:
        raise ValueError("Unable to detect year from PDF header")

    year = int("20" + year_match.group(2))

    # ==========================================================
    # STEP 2: TRANSACTION PARSER
    # ==========================================================
    transactions = []
    previous_balance = None

    for page_index, page in enumerate(doc):
        words = page.get_text("words")

        rows = [{
            "x": w[0],
            "y": round(w[1], 1),
            "text": w[4].strip()
        } for w in words if w[4].strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))
        used_y = set()

        for r in rows:
            # --------- DATE DETECTION ---------
            date_match = DATE_TXN_RE.search(r["text"])
            if not date_match:
                continue

            y_key = r["y"]
            if y_key in used_y:
                continue

            day, month = date_match.groups()
            date_iso = datetime.strptime(
                f"{day} {month} {year}",
                "%d %b %Y"
            ).strftime("%Y-%m-%d")

            # --------- COLLECT LINE ---------
            line = [w for w in rows if abs(w["y"] - y_key) <= 1.5]
            line.sort(key=lambda w: w["x"])

            description = []
            money_vals = []

            for w in line:
                t = w["text"]

                if DATE_TXN_RE.search(t):
                    continue
                if MONEY_RE.fullmatch(t):
                    money_vals.append(w)
                elif not t.isdigit():
                    description.append(t)

            if not money_vals:
                continue

            # Rightmost money = balance
            balance = parse_money(max(money_vals, key=lambda m: m["x"])["text"])

            # --------- B/F & C/F HANDLING ---------
            desc_joined = " ".join(description).upper()

            if "B/F" in desc_joined:
                previous_balance = balance
                used_y.add(y_key)
                continue

            if "C/F" in desc_joined or "(RM)" in desc_joined or "TOTAL" in desc_joined:
                used_y.add(y_key)
                continue

            # --------- DEBIT / CREDIT ---------
            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": date_iso,
                "description": " ".join(description)[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Bank",
                "source_file": source_filename
            })

            previous_balance = balance
            used_y.add(y_key)

    doc.close()
    return transactions
