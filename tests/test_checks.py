import datetime as dt
import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from helpers import SETTINGS as HELPER_SETTINGS, net, normalise_and_match, only_issue, row

from ledgersync.accounts import BANK, CHART
from ledgersync.accounts import BY_CODE as CHART_BY_CODE
from ledgersync.checks import account_by_note, account_on_claim, booked, normalise, what_differs
from ledgersync.models import BusinessSettings, Issue, Transaction
from ledgersync.posting import trial_balance
from ledgersync.rows import saved_form

REGISTERED = BusinessSettings()
NOT_REGISTERED = BusinessSettings(vat_registered=False)


def tx(direction="out", gross="120.00", account="7502", **kw):
    return Transaction(direction=direction, gross=gross, account_code=account,
                       date=kw.pop("date", dt.date(2026, 9, 1)), description=kw.pop("description", "t"), **kw)


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


def test_a_rate_chosen_on_a_receipt_that_prints_a_vat_number_books_its_vat_and_asks_nothing():
    # Detroit City Burger, £13.55: the receipt prints the supplier's VAT number and no VAT amount. The person chose the
    # standard rate, which with the total gives the VAT, as the account's rate would unasked: nothing is left to check
    # on the receipt, so their answer must not come back as a "VAT estimated" warning.
    t = normalise(tx(gross="13.55", account="7406", people="one", supplier_vat_number="516176005",
                     vat_treatment="standard"), REGISTERED)
    assert (t.vat_posted, t.net) == (Decimal("2.26"), Decimal("11.29"))
    vat = [c for c in codes(t) if c[0] in ("vat_implied", "vat_estimated")]
    assert vat == [("vat_implied", "info")]
    assert "rate you chose" in next(i.message for i in t.issues if i.code == "vat_implied")


@pytest.mark.parametrize("fields, flagged", [
    ({"supplier_vat_number": "516176005"}, False),                      # prints the VAT number
    ({"vat_stated": True}, False),                                      # says VAT is included
    ({}, True),                                                         # nothing says VAT was charged
    ({"supplier_vat_number": "516176005", "gross": "300.00"}, True),    # over £250 a VAT invoice prints its VAT
    ({"supplier_vat_number": "516176005", "not_vat_invoice": True}, True),
    ({"supplier_vat_number": "516176005", "document_type": "statement"}, True),   # a bank line prints neither
])
def test_a_chosen_rate_is_an_estimate_to_check_only_when_the_document_leaves_the_vat_open(fields, flagged):
    t = normalise(tx(**{"gross": "13.55", "account": "7406", "people": "one", "vat_treatment": "standard", **fields}),
                  REGISTERED)
    assert t.vat_posted > 0
    vat = [c for c in codes(t) if c[0] in ("vat_implied", "vat_estimated")]
    assert vat == ([("vat_estimated", "warning")] if flagged else [("vat_implied", "info")])


# ─── A hotel stay in the UK: its VAT is plain, so it is booked now and the VAT invoice asked for ──────────────────────
# The accountant's ruling (2026-11-18): "if the VAT is obvious add it, and then you can get the invoice". A UK hotel
# charges 20% VAT on a stay; a booking site's receipt or confirmation isn't the property's VAT invoice.

def hotel(**kw):
    return tx(**{"gross": "785.60", "account": "7402", "document_type": "receipt", "date": dt.date(2026, 10, 6),
                 "description": "Booking.com - hotel stay at Bermonds Locke, Tower Bridge, 6-8 Oct 2026", **kw})


def test_a_uk_hotel_stay_on_a_receipt_that_is_not_a_vat_invoice_books_its_vat_and_asks_for_the_invoice():
    # Booking.com's receipt for Bermonds Locke, London, £785.60: "it can't be used to claim VAT ... a valid invoice for
    # tax purposes can only be issued by the property".
    t = normalise(hotel(not_vat_invoice=True), REGISTERED)
    assert (t.vat_posted, t.net) == (Decimal("130.93"), Decimal("654.67"))
    assert codes(t) == [("hotel_vat", "warning")]
    assert "Get the VAT invoice from the property" in t.issues[0].message


def test_a_hotel_booking_that_says_vat_is_included_books_it_and_says_so():
    # The Spacious 2 bedroom flat by the Tower, £547.84: "20 % VAT is included", no amount and no VAT number.
    t = normalise(hotel(gross="547.84", vat_stated=True), REGISTERED)
    assert t.vat_posted == Decimal("91.31") and codes(t) == [("hotel_vat", "warning")]
    assert "says VAT is included" in t.issues[0].message


@pytest.mark.parametrize("change", [
    {"abroad": True},                 # a stay outside the UK carries no UK VAT
    {"currency": "EUR"},              # read in another currency: not pounds yet
    {"document_type": "invoice"},     # the property's own invoice shows no VAT: it charged none
    {"vat": "0.00"},                  # it prints VAT of nothing, or a person said there is none (No VAT on it)
    {"vat_treatment": "exempt"},      # a person chose how VAT applies
    {"account": "7400"},              # not a hotel stay
    {"direction": "in"},              # a refund
    {"without_document": "The host issues no invoices"},   # a person booked it without one: no VAT reclaimed
])
def test_hotel_vat_is_worked_out_only_for_a_uk_stay_whose_receipt_is_silent_on_it(change):
    assert "hotel_vat" not in [code for code, _ in codes(normalise(hotel(**change), REGISTERED))]


def test_hotel_vat_is_not_booked_for_a_business_not_registered_for_vat():
    t = normalise(hotel(), NOT_REGISTERED)
    assert t.vat_posted == Decimal("0.00") and "hotel_vat" not in [code for code, _ in codes(t)]


def test_a_small_hotel_receipt_with_the_vat_number_is_a_vat_invoice_and_asks_nothing():
    t = normalise(hotel(gross="120.00", supplier_vat_number="GB123456789"), REGISTERED)
    assert t.vat_posted == Decimal("20.00") and codes(t) == [("vat_implied", "info")]


def test_a_hotel_stay_said_fine_without_its_invoice_keeps_its_vat_and_stops_asking():
    t = normalise(hotel(accepted=["hotel_vat"]), REGISTERED)
    assert t.vat_posted == Decimal("130.93") and codes(t) == []


def test_a_uk_hotel_receipt_over_250_that_prints_its_vat_books_it_and_asks_for_the_full_invoice():
    # A booking site's receipt printing "includes VAT £130.93": over £250 only the property's full VAT invoice backs
    # it. The ruling again: book the VAT now and get the invoice, rather than hold the stay in Suspense for it.
    t = normalise(hotel(vat="130.93", not_vat_invoice=True), REGISTERED)
    assert (t.vat_posted, codes(t)) == (Decimal("130.93"), [("hotel_vat", "warning")])
    assert "as the receipt shows it" in t.issues[0].message
    assert "Get the VAT invoice from the property" in t.issues[0].message


