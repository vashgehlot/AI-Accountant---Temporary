"""The bank side: each money account's statement lines with running balances, and the monthly reconciliation of
statement against books."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from testbooks.money import ZERO


@dataclass(frozen=True)
class StatementLine:
    id: str
    account: str
    date: date
    type_code: str
    description: str
    amount: Decimal
    balance: Decimal


@dataclass(frozen=True)
class BankRec:
    account: str
    month_end: date
    statement_balance: Decimal
    book_balance: Decimal
    items: tuple[tuple[str, Decimal, str], ...]


def _opening(world, account_id: str) -> Decimal:
    code = world.client.account(account_id).code
    return world.client.opening.balances.get(code, ZERO)


def statement_lines(world, account_id: str) -> list[StatementLine]:
    """The account's lines in date order, each with the balance after it (client-side signs: a card owed is
    negative)."""
    payments = sorted((p for d in world.deals for p in d.payments if p.account == account_id),
                      key=lambda p: (p.date, p.id))
    balance, out = _opening(world, account_id), []
    for p in payments:
        balance += p.amount
        out.append(StatementLine(p.id, account_id, p.date, p.type_code, p.descriptor, p.amount, balance))
    return out


def bank_rec(world, books, account_id: str, month_end: date) -> BankRec:
    """Statement balance against book balance at a month end. A card payment is booked on the purchase date but
    reaches the statement a day or two later; those are the reconciling items."""
    code = world.client.account(account_id).code
    statement = _opening(world, account_id) + sum(
        (p.amount for d in world.deals for p in d.payments if p.account == account_id and p.date <= month_end), ZERO)
    book = books.balance(code, month_end)
    items = []
    for d in world.deals:
        if d.settles_via != "bank":
            continue
        for p in d.payments:
            if p.account != account_id:
                continue
            if d.date <= month_end < p.date:
                items.append((p.id, -p.amount, "Booked, not yet on the statement"))
            elif p.date <= month_end < d.date:
                items.append((p.id, p.amount, "On the statement, booked later"))
    return BankRec(account_id, month_end, statement, book, tuple(sorted(items)))
