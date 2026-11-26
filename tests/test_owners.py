"""A client's directors, partners and LLP members, each with accounts of their own."""
from datetime import date
from decimal import Decimal as D

import pytest
from helpers import add_rows, only_issue, row

from ledgersync import books, ledger
from ledgersync.accounts import (BY_CODE, DIRECTORS_LOANS, Heading, choosable, owner_code, owner_codes,
                                 profit_split)
from ledgersync.adapter import to_transactions
from ledgersync.checks import normalise
from ledgersync.errors import InvalidInput
from ledgersync.models import BusinessSettings, ClientFields, ClientPatch, Owner

YEAR_1, YEAR_2 = date(2025, 4, 1), date(2026, 4, 1)


def fields(kind="partnership", owners=(), **more) -> ClientFields:
    return ClientFields(name="Lee & Shah", business_type=kind, contact_name="Ann Lee", first_year_end=date(2026, 3, 31),
                        owners=[Owner(**o) for o in owners], **more)


def test_each_owner_has_accounts_of_their_own_by_slot():
    assert owner_code("limited_company", "drawings", (2,)) == "2252"
    assert owner_code("partnership", "capital", (1,)) == "3011" and owner_code("partnership", "profit", (3,)) == "3103"
    assert owner_code("llp", "drawings", (1,)) == owner_code("llp", "profit", (1,)) == "2261"
    assert owner_codes("sole_trader") == {"3010", "3100", "3260"}
    assert all(BY_CODE[c].heading == Heading.MEMBERS_DEBT for c in ("2260", "2261", "2262", "2263"))
    assert set(DIRECTORS_LOANS) <= set(BY_CODE)


def test_only_the_listed_owners_accounts_are_offered_named_after_them():
    offered = {a.code: a for a in choosable("partnership", owners=((0, "Ann Lee"), (2, "Raj Shah")))}
    assert {"3010", "3012", "3260", "3262"} <= set(offered) and not {"3011", "3261", "3013"} & set(offered)
    assert offered["3262"].name == "Drawings — Raj Shah"
    assert offered["3262"].definition.startswith("Raj Shah's: Money the owner takes out")
    company = {a.code for a in choosable("limited_company", owners=((0, "A"), (1, "B")))}
    assert {"2250", "2251"} <= company and not {"2252", "2253"} & company


def test_profit_is_split_by_share_the_pennies_to_the_first():
    profit = D("-1000.01")   # a credit: a profit
    assert profit_split("partnership", ((0, D(60)), (2, D(40))), profit) == {"3100": D("-600.01"), "3102": D("-400.00")}
    assert profit_split("llp", ((1, D(50)), (0, D(50))), D("100.00")) == {"2261": D("50.00"), "2260": D("50.00")}
    # No shares given: equal shares (Partnership Act 1890 s.24). No owners listed: all to the first owner's.
    assert profit_split("partnership", ((0, None), (1, None), (2, None)), D("-90.00")) == {
        "3100": D("-30.00"), "3101": D("-30.00"), "3102": D("-30.00")}
    assert profit_split("partnership", (), D("-5")) == {"3100": D("-5")}
    assert profit_split("limited_company", ((0, None), (1, None)), D("-5")) == {"3200": D("-5")}


@pytest.mark.parametrize("kind, owners, message", [
    ("sole_trader", [{"name": "Ann"}], "A sole trader has no"),
    ("partnership", [{"name": "Ann"}, {"name": "ann"}], "Two partners are called ann"),
    ("llp", [{"name": ""}], "Name each member"),
    ("partnership", [{"name": "Ann", "share": 60}, {"name": "Raj"}], "Give each partner's share"),
    ("llp", [{"name": "Ann", "share": 60}, {"name": "Raj", "share": 30}], "add up to 90%: make them 100%"),
    ("limited_company", [{"name": n} for n in "ABCDE"], "up to 4 directors"),
])
def test_owners_are_checked(kind, owners, message):
    with pytest.raises(InvalidInput, match=message):
        ledger.check_client(fields(kind, owners))


def test_owners_are_given_the_next_free_slot_and_keep_theirs():
    slotted = ledger.assign_owners([Owner(name="A", slot=1), Owner(name="B"), Owner(name="C")], [])
    assert [o.slot for o in slotted] == [1, 0, 2]
    with pytest.raises(InvalidInput, match="A's accounts have transactions"):
        ledger.assign_owners([Owner(name="B", slot=0)], [Owner(name="A", slot=1)])


