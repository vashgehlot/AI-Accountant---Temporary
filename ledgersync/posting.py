"""Double entry: each transaction becomes balanced journal lines against the bank (or its
contra account), with VAT on its own control account; the trial balance sums them."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .accounts import BY_CODE, PURCHASE_VAT, SALES_VAT, VAT_ACCOUNTS, AccountType
from .checks import booked, normalise
from .errors import InvalidTransactions
from .matching import match
from .models import BusinessSettings, Direction, JournalLine, Transaction, TrialBalance, TrialBalanceLine
from .money import ZERO


def journal_for(tx: Transaction, index: int) -> list[JournalLine]:
    """Journal lines for one transaction after checks.normalise and matching.match: the account and VAT
    legs, then the bank (or contra) leg. A bank line that pays a document posts against the account
    holding what was owed (paid_against); its VAT is nil, because it was booked with the document."""
    code = tx.paid_against or tx.account_code
    account = BY_CODE[code]
    vat_account = SALES_VAT if account.type == AccountType.INCOME else PURCHASE_VAT
    out = tx.direction == Direction.OUT
    lines = [JournalLine(transaction=index, code=leg, description=tx.description,
                         debit=amount if out else ZERO, credit=ZERO if out else amount)
             for leg, amount in ((code, tx.net), (vat_account, tx.vat_posted)) if amount]
    lines.append(JournalLine(transaction=index, code=tx.contra_account_code, description=tx.description,
                             debit=ZERO if out else tx.gross, credit=tx.gross if out else ZERO))
    debits, credits = sum(l.debit for l in lines), sum(l.credit for l in lines)
    if debits != credits:   # net + vat == gross by construction; this guards the invariant
        raise AssertionError(f"transaction {index} does not balance: {debits} != {credits}")
    return lines


def _vat_last(item: tuple[str, Decimal]) -> tuple[bool, str]:
    """By account code, with the VAT accounts last."""
    return item[0] in VAT_ACCOUNTS, item[0]


def trial_balance(transactions: list[Transaction], settings: BusinessSettings) -> TrialBalance:
    ready = match([normalise(tx, settings) for tx in transactions], settings)
    posted = [(n, tx) for n, tx in enumerate(ready) if booked(tx)]   # a quote or the like waits for Include
    problems = [f"#{n + 1}: {issue.message}" for n, tx in posted
                for issue in tx.issues if issue.severity == "error"]
    if problems:
        raise InvalidTransactions(f"{len(problems)} problem(s) must be fixed before the trial balance: "
                                  + " ".join(problems[:5]), problems=problems)
    journal = [line for n, tx in posted for line in journal_for(tx, n)]
    balances: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in journal:
        balances[line.code] += line.debit - line.credit
    lines = [TrialBalanceLine(code=code, name=BY_CODE[code].name, type=BY_CODE[code].type.value,
                              debit=balance if balance > 0 else ZERO, credit=-balance if balance < 0 else ZERO)
             for code, balance in sorted(balances.items(), key=_vat_last) if balance != 0]
    total_debits = sum((l.debit for l in lines), ZERO)
    total_credits = sum((l.credit for l in lines), ZERO)
    total_income = sum((l.credit - l.debit for l in lines if l.type == AccountType.INCOME.value), ZERO)
    total_expenses = sum((l.debit - l.credit for l in lines if l.type == AccountType.EXPENSE.value), ZERO)
    net_profit = total_income - total_expenses
    total_assets = sum((l.debit - l.credit for l in lines if l.type == AccountType.ASSET.value), ZERO)
    total_liabilities = sum((l.credit - l.debit for l in lines if l.type == AccountType.LIABILITY.value), ZERO)
    return TrialBalance(lines=lines, total_debits=total_debits, total_credits=total_credits,
                        is_balanced=total_debits == total_credits, journal=journal,
                        total_income=total_income, total_expenses=total_expenses,
                        net_profit=net_profit, total_assets=total_assets, total_liabilities=total_liabilities)
