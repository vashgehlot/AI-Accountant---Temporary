"""The document rules: which rows book from what they have, which wait in Suspense for a receipt or invoice, and
when a receipt's VAT is reclaimed."""
from decimal import Decimal as D

import pytest

from helpers import SETTINGS, normalise_and_match, row
from ledgersync.evidence_rules import (NO_DOCUMENT_LIMIT, SIMPLIFIED_LIMIT, DocumentRule, document_rule,
                                       journal_with_rule)
from ledgersync.checks import issue
from ledgersync.models import Transaction


def ready(**overrides) -> Transaction:
    """The row after normalise and match, as the ledger hands it to the rules."""
    return normalise_and_match([row(**overrides)])[0]


def statement_line(gross: str, account: str = "7500", direction: str = "out") -> Transaction:
    """A bank line with no document behind it."""
    return ready(document_type="statement", gross=D(gross), account_code=account, direction=direction)


def receipt(gross: str, vat: str = None, vat_no: str = None, account: str = "7400", **overrides) -> Transaction:
    """A receipt, with the VAT it shows and the supplier's VAT number if printed."""
    return ready(document_type="receipt", gross=D(gross), vat=D(vat) if vat else None, account_code=account,
                 supplier_vat_number=vat_no, **overrides)


def verdict(rule: DocumentRule) -> tuple:
    return rule.action, rule.reclaim_vat, rule.needs


def test_the_limits_are_those_the_accountant_chose():
    assert (NO_DOCUMENT_LIMIT, SIMPLIFIED_LIMIT) == (D("50.00"), D("250.00"))


@pytest.mark.parametrize("kind,gross,vat_no,expected", [
    ("statement", "49.99", None, ("book", False, None)),
    ("statement", "50.00", None, ("hold", False, "receipt_or_invoice")),
    ("expense_claim", "84.20", None, ("book", True, None)),   # a claim line is booked as the claim shows it
    ("expense_claim", "20.00", None, ("book", True, None)),
    ("receipt", "120.00", "GB123456789", ("book", True, None)),
    ("receipt", "120.00", None, ("book", True, None)),     # the VAT it prints is reclaimed, number or not
    ("receipt", "250.00", "GB123456789", ("book", True, None)),
    ("receipt", "250.01", "GB123456789", ("hold", False, "vat_invoice")),
    ("invoice", "300.00", None, ("book", True, None)),
])
def test_document_rule(kind, gross, vat_no, expected):
    # Every row shows VAT of a fifth of its gross, as a receipt or invoice would for a standard-rate purchase.
    vat = str((D(gross) / 6).quantize(D("0.01"))) if kind in ("receipt", "invoice") else None
    tx = ready(document_type=kind, gross=D(gross), vat=D(vat) if vat else None, account_code="7400",
               supplier_vat_number=vat_no)
    assert verdict(document_rule(tx, SETTINGS)) == expected


def test_vat_a_receipt_prints_is_reclaimed_without_the_suppliers_vat_number():
    # Jenny's Amazon order summary (hi-viz vests): £5.82 before VAT, "Estimated VAT" £1.17, £6.99 in all, and no VAT
    # number. The accountant's ruling: VAT the receipt prints, estimated or not, is reclaimed with no one asked.
    amazon = receipt("6.99", vat="1.17", account="8207", document_net="5.82")
    rule = document_rule(amazon, SETTINGS)
    assert verdict(rule) == ("book", True, None)
    lines = {l.code: l.debit for l in journal_with_rule(amazon, 0, rule)}
    assert (lines["8207"], lines["2201"]) == (D("5.82"), D("1.17"))


def test_a_receipt_showing_no_vat_and_no_sign_of_it_reclaims_none():
    assert document_rule(receipt("120.00", vat=None), SETTINGS).reclaim_vat is False


def test_a_document_that_is_not_a_vat_invoice_reclaims_nothing():
    rule = document_rule(receipt("120.00", vat="20.00", vat_no="GB123456789", not_vat_invoice=True), SETTINGS)
    assert verdict(rule) == ("book", False, None)
    invoice = ready(document_type="invoice", gross=D("300.00"), vat=D("50.00"), not_vat_invoice=True)
    assert document_rule(invoice, SETTINGS).reclaim_vat is False


@pytest.mark.parametrize("gross,needs", [("250.00", "receipt_or_invoice"), ("250.01", "vat_invoice"),
                                         ("300.00", "vat_invoice")])
