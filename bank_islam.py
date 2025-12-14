import re
from datetime import datetime
import fitz

DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})")
AMT_RE = re.compile(r"[\d,]+\.\d{2}")

def parse_bank_islam(pdf, source_filename=""):
    results = []

    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # ✅ 1) Initialize previous_balance using Opening Balance if present
    full_text = "\n".join(doc[i].get_text() for i in range(min(2, doc.page_count)))
    opening_balance = None

    m = re.search(r"Opening Balance\s*\(MYR\)\s*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
    if m:
        opening_balance = float(m.group(1).replace(",", ""))
    else:
        # fallback for other Bank Islam formats: BAL B/F
        m2 = re.search(r"BAL\s+B/F\s*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
        if m2:
            opening_balance = float(m2.group(1).replace(",", ""))

    previous_balance = opening_balance  # <-- THIS fixes first txn debit/credit

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_text = " ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0]))

            # ✅ 2) Support DD/MM/YY and DD/MM/YYYY
            date_match = DATE_RE.search(row_text)
            if not date_match:
                continue

            amounts = AMT_RE.findall(row_text)
            if not amounts:
                continue

            balance = float(amounts[-1].replace(",", ""))

            # description = same line excluding date + balance only
            description = row_text.replace(date_match.group(), "")
            description = description.replace(amounts[-1], "")
            description = " ".join(description.split())

            debit = credit = 0.0
            if previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            previous_balance = balance

            # ✅ parse date with both formats
            raw_date = date_match.group()
            if len(raw_date.split("/")[-1]) == 4:
                iso_date = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%Y-%m-%d")
            else:
                iso_date = datetime.strptime(raw_date, "%d/%m/%y").strftime("%Y-%m-%d")

            results.append({
                "date": iso_date,
                "description": description,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_index + 1,
                "bank": "Bank Islam",
                "source_file": source_filename,
            })

    return results
