"""Double entry: each transaction becomes balanced journal lines against the bank (or its
contra account), with VAT on its own control account; the trial balance sums them."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Optional, Sequence

from .accounts import (BY_CODE, CIS_DEDUCTED, CIS_PAYABLE, PURCHASE_VAT, SALES_VAT, SUSPENSE, VAT_ACCOUNTS,
                       AccountType, heading_for)
from .checks import booked, normalise
from .errors import InvalidTransactions
from .matching import match
from .models import (BusinessSettings, Direction, JournalLine, OpenItem, Transaction, TrialBalance,
                     TrialBalanceLine)
from .money import ZERO


def withheld(tx: Transaction) -> Decimal:
    """The CIS tax a contractor took off the row's invoice: nothing on a bank line, which pays only what is due."""
    return tx.cis_deducted if tx.cis_deducted and tx.document_type != "statement" and tx.paid_against is None else ZERO


def journal_for(tx: Transaction, index: int) -> list[JournalLine]:
    """Journal lines for one transaction after checks.normalise and matching.match: the account and VAT
    legs, then the bank (or contra) leg. A bank line that pays a document posts against the account
    holding what was owed (paid_against); its VAT is nil, because it was booked with the document."""
    code = tx.paid_against or tx.account_code
    account = BY_CODE[code]
    # A recovery of a bad debt pays its VAT share over again, as output VAT; other VAT goes by the account.
    vat_account = SALES_VAT if account.type == AccountType.INCOME or tx.recovers else PURCHASE_VAT
    out = tx.direction == Direction.OUT
    lines = [JournalLine(transaction=index, code=leg, description=tx.description,
                         debit=amount if out else ZERO, credit=ZERO if out else amount)
             for leg, amount in ((code, tx.net), (vat_account, tx.vat_posted)) if amount]
    cis = withheld(tx)
    if cis:   # the tax a contractor withheld: owed by HMRC to the business on a sale, to HMRC on a cost
        lines.append(JournalLine(transaction=index, code=CIS_PAYABLE if out else CIS_DEDUCTED,
                                 description=tx.description, debit=ZERO if out else cis, credit=cis if out else ZERO))
    lines.append(JournalLine(transaction=index, code=tx.contra_account_code, description=tx.description,
                             debit=ZERO if out else tx.gross, credit=tx.gross if out else ZERO))
    if tx.reverse_vat and tx.paid_against is None:
        # The reverse charge on a service from abroad: the business owes the VAT its supplier didn't charge, and
        # reclaims it in the same return.
        lines += [JournalLine(transaction=index, code=PURCHASE_VAT, description=tx.description, debit=tx.reverse_vat,
                              credit=ZERO),
                  JournalLine(transaction=index, code=SALES_VAT, description=tx.description, debit=ZERO,
                              credit=tx.reverse_vat)]
    debits, credits = sum(l.debit for l in lines), sum(l.credit for l in lines)
    if debits != credits:   # net + vat == gross by construction; this guards the invariant
        raise AssertionError(f"{_named(tx)} does not balance: debits £{debits:,.2f}, credits £{credits:,.2f}")
    return lines


def _vat_last(item: tuple[str, Decimal]) -> tuple[bool, str]:
    """By account code, with the VAT accounts last."""
    return item[0] in VAT_ACCOUNTS, item[0]


def _line(code: str, balance: Decimal) -> TrialBalanceLine:
    account = BY_CODE[code]
    return TrialBalanceLine(code=code, name=account.name, type=account.type.value,
                            heading=heading_for(code, balance).value,
                            debit=balance if balance > 0 else ZERO, credit=-balance if balance < 0 else ZERO)


def _named(tx: Transaction) -> str:
    """A row as a message names it, so a person can find it: what it is, its date and its amount."""
    what = tx.description.strip() or "A row with no description"
    what = what if len(what) <= 60 else what[:57].rstrip() + "..."
    when = f"{tx.date.day} {tx.date:%b %Y}" if tx.date else "no date"
    return f"{what} ({when}, £{tx.gross:,.2f})"