def test_a_bank_line_over_250_with_no_document_needs_a_vat_invoice(gross, needs):
    assert verdict(document_rule(statement_line(gross), SETTINGS)) == ("hold", False, needs)


def test_an_asset_purchase_is_covered():
    assert document_rule(statement_line("500.00", "0030"), SETTINGS).action == "hold"


@pytest.mark.parametrize("account", ["0030", "0040", "0050", "0055"])   # equipment, furniture, cars, vans
def test_a_fixed_asset_bought_without_a_document_is_held(account):
    assert verdict(document_rule(statement_line("100.00", account), SETTINGS)) == ("hold", False, "receipt_or_invoice")


@pytest.mark.parametrize("account", ["1100", "1103", "0031"])   # debtors, prepayments, depreciation
def test_other_asset_accounts_need_no_document(account):
    assert verdict(document_rule(statement_line("100.00", account), SETTINGS)) == ("book", True, None)


@pytest.mark.parametrize("account", ["2210", "2202", "2250", "2300", "1240"])   # PAYE, VAT, DLA, loan, card pay-off
def test_exempt_accounts_need_no_document(account):
    rule = document_rule(statement_line("500.00", account), SETTINGS)
    assert verdict(rule) == ("book", True, None)


def test_a_transfer_between_the_clients_banks_needs_no_document():
    assert document_rule(statement_line("500.00", "1210"), SETTINGS).action == "book"


def test_money_in_needs_no_document():
    assert document_rule(statement_line("500.00", "4000", direction="in"), SETTINGS).action == "book"
    assert document_rule(statement_line("500.00", "7500", direction="in"), SETTINGS).action == "book"   # a refund


def test_a_payment_of_a_document_needs_no_further_document():
    paying = ready(document_type="statement", gross=D("500.00"), account_code="7400")
    paying = paying.model_copy(update={"paid_against": "2100"})
    assert document_rule(paying, SETTINGS).action == "book"


def test_reasons_are_one_plain_sentence_without_amounts():
    for tx in (statement_line("500.00"), statement_line("20.00"), receipt("300.00"), receipt("60.00"),
               receipt("60.00", vat_no="GB123456789")):
        reason = document_rule(tx, SETTINGS).reason
        assert reason.endswith(".") and "£" not in reason and "\n" not in reason


def test_held_row_posts_gross_to_suspense():
    lines = journal_with_rule(statement_line("240.00", "7500"), 0,
                              DocumentRule(action="hold", reclaim_vat=False, needs="receipt_or_invoice", reason="x"))
    assert [(l.code, l.debit, l.credit) for l in lines] == [("9998", D("240.00"), 0), ("1200", 0, D("240.00"))]


def test_a_held_row_that_has_vat_still_posts_no_vat_leg():
    tx = receipt("300.00", vat="50.00", vat_no="GB123456789")
    lines = journal_with_rule(tx, 3, document_rule(tx, SETTINGS))
    assert [(l.transaction, l.code, l.debit, l.credit) for l in lines] == [
        (3, "9998", D("300.00"), 0), (3, "1200", 0, D("300.00"))]


def test_a_held_refund_reverses_the_legs():
    tx = statement_line("240.00", "7500", direction="in")
    lines = journal_with_rule(tx, 0, DocumentRule(action="hold", reclaim_vat=False, needs="receipt_or_invoice",
                                                  reason="x"))
    assert [(l.code, l.debit, l.credit) for l in lines] == [("9998", 0, D("240.00")), ("1200", D("240.00"), 0)]


def test_reclaimed_vat_posts_as_the_row_does():
    tx = receipt("120.00", vat="20.00", vat_no="GB123456789")
    lines = journal_with_rule(tx, 0, document_rule(tx, SETTINGS))
    assert [(l.code, l.debit, l.credit) for l in lines] == [
        ("7400", D("100.00"), 0), ("2201", D("20.00"), 0), ("1200", 0, D("120.00"))]


def test_no_reclaim_puts_vat_in_cost():
    tx = receipt("60.00", vat="10.00", not_vat_invoice=True)
    assert tx.vat_posted == D("10.00")   # normalise would book it; the rule keeps it in the cost
    before = tx.model_copy(deep=True)
    lines = journal_with_rule(tx, 0, document_rule(tx, SETTINGS))
    assert {l.code for l in lines} == {"7400", "1200"} and sum(l.debit for l in lines) == D("60.00")
    assert [(l.code, l.debit, l.credit) for l in lines] == [("7400", D("60.00"), 0), ("1200", 0, D("60.00"))]
    assert tx == before   # the row itself is not changed


