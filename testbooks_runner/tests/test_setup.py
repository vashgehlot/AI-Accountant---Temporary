import shutil
from datetime import date
from pathlib import Path

import pytest

from testbooks_runner import books, mapping, setup
from testbooks_runner.model import Period
from testbooks_runner.tests.helpers import write_mini_client

FIX = Path(__file__).parent / "fixtures" / "set"


@pytest.fixture
def mini(tmp_path):
    shutil.copytree(FIX, tmp_path / "set")
    return write_mini_client(tmp_path / "set")


@pytest.fixture
def profile(mini):
    return books.load_profile(mini)


@pytest.fixture
def key(mini):
    return books.load_key(mini / "key" / "2024-03-31")


def test_client_fields_for_a_limited_company(profile):
    f = setup.client_fields(profile, Period(date(2023, 4, 1), date(2024, 3, 31)), "automatic")
    assert f["business_type"] == "limited_company" and f["first_year_end"] == "2024-03-31" and f["vat_registered"]
    assert [(a["name"], a["kind"]) for a in f["bank_accounts"]] == [
        ("Business current", "current"), ("Business card", "credit_card")]
    assert f["owners"] == [{"name": "Ann Mini", "share": "100"}] and f["ai_review"] == "automatic"
    assert f["contact_name"] == "Ann Mini" and f["name"] == "Mini Widgets Ltd"
    assert all(a["code"] == "" for a in f["bank_accounts"])


def test_sole_trader_sends_no_owners_and_partnership_shares_are_percents():
    period = Period(date(2023, 4, 1), date(2024, 3, 31))
    sole = {"kind": "sole_trader", "name": "Grace Adeyemi", "owners": [{"name": "Grace Adeyemi", "share": "1"}]}
    f = setup.client_fields(sole, period, "off")
    assert f["owners"] == [] and f["business_type"] == "sole_trader" and f["contact_name"] == "Grace Adeyemi"
    assert not f["vat_registered"]
    part = {"kind": "partnership", "name": "Bell and Fox",
            "owners": [{"name": "A Bell", "share": "0.5"}, {"name": "B Fox", "share": "0.5"}]}
    assert setup.client_fields(part, period, "off")["owners"] == [
        {"name": "A Bell", "share": "50"}, {"name": "B Fox", "share": "50"}]


def test_pack_business_type_from_its_name():
    assert setup.business_type({"kind": "pack", "name": "Fernbrook Consulting Ltd"}) == "limited_company"
    assert setup.business_type({"kind": "pack", "name": "Ashgrove Studio LLP"}) == "llp"
    with pytest.raises(setup.SetupError):
        setup.business_type({"kind": "pack", "name": "Grace Adeyemi"})


def test_bank_kind_ranges():
    assert [setup.bank_kind(c) for c in ("1200", "1209", "1210", "1219", "1230", "1239", "1240", "1249")] == [
        "current", "current", "savings", "savings", "petty_cash", "petty_cash", "credit_card", "credit_card"]
    assert [setup.bank_kind(c) for c in ("1250", "1220", "1100", "2100")] == [None] * 4


def test_statement_account_from_the_document_id(profile):
    assert setup.statement_account("amex-statement-20230304-20230403", profile) == "amex"
    assert setup.statement_account("MN-D0002", profile) is None


def test_bank_codes_from_the_created_client(profile):
    client = {"bank_accounts": [{"code": "1200", "name": "Business current"},
                                {"code": "1240", "name": "Business card"}]}
    assert setup.bank_codes(profile, client) == {"hsbc": "1200", "amex": "1240"}


def test_opening_lines_go_to_app_codes(key):
    opening, _ = setup.opening_balances(key, mapping.load_chart())
    assert {l["code"] for l in opening["lines"]} >= {"1100", "1200", "2100", "3200"}
    by_code = {l["code"]: l for l in opening["lines"]}
    assert by_code["1100"] == {"code": "1100", "debit": "1000.00", "credit": "0.00"}
    assert by_code["2100"] == {"code": "2100", "debit": "0.00", "credit": "300.00"}
    assert len(opening["unpaid"]) == 3


def test_opening_items_named_first_then_from_first_payments(key):
    items, warnings = setup.opening_items(key)
    assert [(i["counterparty"], i["amount"], i["number"]) for i in items] == [
        ("Calder", "400.00", "INV-1"), ("Brightwater", "600.00", None), ("Cabot", "300.00", None)]
    assert [(i["id"], i["direction"]) for i in items] == [
        ("open-1", "in"), ("open-2", "in"), ("open-3", "out")]
    assert items[0]["date"] == "2023-03-20" and items[1]["date"] is None
    assert warnings == []


def test_opening_items_warn_when_payments_dont_reach_the_total(key):
    key.opening[0]["debit"] = "1500.00"   # 1100 now 1500, payments only reach 1000
    items, warnings = setup.opening_items(key)
    assert any("1100" in w for w in warnings) and [i["counterparty"] for i in items if i["direction"] == "in"] == ["Calder"]


def test_the_capitalisation_threshold_is_sent_when_the_policies_give_one(profile):
    period = Period(date(2023, 4, 1), date(2024, 3, 31))
    assert "capitalise_from" not in setup.client_fields(profile, period, "off")
    with_policy = {**profile, "policies": {"capitalise_from": "500"}}
    assert setup.client_fields(with_policy, period, "off")["capitalise_from"] == "500"
