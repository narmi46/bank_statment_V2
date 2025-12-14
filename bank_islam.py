# bank_islam.py
# Simple, balance-driven Bank Islam parser (PyMuPDF)

import fitz  # PyMuPDF
import re
from datetime import datetime


def parse_bank_islam(pdf, source_filename=""):
    results = []

    # 🔑 rewind stream (Streamlit-safe)
    pdf.stream.seek(0)
    pdf_bytes = pdf.stream.read()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    previous_balance = None

    for page_index in range(doc.page_count):
        page = doc[page_index]
        words = page.get_text("words")

        # group words by Y (rows)
        rows = {}
        for x0, y0, x1, y1, text, *_ in words:
            y = round(y0, 1)
            rows.setdefault(y, []).append((x0, text))

        for y in sorted(rows):
            row_text = " ".join(t[1] for t in sorted(rows[y], key=lambda x: x[0]))

            # must contain date
            date_match = re.search(r"\d{1,2}/\d{1,2}/\d{2}", row_text)
            if not date_match:
                continue

            # must contain balance (last amount on row)
            amounts = re.findall(r"[\d,]+\.\d{2}", row_text)
            if not amounts:
                continue

            balance = float(amounts[-1].replace(",", ""))

            # clean description: remove date + balance
            description = row_text
            description = description.replace(date_match.group(), "")
            description = description.replace(amounts[-1], "")
            description = " ".join(description.split())

            # determine debit / credit using balance delta
            debit = credit = 0.0
            if previous_balance is not None:
                delta = balance - previous_balance
                if delta > 0:
                    credit = round(delta, 2)
                elif delta < 0:
                    debit = round(abs(delta), 2)

            previous_balance = balance

            results.append({
                "date": datetime.strptime(date_match.group(), "%d/%m/%y").strftime("%Y-%m-%d"),
                "description": description,
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "page": page_index + 1,
                "bank": "Bank Islam",
                "source_file": source_filename
            })

    return results
