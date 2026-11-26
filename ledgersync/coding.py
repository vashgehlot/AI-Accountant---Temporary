"""Purchases coded away from their supplier's usual account: a regular supplier's bills go to one account month after
month, so a bill of theirs on another is more often a slip than a change. Nothing is changed here: books.py says so
on the row (unusual_account) and the rules suggest the usual account, for a person to apply. A supplier with few
bills, or whose bills go to several accounts (a supermarket, a marketplace), is left alone: a wrong flag costs more
than a missed one."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .accounts import BY_CODE, SUSPENSE, AccountType
from .checks import _FOOD_AND_DRINK, booked
from .matching import same_supplier
from .models import Direction, Transaction

MIN_HISTORY = 3          # a supplier's other bills needed before one of theirs is called unusual
SHARE = Decimal("0.8")   # the part of those that must be on one account for it to be the usual one
RELATED = 5              # how many of the usual bills an unusual one points to
_NOT_CODED = {"journal", "payroll"}   # entries a person makes between accounts, and wages: no supplier's bill


@dataclass(frozen=True)
class Usual:
    """Where a supplier's other bills went, for a row that went elsewhere."""
    code: str            # the account the supplier's other bills are on
    others: int          # how many other bills of the supplier were counted
    on_usual: int        # how many of them are on `code`
    related: list[int]   # the places in the rows of up to RELATED of those, the latest first


def _checked(tx: Transaction) -> bool:
    """A booked purchase from a named supplier, on a cost account or a fixed asset: a row whose account someone
    chose for what was bought. Suspense holds what no one has coded yet. A bank line that pays a bill posts against
    the supplier's account (paid_against), so the account on it was never chosen for anything."""
    account = BY_CODE.get(tx.account_code)
    return (booked(tx) and tx.direction == Direction.OUT and tx.document_type not in _NOT_CODED
            and not (tx.pays and tx.paid_against is not None)
            and bool((tx.counterparty or "").strip()) and account is not None and account.code != SUSPENSE
            and (account.type == AccountType.EXPENSE or account.code.startswith("00")))


def usual_accounts(rows: list[Transaction], *, flag: list[bool]) -> list[Optional[Usual]]:
    """For each row, its supplier's usual account when the row is on a different one; otherwise None. Suppliers are
    told apart by matching.same_supplier. A row's others are its supplier's rows of other documents,
    counted once for each account a document is on, so a bill split over three lines is one bill. flag[k] False: row
    k counts as history but is never flagged (a row of a closed year, or one a person said is right)."""
    suppliers: list[list[int]] = []   # the places of each supplier's rows, the supplier named by its first row
    named: dict[str, list[int]] = {}  # a name as written to its supplier: most rows repeat a name already placed
    for k, tx in enumerate(rows):
        if not _checked(tx):
            continue
        name = tx.counterparty.strip()
        group = named.get(name)
        if group is None:
            group = next((g for g in suppliers if same_supplier(rows[g[0]].counterparty, name)), None)
            if group is None:
                suppliers.append(group := [])
            named[name] = group
        group.append(k)
    found: list[Optional[Usual]] = [None] * len(rows)
    for group in suppliers:
        # A document's key: its reference, or the row itself when it has none.
        doc = {k: rows[k].document_ref or f"row:{k}" for k in group}
        for k in group:
            if not flag[k]:
                continue
            seen: dict[tuple[str, str], int] = {}   # (document, account) to the first row of it
            for j in group:
                if doc[j] != doc[k]:
                    seen.setdefault((doc[j], rows[j].account_code), j)
            if len(seen) < MIN_HISTORY:
                continue
            counts = Counter(code for _, code in seen)
            code, on_usual = counts.most_common(1)[0]
            if Decimal(on_usual) / len(seen) < SHARE or rows[k].account_code == code:
                continue
            if rows[k].account_code in _FOOD_AND_DRINK and code in _FOOD_AND_DRINK:
                continue   # one meal account or another: who was there decides (checks.meal_check), not the place
            usual = sorted((j for (_, c), j in seen.items() if c == code),
                           key=lambda j: (rows[j].date or dt.date.min, j), reverse=True)
            found[k] = Usual(code=code, others=len(seen), on_usual=on_usual, related=usual[:RELATED])
    return found


def named_account(code: str) -> str:
    return f"{code} {BY_CODE[code].name}"


def usual_text(tx: Transaction, usual: Usual) -> str:
    """Where the supplier's other bills went: "The other 11 bills from Vodafone Ltd went to 7502 Telephone and
    Internet." The reason a suggested account change gives."""
    who = (tx.counterparty or "").strip()
    count = (f"The other {usual.others} bills" if usual.on_usual == usual.others
             else f"{usual.on_usual} of the other {usual.others} bills")
    return f"{count} from {who} went to {named_account(usual.code)}."


def unusual_account_text(tx: Transaction, usual: Usual) -> str:
    """What the row says: the account it is on, then where the supplier's other bills went."""
    return f"Coded to {named_account(tx.account_code)}. {usual_text(tx, usual)}"