@pytest.mark.parametrize("change", [
    {"gross": "120.00", "vat": "20.00"},                                  # up to £250 the receipt will do
    {"vat": "130.93", "without_document": "The hotel won't issue one"},   # a person booked it without the invoice
    {"vat": "130.93", "abroad": True},                                    # a stay abroad: not UK VAT
])
def test_a_hotel_receipt_that_prints_its_vat_asks_nothing_where_the_rules_or_a_person_settle_it(change):
    assert "hotel_vat" not in [code for code, _ in codes(normalise(hotel(**change), REGISTERED))]


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
    [found] = [i for i in normalise(tx(gross="25.63", vat="3.88", account="7406", people="one"), REGISTERED).issues
               if i.code != "meal_decided"]
    assert (found.code, found.severity) == ("vat_rate_mismatch", "info")
    assert found.message == ("£3.88 is 20% VAT on £23.28; £2.35 has no VAT (zero-rated or exempt items, a tip or "
                             "a service charge?).")


MIXED = Issue(code="mixed_items", severity="warning", message="This document mixes items of different kinds.")


def test_a_hotel_bill_of_mixed_items_is_one_note_with_its_vat():
    # Fawsley Hall: the stay, a conference room and meals with one VAT total, £62.35 on £381.86. It showed Mixed items
    # and Unusual VAT, two messages for one cause, and a warning for a bill booked to Hotels as a hotel bill usually is.
    t = normalise(tx(gross="381.86", vat="62.35", account="7402", document_type="invoice",
                     supplier_vat_number="GB123456789", issues=[MIXED]), REGISTERED)   # the hotel's own VAT invoice
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


def test_vat_an_invoice_prints_but_the_entry_lacks_is_flagged():
    # Northern Fibre's invoice prints £60.00 + £12.00 VAT = £72.00, but was read with no VAT: nothing said so, and
    # £12.00 of VAT went unreclaimed unless someone opened the invoice.
    t = normalise(tx(gross="72.00", document_type="invoice", document_total="72.00", document_net="60.00"),
                  REGISTERED)
    assert codes(t) == [("vat_not_booked", "warning")] and t.vat_posted == Decimal("0.00")
    assert t.issues[0].message == "The invoice shows £12.00 VAT; none is booked."
    receipt = normalise(tx(gross="58.00", document_type="receipt", document_total="58.00", document_net="48.34"),
                        REGISTERED)
    assert receipt.issues[0].message == "The receipt shows £9.66 VAT; none is booked."
    again = normalise(Transaction.model_validate(t.model_dump(mode="json")), REGISTERED)
    assert codes(again) == [("vat_not_booked", "warning")]


@pytest.mark.parametrize("change, settings", [
    ({}, NOT_REGISTERED),                                     # no VAT is booked for anyone
    ({"account": "2250"}, REGISTERED),                        # no VAT on a liability
    ({"account": "7403"}, REGISTERED),                        # entertainment: never reclaimed
    ({"vat": "12.00"}, REGISTERED),                           # booked
    ({"vat_treatment": "standard"}, REGISTERED),              # a person chose the rate: worked out and booked
    ({"document_net": "72.00"}, REGISTERED),                  # no VAT on the invoice
    ({"document_net": "59.00"}, REGISTERED),                  # £13.00: more than £72.00 can hold
    ({"document_net": None}, REGISTERED),                     # no net printed
])
def test_vat_not_booked_only_when_the_document_shows_vat_that_could_be(change, settings):
    fields = {"gross": "72.00", "document_type": "invoice", "document_total": "72.00", "document_net": "60.00",
              **change}
    assert "vat_not_booked" not in [code for code, _ in codes(normalise(tx(**fields), settings))]


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
    t = normalise(tx(account="7403", gross="38.20", vat="6.37", description="Sandwiches for clients"), REGISTERED)
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
    capital = normalise(tx(account="3010", gross="500.00"), LIMITED)
    assert capital.issues[0].message == "Use Director's Loan Account, not Capital Introduced, for a limited company."
    assert codes(normalise(tx(account="2250", gross="500.00"), LIMITED)) == []


def test_a_sole_trader_has_no_directors_loan_account():
    loan = normalise(tx(account="2250", gross="500.00"), TRADER)
    assert codes(loan) == [("director_loan", "warning")]
    assert loan.issues[0].message == "Director's Loan Account is for companies only. Use Drawings or Capital Introduced."
    assert codes(normalise(tx(account="3260", gross="500.00"), TRADER)) == []


def test_a_sole_trader_has_no_shares_or_dividends():
    for code, name in (("3000", "Ordinary Shares"), ("3250", "Dividends")):
        t = normalise(tx(account=code, gross="500.00"), TRADER)
        assert codes(t) == [("director_loan", "warning")]
        assert t.issues[0].message == f"{name} is for companies only. Use Drawings or Capital Introduced."
        assert codes(normalise(tx(account=code, gross="500.00"), LIMITED)) == []


def test_without_a_business_type_the_owners_accounts_are_not_questioned():
    assert codes(normalise(tx(account="3260", gross="500.00"), REGISTERED)) == []
    assert codes(normalise(tx(account="2250", gross="500.00"), REGISTERED)) == []


@pytest.mark.parametrize("output", ["copy_of", "recorded_by"])
def test_a_row_sent_back_with_its_matching_outputs_validates_again(output):
    # The API returns a copy or a card payment its receipt records with these set; sent back, it must validate.
    earlier = {"ref": "bill", "amount": "120.00", "date": "2026-09-01", "description": "BT"}
    t = normalise(tx(document_type="invoice" if output == "copy_of" else "statement", **{output: earlier}), REGISTERED)
    assert "not_booked" not in [code for code, _ in codes(t)]


def test_a_wages_payment_with_no_payroll_report_is_flagged():
    line = row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="2220", document_type="statement")
    found = only_issue(normalise_and_match([line])[0], "no_payroll")
    assert found.message == "No payroll report for March 2026: add it so wages are booked in full."
    assert found.severity == "warning"


def test_a_payroll_report_of_this_month_or_the_one_before_answers_a_payment():
    report = row(date=dt.date(2026, 3, 28), gross=Decimal("1000.00"), account_code="7000", owed_to="paye_ni",
                 document_type="payroll")
    for paid, wanted in ((dt.date(2026, 3, 31), False), (dt.date(2026, 4, 19), False), (dt.date(2026, 5, 2), True),
                         (dt.date(2026, 2, 27), True)):
        line = row(date=paid, gross=Decimal("1000.00"), account_code="2210", document_type="statement")
        found = [i for i in normalise_and_match([report, line])[1].issues if i.code == "no_payroll"]
        assert bool(found) is wanted, paid
    january = row(date=dt.date(2026, 1, 28), gross=Decimal("1000.00"), account_code="2230", document_type="statement")
    december = report.model_copy(update={"date": dt.date(2025, 12, 31)})
    assert not [i for i in normalise_and_match([december, january])[1].issues if i.code == "no_payroll"]


