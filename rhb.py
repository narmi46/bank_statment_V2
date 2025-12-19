import re
import pdfplumber
from datetime import datetime


def parse_money(t: str) -> float:
    try:
        return float(t.replace(",", ""))
    except Exception:
        return 0.0


def extract_year_from_header(pdf):
    header = pdf.pages[0].extract_text()

    # Matches: 1Jan25, 1 Jan 25, 1Apr24
    m = re.search(r"\d{1,2}\s*[A-Za-z]{3}\s*(\d{2})", header)
    if not m:
        return None

    return int("20" + m.group(1))


#Parser 1: RHB REFLEX (YOUR WORKING LOGIC)

def parse_rhb_reflex(pdf, source_filename):
    transactions = []
    previous_balance = None

    DATE_RE = re.compile(r"\d{2}-\d{2}-\d{4}")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

    for page_index, page in enumerate(pdf.pages):
        words = page.extract_words(use_text_flow=True)

        rows = [{
            "x": w["x0"],
            "y": round(w["top"], 1),
            "text": w["text"].strip()
        } for w in words if w["text"].strip()]

        rows.sort(key=lambda r: (r["y"], r["x"]))
        used_y = set()

        for r in rows:
            if not DATE_RE.fullmatch(r["text"]):
                continue

            y = r["y"]
            if y in used_y:
                continue

            date_iso = datetime.strptime(
                r["text"], "%d-%m-%Y"
            ).strftime("%Y-%m-%d")

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
                "bank": "RHB Reflex",
                "source_file": source_filename,
                "page": page_index + 1
            })

            previous_balance = balance
            used_y.add(y)

    return transactions


#Parser 2: RHB CONVENTIONAL

def parse_rhb_conventional(pdf, source_filename):
    transactions = []
    previous_balance = None

    year = extract_year_from_header(pdf)
    if not year:
        return []

    DATE_RE = re.compile(r"(\d{2})\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

    for page_index, page in enumerate(pdf.pages):
        lines = page.extract_text().split("\n")

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
            date_iso = datetime.strptime(
                f"{day} {mon} {year}", "%d %b %Y"
            ).strftime("%Y-%m-%d")

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
                "bank": "RHB Conventional",
                "source_file": source_filename,
                "page": page_index + 1
            })

            previous_balance = balance

    return transactions

#Parser 3: RHB ISLAMIC

def parse_rhb_islamic(pdf, source_filename):
    transactions = []
    previous_balance = None

    year = extract_year_from_header(pdf)
    if not year:
        return []

    DATE_RE = re.compile(r"(\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)")
    MONEY_RE = re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}")

    for page_index, page in enumerate(pdf.pages):
        lines = page.extract_text().split("\n")

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
            date_iso = datetime.strptime(
                f"{day} {mon} {year}", "%d %b %Y"
            ).strftime("%Y-%m-%d")

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
                "bank": "RHB Islamic",
                "source_file": source_filename,
                "page": page_index + 1
            })

            previous_balance = balance

    return transactions

#Dispatcher (THIS IS THE KEY)

def parse_transactions_rhb(pdf_input, source_filename):
    import pdfplumber

    # ✅ ALWAYS convert UploadedFile → pdfplumber.PDF HERE
    if hasattr(pdf_input, "read"):
        pdf = pdfplumber.open(pdf_input)
    else:
        pdf = pdfplumber.open(pdf_input)

    for parser in (
        parse_rhb_reflex,
        parse_rhb_islamic,
        parse_rhb_conventional,
    ):
        try:
            txns = parser(pdf, source_filename)  # ✅ pdf, not pdf_input
            if txns:
                pdf.close()
                return txns
        except Exception as e:
            # TEMP DEBUG (keep during testing)
            print(f"{parser.__name__} failed:", e)
            continue

    pdf.close()
    return []