def test_no_reclaim_on_a_refund_credits_the_whole_gross_to_the_account():
    tx = receipt("60.00", vat="10.00", direction="in")
    lines = journal_with_rule(tx, 0, DocumentRule(action="book", reclaim_vat=False, reason="x"))
    assert [(l.code, l.debit, l.credit) for l in lines] == [("7400", 0, D("60.00")), ("1200", D("60.00"), 0)]


def test_every_journal_balances():
    rows = [statement_line("20.00"), statement_line("500.00"), receipt("60.00", vat="10.00"),
            receipt("300.00", vat="50.00", vat_no="GB123456789"), receipt("90.00", vat="15.00", vat_no="GB123456789")]
    for tx in rows:
        lines = journal_with_rule(tx, 0, document_rule(tx, SETTINGS))
        assert sum(l.debit for l in lines) == sum(l.credit for l in lines)


def parked(gross: str, code: str = "account_unclear", direction: str = "out", document_type: str = "statement"):
    """A line the reader parked in Suspense, with the issue it raised."""
    return ready(document_type=document_type, gross=D(gross), account_code="9998", direction=direction,
                 issues=[issue(code, "Account unclear: put in Suspense. Choose one.")])


@pytest.mark.parametrize("gross,expected", [
    ("49.99", ("book", False, None)),
    ("50.00", ("hold", False, "receipt_or_invoice")),
    ("300.00", ("hold", False, "vat_invoice")),
])
def test_a_purchase_parked_in_suspense_as_unclear_falls_under_the_document_rule(gross, expected):
    assert verdict(document_rule(parked(gross), SETTINGS)) == expected


def test_an_unclear_expense_claim_line_is_covered_too_and_says_its_document_is_wanted():
    # A claim line is booked as the claim shows it (here to Suspense, its account being unclear), and says so.
    rule = document_rule(parked("84.20", document_type="expense_claim"), SETTINGS)
    assert (verdict(rule), rule.unbacked) == (("book", True, None), True)


def test_money_in_parked_as_unclear_books():
    assert document_rule(parked("500.00", direction="in"), SETTINGS).action == "book"


def test_a_line_in_suspense_with_the_fallback_issue_stays_exempt():
    assert document_rule(parked("500.00", code="account_not_recognised"), SETTINGS).action == "book"


def test_a_receipt_in_suspense_is_not_held_by_the_unclear_issue():
    assert document_rule(parked("500.00", document_type="receipt"), SETTINGS).action == "book"


def test_a_held_unclear_line_posts_to_suspense_and_the_bank():
    tx = parked("50.00")
    lines = journal_with_rule(tx, 0, document_rule(tx, SETTINGS))
    assert [(l.code, l.debit, l.credit) for l in lines] == [("9998", D("50.00"), 0), ("1200", 0, D("50.00"))]


def test_a_purchase_a_person_books_without_its_document_is_booked_with_no_vat():
    held = statement_line("120.00")
    assert verdict(document_rule(held, SETTINGS)) == ("hold", False, "receipt_or_invoice")
    booked = held.model_copy(update={"without_document": "Receipt lost; client confirms hand tools"})
    rule = document_rule(booked, SETTINGS)
    assert verdict(rule) == ("book", False, None)
    assert "Receipt lost; client confirms hand tools" in rule.reason and "no VAT reclaimed" in rule.reason


def test_a_reason_on_a_row_the_rules_book_anyway_changes_nothing():
    small = statement_line("12.00").model_copy(update={"without_document": "Lost"})
    assert document_rule(small, SETTINGS) == document_rule(statement_line("12.00"), SETTINGS)


def test_a_claim_line_its_bill_backs_is_booked_with_its_vat_kept_in_the_cost():
    from ledgersync.models import Settlement
    line = ready(document_type="expense_claim", gross=D("120.00"), account_code="7400")
    assert verdict(document_rule(line, SETTINGS)) == ("book", True, None)   # as the claim shows it, until it is backed
    backed = line.model_copy(update={"documented_by": Settlement(ref="bill", amount=D("130.00"), kind="invoice")})
    assert verdict(document_rule(backed, SETTINGS)) == ("book", False, None)


