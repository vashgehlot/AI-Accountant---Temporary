"""The answer key for one client-year: plain CSV files any software can be checked against, the same tables in
key.xlsx, and the accounts in accounts.xlsx."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path


from testbooks.books.accounts import accounts
from testbooks.books.bank import bank_rec, statement_lines
from testbooks.books.chart import CHART, for_client
from testbooks.books.ledger import Books
from testbooks.books.year_end import CAPITAL, years_charged
from testbooks.dates import add_months, month_end
from testbooks.engine.model import Doc, Period
from testbooks.money import ZERO, pennies
from testbooks.render.sheets import write_xlsx

COLUMNS = {
    "documents": ["doc_id", "file", "arrived", "kind", "issuer", "recipient", "number", "date", "currency", "net",
                  "vat", "gross", "treatment", "reason", "cases"],
    "statement-lines": ["line_id", "account", "date", "type", "description", "amount", "balance", "deal_id",
                        "cases"],
    "entries": ["entry_id", "journal_id", "date", "account", "account_name", "debit", "credit", "vat_code", "vat",
                "counterparty", "deal_id", "doc_ids", "line_ids", "stakes", "also_ok", "phase", "cases"],
    "bank-recs": ["account", "month_end", "statement_balance", "book_balance", "item", "item_amount", "item_note"],
    "vat-returns": ["period_start", "period_end", "box1", "box2", "box3", "box4", "box5", "box6", "box7", "box8",
                    "box9", "due", "dd"],
    "debtors": ["as_at", "counterparty", "doc_id", "number", "date", "gross", "paid", "owed"],
    "creditors": ["as_at", "counterparty", "doc_id", "number", "date", "gross", "paid", "owed"],
    "payroll": ["pay_date", "employee", "gross", "tax", "ee_ni", "er_ni", "ee_pension", "er_pension", "net",
                "ea_used"],
    "opening-balances": ["account", "name", "debit", "credit", "source"],
    "fixed-assets": ["asset_id", "description", "class", "bought", "cost", "depreciation", "accumulated",
                     "net_book_value"],
    "owners": ["account", "person", "opening", "increases", "decreases", "closing"],
    "year-end": ["adjustment_id", "kind", "account", "debit", "credit", "reason", "cases"],
    "trial-balance": ["account", "name", "heading", "opening", "books", "before_answers", "year_end", "final"],
    "queries": ["query_id", "about", "question", "why", "stakes", "answer_file", "answer_date", "effect"],
    "ct-working": ["item", "amount"],
    "mess": ["file", "kind", "detail"],
}


def fmt(x: Decimal) -> str:
    return f"{x:.2f}"


def _join(values) -> str:
    return ";".join(values)


def _month_ends(period: Period) -> list[date]:
    out, d = [], month_end(period.start)
    while d <= period.end:
        out.append(d)
        d = month_end(add_months(date(d.year, d.month, 1), 1))
    return out


def _open_items(world, side: str) -> list[dict]:
    """Every unpaid sales (or purchase) document with what cleared it, oldest first."""
    items = [dict(counterparty=i.counterparty, doc_id=f"OPENING-{i.number}", number=i.number, date=i.date,
                  gross=i.gross, moves=[]) for i in world.client.opening.open_items if i.kind == side]

    def take(counterparty: str, on: date, amount: Decimal, number: str | None = None):
        for item in items:
            if item["counterparty"] != counterparty or (number and item["number"] != number):
                continue
            owed = item["gross"] - sum(a for d, a in item["moves"] if d <= on)
            if owed <= 0:
                continue
            part = min(owed, amount)
            item["moves"].append((on, part))
            amount -= part
            if not amount:
                return

    for deal in world.deals:
        if side == "debtor":
            if deal.kind == "sale":
                doc = next(x for x in deal.docs if x.kind == "sales_invoice")
                items.append(dict(counterparty=deal.counterparty, doc_id=doc.id, number=doc.number, date=deal.date,
                                  gross=deal.gross, moves=[(p.date, p.amount) for p in deal.payments]))
            elif deal.kind == "debtor_receipt":
                for p in deal.payments:
                    take(deal.counterparty, p.date, p.amount, p.descriptor.rsplit(" ", 1)[-1])
            elif deal.kind == "sale_credit":
                take(deal.counterparty, deal.date, deal.gross)
            elif deal.kind == "bad_debt_relief":
                take(deal.counterparty, deal.date, sum((j.credit for j in deal.journal if j.account == "1100"), ZERO))
        else:
            if deal.kind == "purchase" and deal.settles_via == "creditor":
                doc = next(x for x in deal.docs if x.kind == "purchase_invoice")
                items.append(dict(counterparty=deal.counterparty, doc_id=doc.id, number=doc.number, date=deal.date,
                                  gross=deal.gross, moves=[(p.date, -p.amount) for p in deal.payments]))
            elif deal.kind == "creditor_payment":
                for p in deal.payments:
                    take(deal.counterparty, p.date, -p.amount)
    return items


def _write(key: Path, name: str, rows: list[list]):
    with open(key / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS[name])
        w.writerows(rows)


def _xlsx(path: Path, sheets: dict[str, list[list]]):
    write_xlsx(path, sheets)


def write_key(world, books: Books, adjustments, period: Period, client_dir: Path, delivered: dict[str, str],
              extra_docs: tuple[Doc, ...] = ()) -> Path:
    client = world.client
    chart = for_client(client.owners)
    key = client_dir / "key" / f"{period.end:%Y-%m-%d}"
    key.mkdir(parents=True, exist_ok=True)
    final = Books(books.entries + tuple(e for a in adjustments for e in a.entries))
    tables: dict[str, list[list]] = {}

    relied_on = {d for a in adjustments for d in a.deals}
    docs = []
    for deal in world.deals:
        for x in deal.docs + ((deal.query.answer_doc,) if deal.query and deal.query.answer_doc else ()):
            if x.date <= period.end or deal.id in relied_on:
                docs.append((x, deal.cases))
    docs += [(x, tuple(x.extra.get("cases", ()))) for x in extra_docs if x.date <= period.end]
    rows = []
    for x, cases in sorted(docs, key=lambda t: (t[0].date, t[0].id)):
        file = delivered[x.id]
        arrived = file.split("/")[1]
        rows.append([x.id, file, arrived, x.kind, x.issuer, x.recipient, x.number, x.date.isoformat(), x.currency,
                     *(fmt(x.printed[k]) if k in x.printed else "" for k in ("net", "vat", "gross")), x.treatment,
                     x.reason, _join(cases)])
    tables["documents"] = rows

    deal_of = {p.id: d for d in world.deals for p in d.payments}
    rows = []
    for acc in client.accounts:
        for ln in statement_lines(world, acc.id):
            if period.start <= ln.date <= period.end:
                d = deal_of[ln.id]
                rows.append([ln.id, acc.id, ln.date.isoformat(), ln.type_code, ln.description, fmt(ln.amount),
                             fmt(ln.balance), d.id, _join(d.cases)])
    tables["statement-lines"] = rows

    tables["entries"] = [[e.id, e.journal_id, e.date.isoformat(), e.account, chart[e.account].name, fmt(e.debit),
                          fmt(e.credit), e.vat_code, fmt(e.vat), e.counterparty, e.deal_id, _join(e.doc_ids),
                          _join(e.line_ids), e.stakes, _join(e.also_ok), e.phase, _join(e.cases)]
                         for e in final.entries]

    rows = []
    for acc in client.accounts:
        for me in _month_ends(period):
            r = bank_rec(world, books, acc.id, me)
            base = [acc.id, me.isoformat(), fmt(r.statement_balance), fmt(r.book_balance)]
            rows += [base + [i, fmt(a), note] for i, a, note in r.items] or [base + ["", "", ""]]
    tables["bank-recs"] = rows

    tables["vat-returns"] = [[r.start.isoformat(), r.end.isoformat(), fmt(r.box1), fmt(r.box2), fmt(r.box3),
                              fmt(r.box4), fmt(r.box5), r.box6, r.box7, r.box8, r.box9, r.due.isoformat(),
                              r.dd.isoformat()]
                             for r in world.vat_returns if period.start <= r.end <= period.end]

    for side, name in (("debtor", "debtors"), ("creditor", "creditors")):
        rows = []
        for me in _month_ends(period):
            for item in _open_items(world, side):
                if item["date"] > me:
                    continue
                paid = sum((a for d, a in item["moves"] if d <= me), ZERO)
                if item["gross"] - paid:
                    rows.append([me.isoformat(), item["counterparty"], item["doc_id"], item["number"],
                                 item["date"].isoformat(), fmt(item["gross"]), fmt(paid), fmt(item["gross"] - paid)])
        tables[name] = rows

    names = {e.id: e.name for e in client.employees}
    tables["payroll"] = [[r.pay_date.isoformat(), names[p.employee_id], fmt(p.gross), fmt(p.tax), fmt(p.ee_ni),
                          fmt(p.er_ni), fmt(p.ee_pension), fmt(p.er_pension), fmt(p.net),
                          fmt(r.ea_used if i == 0 else ZERO)]
                         for r in world.pay_runs if period.start <= r.pay_date <= period.end
                         for i, p in enumerate(r.payslips)]

    opening = final.balances(period.start, ("opening",))
    tables["opening-balances"] = [[c, chart[c].name, fmt(v) if v > 0 else "", fmt(-v) if v < 0 else "",
                                   "The previous accountant's trial balance"] for c, v in opening.items() if v]

    rows = []
    years = client.policies.depreciation_years
    depreciating = any(a.kind == "depreciation" for a in adjustments)   # none in a part year or a pack's month
    for a in client.opening.assets:
        before = years_charged(a.bought, period)
        dep = pennies(a.cost / years[a.cls]) if depreciating and before < years[a.cls] else ZERO
        acc_dep = pennies(a.cost / years[a.cls] * min(before, years[a.cls])) + dep
        rows.append([a.id, a.description, a.cls, a.bought.isoformat(), fmt(a.cost), fmt(dep), fmt(acc_dep),
                     fmt(a.cost - acc_dep)])
    for deal in world.deals:
        if period.start <= deal.date <= period.end:
            for ln in deal.lines:
                if ln.account in CAPITAL:
                    cls = CAPITAL[ln.account][0]
                    dep = pennies(ln.net / years[cls]) if depreciating else ZERO
                    rows.append([deal.id, ln.description, cls, deal.date.isoformat(), fmt(ln.net), fmt(dep), fmt(dep),
                                 fmt(ln.net - dep)])
    tables["fixed-assets"] = rows

    rows = []
    for o in client.owners:
        moves = [e for e in final.entries if e.account == o.loan_code and e.phase in ("books", "year_end")]
        start = -opening.get(o.loan_code, ZERO)
        up, down = sum((e.credit for e in moves), ZERO), sum((e.debit for e in moves), ZERO)
        rows.append([o.loan_code, o.name, fmt(start), fmt(up), fmt(down), fmt(start + up - down)])
    tables["owners"] = rows

    tables["year-end"] = [[a.id, a.kind, e.account, fmt(e.debit), fmt(e.credit), a.reason, _join(a.cases)]
                          for a in adjustments for e in a.entries]

    end_books = final.balances(period.end, ("opening", "books", "answers"))
    before = final.before_answers(period.end)
    ye = defaultdict(lambda: ZERO)
    for a in adjustments:
        for e in a.entries:
            ye[e.account] += e.debit - e.credit
    rows = []
    for code in sorted(set(opening) | set(end_books) | set(before) | set(ye)):
        o, b = opening.get(code, ZERO), end_books.get(code, ZERO)
        values = (o, b - o, before.get(code, ZERO), ye[code], b + ye[code])
        if any(values):
            rows.append([code, chart[code].name, CHART[code].heading, *map(fmt, values)])
    tables["trial-balance"] = rows

    rows = []
    for deal in world.deals:
        q = deal.query
        if q is None or not period.start <= deal.date <= period.end:
            continue
        if q.before:
            effect = ("Until the answer: " + "; ".join(
                f"{ln.account} {fmt(ln.net)}" + (f" (or {', '.join(ln.also_ok)})" if ln.also_ok else "")
                for ln in q.before)
                + ". After it, from the answer's date: " + "; ".join(
                f"{ln.account} {fmt(ln.net)} with VAT {fmt(ln.vat)} reclaimed" for ln in deal.lines))
        else:
            effect = "The figures don't change; the answer confirms them"
        rows.append([q.id, _join((deal.id,) + tuple(x.id for x in deal.docs)), q.question, q.why, q.stakes,
                     delivered.get(q.id, ""), q.answer_date.isoformat(), effect])
    tables["queries"] = rows

    charge = next((a for a in adjustments if a.kind == "ct_charge"), None)
    rows = []
    if charge is not None:
        w = charge.working
        rows.append(["Profit before tax", fmt(w.profit_before_tax)])
        rows += [[f"Add back: {code} {chart[code].name}", fmt(v)] for code, v in w.add_backs.items()]
        rows += [["Less capital allowances (full expensing)", fmt(-w.capital_allowances)],
                 ["Taxable profit", fmt(w.taxable)], ["Corporation tax", fmt(w.tax)]]
    tables["ct-working"] = rows
    tables["mess"] = []

    for name, rows in tables.items():
        _write(key, name, rows)
    _xlsx(key / "key.xlsx", {name: [COLUMNS[name]] + rows for name, rows in tables.items()})
    if not period.partial:
        acc = accounts(final, period, client.opening.prior_pl)
        _xlsx(key / "accounts.xlsx", {
            "Profit and loss": [["", f"Year to {period.end:%d %b %Y}", "Last year"]] +
                               [[h, float(v), float(last)] for h, v, last in acc.pl] +
                               [["Profit after tax", float(acc.profit_after_tax), ""]],
            "Balance sheet": [["", f"At {period.end:%d %b %Y}", "Last year"]] +
                             [[h, float(v), float(last)] for h, v, last in acc.bs]})
    return key