def test_a_bank_line_coded_to_wages_is_told_to_use_the_report():
    line = row(gross=Decimal("3000.00"), account_code="7000", document_type="statement")
    assert only_issue(normalise_and_match([line])[0], "wages_from_bank").message == (
        "Book wages from the payroll report: code net pay to 2220 Net Wages.")
    director = row(gross=Decimal("3000.00"), account_code="7001", document_type="statement")
    assert only_issue(normalise_and_match([director])[0], "wages_from_bank")


def test_wages_on_a_report_or_a_receipt_are_not_told_to_use_the_report():
    report = row(gross=Decimal("3000.00"), account_code="7000", owed_to="net_pay", document_type="payroll")
    assert not [i for i in normalise_and_match([report])[0].issues if i.code in ("wages_from_bank", "no_payroll")]


def test_a_payroll_report_keeps_the_account_it_is_owed_on_and_is_never_paid_as_an_invoice():
    report = row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="7000", owed_to="net_pay",
                 document_type="payroll", counterparty="Staff")
    line = row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="2220", document_type="statement",
               counterparty="Staff")
    report_after, line_after = normalise_and_match([report, line])
    assert report_after.contra_account_code == "2220" and report_after.owed is None
    assert not line_after.pays and not line_after.candidates
    assert not [i for i in line_after.issues if i.code in ("open_document", "possible_payment", "choose_payment")]


def test_a_summary_of_what_payroll_owes_hmrc_is_not_booked_again():
    # The test books' agency year: each month's P32 from the payroll bureau, read as a payroll report on 2210 PAYE
    # and NI, posted to and from 2210, an error on four rows that stopped the whole year being posted. The payroll
    # report books what is owed to HMRC and the bank payment clears it: the P32 only shows it.
    p32 = row(date=dt.date(2023, 4, 28), gross=Decimal("3321.37"), account_code="2210", owed_to="paye_ni",
              document_type="payroll", counterparty="HMRC")
    [after] = normalise_and_match([p32])
    assert not booked(after) and not [i for i in after.issues if i.severity == "error"]
    assert [i.code for i in after.issues] == ["not_booked"] and "already owed" in after.issues[0].message
    assert booked(normalise_and_match([p32.model_copy(update={"include": True})])[0])   # a person can still book it


def test_a_payroll_line_without_owed_to_is_owed_not_paid_and_flagged():
    line = row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="7000", document_type="payroll")
    [checked] = normalise_and_match([line])
    assert checked.contra_account_code == "2220"
    assert only_issue(checked, "payroll_owed_to").message == (
        "Check what this payroll line is owed to: booked to Net Wages for now.")
    assert only_issue(checked, "payroll_owed_to").severity == "warning"
    bank = row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="2220", document_type="statement")
    tb = trial_balance([line, bank], HELPER_SETTINGS)
    assert (net(tb, "7000"), net(tb, "2220"), net(tb, "1200")) == (Decimal("3000.00"), 0, Decimal("-3000.00"))


def test_a_saved_payroll_contra_is_ignored_for_what_the_row_is_owed_to():
    for contra in ("1200", "2250", "2220"):
        line = row(gross=Decimal("3000.00"), account_code="7000", document_type="payroll", owed_to="pension",
                   contra_account_code=contra)
        checked = normalise(line, HELPER_SETTINGS)
        assert checked.contra_account_code == "2230" and not [i for i in checked.issues if i.code == "payroll_owed_to"]


def test_employers_ni_and_pension_default_to_their_own_liabilities():
    for account, owed in (("7006", "2210"), ("7007", "2230")):
        checked = normalise(row(gross=Decimal("100.00"), account_code=account, document_type="payroll"), HELPER_SETTINGS)
        assert checked.contra_account_code == owed and only_issue(checked, "payroll_owed_to")


def test_a_payroll_line_with_its_owed_to_has_no_warning():
    line = row(gross=Decimal("100.00"), account_code="7006", document_type="payroll", owed_to="paye_ni")
    assert not [i for i in normalise(line, HELPER_SETTINGS).issues if i.code == "payroll_owed_to"]


def test_the_payroll_owed_to_warning_survives_saving():
    line = row(gross=Decimal("3000.00"), account_code="7000", document_type="payroll")
    first = normalise(line, HELPER_SETTINGS)
    saved = saved_form(first)   # only the row's inputs, and the issues the ledger does not work out itself
    assert saved["owed_to"] is None and saved["contra_account_code"] == "2220"
    second = normalise(Transaction(**saved), HELPER_SETTINGS)
    assert second.contra_account_code == "2220" and only_issue(second, "payroll_owed_to")


def test_what_a_decision_set_and_the_suppliers_vat_number_survive_saving():
    line = normalise(row(gross=Decimal("12.00"), excluded=True, superseded_by="d2", decision_ids=["d1", "d2"],
                         supplier_vat_number="GB123456789"), HELPER_SETTINGS)
    again = Transaction(**saved_form(line))
    assert (again.excluded, again.superseded_by, again.decision_ids, again.supplier_vat_number) == (
        True, "d2", ["d1", "d2"], "GB123456789")


def test_a_stay_the_reader_saw_was_abroad_is_still_abroad_once_saved_and_books_no_uk_vat():
    # Every pass after the first reads the row back from what was saved: a stay abroad that came back as one in the UK
    # would have 20% VAT booked on it (checks.hotel_vat).
    stay = normalise(hotel(abroad=True), REGISTERED)
    again = normalise(Transaction(**saved_form(stay)), REGISTERED)
    assert again.abroad is True
    assert (again.vat_posted, "hotel_vat" in [code for code, _ in codes(again)]) == (Decimal("0.00"), False)


def test_every_field_the_reader_gives_a_row_is_kept_when_it_is_saved():
    # What the reader saw is an input, worked out from nothing else: a field it gives that saving drops is lost on the
    # next pass. A new reader field needs adding to rows.INPUTS.
    from ledgersync.extractor import AccountingTransaction
    from ledgersync.rows import INPUTS
    read = set(AccountingTransaction.model_fields) & set(Transaction.model_fields)
    assert read - INPUTS == set()


