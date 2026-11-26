"""The independent double-entry ledger: it posts the simulated deals the way a UK accountant would, and gives the
trial balance. Nothing here comes from the app."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from testbooks.engine.model import Deal, Line, Payment, Period
from testbooks.money import ZERO
from testbooks.rules.vat import reclaimable

# "answers" holds what the client's answers change, dated the day they answer, and the VAT sweep of it.
PHASES = ("opening", "books", "answers", "year_end")
AFTER = ("opening", "books", "answers")


@dataclass(frozen=True)
class Entry:
    id: str
    journal_id: str
    date: date
    account: str
    debit: Decimal
    credit: Decimal
    deal_id: str = ""
    doc_ids: tuple[str, ...] = ()
    line_ids: tuple[str, ...] = ()
    vat_code: str = ""
    vat: Decimal = ZERO
    counterparty: str = ""
    stakes: str = ""
    also_ok: tuple[str, ...] = ()
    phase: str = "books"
    cases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Books:
    entries: tuple[Entry, ...]

    def balances(self, as_at: date, phases=AFTER) -> dict[str, Decimal]:
        """Each account's balance (debit positive) from the entries of these phases dated up to `as_at`."""
        out: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for e in self.entries:
            if e.phase in phases and e.date <= as_at:
                out[e.account] += e.debit - e.credit
        return dict(sorted(out.items()))

    def balance(self, code: str, as_at: date, phases=AFTER) -> Decimal:
        return self.balances(as_at, phases).get(code, ZERO)

    def before_answers(self, as_at: date) -> dict[str, Decimal]:
        """The balances an accountant has if the client never answers: what the answers change, and the VAT
        sweep of it, left out."""
        return self.balances(as_at, ("opening", "books"))


class _Poster:
    def __init__(self, world):
        self.world = world
        self.client = world.client
        self.money = {a.id: a.code for a in self.client.accounts}
        self.loans = {o.name: o.loan_code for o in self.client.owners}
        self.rows: list[dict] = []

    def add(self, journal_id: str, on: date, account: str, amount: Decimal, *, phase: str = "books",
            deal: Deal | None = None, line: Line | None = None, payment: Payment | None = None, **extra):
        """Post `amount` to `account`: positive is a debit, negative a credit."""
        if not amount:
            return
        row = dict(journal_id=journal_id, date=on, account=account,
                   debit=amount if amount > 0 else ZERO, credit=-amount if amount < 0 else ZERO, phase=phase)
        if deal is not None:
            row.update(deal_id=deal.id, doc_ids=tuple(d.id for d in deal.docs), counterparty=deal.counterparty,
                       cases=deal.cases,
                       line_ids=tuple(p.id for p in deal.payments) if payment is None else (payment.id,))
        if line is not None:
            row.update(vat_code=line.vat_code, vat=line.vat, stakes=line.stakes, also_ok=line.also_ok)
        row.update(extra)
        self.rows.append(row)

    def post_lines(self, deal: Deal, lines, contra: str, phase: str, sign: int = 1):
        """A purchase-shaped posting: each line's cost (with VAT it can't reclaim) and reclaimable VAT, a reverse
        charge's output VAT, and the total against `contra`. `sign` -1 posts it the other way round."""
        total = ZERO
        for ln in lines:
            back = reclaimable(ln)
            self.add(deal.id, deal.date, ln.account, sign * (ln.net + ln.vat - back if ln.vat_code != "reverse_charge"
                                                            else ln.net), phase=phase, deal=deal, line=ln)
            if back:
                self.add(deal.id, deal.date, "2201", sign * back, phase=phase, deal=deal, line=ln)
            if ln.vat_code == "reverse_charge" and ln.vat:
                self.add(deal.id, deal.date, "2200", -sign * ln.vat, phase=phase, deal=deal, line=ln)
            total += ln.gross
        self.add(deal.id, deal.date, contra, -sign * total, phase=phase, deal=deal)

    def post_sale(self, deal: Deal, lines, phase: str, sign: int = 1):
        total = ZERO
        for ln in lines:
            self.add(deal.id, deal.date, ln.account, -sign * ln.net, phase=phase, deal=deal, line=ln)
            if ln.vat_code in ("standard", "reduced") and ln.vat:
                self.add(deal.id, deal.date, "2200", -sign * ln.vat, phase=phase, deal=deal, line=ln)
            total += ln.gross
        return total

    def post_deal(self, deal: Deal, lines, phase: str):
        via = deal.settles_via
        if via == "debtor":
            sign = -1 if deal.kind == "sale_credit" else 1
            total = self.post_sale(deal, lines, phase, sign)
            self.add(deal.id, deal.date, "1100", sign * total, phase=phase, deal=deal)
        elif via == "creditor":
            self.post_lines(deal, lines, "2100", phase, -1 if deal.kind == "purchase_credit" else 1)
        elif via == "director_loan":
            self.post_lines(deal, lines, self.loans[deal.counterparty], phase)
        elif via == "bank":
            account = self.money[deal.payments[0].account]
            if sum(p.amount for p in deal.payments) > 0:
                total = self.post_sale(deal, lines, phase)
                self.add(deal.id, deal.date, account, total, phase=phase, deal=deal)
            else:
                self.post_lines(deal, lines, account, phase)
        elif via == "journal" and phase == "books":
            for j in deal.journal:
                self.add(deal.id, deal.date, j.account, j.debit - j.credit, deal=deal, stakes="accounts")

    def post_answer(self, deal: Deal):
        """What the client's answer changes: the booking after it less the booking before it, dated the answer."""
        query, scratch = deal.query, _Poster(self.world)
        scratch.post_deal(deal, deal.lines, "after")
        scratch.post_deal(deal, query.before, "before")
        net: dict[str, Decimal] = defaultdict(lambda: ZERO)
        meta: dict[str, dict] = {}
        for r in scratch.rows:
            net[r["account"]] += (1 if r["phase"] == "after" else -1) * (r["debit"] - r["credit"])
            if r["phase"] == "after":
                meta.setdefault(r["account"], r)
        for account, amount in sorted(net.items()):
            m = meta.get(account, {})
            self.add(f"ANSWER-{deal.id}", query.answer_date, account, amount, phase="answers", deal=deal,
                     vat_code=m.get("vat_code", ""), vat=m.get("vat", ZERO), stakes=m.get("stakes", "accounts"),
                     also_ok=m.get("also_ok", ()))

    def post_payments(self, deal: Deal):
        if deal.settles_via == "bank":
            return
        for p in deal.payments:
            money = self.money[p.account]
            if deal.settles_via == "transfer":
                other = "1290"
            elif deal.settles_via == "debtor":
                other = "1100"
            elif deal.settles_via == "creditor":
                other = "2100"
            elif deal.settles_via == "director_loan":
                other = self.loans[deal.counterparty]
            else:
                other = p.against
            jid = f"{deal.id}/{p.id}"
            self.add(jid, p.date, money, p.amount, deal=deal, payment=p)
            self.add(jid, p.date, other, -p.amount, deal=deal, payment=p)