def matched_rows(transactions: list[Transaction], settings: BusinessSettings,
                 read: Optional[list[Optional[Decimal]]] = None, apart: Optional[list[set[int]]] = None, *,
                 keep: Optional[list[bool]] = None, open_items: Sequence[OpenItem] = (),
                 name_days: Optional[list] = None, upload_ids: Optional[list] = None,
                 skip_errors: bool = False, held: Optional[list] = None) -> list[tuple[int, Transaction]]:
    """The rows trial_balance posts, each with its place in transactions, matched as it matches them (see there);
    InvalidTransactions while any of them has an error. name_days: each row's file name's day; upload_ids: each row's
    upload (matching.match). With skip_errors the rows with an error are left out instead, and held (when given)
    gets each of them, with its place and its problems."""
    ready = match([normalise(tx, settings) for tx in transactions], settings, read=read, apart=apart,
                  open_items=open_items, name_days=name_days, upload_ids=upload_ids)
    posted = [(n, tx) for n, tx in enumerate(ready)   # a quote or the like waits for Include
              if booked(tx) and (keep is None or keep[n])]
    problems = [f"{_named(tx)}: {issue.message}" for n, tx in posted
                for issue in tx.issues if issue.severity == "error"]
    if problems and skip_errors:   # shown without them, for a page that says which are left out
        if held is not None:
            held.extend((n, tx, [f"{_named(tx)}: {i.message}" for i in tx.issues if i.severity == "error"])
                        for n, tx in posted if any(i.severity == "error" for i in tx.issues))
        return [(n, tx) for n, tx in posted if not any(issue.severity == "error" for issue in tx.issues)]
    if problems:
        raise InvalidTransactions(f"{len(problems)} problem(s) must be fixed before the trial balance: "
                                  + "; ".join(problems[:5]), problems=problems)
    return posted


def trial_balance(transactions: list[Transaction], settings: BusinessSettings,
                  read: Optional[list[Optional[Decimal]]] = None, apart: Optional[list[set[int]]] = None, *,
                  keep: Optional[list[bool]] = None, opening: Optional[dict[str, Decimal]] = None,
                  open_items: Sequence[OpenItem] = ()) -> TrialBalance:
    """The trial balance of the transactions, matched as matching.match does. A client's saved rows pass what people
    decided (read and apart, as match takes them) so the figures book the rows the ledger books; pasted or unsaved
    rows have no decisions and pass neither. A year of a client's passes all its rows, so a payment in one year can
    clear an invoice of another (and the open items brought into its first year), and keep: the rows of that year,
    the only ones posted and checked for errors; and its opening balances, signed with debits positive, which are
    added before the movements."""
    posted = matched_rows(transactions, settings, read, apart, keep=keep, open_items=open_items)
    return summarise([line for n, tx in posted for line in journal_for(tx, n)], opening)


def summarise(journal: list[JournalLine], opening: Optional[dict[str, Decimal]] = None) -> TrialBalance:
    """The trial balance of journal lines on top of opening balances (signed with debits positive)."""
    opening = opening or {}
    balances: dict[str, Decimal] = defaultdict(lambda: ZERO, opening)
    for line in journal:
        balances[line.code] += line.debit - line.credit
    lines = [_line(code, balance) for code, balance in sorted(balances.items(), key=_vat_last) if balance != 0]
    total_debits = sum((l.debit for l in lines), ZERO)
    total_credits = sum((l.credit for l in lines), ZERO)
    total_income = sum((l.credit - l.debit for l in lines if l.type == AccountType.INCOME.value), ZERO)
    total_expenses = sum((l.debit - l.credit for l in lines if l.type == AccountType.EXPENSE.value), ZERO)
    net_profit = total_income - total_expenses
    # Suspense is no one's liability: what is held there in debit is counted with the assets until it is cleared,
    # so it neither shrinks what the business owes nor shows as a debt.
    held = sum((l.debit - l.credit for l in lines if l.code == SUSPENSE), ZERO)
    total_assets = sum((l.debit - l.credit for l in lines if l.type == AccountType.ASSET.value), ZERO) + max(held, ZERO)
    total_liabilities = sum((l.credit - l.debit for l in lines
                             if l.type == AccountType.LIABILITY.value and l.code != SUSPENSE), ZERO) + max(-held, ZERO)
    return TrialBalance(lines=lines, total_debits=total_debits, total_credits=total_credits,
                        opening=[_line(code, balance) for code, balance in sorted(opening.items(), key=_vat_last)
                                 if balance != 0],
                        is_balanced=total_debits == total_credits, journal=journal,
                        total_income=total_income, total_expenses=total_expenses,
                        net_profit=net_profit, total_assets=total_assets, total_liabilities=total_liabilities)
