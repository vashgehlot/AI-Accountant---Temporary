"""Rows that may record one payment twice: the same amount, the same way, from two inputs, dated within a few days.
Nothing is removed: the row says so (possible_duplicate), and a person or the AI decides, keeping one (R2) or saying
they are not the same (apart_from). Worked out here, with the rest of the books, so the AI sees what the page shows."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from .checks import booked
from .matching import names_match
from .models import NOT_TRANSACTIONS, Transaction

WINDOW = dt.timedelta(days=3)   # card payments reach the bank a day or two after the receipt
# A payroll report holds what is owed on 2220, 2210 and 2230 until the bank pays it, as an invoice holds a bill: the
# bank line of the same amount is its payment, never a second record of it.
_DOCUMENTS = {"invoice", "expense_claim", "agent_statement", "payroll"}


def _kind(tx: Transaction) -> str:
    """How a row is booked: a document holding what is owed, a bank line, or anything else paid when it happened.
    Payment matching pairs a document with a bank line, so those two are never each other's duplicates."""
    kind = tx.document_type or "receipt"
    if tx.claimed_in is not None or kind in _DOCUMENTS or kind in NOT_TRANSACTIONS:
        return "document"   # a receipt on an expense claim is owed to the claimant, like a bill
    return "bank" if kind == "statement" else "other"


def _number(tx: Transaction) -> str:
    return "".join(ch for ch in (tx.document_number or "").lower() if ch.isalnum())


def _numbered_apart(a: Transaction, b: Transaction) -> bool:
    """Two receipts from one shop that print different numbers: a till numbers every receipt, so they are two
    purchases (a second photo of one receipt prints its number)."""
    return (a.document_type == b.document_type == "receipt" and bool(_number(a)) and bool(_number(b))
            and _number(a) != _number(b) and bool(a.counterparty) and bool(b.counterparty)
            and names_match(a.counterparty, b.counterparty))


def _linked(tx: Transaction) -> set[str]:
    """The refs of what matching linked the row to: what it pays, what paid it, its claim and what books it."""
    found = [*tx.pays, *tx.paid_by, tx.claimed_in, tx.recorded_by]
    return {s.ref for s in found if s is not None}


def possible_duplicates(rows: list[Transaction], *, uploads: list[int], ids: list[int]) -> list[Optional[int]]:
    """For each row, the index of an earlier row from another upload that it may repeat: the same amount and way,
    dated within WINDOW of it (or both undated); otherwise None. uploads and ids: each row's upload and row id.
    Rows of one upload are not compared (two equal payments on one statement are usually real), nor rows out of the
    books, a document and a bank line, rows matching linked, rows a person said are not the same, or two receipts on
    one expense claim, which has a line for each (claimed_in names the line; the lines of one claim are one upload),
    or two receipts from one shop with different numbers."""
    upload_of = {row.document_ref: uploads[k] for k, row in enumerate(rows) if row.document_ref}

    def claim(row: Transaction) -> Optional[object]:
        """The expense claim the row is a receipt on: its line's upload, else the line itself."""
        if row.claimed_in is None:
            return None
        return upload_of.get(row.claimed_in.ref, row.claimed_in.ref)

    found: list[Optional[int]] = []
    earlier: dict[tuple, list[int]] = {}   # the booked rows so far, by way and amount: only those can repeat a row
    for i, row in enumerate(rows):
        found.append(None)
        if not booked(row) or row.document_type in ("journal", "write_off"):   # they move no money: repeat no payment
            continue
        same = earlier.setdefault((row.direction, row.gross), [])
        candidates = list(same)   # the earlier ones, oldest first
        same.append(i)
        for j in candidates:
            other = rows[j]
            if uploads[j] == uploads[i]:
                continue
            if {_kind(row), _kind(other)} == {"document", "bank"}:
                continue
            if (other.document_ref and other.document_ref in _linked(row)) or (
                    row.document_ref and row.document_ref in _linked(other)):
                continue
            if ids[j] in row.apart_from or ids[i] in other.apart_from:
                continue
            if claim(row) is not None and claim(row) == claim(other):
                continue
            if _numbered_apart(row, other):
                continue
            if row.date is None or other.date is None:
                if row.date is other.date:
                    found[i] = j
                    break
                continue
            if abs(row.date - other.date) <= WINDOW:
                found[i] = j
                break
    return found


def renumbered_invoices(rows: list[Transaction], *, ids: list[int]) -> list[Optional[list[int]]]:
    """For the first row of each invoice, the rows of an earlier booked invoice it may replace: the same number, from
    the same counterparty, the same way, for a different total (a revised invoice sent under the old number);
    otherwise None. Earlier by date, then by place. The same total is a copy, which matching sets aside itself. Not
    rows a person said are not the same."""
    documents: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if row.document_type == "invoice" and booked(row) and row.document_ref and (row.document_number or "").strip():
            documents.setdefault(row.document_ref, []).append(i)

    def total(lines: list[int]):
        return rows[lines[0]].document_total or sum(rows[i].gross for i in lines)

    def number(lines: list[int]) -> str:
        return "".join(ch for ch in rows[lines[0]].document_number.lower() if ch.isalnum())

    ordered = sorted(documents.values(), key=lambda lines: (rows[lines[0]].date or dt.date.max, lines[0]))
    found: list[Optional[list[int]]] = [None] * len(rows)
    for at, lines in enumerate(ordered):
        first = rows[lines[0]]
        for earlier in ordered[:at]:
            other = rows[earlier[0]]
            if (number(earlier) == number(lines) and other.direction == first.direction
                    and total(earlier) != total(lines) and names_match(other.counterparty, first.counterparty)
                    and not any(ids[j] in first.apart_from or ids[lines[0]] in rows[j].apart_from for j in earlier)):
                found[lines[0]] = earlier
                break
    return found
