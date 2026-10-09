"""Checks a bank statement's rows against the balances it prints (design of 2026-10-06). Each line's running
balance must follow from the line before, and the opening balance plus the rows must reach the closing
balance; a gap means a line was missed or misread. Pure functions over one upload's rows, in their order."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .checks import STATEMENT_ISSUES, issue
from .models import Direction, Issue, StatementCheck, Transaction
from .money import ZERO


def _signed(tx: Transaction) -> Decimal:
    return tx.gross if tx.direction == Direction.IN else -tx.gross


def _gbp(amount: Decimal) -> str:
    return f"£{amount:,.2f}" if amount >= 0 else f"-£{-amount:,.2f}"


def check_statement(rows: list[Transaction]) -> tuple[list[Transaction], Optional[StatementCheck]]:
    """One upload's rows, its bank lines carrying statement_gap or statement_total warnings where they don't
    agree with the printed balances, and the upload's summary; the summary is None when it has no bank lines."""
    lines = [n for n, tx in enumerate(rows) if tx.document_type == "statement"]
    if not lines:
        return rows, None
    found: dict[int, list[Issue]] = {}
    gaps: list[Decimal] = []
    compared = 0

    def moved(start: int, stop: int) -> Decimal:
        """The money in less the money out of lines[start:stop]."""
        return sum((_signed(rows[lines[k]]) for k in range(start, stop)), ZERO)

    def fits(expected: list[tuple[int, Decimal]]) -> int:
        return sum(rows[lines[k]].balance == want for k, want in expected)

    # Running balances, from one printed balance to the next (some statements print one a day). A statement
    # may list its lines oldest or newest first; the reading that fits more of them is used.
    shown = [k for k, n in enumerate(lines) if rows[n].balance is not None]
    pairs = list(zip(shown, shown[1:]))
    oldest_first = [(q, rows[lines[p]].balance + moved(p + 1, q + 1)) for p, q in pairs]
    newest_first = [(p, rows[lines[q]].balance + moved(p, q)) for p, q in pairs]
    for k, want in newest_first if fits(newest_first) > fits(oldest_first) else oldest_first:
        compared += 1
        printed = rows[lines[k]].balance
        if printed != want:
            gaps.append(abs(want - printed))
            found.setdefault(lines[k], []).append(issue(
                "statement_gap",
                f"Balance should be {_gbp(want)}; the statement shows {_gbp(printed)}."))

    # The opening balance plus every line must reach the closing balance.
    openings = [rows[n].opening_balance for n in lines if rows[n].opening_balance is not None]
    closings = [rows[n].closing_balance for n in lines if rows[n].closing_balance is not None]
    if openings and closings:
        compared += 1
        total = openings[0] + moved(0, len(lines))
        if total != closings[-1]:
            apart = abs(total - closings[-1])
            gaps.insert(0, apart)
            found.setdefault(lines[-1], []).append(issue(
                "statement_total",
                f"Opening {_gbp(openings[0])} plus these rows is {_gbp(total)}; the statement closes at "
                f"{_gbp(closings[-1])}."))

    on_lines = set(lines)
    checked = [tx.model_copy(update={"issues": [i for i in tx.issues if i.code not in STATEMENT_ISSUES]
                                               + found.get(n, [])}) if n in on_lines else tx
               for n, tx in enumerate(rows)]
    if not compared:
        return checked, StatementCheck(status="none")
    return checked, StatementCheck(status="gap", difference=gaps[0]) if gaps else StatementCheck(status="ok")
