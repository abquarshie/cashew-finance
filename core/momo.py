"""Read a mobile money text message (MTN MoMo, Telecel Cash, AT Money) into entry details.

Networks word their messages differently and change them now and then, so this
looks for the parts every message has (an amount in GHS, a fee, a balance, who
the money went to or came from, a transaction ID) rather than matching one exact
template. Anything it can't find is simply left for the person to fill in.
"""
import re
from datetime import date, datetime

MONEY = re.compile(r"(?:GHS|GH₵|GH¢|GHC|¢)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)

# words in a message that suggest a category, matched against the family's own category names
CATEGORY_HINTS = [
    (r"\bairtime\b|\bcredit\b", ["Telephone calls credit"]),
    (r"\bdata\b|\bbundle\b|internet", ["Internet Data"]),
    (r"\becg\b|prepaid|electric|\bnedco\b", ["Electricity"]),
    (r"\bgwcl\b|ghana water", ["Water for washing and bathing"]),
    (r"\bgas\b|\blpg\b", ["Gas"]),
    (r"pharma|chemist|hospital|clinic", ["Medications", "Hospital bills"]),
    (r"uber|bolt|yango|trotro|taxi", ["Transportation › Other", "Other"]),
]
MOMO_ACCOUNT = re.compile(r"momo|mobile money|\bmtn\b|telecel|vodafone|airtel|\bat money\b", re.I)


def _num(text):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _date(text):
    for pattern, fmt in ((r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
                         (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", "%d/%m/%Y"),
                         (r"\b(\d{1,2}-[A-Za-z]{3}-\d{4})\b", "%d-%b-%Y"),
                         (r"\b(\d{1,2}-[A-Za-z]{3}-\d{2})\b", "%d-%b-%y")):
        m = re.search(pattern, text)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                continue
    return None


INITIALISMS = {"ECG", "NHIS", "UBA", "ABSA", "SIC", "GOIL", "ATM", "GRA", "VRA", "STC", "UPSA", "KNUST", "UG", "AT"}


def _initialism(word):
    w = word.strip(".,")
    return w in INITIALISMS or (2 <= len(w) <= 5 and w.isalpha() and not any(v in w for v in "AEIOU"))


def _party(text, amount_end):
    """Who the money went to or came from: the words after 'to'/'from' following the amount."""
    m = re.search(r"\b(?:to|from)\s+(.+?)(?=\s*(?:\.\s|,|\bcurrent\b|\bon\b|\bhas\b|\bat\b|\bwith\b|\breference\b|"
                  r"\bfee\b|\byour\b|\bnew balance\b|\.?$))", text[amount_end:], re.I)
    if not m:
        return ""
    name = m.group(1).strip(" .:-")
    name = re.sub(r"^\+?\d[\d\s]{8,}\s*", "", name)          # drop a leading phone number
    name = re.sub(r"\s+", " ", name).strip()
    if not name or name.isdigit():
        return ""
    if not name.isupper():
        return name
    # KOFI MENSAH -> Kofi Mensah and AMA -> Ama, but initialisms like ECG, MTN or GCB stay as they are
    return " ".join(w if _initialism(w) else w.title() for w in name.split())


def parse(text):
    """Returns a dict of what was found, or None if this doesn't look like a money message."""
    if not text or not text.strip():
        return None
    t = " ".join(text.split())
    low = t.lower()

    amount = fee = balance = None
    amount_end = 0
    prev_end = 0
    for m in MONEY.finditer(t):
        before = low[max(prev_end, m.start() - 45):m.start()]
        value = _num(m.group(1))
        prev_end = m.end()
        if value is None:
            continue
        if "levy" in before or re.search(r"\btax\b", before):
            fee = (fee or 0) + value
        elif "fee" in before or "charge" in before:
            fee = (fee or 0) + value
        elif "balance" in before:
            if balance is None:
                balance = value
        elif amount is None:
            amount, amount_end = value, m.end()
    if fee is None:  # some messages give the fee without "GHS", e.g. "TRANSACTION FEE: 0.50"
        m = re.search(r"fee[^0-9]{0,20}([0-9]+\.[0-9]{2})", low)
        if m:
            fee = _num(m.group(1))
    if amount is None:
        return None

    if re.search(r"cash ?out|withdrawal|withdrawn", low):
        kind, direction = "Transfer", "cash_out"
    elif re.search(r"cash ?in\b|deposit", low):
        kind, direction = "Transfer", "cash_in"
    elif re.search(r"\breceived\b|\bcredited\b|you have received", low):
        kind, direction = "Income", "in"
    else:
        kind, direction = "Expense", "out"

    ref = None
    m = re.search(r"reference:?\s*(.+?)(?=\s*(?:\.\s|\.?$|\btransaction\b|\bfinancial\b|\bfee\b))", t, re.I)
    if m and m.group(1).strip(" .").lower() not in ("", "n/a", "na", "-", "none"):
        ref = m.group(1).strip(" .")
    txn = None
    m = re.search(r"(?:financial\s+)?trans(?:action)?\.?\s*id:?\s*([A-Za-z0-9][A-Za-z0-9.]{3,})", t, re.I) \
        or re.search(r"^\s*(\d{6,})\s+confirmed", t, re.I)
    if m:
        txn = m.group(1).rstrip(".")

    hints = []
    for pattern, names in CATEGORY_HINTS:
        if re.search(pattern, low):
            hints.extend(names)

    party = _party(t, amount_end)
    return {
        "kind": kind, "direction": direction, "amount": amount, "fee": fee or 0.0, "balance": balance,
        "party": party, "reference": ref, "txn_id": txn, "date": _date(t), "category_hints": hints,
    }


def describe(found):
    """One line saying what was read, for the person to check."""
    what = {"out": "Paid", "in": "Received", "cash_out": "Cash out", "cash_in": "Cash in"}[found["direction"]]
    head = f"{what} GH₵{found['amount']:,.2f}"
    if found["party"]:
        head += (" from " if found["direction"] in ("in", "cash_in") else " to ") + found["party"]
    parts = [head]
    if found["fee"]:
        parts.append(f"fee GH₵{found['fee']:,.2f}")
    if found["date"] and found["date"] != date.today():
        parts.append(f"on {found['date']:%d %b %Y}")
    return ", ".join(parts)


def momo_account(account_names):
    for name in account_names:
        if MOMO_ACCOUNT.search(name):
            return name
    return None
