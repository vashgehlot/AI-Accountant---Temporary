"""Bank, card and payment processor exports read in code (design of 2026-11-23): the heading row and what each column
holds, found by the columns' headings rather than by a list of banks, and every date and amount read exactly as the
file states it. A file that can't be read with certainty is None here, and the model reads it as before."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

from .accounts import BANK_SLOTS

HEADER_ROWS = 15   # the heading row is among a file's first lines: a bank's account details may come before it

# What each column holds, by its heading lowercased with everything but letters and digits dropped; first match wins.
ROLES: dict[str, tuple[str, ...]] = {
    "date": ("date", "transactiondate", "posteddate", "postingdate", "valuedate", "completeddate", "created",
             "createdutc", "createddate"),
    "description": ("description", "details", "narrative", "transactiondescription", "payee", "payeename", "name",
                    "merchant", "counterparty", "counterpartyname", "memo", "reference"),
    "amount": ("amount", "value", "amountgbp", "transactionamount"),
    "paid_in": ("paidin", "moneyin", "credit", "creditamount", "in"),
    "paid_out": ("paidout", "moneyout", "debit", "debitamount", "out"),
    "balance": ("balance", "runningbalance"),
    "type": ("type", "transactiontype"),
    "currency": ("currency",),
    "gross": ("gross",),
    "fee": ("fee", "fees"),
    "net": ("net",),
    "category": ("reportingcategory", "category"),
    "id": ("balancetransactionid", "transactionid", "id"),
    "customer": ("customername", "customer"),
    "sign": ("debitcredit", "creditdebit", "drcr", "crdr", "dc", "cd", "debitorcredit", "indicator"),
}
_SEVERAL = {"description"}   # roles whose columns are all kept, joined in file order

_DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y",
                 "%d-%b-%y", "%d %b %y", "%Y-%m-%d")
_ISO_WITH_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
_AMOUNT = re.compile(r"^[+-]?\d+(\.\d+)?$")
_NOT_A_LINE = re.compile(r"\b(totals?|balance)\b", re.IGNORECASE)
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
_SIGN_WORDS = {"dr": -1, "d": -1, "debit": -1, "cr": 1, "c": 1, "credit": 1}
_CARD_ISSUERS = ("amex", "american express", "barclaycard", "credit card", "creditcard", "capital one", "mbna")


@dataclass(frozen=True)
class Table:
    """A recognised table: the lines above its heading row, the heading row, which columns hold what, and its rows
    (blank rows and totals rows left out)."""
    heading: list[str]
    header: list[str]
    roles: dict[str, list[int]]
    rows: list[list[str]]


def _key(heading: str) -> str:
    """A heading as compared: lowercase letters and digits only, without "GBP" ("Balance (GBP)"). Another currency
    stays in it, so an "Amount (EUR)" column is not taken for pounds."""
    key = re.sub(r"[^a-z0-9]", "", heading.lower())
    return key[:-3] if key.endswith("gbp") and len(key) > 3 else key


def _roles(header: list[str]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for n, cell in enumerate(header):
        key = _key(cell)
        role = next((r for r, names in ROLES.items() if key in names), None)
        if role is None or (role in found and role not in _SEVERAL):
            continue
        found.setdefault(role, []).append(n)
    return found


def _is_header(roles: dict[str, list[int]]) -> bool:
    return "date" in roles and ("amount" in roles or {"paid_in", "paid_out"} <= set(roles)
                                or {"gross", "fee", "net"} <= set(roles))


def parse_date(column: list[str]) -> Optional[list[dt.date]]:
    """The column's dates, read with one format for all of them (UK day first, or ISO with or without a time); None
    when no one format reads them all."""
    values = [(m.group(1) if (m := _ISO_WITH_TIME.match(v.strip())) else v.strip()) for v in column]
    for fmt in _DATE_FORMATS:
        try:
            return [dt.datetime.strptime(v, fmt).date() for v in values]
        except ValueError:
            continue
    return None


def parse_amount(cell: str) -> Optional[Decimal]:
    """An amount as a bank writes it ("£1,234.56", "(12.00)", "12.00 CR", "12.00 DR"), signed; None for a blank cell
    and for anything that isn't an amount."""
    text = re.sub(r"[£\s]|GBP", "", cell.strip(), flags=re.IGNORECASE)
    sign = 1
    if text.upper().endswith(("CR", "DR")):
        sign = -1 if text.upper().endswith("DR") else 1
        text = text[:-2]
    if text.startswith("(") and text.endswith(")"):
        sign, text = -sign, text[1:-1]
    if "," in text:   # only as thousands separators: "12,5" or "1.234,56" may be a decimal comma
        if not _THOUSANDS.match(text):
            return None
        text = text.replace(",", "")
    if not _AMOUNT.match(text):
        return None
    try:
        return sign * Decimal(text)
    except InvalidOperation:
        return None