def test_a_subcontractors_bill_that_is_not_a_vat_invoice_keeps_its_cis_and_balances():
    tx = ready(document_type="invoice", gross=D("800.00"), account_code="5002", not_vat_invoice=True,
               cis_deducted=D("200.00"))
    lines = journal_with_rule(tx, 0, document_rule(tx, SETTINGS))
    assert [(l.code, l.debit, l.credit) for l in lines] == [
        ("5002", D("1000.00"), 0), ("2215", 0, D("200.00")), ("2100", 0, D("800.00"))]


def test_a_payment_worded_as_a_deposit_pays_its_invoice_and_is_not_held():
    # "Southern Van Centre, deposit on van" was matched to the van's invoice as a part payment, then held in
    # Suspense for "the full VAT invoice" that was already there.
    from ledgersync.checks import normalise
    from ledgersync.matching import match
    from ledgersync.models import BusinessSettings
    settings = BusinessSettings()
    van = Transaction(document_type="invoice", direction="out", gross="21600.00", vat="3600.00", account_code="0055",
                      date="2026-04-02", counterparty="Southern Van Centre Ltd", document_ref="van",
                      description="Ford Transit Custom", supplier_vat_number="GB1")
    def deposit(words):
        return Transaction(document_type="statement", direction="out", gross="3600.00", account_code="0055",
                           date="2026-04-03", counterparty="Southern Van Centre", document_ref="line", description=words)
    for words, action in (("Southern Van Centre, deposit on van", "book"), ("Southern Van Centre", "hold")):
        _, line = match([normalise(t, settings) for t in (van, deposit(words))], settings)
        assert line.paid_against == "2100" and document_rule(line, settings).action == action


def _line(kind, account, gross, description="x", **kw):
    from ledgersync.checks import normalise
    from ledgersync.models import BusinessSettings
    return normalise(Transaction(document_type=kind, direction="out", gross=gross, account_code=account,
                                 date="2026-06-10", description=description, **kw), BusinessSettings())


def test_a_mileage_claim_is_its_own_record():
    # "Business mileage in own car, 320 miles @ 45p" was held in Suspense for a receipt that can't exist.
    rule = document_rule(_line("expense_claim", "7400", "144.00", "Business mileage in own car, 320 miles @ 45p"), SETTINGS)
    assert (rule.action, rule.reclaim_vat) == ("book", False)
    other = document_rule(_line("expense_claim", "7400", "144.00", "Train to Leeds"), SETTINGS)
    assert (other.action, other.unbacked) == ("book", True)   # any other claim line says its receipt is wanted


def test_business_rates_are_never_asked_for_a_vat_invoice():
    rates = document_rule(_line("statement", "7103", "310.00", "Rushmoor BC, business rates"), SETTINGS)
    assert (rates.action, rates.needs) == ("hold", "receipt_or_invoice")
    assert document_rule(_line("statement", "7500", "310.00"), SETTINGS).needs == "vat_invoice"


# ─── VAT a person entered or confirmed ─────────────────────────────────────────

def test_vat_a_person_entered_is_reclaimed_where_the_rules_alone_would_hold_the_row():
    # A £547.84 receipt for phones: over £250 and not a VAT invoice, so held; with the VAT a person typed, booked.
    # (A hotel stay in the UK is booked with its VAT at once: hotel_vat.)
    held = receipt("547.84", vat="91.31", account="7502", not_vat_invoice=True)
    assert verdict(document_rule(held, SETTINGS)) == ("hold", False, "vat_invoice")
    theirs = receipt("547.84", vat="91.31", account="7502", not_vat_invoice=True, vat_confirmed=True)
    rule = document_rule(theirs, SETTINGS)
    assert (verdict(rule), rule.confirmed) == (("book", True, None), True) and "person" in rule.reason
    lines = {l.code: (l.debit, l.credit) for l in journal_with_rule(theirs, 0, rule)}
    assert lines["7502"] == (D("456.53"), D("0")) and lines["2201"] == (D("91.31"), D("0")) and "9998" not in lines


def test_vat_a_person_entered_is_reclaimed_on_a_receipt_that_is_not_a_vat_invoice_and_a_line_with_no_receipt():
    small = receipt("12.00", vat="2.00", not_vat_invoice=True, vat_confirmed=True)   # kept in the cost otherwise
    assert verdict(document_rule(receipt("12.00", vat="2.00", not_vat_invoice=True), SETTINGS)) == ("book", False, None)
    assert verdict(document_rule(small, SETTINGS)) == ("book", True, None)
    line = ready(document_type="statement", gross=D("300.00"), vat=D("50.00"), account_code="7500", vat_confirmed=True)
    assert verdict(document_rule(line, SETTINGS)) == ("book", True, None)