def test_owed_to_decides_the_other_side_on_every_pass():
    line = row(gross=Decimal("3000.00"), account_code="7000", document_type="payroll", owed_to="pension")
    first = normalise(line, HELPER_SETTINGS)
    second = normalise(Transaction(**saved_form(first)), HELPER_SETTINGS)
    for checked in (first, second):
        assert checked.contra_account_code == "2230" and not [i for i in checked.issues if i.code == "payroll_owed_to"]


# ─── The smaller VAT points (Task 11) ──────────────────────────────────────────

def test_a_vat_registered_sale_from_a_bank_line_without_vat_is_flagged():
    line = row(direction="in", gross=Decimal("600.00"), account_code="4000", document_type="statement")
    assert only_issue(normalise_and_match([line])[0], "sale_without_vat").severity == "warning"
    unregistered = normalise_and_match([line], HELPER_SETTINGS.model_copy(update={"vat_registered": False}))[0]
    assert not any(i.code == "sale_without_vat" for i in unregistered.issues)


def test_a_bank_line_that_pays_a_sales_invoice_is_not_flagged():
    invoice = row(direction="in", gross=Decimal("600.00"), vat=Decimal("100.00"), account_code="4000",
                  counterparty="Bright Cafe", document_type="invoice", document_ref="s1")
    paid = row(direction="in", date=dt.date(2026, 1, 5), gross=Decimal("600.00"), account_code="4000",
               counterparty="Bright Cafe", document_type="statement")
    assert not any(i.code == "sale_without_vat" for i in normalise_and_match([invoice, paid])[1].issues)


def test_a_sale_whose_vat_rate_a_person_chose_is_not_flagged():
    line = row(direction="in", gross=Decimal("600.00"), account_code="4000", document_type="statement",
               vat_treatment="standard")
    assert not any(i.code == "sale_without_vat" for i in normalise_and_match([line])[0].issues)


def test_a_sale_to_an_account_not_usually_standard_rated_is_not_flagged():
    line = row(direction="in", gross=Decimal("600.00"), account_code="4904", document_type="statement")
    assert not any(i.code == "sale_without_vat" for i in normalise_and_match([line])[0].issues)


@pytest.mark.parametrize("account, vat", [("7400", Decimal("0.00")), ("7501", Decimal("0.00"))])
def test_travel_and_postage_with_no_vat_charged_are_not_flagged(account, vat):
    bill = normalise(row(gross=Decimal("12.00"), vat=vat, account_code=account), HELPER_SETTINGS)
    assert not any(i.code == "vat_rate_mismatch" for i in bill.issues)


def test_the_usual_vat_on_travel_postage_and_rent():
    from ledgersync.accounts import BY_CODE
    from ledgersync.money import VatTreatment
    assert [BY_CODE[c].vat for c in ("7400", "7501", "7100")] == [
        VatTreatment.STANDARD, VatTreatment.STANDARD, VatTreatment.EXEMPT]


def test_an_excluded_row_is_not_booked_even_when_included():
    assert booked(tx(excluded=True, include=True)) is False


def test_a_superseded_row_is_not_booked():
    assert booked(tx(superseded_by="d1")) is False


@pytest.mark.parametrize("account", ["8204", "7901", "7302"])   # insurance, bank charges, vehicle licences
def test_a_difference_on_an_account_that_carries_no_vat_is_not_taken_for_vat(account):
    # Hiscox's schedule prints a £1,125.00 premium and a £1,260.00 total: the £135.00 is Insurance Premium Tax, not VAT,
    # but the row said "The invoice shows £135.00 VAT; none is booked", and the AI couldn't clear it.
    t = normalise(tx(gross="1260.00", account=account, document_type="invoice", document_total="1260.00",
                     document_net="1125.00"), REGISTERED)
    assert "vat_not_booked" not in [code for code, _ in codes(t)]


def test_vat_on_rent_is_still_looked_for_where_the_landlord_may_charge_it():
    t = normalise(tx(gross="1200.00", account="7100", document_type="invoice", document_total="1200.00",
                     document_net="1000.00"), REGISTERED)
    assert codes(t) == [("vat_not_booked", "warning")]


def test_vat_worked_out_from_a_total_the_document_does_not_print_is_not_said_to_be_shown():
    # Screwfix's receipt is cut off at "Subtotal 72.00 / VAT 20": £86.40 and £14.40 are not on it, yet the row said
    # "The receipt shows £14.40 VAT".
    t = normalise(tx(gross="86.40", account="5000", document_type="receipt", document_total="86.40",
                     document_net="72.00", total_worked_out=True), REGISTERED)
    assert codes(t) == [("vat_not_booked", "warning")]
    assert t.issues[0].message == ("The receipt doesn't print its total: £86.40 was worked out from what it does print. "
                                   "Get a complete copy to reclaim the £14.40 VAT.")


def test_a_total_the_document_does_not_print_says_so():
    t = normalise(tx(gross="30.00", document_type="receipt", total_worked_out=True), REGISTERED)
    assert codes(t) == [("total_worked_out", "warning")]
    assert t.issues[0].message == ("The receipt doesn't print £30.00: it was worked out from what it does print. "
                                   "Check it against the document.")


def test_spending_that_looks_personal_says_where_it_went():
    t = normalise(tx(gross="12.99", account="2250", counterparty="Netflix.com", document_type="statement"),
                  BusinessSettings(business_type="limited_company"))
    assert [(i.code, i.severity, i.message) for i in t.issues] == [
        ("personal", "info", "Netflix looks like personal spending: booked to the Director's Loan Account. Recode it "
                             "if it was for the business.")]


def test_a_vat_treatment_a_person_chose_decides_whether_vat_is_booked():
    from ledgersync.money import VatTreatment
    # An EU reverse-charge sale and a zero-rated one read alike as "VAT 0.00": the treatment now says which.
    marked = normalise(tx(gross="120.00", vat="20.00", vat_treatment=VatTreatment.OUTSIDE_SCOPE), REGISTERED)
    assert (marked.vat_posted, marked.net) == (Decimal("0.00"), Decimal("120.00"))
    assert ("vat_not_applicable", "info") in codes(marked)
    zero = normalise(tx(gross="120.00", vat_treatment=VatTreatment.ZERO), REGISTERED)
    assert (zero.vat_posted, codes(zero)) == (Decimal("0.00"), [])
    worked_out = normalise(tx(gross="120.00", vat_treatment=VatTreatment.STANDARD), REGISTERED)
    assert worked_out.vat_posted == Decimal("20.00")
    # A supplier's credit note says what it is, not "a refund?".
    note = normalise(tx(direction="in", document_type="invoice"), REGISTERED)
    assert "credit note" in next(i.message for i in note.issues if i.code == "unusual_direction")


# ─── UAT round 2, high issues ──────────────────────────────────────────────────

