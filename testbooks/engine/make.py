"""Small builders the client modules use to describe deals. IDs are left blank: the simulator numbers everything
once all the deals exist, in date order."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from testbooks.engine.model import Deal, Doc, JournalLine, Line, Payment, Query
from testbooks.money import ZERO, pennies, vat_in

TAXED = ("standard", "reduced", "reverse_charge", "blocked", "blocked_half")


def m(x) -> Decimal:
    """Money from a number or string, to the penny."""
    return pennies(x if isinstance(x, Decimal) else str(x))


def line(description: str, account: str, net, code: str = "standard", vat=None, rate: str = "0.20",
         also_ok: tuple[str, ...] = (), stakes: str = "accounts") -> Line:
    net = m(net)
    if vat is None:
        vat = pennies(net * Decimal(rate)) if code in TAXED else ZERO
    return Line(description, account, net, code, m(vat), tuple(also_ok), stakes)


def gross_line(description: str, account: str, gross, code: str = "standard", rate: str = "0.20",
               also_ok: tuple[str, ...] = (), stakes: str = "accounts") -> Line:
    """A line worked back from a VAT-inclusive amount, as a till receipt prints it."""
    gross = m(gross)
    vat = vat_in(gross, Decimal(rate)) if code in TAXED else ZERO
    return Line(description, account, gross - vat, code, vat, tuple(also_ok), stakes)


def held_vat(description: str, account: str, net, vat) -> tuple[Line, Line]:
    """What an accountant books until a full VAT invoice comes: the cost, and the VAT held in Suspense (or left in
    the cost, the other fair choice)."""
    return (line(description, account, net, "none"),
            line("VAT held until the full VAT invoice comes", "9998", vat, "outside", also_ok=(account,)))


def printed_figures(lines) -> dict[str, Decimal]:
    """The net, VAT and total a document prints for these lines (a reverse charge prints no VAT)."""
    net = sum((ln.net for ln in lines), ZERO)
    vat = sum((ln.vat for ln in lines if ln.vat_code != "reverse_charge"), ZERO)
    return {"net": net, "vat": vat, "gross": net + vat}


def doc(kind: str, issuer: str, recipient: str, number: str, on: date, lines=(), *, currency: str = "GBP",
        treatment: str = "book", reason: str = "", printed: dict | None = None, **extra) -> Doc:
    figures = printed if printed is not None else (printed_figures(lines) if lines else {})
    if lines:
        extra = {"lines": tuple(lines), **extra}
    return Doc("", kind, issuer, recipient, number, on, currency, treatment, reason, dict(figures), dict(extra))


def pay(account: str, on: date, amount, descriptor: str, type_code: str = "", against: str = "") -> Payment:
    return Payment("", account, on, m(amount), descriptor, type_code, against)


def jl(account: str, debit=0, credit=0, description: str = "") -> JournalLine:
    return JournalLine(account, m(debit), m(credit), description)


def deal(kind: str, on: date, counterparty: str, via: str, *, lines=(), journal=(), payments=(), docs=(),
         cases=(), query: Query | None = None, vat_boxes: dict | None = None,
         covers: tuple[date, date] | None = None) -> Deal:
    return Deal("", kind, on, counterparty, via, tuple(lines), tuple(journal), tuple(payments), tuple(docs),
                tuple(sorted(set(cases))), query, dict(vat_boxes or {}), covers)
