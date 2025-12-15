"""
Maybank / Maybank Islamic Bank Statement Parser
Correctly extracts:
- Date
- First-line description
- Debit
- Credit
- Balance

Key fixes:
- Handles fee rows like ".30-" correctly
- Uses balance delta fallback
- Prevents missing or zeroed debits
"""

import re
from datetime import datetime


def parse_transactions_maybank(pdf, source_filename):
    transactions = []

    opening_balance = None
    previous_balance = None
    statement_year = None
    bank_name = "Maybank"

    for page_num, page in enumerate(pdf.pages, start=1):
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')

        # -------------------------------
        # Detect bank name
        # -------------------------------
        if page_num == 1:
            for line in lines[:10]:
                if 'MAYBANK ISLAMIC' in line.upper():
                    bank_name = "Maybank Islamic"
                    break
                elif 'MAYBANK' in line.upper():
                    bank_name = "Maybank"
                    break

        # -------------------------------
        # Detect statement year
        # -------------------------------
        if page_num == 1 and statement_year is None:
            for line in lines[:30]:
                match = re.search(r'20\d{2}', line)
                if match:
                    statement_year = match.group(0)
                    break
        if not statement_year:
            statement_year = "2025"

        # -------------------------------
        # Extract opening balance
        # -------------------------------
        if page_num == 1 and opening_balance is None:
            for line in lines:
                if 'BEGINNING BALANCE' in line.upper() or 'OPENING BALANCE' in line.upper():
                    match = re.search(r'([\d,]+\.\d{2})', line)
                    if match:
                        opening_balance = float(match.group(1).replace(',', ''))
                        previous_balance = opening_balance

                        transactions.append({
                            'date': '',
                            'description': 'BEGINNING BALANCE',
                            'debit': 0.00,
                            'credit': 0.00,
                            'balance': round(opening_balance, 2),
                            'page': page_num,
                            'bank': bank_name,
                            'source_file': source_filename
                        })
                    break

        # -------------------------------
        # Parse transactions
        # -------------------------------
        for line in lines:
            line = line.strip()
            if not line or not re.match(r'^\d{2}/\d{2}', line):
                continue

            match = re.match(r'^(\d{2}/\d{2})\s+(.*)', line)
            if not match:
                continue

            date_str, rest = match.groups()

            # Extract monetary values
            numbers = re.findall(r'([\d,]+\.\d{2})([+-]?)', rest)
            if not numbers:
                continue

            # Last number is ALWAYS balance
            balance = float(numbers[-1][0].replace(',', ''))

            debit = 0.0
            credit = 0.0

            # ----------------------------------
            # Case 1: Signed transaction amount
            # ----------------------------------
            if len(numbers) >= 2 and numbers[-2][1] in ['+', '-']:
                amount = float(numbers[-2][0].replace(',', ''))
                if numbers[-2][1] == '+':
                    credit = amount
                else:
                    debit = amount

            # ----------------------------------
            # Case 2: Balance delta fallback (FIX)
            # ----------------------------------
            elif previous_balance is not None:
                delta = round(balance - previous_balance, 2)
                if delta > 0:
                    credit = delta
                elif delta < 0:
                    debit = abs(delta)

            # ----------------------------------
            # Description (first line only)
            # ----------------------------------
            first_amount = numbers[0][0]
            description = rest.split(first_amount)[0].strip()
            description = re.sub(r'\s+', ' ', description)
            description = description[:100] if description else 'TRANSACTION'

            # ----------------------------------
            # Date formatting
            # ----------------------------------
            try:
                full_date = datetime.strptime(
                    f"{date_str}/{statement_year}", "%d/%m/%Y"
                ).strftime("%Y-%m-%d")
            except Exception:
                day, month = date_str.split('/')
                full_date = f"{statement_year}-{month}-{day}"

            transactions.append({
                'date': full_date,
                'description': description,
                'debit': round(debit, 2),
                'credit': round(credit, 2),
                'balance': round(balance, 2),
                'page': page_num,
                'bank': bank_name,
                'source_file': source_filename
            })

            previous_balance = balance

    return transactions