def test_vat_on_an_invoice_without_a_vat_number_is_warned_about_until_a_person_says():
    # Dave's Skips charged VAT on an invoice with no VAT registration number: it was reclaimed in silence.
    skip = tx(gross="300.00", vat="50.00", account="7700", document_type="invoice")
    assert ("no_vat_number", "warning") in codes(normalise(skip, REGISTERED))
    assert "no_vat_number" not in dict(codes(normalise(skip.model_copy(update={"supplier_vat_number": "GB123456789"}),
                                                       REGISTERED)))
    assert "no_vat_number" not in dict(codes(normalise(skip.model_copy(update={"accepted": ["no_vat_number"]}),
                                                       REGISTERED)))


def test_vat_charged_before_a_voucher_came_off_is_booked_and_said_not_refused():
    # Amazon: VAT £1.70 on £8.48, then a promotion, £9.67 paid. It was "impossible" and blocked the client's books.
    t = normalise(tx(gross="9.67", vat="1.70", supplier_vat_number="GB727255821"), REGISTERED)
    assert (t.vat_posted, t.net) == (Decimal("1.70"), Decimal("7.97"))
    assert codes(t) == [("vat_over_rate", "warning")]
    assert ("vat_arithmetic", "error") in codes(normalise(tx(gross="9.67", vat="2.50"), REGISTERED))


def test_a_reverse_charge_service_owes_and_reclaims_its_vat():
    google = tx(gross="55.20", account="7502", document_type="invoice", reverse_charge=True)
    t = normalise(google, REGISTERED)
    assert (t.vat_posted, t.net, t.reverse_vat) == (Decimal("0.00"), Decimal("55.20"), Decimal("11.04"))
    assert codes(t) == [("reverse_charge", "info")]
    tb = trial_balance([google], REGISTERED)
    assert (net(tb, "2201"), net(tb, "2200"), net(tb, "7502")) == (Decimal("11.04"), Decimal("-11.04"), Decimal("55.20"))
    assert normalise(google, NOT_REGISTERED).reverse_vat is None


def test_a_row_dated_before_the_vat_registration_books_no_vat():
    settings = BusinessSettings(vat_from=dt.date(2026, 10, 1))
    before = normalise(tx(vat="20.00", supplier_vat_number="GB1"), settings)
    after = normalise(tx(vat="20.00", supplier_vat_number="GB1", date=dt.date(2026, 10, 1)), settings)
    assert (before.vat_posted, codes(before)) == (Decimal("0.00"), [("before_vat_registration", "info")])
    assert (after.vat_posted, codes(after)) == (Decimal("20.00"), [])


def presented(t):
    """The presentation questions normalise found: asked or left by the client's levels (materiality.decide)."""
    return [(i.code, i.difference) for i in t.presentation]


def test_a_cheap_item_on_an_equipment_account_is_asked_about():
    # Small for an asset is the client's trivial level, not a fixed amount (materiality.decide).
    cable = normalise(tx(gross="9.67", account="0030"), REGISTERED)
    assert presented(cable) == [("small_asset", Decimal("9.67"))] and codes(cable) == []
    part = normalise(tx(gross="9.67", account="0030", document_total="640.00"), REGISTERED)
    assert presented(part) == [("small_asset", Decimal("640.00"))]   # part of a bigger purchase: judged by it


def test_a_big_meal_on_subsistence_that_says_it_was_for_the_team_is_pointed_at_staff_welfare():
    t = normalise(tx(gross="96.40", account="7406", description="Dinner with the team"), REGISTERED)
    assert codes(t) == [("meal_check", "warning")] and "Staff Welfare" in t.issues[0].message


def test_a_team_only_bill_on_entertainment_is_asked_about_because_its_vat_could_be_reclaimed():
    # The Gun: "Drinks for team after DAS" coded to Entertainment, where its £9.41 VAT is lost.
    pub = normalise(tx(gross="56.45", vat="9.41", account="7403", description="The Gun - Drinks for team after DAS"),
                    REGISTERED)
    assert ("meal_check", "warning") in codes(pub)
    assert "Staff Welfare" in [i for i in pub.issues if i.code == "meal_check"][0].message
    clients = normalise(tx(gross="56.45", account="7403", description="Lunch with the team and a client"), REGISTERED)
    assert "meal_check" not in [code for code, _ in codes(clients)]


def test_a_claim_note_with_guests_points_at_entertainment_even_with_staff():
    t = tx(gross="80.00", account="8206", claim_note="Jenny Hogg - Dishoom - team and client dinner")
    assert account_by_note(t) == "7403"


def test_a_claim_note_does_not_recode_what_is_not_food_or_drink():
    t = tx(gross="54.00", account="7400", claim_note="Jenny Hogg - Trainline - team away day")
    assert account_by_note(t) is None


def test_a_receipt_on_staff_welfare_by_its_claim_note_says_so_and_is_not_asked():
    t = normalise(tx(gross="28.15", account="8206", claim_note="Jenny Hogg - ExCeL - Coffees for team at DAS"),
                  REGISTERED)
    assert codes(t) == [("claim_note", "info")] and "Coffees for team at DAS" in t.issues[0].message


def test_anything_on_sundry_asks_what_it_was_for():
    assert presented(normalise(tx(gross="6.99", account="8207"), REGISTERED)) == [("sundry_check", Decimal("6.99"))]


def test_a_claim_note_needs_guests_to_have_been_there_to_point_at_entertainment():
    # Review: "at client site" is where she worked, not who she ate with; recoding it would lose the VAT and the tax.
    at_site = tx(gross="24.00", account="7406", claim_note="Jenny Hogg - Pret - lunch at client site")
    assert account_by_note(at_site) is None
    assert ("meal_check", "warning") in codes(normalise(at_site, REGISTERED))
    assert account_by_note(tx(gross="60.00", account="7406", claim_note="The Gun - drinks with clients")) == "7403"
    assert account_by_note(tx(gross="28.15", account="7406", claim_note="Coffees for the teams at DAS")) == "8206"


def test_a_claim_note_does_not_overrule_the_account_a_person_chose():
    t = tx(gross="56.45", account="7403", claim_note="The Gun - drinks for team", account_chosen=True)
    assert account_by_note(t) is None


def test_a_stored_row_whose_account_a_person_changed_is_marked_so():
    from ledgersync.store_mongo import _stored
    data = {"direction": "out", "gross": "56.45", "account_code": "8206", "original": {"account_code": "7403"}}
    unchanged = {"direction": "out", "gross": "9.20", "account_code": "7406", "original": {"account_code": "7406"}}
    chosen, kept, read = _stored([{"id": 1, "upload_id": 1, "data": data},
                                  {"id": 2, "upload_id": 1, "position": 1, "data": unchanged},
                                  {"id": 3, "upload_id": 1, "position": 2,
                                   "data": {"direction": "out", "gross": "1.00", "account_code": "7406"}}])
    assert (chosen.tx.account_chosen, kept.tx.account_chosen, read.tx.account_chosen) == (True, False, False)


