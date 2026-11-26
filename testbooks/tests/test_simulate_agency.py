from datetime import date
from decimal import Decimal as D

from testbooks.clients import agency
from testbooks.engine.simulate import simulate

UNTIL = date(2024, 6, 30)


def world(seed=7):
    return simulate(agency.define(), until=UNTIL, seed=seed)


def test_deterministic_and_planted():
    a, b = world(), world()
    assert a.deals == b.deals
    planted_on_deals = set(agency.STEP1_CASES) - set(agency.STEP1_OUTSIDE_DEALS)
    assert planted_on_deals <= {c for d in a.deals for c in d.cases}


def test_every_deal_adds_up_and_ids_are_unique():
    w = world()
    for d in w.deals:
        if d.settles_via == "bank":
            assert abs(sum(p.amount for p in d.payments)) == d.gross, d.id
        for doc in d.docs:
            if d.lines and doc.currency == "GBP" and "gross" in doc.printed and doc.treatment == "book":
                assert doc.printed["gross"] == d.gross, doc.id
    for ids in ([d.id for d in w.deals], [x.id for d in w.deals for x in d.docs],
                [p.id for d in w.deals for p in d.payments]):
        assert len(ids) == len(set(ids))


def test_tax_payments():
    w = world()
    vat = {p.date: -p.amount for d in w.deals if d.kind == "vat_payment" for p in d.payments}
    assert vat[date(2023, 4, 13)] == D("27412.00")
    for r in w.vat_returns:
        if r.dd <= UNTIL:
            assert vat[r.dd] == r.box5
    ct = next(d for d in w.deals if d.kind == "ct_payment")
    assert (ct.payments[0].date, ct.payments[0].amount) == (date(2023, 12, 29), D("-13987.00"))
    assert next(r for r in w.pay_runs if r.pay_date.year == 2024 and r.pay_date.month == 3).pay_date == date(2024, 3, 28)
    assert any(d.date == date(2024, 2, 29) for d in w.deals)


def test_payroll_payments_match_the_runs():
    w = world()
    paye = {p.date: -p.amount for d in w.deals if d.kind == "paye_payment" for p in d.payments}
    from testbooks.dates import paye_due
    for run in w.pay_runs:
        if paye_due(run.pay_date) <= UNTIL:
            assert paye[paye_due(run.pay_date)] == run.paye


def test_deposit_interest_is_exempt_and_in_box_6():
    # Key audit, 25 Nov 2026: interest was coded outside the scope, so box 6 left out £357.45 in the year.
    w = world()
    interest = [ln for d in w.deals if d.kind == "interest" for ln in d.lines]
    assert interest and {ln.vat_code for ln in interest} == {"exempt"}
    june = next(r for r in w.vat_returns if r.start == date(2023, 6, 1))
    sales = sum(ln.net for d in w.deals if d.kind == "sale" and date(2023, 6, 1) <= d.date <= date(2023, 8, 31)
                for ln in d.lines)
    rc = sum(ln.net for d in w.deals if date(2023, 6, 1) <= d.date <= date(2023, 8, 31) for ln in d.lines
             if ln.vat_code == "reverse_charge")
    paid = sum(ln.net for d in w.deals if d.kind == "interest" and date(2023, 6, 1) <= d.date <= date(2023, 8, 31)
               for ln in d.lines)
    assert paid > 0 and june.box6 == int(sales + rc + paid)


def test_a_card_line_names_the_town_on_its_receipt():
    # Key audit, 25 Nov 2026: receipts printed Reading or Cardiff while every card line said BRISTOL, so a meal on a
    # journey read as a lunch by the office.
    from testbooks.places import TOWNS, card_town
    KNOWN_TOWNS = {t.split(",")[0].split()[0].upper() for towns in TOWNS.values() for t, _ in towns}
    w = world()
    # A foreign-currency payment prints the currency and amount where the town would be (Tallgrass, in dollars).
    cards = [d for d in w.deals if d.kind == "card_spend" and d.docs and d.payments and d.docs[0].currency == "GBP"]
    assert cards
    for d in cards:
        town = card_town(d.docs[0].issuer, d.docs[0].extra.get("country"))
        # An online shop prints no town ("SHELFWISE ONLINE"); any town a line does print is the receipt's.
        named = (set(d.payments[0].descriptor.split()) - set(d.counterparty.upper().split())) & (KNOWN_TOWNS | {"LONDON"})
        assert named <= {town}, (d.counterparty, d.payments[0].descriptor, town)
    assert any(card_town(d.docs[0].issuer) in d.payments[0].descriptor for d in cards if d.counterparty == "Gantry Deli")


def test_groceries_on_the_company_card_go_to_the_directors_loan():
    # EC-0601 is a streaming subscription and groceries on the company card; only the subscription was made.
    w = world()
    shops = [d for d in w.deals if "EC-0601" in d.cases and d.counterparty != "Streamflix"]
    assert shops and all(ln.account == "2250" for d in shops for ln in d.lines)
    assert all(d.docs and d.docs[0].kind == "receipt" for d in shops)
    assert any(d.query is not None for d in shops)
