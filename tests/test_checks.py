import datetime as dt
import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ledgersync.accounts import BANK, CHART
from ledgersync.checks import normalise
from ledgersync.models import BusinessSettings, Issue, Transaction
from ledgersync.posting import trial_balance

REGISTERED = BusinessSettings()
NOT_REGISTERED = BusinessSettings(vat_registered=False)


def tx(direction="out", gross="120.00", account="7502", **kw):
    return Transaction(direction=direction, gross=gross, account_code=account,
                       date=kw.pop("date", dt.date(2026, 9, 1)), description="t", **kw)


def codes(t):
    return [(i.code, i.severity) for i in t.issues]


def test_no_vat_is_claimed_unless_the_document_shows_it():
    # A handwritten note "Breakfast £20" was booked with £3.33 VAT worked out from the account's
    # usual rate. VAT can only be reclaimed when it was charged, so nothing shown means none booked.
    t = normalise(tx(), REGISTERED)
    assert (t.vat_posted, t.net, t.contra_account_code) == (Decimal("0.00"), Decimal("120.00"), "1200")
    assert codes(t) == []


def test_a_vat_rate_chosen_by_a_person_is_applied_and_flagged():
    t = normalise(tx(vat_treatment="standard"), REGISTERED)
    assert (t.vat_posted, t.net) == (Decimal("20.00"), Decimal("100.00"))
    assert codes(t) == [("vat_estimated", "warning")]


def test_vat_shown_on_the_document_wins():
    t = normalise(tx(gross="7.95", account="8205", vat="0.70"), REGISTERED)
    assert (t.vat_posted, t.net, codes(t)) == (Decimal("0.70"), Decimal("7.25"), [])


def test_not_vat_registered_books_the_gross():
    t = normalise(tx(), NOT_REGISTERED)
    assert (t.vat_posted, t.net, codes(t)) == (Decimal("0.00"), Decimal("120.00"), [])


def test_vat_never_applies_to_liabilities():
    t = normalise(tx(gross="1450.00", account="2202", vat="10.00"), REGISTERED)
    assert t.vat_posted == Decimal("0.00") and codes(t) == [("vat_not_applicable", "warning")]


@pytest.mark.parametrize("change, code", [
    ({"account": "9999"}, "unknown_account"),
    ({"account": "1200"}, "same_account"),
    ({"currency": "usd"}, "non_gbp_currency"),
    ({"vat": "130.00"}, "vat_arithmetic"),
])
def test_unpostable_rows_get_an_error(change, code):
    assert (code, "error") in codes(normalise(tx(**change), REGISTERED))



@pytest.mark.parametrize("account", ["7502", "7400", "8204"])
def test_vat_above_the_standard_rate_is_an_error(account):
    # £50 VAT on £60 is impossible at any UK rate (e.g. the net misread as VAT); it would overclaim VAT.
    assert ("vat_arithmetic", "error") in codes(normalise(tx(gross="60.00", account=account, vat="50.00"), REGISTERED))


def test_a_few_pence_over_a_sixth_is_line_rounding_not_an_error():
    # Invoices round VAT line by line, so their total can sit slightly above gross/6.
    t = normalise(tx(gross="120.00", vat="20.04"), REGISTERED)
    assert not [i for i in t.issues if i.severity == "error"]

def test_dates_are_checked_against_the_period():
    period = BusinessSettings(period_start=dt.date(2026, 9, 1), period_end=dt.date(2026, 9, 30))
    assert ("date_missing", "warning") in codes(normalise(tx(date=None), period))
    assert ("date_out_of_period", "warning") in codes(normalise(tx(date=dt.date(2026, 10, 2)), period))


def test_money_in_on_an_expense_account_is_flagged_as_a_likely_refund():
    assert ("unusual_direction", "info") in codes(normalise(tx(direction="in"), REGISTERED))


def test_odd_vat_on_a_standard_rated_account_is_flagged():
    assert ("vat_rate_mismatch", "info") in codes(normalise(tx(vat="5.00"), REGISTERED))


def test_vat_below_the_rate_says_how_much_of_the_amount_has_none():
    # wagamama: VAT £3.88 on £25.63, as the £2.33 tip has none. "Mixed rates?" left a person guessing.
    [found] = normalise(tx(gross="25.63", vat="3.88", account="7406"), REGISTERED).issues
    assert (found.code, found.severity) == ("vat_rate_mismatch", "info")
    assert found.message == "£3.88 is 20% VAT on £23.28; £2.35 has no VAT (a tip or service charge?)."


MIXED = Issue(code="mixed_items", severity="warning", message="This document mixes items of different kinds.")