# Who was at a meal decides its VAT and tax: asked at any amount when the claim, the words and the receipt don't say.
def meal(account="7406", gross="3.40", **kw):
    return codes(normalise(tx(gross=gross, account=account, **kw), REGISTERED))


def test_a_meal_with_no_evidence_of_who_was_there_is_asked_about_at_any_amount():
    assert meal() == [("meal_check", "warning")]
    assert "and nothing on it says who it was for" in normalise(tx(gross="3.40", account="7406"), REGISTERED).issues[0].message
    assert meal(gross="96.40") == [("meal_check", "warning")]


def test_a_receipt_for_one_persons_meal_answers_who_was_there_and_says_so():
    t = normalise(tx(gross="3.40", account="7406", people="one"), REGISTERED)
    assert codes(t) == [("meal_decided", "info")]
    assert t.issues[0].message == "The receipt is for one person: their own food or drink while working, on Subsistence."


def test_groceries_from_a_food_shop_are_the_claimants_own_food_and_ask_nothing():
    # Nobody entertains a client with groceries: the shop and what was bought settle who it was for.
    for kw in ({"counterparty": "Victoria Food & Groceries", "description": "grocery purchase"},
               {"description": "Victoria Food & Groceries - groceries and drink (2 Grocery, 1 Saka)", "people": "several"},
               {"counterparty": "Tesco Express", "description": "meal deal"}):
        t = normalise(tx(gross="8.19", account="7406", claim_note="Jenny Hogg claiming Victoria Food & Groceries", **kw),
                      REGISTERED)
        assert codes(t) == [("meal_decided", "info")], kw
        assert t.issues[0].message.startswith("Groceries from a food shop: the claimant's own food while working")
    with_clients = tx(gross="8.19", account="7406", counterparty="Tesco", description="snacks for client meeting")
    assert ("meal_check", "warning") in codes(normalise(with_clients, REGISTERED))   # guests named: still asked


def test_what_was_bought_says_who_it_was_for_as_an_accountant_reads_it():
    # Groceries, or food or a drink to go for one, are the buyer's own; a sit-down meal, a round at the bar or a
    # group order for several, or one whose numbers aren't known, may have had guests: asked.
    own = [{"bought": "groceries", "people": "several", "claim_note": "Jenny Hogg claiming groceries"},
           {"bought": "food_to_go"}, {"bought": "food_to_go", "people": "one"}, {"bought": "meal_out", "people": "one"}]
    for kw in own:
        assert meal(**kw) == [("meal_decided", "info")], kw
    for kw in ({"bought": "food_to_go", "people": "several"}, {"bought": "meal_out"}, {"bought": "drinks_out"},
               {"bought": "catering", "people": "several"}):
        assert meal(**kw) == [("meal_check", "warning")], kw
    t = normalise(tx(gross="4.20", account="7406", bought="food_to_go"), REGISTERED)
    assert t.issues[0].message == ("Food or a drink to go: the buyer's own while working, on Subsistence, unless "
                                   "something says others had some.")


def test_groceries_the_company_paid_for_ask_whose_they_were_at_any_amount():
    # The paid run of 25 Nov 2026: a director's household shop on the company card (£35.65 at a supermarket) went to
    # Subsistence as "the claimant's own food while working", though no one claimed it. On a claim the claimant
    # bought it; paid by the company, it may be a director's own shopping, the office's, or a trip's (user, 25 Nov).
    t = normalise(tx(gross="35.65", account="7406", bought="groceries", counterparty="Harbour Fresh Market",
                     description="Harbour Fresh Market – fruit and vegetables, pasta, wine"), REGISTERED)
    [asked] = t.issues
    assert (asked.code, asked.severity, asked.difference) == ("meal_check", "warning", None)   # at any amount
    assert "director's loan" in asked.message and "Staff Welfare" in asked.message
    office = normalise(tx(gross="6.40", account="8205", bought="groceries", counterparty="Tesco",
                          description="Tesco, milk, tea bags and biscuits for the studio"), REGISTERED)
    assert "meal_check" not in [c for c, _ in codes(office)]   # its words say the workplace
    claimed = normalise(tx(gross="35.65", account="7406", bought="groceries", counterparty="Harbour Fresh Market",
                           description="Harbour Fresh Market – fruit and vegetables, pasta, wine",
                           claim_note="Omar Kestrel claiming groceries"), REGISTERED)
    assert codes(claimed) == [("meal_decided", "info")]


def test_a_deli_lunch_the_company_paid_for_is_still_the_buyers_own():
    # The preview of 25 Nov 2026: the reader calls a deli's or bakery's "Food and drink" groceries, so 43 lunches on
    # the agency's card (£960) asked whose they were. Only a household shop is asked: its receipt shows it.
    lunch = normalise(tx(gross="38.38", account="7406", bought="groceries", counterparty="Gantry Deli",
                         description="Gantry Deli – Food and drink"), REGISTERED)
    assert codes(lunch) == [("meal_decided", "info")]


def test_the_reader_saying_what_was_bought_comes_before_the_shops_name():
    # A shop's name says groceries, but the reader saw a table's meal: who was there is asked.
    assert meal(counterparty="Tesco Cafe", bought="catering", people="several") == [("meal_check", "warning")]


def test_a_receipt_for_several_asks_who_was_there_and_says_why():
    t = normalise(tx(gross="28.15", account="7406", people="several"), REGISTERED)
    assert codes(t) == [("meal_check", "warning")] and "more than one" in t.issues[0].message


def test_a_meal_on_a_claim_that_doesnt_say_who_asks():
    t = normalise(tx(gross="28.15", account="7406", claim_note="Jenny Hogg - ExCeL London Hospitality"), REGISTERED)
    assert codes(t) == [("meal_check", "warning")] and "doesn't say who" in t.issues[0].message


def test_entertainment_that_names_no_guests_is_asked_about_at_any_amount():
    assert meal(account="7403", gross="3.00", description="The Gun") == [("meal_check", "warning")]
    assert meal(account="7403", gross="3.00", description="The Gun", people="one") == [("meal_check", "warning")]
    assert meal(account="7403", gross="3.00", description="The Gun - drinks with clients") == []