def post(world, period: Period) -> Books:
    client, poster = world.client, _Poster(world)
    if period == client.periods[0]:
        for code, amount in sorted(client.opening.balances.items()):
            poster.add("OPENING", period.start, code, amount, phase="opening")
        for n, (sheet, pl, amount) in enumerate(client.opening.reversals, 1):
            sign = -1 if sheet == "1103" else 1          # a prepayment is used up; an accrual is released
            poster.add(f"REVERSAL-{n}", period.start, pl, -sign * amount)
            poster.add(f"REVERSAL-{n}", period.start, sheet, sign * amount)
    for deal in world.deals:
        if deal.query is not None and deal.query.before is not None:
            poster.post_deal(deal, deal.query.before, "books")     # what is booked until the answer comes
            poster.post_answer(deal)
        else:
            poster.post_deal(deal, deal.lines, "books")
        poster.post_payments(deal)
    rows = [r for r in poster.rows if period.start <= r["date"] <= period.end]
    for r in sorted(world.vat_returns, key=lambda r: r.end):
        if not period.start <= r.end <= period.end:
            continue
        for code in ("2200", "2201"):
            # The answers' VAT is swept apart, so leaving the answers out also leaves out their sweep.
            for phase, phases, jid in (("books", ("opening", "books"), f"VAT-{r.end}"),
                                       ("answers", ("answers",), f"VAT-{r.end}-ANSWERS")):
                held = sum((x["debit"] - x["credit"] for x in rows
                            if x["account"] == code and x["phase"] in phases and x["date"] <= r.end), ZERO)
                if held:
                    rows.append(dict(journal_id=jid, date=r.end, account=code, debit=-held if held < 0 else ZERO,
                                     credit=held if held > 0 else ZERO, phase=phase))
                    rows.append(dict(journal_id=jid, date=r.end, account="2202", debit=held if held > 0 else ZERO,
                                     credit=-held if held < 0 else ZERO, phase=phase))
    order = {p: i for i, p in enumerate(PHASES)}
    rows.sort(key=lambda r: (r["date"], order[r["phase"]], r["journal_id"]))
    entries = tuple(Entry(id=f"E{n:05d}", **r) for n, r in enumerate(rows, 1))
    return Books(entries)
