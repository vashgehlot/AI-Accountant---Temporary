"""The simulator: a client's own trading deals, plus the payroll, VAT and the payments the rules make due, numbered
in date order."""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Callable

from testbooks.dates import add_months, next_working_day, paye_due, previous_working_day, vat_dd_date
from testbooks.engine.make import deal, doc, jl, pay
from testbooks.engine.model import Client, Deal
from testbooks.money import ZERO
from testbooks.rules.payroll import PayRun, pay_year
from testbooks.rules.vat import VatReturn, quarter_ends, vat_return

PAYROLL_BUREAU = "Clearline Payroll Bureau"
PENSION_PROVIDER = "Clearwell Workplace Pensions"


@dataclass(frozen=True)
class World:
    client: Client
    deals: tuple[Deal, ...]
    vat_returns: tuple[VatReturn, ...]
    pay_runs: tuple[PayRun, ...]
    until: date


def _registry() -> dict[str, tuple[Callable[[], Client], Callable]]:
    from testbooks.clients import agency
    from testbooks.packs.definitions import PACKS
    registry = {"agency": (agency.define, agency.deals)}
    for case_id, entry in PACKS.items():
        registry[f"pack:{case_id}"] = entry
    return registry


CLIENTS = _registry


def _prefix(client: Client) -> str:
    return "PK" if client.kind == "pack" else client.id[:2].upper()


def _payroll(client: Client, until: date) -> tuple[list[Deal], list[PayRun]]:
    if not client.employees:
        return [], []
    start = client.periods[0].start
    first_payday = previous_working_day(date(start.year, start.month, 28))
    if first_payday < start:
        first_payday = previous_working_day(add_months(date(start.year, start.month, 28), 1))
    first_tax_year = first_payday.year if first_payday >= date(first_payday.year, 4, 6) else first_payday.year - 1
    runs: list[PayRun] = []
    year = first_tax_year
    while date(year, 4, 6) <= until:
        runs += [r for r in pay_year(client.employees, year, client.policies.pension_ee, client.policies.pension_er)
                 if start <= r.pay_date <= until]
        year += 1
    names = {e.id: e for e in client.employees}
    deals = []
    for run in runs:
        staff = sum((p.gross for p in run.payslips if not names[p.employee_id].director), ZERO)
        directors = run.gross - staff
        er_pension = sum((p.er_pension for p in run.payslips), ZERO)
        paye_total = sum((p.tax + p.ee_ni + p.er_ni for p in run.payslips), ZERO)
        journal = [jl("7000", staff), jl("7001", directors), jl("7006", run.er_ni), jl("7007", er_pension),
                   jl("2220", credit=run.net), jl("2210", credit=paye_total), jl("2230", credit=run.pension)]
        if run.ea_used:
            journal += [jl("2210", run.ea_used), jl("7006", credit=run.ea_used)]
        cases = {"EC-0244", "EC-0372"}
        if date(2024, 1, 6) <= run.pay_date <= date(2024, 4, 5):
            cases.add("EC-0373")
        if run.ea_used:
            cases.add("EC-0375")
        if run.pay_date.year == 2024 and run.pay_date.month == 3:
            cases |= {"EC-0519", "EC-0521"}
        payments = [pay("hsbc", run.pay_date, -p.net, f"{names[p.employee_id].name.upper()} SALARY", "BP", "2220")
                    for p in run.payslips if p.net]
        docs = [doc("payroll_summary", PAYROLL_BUREAU, client.name, f"PR-{run.pay_date:%Y-%m}", run.pay_date,
                    printed={"gross": run.gross}, payslips=run.payslips),
                doc("employer_payment_record", PAYROLL_BUREAU, client.name, f"P32-{run.pay_date:%Y-%m}",
                    run.pay_date, treatment="evidence", printed={"gross": run.paye}, ea_used=run.ea_used,
                    paye_before_allowance=paye_total)]
        deals.append(deal("payroll", run.pay_date, PAYROLL_BUREAU, "journal", journal=journal, payments=payments,
                          docs=docs, cases=cases))
        due = paye_due(run.pay_date)
        if due <= until:
            deals.append(deal("paye_payment", due, "HMRC", "journal", cases={"EC-0438"}, payments=[
                pay("hsbc", due, -run.paye, "HMRC CUMBERNAULD 120PA00048215", "BP", "2210")]))
        pension_day = next_working_day(add_months(date(run.pay_date.year, run.pay_date.month, 15), 1))
        if pension_day <= until:
            deals.append(deal("pension_payment", pension_day, PENSION_PROVIDER, "journal", cases={"EC-0380"},
                              payments=[pay("hsbc", pension_day, -run.pension, "CLEARWELL PENSIONS DD", "DD",
                                            "2230")]))
    return deals, runs