def test_staff_welfare_food_that_doesnt_say_staff_or_names_guests_is_asked_about():
    # Nothing says staff: Subsistence (meal_recoded), and for several people still asked who was there.
    assert meal(account="8206", gross="5.00", description="The Gun", people="several") == [
        ("meal_recoded", "info"), ("meal_check", "warning")]
    assert meal(account="8206", gross="5.00", description="Team drinks", people="several") == []
    t = normalise(tx(gross="80.00", account="8206", description="Drinks with clients"), REGISTERED)
    assert codes(t) == [("meal_check", "warning")] and "Entertainment" in t.issues[0].message
    assert meal(account="8206", gross="40.00", description="Specsavers eye test") == []   # not food or drink


def test_refreshments_on_a_claim_go_to_subsistence():
    on_claim = tx(gross="8.19", account="8205", claim_note="Jenny Hogg - Victoria Food & Groceries")
    assert account_on_claim(on_claim) == "7406"
    assert account_on_claim(tx(gross="8.19", account="8205")) is None
    staff = tx(gross="28.15", account="7406", claim_note="Coffees for team")
    assert account_on_claim(staff) == "8206"


def test_a_claim_line_booked_without_a_receipt_asks_who_was_there():
    line = tx(gross="28.15", account="7406", document_type="expense_claim", description="Jenny Hogg - ExCeL")
    assert codes(normalise(line, REGISTERED)) == [("meal_check", "warning")]


def test_the_meal_check_does_not_duplicate_when_run_again():
    once = normalise(tx(gross="8.19", account="7406", claim_note="Jenny Hogg - Victoria Food"), REGISTERED)
    assert codes(normalise(once, REGISTERED)) == codes(once)


def test_nothing_asks_about_refreshments_claimed_back():
    t = normalise(tx(gross="8.19", account="8205", claim_note="Jenny Hogg - Victoria Food"), REGISTERED)
    assert "claim_refreshments" not in [c for c, _ in codes(t)]


# Another account the reader considered: a fact question when the two differ in tax or VAT, not when only in name.
def test_what_differs_between_two_accounts_is_their_tax_and_vat_not_their_name():
    meal = tx(gross="28.15", vat="3.25", account="7406")
    said = what_differs(meal, CHART_BY_CODE["7403"])
    assert "VAT" in said and "tax" in said
    assert what_differs(tx(account="7502"), CHART_BY_CODE["7504"]) is not None   # Telephone is "check" for tax
    assert what_differs(tx(account="8207"), CHART_BY_CODE["7504"]) is None
    assert what_differs(tx(account="7504"), CHART_BY_CODE["7800"]) is None        # cost or asset: presentation
    assert "owner" in what_differs(tx(account="7504"), CHART_BY_CODE["3260"])
    assert what_differs(tx(account="7406"), CHART_BY_CODE["7403"]) is not None   # tax differs without VAT too


def test_a_cost_or_income_against_a_balance_sheet_account_changes_the_profit():
    assert what_differs(tx(account="7903"), CHART_BY_CODE["2300"]) is not None   # interest, or repaying the loan
    assert what_differs(tx(account="4000", direction="in"), CHART_BY_CODE["3000"]) is not None
    assert what_differs(tx(account="7504"), CHART_BY_CODE["0030"]) is None   # cost or fixed asset: presentation


def test_an_alternative_account_that_changes_the_tax_is_asked():
    t = normalise(tx(gross="54.00", vat="9.00", account="7400", alternatives=["7403"]), REGISTERED)
    assert ("account_fact", "warning") in codes(t)
    assert "7403 Entertainment" in next(i.message for i in t.issues if i.code == "account_fact")


def test_an_alternative_that_only_renames_or_is_a_meal_account_raises_no_account_fact():
    assert "account_fact" not in [c for c, _ in codes(normalise(tx(account="8207", alternatives=["7504"]), REGISTERED))]
    meal = normalise(tx(gross="9.00", account="7406", people="one", alternatives=["8206", "7403"]), REGISTERED)
    assert "account_fact" not in [c for c, _ in codes(meal)]
    own = normalise(tx(account="8207", alternatives=["8207", "9999"]), REGISTERED)
    assert "account_fact" not in [c for c, _ in codes(own)]


def test_a_finance_agreement_is_not_booked():
    hp = normalise(tx(gross="18000.00", account="0055", document_type="finance_agreement"), REGISTERED)
    assert not booked(hp) and only_issue(hp, "not_booked").message.startswith("A finance or loan agreement")


# ─── UAT round 2, medium issues ────────────────────────────────────────────────

def journal(debit, credit, **kw):
    return tx(account=debit, contra_account_code=credit, document_type="journal", gross="500.00", **kw)


def test_a_journal_on_the_bank_the_vat_account_or_debtors_says_what_it_leaves_out_of_step():
    for debit, credit, word in (("7100", "1200", "bank account"), ("2201", "4000", "VAT figures"),
                                ("1100", "4000", "Invoices page")):
        t = normalise(journal(debit, credit), REGISTERED)
        assert codes(t) == [("journal_note", "info")] and word in t.issues[0].message
    assert codes(normalise(journal("8000", "0031"), REGISTERED)) == []


def test_a_cost_paid_ahead_is_pointed_out_once_the_year_end_is_known():
    year = BusinessSettings(period_start=dt.date(2026, 4, 1), period_end=dt.date(2027, 3, 31))
    insurance = tx(gross="1260.00", account="8204", document_type="invoice")   # 1 Sep: 153 of its 365 days after 31 Mar
    assert presented(normalise(insurance, year)) == [("prepayment", Decimal("528.16"))]
    rent = tx(account="7100").model_copy(update={"description": "Rent, quarter in advance"})
    assert presented(normalise(rent, year)) == [("prepayment", Decimal("50.30"))]
    whole_year = tx(gross="100.00", account="8204", date=dt.date(2026, 4, 1))   # 1 Apr to 31 Mar: all in the year
    assert presented(normalise(whole_year, year)) == []
    assert presented(normalise(insurance, REGISTERED)) == []
    assert "prepayment" not in dict(presented(normalise(tx(), year)))


def test_a_mixed_rate_note_doesnt_call_zero_rated_goods_a_tip():
    t = normalise(tx(gross="236.50", vat="24.00", account="5000", supplier_vat_number="GB1"), REGISTERED)
    assert "zero-rated or exempt items" in only_issue(t, "vat_rate_mismatch").message


# ─── A large purchase on a cost account: checked for equipment ─────────────────

def big(gross="1800.00", account="7504", **kw):
    """The row with the presentation questions normalise found among its issues."""
    t = normalise(tx(gross=gross, account=account, **{"document_type": "invoice", "document_total": gross,
                                                       "alternatives": ["0030"], **kw}),
                  REGISTERED)
    return t.model_copy(update={"issues": t.issues + t.presentation})