def test_a_hotel_bill_of_mixed_items_is_one_note_with_its_vat():
    # Fawsley Hall: the stay, a conference room and meals with one VAT total, £62.35 on £381.86. It showed Mixed items
    # and Unusual VAT, two messages for one cause, and a warning for a bill booked to Hotels as a hotel bill usually is.
    t = normalise(tx(gross="381.86", vat="62.35", account="7402", issues=[MIXED]), REGISTERED)
    assert codes(t) == [("mixed_items", "info")]
    assert t.issues[0].message == "Kept as one row on Hotels. VAT £62.35 is on £374.10; £7.76 has none."
    assert normalise(t, REGISTERED).issues == t.issues      # worked out the same on every pass


def test_mixed_items_on_another_account_still_ask_for_a_split():
    t = normalise(tx(gross="120.00", vat="20.00", account="7502", issues=[MIXED]), REGISTERED)
    assert codes(t) == [("mixed_items", "warning")]
    assert t.issues[0].message == "Items of different kinds with one VAT total: kept as one row on Telephone and Internet. Split it by hand if needed."
    assert "has none" not in t.issues[0].message           # its VAT is all at 20%: nothing to explain


def test_vat_at_the_reduced_rate_is_not_flagged():
    # A small business's electricity is charged VAT at 5%: £2.67 on £56.15 was flagged "mixed rates?".
    t = normalise(tx(gross="56.15", vat="2.67", account="7200"), REGISTERED)
    assert codes(t) == [] and t.vat_posted == Decimal("2.67")


def test_no_vat_charged_is_not_flagged():
    # A supplier that isn't VAT registered prints VAT £0.00, which was flagged "not standard-rate VAT".
    assert codes(normalise(tx(gross="280.00", vat="0.00", account="7800"), REGISTERED)) == []


def test_renormalising_keeps_the_estimate_flag_without_duplicates():
    once = normalise(tx(vat_treatment="standard"), REGISTERED)
    twice = normalise(Transaction.model_validate(once.model_dump(mode="json")), REGISTERED)
    assert codes(twice) == [("vat_estimated", "warning")] and twice.vat_posted == Decimal("20.00")


def test_float_noise_becomes_exact_pennies():
    assert tx(gross=0.1 + 0.2).gross == Decimal("0.30")


def test_a_pound_sign_or_no_currency_means_gbp():
    assert tx(currency="£").currency == tx(currency=None).currency == "GBP"


@pytest.mark.parametrize("gross", ["0", "-5.00", "abc"])
def test_gross_must_be_a_positive_amount(gross):
    with pytest.raises(ValidationError):
        tx(gross=gross)


def test_account_name_is_included_in_json():
    assert tx().model_dump(mode="json")["account_name"] == "Telephone and Internet"


# ─── Validating again after an edit (the UI round trip) ───────────────────────

def revalidated(t, **changes):
    """The JSON the API returned, optionally edited, sent back as the UI does."""
    return Transaction.model_validate({**t.model_dump(mode="json"), **changes})


def vat_booked(t, settings=REGISTERED):
    """The VAT the trial balance books for one transaction, whatever the fields are called."""
    lines = trial_balance([t], settings).lines
    return sum((l.debit + l.credit for l in lines if l.code in ("2200", "2201")), Decimal("0.00"))


def test_recoding_a_suspense_row_books_the_new_accounts_vat():
    first = normalise(tx(account="9998", vat="20.00"), REGISTERED)
    assert vat_booked(revalidated(first, account_code="7502")) == Decimal("20.00")


def test_vat_typed_in_later_is_booked():
    first = normalise(tx(), REGISTERED)
    assert vat_booked(revalidated(first, vat="11.50")) == Decimal("11.50")


def test_the_new_accounts_vat_treatment_replaces_the_old_default():
    first = normalise(tx(), REGISTERED)                                            # 7502: standard-rated
    assert vat_booked(revalidated(first, account_code="8204")) == Decimal("0.00")  # insurance: exempt


def test_registering_for_vat_later_books_vat():
    first = normalise(tx(vat="20.00"), NOT_REGISTERED)
    assert vat_booked(revalidated(first)) == Decimal("20.00")


def test_normalising_twice_changes_nothing():
    rng = random.Random(7)
    accounts = [a.code for a in CHART if a.code != BANK]
    for n in range(600):
        gross = f"{rng.randrange(1, 10**6) / 100:.2f}"
        shown = {"vat": f"{float(gross) * rng.choice([0, 0.05, 0.1, 0.16]):.2f}"} if n % 3 == 0 else {}
        settings = NOT_REGISTERED if n % 5 == 0 else REGISTERED
        once = normalise(tx(rng.choice(["in", "out"]), gross, rng.choice(accounts), **shown), settings)
        assert normalise(revalidated(once), settings) == once, once


# ─── The other side, by document type ─────────────────────────────────────────

