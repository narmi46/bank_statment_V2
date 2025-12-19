import re
import fitz
from datetime import datetime

def open_pdf(inp):
    if hasattr(inp, "stream"):  # Streamlit upload
        inp.stream.seek(0)
        return fitz.open(stream=inp.stream.read(), filetype="pdf")
    return fitz.open(inp)


def parse_money(t):
    try:
        return float(t.replace(",", ""))
    except Exception:
        return 0.0

#Parser 1: RHB REFLEX (YOUR WORKING LOGIC)

def parse_rhb_reflex(doc, source_filename):
    transactions = []
    previous_balance = None

    DATE_RE = re.compile(r"\d{2}-\d{2}-\d{4}")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

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
            if not DATE_RE.fullmatch(r["text"]):
                continue

            y = r["y"]
            if y in used_y:
                continue

            date_iso = datetime.strptime(r["text"], "%d-%m-%Y").strftime("%Y-%m-%d")

            line = [w for w in rows if abs(w["y"] - y) <= 1.5]
            line.sort(key=lambda w: w["x"])

            desc, money_vals = [], []

            for w in line:
                if w["text"] == r["text"]:
                    continue
                if MONEY_RE.fullmatch(w["text"]):
                    money_vals.append(w)
                else:
                    desc.append(w["text"])

            if not money_vals:
                continue

            balance = parse_money(money_vals[-1]["text"])

            debit = credit = 0.0
            if previous_balance is not None:
                delta = balance - previous_balance
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            transactions.append({
                "date": date_iso,
                "description": " ".join(desc)[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Reflex",
                "source_file": source_filename
            })

            previous_balance = balance
            used_y.add(y)

    return transactions

#Parser 2: RHB CONVENTIONAL

def parse_rhb_conventional(doc, source_filename):
    transactions = []
    previous_balance = None

    DATE_RE = re.compile(r"(\d{2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")
    YEAR_RE = re.compile(r"\d{1,2}\s+\w+\s+(\d{2})")

    header_text = doc[0].get_text()
    y = YEAR_RE.search(header_text)
    if not y:
        return []

    year = int("20" + y.group(1))

    for page_index, page in enumerate(doc):
        lines = page.get_text().split("\n")

        for line in lines:
            if not MONEY_RE.search(line):
                continue

            if "B/F" in line:
                previous_balance = parse_money(MONEY_RE.findall(line)[-1])
                continue

            if "C/F" in line or "(RM)" in line or "Total" in line:
                continue

            dm = DATE_RE.search(line)
            if not dm:
                continue

            day, mon = dm.groups()
            date_iso = datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").strftime("%Y-%m-%d")

            balance = parse_money(MONEY_RE.findall(line)[-1])

            if previous_balance is None:
                previous_balance = balance
                continue

            delta = balance - previous_balance
            debit = abs(delta) if delta < 0 else 0
            credit = delta if delta > 0 else 0

            desc = re.sub(MONEY_RE, "", line)
            desc = re.sub(DATE_RE, "", desc).strip()

            transactions.append({
                "date": date_iso,
                "description": desc[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Conventional",
                "source_file": source_filename
            })

            previous_balance = balance

    return transactions

#Parser 3: RHB ISLAMIC

def parse_rhb_islamic(doc, source_filename):
    transactions = []
    previous_balance = None

    DATE_RE = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")
    YEAR_RE = re.compile(r"\d{1,2}\s+Jan\s+(\d{2})")

    header_text = doc[0].get_text()
    y = YEAR_RE.search(header_text)
    if not y:
        return []

    year = int("20" + y.group(1))

    for page_index, page in enumerate(doc):
        lines = page.get_text().split("\n")

        for line in lines:
            if not MONEY_RE.search(line):
                continue

            if "B/F" in line:
                previous_balance = parse_money(MONEY_RE.findall(line)[-1])
                continue

            if "C/F" in line or "(RM)" in line or "Total" in line:
                continue

            dm = DATE_RE.search(line)
            if not dm:
                continue

            day, mon = dm.groups()
            date_iso = datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").strftime("%Y-%m-%d")

            balance = parse_money(MONEY_RE.findall(line)[-1])

            if previous_balance is None:
                previous_balance = balance
                continue

            delta = balance - previous_balance
            debit = abs(delta) if delta < 0 else 0
            credit = delta if delta > 0 else 0

            desc = re.sub(MONEY_RE, "", line)
            desc = re.sub(DATE_RE, "", desc).strip()

            transactions.append({
                "date": date_iso,
                "description": desc[:200],
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "page": page_index + 1,
                "bank": "RHB Islamic",
                "source_file": source_filename
            })

            previous_balance = balance

    return transactions

#Dispatcher (THIS IS THE KEY)

def parse_transactions_rhb(pdf_input, source_filename):
    doc = open_pdf(pdf_input)

    for parser in (
        parse_rhb_reflex,
        parse_rhb_islamic,
        parse_rhb_conventional,
    ):
        try:
            txns = parser(doc, source_filename)
            if txns:
                doc.close()
                return txns
        except Exception:
            continue

    doc.close()
    return []