def test_a_large_purchase_on_a_candidate_account_is_marked():
    said = only_issue(big(), "asset_check")
    assert said.severity == "info"
    assert said.message == "£1,800.00 on 7504 Office Stationery may be equipment to keep as an asset."


def test_any_amount_on_a_candidate_account_is_a_candidate_for_the_working_level():
    assert "asset_check" in dict(codes(big("499.99")))   # materiality.decide asks it from the client's working level


def test_an_amount_in_another_currency_is_not_marked_until_it_is_in_pounds():
    # USD 1,800.00 is not £1,800.00: the row asks to be converted, and is checked once it has been.
    dollars = big(currency="USD")
    assert "asset_check" not in dict(codes(dollars)) and "non_gbp_currency" in dict(codes(dollars))


def test_rent_and_stock_are_not_marked():
    assert "asset_check" not in dict(codes(big(account="7100")))
    assert "asset_check" not in dict(codes(big(account="5000")))


def test_a_bill_the_reader_saw_no_equipment_in_is_not_asked_about_as_an_asset():
    assert "asset_check" not in dict(codes(big(alternatives=[])))   # a BT broadband bill on Telephone


def test_a_line_of_a_bigger_document_goes_by_the_line():
    line = big("120.00", document_total="1800.00")
    assert next(i.difference for i in line.issues if i.code == "asset_check") == Decimal("120.00")


def test_a_document_with_no_total_goes_by_the_row():
    assert "asset_check" in dict(codes(big(document_total=None)))


def test_mixed_items_is_not_marked():
    mixed = big(issues=[Issue(code="mixed_items", message="m", severity="warning")])
    assert "asset_check" not in dict(codes(mixed))


def test_a_bank_line_is_not_marked():
    assert "asset_check" not in dict(codes(big(document_type="statement", document_total=None)))


def test_money_in_is_not_marked():
    assert "asset_check" not in dict(codes(big(direction="in")))


def test_an_accepted_candidate_is_not_marked():
    quiet = big(accepted=["asset_check"])
    assert "asset_check" not in dict(codes(quiet))


def test_only_half_the_vat_on_a_car_lease_is_reclaimed():
    # The test books' agency year: each month's £504 car lease (VAT £84) reclaimed all £84, £126 too much a quarter.
    lease = row(gross=Decimal("504.00"), vat=Decimal("84.00"), account_code="7304", document_type="invoice",
                counterparty="Avon Vehicle Leasing", description="Car lease, April")
    checked = normalise(lease, HELPER_SETTINGS)
    assert (checked.vat_posted, checked.net) == (Decimal("42.00"), Decimal("462.00"))
    assert "van" in only_issue(checked, "vat_half_blocked").message
    tb = trial_balance([lease], HELPER_SETTINGS)
    assert (net(tb, "7304"), net(tb, "2201")) == (Decimal("462.00"), Decimal("42.00"))


def test_a_van_lease_whose_vat_rate_a_person_chose_reclaims_it_all():
    van = row(gross=Decimal("504.00"), vat=Decimal("84.00"), account_code="7304", document_type="invoice",
              counterparty="Avon Vehicle Leasing", description="Van lease", vat_treatment="standard")
    checked = normalise(van, HELPER_SETTINGS)
    assert checked.vat_posted == Decimal("84.00") and not [i for i in checked.issues if i.code == "vat_half_blocked"]


# ─── A client's capitalisation threshold ──────────────────────────────────────

POLICY = HELPER_SETTINGS.model_copy(update={"capitalise_from": Decimal("500")})


def equipment(gross, vat, account, **kw):
    return row(gross=Decimal(gross), vat=Decimal(vat), account_code=account, document_type="invoice",
               counterparty="Cabot Office Supplies", description="Office kit", **kw)


def test_equipment_under_the_clients_threshold_is_booked_as_a_cost():
    # The test books' agency year: capitalise from £500 net. The £576 monitor (£480 net) and £320 of task chairs
    # stayed on fixed assets; the £1,299 laptop was called "small" by materiality although well over the policy.
    monitor = normalise(equipment("576.00", "96.00", "0030"), POLICY)
    assert monitor.account_code == "7504" and "£500" in only_issue(monitor, "under_capitalisation").message
    assert not [i for i in monitor.issues if i.code == "small_asset"]
    for gross, vat, account in (("1299.00", "216.50", "0030"), ("624.00", "104.00", "0040")):   # £1,082.50 and £520 net
        kept = normalise(equipment(gross, vat, account), POLICY)
        assert kept.account_code == account and not [i for i in kept.issues if i.code in ("small_asset",
                                                                                          "under_capitalisation")]
        # small_asset is a presentation question, kept apart until materiality decides: the paid run of 25 Nov 2026
        # still asked "small to keep as Office Equipment" of both.
        assert presented(kept) == [], gross


def test_without_vat_registration_the_threshold_is_on_the_whole_price():
    kept = normalise(equipment("576.00", "96.00", "0030"), POLICY.model_copy(update={"vat_registered": False}))
    assert kept.account_code == "0030"   # £576 paid, no VAT back: over £500


def test_an_account_a_person_chose_is_kept_and_no_threshold_means_no_change():
    chosen = normalise(equipment("576.00", "96.00", "0030", account_chosen=True), POLICY)
    assert chosen.account_code == "0030"
    assert normalise(equipment("576.00", "96.00", "0030"), HELPER_SETTINGS).account_code == "0030"


# ─── Food and drink with nothing to show it was for the staff ─────────────────

def deli(account, description="Gantry Deli, sandwiches and coffee", **kw):
    return row(date=dt.date(2026, 1, 9), gross=Decimal("12.00"), vat=Decimal("2.00"), account_code=account,
               counterparty="Gantry Deli", description=description, bought="food_to_go", **kw)


def test_food_on_refreshments_or_staff_welfare_with_nothing_saying_staff_is_subsistence():
    # The agency run: 49 deli and bakery receipts went to Refreshments; the key books them as Subsistence. Only a note
    # or remark that they were for the staff makes them staff welfare.
    for account in ("8205", "8206"):
        t = normalise(deli(account), REGISTERED)
        assert t.account_code == "7406" and ("meal_recoded", "info") in codes(t)


def test_food_said_to_be_for_the_staff_or_chosen_by_a_person_stays():
    party = normalise(deli("8206", "The Granary Rooms, staff Christmas party for 9"), REGISTERED)
    milk = normalise(deli("8205", "Milk and coffee for the office kitchen"), REGISTERED)
    chosen = normalise(deli("8205", account_chosen=True), REGISTERED)
    assert (party.account_code, milk.account_code, chosen.account_code) == ("8206", "8205", "8205")
    assert not any(c == "meal_recoded" for t in (party, milk, chosen) for c, _ in codes(t))