@pytest.mark.parametrize("document_type, direction, account, other_side", [
    ("receipt", "out", "7502", "1200"),
    ("statement", "out", "7100", "1200"),
    ("invoice", "out", "7100", "2100"),        # a bill received: owed to the supplier
    ("invoice", "in", "7100", "2100"),         # a supplier's credit note: the supplier owes us
    ("invoice", "in", "4000", "1100"),         # a sales invoice: owed by the customer
    ("invoice", "out", "4000", "1100"),        # a credit note to a customer: we owe them
    ("expense_claim", "out", "7402", "2110"),  # owed to the employee until reimbursed
])
def test_the_other_side_follows_the_document_type(document_type, direction, account, other_side):
    t = normalise(tx(direction, account=account, document_type=document_type), REGISTERED)
    assert t.contra_account_code == other_side


def test_rows_without_a_document_type_are_booked_as_paid_from_the_bank():
    # Older API clients send no document_type: their postings must not change.
    t = normalise(Transaction(direction="out", gross="72.00", account_code="7502", description="BT"), REGISTERED)
    assert (t.document_type, t.contra_account_code) == ("receipt", "1200")


def test_a_document_that_is_not_a_transaction_is_flagged_not_booked():
    assert ("not_booked", "info") in codes(normalise(tx(document_type="pro_forma"), REGISTERED))
    assert ("not_booked", "info") not in codes(normalise(tx(document_type="pro_forma", include=True), REGISTERED))


def test_the_worked_out_side_follows_an_edit():
    bill = normalise(tx(account="7100", document_type="invoice"), REGISTERED)
    assert normalise(revalidated(bill, account_code="4000"), REGISTERED).contra_account_code == "1100"


def test_an_other_side_sent_by_a_client_is_kept():
    assert normalise(tx(contra_account_code="1230"), REGISTERED).contra_account_code == "1230"


LIMITED = BusinessSettings(business_type="limited_company")
TRADER = BusinessSettings(business_type="sole_trader")


def test_vat_on_business_entertainment_stays_in_the_cost():
    # Client sandwiches with £6.37 VAT on the receipt: UK rules block that VAT, so it is part of the cost.
    t = normalise(tx(account="7403", gross="38.20", vat="6.37"), REGISTERED)
    assert (t.vat_posted, t.net) == (Decimal("0.00"), Decimal("38.20"))
    assert codes(t) == [("vat_blocked", "info")]
    assert t.issues[0].message == "VAT £6.37 on Entertainment can't be reclaimed: kept in the cost."
    assert codes(normalise(t, REGISTERED)) == [("vat_blocked", "info")]   # validating again doesn't repeat it


def test_a_cars_vat_stays_in_its_cost_but_a_vans_is_reclaimed():
    car = normalise(tx(account="0050", gross="24000.00", vat="4000.00"), REGISTERED)
    van = normalise(tx(account="0055", gross="24000.00", vat="4000.00"), REGISTERED)
    assert (car.vat_posted, car.net) == (Decimal("0.00"), Decimal("24000.00"))
    assert (van.vat_posted, van.net) == (Decimal("4000.00"), Decimal("20000.00"))


def test_a_limited_companys_owners_go_through_the_directors_loan_account():
    drawings = normalise(tx(account="3260", gross="500.00"), LIMITED)
    assert codes(drawings) == [("director_loan", "warning")]
    assert drawings.issues[0].message == "Use Director's Loan Account, not Drawings, for a limited company."
    assert codes(normalise(tx(account="2250", gross="500.00"), LIMITED)) == []


def test_a_sole_trader_has_no_directors_loan_account():
    loan = normalise(tx(account="2250", gross="500.00"), TRADER)
    assert codes(loan) == [("director_loan", "warning")]
    assert loan.issues[0].message == "Director's Loan Account is for companies only. Use Drawings or Capital Introduced."
    assert codes(normalise(tx(account="3260", gross="500.00"), TRADER)) == []


def test_without_a_business_type_the_owners_accounts_are_not_questioned():
    assert codes(normalise(tx(account="3260", gross="500.00"), REGISTERED)) == []
    assert codes(normalise(tx(account="2250", gross="500.00"), REGISTERED)) == []


@pytest.mark.parametrize("output", ["copy_of", "recorded_by"])
def test_a_row_sent_back_with_its_matching_outputs_validates_again(output):
    # The API returns a copy or a card payment its receipt records with these set; sent back, it must validate.
    earlier = {"ref": "bill", "amount": "120.00", "date": "2026-09-01", "description": "BT"}
    t = normalise(tx(document_type="invoice" if output == "copy_of" else "statement", **{output: earlier}), REGISTERED)
    assert "not_booked" not in [code for code, _ in codes(t)]
