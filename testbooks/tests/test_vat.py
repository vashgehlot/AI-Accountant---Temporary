from datetime import date
from decimal import Decimal as D

from testbooks.engine.model import Deal, Line, VatTotals
from testbooks.rules.vat import quarter_ends, vat_return


def mk(i, kind, d, net, vat, code, account, via):
    return Deal(id=i, kind=kind, date=d, counterparty="X", settles_via=via,
                lines=(Line("x", account, D(net), code, D(vat)),))


def test_boxes_for_a_quarter():
    deals = [mk("s1", "sale", date(2023, 6, 1), "1000.00", "200.00", "standard", "4010", "debtor"),
             mk("c1", "sale_credit", date(2023, 6, 9), "600.00", "120.00", "standard", "4000", "debtor"),
             mk("p1", "purchase", date(2023, 6, 2), "500.00", "100.00", "standard", "7500", "creditor"),
             mk("p2", "purchase", date(2023, 6, 3), "250.00", "50.00", "reverse_charge", "7550", "bank"),
             mk("p3", "purchase", date(2023, 6, 4), "155.00", "31.00", "blocked", "7403", "bank"),
             mk("p4", "purchase", date(2023, 6, 5), "420.00", "84.00", "blocked_half", "7410", "creditor"),
             mk("p5", "purchase", date(2023, 6, 6), "1950.00", "0.00", "exempt", "8204", "creditor"),
             mk("p6", "purchase", date(2023, 6, 7), "999.00", "0.00", "outside", "7000", "journal"),
             mk("s2", "sale", date(2023, 9, 1), "5000.00", "1000.00", "standard", "4010", "debtor")]
    r = vat_return(deals, date(2023, 6, 1), date(2023, 8, 31))
    assert (r.box1, r.box2, r.box3) == (D("130.00"), D("0.00"), D("130.00"))   # 200 - 120 credit + 50 RC
    assert r.box4 == D("192.00")                                               # 100 + 50 RC + 0 + 42
    assert r.box5 == D("-62.00")
    assert (r.box6, r.box7, r.box8, r.box9) == (650, 3275, 0, 0)               # 1000 - 600 + 250 RC; 500+250+155+420+1950
    assert (r.due, r.dd) == (date(2023, 10, 7), date(2023, 10, 11))


def test_brought_in_and_bad_debt_relief():
    bdr = Deal(id="b1", kind="bad_debt_relief", date=date(2024, 1, 31), counterparty="Lowther",
               settles_via="journal", vat_boxes={4: D("800.00")})
    rec = Deal(id="b2", kind="bad_debt_recovery", date=date(2024, 3, 20), counterparty="Lowther",
               settles_via="journal", vat_boxes={1: D("200.00")})
    assert vat_return([bdr, rec], date(2023, 12, 1), date(2024, 2, 29)).box4 == D("800.00")
    assert vat_return([bdr, rec], date(2024, 3, 1), date(2024, 5, 31)).box1 == D("200.00")
    bi = VatTotals(D("10560.00"), D("1980.00"), D("52800.00"), D("9900.00"))
    r0 = vat_return([], date(2023, 3, 1), date(2023, 5, 31), brought_in=bi)
    assert (r0.box1, r0.box4, r0.box6, r0.box7) == (D("10560.00"), D("1980.00"), 52800, 9900)


def test_quarters_feb_may_aug_nov():
    q = quarter_ends((2, 5, 8, 11), date(2023, 3, 1), date(2024, 5, 31))
    assert q[0] == (date(2023, 3, 1), date(2023, 5, 31)) and q[-1] == (date(2024, 3, 1), date(2024, 5, 31))
    assert (date(2023, 12, 1), date(2024, 2, 29)) in q


def test_deposit_interest_is_an_exempt_supply_in_box_6():
    # A business's deposit interest is an exempt supply: in box 6, no VAT (VAT Notice 700/12). The key left it out,
    # coded outside the scope (key audit, 25 Nov 2026).
    deals = [mk("i1", "interest", date(2023, 6, 30), "93.49", "0.00", "exempt", "4906", "bank")]
    r = vat_return(deals, date(2023, 6, 1), date(2023, 8, 31))
    assert (r.box1, r.box6) == (D("0.00"), 93)