def _cells(text: str) -> list[list[str]]:
    delimiter = "\t" if "\t" in text else ","
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def parse(text: str) -> Optional[Table]:
    """The table, if its heading row names a date column and an amount (or paid in and paid out, or gross, fee and
    net), and every date and amount under them reads; else None."""
    lines = _cells(text)
    at = next((n for n, row in enumerate(lines[:HEADER_ROWS]) if _is_header(_roles(row))), None)
    if at is None:
        return None
    header, roles = lines[at], _roles(lines[at])
    heading = [" ".join(c for c in row if c) for row in lines[:at] if any(row)]
    width = len(header)
    money = [n for role in ("amount", "paid_in", "paid_out", "balance", "gross", "fee", "net")
             for n in roles.get(role, [])]
    date_at = roles["date"][0]
    rows = []
    for row in lines[at + 1:]:
        if not any(row):
            continue
        row = (row + [""] * width)[:width]
        if any(row[n] and parse_amount(row[n]) is None for n in money):
            return None
        if not row[date_at]:
            if _NOT_A_LINE.search(" ".join(row)):
                continue   # a total or a balance line: not a transaction
            return None
        rows.append(row)
    if rows and parse_date([row[date_at] for row in rows]) is None:
        return None   # no rows is an empty statement (a month with no movement), not an unreadable one
    return Table(heading=heading, header=header, roles=roles, rows=rows)


# ─── Direction and balances ───────────────────────────────────────────────────

