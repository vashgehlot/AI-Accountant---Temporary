import calendar
from datetime import date
from decimal import Decimal as D

from testbooks.books.bank import bank_rec
from testbooks.books.ledger import post
from testbooks.clients import agency
from testbooks.engine.simulate import simulate

W = simulate(agency.define(), until=date(2024, 6, 30), seed=7)
P = W.client.periods[0]
B = post(W, P)


def rows(case, on=None):
    return {(e.account, e.debit, e.credit) for e in B.entries
            if case in e.cases and (on is None or e.date == on) and e.phase == "books"}


def test_trial_balance_balances():
    assert sum(B.balances(P.end, ("opening", "books")).values()) == 0


def test_planted_postings():
    assert rows("EC-0334", date(2023, 5, 1)) == {("7410", D("462.00"), D("0")), ("2201", D("42.00"), D("0")),
                                                 ("2100", D("0"), D("504.00"))}
    assert rows("EC-0210") == {("4000", D("600.00"), D("0")), ("2200", D("120.00"), D("0")),
                               ("1100", D("0"), D("720.00"))}
    assert rows("EC-0512") == {("8250", D("312.00"), D("0")), ("2202", D("0"), D("312.00"))}


def test_signs_and_transit():
    assert B.balance("1240", P.end) < 0                  # the card is owed
    assert B.balance("1290", P.end) == 0                 # no transfer in transit at 31 Mar 2024
    assert B.balance("1250", P.end) > 0                  # Stripe charges awaiting the 2 Apr payout


def test_bank_recs_tie_every_month():
    months = [(2023, m) for m in range(4, 13)] + [(2024, m) for m in range(1, 4)]
    for acc in ("hsbc", "savings", "amex", "stripe"):
        for y, m in months:
            month_end = date(y, m, calendar.monthrange(y, m)[1])
            r = bank_rec(W, B, acc, month_end)
            assert r.statement_balance - r.book_balance == sum(a for _, a, _ in r.items), (acc, month_end)


def test_opening_reversals():
    rev = {(e.account, e.debit, e.credit) for e in B.entries if e.date == P.start and e.phase == "books"}
    assert ("7100", D("5538.46"), D("0")) in rev and ("2109", D("2400.00"), D("0")) in rev


def test_vat_moves_agree_with_the_returns():
    for r in W.vat_returns:
        if P.start <= r.end <= P.end:
            moved = sum(e.credit - e.debit for e in B.entries if e.journal_id == f"VAT-{r.end}" and e.account == "2202")
            assert moved == r.box5, r.end


def test_before_answers_differs_only_by_the_queried_deal():
    """Until the full invoice comes the chairs' VAT is held in Suspense; the answer moves it to VAT on purchases."""
    before, after = B.before_answers(P.end), B.balances(P.end)
    assert before["9998"] == D("53.33") and after.get("9998", D("0")) == 0
    assert after["2201"] - before["2201"] == D("53.33") and before["7504"] == after["7504"]
