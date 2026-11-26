from collections import defaultdict
from decimal import Decimal as D

from testbooks.books.accounts import accounts
from testbooks.books.ledger import Books
from testbooks.books.year_end import ct_tax, year_end
from testbooks.tests.test_ledger import B, P, W

ADJ = year_end(W, B, P)


def amount(case, kind):
    return sum(e.debit for a in ADJ if a.kind == kind and case in a.cases for e in a.entries)


def test_ct_tax():
    assert ct_tax(D("80000"), 12) == D("17450.00")
    assert ct_tax(D("40000"), 12) == D("7600.00")
    assert ct_tax(D("300000"), 12) == D("75000.00")
    assert ct_tax(D("40000"), 5) == D("9037.50")


def test_agency_adjustments():
    assert amount("EC-0225", "prepayment") == D("1203.93")
    assert amount("EC-0352", "prepayment") == D("5538.46")
    assert amount("EC-0314", "prepayment") == D("1092.00")
    assert amount("EC-0502", "deferred_income") == D("12700.00")
    assert amount("EC-0506", "accrual") == D("3000.00")
    dep = defaultdict(D)
    for a in ADJ:
        if a.kind == "depreciation":
            for e in a.entries:
                dep[e.account] += e.credit
    assert dep["0031"] == D("3560.83") and dep["0041"] == D("1074.00")
    prior = next(a for a in ADJ if a.kind == "ct_prior_year")
    assert {(e.account, e.debit, e.credit) for e in prior.entries} == {("2320", D("223.00"), D("0")),
                                                                       ("9100", D("0"), D("223.00"))}


def test_electricity_accrual_is_the_april_bill():
    bill = next(d for d in W.deals if "EC-0505" in d.cases)
    assert amount("EC-0505", "accrual") == bill.lines[0].net


def test_ct_charge_follows_its_working():
    charge = next(a for a in ADJ if a.kind == "ct_charge")
    w = charge.working
    assert w.taxable == w.profit_before_tax + sum(w.add_backs.values()) - w.capital_allowances
    assert w.capital_allowances == D("1602.50") and w.tax == ct_tax(w.taxable, 12)
    assert {(e.account, e.debit, e.credit) for e in charge.entries} == {("9100", w.tax, D("0")),
                                                                        ("2320", D("0"), w.tax)}


def test_accounts_balance_and_reserves_roll():
    final = Books(B.entries + tuple(e for a in ADJ for e in a.entries))
    acc = accounts(final, P, W.client.opening.prior_pl)
    bs = dict((h, v) for h, v, _ in acc.bs)
    assert sum(final.balances(P.end, ("opening", "books", "year_end")).values()) == 0
    closing_reserves = D("32240.96") + acc.profit_after_tax - D("32000.00")
    assert bs["Capital and reserves"] == closing_reserves + D("100.00")
    assert bs["Net assets"] == bs["Capital and reserves"]
