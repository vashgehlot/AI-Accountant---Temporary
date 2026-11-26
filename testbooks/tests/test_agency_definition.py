from datetime import date
from decimal import Decimal as D

from testbooks.clients import agency
from testbooks.ids import vat_number_valid


def test_agency_definition():
    c = agency.define()
    assert c.name == "Kestrel & Finch Digital Ltd" and c.kind == "ltd" and vat_number_valid(c.vat_number)
    assert [p.end for p in c.periods] == [date(2024, 3, 31), date(2025, 3, 31), date(2026, 3, 31), date(2026, 10, 31)]
    assert c.periods[-1].partial and c.vat_stagger == (2, 5, 8, 11)
    assert {a.id: a.code for a in c.accounts} == {"hsbc": "1200", "savings": "1210", "amex": "1240", "stripe": "1250"}
    assert sum(c.opening.balances.values()) == 0
    assert c.opening.balances["2202"] == D("-27100.00") and c.opening.true_differences == {"2202": D("-312.00")}
    assert c.opening.balances["2320"] == D("-14210.00") and c.opening.balances["3200"] == D("-32240.96")
    assert c.policies.capitalise_from == D("500") and c.policies.accrue_from == D("250")
    assert c.policies.depreciation_years == {"computer": 3, "furniture": 5}


def test_open_items_and_assets_agree_with_the_balances():
    o = agency.define().opening
    assert sum(i.gross for i in o.open_items if i.kind == "debtor") == o.balances["1100"]
    assert sum(i.gross for i in o.open_items if i.kind == "creditor") == -o.balances["2100"]
    assert sum(a.cost for a in o.assets if a.cls == "computer") == o.balances["0030"]
    assert sum(a.cost for a in o.assets if a.cls == "furniture") == o.balances["0040"]
    assert sum(amount for acc, _, amount in o.reversals if acc == "1103") == o.balances["1103"]
