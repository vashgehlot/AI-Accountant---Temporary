"""The adjustments an accountant makes at the year end: prepayments, accruals, deferred income, depreciation, the
corporation tax charge and last year's over- or under-provision. All time-apportioned by days."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from testbooks.books.chart import CHART
from testbooks.books.ledger import Books, Entry
from testbooks.engine.model import Deal, Period
from testbooks.money import ZERO, pennies
from testbooks.rules.rates import rate
from testbooks.rules.vat import reclaimable

CAPITAL = {"0030": ("computer", "0031"), "0040": ("furniture", "0041")}
CLASS_ACCUMULATED = {cls: acc for cls, acc in CAPITAL.values()}


@dataclass(frozen=True)
class CtWorking:
    profit_before_tax: Decimal
    add_backs: dict[str, Decimal]
    capital_allowances: Decimal
    taxable: Decimal
    tax: Decimal


@dataclass(frozen=True)
class Adjustment:
    id: str
    kind: str
    entries: tuple[Entry, ...]
    reason: str
    cases: tuple[str, ...] = ()
    working: CtWorking | None = field(default=None, compare=False)
    deals: tuple[str, ...] = field(default=(), compare=False)


def ct_tax(taxable: Decimal, months: int) -> Decimal:
    """Corporation tax at 19% to the lower limit, 25% from the upper, and marginal relief between (3/200 of the
    gap to the upper limit); both limits scale with the length of the period."""
    on = date(2023, 4, 1)
    lower = rate("ct_lower", on) * months / 12
    upper = rate("ct_upper", on) * months / 12
    if taxable <= lower:
        return pennies(taxable * rate("ct_small", on))
    if taxable >= upper:
        return pennies(taxable * rate("ct_main", on))
    return pennies(taxable * rate("ct_main", on) - (upper - taxable) * rate("ct_mr_fraction", on))


def _days(a: date, b: date) -> int:
    return (b - a).days + 1


def _pl_cost(deal: Deal) -> dict[str, Decimal]:
    """What a deal put on each profit and loss account: its net plus any VAT it couldn't reclaim."""
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in deal.lines:
        if CHART[ln.account].kind in ("income", "expense"):
            out[ln.account] += ln.net if ln.vat_code == "reverse_charge" else ln.net + ln.vat - reclaimable(ln)
    return dict(out)


class _Adjuster:
    def __init__(self, period: Period):
        self.period = period
        self.out: list[Adjustment] = []

    def add(self, kind: str, lines: list[tuple[str, Decimal]], reason: str, cases=(), working=None, deals=()):
        """`lines` are (account, amount): positive a debit, negative a credit. `deals` are the deals it rests on."""
        n = len(self.out) + 1
        aid = f"YE-{n:02d}"
        entries = tuple(Entry(id=f"Y{n:02d}{i:02d}", journal_id=aid, date=self.period.end, account=acc,
                              debit=amt if amt > 0 else ZERO, credit=-amt if amt < 0 else ZERO, phase="year_end",
                              cases=tuple(cases), stakes="accounts")
                        for i, (acc, amt) in enumerate(lines, 1) if amt)
        if entries:
            self.out.append(Adjustment(aid, kind, entries, reason, tuple(cases), working, tuple(deals)))


def years_charged(bought: date, period: Period) -> int:
    """How many year ends (on this period's year-end day) fall between purchase and this period's start."""
    count, y = 0, bought.year
    while True:
        ye = date(y, period.end.month, period.end.day)
        if ye >= period.start:
            return count
        if ye >= bought:
            count += 1
        y += 1


def year_end(world, books: Books, period: Period) -> tuple[Adjustment, ...]:
    client, adj = world.client, _Adjuster(period)
    policies = client.policies
    threshold = policies.accrue_from
    in_period = [d for d in world.deals if period.start <= d.date <= period.end]

    for d in in_period:
        if d.covers is None or d.covers[1] <= period.end:
            continue
        after = _days(max(d.covers[0], date.fromordinal(period.end.toordinal() + 1)), d.covers[1])
        share = Decimal(after) / _days(*d.covers)
        if d.kind == "sale":
            net = sum((ln.net for ln in d.lines), ZERO)
            if net >= threshold:
                amt = pennies(net * share)
                adj.add("deferred_income", [(d.lines[0].account, amt), ("2125", -amt)],
                        f"{d.counterparty}: invoiced for {d.covers[0]:%d %b %Y} to {d.covers[1]:%d %b %Y}", d.cases,
                        deals=(d.id,))
        else:
            for account, cost in sorted(_pl_cost(d).items()):
                if cost >= threshold:
                    amt = pennies(cost * share)
                    adj.add("prepayment", [("1103", amt), (account, -amt)],
                            f"{d.counterparty}: {after} of {_days(*d.covers)} days are next year", d.cases,
                            deals=(d.id,))

    for d in world.deals:
        if not period.end < d.date <= world.until or d.covers is None or d.covers[0] > period.end:
            continue
        within = _days(d.covers[0], min(d.covers[1], period.end))
        share = Decimal(within) / _days(*d.covers)
        for account, cost in sorted(_pl_cost(d).items()):
            if cost >= threshold and d.kind != "sale":
                amt = pennies(cost * share)
                adj.add("accrual", [(account, amt), ("2109", -amt)],
                        f"{d.counterparty}: billed {d.date:%d %b %Y} for {within} days of this year", d.cases,
                        deals=(d.id,))
    for description, account, amount, end in policies.known_accruals:
        if end == period.end:
            adj.add("accrual", [(account, amount), ("2109", -amount)], description, ("EC-0506",))

    charges: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for a in client.opening.assets:
        if a.bought <= period.end and years_charged(a.bought, period) < policies.depreciation_years[a.cls]:
            charges[CLASS_ACCUMULATED[a.cls]] += pennies(a.cost / policies.depreciation_years[a.cls])
    additions = ZERO
    for d in in_period:
        for ln in d.lines:
            if ln.account in CAPITAL:
                cls, acc = CAPITAL[ln.account]
                charges[acc] += pennies(ln.net / policies.depreciation_years[cls])
                additions += ln.net
    for acc, amt in sorted(charges.items()):
        adj.add("depreciation", [("8000", amt), (acc, -amt)], f"Straight line, a full year in the year bought")

    opening_ct = -client.opening.balances.get("2320", ZERO)
    paid = sum((-p.amount for d in in_period if d.kind == "ct_payment" for p in d.payments), ZERO)
    ct_cases = tuple(sorted({c for d in in_period if d.kind == "ct_payment" for c in d.cases}))
    if opening_ct and paid:
        diff = opening_ct - paid
        adj.add("ct_prior_year", [("2320", diff), ("9100", -diff)],
                "Last year's corporation tax: provided against paid", ct_cases)

    so_far = Books(books.entries + tuple(e for a in adj.out for e in a.entries))
    balances = so_far.balances(period.end, ("opening", "books", "answers", "year_end"))
    pbt = -sum((v for code, v in balances.items()
                if CHART[code].kind in ("income", "expense") and code != "9100"), ZERO)
    add_backs = {code: balances[code] for code in sorted(balances)
                 if CHART[code].tax == "disallowable" and CHART[code].kind == "expense" and balances[code]}
    taxable = pbt + sum(add_backs.values(), ZERO) - additions
    months = round((period.end - period.start).days / 30.44)
    tax = ct_tax(max(taxable, ZERO), months)
    working = CtWorking(pbt, add_backs, additions, taxable, tax)
    adj.add("ct_charge", [("9100", tax), ("2320", -tax)], "Corporation tax on this year's profit",
            ("EC-0707",), working)
    return tuple(adj.out)