def test_confirming_changes_nothing_where_the_rules_reclaim_already_or_there_is_no_vat():
    already = document_rule(receipt("12.00", vat="2.00", vat_no="123456789", vat_confirmed=True), SETTINGS)
    assert (verdict(already), already.confirmed) == (("book", True, None), False)
    none = document_rule(receipt("547.84", account="7402", vat_confirmed=True, abroad=True), SETTINGS)   # no VAT on it
    assert (verdict(none), none.confirmed) == (("book", False, None), False)


def test_a_receipt_over_250_that_shows_no_vat_is_booked_whole_and_one_that_shows_vat_is_held():
    # A £447.28 hotel stay abroad, booked through Booking.com: no UK VAT on it, so no VAT invoice would add anything.
    # The receipt is the record of the cost. (A stay in the UK carries VAT, booked now: the test below.)
    stay = receipt("447.28", account="7402", description="Booking.com, hotel stay", abroad=True)
    rule = document_rule(stay, SETTINGS)
    assert (verdict(rule), rule.large_no_vat) == (("book", False, None), True)
    lines = {l.code: l.debit for l in journal_with_rule(stay, 0, rule)}
    assert lines["7402"] == D("447.28") and "9998" not in lines and "2201" not in lines
    assert verdict(document_rule(receipt("447.28", vat="74.55"), SETTINGS)) == ("hold", False, "vat_invoice")
    assert verdict(document_rule(statement_line("447.28"), SETTINGS)) == ("hold", False, "vat_invoice")   # no receipt


def test_a_uk_hotel_stay_without_its_vat_invoice_has_the_vat_reclaimed_now():
    # The accountant's ruling (2026-11-18): a hotel stay in the UK carries 20% VAT, so it is booked and reclaimed at
    # once and the property's VAT invoice asked for (checks: hotel_vat), not booked whole or held in Suspense.
    bermonds = receipt("785.60", account="7402", not_vat_invoice=True, description="Booking.com, Bermonds Locke")
    flat = receipt("547.84", account="7402", vat_stated=True, description="Booking.com, 2 bedroom flat")
    for stay in (bermonds, flat):
        rule = document_rule(stay, SETTINGS)
        assert (verdict(rule), rule.large_no_vat) == (("book", True, None), False)
    lines = {l.code: l.debit for l in journal_with_rule(bermonds, 0, document_rule(bermonds, SETTINGS))}
    assert (lines["7402"], lines["2201"]) == (D("654.67"), D("130.93")) and "9998" not in lines


def test_a_uk_hotel_receipt_over_250_that_prints_its_vat_is_booked_now_not_held():
    stay = receipt("785.60", vat="130.93", account="7402", not_vat_invoice=True, description="Booking.com, Bermonds Locke")
    assert verdict(document_rule(stay, SETTINGS)) == ("book", True, None)
    lines = {l.code: l.debit for l in journal_with_rule(stay, 0, document_rule(stay, SETTINGS))}
    assert (lines["7402"], lines["2201"]) == (D("654.67"), D("130.93")) and "9998" not in lines
    # A person who booked it without the invoice said no VAT is reclaimed: that stands.
    waived = receipt("785.60", vat="130.93", account="7402", not_vat_invoice=True, without_document="No invoice")
    rule = document_rule(waived, SETTINGS)
    assert (verdict(rule), rule.waived) == (("book", False, None), True)


# ─── VAT a receipt shows is there, without printing how much ───────────────────

def worked_out(tx: Transaction) -> tuple:
    """The VAT booked, whether it is reclaimed, and whether the row says it was worked out."""
    return tx.vat_posted, document_rule(tx, SETTINGS).reclaim_vat, "vat_implied" in [i.code for i in tx.issues]


def test_a_receipt_with_the_suppliers_vat_number_and_no_vat_amount_has_its_vat_worked_out_and_reclaimed():
    # Two burger receipts print the VAT number and a total, no VAT line: a sixth of each is VAT.
    assert worked_out(receipt("14.70", vat_no="516176005", account="7406")) == (D("2.45"), True, True)
    assert worked_out(receipt("13.55", vat_no="516176005", account="7406")) == (D("2.26"), True, True)
    burger = receipt("14.70", vat_no="516176005", account="7406")
    lines = {l.code: l.debit for l in journal_with_rule(burger, 0, document_rule(burger, SETTINGS))}
    assert (lines["7406"], lines["2201"]) == (D("12.25"), D("2.45"))