_BROUGHT_FORWARD = re.compile(r"brought forward|opening balance|balance b/?f|start balance", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """One payment line of a statement: its amount positive, its direction settled."""
    date: dt.date
    text: str
    amount: Decimal
    direction: Literal["in", "out"]
    balance: Optional[Decimal]
    currency: str
    kind: Optional[str]   # what the type column says (BP, DD, TRF), if the file has one


@dataclass(frozen=True)
class Statement:
    lines: list[Line]
    opening_balance: Optional[Decimal]
    closing_balance: Optional[Decimal]
    heading: str


def account_kind(code: Optional[str]) -> Optional[str]:
    """The kind of the client's bank account or card with this code (current, savings, credit_card, petty_cash)."""
    return next((kind for kind, codes in BANK_SLOTS.items() if code in codes), None)


def _chain(signed: list[Decimal], balances: list[Optional[Decimal]]) -> bool:
    """Whether each line's signed amount takes the last balance shown to its own, oldest line first; with fewer than
    two balances there is nothing to check by."""
    last, checked = None, 0
    for amount, balance in zip(signed, balances):
        if last is not None:
            last += amount
        if balance is not None:
            if last is not None:
                if last != balance:
                    return False
                checked += 1
            last = balance
    return checked > 0


def statement(table: Table, account_kind: Optional[str]) -> Optional[Statement]:
    """The table's payment lines with their direction, and the statement's opening and closing balances; None when
    the direction can't be settled with certainty. Paid in and paid out columns say it. One amount column: positive
    is money in on a bank account and money spent on a card; with a balance column, each line must take the balance
    before it to its own (oldest first, whichever way the file runs), and on a bank account the balance's movement
    settles the sign."""
    roles, rows = table.roles, table.rows
    dates = parse_date([row[roles["date"][0]] for row in rows])
    cell = lambda row, role: row[roles[role][0]] if role in roles else ""   # noqa: E731

    raw: list[Optional[Decimal]] = []
    for row in rows:
        if "amount" in roles:
            raw.append(parse_amount(cell(row, "amount")))
        else:
            paid_in, paid_out = parse_amount(cell(row, "paid_in")), parse_amount(cell(row, "paid_out"))
            raw.append(None if paid_in is None and paid_out is None
                       else (paid_in or Decimal(0)) - abs(paid_out or Decimal(0)))
    balances = [parse_amount(cell(row, "balance")) for row in rows]
    texts = [" ".join(row[n] for n in roles.get("description", []) if row[n]) for row in rows]

    opening = None
    keep = []
    for n, amount in enumerate(raw):
        if not amount:   # a balance brought forward or carried forward, or another line with no money: not a payment
            if _BROUGHT_FORWARD.search(texts[n]) and balances[n] is not None:
                opening = balances[n]
            continue
        keep.append(n)
    if not keep:   # nothing moved: an empty statement, at its brought-forward balance if it shows one
        return Statement(lines=[], opening_balance=opening, closing_balance=opening, heading="\n".join(table.heading))

    # A column saying debit or credit ("Debit/Credit", or a type column of DR and CR) gives the sign outright.
    explicit = "amount" not in roles
    indicator = "sign" if "sign" in roles else "type" if "type" in roles and all(
        cell(rows[n], "type").lower() in _SIGN_WORDS for n in keep) and all(raw[n] > 0 for n in keep) else None
    if indicator:
        words = [cell(rows[n], indicator).lower() for n in keep]
        if not all(w in _SIGN_WORDS for w in words):
            return None
        for n, word in zip(keep, words):
            raw[n] = abs(raw[n]) * _SIGN_WORDS[word]
        explicit = True

    # Oldest line first. When the dates don't say which way the file runs (all on one day), both ways are tried, and
    # the balances must settle it.
    if dates[keep[0]] != dates[keep[-1]]:
        orders = [list(reversed(keep))] if dates[keep[0]] > dates[keep[-1]] else [keep]
    else:
        orders = [keep, list(reversed(keep))]
    has_balances = "balance" in roles and any(balances[n] is not None for n in keep)
    order, holds, against = orders[0], False, False   # against: the balance moves the other way from the amounts
    if has_balances:
        found = []
        for candidate in orders:
            signed, shown_balances = [raw[n] for n in candidate], [balances[n] for n in candidate]
            ok, flipped = _chain(signed, shown_balances), _chain([-a for a in signed], shown_balances)
            if ok or flipped:
                found.append((candidate, ok, flipped and not ok))
        if len(found) > 1:
            return None   # the file could run either way, with different signs: not certain
        if found:
            order, holds, against = found[0]
        elif sum(balances[n] is not None for n in keep) > 1:
            return None   # the balances don't follow the amounts either way
        elif account_kind is None:
            return None
        if against and explicit:
            return None   # the file says the direction: a balance that disagrees is not to be trusted

    card = account_kind == "credit_card" and not explicit
    flip = False
    if card:
        owed = {b > 0 for n in keep if (b := balances[n]) is not None and b != 0}
        if len(owed) > 1:
            return None   # a card balance shown both ways
        if owed and (holds or against):
            # Amex shows what is owed as positive, rising with spending written positive; NatWest-style exports show
            # it negative, falling with spending written negative. Spending is what makes the balance owed grow.
            flip = (owed == {True}) != against
        else:
            positives = sum(raw[n] > 0 for n in keep)
            flip = positives >= len(keep) - positives   # mostly positive: spending written positive, as Amex does
    elif has_balances:
        flip = against   # the balance falls by a positive amount: it is money out
    elif account_kind is None and not explicit:
        return None   # one amount column, no balance, and not known whether it is a bank account or a card

    lines = []
    for n in keep:
        amount = -raw[n] if flip else raw[n]
        currency = (cell(rows[n], "currency") or "GBP").upper()
        lines.append(Line(date=dates[n], text=texts[n], amount=abs(amount), direction="in" if amount > 0 else "out",
                          balance=balances[n], currency=currency, kind=cell(rows[n], "type") or None))
    shown = [n for n in order if balances[n] is not None]
    closing = balances[shown[-1]] if shown else None
    if opening is None and shown:
        first = shown[0]
        opening = balances[first] - (-raw[first] if against else raw[first])
    return Statement(lines=lines, opening_balance=opening, closing_balance=closing,
                     heading="\n".join(table.heading))


# ─── Payment processor exports, in code ───────────────────────────────────────

PROCESSORS = ("Stripe", "PayPal", "Square", "SumUp", "Zettle", "Shopify", "GoCardless")
SALES, FEES, SUSPENSE = "4000", "7901", "9998"
# A line's category, by words its key holds (Stripe's "payout", PayPal's "General Withdrawal", "Express Checkout
# Payment", "Payment Refund"), tried in this order.
_CATEGORIES = (("payout", ("payout", "withdrawal", "transfer")), ("refund", ("refund",)),
               ("fee", ("stripefee", "applicationfee")), ("charge", ("charge", "payment", "sale", "transaction")))


def _category(key: str) -> Optional[str]:
    return next((name for name, words in _CATEGORIES if any(w in key for w in words) or key == "fee"), None)


def names_a_card(file_name: str, heading: list[str]) -> bool:
    """Whether the file's name or the lines above its headings name a card issuer (Amex, Barclaycard): such a file
    on a bank account is left to the model, which reads what it is."""
    text = f"{file_name} {' '.join(heading)}".lower()
    return any(name in text for name in _CARD_ISSUERS)


def _processor_name(file_name: str, heading: list[str]) -> str:
    text = f"{file_name} {' '.join(heading)}".lower()
    return next((name for name in PROCESSORS if name.lower() in text), "Payment processor")


def processor(table: Table, file_name: str):
    """A payment processor's export (gross, fee and net on each line) as rows, with no model: each charge "in" on
    Sales and its fee "out" on Bank Charges, a refund "out" on Sales, each on its own day and sharing the line's id
    and net; a payout is the net paid over, not a row; any other line is on Suspense with a warning. None for a table
    without gross, fee and net."""
    from .extractor import AccountingTransaction, TransactionExtractionResult
    roles = dict(table.roles)
    if "gross" not in roles and "amount" in roles:
        roles["gross"] = roles["amount"]      # Stripe's balance history: Amount, Fee, Net
    if "category" not in roles and "type" in roles:
        roles["category"] = roles["type"]     # PayPal's and Stripe's Type column
    if not {"gross", "fee", "net"} <= set(roles):
        return None
    agent = _processor_name(file_name, table.heading)
    dates = parse_date([row[roles["date"][0]] for row in table.rows])
    cell = lambda row, role: row[roles[role][0]] if role in roles else ""   # noqa: E731
    rows, warnings = [], []
    # The app takes a processor's items of one day as one document (adapter._document_key): what it nets to is the
    # day's nets together, not one line's.
    day_net: dict = {}
    for n, row in enumerate(table.rows):
        if _category(_key(cell(row, "category"))) != "payout":
            day_net[dates[n]] = day_net.get(dates[n], Decimal(0)) + (parse_amount(cell(row, "net")) or Decimal(0))
    for n, row in enumerate(table.rows):
        gross, fee, net = (parse_amount(cell(row, r)) or Decimal(0) for r in ("gross", "fee", "net"))
        category = _category(_key(cell(row, "category")))
        text = " ".join(row[k] for k in roles.get("description", []) if row[k]) or agent
        day, ref = dates[n].isoformat(), cell(row, "id") or f"line {n + 1}"
        currency = (cell(row, "currency") or "GBP").upper()
        if category == "payout":
            continue

        def booked(amount: Decimal, account: str, description: str, counterparty: str):
            return AccountingTransaction(description=description, date=day, amount=float(abs(amount)),
                                         direction="in" if amount > 0 else "out", account=account,
                                         currency=currency, document_type="agent_statement",
                                         counterparty=counterparty, document_number=ref,
                                         document_total=float(day_net[dates[n]]))

        if category in ("charge", "refund"):
            rows.append(booked(gross, SALES, text, cell(row, "customer") or agent))
            if fee:   # a cost whichever way it is written (Stripe positive, PayPal negative)
                rows.append(booked(-abs(fee), FEES, f"{agent} fee: {text}", agent))
        elif category == "fee":
            rows.append(booked(-abs(gross or fee), FEES, text, agent))
        else:
            rows.append(booked(gross or net, SUSPENSE, text, agent))
            warnings.append(f"{agent} line of type '{cell(row, 'category') or 'none'}' on {dates[n]:%d %b %Y} "
                            f"({abs(gross or net):,.2f}) is on Suspense: check what it was.")
    return TransactionExtractionResult(data=rows, warnings=warnings, agent=agent)
