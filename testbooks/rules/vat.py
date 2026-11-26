"""VAT returns under the standard (accrual) scheme: boxes 1 to 9 from the deals whose tax point falls in a period.

The tax point is the deal's date. Reverse-charge purchases go in boxes 1 and 4 (VAT) and 6 and 7 (value), as
VAT Notice 741A sets out (research notes 2.8). Boxes 6 to 9 are whole pounds, pence left out."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from testbooks.dates import add_months, month_end, vat_dd_date, vat_deadline
from testbooks.engine.model import Deal, Line, VatTotals
from testbooks.money import ZERO, pennies, whole_pounds

# The sign each kind of deal carries on the output (sales) or input (purchases) side of a return.
OUTPUT_KINDS = {"sale": 1, "sale_credit": -1, "interest": 1}   # deposit interest: an exempt supply
INPUT_KINDS = {"purchase": 1, "card_spend": 1, "director_expense": 1, "expense_claim": 1, "purchase_credit": -1}


@dataclass(frozen=True)
class VatReturn:
    start: date
    end: date
    box1: Decimal
    box2: Decimal
    box3: Decimal
    box4: Decimal
    box5: Decimal
    box6: int
    box7: int
    box8: int
    box9: int
    due: date
    dd: date


def reclaimable(line: Line) -> Decimal:
    """The input VAT a line lets the business reclaim."""
    if line.vat_code in ("standard", "reduced", "reverse_charge"):
        return line.vat
    if line.vat_code == "blocked_half":
        return pennies(line.vat / 2)
    return ZERO


def quarter_ends(stagger: tuple[int, ...], start: date, end: date) -> list[tuple[date, date]]:
    """The three-month quarters ending in the stagger's months that lie wholly between `start` and `end`."""
    quarters = []
    first = date(start.year, start.month, 1)
    while first <= end:
        last = month_end(add_months(first, 2))
        if last.month in stagger and first >= start and last <= end:
            quarters.append((first, last))
        first = add_months(first, 1)
    return quarters


def _parts(deal: Deal) -> list[tuple[date, tuple[Line, ...], int]]:
    """When each part of a deal enters a return. A deal whose VAT waits on the client's answer (say, the full VAT
    invoice) is in the return as first booked, and the answer's difference joins the return it is dated in: input
    VAT is reclaimed once the invoice is in hand."""
    query = deal.query
    if query is not None and query.before is not None:
        return [(deal.date, query.before, 1), (query.answer_date, deal.lines, 1), (query.answer_date, query.before, -1)]
    return [(deal.date, deal.lines, 1)]


def vat_return(deals: Iterable[Deal], start: date, end: date, brought_in: VatTotals | None = None) -> VatReturn:
    box1 = box4 = sales = purchases = ZERO
    for deal in deals:
        out_sign, in_sign = OUTPUT_KINDS.get(deal.kind), INPUT_KINDS.get(deal.kind)
        for on, lines, k in _parts(deal):
            if not start <= on <= end:
                continue
            for line in lines:
                if out_sign:
                    if line.vat_code in ("standard", "reduced"):
                        box1 += k * out_sign * line.vat
                    if line.vat_code != "outside":
                        sales += k * out_sign * line.net
                elif in_sign:
                    box4 += k * in_sign * reclaimable(line)
                    if line.vat_code == "reverse_charge":
                        box1 += k * in_sign * line.vat
                        sales += k * in_sign * line.net
                    if line.vat_code != "outside":
                        purchases += k * in_sign * line.net
        if not start <= deal.date <= end:
            continue
        box1 += deal.vat_boxes.get(1, ZERO)
        box4 += deal.vat_boxes.get(4, ZERO)
        sales += deal.vat_boxes.get(6, ZERO)
        purchases += deal.vat_boxes.get(7, ZERO)
    if brought_in is not None:
        box1 += brought_in.output
        box4 += brought_in.input
        sales += brought_in.net_sales
        purchases += brought_in.net_purchases
    box1, box4 = pennies(box1), pennies(box4)
    box2 = pennies(0)
    box3 = box1 + box2
    return VatReturn(start, end, box1, box2, box3, box4, box3 - box4, whole_pounds(sales), whole_pounds(purchases),
                     0, 0, vat_deadline(end), vat_dd_date(end))