def test_personal_spending_goes_to_the_first_owner_and_asks_whose_it_is_when_there_are_several():
    settings = BusinessSettings(business_name="Lee & Shah", business_type="partnership", owners=(1, 0))
    [tax] = to_transactions([{"date": "2026-01-31", "description": "HMRC SELF ASSESSMENT 1234567890K",
                              "counterparty": "HMRC", "amount": -850.0, "account": "9998 Suspense",
                              "document_type": "statement"}], source="table", settings=settings)
    assert tax.account_code == "3261"   # the first listed partner's drawings
    assert "several" not in only_issue(normalise(tax, settings), "whose_account").message
    assert "2 partners" in only_issue(normalise(tax, settings), "whose_account").message
    # A person's own choice isn't questioned, nor a business with one owner.
    assert "whose_account" not in [i.code for i in normalise(tax.model_copy(update={"method": "user"}), settings).issues]
    one = settings.model_copy(update={"owners": (0,)})
    assert "whose_account" not in [i.code for i in normalise(tax.model_copy(update={"account_code": "3260"}), one).issues]


@pytest.mark.mongo
def test_a_partnerships_profit_closes_to_each_partner_by_share(mongo_store):
    client = ledger.add_client(mongo_store, fields("partnership", [{"name": "Ann Lee", "share": 75},
                                                                   {"name": "Raj Shah", "share": 25}]))
    assert [(o.slot, o.name) for o in client.owners] == [(0, "Ann Lee"), (1, "Raj Shah")]
    add_rows(mongo_store, client.id, row(date=date(2025, 6, 1), direction="in", gross=D("1000.00"), vat=D("0.00"),
                                         account_code="4000", counterparty="Bright Cafe"),
             row(date=date(2025, 7, 1), gross=D("200.00"), account_code="3261", description="Raj's drawings"))
    books.close(mongo_store, client.id, YEAR_1)
    tb = books.trial_balance(mongo_store, client.id, YEAR_2)
    opening = {line.code: line.debit - line.credit for line in tb.opening}
    assert (opening["3100"], opening["3101"], opening["3261"]) == (D("-750.00"), D("-250.00"), D("200.00"))
    names = {line.code: line.name for line in tb.opening}
    assert (names["3100"], names["3261"]) == ("Owner's Capital Account — Ann Lee", "Drawings — Raj Shah")
    # Raj's accounts have rows on them, so he can't be dropped.
    with pytest.raises(InvalidInput, match="Raj Shah's accounts have transactions"):
        ledger.change_client(mongo_store, client.id,
                             ClientPatch(owners=[client.owners[0].model_copy(update={"share": D(100)})]))
    # Ann's shares stay; a third partner gets the next slot.
    changed = ledger.change_client(mongo_store, client.id, ClientPatch(owners=[
        *(o.model_copy(update={"share": D(40)}) for o in client.owners), Owner(name="Tom Ray", share=D(20))]))
    assert [(o.slot, o.name, o.share) for o in mongo_store.get_client(client.id).owners] == [
        (0, "Ann Lee", D(40)), (1, "Raj Shah", D(40)), (2, "Tom Ray", D(20))] == [
        (o.slot, o.name, o.share) for o in changed.owners]


@pytest.mark.mongo
def test_an_llps_profit_is_allocated_to_its_members(mongo_store):
    client = ledger.add_client(mongo_store, fields("llp", [{"name": "Ann Lee"}, {"name": "Raj Shah"}]))
    add_rows(mongo_store, client.id, row(date=date(2025, 6, 1), direction="in", gross=D("900.00"), vat=D("0.00"),
                                         account_code="4000", counterparty="Bright Cafe"))
    books.close(mongo_store, client.id, YEAR_1)
    opening = {line.code: line.debit - line.credit
               for line in books.trial_balance(mongo_store, client.id, YEAR_2).opening}
    assert (opening["2260"], opening["2261"]) == (D("-450.00"), D("-450.00")) and "3200" not in opening


@pytest.mark.mongo
def test_a_closed_years_split_stays_when_the_shares_change_later(mongo_store):
    client = ledger.add_client(mongo_store, fields("partnership", [{"name": "Ann Lee", "share": 75},
                                                                   {"name": "Raj Shah", "share": 25}]))
    add_rows(mongo_store, client.id, row(date=date(2025, 6, 1), direction="in", gross=D("1000.00"), vat=D("0.00"),
                                         account_code="4000", counterparty="Bright Cafe"))
    books.close(mongo_store, client.id, YEAR_1)
    ledger.change_client(mongo_store, client.id, ClientPatch(owners=[
        o.model_copy(update={"share": D(50)}) for o in client.owners]))
    opening = {line.code: line.debit - line.credit
               for line in books.trial_balance(mongo_store, client.id, YEAR_2).opening}
    assert (opening["3100"], opening["3101"]) == (D("-750.00"), D("-250.00"))