def test_a_receipt_that_says_vat_is_included_has_it_worked_out_and_reclaimed_without_a_number():
    assert worked_out(receipt("14.70", account="7406", vat_stated=True)) == (D("2.45"), True, True)
    assert worked_out(receipt("14.70", account="7406")) == (D("0.00"), False, False)   # no sign of VAT: none


def test_vat_is_not_worked_out_where_the_document_or_what_it_is_for_says_there_is_none():
    # a fare is zero-rated, whoever prints a VAT number on the ticket
    assert worked_out(receipt("21.20", vat_no="791726106", counterparty="Trainline",
                              description="Stansted Airport to London Liverpool Street train tickets"))[::2] == (D("0.00"), False)
    assert worked_out(receipt("128.98", vat_no="GB1", description="easyJet flight Glasgow to London"))[::2] == (D("0.00"), False)
    # the receipt prints VAT of nothing (cold food to take away): shown, so not worked out
    printed = ready(document_type="receipt", gross=D("4.00"), vat=D("0.00"), account_code="7406", supplier_vat_number="GB1")
    assert worked_out(printed) == (D("0.00"), False, False)
    assert worked_out(receipt("14.70", vat_no="GB1", account="7406", not_vat_invoice=True))[::2] == (D("0.00"), False)
    assert worked_out(receipt("600.00", vat_no="GB1", account="7504"))[::2] == (D("0.00"), False)   # over £250
    assert worked_out(receipt("60.00", vat_no="GB1", account="8204"))[::2] == (D("0.00"), False)   # insurance: exempt
    assert worked_out(statement_line("14.70"))[::2] == (D("0.00"), False)                          # a bank line


def test_a_fare_is_zero_rated_so_it_is_never_held_for_a_vat_invoice():
    # A £447.28 flight with VAT someone typed on it: booked whole to Travel, the VAT not reclaimed.
    flight = receipt("447.28", vat="74.55", description="British Airways - Air travel Glasgow to London")
    rule = document_rule(flight, SETTINGS)
    assert verdict(rule) == ("book", False, None) and "zero-rated" in rule.reason
    lines = {l.code: l.debit for l in journal_with_rule(flight, 0, rule)}
    assert lines["7400"] == D("447.28") and "9998" not in lines and "2201" not in lines
    abroad = receipt("612.00", description="Emirates flight London to Delhi")
    assert verdict(document_rule(abroad, SETTINGS)) == ("book", False, None)
    # with no receipt at all, a fare over £250 still wants one, but not a VAT invoice
    line = ready(document_type="statement", gross=D("447.28"), account_code="7400", description="BRITISH AIRWAYS flight")
    assert verdict(document_rule(line, SETTINGS)) == ("hold", False, "receipt_or_invoice")
    # anything else that size showing VAT is still held for its VAT invoice
    assert verdict(document_rule(receipt("447.28", vat="74.55", description="Laptop"), SETTINGS)) == ("hold", False, "vat_invoice")


def test_a_claim_line_with_no_receipt_is_booked_as_the_claim_shows_it_and_says_a_document_is_wanted():
    # A £457.20 hotel on the claim sheet with £76.20 VAT and no receipt: on Hotels, the VAT reclaimed.
    line = ready(document_type="expense_claim", gross=D("457.20"), vat=D("76.20"), account_code="7402",
                 counterparty="Mark McNee", description="Mark McNee - Innside Liverpool")
    rule = document_rule(line, SETTINGS)
    assert (verdict(rule), rule.unbacked) == (("book", True, None), True)
    lines = {l.code: l.debit for l in journal_with_rule(line, 0, rule)}
    assert (lines["7402"], lines["2201"]) == (D("381.00"), D("76.20")) and "9998" not in lines
    small = ready(document_type="expense_claim", gross=D("20.00"), account_code="7400")   # under £50, no VAT: nothing said
    assert document_rule(small, SETTINGS).unbacked is False
    assert document_rule(ready(document_type="expense_claim", gross=D("20.00"), vat=D("3.33"), account_code="7500"),
                         SETTINGS).unbacked is True
    assert verdict(document_rule(statement_line("457.20"), SETTINGS)) == ("hold", False, "vat_invoice")   # a bank line waits
