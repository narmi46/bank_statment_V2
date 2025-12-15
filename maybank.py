import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# -----------------------------
# Helpers
# -----------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

def _to_float_money(s: str) -> Optional[float]:
    """
    Convert '50,483.76' or '.50' or '0.50' to float.
    Returns None if not parseable.
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None

    # remove commas and spaces
    s = s.replace(",", "").replace(" ", "")

    # handle values like ".50"
    if s.startswith("."):
        s = "0" + s

    # keep only digits and dot (we do sign separately)
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None

    try:
        return float(s)
    except Exception:
        return None


def _extract_statement_year(all_text: str) -> Optional[int]:
    """
    Find statement year from statement date lines like:
      - '结单日期 : 31/01/25'
      - '结单日期 :28/02/2025'
      - 'STATEMENT DATE : 31/01/25'
    """
    # Prefer explicit "STATEMENT DATE" / Chinese "结单日期" vicinity, but fallback to any date with year.
    patterns = [
        r"(?:STATEMENT\s*DATE|结单日期)\s*:?\s*(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})",
        r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})",
        r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2})",
    ]

    for pat in patterns:
        m = re.search(pat, all_text, flags=re.IGNORECASE)
        if m:
            yy = m.group(3)
            year = int(yy)
            if year < 100:
                # assume 20xx for statements
                year += 2000
            if 1990 <= year <= 2100:
                return year
    return None


def _extract_opening_balance(lines: List[str]) -> Optional[float]:
    """
    Supports:
      'BEGINNING BALANCE : 50,483.76'
      'OPENING BALANCE : 12,345.67'
    """
    for ln in lines:
        m = re.search(r"(BEGINNING|OPENING)\s+BALANCE\s*:?\s*([0-9][0-9,]*\.\d{2})", ln, flags=re.IGNORECASE)
        if m:
            return _to_float_money(m.group(2))
    return None


def _parse_date_ddmm(token: str, statement_year: int) -> Optional[str]:
    """
    token like '01/02' => YYYY-MM-DD using statement year.
    """
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", token)
    if not m:
        return None
    d = int(m.group(1))
    mo = int(m.group(2))
    try:
        dt = datetime(statement_year, mo, d)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_date_dd_mon_yyyy(tokens: List[str]) -> Optional[Tuple[str, int]]:
    """
    tokens like ['01','Feb','2025', ...]
    returns (YYYY-MM-DD, index_after_date_tokens)
    """
    if len(tokens) < 3:
        return None
    d, mon, y = tokens[0], tokens[1], tokens[2]
    if not re.fullmatch(r"\d{1,2}", d):
        return None
    if mon.lower()[:3] not in MONTHS:
        return None
    if not re.fullmatch(r"\d{4}", y):
        return None

    day = int(d)
    month = MONTHS[mon.lower()[:3]]
    year = int(y)
    try:
        dt = datetime(year, month, day)
        return (dt.strftime("%Y-%m-%d"), 3)
    except Exception:
        return None


def _last_money_token(tokens: List[str]) -> Optional[float]:
    """
    Find last parseable money token in tokens.
    """
    for t in reversed(tokens):
        # allow commas
        tt = t.strip()
        if re.fullmatch(r"[0-9][0-9,]*\.\d{2}", tt) or re.fullmatch(r"\.[0-9]{1,2}", tt):
            val = _to_float_money(tt)
            if val is not None:
                return val
    return None


# -----------------------------
# Core parser
# -----------------------------

def parse_transactions_maybank(pdf, source_file: str) -> List[Dict]:
    """
    Supports BOTH common Maybank layouts encountered in your files:
      1) Maybank Islamic style: '01 Feb 2025 ... 78.00 - 50,405.76'
      2) DD/MM style: '01/01 ... 1,980.00 51,142.90' (year taken from statement date)

    Output matches what app.py expects: list of dict with date, description (first line only),
    debit, credit, balance, page, bank, source_file.

    Debit/Credit is computed from BALANCE DELTA using OPENING/BIGINNING BALANCE.
    """
    transactions: List[Dict] = []

    # Collect all lines and also per-page lines
    all_lines: List[str] = []
    page_lines: List[List[str]] = []

    for i, page in enumerate(pdf.pages, start=1):
        text = page.extract_text() or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        page_lines.append(lines)
        all_lines.extend(lines)

    all_text = "\n".join(all_lines)

    statement_year = _extract_statement_year(all_text)
    if statement_year is None:
        raise ValueError("Statement year not found (cannot resolve DD/MM transaction dates).")

    opening_balance = _extract_opening_balance(all_lines)
    if opening_balance is None:
        raise ValueError("Opening/Beginning balance not found.")

    # Patterns:
    #  A) Islamic line begins with "DD Mon YYYY"
    #  B) DD/MM line begins with "DD/MM"
    for page_idx, lines in enumerate(page_lines, start=1):
        for ln in lines:
            # skip ending balance line
            if re.search(r"ENDING\s+BALANCE", ln, flags=re.IGNORECASE):
                continue
            # skip opening/beginning balance line
            if re.search(r"(BEGINNING|OPENING)\s+BALANCE", ln, flags=re.IGNORECASE):
                continue

            # quick tokenize
            tokens = ln.split()

            # A) DD Mon YYYY ...
            date_a = _parse_date_dd_mon_yyyy(tokens)
            if date_a:
                date_str, start_idx = date_a

                # Expect last numeric token as balance
                bal = _last_money_token(tokens)
                if bal is None:
                    continue

                # Description = tokens between date and the trailing amount/balance stuff
                # In Islamic format you often have "... <amount> <sign> <balance>"
                # We'll remove last 1-3 tokens if they look like [amount] [sign] [balance] or [sign] [balance]
                desc_tokens = tokens[start_idx:]

                # remove trailing balance token
                # (find last occurrence of the balance string form is hard; just drop from end by pattern)
                # If last token is a money, pop it
                if desc_tokens and re.fullmatch(r"[0-9][0-9,]*\.\d{2}", desc_tokens[-1]):
                    desc_tokens = desc_tokens[:-1]

                # If there is a trailing sign token ('+' or '-'), drop it
                if desc_tokens and desc_tokens[-1] in {"+", "-"}:
                    desc_tokens = desc_tokens[:-1]

                # If there is a trailing amount token, drop it too (we compute debit/credit from balance delta anyway)
                if desc_tokens and (re.fullmatch(r"[0-9][0-9,]*\.\d{2}", desc_tokens[-1]) or re.fullmatch(r"\.[0-9]{1,2}", desc_tokens[-1])):
                    desc_tokens = desc_tokens[:-1]

                description = " ".join(desc_tokens).strip()
                if not description:
                    # fallback: keep entire line minus date
                    description = " ".join(tokens[start_idx:]).strip()

                transactions.append({
                    "date": date_str,
                    "description": description,  # FIRST LINE ONLY
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": bal,
                    "page": page_idx,
                    "bank": "Maybank",
                    "source_file": source_file,
                })
                continue

            # B) DD/MM ...
            if tokens and re.fullmatch(r"\d{1,2}/\d{1,2}", tokens[0]):
                date_str = _parse_date_ddmm(tokens[0], statement_year)
                if not date_str:
                    continue

                bal = _last_money_token(tokens)
                if bal is None:
                    continue

                # Remove leading date token
                desc_tokens = tokens[1:]

                # Remove trailing balance token
                if desc_tokens and re.fullmatch(r"[0-9][0-9,]*\.\d{2}", desc_tokens[-1]):
                    desc_tokens = desc_tokens[:-1]

                # Remove trailing amount token with optional +/- attached, like '1,980.00+' or '10.00-'
                # or separate sign token
                if desc_tokens:
                    # separate sign token
                    if desc_tokens[-1] in {"+", "-"}:
                        desc_tokens = desc_tokens[:-1]
                    # amount with sign attached
                    if desc_tokens and re.fullmatch(r"[0-9][0-9,]*\.\d{2}[+-]", desc_tokens[-1]):
                        desc_tokens = desc_tokens[:-1]
                    # plain amount
                    if desc_tokens and re.fullmatch(r"[0-9][0-9,]*\.\d{2}", desc_tokens[-1]):
                        desc_tokens = desc_tokens[:-1]

                description = " ".join(desc_tokens).strip()
                if not description:
                    description = ln

                transactions.append({
                    "date": date_str,
                    "description": description,  # FIRST LINE ONLY
                    "debit": 0.0,
                    "credit": 0.0,
                    "balance": bal,
                    "page": page_idx,
                    "bank": "Maybank",
                    "source_file": source_file,
                })
                continue

            # Otherwise: continuation lines (multi-line description) -> IGNORE (you want first line only)
            # So do nothing.

    # If nothing parsed, raise to show issue quickly
    if not transactions:
        raise ValueError("No Maybank transactions detected (format not recognized).")

    # Compute debit/credit using balance delta from opening balance
    prev_bal = opening_balance
    for tx in transactions:
        bal = tx.get("balance", None)
        if bal is None:
            # can't compute; keep zeros
            continue

        delta = bal - prev_bal
        if delta < 0:
            tx["debit"] = round(-delta, 2)
            tx["credit"] = 0.0
        elif delta > 0:
            tx["debit"] = 0.0
            tx["credit"] = round(delta, 2)
        else:
            tx["debit"] = 0.0
            tx["credit"] = 0.0

        prev_bal = bal

    return transactions