def _vat(client: Client, trading: list[Deal], until: date) -> tuple[list[Deal], list[VatReturn]]:
    if not client.vat_stagger:
        return [], []
    start = client.periods[0].start
    quarters = [q for q in quarter_ends(client.vat_stagger, add_months(start, -2), until) if q[1] >= start]
    returns = [vat_return(trading, q0, q1, client.opening.vat_brought_in if q0 < start else None)
               for q0, q1 in quarters]
    deals = []
    for r in returns:
        if r.dd <= until and r.box5:
            amount = -r.box5
            text = f"HMRC VAT {client.vat_number}" if amount < 0 else "HMRC VAT REPAYMENT"
            deals.append(deal("vat_payment", r.dd, "HMRC", "journal", cases={"EC-0438"},
                              payments=[pay("hsbc", r.dd, amount, text, "DD" if amount < 0 else "CR", "2202")]))
    return deals, returns


def _opening_liabilities(client: Client, until: date) -> list[Deal]:
    """The liabilities the opening balances owe that the rules date: the last VAT quarter before the period, and the
    last month's PAYE and pension."""
    o, start = client.opening, client.periods[0].start
    deals = []
    if client.vat_stagger and "2202" in o.balances:
        last_quarter_end = max(q1 for _, q1 in quarter_ends(client.vat_stagger, add_months(start, -6), o.as_at))
        owed = -(o.balances["2202"] + o.true_differences.get("2202", ZERO))
        on = vat_dd_date(last_quarter_end)
        deals.append(deal("vat_payment", on, "HMRC", "journal", cases={"EC-0438"},
                          payments=[pay("hsbc", on, -owed, f"HMRC VAT {client.vat_number}", "DD", "2202")]))
    if o.balances.get("2210"):
        on = paye_due(previous_working_day(date(o.as_at.year, o.as_at.month, 28)))
        deals.append(deal("paye_payment", on, "HMRC", "journal", cases={"EC-0438"}, payments=[
            pay("hsbc", on, o.balances["2210"], "HMRC CUMBERNAULD 120PA00048215", "BP", "2210")]))
    if o.balances.get("2230"):
        on = next_working_day(date(start.year, start.month, 15))
        deals.append(deal("pension_payment", on, PENSION_PROVIDER, "journal", cases={"EC-0380"}, payments=[
            pay("hsbc", on, o.balances["2230"], "CLEARWELL PENSIONS DD", "DD", "2230")]))
    return [d for d in deals if d.date <= until]


def _number(client: Client, deals: list[Deal]) -> tuple[Deal, ...]:
    """Sort by date (creation order breaks ties) and give every deal, document, query and payment its ID."""
    prefix = _prefix(client)
    ordered = [d for _, _, d in sorted((d.date, i, d) for i, d in enumerate(deals))]
    doc_no = 0
    pay_no: dict[tuple[str, int, int], int] = {}
    out = []
    for n, d in enumerate(ordered, 1):
        docs = []
        for x in d.docs:
            doc_no += 1
            docs.append(replace(x, id=f"{prefix}-D{doc_no:04d}"))
        query = d.query
        if query is not None:
            answer_doc = query.answer_doc
            if answer_doc is not None:
                doc_no += 1
                answer_doc = replace(answer_doc, id=f"{prefix}-D{doc_no:04d}")
            query = replace(query, id=f"{prefix}-Q{n:04d}", answer_doc=answer_doc)
        payments = []
        for p in d.payments:
            key = (p.account, p.date.year, p.date.month)
            pay_no[key] = pay_no.get(key, 0) + 1
            payments.append(replace(p, id=f"{p.account}-{p.date:%Y-%m}-{pay_no[key]:04d}"))
        out.append(replace(d, id=f"{prefix}-{n:04d}", docs=tuple(docs), query=query, payments=tuple(payments)))
    return tuple(out)


def simulate(client: Client, until: date, seed: int) -> World:
    _, deal_source = CLIENTS()[client.id if client.kind != "pack" else f"pack:{client.id}"]
    rng = random.Random(f"{seed}:{client.id}")
    trading = [d for d in deal_source(client, until, rng) if d.date <= until]
    payroll, runs = _payroll(client, until)
    if client.kind == "pack":
        period = client.periods[0]          # a pack shows its month's VAT return, with nothing paid
        vat_deals, returns = [], [vat_return(trading, period.start, period.end)]
    else:
        vat_deals, returns = _vat(client, trading, until)
    opening = _opening_liabilities(client, until) if client.kind != "pack" else []
    late = getattr(sys.modules[deal_source.__module__], "late_deals", None)
    if late is not None:
        extra = [d for d in late(client, trading + payroll + vat_deals + opening, until) if d.date <= until]
        if any(ln.vat for d in extra for ln in d.lines):
            raise ValueError("late deals must carry no VAT: the VAT payments are already fixed")
        trading = trading + extra
        # Worked again so boxes 6 and 7 include them; with no VAT on them, box 5 and the payments stand.
        _, returns = _vat(client, trading, until)
    deals = _number(client, trading + payroll + vat_deals + opening)
    return World(client, deals, tuple(returns), tuple(runs), until)
