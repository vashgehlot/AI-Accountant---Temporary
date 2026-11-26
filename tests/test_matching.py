import pytest

from ledgersync.matching import names_match, same_payee


@pytest.mark.parametrize("a, b", [
    ("M BARNES EXPENSES", "Matt Barnes"),
    ("BUS CUBE MGMT", "Business Cube Management Solutions Limited"),
    ("FIN: CURRYS ONLINE", "Currys Ltd"),
    ("BUS MGMT SOL", "Business Management Solutions"),   # only abbreviations in common
    # Names made only of short words: "HML PM Ltd" on a bill and on its bank line did not match, so every
    # payment to the managing agent needed Link, and a payment of two of its bills was never offered at all.
    ("HML PM Ltd", "HML PM Ltd"),
    ("R+R PR LTD", "R+R PR Ltd"),
    ("BT", "BT"),
    ("R+R PR LTD CL AC", "R+R PR Ltd"),                  # the whole of one name, in order, in the other
    ("NCP", "National Car Parks Ltd"),                   # initials: Matt's claim said NCP, the receipt the full name
    ("Matt Barnes — NCP Manchester Central, parking", "National Car Parks Ltd"),
    ("TFL", "Transport for London"),
    # Jenny's TfL Payment Statement names "TfL Customer Services"; her claim line says "Transport for London, Train".
    ("TfL Customer Services", "Transport for London, Train"),
])
def test_names_that_match(a, b):
    assert names_match(a, b) and names_match(b, a)


@pytest.mark.parametrize("a, b", [
    ("ACME CONSULTING SERVICES LTD", "Northbridge Services Ltd"),   # only generic words in common
    ("HMRC PAYE", "Business Cube Management"),
    ("", "Business Cube"),
    (None, "Business Cube"),
    ("BT", "BT Sport"),                                             # too short to tell
    ("PM", "HML PM Ltd"),
    ("BRITISH GAS", "British Airways"),                             # national and place words say nothing
    ("PRET A MANGER LONDON", "London Borough of Camden"),
    ("TRANSPORT FOR LONDON", "Fordham Ltd"),                        # "for" is not an abbreviation of Fordham
    ("DIRECT DEBIT OCTOPUS ENERGY", "Screwfix Direct"),             # bank-line words say nothing either
    ("DEB 4421 TESCO STORES", "Debenhams"),
    ("VIS 0193 BOOTS", "Vision Express"),
    ("NCP", "National Grid"),                                       # not its initials
    ("CPS", "National Car Parks Ltd"),
    ("NCP", "Car Parks National Ltd"),                              # initials out of order
    ("SAP", "Hotel stay at Premier Inn"),                           # initials of words in the middle say nothing
    ("API", "Hotel stay at Premier Inn for conference"),
])
def test_names_that_do_not_match(a, b):
    assert not names_match(a, b)


@pytest.mark.parametrize("a, b", [
    ("BRIGHTLINE PRINT", "Brightline Print Ltd"),
    ("BRIGHTLINE PRI", "Brightline Print Ltd"),          # a bank line cut short
    ("M BARNES EXPENSES", "Matt Barnes"),                # an initial, and the payment's reference
    ("BUS CUBE MGMT", "Business Cube Management Solutions Limited"),
    ("FIN: CURRYS ONLINE", "Currys Ltd"),
    ("HML PM Ltd", "HML PM Ltd"),                        # names_match's own cases
    ("R+R PR LTD CL AC", "R+R PR Ltd"),
    ("NCP", "National Car Parks Ltd"),
    ("TFL", "Transport for London"),
])
def test_the_same_payee(a, b):
    assert same_payee(a, b) and same_payee(b, a) and names_match(a, b)


@pytest.mark.parametrize("a, b", [
    ("Brightline Print", "Acme Print Ltd"),              # one trade word shared, the names themselves differ
    ("Leeds City Cabs", "Leeds Print"),
    ("Northern Consulting", "Southern Consulting Ltd"),
    ("M BARNES", "Barnes Plumbing"),
    ("Print Ltd", "Brightline Print"),                   # only a trade word
    ("BT", "BT Sport"),                                  # too short to tell
    ("Starling Bank", "Amazon Web Services EMEA SARL"),  # a legal form is not a name: 'sarl' is not 'starling'
    ("Starling", "Sarl Trading"),                        # nor does it abbreviate one
    ("", "Brightline Print"),
    (None, "Brightline Print"),
])
def test_names_that_are_not_surely_the_same_payee(a, b):
    assert not same_payee(a, b) and not same_payee(b, a)


@pytest.mark.parametrize("total, asks", [("240.00", "possible_payment"), ("200.00", "open_document")])
def test_another_payee_sharing_a_trade_word_is_only_suggested(total, asks):
    # Acme Print Ltd's invoice is not Brightline Print's: the £240 payment is not paid against it, at its own amount
    # or another, and a person can Link it if it is.
    acme = bill(total, date="2026-10-19", who="Acme Print Ltd", ref="acme", account="7500")
    invoice, line = matched(acme, bank("240.00", "2026-10-22", "Brightline Print", account="7500"))
    assert line.pays == [] and line.paid_against is None and invoice.owed == Decimal(total)
    assert [code for code, _ in codes(line)] == [asks] and [c[0].ref for c in line.candidates] == ["acme"]


import datetime as dt
from decimal import Decimal

from helpers import SETTINGS as HELPER_SETTINGS, match_one, net, normalise_and_match, only_issue
from helpers import row as helper_row
from ledgersync.checks import booked, issue, normalise
from ledgersync.evidence_rules import document_rule
from ledgersync.matching import match
from ledgersync.models import BusinessSettings, Direction, Issue, Transaction
from ledgersync.posting import journal_for, trial_balance

SETTINGS = BusinessSettings()


def row(kind, direction, gross, date, counterparty, ref, account="7100", **kw):
    return Transaction(document_type=kind, direction=direction, gross=gross, date=dt.date.fromisoformat(date),
                       counterparty=counterparty, document_ref=ref, account_code=account,
                       description=kw.pop("description", f"{counterparty} {kind}"), **kw)


def bill(gross="12000.00", date="2026-10-01", who="Business Cube Management Solutions", ref="bill-oct", **kw):
    return row("invoice", "out", gross, date, who, ref, **kw)


def bank(gross="12000.00", date="2026-10-03", who="BUSINESS CUBE MGMT", ref="line-1", direction="out", **kw):
    return row("statement", direction, gross, date, who, ref, **kw)


def matched(*rows):
    return match([normalise(t, SETTINGS) for t in rows], SETTINGS)


def codes(t):
    """The row's issues, without the note saying who a meal was for (checks' meal_decided): matching's tests are about
    what pairs with what, and test_checks covers that note."""
    return [(i.code, i.severity) for i in t.issues if i.code != "meal_decided"]


def about(t, code):
    """The other rows the row's issue of that code is about (Show both)."""
    return next(i.related for i in t.issues if i.code == code)


def test_a_bank_line_pays_the_one_bill_it_matches():
    paid_bill, line = matched(bill(), bank())
    assert [(p.ref, p.amount) for p in line.pays] == [("bill-oct", Decimal("12000.00"))]
    assert (line.paid_against, line.paid_against_name) == ("2100", "Creditors")
    assert (line.vat_posted, line.net) == (Decimal("0.00"), Decimal("12000.00"))
    assert paid_bill.owed == Decimal("0.00") and [p.ref for p in paid_bill.paid_by] == ["line-1"]
    assert codes(line) == []


def test_a_bill_in_another_currency_is_booked_at_the_pounds_its_payment_took():
    # The test books' agency year: a $49 analytics invoice stayed "edit the row and enter the pounds" although the
    # bank paid £38.31 for it two days later, and one such error stops the whole year being posted.
    usd = bill(gross="500.00", who="Amazon Web Services EMEA SARL", ref="aws", currency="USD")
    card = bank(gross="396.42", who="AMAZON WEB SERVICES", ref="card")
    fee = bank(gross="7.00", date="2026-10-20", who="Starling Bank", ref="fee", account="7901")
    foreign, card_line, fee_line = matched(usd, card, fee)
    assert (foreign.currency, foreign.gross, foreign.owed) == ("GBP", Decimal("396.42"), Decimal("0.00"))
    assert [p.ref for p in card_line.pays] == ["aws"] and fee_line.pays == []
    assert [c for c, _ in codes(foreign)] == ["converted_currency"]
    assert "USD 500.00" in foreign.issues[0].message and "£396.42" in foreign.issues[0].message
    lonely, = matched(usd)   # with no payment to go by, a person enters the pounds
    assert lonely.currency == "USD" and ("non_gbp_currency", "error") in codes(lonely)
    converted, card_line, fee_line = matched(usd.model_copy(update={"gross": Decimal("396.42"), "currency": "GBP"}),
                                             card, fee)
    assert [p.ref for p in card_line.pays] == ["aws"] and converted.owed == Decimal("0.00") and fee_line.pays == []


def test_a_reverse_charge_invoice_in_dollars_books_its_vat_on_the_pounds():
    usd = bill(gross="49.00", date="2023-04-15", who="Tallgrass Metrics Inc.", ref="tm", currency="USD",
               account="7502", reverse_charge=True)
    foreign, line = matched(usd, bank("38.31", "2023-04-17", "Tallgrass Metrics Inc", account="7502"))
    assert (foreign.gross, foreign.reverse_vat, [p.ref for p in line.pays]) == (
        Decimal("38.31"), Decimal("7.66"), ["tm"])


def test_a_bill_in_another_currency_with_two_payments_as_near_stays_for_a_person():
    usd = bill(gross="49.00", date="2023-04-15", who="Tallgrass Metrics Inc.", ref="tm", currency="USD")
    foreign, *_ = matched(usd, bank("38.31", "2023-04-13", "Tallgrass Metrics Inc", ref="a"),
                          bank("38.90", "2023-04-17", "Tallgrass Metrics Inc", ref="b"))
    assert foreign.currency == "USD" and ("non_gbp_currency", "error") in codes(foreign)


def _northgate(month, name):
    return row("invoice", "in", "4800.00", f"2023-{month:02d}-01", "Northgate Dental Group", f"inv-{month}",
               account="4000", description=f"Northgate Dental Group, retainer {name} 2023")


def test_a_credit_note_comes_off_the_invoice_it_credits_and_the_payment_of_the_rest_clears_it():
    # The test books' agency year: £720 was credited on September's £4,800 and the customer paid £4,080. The credit
    # note stayed open as £720 the business owed, so the £4,080 was asked about, which stopped the year being posted.
    credit = row("invoice", "out", "720.00", "2023-10-06", "Northgate Dental Group", "cn", account="4000",
                 description="Credit to Northgate Dental Group: September 2023 retainer, hours disputed",
                 document_number="CN-0007")
    august, september, credited, line = matched(
        _northgate(8, "August"), _northgate(9, "September"), credit,
        bank("4080.00", "2023-10-10", "Northgate Dental Group", direction="in", account="4000"))
    assert [p.ref for p in line.pays] == ["inv-9"] and codes(line) == []
    assert (september.owed, credited.owed, august.owed) == (Decimal("0.00"), Decimal("0.00"), Decimal("4800.00"))
    assert [p.ref for p in september.paid_by] == ["cn", "line-1"]
    assert "Takes £720.00 off" in next(i.message for i in credited.issues if i.code == "credited")


def test_a_supplier_credit_note_comes_off_the_only_bill_it_can_be_for():
    bill_, credit = matched(bill("500.00"), row("invoice", "in", "100.00", "2026-10-08",
                                                "Business Cube Management Solutions", "cn", account="7100",
                                                description="Credit note: damaged stock"))
    assert (bill_.owed, credit.owed) == (Decimal("400.00"), Decimal("0.00"))


def test_an_unpaid_bill_is_still_owed():
    [open_bill] = matched(bill())
    assert open_bill.owed == Decimal("12000.00") and open_bill.paid_by == []


def test_of_two_bills_for_the_payment_it_pays_the_oldest_and_says_so():
    # The test books' agency year: a customer's £7,200 a month met two open items of £7,200 (the balance brought
    # forward and April's invoice). Asking which one held the payment back, so the next one met three, then four,
    # and none of the year's 25 payments from two customers settled anything; nothing could be posted.
    october, later, line = matched(bill(), bill(date="2026-10-10", ref="bill-later"), bank(date="2026-10-20"))
    assert [p.ref for p in line.pays] == ["bill-oct"] and codes(line) == [("paid_oldest", "warning")]
    assert (october.owed, later.owed) == (Decimal("0.00"), Decimal("12000.00"))
    assert "the oldest" in line.issues[0].message


def test_a_customer_paying_the_same_each_month_clears_the_invoices_in_order():
    months = [row("invoice", "in", "7200.00", f"2023-{m:02d}-01", "Brightwater Homes Ltd", f"inv-{m}", account="4000",
                  description=f"Brightwater Homes Ltd, retainer {name} 2023")
              for m, name in ((4, "April"), (5, "May"), (6, "June"))]
    pays = [bank("7200.00", day, "Brightwater Homes Ltd", ref=f"line-{n}", direction="in", account="4000",
                 description="Brightwater Homes Ltd payment received")
            for n, day in enumerate(("2023-05-02", "2023-05-24", "2023-06-26"))]
    *invoices, first, second, third = matched(*months, *pays)
    assert [[p.ref for p in line.pays] for line in (first, second, third)] == [["inv-4"], ["inv-5"], ["inv-6"]]
    assert not [i for line in (first, second, third) for i in line.issues if i.severity == "error"]
    assert [i.owed for i in invoices] == [Decimal("0.00")] * 3


def test_a_payment_that_names_the_month_pays_that_months_invoice():
    months = [row("invoice", "in", "720.00", f"2023-{m:02d}-01", "Moss & Pine Florists", f"inv-{m}", account="4000",
                  description=f"Moss & Pine Florists – Retainer, {name} 2023")
              for m, name in ((4, "April"), (5, "May"), (6, "June"))]
    *_, line = matched(*months, bank("720.00", "2023-06-06", "Moss & Pine Florists", direction="in", account="4000",
                                     description="Moss & Pine Florists retainer Jun 2023"))
    assert [p.ref for p in line.pays] == ["inv-6"] and codes(line) == []


def test_a_payment_before_the_bill_is_not_matched():
    open_bill, line = matched(bill(), bank(date="2026-09-30"))
    assert line.pays == [] and open_bill.owed == Decimal("12000.00")


def test_an_exact_payment_more_than_31_days_after_the_bill_is_still_matched():
    open_bill, line = matched(bill(), bank(date="2026-11-02"))
    assert [p.ref for p in line.pays] == ["bill-oct"] and open_bill.owed == Decimal("0.00")


def test_a_payment_on_the_31st_day_is_matched():
    _, line = matched(bill(), bank(date="2026-11-01"))
    assert [p.ref for p in line.pays] == ["bill-oct"]


def test_undated_rows_are_never_matched():
    _, line = matched(bill(), bank().model_copy(update={"date": None}))
    assert line.pays == [] and line.candidates == []


def test_money_in_does_not_pay_a_bill():
    open_bill, line = matched(bill(), bank(direction="in"))
    assert line.pays == [] and open_bill.owed == Decimal("12000.00")


def test_a_sales_invoice_is_paid_by_money_in():
    invoice = row("invoice", "in", "2400.00", "2026-09-30", "Harbour & Lane Architects LLP", "inv-117", account="4000")
    paid, line = matched(invoice, bank("2400.00", "2026-10-14", "HARBOUR LANE ARCHITECTS", direction="in",
                                       account="4000"))
    assert line.paid_against == "1100" and paid.owed == Decimal("0.00")


def test_a_claim_is_paid_by_its_reimbursement():
    lines = [row("expense_claim", "out", gross, date, "Matt Barnes", "claim-matt", account=account)
             for gross, date, account in (("173.75", "2026-09-14", "7402"), ("12.88", "2026-09-14", "7406"),
                                          ("27.50", "2026-09-30", "7502"))]
    *claim, line = matched(*lines, bank("214.13", "2026-10-05", "M BARNES EXPENSES"))
    assert line.paid_against == "2110" and {t.owed for t in claim} == {Decimal("0.00")}


def test_a_claim_is_dated_by_its_latest_dated_line():
    first = row("expense_claim", "out", "100.00", "2026-09-01", "Jenny Hogg", "claim")
    second = row("expense_claim", "out", "50.00", "2026-09-20", "Jenny Hogg", "claim")
    undated = second.model_copy(update={"date": None})
    paid = bank("150.00", "2026-09-10", "J HOGG EXPENSES")
    *_, before_the_latest_line = matched(first, second, paid)
    *_, no_later_line = matched(first, undated, paid)
    assert before_the_latest_line.pays == [] and [p.ref for p in no_later_line.pays] == ["claim"]


def test_unlink_makes_an_ordinary_bank_line():
    open_bill, line = matched(bill(), bank(link=[]))
    assert line.pays == [] and line.paid_against is None and open_bill.owed == Decimal("12000.00")


def test_link_pays_the_document_a_person_chose():
    october, later, line = matched(bill(), bill(date="2026-10-10", ref="bill-later"),
                                   bank(date="2026-10-20", link=["bill-later"]))
    assert [p.ref for p in line.pays] == ["bill-later"] and codes(line) == []
    assert (october.owed, later.owed) == (Decimal("12000.00"), Decimal("0.00"))


def test_a_link_to_a_document_no_longer_in_the_table_is_dropped():
    _, line = matched(bill(), bank(link=["gone"]))
    assert ("stale_link", "warning") in codes(line) and [p.ref for p in line.pays] == ["bill-oct"]


def test_lines_a_person_linked_are_applied_before_automatic_matches():
    # The automatic line comes first by date, but the person said the later line pays the bill.
    _, first, second = matched(bill(), bank(date="2026-10-02", ref="early"),
                               bank(date="2026-10-05", ref="late", link=["bill-oct"]))
    assert first.pays == [] and [p.ref for p in second.pays] == ["bill-oct"]


def test_matching_does_not_depend_on_the_order_of_the_rows():
    rows = [bill(), bill(gross="500.00", ref="bill-small", who="Clearway Office Supplies"),
            bank(), bank("500.00", ref="line-2", who="CLEARWAY OFFICE")]
    forward = {t.document_ref: (t.owed, [p.ref for p in t.pays]) for t in matched(*rows)}
    backward = {t.document_ref: (t.owed, [p.ref for p in t.pays]) for t in matched(*reversed(rows))}
    assert forward == backward


def test_matching_again_gives_the_same_result_without_duplicate_issues():
    once = matched(bill(), bill(date="2026-10-10", ref="bill-later"), bank(date="2026-10-20"))
    again = match([normalise(Transaction.model_validate(t.model_dump(mode="json")), SETTINGS) for t in once],
                  SETTINGS)
    assert again == once


def test_receipts_are_neither_documents_nor_payments():
    receipt, line = matched(row("receipt", "out", "12000.00", "2026-10-01", "Business Cube", "r-1"), bank())
    assert line.pays == [] and receipt.owed is None


def test_one_payment_can_clear_several_bills_from_the_same_supplier():
    a, b, line = matched(bill("300.00", ref="cw-1", who="Clearway Office Supplies"),
                         bill("200.00", date="2026-10-05", ref="cw-2", who="Clearway Office Supplies"),
                         bank("500.00", "2026-10-20", "CLEARWAY OFFICE SUPP"))
    assert sorted(p.ref for p in line.pays) == ["cw-1", "cw-2"] and a.owed == b.owed == Decimal("0.00")


def test_several_sets_that_add_up_ask_a_person_to_choose():
    docs = [bill(gross, date=date, ref=ref, who="Clearway Office Supplies")
            for gross, date, ref in (("300.00", "2026-10-01", "a"), ("200.00", "2026-10-02", "b"),
                                     ("400.00", "2026-10-03", "c"), ("100.00", "2026-10-04", "d"))]
    *_, line = matched(*docs, bank("500.00", "2026-10-20", "CLEARWAY"))
    assert codes(line) == [("choose_payment", "error")]
    assert sorted(sorted(c.ref for c in option) for option in line.candidates) == [["a", "b"], ["c", "d"]]


def test_a_part_payment_is_applied_and_flagged():
    open_bill, line = matched(bill(), bank("10000.00"))
    assert open_bill.owed == Decimal("2000.00") and [p.amount for p in line.pays] == [Decimal("10000.00")]
    assert codes(line) == [("part_payment", "warning")]
    assert line.issues[0].message == "Paid £10,000.00 of £12,000.00; £2,000.00 still owed."


def test_an_overpayment_is_applied_and_flagged():
    open_bill, line = matched(bill(), bank("12050.00"))
    assert open_bill.owed == Decimal("-50.00") and codes(line) == [("overpayment", "warning")]
    assert line.issues[0].message == "Paid £50.00 over. The supplier owes you £50.00."


def test_a_customer_who_pays_too_much_is_owed_the_difference():
    invoice = row("invoice", "in", "2400.00", "2026-09-30", "Harbour & Lane Architects", "inv-117", account="4000")
    _, line = matched(invoice, bank("2450.00", "2026-10-14", "HARBOUR LANE", direction="in", account="4000"))
    assert line.issues[0].message == "Received £50.00 over. You owe the customer £50.00."


def test_a_bill_linked_twice_is_flagged_as_overpaid():
    _, first, second = matched(bill(), bank(ref="line-1", link=["bill-oct"]),
                               bank(ref="line-2", date="2026-10-04", link=["bill-oct"]))
    assert codes(first) == [] and codes(second) == [("overpayment", "warning")]


@pytest.mark.parametrize("exact_on", ["2025-05-13", "2025-05-14"])
def test_an_exact_payment_wins_over_a_bigger_one_to_the_same_person(exact_on):
    # Two payments to the director, £500 and £50: the £500 came first and took the £50 claim as an overpayment,
    # so the claim showed £450 overpaid and the £50 went to the director's loan account instead.
    claim = row("expense_claim", "out", "50.00", "2025-04-30", "T. Crook", "claim", account="7400")
    open_claim, bigger, exact = matched(claim, bank("500.00", "2025-05-13", "MR T CROOK", ref="bigger", account="2250"),
                                        bank("50.00", exact_on, "MR T CROOK", ref="exact", account="2250"))
    assert [p.ref for p in exact.pays] == ["claim"] and open_claim.owed == Decimal("0.00")
    assert bigger.pays == [] and bigger.paid_against is None and codes(bigger) == []


def test_one_payment_clears_two_bills_from_a_supplier_with_a_short_name():
    on_account = bill("610.63", date="2025-04-04", ref="on-account", who="HML PM Ltd")
    reserve = bill("95.53", date="2025-04-10", ref="reserve", who="HML PM Ltd", account="7800")
    *_, line = matched(on_account, reserve, bank("706.16", "2025-05-01", "HML PM Ltd"))
    assert sorted(p.ref for p in line.pays) == ["on-account", "reserve"] and codes(line) == []


def test_two_payments_on_one_day_clear_one_bill_between_them():
    open_bill, first, second = matched(bill("675.38", date="2025-09-29", who="HML PM Ltd"),
                                       bank("610.63", "2025-10-15", "HML PM Ltd", ref="first"),
                                       bank("64.75", "2025-10-15", "HML PM Ltd", ref="second"))
    assert open_bill.owed == Decimal("0.00") and [p.ref for p in second.pays] == ["bill-oct"]
    assert codes(first) == [("part_payment", "info")] and codes(second) == []   # a note: the rest was paid


def reminder_pair(**reminder):
    # A bill and its reminder: the same number (printed a little differently), supplier and amount, three weeks apart.
    original = bill("610.63", date="2026-03-25", ref="bill", who="HML PM Ltd", document_number="SC-2026-00718")
    again = bill("610.63", date="2026-04-15", ref="reminder", who="HML PM Ltd", document_number="sc 2026 00718",
                 **reminder)
    return original, again


def test_a_reminder_of_a_bill_is_not_booked_again():
    # The reminder was booked as a second bill; the payment cleared the reminder and the bill stayed owed.
    paid, reminder, line = matched(*reminder_pair(), bank("610.63", "2026-04-23", "HML PM Ltd"))
    assert [p.ref for p in line.pays] == ["bill"] and paid.owed == Decimal("0.00") and codes(line) == []
    assert (reminder.copy_of.ref, reminder.owed, booked(reminder)) == ("bill", None, False)
    assert codes(reminder) == [("duplicate_document", "info")]


def test_a_copy_a_person_includes_is_booked_as_well():
    _, reminder, line = matched(*reminder_pair(include=True), bank("610.63", "2026-04-23", "HML PM Ltd"))
    assert booked(reminder) and codes(line) == [("paid_oldest", "warning")]   # booked twice: two owed, the oldest paid


@pytest.mark.parametrize("change", [{"document_number": "SC-2026-00719"}, {"gross": "650.00"},
                                    {"who": "Lambert Smith Hampton"}])
def test_a_different_number_amount_or_supplier_is_a_separate_document(change):
    original = bill("610.63", date="2026-03-25", ref="bill", who="HML PM Ltd", document_number="SC-2026-00718")
    other = bill(**{"gross": "610.63", "date": "2026-04-15", "ref": "other", "who": "HML PM Ltd",
                    "document_number": "SC-2026-00718", **change})
    _, other = matched(original, other)
    assert other.copy_of is None and booked(other) and other.owed is not None


def test_the_same_receipt_read_twice_is_booked_once():
    receipt = dict(kind="receipt", direction="out", gross="7.49", date="2026-01-02", counterparty="Pizza Hut",
                   account="7406", document_number="Chk 3318")
    first, again = matched(row(**receipt, ref="photo"), row(**receipt, ref="photo-again"))
    assert (first.copy_of, again.copy_of.ref) == (None, "photo") and booked(first) and not booked(again)


def claim(ref, lines=(("12.88", "2026-09-14"), ("173.75", "2026-09-14"), ("2.70", "2026-09-15"))):
    """An expenses sheet with no number of its own: one row a line."""
    total = str(sum(Decimal(g) for g, _ in lines))
    return [row("expense_claim", "out", gross, date, "Matt Barnes", ref, document_total=total)
            for gross, date in lines]


def test_an_expenses_sheet_read_three_times_is_booked_once():
    rows = matched(*claim("sheet"), *claim("sheet-2"), *claim("sheet-3"))
    first, second, third = rows[:3], rows[3:6], rows[6:]
    assert all(r.copy_of is None and booked(r) for r in first)
    assert all(r.copy_of.ref == "sheet" and not booked(r) for r in second + third)
    assert codes(second[0]) == [("duplicate_document", "info")]


def test_an_expenses_sheet_with_other_lines_is_another_claim():
    rows = matched(*claim("sheet"), *claim("later", (("12.88", "2026-09-14"), ("40.00", "2026-09-20"))))
    assert all(r.copy_of is None and booked(r) for r in rows)


def test_one_unnumbered_receipt_like_another_is_not_taken_for_a_copy():
    # Two coffees of the same price on one day are often two coffees: a person or the AI decides.
    coffee = dict(kind="receipt", direction="out", gross="3.20", date="2026-09-14", counterparty="Costa",
                  account="7406")
    first, second = matched(row(**coffee, ref="a"), row(**coffee, ref="b"))
    assert first.copy_of is None and second.copy_of is None


def test_receipts_with_the_same_number_on_different_days_are_both_booked():
    # Till numbers start again every day.
    receipt = dict(kind="receipt", direction="out", gross="4.75", counterparty="Costa", account="7406",
                   document_number="217")
    first, second = matched(row(**receipt, date="2026-03-13", ref="a"), row(**receipt, date="2026-03-14", ref="b"))
    assert first.copy_of is None and second.copy_of is None


def test_a_part_payment_with_two_open_bills_from_the_supplier_asks_a_person():
    *_, line = matched(bill(), bill("9000.00", date="2026-10-05", ref="bill-2"), bank("10000.00", "2026-10-20"))
    assert codes(line) == [("choose_payment", "error")] and len(line.candidates) == 2


def test_the_same_amount_from_a_different_name_is_only_a_suggestion():
    open_bill, line = matched(bill(), bank(who="HMRC PAYE"))
    assert codes(line) == [("possible_payment", "warning")] and line.pays == []
    assert [[c.ref for c in o] for o in line.candidates] == [["bill-oct"]] and open_bill.owed == Decimal("12000.00")


def test_a_bank_line_without_a_counterparty_is_only_a_suggestion():
    _, line = matched(bill(), bank(who=None))
    assert codes(line) == [("possible_payment", "warning")]


def test_one_payment_never_clears_documents_owed_on_different_accounts():
    # A £300 claim (owed to staff) and a £200 bill (owed to a supplier), both from payees "M BARNES" names, must not
    # be settled together by one £500 line: the whole £500 would post against just one of the two accounts. (Barnes
    # Plumbing alone is not surely M Barnes: same_payee.)
    claim = row("expense_claim", "out", "300.00", "2026-10-01", "Matt Barnes", "claim", account="7402")
    plumber = bill("200.00", date="2026-10-01", ref="plumber", who="Matt Barnes Plumbing", account="7800")
    *_, line = matched(claim, plumber, bank("500.00", "2026-10-05", "M BARNES"))
    assert line.pays == [] and codes(line) == [("choose_payment", "error")]


def test_a_link_to_documents_on_different_accounts_is_refused():
    claim = row("expense_claim", "out", "300.00", "2026-10-01", "Matt Barnes", "claim", account="7402")
    plumber = bill("200.00", date="2026-10-01", ref="plumber", who="Barnes Plumbing", account="7800")
    open_claim, open_bill, line = matched(claim, plumber,
                                          bank("500.00", "2026-10-05", "M BARNES", link=["claim", "plumber"]))
    assert line.pays == [] and codes(line) == [("mixed_link", "error")]
    assert (open_claim.owed, open_bill.owed) == (Decimal("300.00"), Decimal("200.00"))


def test_a_payment_dated_before_its_bill_is_suggested_not_ignored():
    # A card payment the day before the invoice was neither matched nor flagged, so the rent was counted twice.
    open_bill, line = matched(bill(date="2026-10-02"), bank(date="2026-10-01"))
    assert codes(line) == [("possible_payment", "warning")] and line.pays == []
    assert [[c.ref for c in o] for o in line.candidates] == [["bill-oct"]]
    assert "the payment is dated before the document" in line.issues[0].message
    assert open_bill.owed == Decimal("12000.00")


# May's letting agent statement: the rent it collected, less its fee, its charge and a boiler repair it paid.
MAY = [("in", "925.00", "22 Telecom Ltd", "4904"), ("out", "111.00", "R+R PR Ltd", "7603"),
       ("out", "7.25", "R+R PR Ltd", "7901"), ("out", "280.00", "Parkside Heating & Plumbing", "7800")]


def agent_statement(items=MAY, agent="R+R PR Ltd", date="2025-05-09", ref="statement"):
    return [row("agent_statement", direction, gross, date, who, ref, account=account, agent=agent)
            for direction, gross, who, account in items]


def test_an_agents_net_payment_clears_its_statement():
    *statement, line = matched(*agent_statement(), bank("526.75", "2025-05-13", "R+R PR LTD", direction="in",
                                                        account="4904"))
    assert [p.ref for p in line.pays] == ["statement"] and line.paid_against == "1100" and codes(line) == []
    assert {t.owed for t in statement} == {Decimal("0.00")}


def test_a_bill_the_agent_paid_is_cleared_by_its_statement():
    boiler = bill("280.00", date="2025-05-08", ref="boiler", who="Parkside Heating & Plumbing", account="7800")
    paid, *statement = matched(boiler, *agent_statement())
    assert paid.owed == Decimal("0.00") and [p.ref for p in statement[3].pays] == ["boiler"]
    assert [(p.kind, p.description) for p in paid.paid_by] == [("agent_statement", "R+R PR Ltd's statement")]
    assert (statement[3].paid_against, statement[0].pays) == ("2100", [])


def test_an_agent_who_paid_out_more_than_it_collected_is_owed_the_difference():
    costs = [("in", "925.00", "22 Telecom Ltd", "4904"), ("out", "1200.00", "Parkside Heating & Plumbing", "7800")]
    *statement, line = matched(*agent_statement(costs), bank("275.00", "2025-05-13", "R+R PR LTD", account="7800"))
    assert [p.ref for p in line.pays] == ["statement"] and statement[0].owed == Decimal("0.00")
    assert {t.document_direction for t in statement} == {Direction.OUT}


def till(gross="21.35", date="2026-02-22", who="McDonald's", ref="receipt", **kw):
    # One person's meal (people="one"): who was there isn't these tests' question.
    return row("receipt", "out", gross, date, who, ref, account="7406", **{"people": "one", **kw})


def test_a_receipt_and_its_card_payment_are_booked_once():
    # A receipt and the card line for it were two payments: the meal and the bank were both counted twice.
    receipt, line = matched(till(vat="3.56"), bank("21.35", "2026-02-23", "MCDONALDS", ref="card", account="7406"))
    assert (line.recorded_by.ref, booked(line), line.pays) == ("receipt", False, [])
    assert [p.ref for p in receipt.paid_by] == ["card"] and booked(receipt) and receipt.owed is None


def test_unlink_books_a_card_payment_apart_from_the_receipt():
    receipt, line = matched(till(), bank("21.35", "2026-02-22", "MCDONALDS", ref="card", account="7406", link=[]))
    assert line.recorded_by is None and booked(line) and receipt.paid_by == []


@pytest.mark.parametrize("change", [{"gross": "21.36"}, {"direction": "in"}])   # days apart instead: a date question
def test_a_receipt_records_only_a_payment_of_its_amount_from_its_shop_within_days(change):
    receipt, line = matched(till(), bank(**{"gross": "21.35", "date": "2026-02-22", "who": "MCDONALDS", "ref": "card",
                                            "account": "7406", **change}))
    assert line.recorded_by is None and receipt.paid_by == []


def test_two_coffees_and_two_card_payments_pair_one_to_one():
    first, second = till("3.85", "2026-03-13", "Costa", "cup-1"), till("3.85", "2026-03-13", "Costa", "cup-2")
    *_, a, b = matched(first, second, bank("3.85", "2026-03-13", "COSTA COFFEE", ref="a", account="7406"),
                       bank("3.85", "2026-03-13", "COSTA COFFEE", ref="b", account="7406"))
    assert sorted([a.recorded_by.ref, b.recorded_by.ref]) == ["cup-1", "cup-2"]


def test_a_bank_line_that_pays_a_bill_is_not_taken_by_a_receipt():
    _, _, line = matched(bill(), till("12000.00", "2026-10-02", "Business Cube Management Solutions"), bank())
    assert [p.ref for p in line.pays] == ["bill-oct"] and line.recorded_by is None


def test_items_of_agent_statements_never_pay_one_another():
    # Rows of one statement saved with references of their own (bank lines retyped one by one) took each other's
    # amounts as payments, and the trial balance waited for a choice between the agent's own fees.
    items = [row("agent_statement", direction, gross, "2025-05-09", who, ref, account=account, agent="R+R PR Ltd")
             for direction, gross, who, ref, account in (("in", "925.00", "22 Telecom Ltd", "a", "4904"),
                                                         ("out", "111.00", "R+R PR Ltd", "b", "7603"),
                                                         ("out", "7.25", "R+R PR Ltd", "c", "7901"))]
    assert [(t.pays, codes(t)) for t in matched(*items)] == [([], [])] * 3


# Jenny Hogg's expense claim: each line names the shop in its description; the counterparty is Jenny.
def claim_line(gross, date, merchant, ref="claim", **kw):
    return row("expense_claim", "out", gross, date, "Jenny Hogg", ref, account=kw.pop("account", "7400"),
               description=f"Jenny Hogg - {merchant}", **kw)


def test_a_receipt_for_a_claim_line_is_booked_once_and_owed_to_the_claimant():
    # Jenny claimed her train fare and also sent the Trainline receipt: the fare was booked twice, once owed to her
    # and once as paid from a bank account the business never used.
    line, other, receipt = matched(claim_line("157.59", "2026-09-07", "Trainline (Bath Spa–London return)"),
                                   claim_line("30.90", "2026-09-30", "Transport for London"),
                                   row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket"))
    assert (line.recorded_by.ref, booked(line)) == ("ticket", False)
    assert (receipt.claimed_in.ref, receipt.contra_account_code, booked(receipt)) == ("claim", "2110", True)
    assert line.owed == other.owed == Decimal("188.49")      # the claim still asks for both lines back


def test_an_invoice_the_claimant_paid_is_owed_to_the_claimant_not_the_supplier():
    line, invoice = matched(claim_line("230.56", "2026-09-25", "instantprint / Bluetree Print Ltd (brochures)",
                                       account="7500"),
                            row("invoice", "out", "230.56", "2026-09-25", "Bluetree Print Limited", "inv", account="7500"))
    assert (invoice.claimed_in.ref, invoice.contra_account_code, invoice.owed) == ("claim", "2110", None)
    assert not booked(line)


def test_a_receipt_goes_with_the_claim_line_nearest_its_date():
    # The same Amazon item was bought on 8 and 11 September; only the second receipt was sent.
    first, second, receipt = matched(claim_line("17.99", "2026-09-08", "Amazon stationery", account="7504"),
                                     claim_line("17.99", "2026-09-11", "Amazon stationery", account="7504"),
                                     row("receipt", "out", "17.99", "2026-09-11", "Amazon.co.uk", "r", account="7504"))
    assert (first.recorded_by, second.recorded_by.ref) == (None, "r")


@pytest.mark.parametrize("change", [{"gross": "157.60"}])   # five days apart instead: a date question
def test_a_claim_line_keeps_its_own_booking_unless_a_receipt_clearly_is_the_same(change):
    line = claim_line(change.get("gross", "157.59"), change.get("date", "2026-09-07"),
                      change.get("merchant", "Trainline"), include=change.get("include", False))
    line, receipt = matched(line, row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket"))
    assert line.recorded_by is None and booked(line) and receipt.claimed_in is None


def test_a_claim_line_a_person_ticks_is_booked_as_well_and_keeps_its_receipt():
    # Once ticked, the line lost its receipt, so its tick box went and the receipt was booked as paid from the bank.
    line, receipt = matched(claim_line("157.59", "2026-09-07", "Trainline", include=True),
                            row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket"))
    assert (line.recorded_by.ref, booked(line)) == ("ticket", True)
    assert (receipt.claimed_in.ref, receipt.contra_account_code, booked(receipt)) == ("claim", "2110", True)


def undated(t):
    return t.model_copy(update={"date": None})


SOUTHGATE = "Southgate Bath Car Park"


def test_a_receipt_without_a_date_takes_the_date_of_its_claim_line():
    line, receipt = matched(claim_line("36.00", "2026-09-09", SOUTHGATE),
                            undated(row("receipt", "out", "36.00", "2026-09-09", SOUTHGATE, "photo")))
    assert (line.recorded_by.ref, receipt.claimed_in.ref, receipt.date) == ("photo", "claim", dt.date(2026, 9, 9))
    assert codes(receipt) == [("date_from_claim", "info")]     # "no date found" no longer applies


def test_a_receipt_and_its_claim_line_on_different_dates_ask_which_is_right():
    # The Southgate receipt photo was read as 9 August; Jenny's claim has the same £36.00 on 9 September. The amounts
    # agree, so it is one purchase, booked once from the receipt (left apart, it counted twice); the question is
    # only which date is right.
    line, receipt = matched(claim_line("36.00", "2026-09-09", SOUTHGATE),
                            row("receipt", "out", "36.00", "2026-08-09", SOUTHGATE, "photo"))
    assert (line.recorded_by.ref, receipt.claimed_in.ref, booked(line), booked(receipt)) == ("photo", "claim", False, True)
    assert (receipt.date_found, line.date_found) == (dt.date(2026, 9, 9), dt.date(2026, 8, 9))
    assert (about(receipt, "date_conflict"), about(line, "date_conflict")) == ([0], [1])   # each the other (Show both)
    assert codes(receipt) == codes(line) == [("date_conflict", "warning")]
    assert all(d in receipt.issues[0].message and d in line.issues[0].message for d in ("9 Sep 2026", "9 Aug 2026"))


@pytest.mark.parametrize("others", [
    [claim_line("36.00", "2026-10-21", SOUTHGATE)],                              # two lines it could be
    [row("receipt", "out", "36.00", "2026-10-21", SOUTHGATE, "photo-2")],        # two receipts it could be
])
def test_no_date_is_asked_about_when_more_than_one_record_could_be_the_one(others):
    rows = matched(claim_line("36.00", "2026-09-09", SOUTHGATE),
                   row("receipt", "out", "36.00", "2026-08-09", SOUTHGATE, "photo"), *others)
    assert [(t.date_found, codes(t)) for t in rows] == [(None, [])] * len(rows)


@pytest.mark.parametrize("other", [lambda: claim_line("36.00", "2026-09-09", SOUTHGATE),
                                   lambda: bank("36.00", "2026-09-09", "SOUTHGATE BATH CAR PARK", ref="card",
                                                account="7400")])
def test_dates_more_than_a_year_apart_are_different_purchases(other):
    rows = matched(other(), row("receipt", "out", "36.00", "2025-08-01", SOUTHGATE, "photo"))
    assert [(t.date_found, codes(t)) for t in rows] == [(None, [])] * 2


def test_a_receipt_without_a_date_takes_the_date_of_its_card_payment():
    receipt, line = matched(undated(till()), bank("21.35", "2026-02-23", "MCDONALDS", ref="card", account="7406"))
    assert (line.recorded_by.ref, [p.ref for p in receipt.paid_by], receipt.date) == ("receipt", ["card"],
                                                                                       dt.date(2026, 2, 23))
    assert codes(receipt) == [("date_from_bank", "info")]


def test_a_receipt_dated_away_from_its_card_payment_asks_and_the_bank_line_does_not():
    # The bank's own date is taken as right: only the receipt asks.
    receipt, line = matched(till(date="2026-01-22"), bank("21.35", "2026-02-23", "MCDONALDS", ref="card", account="7406"))
    assert (line.recorded_by.ref, [p.ref for p in receipt.paid_by], booked(line)) == ("receipt", ["card"], False)
    assert (receipt.date_found, codes(receipt), about(receipt, "date_conflict")) == (dt.date(2026, 2, 23),
                                                                                      [("date_conflict", "warning")], [1])
    assert (line.date_found, codes(line)) == (None, [])
    said = next(i.message for i in receipt.issues if i.code == "date_conflict")
    assert all(d in said for d in ("23 Feb 2026", "22 Jan 2026"))


def test_a_claim_line_booked_as_well_as_its_receipt_warns_that_it_counts_twice():
    # Jenny's Southgate line stayed ticked: £36.00 was owed to her twice, and nothing said so.
    line, receipt = matched(claim_line("157.59", "2026-09-07", "Trainline", include=True),
                            row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket"))
    assert codes(line) == [("booked_twice", "warning")] and codes(receipt) == []
    assert about(line, "booked_twice") == [1]
    assert all(s in line.issues[0].message for s in ("£157.59", "Trainline", "7 Sep 2026", "Untick"))
    line, _ = matched(claim_line("157.59", "2026-09-07", "Trainline", include=True),   # a ticket without a date
                      undated(row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket")))
    assert codes(line) == [("booked_twice", "warning")]
    line, _ = matched(claim_line("157.59", "2026-09-07", "Trainline"),
                      row("receipt", "out", "157.59", "2026-09-07", "Trainline", "ticket"))
    assert codes(line) == []


def costco_on_the_sheet_and_the_card(**line):
    """Northbridge's Costco shop: the receipt, Priya's sheet line for it, and the Barclays card payment."""
    return (row("receipt", "out", "58.00", "2026-10-21", "Costco Wholesale UK Ltd", "costco", account="7504"),
            claim_line("58.00", "2026-10-21", "Costco - office supplies", account="7504"),
            bank(**{"gross": "58.00", "date": "2026-10-21", "who": "Costco", "ref": "card", "account": "7504", **line}))


def test_a_card_payment_for_a_receipt_the_claim_books_warns_that_it_counts_twice():
    # The sheet line took the receipt, so the card line was left to book the same shop again, into Suspense; only a
    # possible_payment hinted at it, and the review asked for a receipt that was already in.
    receipt, claim, line = matched(*costco_on_the_sheet_and_the_card())
    assert (receipt.claimed_in.ref, claim.recorded_by.ref, line.recorded_by, line.pays) == ("claim", "costco", None, [])
    assert ("booked_twice", "warning") in codes(line) and about(line, "booked_twice") == [0, 1]
    assert next(i.message for i in line.issues if i.code == "booked_twice") == (
        "Also booked from the expenses sheet's receipt (Costco Wholesale UK Ltd, £58.00, 21 Oct 2026). If this line "
        "paid it, drop the expenses sheet line: this line then pays the receipt.")
    assert "Keep one" not in next(i.message for i in line.issues if i.code == "booked_twice")
    assert [code for code, _ in codes(receipt) + codes(claim)].count("booked_twice") == 0


@pytest.mark.parametrize("line", [{"date": "2026-10-22"}, {"gross": "58.01"}, {"who": "Makro"}, {"link": []}])
def test_a_card_payment_that_differs_from_the_receipt_on_the_claim_is_not_booked_twice(line):
    *_, paid = matched(*costco_on_the_sheet_and_the_card(**line))
    assert "booked_twice" not in [code for code, _ in codes(paid)]


def test_once_the_sheet_line_is_left_out_the_card_payment_is_the_receipts():
    receipt, claim, line = costco_on_the_sheet_and_the_card()
    receipt, _, line = matched(receipt, claim.model_copy(update={"excluded": True}), line)
    assert (line.recorded_by.ref, codes(line)) == ("costco", [])


@pytest.mark.parametrize("receipt", [
    row("receipt", "out", "251.01", "2026-09-15", None, "log", description="Mileage, Farnham to Manchester and back"),
    row("receipt", "out", "251.01", "2026-09-16", "Somewhere Else Ltd", "log"),     # a name that says nothing
])
def test_a_receipt_pairs_with_its_claim_line_on_amount_and_date_whatever_its_name(receipt):
    # Matt's mileage logs name no shop, and names can differ even beyond initials: the amount and the date decide.
    line, receipt = matched(claim_line("251.01", "2026-09-15", "456.39 mi @ £0.55/mi", account="7300"), receipt)
    assert (line.recorded_by.ref, receipt.claimed_in.ref) == ("log", "claim")


def test_names_decide_between_records_of_the_same_amount_and_day():
    toll, lunch, pret, m6 = matched(claim_line("12.00", "2026-09-14", "M6toll (M42 to M6)"),
                                    claim_line("12.00", "2026-09-14", "Pret A Manger, lunch", account="7406"),
                                    row("receipt", "out", "12.00", "2026-09-14", "Pret A Manger", "pret", account="7406"),
                                    row("receipt", "out", "12.00", "2026-09-14", "M6toll", "toll"))
    assert (toll.recorded_by.ref, lunch.recorded_by.ref) == ("toll", "pret")


def test_without_a_name_the_nearest_date_decides():
    # Two EE bills of £27.50 were claimed, on 3 and 4 September; the bill of the 4th pairs with the line of the 4th.
    third, fourth, bill = matched(claim_line("27.50", "2026-09-03", "EE, mobile phone bill", account="7502"),
                                  claim_line("27.50", "2026-09-04", "EE, mobile phone bill", account="7502"),
                                  row("invoice", "out", "27.50", "2026-09-04", "EE", "bill", account="7502"))
    assert (third.recorded_by, fourth.recorded_by.ref) == (None, "bill")


def test_a_receipt_pairs_with_a_card_payment_on_amount_and_date_whatever_the_bank_calls_it():
    receipt, line = matched(till(), bank("21.35", "2026-02-23", "SQ *KIOSK 4471", ref="card", account="7406"))
    assert (line.recorded_by.ref, [p.ref for p in receipt.paid_by]) == ("receipt", ["card"])


@pytest.mark.parametrize("shop, read, claimed", [
    ("M6toll", "14.00", "12.00"),    # the toll receipt read as its £12.00 charge plus the £2.00 of VAT in it
    ("EE", "30.22", "27.50"),        # Matt claimed the £27.50 plan of a £30.22 phone bill
])
def test_a_receipt_and_its_claim_line_on_one_day_at_different_amounts_ask_which_is_right(shop, read, claimed):
    line, receipt = matched(claim_line(claimed, "2026-09-14", f"{shop}, charge"),
                            row("receipt", "out", read, "2026-09-14", shop, "doc"))
    # Until a person says, the purchase counts once: the claim line, what is owed, is booked and the receipt waits.
    # Both were booked, and Matt's phone bill counted twice.
    assert (booked(line), booked(receipt), receipt.recorded_by.ref, receipt.claimed_in) == (True, False, "claim", None)
    assert (receipt.amount_found, line.amount_found) == (Decimal(claimed), Decimal(read))
    assert (about(receipt, "amount_conflict"), about(line, "amount_conflict")) == ([0], [1])
    assert codes(receipt) == codes(line) == [("amount_conflict", "warning")]
    assert all(f"£{a}" in t.issues[0].message for a in (read, claimed) for t in (line, receipt))


def test_a_claim_line_its_claims_total_confirms_is_booked_as_claimed_when_its_bill_covers_it():
    # Matt claimed £27.50 of a £30.22 EE bill, and his claim's printed total adds up with £27.50: the company owes him
    # what he claimed, so that is booked, the bill backs it, and no one is asked.
    line, bill = matched(claim_line("27.50", "2026-09-03", "EE, mobile phone bill", account="7502", document_total="27.50"),
                         row("invoice", "out", "30.22", "2026-09-03", "EE", "bill", account="7502"))
    assert (booked(line), booked(bill), bill.recorded_by.ref, line.documented_by.ref) == (True, False, "claim", "bill")
    assert codes(line) == codes(bill) == [("claimed_less", "info")]
    assert (line.amount_found, bill.amount_found) == (None, None)
    assert all(s in line.issues[0].message for s in ("£27.50", "£30.22", "£2.72"))


@pytest.mark.parametrize("claimed,total,read", [
    ("32.00", "32.00", "30.22"),   # claimed more than the bill: the bill doesn't cover it
    ("27.50", None, "30.22"),      # no total on the claim confirms the line: it may be the misread one
])
def test_a_claim_line_its_bill_does_not_cover_or_its_total_does_not_confirm_still_asks(claimed, total, read):
    line, bill = matched(claim_line(claimed, "2026-09-03", "EE, mobile phone bill", account="7502",
                                    **({"document_total": total} if total else {})),
                         row("invoice", "out", read, "2026-09-03", "EE", "bill", account="7502"))
    assert codes(line) == codes(bill) == [("amount_conflict", "warning")]


@pytest.mark.parametrize("pair", [
    (lambda: claim_line("36.00", "2026-09-09", SOUTHGATE), lambda: row("receipt", "out", "36.00", "2026-09-09", SOUTHGATE, "p")),
    (lambda: claim_line("36.00", "2026-09-09", SOUTHGATE), lambda: row("receipt", "out", "36.00", "2026-08-09", SOUTHGATE, "p")),
    (lambda: claim_line("12.00", "2026-09-14", "M6toll"), lambda: row("receipt", "out", "14.00", "2026-09-14", "M6toll", "t")),
    (lambda: till(), lambda: bank("21.35", "2026-02-23", "MCDONALDS", ref="card", account="7406")),
    (lambda: till(date="2026-01-22"), lambda: bank("21.35", "2026-02-23", "MCDONALDS", ref="card", account="7406")),
])
def test_records_a_person_said_are_not_the_same_are_never_paired_or_asked_about(pair):
    rows = [normalise(make(), SETTINGS) for make in pair]
    for t in match(rows, SETTINGS, apart=[{1}, {0}]):
        assert (t.recorded_by, t.claimed_in, t.paid_by, t.date_found, t.amount_found, codes(t)) == (None, None, [], None, None, [])


@pytest.mark.parametrize("others", [
    [row("receipt", "out", "8.40", "2026-09-14", "Pret A Manger", "pret")],                 # another shop
    [row("receipt", "out", "14.00", "2026-09-14", "M6toll", "toll"),                        # more than one it could be
     claim_line("13.00", "2026-09-15", "M6toll")],
    [row("receipt", "out", "8.00", "2026-09-14", "M6toll", "toll"),                         # a receipt on two accounts:
     row("receipt", "out", "6.00", "2026-09-14", "M6toll", "toll", account="7406", people="one")],   # Use can't say which
])
def test_no_amount_is_asked_about_for_another_shop_or_when_more_than_one_record_could_be_the_one(others):
    rows = matched(claim_line("12.00", "2026-09-14", "M6toll"), *others)
    assert [(t.amount_found, codes(t)) for t in rows] == [(None, [])] * len(rows)


@pytest.mark.parametrize("receipt", [
    [till("14.00", who="Pret A Manger")],                                                    # another shop
    [till("8.00", who="M6toll"), till("6.00", who="M6toll").model_copy(update={"account_code": "7400"})],  # two accounts
])
def test_no_amount_is_asked_about_against_a_card_payment_of_another_shop_or_from_a_split_receipt(receipt):
    rows = matched(*receipt, bank("12.00", "2026-02-22", "M6TOLL", ref="card", account="7406"))
    assert [(t.amount_found, codes(t)) for t in rows] == [(None, [])] * len(rows)


def test_a_receipt_read_at_another_amount_than_its_card_payment_asks_and_the_bank_line_does_not():
    receipt, line = matched(till("14.00", who="M6toll"), bank("12.00", "2026-02-22", "M6TOLL", ref="card", account="7406"))
    assert (booked(line), booked(receipt), receipt.recorded_by.ref, line.recorded_by) == (True, False, "card", None)
    assert (receipt.amount_found, codes(receipt), about(receipt, "amount_conflict")) == (
        Decimal("12.00"), [("amount_conflict", "warning")], [1])
    assert (line.amount_found, codes(line)) == (None, [])


@pytest.mark.parametrize("include", [False, True])
def test_a_claim_line_booked_from_its_bill_has_no_vat_notes_of_its_own(include):
    # Fawsley Hall's line on Matt's claim said Unusual VAT, as did the hotel's own bill: one cause, said twice. The
    # line books nothing of its own unless it is ticked.
    line, _ = matched(claim_line("381.86", "2026-09-18", "Fawsley Hall Hotel & Spa", account="7402", vat="62.35",
                                 include=include),
                      row("invoice", "out", "381.86", "2026-09-18", "Fawsley Hall Hotel & Spa", "bill", account="7402",
                          vat="62.35"))
    assert ("vat_rate_mismatch" in [c for c, _ in codes(line)]) == include


def test_the_claimants_own_name_does_not_make_a_bill_the_shop_of_a_claim_line():
    # Barnes Plumbing's bill was taken for Matt Barnes's claim line on the same day, as his name is on every line.
    line, plumber = matched(row("expense_claim", "out", "300.00", "2026-10-01", "Matt Barnes", "claim", account="7402",
                                description="Matt Barnes - Clayton Hotel, rooms"),
                            row("invoice", "out", "200.00", "2026-10-01", "Barnes Plumbing", "plumber", account="7800"))
    assert [(t.amount_found, t.recorded_by, codes(t)) for t in (line, plumber)] == [(None, None, [])] * 2


def test_vat_on_the_claim_that_the_receipt_does_not_show_is_booked_as_claimed_and_an_invoice_asked_for():
    # The hotel "receipt" was a check-in email; the claim shows VAT £28.96. The claim is the person's record of it.
    _, receipt = matched(claim_line("173.75", "2026-09-14", "Clayton Hotel Manchester", account="7402", vat="28.96"),
                         row("receipt", "out", "173.75", "2026-09-14", "Clayton Hotel Manchester City Centre", "email",
                             account="7402"))
    assert codes(receipt) == [("claim_vat", "warning")]
    assert "£28.96" in receipt.issues[0].message and "Get a VAT invoice" in receipt.issues[0].message
    assert (receipt.vat_posted, receipt.net, receipt.vat_from_claim) == (Decimal("28.96"), Decimal("144.79"), True)
    assert document_rule(receipt, SETTINGS).reclaim_vat is True


def test_a_fare_takes_no_vat_from_the_claim_and_a_receipt_showing_nil_vat_keeps_it():
    _, flight = matched(claim_line("173.75", "2026-09-14", "British Airways", vat="28.96"),
                        row("receipt", "out", "173.75", "2026-09-14", "British Airways", "ticket", account="7400",
                            description="British Airways flight Glasgow to London"))
    assert (flight.vat_posted, flight.vat_from_claim) == (Decimal("0.00"), False)
    _, nil = matched(claim_line("173.75", "2026-09-14", "Clayton Hotel Manchester", account="7402", vat="28.96"),
                     row("receipt", "out", "173.75", "2026-09-14", "Clayton Hotel Manchester City Centre", "email",
                         account="7402", vat="0.00"))
    assert (nil.vat_posted, nil.vat_from_claim, codes(nil)) == (Decimal("0.00"), False, [("claim_vat", "warning")])


def test_vat_on_the_claim_only_is_not_flagged_once_a_person_says_it_is_fine():
    receipt = row("receipt", "out", "173.75", "2026-09-14", "Clayton Hotel Manchester City Centre", "email",
                  account="7402").model_copy(update={"accepted": ["claim_vat"]})
    _, receipt = matched(claim_line("173.75", "2026-09-14", "Clayton Hotel Manchester", account="7402", vat="28.96"),
                         receipt)
    assert codes(receipt) == [] and receipt.vat_posted == Decimal("28.96")   # booked as claimed, and nothing said


@pytest.mark.parametrize("shows", [{"supplier_vat_number": "731919917"}, {"vat_stated": True}])
def test_a_small_receipt_that_shows_vat_is_included_is_not_asked_for_a_vat_invoice_when_the_claim_agrees(shows):
    # Jenny's Bagel Factory receipt (£8.69) prints the VAT number and "All prices inclusive of VAT" but no VAT
    # amount; her claim shows VAT £1.45. Up to £250 the receipt is a VAT invoice in its own right, and its own 20%
    # gives the claim's figure: booked from the receipt, with no warning that the receipt shows none.
    _, receipt = matched(claim_line("8.69", "2026-10-07", "The Bagel Factory, ExCeL London", account="7406",
                                    vat="1.45"),
                         row("receipt", "out", "8.69", "2026-10-07", "The Bagel Factory", "bagel", account="7406", people="one",
                             **shows))
    assert codes(receipt) == [("vat_implied", "info")]
    assert (receipt.vat_posted, receipt.vat_from_claim) == (Decimal("1.45"), False)
    assert document_rule(receipt, SETTINGS).reclaim_vat is True


def test_a_small_receipt_that_shows_vat_is_included_still_says_so_when_the_claims_vat_differs():
    # The receipt's own 20% is £1.45; the claim says £1.00. Which is right is for a person to say.
    _, receipt = matched(claim_line("8.69", "2026-10-07", "The Bagel Factory", account="7406", vat="1.00"),
                         row("receipt", "out", "8.69", "2026-10-07", "The Bagel Factory", "bagel", account="7406",
                             supplier_vat_number="731919917"))
    assert ("claim_vat", "warning") in codes(receipt)


def amazon_order(settings=SETTINGS, account="7504", **receipt):
    """Jenny's second Amazon order: the claim shows VAT £3.00; the receipt prints no VAT, only its prices."""
    rows = [claim_line("17.99", "2026-09-11", "Amazon (seller: BengBuShiYouSheng), A4 leaflet holder", account=account,
                       vat="3.00"),
            row("receipt", "out", "17.99", "2026-09-11", "Amazon.co.uk", "order", account=account, **receipt)]
    first = match([normalise(t, settings) for t in rows], settings)
    again = match([normalise(t, settings) for t in first], settings)    # every pass works it out afresh
    assert [(t.vat_posted, t.vat_found, codes(t)) for t in again] == [(t.vat_posted, t.vat_found, codes(t)) for t in first]
    return first[1]


def test_vat_the_claim_and_the_receipts_own_prices_agree_on_is_booked():
    receipt = amazon_order(document_net="14.99")   # £14.99 before VAT, £17.99 in all: £3.00, as the claim shows
    assert (receipt.vat, receipt.vat_posted, receipt.net) == (None, Decimal("3.00"), Decimal("14.99"))
    assert codes(receipt) == [("vat_worked_out", "info")]
    assert all(s in receipt.issues[0].message for s in ("£3.00", "£14.99", "£17.99"))


def test_vat_on_a_receipt_that_says_it_is_not_a_vat_invoice_is_offered_not_booked():
    # The Amazon receipt says "This is not a VAT invoice": the £3.00 can be reclaimed only with the VAT invoice.
    receipt = amazon_order(document_net="14.99", not_vat_invoice=True)
    assert (receipt.vat_posted, receipt.vat_found) == (Decimal("0.00"), Decimal("3.00"))
    assert codes(receipt) == [("not_vat_invoice", "warning")]
    assert all(s in receipt.issues[0].message for s in ("£3.00", "£14.99", "£17.99", "Book VAT"))


@pytest.mark.parametrize("prices", [{}, {"document_net": "15.00"}])     # no price before VAT, or £2.99 of VAT
def test_prices_that_do_not_show_the_claims_vat_book_it_as_claimed_and_ask_for_an_invoice(prices):
    receipt = amazon_order(**prices)
    assert (receipt.vat_posted, receipt.vat_found, codes(receipt)) == (Decimal("3.00"), None, [("claim_vat", "warning")])
    assert "Get a VAT invoice" in receipt.issues[0].message


def test_a_receipt_that_shows_no_vat_charged_leaves_the_claims_vat_unbooked():
    receipt = amazon_order(document_net="14.99", vat="0.00")
    assert (receipt.vat_posted, receipt.vat_found, codes(receipt)) == (Decimal("0.00"), None, [("claim_vat", "warning")])


@pytest.mark.parametrize("settings, account", [(BusinessSettings(vat_registered=False), "7504"),
                                               (SETTINGS, "7403")])     # entertainment: VAT can't be reclaimed
def test_no_vat_is_worked_out_where_none_could_be_booked(settings, account):
    for flag in (False, True):
        receipt = amazon_order(settings, account, document_net="14.99", not_vat_invoice=flag)
        assert (receipt.vat_posted, receipt.vat_found) == (Decimal("0.00"), None)
        assert not {"vat_worked_out", "not_vat_invoice"} & {code for code, _ in codes(receipt)}


def test_vat_is_not_worked_out_for_a_receipt_split_over_accounts():
    # One price before VAT for the whole receipt can't say how its VAT divides between the accounts.
    line, *parts = matched(claim_line("17.99", "2026-09-11", "Amazon", account="7504", vat="3.00"),
                           row("receipt", "out", "12.00", "2026-09-11", "Amazon.co.uk", "order", account="7504",
                               document_net="14.99"),
                           row("receipt", "out", "5.99", "2026-09-11", "Amazon.co.uk", "order", account="7500",
                               document_net="14.99"))
    assert line.recorded_by.ref == "order"
    assert [(p.vat_posted, p.vat_found) for p in parts] == [(Decimal("0.00"), None)] * 2
    assert codes(parts[0]) == [("claim_vat", "warning")]


def test_a_document_that_does_not_add_up_says_once_what_is_missing():
    # A claim totalling £1,048.52 came back with a line missing: all twelve lines said "add up to £994.52 but its
    # total is £1048.52", and the warning could not go away once the missing line was added by hand.
    first, second = matched(claim_line("36.00", "2026-09-09", "Southgate Bath Car Park", document_total="120.90"),
                            claim_line("30.90", "2026-09-30", "Transport for London", document_total="120.90"))
    assert codes(first) == [("total_mismatch", "warning")] and codes(second) == []
    assert about(first, "total_mismatch") == [1]                # Show its lines
    assert first.issues[0].message == "Lines total £66.90; the claim's total is £120.90. £54.00 missing: add the line."
    # No one line explains it, so it is the claim's problem, not the first line's; and it says by how much.
    assert (first.issues[0].about, first.issues[0].difference) == ("document", Decimal("54.00"))


def test_a_total_problem_a_row_explains_stays_about_the_row():
    *_, twice = matched(*(claim_line(gross, date, "Southgate", document_total="90.00") for gross, date in (
        ("36.00", "2026-09-09"), ("54.00", "2026-09-24"), ("54.00", "2026-09-24"))))
    assert (twice.issues[0].about, twice.issues[0].difference) == ("row", Decimal("-54.00"))


def test_an_agents_statement_that_does_not_net_is_about_the_document():
    first, *_ = matched(*(t.model_copy(update={"document_total": Decimal("600.00")}) for t in agent_statement()))
    [found] = [i for i in first.issues if i.code == "total_mismatch"]
    assert (found.about, found.difference) == ("document", Decimal("73.25"))


def test_a_total_put_out_by_a_changed_line_is_said_on_that_line():
    # Matt's EE line was changed from £27.50 to £30.22: the warning sat on the claim's first line, the hotel.
    rows = [normalise(t, SETTINGS) for t in (claim_line("173.75", "2026-09-14", "Clayton Hotel", document_total="201.25"),
                                              claim_line("30.22", "2026-09-03", "EE, mobile phone bill",
                                                         document_total="201.25"))]
    hotel, ee = match(rows, SETTINGS, read=[None, Decimal("27.50")])
    assert (codes(hotel), codes(ee), about(ee, "total_mismatch")) == ([], [("total_mismatch", "warning")], [0])
    assert all(s in ee.issues[0].message for s in ("£27.50", "£30.22", "Revert"))


def test_each_warning_on_a_row_points_at_its_own_rows():
    # Matt's EE line, ticked and changed to £30.22, said Booked twice and Total doesn't add up; Show both on Booked
    # twice showed all 24 rows of his claim, as the row kept one list for both.
    rows = [normalise(t, SETTINGS) for t in (
        claim_line("173.75", "2026-09-14", "Clayton Hotel", account="7402", document_total="201.25"),
        claim_line("30.22", "2026-09-03", "EE, mobile phone bill", account="7502", document_total="201.25", include=True),
        row("invoice", "out", "30.22", "2026-09-03", "EE", "bill", account="7502"))]
    _, ee, _ = match(rows, SETTINGS, read=[None, Decimal("27.50"), None])
    assert (about(ee, "booked_twice"), about(ee, "total_mismatch")) == ([2], [0])


def test_a_line_read_twice_is_named_by_the_total():
    first, once, twice = matched(*(claim_line(gross, date, shop, document_total="90.00") for gross, date, shop in (
        ("36.00", "2026-09-09", "Southgate"), ("54.00", "2026-09-24", "Southgate"), ("54.00", "2026-09-24", "Southgate"))))
    assert (codes(first), codes(once), codes(twice), about(twice, "total_mismatch")) == (
        [], [], [("total_mismatch", "warning")], [1])
    assert "twice" in twice.issues[0].message


def test_a_line_a_decision_left_out_is_not_missing_from_the_claim():
    # The 42.00 line was excluded in favour of its invoice; the claim's 60.00 total is still the sheet's, and the kept
    # 18.00 line must not be told that 42.00 is missing.
    kept, = [t for t in matched(claim_line("42.00", "2026-10-02", "Pagecraft", document_total="60.00", excluded=True),
                                claim_line("18.00", "2026-10-03", "Taxi", document_total="60.00"))
             if not t.excluded]
    assert codes(kept) == []


def test_a_claim_read_twice_is_still_named_by_the_total_and_clears_once_the_copy_is_left_out():
    lines = [claim_line(gross, date, "Southgate", document_total="90.00") for gross, date in (
        ("36.00", "2026-09-09"), ("54.00", "2026-09-24"), ("54.00", "2026-09-24"))]
    assert "Repeats another line" in matched(*lines)[2].issues[0].message
    after = matched(lines[0], lines[1], lines[2].model_copy(update={"excluded": True}))
    assert [codes(t) for t in after] == [[], [], []]


def test_a_total_the_kept_and_left_out_lines_do_not_reach_is_still_flagged():
    kept = [t for t in matched(claim_line("42.00", "2026-10-02", "Pagecraft", document_total="80.00", excluded=True),
                               claim_line("18.00", "2026-10-03", "Taxi", document_total="80.00"))
            if not t.excluded]
    assert codes(kept[0]) == [("total_mismatch", "warning")]


def test_a_line_that_was_split_is_not_counted_twice_as_left_out():
    # Printed 100.00 but only a 50.00 line was read: 50.00 is missing. Splitting that line into 30.00 + 20.00 keeps
    # its document_ref and adds up to it; the replaced row must not make up the 50.00 that is missing.
    original = claim_line("50.00", "2026-10-02", "Pagecraft", document_total="100.00", superseded_by="d1")
    parts = [claim_line("30.00", "2026-10-02", "Pagecraft", document_total="100.00"),
             claim_line("20.00", "2026-10-02", "Pagecraft", document_total="100.00")]
    rows = matched(original, *parts)
    assert "£50.00 missing" in rows[1].issues[0].message


def test_a_line_left_out_the_other_way_is_taken_off_not_added():
    # Printed 90.00: 80.00 out is kept, a 10.00 refund line (in) is excluded. The net is 70.00, so 20.00 is short.
    rows = matched(claim_line("80.00", "2026-10-02", "Pagecraft", document_total="90.00"),
                   row("expense_claim", "in", "10.00", "2026-10-03", "Jenny Hogg", "claim", account="7400",
                       description="Jenny Hogg - Refund", document_total="90.00", excluded=True))
    assert [c for c, _ in codes(rows[0])] == ["total_mismatch"]


def test_the_gap_a_warning_names_is_net_of_what_was_left_out():
    kept = matched(claim_line("42.00", "2026-10-02", "Pagecraft", document_total="80.00", excluded=True),
                   claim_line("18.00", "2026-10-03", "Taxi", document_total="80.00"))[1]
    assert "£20.00 missing" in kept.issues[0].message and "£62.00" not in kept.issues[0].message


def test_lines_short_of_the_total_with_nothing_left_out_still_warn():
    first, _ = matched(claim_line("18.00", "2026-10-03", "Taxi", document_total="70.00"),
                       claim_line("42.00", "2026-10-02", "Pagecraft", document_total="70.00"))
    assert [c for c, _ in codes(first)] == ["total_mismatch"]


def test_a_line_whose_amount_is_the_surplus_is_asked_about():
    first, odd = matched(claim_line("36.00", "2026-09-09", "Southgate", document_total="36.00"),
                         claim_line("12.00", "2026-09-14", "M6toll", document_total="36.00"))
    assert (codes(first), codes(odd)) == ([], [("total_mismatch", "warning")])
    assert "belongs" in odd.issues[0].message


def test_a_bill_set_to_the_part_of_it_that_is_claimed_does_not_say_its_total_is_out():
    # Matt claimed £27.50 of a £30.22 EE bill; choosing the claim's £27.50 set the bill to it, and the bill then said
    # its rows came to less than its printed £30.22. On a claim, a document books what the claim says.
    line, bill = matched(claim_line("27.50", "2026-09-03", "EE, mobile phone bill", account="7502"),
                         row("invoice", "out", "27.50", "2026-09-03", "EE", "bill", account="7502", document_total="30.22"))
    assert (bill.claimed_in.ref, codes(bill)) == ("claim", [])


def test_adding_the_missing_line_clears_the_total_warning():
    rows = matched(claim_line("36.00", "2026-09-09", "Southgate Bath Car Park", document_total="120.90"),
                   claim_line("30.90", "2026-09-30", "Transport for London", document_total="120.90"),
                   claim_line("54.00", "2026-09-24", "Southgate Bath Car Park"))   # added by hand
    assert [codes(t) for t in rows] == [[], [], []]


def test_a_document_with_too_much_says_so():
    [only] = matched(bill("130.00", document_total="120.90", who="BT"))
    assert only.issues[0].message == "Rows total £130.00; the invoice's total is £120.90. £9.10 over: remove a duplicate or fix an amount."


def test_a_part_payment_matches_only_within_120_days():
    invoice = helper_row(date=dt.date(2026, 1, 10), counterparty="Smith Solicitors Ltd", gross=Decimal("1200.00"),
                         document_type="invoice", document_ref="d1")
    part = helper_row(date=dt.date(2026, 4, 1), counterparty="Smith Solicitors", gross=Decimal("600.00"),
                      document_type="statement")
    late = part.model_copy(update={"date": dt.date(2026, 6, 1)})
    assert match_one(invoice, part).pays
    assert not match_one(invoice, late).pays


def test_an_unmatched_line_to_someone_with_an_open_invoice_is_never_silent():
    invoice = helper_row(date=dt.date(2026, 1, 10), counterparty="Smith Solicitors Ltd", gross=Decimal("1200.00"),
                         description="Smith Solicitors invoice", document_type="invoice", document_ref="d1")
    line = helper_row(date=dt.date(2026, 8, 1), counterparty="Smith Solicitors", gross=Decimal("450.00"),
                      document_type="statement")
    issue = only_issue(match_one(invoice, line), "open_document")
    assert issue.severity == "warning" and "Smith" in issue.message


# ─── Transfers between the client's own accounts ──────────────────────────────

TWO_BANKS = HELPER_SETTINGS.model_copy(update={"bank_accounts": ("1200", "1210")})


def transfer(**out_changes):
    """£5,000 moved from the current account (1200) to the savings account (1210), on both statements."""
    out = helper_row(**{**dict(gross=Decimal("5000.00"), account_code="1210", bank_account="1200",
                               document_type="statement", description="To savings", document_ref="a"), **out_changes})
    into = helper_row(direction="in", gross=Decimal("5000.00"), account_code="1200", bank_account="1210",
                      document_type="statement", description="From current", document_ref="b",
                      date=dt.date(2026, 1, 2))
    return out, into


def test_a_transfer_between_the_clients_own_accounts_books_once():
    out, into = transfer()
    tb = trial_balance([out, into], TWO_BANKS)
    assert net(tb, "1200") == Decimal("-5000.00") and net(tb, "1210") == Decimal("5000.00")


def test_the_second_side_of_a_transfer_says_it_is_booked_from_the_first():
    out, into = transfer()
    for rows in ([out, into], [into, out]):   # whichever order the statements arrived in
        ready = {tx.document_ref: tx for tx in normalise_and_match(rows, TWO_BANKS)}
        assert booked(ready["a"]) and not booked(ready["b"]) and ready["b"].recorded_by.ref == "a"
        found = only_issue(ready["b"], "transfer")
        assert (found.severity, found.message) == ("info", "The other side of To savings on 1 Jan 2026: booked once, "
                                                           "from that line.")
        assert not [i for i in ready["a"].issues + ready["b"].issues if i.severity == "error"]


@pytest.mark.parametrize("changes", [{"gross": Decimal("4999.00")}, {"date": dt.date(2025, 12, 29)},
                                     {"direction": "in"}])
def test_lines_that_differ_in_amount_date_or_direction_are_not_a_transfer(changes):
    out, into = transfer(**changes)
    ready = normalise_and_match([out, into], TWO_BANKS)
    assert all(tx.recorded_by is None for tx in ready)


def test_a_transfer_line_is_not_taken_as_a_payment_of_an_invoice():
    invoice = helper_row(gross=Decimal("5000.00"), account_code="7600", document_type="invoice", document_ref="i",
                         counterparty="Savings", date=dt.date(2025, 12, 1))
    out, into = transfer(counterparty="Savings")
    ready = {tx.document_ref: tx for tx in normalise_and_match([invoice, out, into], TWO_BANKS)}
    assert ready["a"].pays == [] and ready["i"].owed == Decimal("5000.00")


BANK_AND_CARD = HELPER_SETTINGS.model_copy(update={"bank_accounts": ("1200", "1240")})


def _card_payoff(bank_account="7501"):
    """The card paid off from the current account: the card's statement codes its payment in to 1200; the bank's
    direct debit to the card company was coded as something else."""
    out = helper_row(gross=Decimal("1749.40"), account_code=bank_account, bank_account="1200",
                     document_type="statement", description="Calder Express delivery", counterparty="Calder Express",
                     document_ref="dd", date=dt.date(2023, 4, 25))
    into = helper_row(direction="in", gross=Decimal("1749.40"), account_code="1200", bank_account="1240",
                      document_type="statement", description="Payment received - thank you", document_ref="pay",
                      date=dt.date(2023, 4, 25))
    return out, into


def test_a_card_paid_off_from_the_bank_is_a_transfer_when_one_side_says_so():
    # The test books' agency year: every month's direct debit to the card company was coded as courier costs, though
    # the card's statement showed the payment in from the bank; the money left the bank twice (about £12,850).
    out, into = _card_payoff()
    ready = {tx.document_ref: tx for tx in normalise_and_match([out, into], BANK_AND_CARD)}
    assert ready["dd"].account_code == "1240" and booked(ready["dd"]) and ready["pay"].recorded_by.ref == "dd"
    assert "Recoded" in only_issue(ready["dd"], "transfer").message
    assert not [i for t in ready.values() for i in t.issues if i.severity == "error" or i.code == "needs_document"]
    tb = trial_balance([out, into], BANK_AND_CARD)
    assert (net(tb, "1200"), net(tb, "1240"), net(tb, "7501")) == (Decimal("-1749.40"), Decimal("1749.40"), 0)


def test_the_card_side_is_recoded_when_the_bank_side_says_so():
    out, into = _card_payoff(bank_account="1240")
    into = into.model_copy(update={"account_code": "4000"})   # the card's payment in, read as a sale
    ready = {tx.document_ref: tx for tx in normalise_and_match([out, into], BANK_AND_CARD)}
    assert ready["pay"].account_code == "1200" and ready["pay"].recorded_by.ref == "dd" and booked(ready["dd"])
    [note] = [i for i in ready["pay"].issues if i.code == "transfer"]
    assert "Recoded from" in note.message and "booked once" in note.message


def test_a_line_coded_to_another_of_the_clients_accounts_is_not_recoded():
    # Both sides on own accounts but not each other's: not this case, nothing changes.
    out, into = _card_payoff(bank_account="1210")
    ready = {tx.document_ref: tx for tx in normalise_and_match(
        [out, into], HELPER_SETTINGS.model_copy(update={"bank_accounts": ("1200", "1210", "1240")}))}
    assert ready["dd"].account_code == "1210" and ready["pay"].recorded_by is None


def test_a_transfer_for_a_client_with_one_account_is_not_paired():
    out, into = transfer()
    ready = normalise_and_match([out, into], HELPER_SETTINGS)
    assert all(tx.recorded_by is None for tx in ready)


def test_a_card_payment_paired_with_its_receipt_is_booked_against_the_card():
    receipt = helper_row(gross=Decimal("24.00"), account_code="7504", counterparty="Ryman", document_ref="r")
    card = helper_row(gross=Decimal("24.00"), account_code="7504", counterparty="RYMAN", document_type="statement",
                      bank_account="1240", document_ref="c")
    settings = HELPER_SETTINGS.model_copy(update={"bank_accounts": ("1200", "1240")})
    tb = trial_balance([receipt, card], settings)
    assert net(tb, "1240") == Decimal("-24.00") and net(tb, "1200") == Decimal("0")


# ─── Rows a decision left out of the books ─────────────────────────────────────

@pytest.mark.parametrize("left_out", [{"excluded": True}, {"superseded_by": "d1"}])
def test_a_bank_line_left_out_of_the_books_pays_nothing(left_out):
    open_bill, line = matched(bill(), bank(**left_out))
    assert line.pays == [] and line.paid_against is None and codes(line) == []
    assert open_bill.owed == Decimal("12000.00") and open_bill.paid_by == []


def test_a_bill_left_out_of_the_books_is_not_paid():
    left_out, line = matched(bill(excluded=True), bank())
    assert line.pays == [] and left_out.owed is None


def test_a_left_out_line_is_not_one_side_of_a_transfer():
    out, into = transfer()
    ready = {tx.document_ref: tx for tx in normalise_and_match([out, into.model_copy(update={"excluded": True})],
                                                               TWO_BANKS)}
    assert ready["a"].recorded_by is None and ready["b"].recorded_by is None
    assert not any(i.code == "transfer" for tx in ready.values() for i in tx.issues)


def test_a_left_out_claim_line_is_not_recorded_by_its_receipt():
    receipt = row("receipt", "out", "64.80", "2026-10-07", "Costco", "r", account="7504")
    line = row("expense_claim", "out", "64.80", "2026-10-07", "Priya Shah", "claim", account="7504",
               description="Costco office supplies", excluded=True)
    ready_receipt, ready_line = matched(receipt, line)
    assert ready_line.recorded_by is None and ready_receipt.claimed_in is None


def test_issues_point_at_the_right_rows_when_a_row_before_them_is_left_out():
    """The places an issue names are places in all the rows, not in those left once the left-out ones are set aside."""
    out, into = transfer()
    gone = bank(gross="5000.00", ref="gone", excluded=True)
    ready = normalise_and_match([gone, out, into], TWO_BANKS)
    assert about(ready[2], "transfer") == [1]
    assert ready[0] == normalise(gone, TWO_BANKS)


def unclear_card_line(**kw):
    """A card line read onto Suspense, as the reader does for a shop it can't place, that warns the account is unclear."""
    return bank("64.00", "2026-10-19", "COSTCO", ref="card", account="9998",
                issues=[issue("account_not_recognised", "Account unclear: put in Suspense. Choose one.")], **kw)


def test_a_bank_line_its_receipt_records_no_longer_asks_for_an_account():
    # It posts nothing, so its account has no effect on the books: there is nothing to ask.
    receipt = row("receipt", "out", "64.00", "2026-10-19", "Costco", "r", account="7504", document_total="64.00")
    ready_receipt, line = matched(receipt, unclear_card_line())
    assert (line.recorded_by.ref, booked(line)) == ("r", False)
    assert "account_not_recognised" not in [i.code for i in line.issues]


def test_a_ticked_bank_line_its_receipt_records_keeps_asking_for_an_account():
    receipt = row("receipt", "out", "64.00", "2026-10-19", "Costco", "r", account="7504", document_total="64.00")
    _, line = matched(receipt, unclear_card_line(include=True))
    assert line.recorded_by.ref == "r" and "account_not_recognised" in [i.code for i in line.issues]


def test_a_bank_line_with_no_receipt_keeps_asking_for_an_account():
    [line] = matched(unclear_card_line())
    assert line.recorded_by is None and "account_not_recognised" in [i.code for i in line.issues]


def test_a_bank_line_its_receipt_records_keeps_its_other_issues():
    receipt = row("receipt", "out", "64.00", "2026-10-19", "Costco", "r", account="7504", document_total="64.00")
    line = bank("64.00", "2026-10-19", "COSTCO", ref="card", account="9998",
                issues=[issue("account_not_recognised", "Account unclear."), issue("read_note", "Read from a blurred photo.")])
    _, ready = matched(receipt, line)
    assert [i.code for i in ready.issues] == ["read_note"]


def test_a_bank_line_its_receipt_records_drops_the_unclear_account_issue_too():
    receipt = row("receipt", "out", "64.00", "2026-10-19", "Costco", "r", account="7504", document_total="64.00")
    line = bank("64.00", "2026-10-19", "COSTCO", ref="card", account="9998",
                issues=[issue("account_unclear", "Account unclear: put in Suspense. Choose one.")])
    _, ready = matched(receipt, line)
    assert ready.recorded_by.ref == "r" and "account_unclear" not in [i.code for i in ready.issues]


# ─── A payment processor's payout and its report ──────────────────────────────

def _payout_line():
    return Transaction(date=dt.date(2026, 10, 15), description="Stripe payout", direction="in", gross="1163.10",
                       account_code="1250", document_type="statement", counterparty="Stripe Payments UK")


def test_a_payout_with_no_report_asks_for_it():
    [line] = match([normalise(_payout_line(), SETTINGS)], SETTINGS)
    [found] = [i for i in line.issues if i.code == "payout_report"]
    assert found.message == ("A Stripe payout is sales less Stripe's fees and refunds: upload the Stripe payout "
                             "report for 15 Oct 2026, so they are booked. Held in Payment Processor Clearing until then.")


def test_the_payout_report_books_the_sales_and_fees_and_clears_the_payout():
    report = dict(document_type="agent_statement", agent="Stripe", document_total=Decimal("1163.10"),
                  document_ref="po", date=dt.date(2026, 10, 15))
    rows = [Transaction(description="Card sales", direction="in", gross="1200.00", account_code="4000",
                        counterparty="Customers", **report),
            Transaction(description="Stripe fees", direction="out", gross="36.90", account_code="7901",
                        counterparty="Stripe", **report),
            _payout_line()]
    tb = trial_balance(rows, SETTINGS)
    assert (net(tb, "4000"), net(tb, "7901"), net(tb, "1250"), net(tb, "1100"), net(tb, "1200")) == (
        Decimal("-1200.00"), Decimal("36.90"), 0, 0, Decimal("1163.10"))
    line = match([normalise(t, SETTINGS) for t in rows], SETTINGS)[2]
    assert "payout_report" not in [i.code for i in line.issues]


def test_what_a_processor_holds_is_in_payment_processor_clearing_not_debtors():
    # The agency's Stripe charges of the last days of March 2024, not paid out until April: the customers had paid,
    # so the £2,127 Stripe held is not owed by them. It sat on Debtors, where the payout without a report would have
    # held it on Payment Processor Clearing (agency run, 25 Nov 2026).
    report = dict(document_type="agent_statement", agent="Stripe", document_ref="po", date=dt.date(2026, 10, 15))
    rows = [Transaction(description="Card sales", direction="in", gross="1200.00", account_code="4000",
                        counterparty="Customers", **report),
            Transaction(description="Stripe fees", direction="out", gross="36.90", account_code="7901",
                        counterparty="Stripe", **report)]
    tb = trial_balance(rows, SETTINGS)
    assert (net(tb, "1250"), net(tb, "1100")) == (Decimal("1163.10"), 0)


def _stripe_charges(month):
    """A month of Stripe's balance export as the reader saves it: each charge and its fee a document of their own."""
    return [row("agent_statement", direction, gross, f"2023-{month:02d}-{day:02d}", "Stripe Payments UK",
                f"{month}-{day}", account=account, agent="Stripe")
            for day, sale, fee in ((4, "720.00", "11.00"), (5, "1080.00", "16.40"), (6, "540.00", "8.30"),
                                   (7, "900.00", "13.70"))
            for direction, gross, account in (("in", sale, "4000"), ("out", fee, "7901"))]


def _stripe_payout(gross, date, ref):
    return bank(gross, date, "STRIPE PAYMENTS UK", ref, direction="in", account="1250")


def test_a_processor_payout_pays_out_what_it_holds_oldest_first():
    # The test books' agency year: Stripe paid out the £640 it held at the year start, then £3,190.60, the four
    # days' charges after fees. The £640 was taken as part of the first day's £709, so the four days no longer added
    # up to £3,190.60, and every later payout was asked about.
    *charges, opening, payout = matched(*_stripe_charges(4), _stripe_payout("640.00", "2023-04-04", "po-1"),
                                        _stripe_payout("3190.60", "2023-04-11", "po-2"))
    assert opening.pays == [] and "part_payment" not in [i.code for i in opening.issues]   # what it held before
    assert sorted(p.ref for p in payout.pays) == ["4-4", "4-5", "4-6", "4-7"] and codes(payout) == []
    assert {t.owed for t in charges} == {Decimal("0.00")}


# ─── A receipt cut off before its total ───────────────────────────────────────

def _cut_off_receipt(gross="72.00"):
    return Transaction(date=dt.date(2026, 10, 3), description="Screwfix", direction="out", gross=gross,
                       account_code="5000", document_type="receipt", counterparty="Screwfix Direct",
                       document_total=gross, document_net="72.00", supplier_vat_number="GB232415508",
                       document_ref="sf")


def _card_line(gross="86.40"):
    return Transaction(date=dt.date(2026, 10, 3), description="Screwfix card payment", direction="out", gross=gross,
                       account_code="5000", document_type="statement", counterparty="Screwfix Direct")


def test_a_receipt_read_at_its_subtotal_is_the_document_for_the_bank_line_that_adds_the_vat():
    # The reader took Screwfix's "Subtotal 72.00" as the total (the receipt is cut off at "VAT 20"); the bank paid
    # £86.40, £72.00 plus 20%. It was an amount conflict, held in Suspense, which the AI then "resolved" wrongly.
    receipt, line = match([normalise(t, SETTINGS) for t in (_cut_off_receipt(), _card_line())], SETTINGS)
    assert line.documented_by is not None and line.documented_by.ref == "sf" and booked(line)
    assert receipt.recorded_by is not None and not [i for i in receipt.issues if i.code == "amount_conflict"]
    [note] = [i for i in receipt.issues if i.code == "subtotal_only"]
    assert note.message == ("The receipt prints £72.00 before VAT and no total; the bank paid £86.40, which is £72.00 "
                            "plus VAT at 20%. Booked from the bank line with no VAT: get a complete copy to reclaim "
                            "the £14.40 VAT.")
    from ledgersync.evidence_rules import document_rule
    rule = document_rule(line, SETTINGS)
    assert (rule.action, rule.reclaim_vat) == ("book", False)


def test_a_bank_line_that_is_not_the_subtotal_plus_vat_is_still_a_conflict():
    receipt, line = match([normalise(t, SETTINGS) for t in (_cut_off_receipt(), _card_line("90.00"))], SETTINGS)
    assert line.documented_by is None
    assert [i.code for i in receipt.issues if i.code == "amount_conflict"] == ["amount_conflict"]


def ee_claim():
    """Matt's expenses sheet: two EE lines of £27.50, on 3 and 4 Sep, and a hotel line its invoice names otherwise."""
    return [row("expense_claim", "out", gross, date, "Matt Barnes", "sheet", description=what)
            for gross, date, what in (("27.50", "2026-09-03", "EE, mobile phone bill"),
                                      ("27.50", "2026-09-04", "EE, mobile phone bill"),
                                      ("2308.50", "2026-09-15", "Accommodation for October sales kick off"))]


def undated_bill(gross, ref, who="EE"):
    return Transaction(document_type="invoice", direction="out", gross=gross, date=None, counterparty=who,
                       document_ref=ref, account_code="7502", description=f"{who} bill")


def matched_named(rows, named):
    return match([normalise(t, SETTINGS) for t in rows], SETTINGS, name_days=named)


def test_an_undated_bill_pairs_with_the_one_claim_line_of_its_amount_on_its_file_names_day():
    rows = [*ee_claim(), undated_bill("27.50", "ee-4"), undated_bill("2308.50", "hotel", who=None)]
    named = [None, None, None, dt.date(2026, 9, 4), dt.date(2026, 9, 15)]
    third, fourth, hotel_line, bill, hotel = matched_named(rows, named)
    assert (bill.date, bill.claimed_in.ref, fourth.recorded_by.ref, third.recorded_by) == (
        dt.date(2026, 9, 4), "sheet", "ee-4", None)
    assert (hotel.date, hotel_line.recorded_by.ref) == (dt.date(2026, 9, 15), "hotel")
    assert ("date_from_claim", "info") in codes(bill)


def test_a_file_names_day_that_fits_two_lines_or_none_pairs_nothing():
    rows = [*ee_claim(), undated_bill("27.50", "a"), undated_bill("30.22", "b")]
    twice = [None, None, None, dt.date(2026, 9, 3), dt.date(2026, 9, 3)]
    *_, first, other = matched_named([*ee_claim(), undated_bill("27.50", "a"), undated_bill("27.50", "c")], twice)
    assert first.date is None and other.date is None   # two bills of £27.50 named 3 Sep: which is the line's?
    *_, wrong_amount = matched_named(rows, [None, None, None, None, dt.date(2026, 9, 3)])
    assert wrong_amount.date is None and wrong_amount.claimed_in is None


def test_a_payment_of_tax_or_to_the_owner_is_not_offered_as_a_suppliers_later_bill():
    # Kestrel: the director's £1,250.00 Self Assessment payment was offered as the payment of a £1,250.00 furniture
    # invoice dated eleven days later.
    later = bill(gross="1250.00", date="2026-10-14", who="Halden Furniture Ltd", ref="hf")
    tax = bank(gross="1250.00", date="2026-10-03", who="HMRC Self Assessment", ref="sa", account="2250")
    _, line = matched(later, tax)
    assert "possible_payment" not in [code for code, _ in codes(line)] and line.candidates == []
    # A payment to someone else coded as a cost is still offered: it may be that bill, paid before it was dated.
    _, cost = matched(later, bank(gross="1250.00", date="2026-10-03", who="Card payment", ref="c", account="0040"))
    assert codes(cost) == [("possible_payment", "warning")]


def test_a_dividend_to_the_director_does_not_pay_his_small_expenses_claim():
    # £8,000 to M Marlow coded to Dividends was matched to his £144 mileage claim as an "overpayment of £7,856".
    mileage = row("expense_claim", "out", "144.00", "2026-04-30", "Mark Marlow", "claim", account="7400",
                  document_total="144.00")
    dividend = bank("8000.00", "2026-07-15", "M Marlow", account="3250", description="M Marlow, dividend")
    claim_row, line = matched(mileage, dividend)
    assert line.pays == [] and line.paid_against is None and claim_row.owed == Decimal("144.00")
    assert codes(line) == [("open_document", "warning")]
    assert "the amount differs and the line is on Dividends" in line.issues[0].message


def test_a_payment_coded_to_the_owner_still_pays_a_claim_of_exactly_its_amount():
    mileage = row("expense_claim", "out", "144.00", "2026-04-30", "Mark Marlow", "claim", account="7400",
                  document_total="144.00")
    refund = bank("144.00", "2026-05-06", "M Marlow", account="2250", description="M Marlow expenses")
    claim_row, line = matched(mileage, refund)
    assert [p.amount for p in line.pays] == [Decimal("144.00")] and claim_row.owed == Decimal("0.00")


def test_a_line_on_two_overlapping_statements_is_booked_once_and_pays_once():
    # April to June, then June to July: June's lines are on both, each with the same balance after it.
    invoice = bill("3600.00", "2026-06-01", "Parkside Estates Ltd", "rent")
    first = bank("3600.00", "2026-06-01", "PARKSIDE ESTATES", "june-a", balance=Decimal("41439.23"))
    again = bank("3600.00", "2026-06-01", "PARKSIDE ESTATES", "june-b", balance=Decimal("41439.23"))
    other = bank("3600.00", "2026-06-01", "PARKSIDE ESTATES", "june-c", balance=Decimal("37839.23"))
    invoice, first, again, other = matched(invoice, first, again, other)
    assert first.copy_of is None and [p.amount for p in first.pays] == [Decimal("3600.00")]
    assert again.copy_of.ref == "june-a" and again.pays == [] and codes(again) == [("duplicate_document", "info")]
    assert other.copy_of is None          # another balance after it: a second payment that day
    assert invoice.owed == Decimal("0.00")


def test_a_repeated_line_a_person_included_or_one_without_a_balance_is_left_alone():
    first = bank("14.50", "2026-06-30", "NATWEST", "a", balance=Decimal("100.00"))
    included = bank("14.50", "2026-06-30", "NATWEST", "b", balance=Decimal("100.00"), include=True)
    plain = [bank("14.50", "2026-06-30", "NATWEST", ref) for ref in ("c", "d")]
    assert [t.copy_of for t in matched(first, included, *plain)] == [None, None, None, None]


def _fuel(**kw):
    return row("receipt", "out", "499.00", "2026-05-16", "Currys", "tv", account="0030", **kw)


def test_a_receipt_its_banks_statement_does_not_show_is_kept_off_the_bank():
    # The statement has lines either side of 16 May and no £499.00: the director's own card paid it, not the bank.
    lines = [bank("14.50", "2026-05-11", "NATWEST CHARGES", "a", account="7901"),
             bank("86.99", "2026-05-22", "SCREWFIX", "b", account="5000")]
    receipt, *_ = matched(_fuel(), *lines)
    assert receipt.contra_account_code == "9998" and codes(receipt) == [("not_on_statement", "warning")]
    assert receipt.issues[0].message.startswith(
        "Not on the Bank Current Account statement, which has lines either side of 16 May 2026: that account did "
        "not pay it. Kept off the bank, in Suspense, until you say what paid it")


def test_a_receipt_with_no_statement_around_its_day_or_one_that_shows_it_stays_on_the_bank():
    before_only = [bank("14.50", "2026-05-11", "NATWEST CHARGES", "a", account="7901")]
    assert matched(_fuel(), *before_only)[0].contra_account_code == "1200"
    assert matched(_fuel())[0].contra_account_code == "1200"
    shown = [bank("14.50", "2026-05-11", "NATWEST CHARGES", "a", account="7901"),
             bank("499.00", "2026-05-18", "CURRYS", "c", account="0030"),
             bank("86.99", "2026-05-22", "SCREWFIX", "b", account="5000")]
    receipt, _, line, _ = matched(_fuel(), *shown)
    assert receipt.contra_account_code == "1200" and receipt.issues == [] and line.recorded_by is not None


def test_a_receipt_someone_paid_themselves_is_not_looked_for_on_the_statement():
    lines = [bank("14.50", "2026-05-11", "NATWEST CHARGES", "a", account="7901"),
             bank("86.99", "2026-05-22", "SCREWFIX", "b", account="5000")]
    receipt, *_ = matched(_fuel(bank_account="2250"), *lines)
    assert receipt.contra_account_code == "2250" and receipt.issues == []


def test_a_receipt_parked_in_suspense_goes_back_to_the_bank_once_nothing_says_otherwise():
    parked = matched(_fuel(), bank("14.50", "2026-05-11", "NATWEST", "a", account="7901"),
                     bank("86.99", "2026-05-22", "SCREWFIX", "b", account="5000"))[0]
    assert parked.contra_account_code == "9998"
    assert matched(parked)[0].contra_account_code == "1200"


def _cafe(**sale):
    """A week at a cafe: the till summary, SumUp's report of the card sales it collected and its fee, the payout, and
    the cash paid in at the bank."""
    return [row("receipt", "in", "4100.00", "2026-04-05", "Rosa's Cafe", "z1", account="4000",
                description="Weekly takings, cash and card (week ending 5 Apr)"),
            row("agent_statement", "in", "2860.00", "2026-04-07", "SumUp", "su1", account="4000", agent="SumUp",
                description="Card sales collected by SumUp", **sale),
            row("agent_statement", "out", "48.33", "2026-04-07", "SumUp", "su1", account="7901", agent="SumUp",
                description="SumUp fees"),
            bank("2811.67", "2026-04-07", "SUMUP PAYMENTS", "payout", direction="in", account="1250"),
            bank("1000.00", "2026-04-07", "CASH PAID IN BRANCH 0412", "cash", direction="in", account="4000",
                 description="Cash paid in at branch 0412")]


def test_till_takings_are_sales_once_and_card_payouts_and_cash_banked_only_move_the_money():
    takings, card_sales, fee, payout, cash = matched(*_cafe())
    assert (takings.account_code, takings.contra_account_code) == ("4000", "1230")   # sales, into the till
    assert card_sales.account_code == "1230" and fee.account_code == "7901"       # the till's money goes to SumUp
    assert [p.amount for p in payout.pays] == [Decimal("2811.67")]
    assert cash.account_code == "1230" and codes(cash) == [("till_takings", "info")]   # not a sale without VAT
    lines = [l for t in (takings, card_sales, fee, payout, cash) for l in journal_for(t, 0)]
    balance = lambda code: sum(l.debit - l.credit for l in lines if l.code == code)
    assert balance("4000") == Decimal("-4100.00")                 # the week's sales, once (VAT aside)
    assert balance("1230") == Decimal("240.00")                   # the cash still in the till
    assert balance("1200") == Decimal("3811.67") and balance("1100") == 0 and balance("7901") == Decimal("48.33")


def test_without_a_till_summary_a_processors_sales_and_cash_paid_in_are_left_as_they_were():
    rows = matched(*_cafe()[1:])
    assert rows[0].account_code == "4000" and rows[3].account_code == "4000"
    assert ("sale_without_vat", "warning") in codes(rows[3])


def test_a_processors_sale_a_person_gave_a_vat_treatment_stays_a_sale():
    _, card_sales, *_ = matched(*_cafe(vat_treatment="standard"))
    assert card_sales.account_code == "4000"


def test_the_summarys_own_note_of_cash_banked_is_the_same_movement_as_the_bank_line():
    note = row("receipt", "in", "1000.00", "2026-04-07", "Rosa's Cafe", "z1-note", account="1200",
               description="Cash banked")
    takings, _, _, _, cash, noted = matched(*_cafe(), note)
    assert (noted.account_code, noted.contra_account_code) == ("1230", "1200")
    assert "same_account" not in [c for c, _ in codes(noted)]
    assert cash.recorded_by is not None        # the bank line is the note's payment: booked once


# ─── UAT round 2, high issues ──────────────────────────────────────────────────

def test_a_refund_of_an_overpayment_clears_the_credit_and_is_not_a_sale():
    # Hartwell Homes paid £2,500 on a £2,400 invoice and was sent £100 back: the refund went to Sales.
    invoice = row("invoice", "in", "2400.00", "2026-05-20", "Hartwell Homes Ltd", "inv-1004", account="4000")
    paid = bank("2500.00", "2026-06-08", "HARTWELL HOMES", "line-1", direction="in", account="4000")
    refund = bank("100.00", "2026-07-09", "Hartwell Homes", "line-2", account="4000",
                  description="Hartwell Homes, refund of overpayment")
    invoice, paid, refund = matched(invoice, paid, refund)
    assert (refund.paid_against, refund.vat_posted) == ("1100", Decimal("0.00"))
    assert codes(refund) == [("refund_of_overpayment", "info")]
    assert invoice.owed == Decimal("0.00") and codes(paid) == [("overpayment", "info")]
    journal = journal_for(refund, 2)
    assert [(l.code, l.debit, l.credit) for l in journal] == [("1100", Decimal("100.00"), Decimal("0.00")),
                                                              ("1200", Decimal("0.00"), Decimal("100.00"))]


def test_a_part_payment_is_a_note_once_the_rest_is_paid():
    # Invoice 1001 was paid in two parts; the first still said "£4,200.00 still owed", and the chat repeated it.
    invoice = row("invoice", "in", "7200.00", "2026-03-20", "Hartwell Homes Ltd", "inv-1001", account="4000")
    first = bank("3000.00", "2026-04-01", "HARTWELL HOMES", "line-1", direction="in", account="4000")
    rest = bank("4200.00", "2026-04-20", "HARTWELL HOMES", "line-2", direction="in", account="4000")
    invoice, first, rest = matched(invoice, first, rest)
    assert invoice.owed == Decimal("0.00") and codes(rest) == []
    assert codes(first) == [("part_payment", "info")]
    assert first.issues[0].message == "Paid £3,000.00 of £7,200.00; the rest has been paid since."
    _, alone = matched(row("invoice", "in", "7200.00", "2026-03-20", "Hartwell Homes Ltd", "inv-1001", account="4000"),
                       bank("3000.00", "2026-04-01", "HARTWELL HOMES", "line-1", direction="in", account="4000"))
    assert codes(alone) == [("part_payment", "warning")]


COMPANY = BusinessSettings(business_name="Marlow Building Services Ltd", business_type="limited_company")


def test_a_companys_receipt_addressed_to_someone_else_is_asked_about():
    # A TV delivered to the director's home went to Office Equipment with its VAT, and no one asked.
    tv = row("invoice", "out", "200.00", "2026-05-16", "Currys Group Ltd", "tv", account="7504",
             addressed_to="Mr M Marlow", supplier_vat_number="GB1")
    flagged, = match([normalise(tv, COMPANY)], COMPANY)
    # (its VAT number with no VAT amount: the VAT is worked out, and said)
    assert codes(flagged) == [("vat_implied", "info"), ("addressed_to", "warning")]
    for change in ({"addressed_to": "Marlow Building Services Limited"}, {"accepted": ["addressed_to"]},
                   {"account_code": "2250"}):
        fine, = match([normalise(tv.model_copy(update=change), COMPANY)], COMPANY)
        assert "addressed_to" not in dict(codes(fine))
    sole = BusinessSettings(business_name="Rosa's Cafe", business_type="sole_trader")
    assert "addressed_to" not in dict(codes(match([normalise(tv, sole)], sole)[0]))


def test_a_credit_note_the_company_gives_its_customer_is_not_asked_whose_it_is():
    # The paid run of 25 Nov 2026: Kestrel & Finch's £720 credit note to Northgate Dental Group, addressed to the
    # customer as every credit note is, was flagged "If it is their own spending, recode it to Director's Loan".
    credit = row("invoice", "out", "720.00", "2026-05-16", "Northgate Dental Group", "cn", account="4000",
                 addressed_to="Northgate Dental Group", vat="120.00")
    flagged, = match([normalise(credit, COMPANY)], COMPANY)
    assert "addressed_to" not in dict(codes(flagged))


# ─── UAT round 2, medium issues ────────────────────────────────────────────────

def test_a_direct_debit_returned_unpaid_cancels_the_payment_it_reverses():
    # British Gas £210 out, back in the next day, then taken again: Gas showed a credit of £210 while both
    # payments waited in Suspense for a bill.
    from ledgersync.evidence_rules import document_rule
    first = bank("210.00", "2026-05-06", "British Gas", "a", account="7201")
    back = bank("210.00", "2026-05-07", "British Gas", "b", direction="in", account="7201",
                description="British Gas, unpaid direct debit reversed")
    again = bank("210.00", "2026-05-12", "British Gas", "c", account="7201")
    first, back, again = matched(first, back, again)
    assert codes(first) == codes(back) == [("reversed", "info")] and codes(again) == []
    assert document_rule(first, SETTINGS).action == "book" and document_rule(again, SETTINGS).action == "hold"


def test_a_payment_of_the_exact_amount_days_after_an_invoice_from_a_like_name_pays_it():
    # "Google Workspace Ireland" on the bank, "Google Cloud EMEA Limited" on the invoice: £55.20, three days apart.
    invoice = row("invoice", "out", "55.20", "2026-05-31", "Google Cloud EMEA Limited", "g", account="8201")
    paid, line = matched(invoice, bank("55.20", "2026-06-03", "Google Workspace Ireland", "l", account="8201"))
    assert paid.owed == Decimal("0.00") and line.paid_against == "2100" and codes(line) == []
    _, late = matched(invoice, bank("55.20", "2026-06-20", "Google Workspace Ireland", "l", account="8201"))
    assert late.paid_against is None and codes(late) == [("possible_payment", "warning")]


def test_wages_are_not_offered_another_persons_expense_claim():
    claim = row("expense_claim", "out", "144.00", "2026-04-30", "M Marlow", "claim", account="7400")
    _, wages = matched(claim, bank("1850.00", "2026-05-01", "S Marlow", "w", account="2220"))
    assert "open_document" not in dict(codes(wages))


# ─── A total a person said to leave as it is ───────────────────────────────────

def test_a_difference_a_person_left_raises_a_note_not_a_warning():
    first, second = matched(
        claim_line("36.00", "2026-09-09", "Southgate Bath Car Park", document_total="120.90", total_accepted="54.00"),
        claim_line("30.90", "2026-09-30", "Transport for London", document_total="120.90", total_accepted="54.00"))
    assert codes(first) == [("total_accepted", "info")] and codes(second) == []
    assert first.issues[0].message == "Lines total £66.90, £54.00 under the claim's £120.90."


def test_a_difference_left_on_a_line_read_twice_is_a_note_too():
    lines = matched(*(claim_line(gross, date, "Southgate", document_total="90.00", total_accepted="-54.00")
                      for gross, date in (("36.00", "2026-09-09"), ("54.00", "2026-09-24"), ("54.00", "2026-09-24"))))
    assert [codes(t) for t in lines] == [[("total_accepted", "info")], [], []]
    assert lines[0].issues[0].message == "Lines total £144.00, £54.00 over the claim's £90.00."


def test_an_accepted_difference_that_changed_is_asked_about_again():
    first, _ = matched(
        claim_line("36.00", "2026-09-09", "Southgate Bath Car Park", document_total="120.90", total_accepted="10.00"),
        claim_line("30.90", "2026-09-30", "Transport for London", document_total="120.90", total_accepted="10.00"))
    assert codes(first) == [("total_mismatch", "warning")]


def test_an_accepted_difference_is_forgotten_once_the_document_adds_up():
    lines = matched(claim_line("36.00", "2026-09-09", "Southgate", document_total="90.00", total_accepted="54.00"),
                    claim_line("54.00", "2026-09-24", "Southgate", document_total="90.00", total_accepted="54.00"))
    assert [codes(t) for t in lines] == [[], []]


def test_an_agents_statement_left_as_it_is_raises_a_note():
    first, *rest = matched(*(t.model_copy(update={"document_total": Decimal("600.00"),
                                                   "total_accepted": Decimal("73.25")}) for t in agent_statement()))
    assert [i.code for t in (first, *rest) for i in t.issues if i.code.startswith("total_")] == ["total_accepted"]
    assert first.issues[-1].message == "Items net to £526.75, £73.25 under the £600.00 the statement paid over."


# One claim line for several receipts on one document. Jenny's October claim has one line for TfL, £55.40; her TfL
# Payment Statement (one upload) lists eight daily charges, £61.50 in all, each read as a receipt. Seven of them, all
# but 5 Oct, add up to £55.40; nothing paired, so her TfL travel was booked twice.
TFL_DAYS = [("2026-10-27", "6.20"), ("2026-10-21", "8.90"), ("2026-10-20", "6.60"), ("2026-10-10", "6.00"),
            ("2026-10-08", "7.20"), ("2026-10-07", "10.00"), ("2026-10-06", "10.50"), ("2026-10-05", "6.10")]
CLAIMED = [f"tfl-{day}" for day in sorted(day for day, _ in TFL_DAYS) if day != "2026-10-05"]


def tfl_rows(claimed="55.40", merchant="Transport for London, Train", **kw):
    """Jenny's October claim line for TfL and the eight daily charges on her TfL Payment Statement (upload 199)."""
    line = claim_line(claimed, "2026-10-31", merchant, ref="claim", **kw)
    charges = [row("receipt", "out", gross, day, "TfL Customer Services", f"tfl-{day}", account="7400")
               for day, gross in TFL_DAYS]
    return [line, *charges], [176, *[199] * len(charges)]


def matched_from(rows, uploads, **kw):
    return match([normalise(t, SETTINGS) for t in rows], SETTINGS, upload_ids=uploads, **kw)


def by_ref(rows):
    return {t.document_ref: t for t in rows}


def test_a_claim_line_is_booked_from_the_charges_that_add_up_to_it():
    line, *charges = matched_from(*tfl_rows())
    assert not booked(line)
    assert line.recorded_by_refs == CLAIMED
    assert (line.recorded_by.amount, line.recorded_by.ref) == (Decimal("55.40"), CLAIMED[0])
    for ref in CLAIMED:
        receipt = by_ref(charges)[ref]
        assert (receipt.claimed_in.ref, receipt.contra_account_code, booked(receipt)) == ("claim", "2110", True)


# The claim line's words go with each receipt it is booked from (claim_note): they say who a meal or drink was for.
def test_a_receipt_takes_its_claim_lines_note_and_is_recoded_by_it():
    line, receipt = matched(claim_line("28.15", "2026-10-08", "ExCeL London Hospitality - Coffees for team at DAS",
                                       account="7406"),
                            row("receipt", "out", "28.15", "2026-10-08", "ExCeL London Hospitality", "excel",
                                account="7406", vat="3.25"))
    assert receipt.claim_note == "Jenny Hogg - ExCeL London Hospitality - Coffees for team at DAS"
    assert (receipt.account_code, receipt.vat_posted, receipt.contra_account_code) == ("8206", Decimal("3.25"), "2110")
    assert "claim_note" in [c for c, _ in codes(receipt)] and "meal_check" not in [c for c, _ in codes(receipt)]


def test_a_receipt_recoded_to_entertainment_by_its_note_posts_no_vat():
    line, receipt = matched(claim_line("60.00", "2026-10-07", "The Gun - drinks with clients", account="7406"),
                            row("receipt", "out", "60.00", "2026-10-07", "The Gun", "gun", account="7406", vat="10.00"))
    assert (receipt.account_code, receipt.vat_posted) == ("7403", Decimal("0"))


def test_a_receipt_recoded_to_entertainment_by_its_note_is_not_offered_the_claims_vat():
    line, receipt = matched(claim_line("60.00", "2026-10-07", "The Gun - drinks with clients", account="7406",
                                       vat="10.00"),
                            row("receipt", "out", "60.00", "2026-10-07", "The Gun", "gun", account="7406"))
    assert (receipt.account_code, receipt.vat_posted) == ("7403", Decimal("0"))
    assert "claim_vat" not in [c for c, _ in codes(receipt)]


def test_a_receipt_recoded_to_staff_welfare_by_its_note_reclaims_the_vat_it_shows():
    line, receipt = matched(claim_line("60.00", "2026-10-07", "The Gun - drinks for team", account="7403", vat="10.00"),
                            row("receipt", "out", "60.00", "2026-10-07", "The Gun", "gun", account="7403", vat="10.00"))
    assert (receipt.account_code, receipt.vat_posted) == ("8206", Decimal("10.00"))
    assert "claim_vat" not in [c for c, _ in codes(receipt)]


def test_a_receipt_whose_claim_says_nothing_asks_who_was_there():
    line, receipt = matched(claim_line("28.15", "2026-10-08", "ExCeL London Hospitality", account="7406"),
                            row("receipt", "out", "28.15", "2026-10-08", "ExCeL London Hospitality", "excel",
                                account="7406"))
    assert receipt.account_code == "7406" and ("meal_check", "warning") in codes(receipt)


def test_receipts_booked_from_one_claim_line_together_take_its_note():
    line, *charges = matched_from(*tfl_rows(merchant="Transport for London - team trip"))
    for ref in CLAIMED:
        assert by_ref(charges)[ref].claim_note == "Jenny Hogg - Transport for London - team trip"


def test_a_claim_line_booked_from_its_receipt_does_not_ask_its_receipts_questions():
    # Jenny's claim codes its lines "Other Business Expenses" (Sundry): the receipt books, and asks, not the line.
    line, receipt = matched(claim_line("6.99", "2026-10-04", "Amazon — Stationery", account="8207"),
                            row("receipt", "out", "6.99", "2026-10-04", "Amazon", "amazon", account="8207"))
    assert not booked(line) and booked(receipt)   # materiality.decide asks only of booked rows
    assert "sundry_check" in [i.code for i in receipt.presentation]


def test_a_supermarket_buy_on_a_claim_is_booked_to_subsistence_and_says_why():
    line, receipt = matched(claim_line("8.19", "2026-10-08", "Victoria Food & Groceries", account="8205"),
                            row("receipt", "out", "8.19", "2026-10-08", "Victoria Food & Groceries", "vic",
                                account="8205"))
    assert receipt.account_code == "7406"
    # Nothing on it says it was for the staff, so it is Subsistence before the claim is even read (checks.normalise).
    note = next(i for i in receipt.issues if i.code == "meal_recoded")
    assert note.severity == "info" and "Subsistence" in note.message
    # Groceries from a food shop: the claimant's own, as an accountant reads it; no one is asked who was there.
    assert "meal_check" not in [c for c, _ in codes(receipt)]
    assert "meal_decided" in [i.code for i in receipt.issues]


def test_a_claim_line_booked_from_its_receipt_leaves_the_account_questions_to_the_receipt():
    line, receipt = matched(claim_line("54.00", "2026-10-02", "Trainline", account="7400", alternatives=["7403"]),
                            row("receipt", "out", "54.00", "2026-10-02", "Trainline", "ticket", account="7400"))
    assert not booked(line) and "account_fact" not in [c for c, _ in codes(line)]


def test_matching_the_same_rows_again_gives_the_same_receipt():
    once = matched(claim_line("28.15", "2026-10-08", "ExCeL - Coffees for team", account="7406"),
                   row("receipt", "out", "28.15", "2026-10-08", "ExCeL", "excel", account="7406", vat="3.25"))
    assert matched(*once)[1].model_dump() == once[1].model_dump()


def test_a_charge_the_claim_leaves_out_is_not_booked_and_asks():
    rows, uploads = tfl_rows()
    _, *charges = matched_from(rows, uploads)
    left = by_ref(charges)["tfl-2026-10-05"]
    assert (left.left_off_claim.ref, booked(left), left.contra_account_code) == ("claim", False, "2110")
    assert ("not_claimed", "warning") in codes(left)
    rows[-1] = rows[-1].model_copy(update={"include": True})
    _, *charges = matched_from(rows, uploads)
    assert booked(by_ref(charges)["tfl-2026-10-05"])


def test_the_whole_statement_claimed_pairs_every_charge():
    line, *charges = matched_from(*tfl_rows("61.50"))
    assert len(line.recorded_by_refs) == 8 and not booked(line)
    assert not any("not_claimed" in [c for c, _ in codes(t)] for t in charges)


def test_no_set_that_adds_up_changes_nothing():
    line, *charges = matched_from(*tfl_rows("55.41"))
    assert booked(line) and line.recorded_by is None and line.recorded_by_refs == []
    assert all(t.claimed_in is None and t.left_off_claim is None and booked(t) for t in charges)


def test_a_line_for_another_supplier_takes_no_charges():
    line, *charges = matched_from(*tfl_rows(merchant="Trainline"))
    assert booked(line) and line.recorded_by is None
    assert all(t.claimed_in is None and t.left_off_claim is None for t in charges)


def test_without_uploads_the_set_pass_does_not_run():
    line, *charges = matched(*tfl_rows()[0])
    assert booked(line) and line.recorded_by is None
    assert all(t.claimed_in is None and t.left_off_claim is None for t in charges)


def test_one_receipt_of_the_amount_pairs_as_today():
    rows, uploads = tfl_rows()
    rows[0] = claim_line("6.20", "2026-10-27", "Transport for London", ref="claim")
    line, *charges = matched_from(rows, uploads)
    assert (line.recorded_by.ref, line.recorded_by_refs) == ("tfl-2026-10-27", [])
    assert not any(t.left_off_claim for t in charges)


def test_a_receipt_paired_on_its_own_is_never_in_a_set():
    rows, uploads = tfl_rows()
    rows.append(claim_line("10.50", "2026-10-06", "Transport for London", ref="claim"))
    line, *charges, other = matched_from(rows, [*uploads, 176])
    assert other.recorded_by.ref == "tfl-2026-10-06"
    assert booked(line) and line.recorded_by is None
    assert not any(t.left_off_claim for t in charges)


def test_a_charge_kept_apart_is_never_in_the_set():
    rows, uploads = tfl_rows()
    sixth = [day for day, _ in TFL_DAYS].index("2026-10-06") + 1
    apart = [set() for _ in rows]
    apart[0].add(sixth)
    apart[sixth].add(0)
    line, *charges = matched_from(rows, uploads, apart=apart)
    assert booked(line) and line.recorded_by is None
    assert all(t.claimed_in is None for t in charges)


def test_a_line_ticked_include_is_booked_as_well_and_warns():
    line, *charges = matched_from(*tfl_rows(include=True))
    assert booked(line) and line.recorded_by_refs == CLAIMED
    assert "booked_twice" in [c for c, _ in codes(line)]


def test_a_refund_on_the_statement_is_not_a_candidate():
    rows, uploads = tfl_rows()
    rows.append(row("receipt", "in", "6.10", "2026-10-05", "TfL Customer Services", "tfl-refund", account="7400"))
    line, *charges, refund = matched_from(rows, [*uploads, 199])
    assert line.recorded_by_refs == CLAIMED
    assert refund.claimed_in is None and refund.left_off_claim is None


def test_the_order_of_rows_makes_no_difference():
    rows, uploads = tfl_rows()
    result = by_ref(matched_from(rows[::-1], uploads[::-1]))
    assert result["claim"].recorded_by_refs == CLAIMED
    assert result["tfl-2026-10-05"].left_off_claim.ref == "claim"


def test_upload_ids_follow_rows_a_decision_left_out():
    rows, uploads = tfl_rows()
    gone = row("receipt", "out", "9.99", "2026-10-03", "Pret", "gone", excluded=True)
    gone_row, line, *charges = matched_from([gone, *rows], [300, *uploads])
    assert line.recorded_by_refs == CLAIMED
    assert by_ref(charges)["tfl-2026-10-05"].left_off_claim.ref == "claim"


def test_one_set_counts():
    from ledgersync.matching import _one_set
    assert _one_set([620, 890, 660, 600, 720, 1000, 1050, 610], 5540) == (1, [0, 1, 2, 3, 4, 5, 6])
    assert _one_set([100, 100, 200], 200)[0] == 1      # a set is two or more: {100, 100}, not {200}
    assert _one_set([100, 100, 100], 200)[0] == 2      # three pairs, counted up to two
    assert _one_set([100, 300], 250) == (0, None)


def test_two_sets_that_add_up_pair_nothing_and_ask():
    line = claim_line("12.00", "2026-10-31", "Transport for London", ref="claim")
    charges = [row("receipt", "out", gross, day, "TfL Customer Services", f"t-{day}", account="7400")
               for day, gross in [("2026-10-05", "6.00"), ("2026-10-06", "6.00"), ("2026-10-07", "6.00"),
                                  ("2026-10-08", "3.00")]]
    line, *charges = matched_from([line, *charges], [176, 199, 199, 199, 199])
    assert booked(line) and line.recorded_by is None
    assert all(t.claimed_in is None and t.left_off_claim is None and booked(t) for t in charges)
    assert ("claim_receipts_unclear", "warning") in codes(line)
    assert sorted(about(line, "claim_receipts_unclear")) == [1, 2, 3, 4]
    assert about(charges[0], "claim_receipts_unclear") == [0]


def test_sets_on_two_uploads_pair_nothing():
    rows, uploads = tfl_rows()
    rows += [row("receipt", "out", "30.00", "2026-10-15", "TfL Customer Services", "tfl2-15", account="7400"),
             row("receipt", "out", "25.40", "2026-10-16", "TfL Customer Services", "tfl2-16", account="7400")]
    line, *charges = matched_from(rows, [*uploads, 201, 201])
    assert booked(line) and line.recorded_by is None
    assert all(t.claimed_in is None and t.left_off_claim is None for t in charges)
    assert "claim_receipts_unclear" in [c for c, _ in codes(line)]
    warned = {t.document_ref for t in charges if "claim_receipts_unclear" in [c for c, _ in codes(t)]}
    assert warned == {"tfl-2026-10-05", "tfl2-15"}   # each upload's first candidate


def test_two_lines_that_could_share_charges_pair_neither():
    rows, uploads = tfl_rows()
    rows.append(claim_line("12.80", "2026-10-31", "Transport for London", ref="claim"))
    line, *charges, other = matched_from(rows, [*uploads, 176])
    for claim in (line, other):
        assert booked(claim) and claim.recorded_by is None
        assert "claim_receipts_unclear" in [c for c, _ in codes(claim)]
    assert all(t.claimed_in is None and t.left_off_claim is None and booked(t) for t in charges)


def test_a_leftover_a_bank_line_pays_is_booked_from_the_bank():
    rows, uploads = tfl_rows()
    rows.append(bank("6.10", "2026-10-07", "TFL TRAVEL CH", ref="card-1", account="7400"))
    line, *charges, card = matched_from(rows, [*uploads, 210])
    left = by_ref(charges)["tfl-2026-10-05"]
    assert left.left_off_claim is None and "not_claimed" not in [c for c, _ in codes(left)]
    assert (left.paid_by[0].ref, left.contra_account_code, booked(left)) == ("card-1", "1200", True)
    assert card.recorded_by.ref == "tfl-2026-10-05"
    assert line.recorded_by_refs == CLAIMED


def test_monthly_claim_lines_pair_with_their_own_months_on_one_statement():
    # Review: a statement of two months with a claim line for each. Each line's window reaches into the other month,
    # but their sets don't share a charge, so each pairs.
    september = [("2026-09-08", "4.10"), ("2026-09-15", "7.30"), ("2026-09-29", "5.20")]
    rows, uploads = tfl_rows()
    rows += [row("receipt", "out", gross, day, "TfL Customer Services", f"tfl-{day}", account="7400")
             for day, gross in [*september, ("2026-10-01", "3.30")]]
    rows.append(claim_line("16.60", "2026-09-30", "Transport for London, Train", ref="claim"))
    result = matched_from(rows, [*uploads, 199, 199, 199, 199, 176])
    october, sept_line = result[0], result[-1]
    assert sept_line.recorded_by_refs == ["tfl-2026-09-08", "tfl-2026-09-15", "tfl-2026-09-29"]
    assert october.recorded_by_refs == CLAIMED
    charges = by_ref(result)
    assert charges["tfl-2026-10-01"].left_off_claim is not None and charges["tfl-2026-10-05"].left_off_claim is not None
    assert not any("claim_receipts_unclear" in [c for c, _ in codes(t)] for t in result)


def test_a_charge_the_business_card_paid_is_never_in_a_set():
    # Review: the card line paying the £10.50 on 6 Oct came later in matching, so the charge went in the claim's set and
    # was booked twice. Without it, no set of the rest makes £55.40.
    rows, uploads = tfl_rows()
    rows.append(bank("10.50", "2026-10-07", "TFL TRAVEL CH", ref="card-1", account="7400"))
    line, *charges, card = matched_from(rows, [*uploads, 210])
    assert line.recorded_by is None and booked(line)
    assert card.recorded_by.ref == "tfl-2026-10-06"
    assert all(t.claimed_in is None and t.left_off_claim is None for t in charges)


def test_two_charges_on_one_day_are_named_in_the_same_order_whatever_the_rows_order():
    rows, uploads = tfl_rows("56.40")
    rows.append(row("receipt", "out", "1.00", "2026-10-27", "TfL Customer Services", "tfl-2026-10-27-b", account="7400"))
    uploads = [*uploads, 199]
    forward = by_ref(matched_from(rows, uploads))["claim"]
    backward = by_ref(matched_from(rows[::-1], uploads[::-1]))["claim"]
    assert forward.recorded_by_refs == backward.recorded_by_refs
    assert forward.recorded_by.ref == backward.recorded_by.ref


# ─── A P32 read as wages ──────────────────────────────────────────────────────

def _payroll(account, owed_to, gross, ref, description):
    return row("payroll", "out", gross, "2023-07-28", "HMRC" if owed_to == "paye_ni" else "Staff", ref,
               account=account, owed_to=owed_to, description=description)


def test_a_p32_read_as_wages_is_a_summary_of_what_payroll_owes_and_is_not_booked():
    # The test books' agency year: in seven months the P32 was read onto 7000 Gross wages, so on top of the payroll
    # report it booked £5,097.77 more wages and as much more owed to HMRC: £35,041 over the year.
    report = [_payroll("7000", "net_pay", "12095.01", "r1", "Net pay to employees"),
              _payroll("7000", "paye_ni", "3321.37", "r2", "Employees' income tax and National Insurance"),
              _payroll("7006", "paye_ni", "1776.40", "r3", "Employer's National Insurance")]
    p32 = _payroll("7000", "paye_ni", "5097.77", "p", "PAYE income tax and National Insurance due to HMRC")
    *kept, summary = matched_from([*report, p32], [1, 1, 1, 2])
    assert not booked(summary) and summary.account_code == "2210"
    assert [i.code for i in summary.issues] == ["not_booked"]
    assert all(booked(t) for t in kept) and [t.account_code for t in kept] == ["7000", "7000", "7006"]


def test_a_payroll_report_is_never_taken_for_a_p32():
    report = [_payroll("7000", "paye_ni", "3321.37", "r2", "Employees' income tax and National Insurance"),
              _payroll("7006", "paye_ni", "1776.40", "r3", "Employer's National Insurance")]
    with_pay = matched_from([*report, _payroll("7000", "net_pay", "12095.01", "r1", "Net pay")], [1, 1, 1])
    assert all(booked(t) for t in with_pay)
    alone = matched_from(report, None)   # with no uploads to go by, nothing is changed
    assert all(booked(t) for t in alone) and [t.account_code for t in alone] == ["7000", "7006"]


# ─── HMRC's payment references ────────────────────────────────────────────────

def test_a_payment_with_a_corporation_tax_reference_is_corporation_tax_however_it_was_read():
    # The test books' agency year: "HMRC CUMBERNAULD 8126043571A00123A" was read as a VAT payment, so £13,987 of
    # corporation tax went to VAT Liability.
    [line] = matched(bank("13987.00", "2023-12-29", "HMRC", account="2202",
                          description="HMRC CUMBERNAULD 8126043571A00123A"))
    assert line.account_code == "2320"
    [note] = [i for i in line.issues if i.code == "hmrc_reference"]
    assert "8126043571A00123A" in note.message and "corporation tax" in note.message


def test_a_paye_reference_is_paye_and_a_line_a_person_coded_stays():
    [paye] = matched(bank("5097.77", "2023-08-22", "HMRC", account="2202",
                          description="HMRC CUMBERNAULD 120PA00048215"))
    assert paye.account_code == "2210"
    [kept] = matched(bank("13987.00", "2023-12-29", "HMRC", account="2202", account_chosen=True,
                          description="HMRC CUMBERNAULD 8126043571A00123A"))
    assert kept.account_code == "2202"   # a person chose it
    [other] = matched(bank("13987.00", "2023-12-29", "Acme", account="7100", description="ACME 8126043571A00123A"))
    assert other.account_code == "7100"   # not to HMRC


def _month_of_payroll(p32_gross, p32_description="PAYE income tax and National Insurance due to HMRC", p32_account="2210"):
    report = [_payroll("7000", "net_pay", "12095.01", "r1", "Net pay to employees"),
              _payroll("7000", "paye_ni", "3321.37", "r2", "Employees' income tax and National Insurance"),
              _payroll("7006", "paye_ni", "1776.40", "r3", "Employer's National Insurance")]
    return [*report, _payroll(p32_account, "paye_ni", p32_gross, "p", p32_description)], [1, 1, 1, 2]


def test_the_employment_allowance_a_p32_claims_comes_off_employers_ni():
    # The test books' agency year: only the P32 shows the Employment Allowance (£5,000 over April to June), as what is
    # due to HMRC less than the payroll report's tax and NI; employer's NI and PAYE owed were both £5,000 too high.
    rows, uploads = _month_of_payroll("3321.37")
    ready = matched_from(rows, uploads)
    allowance = ready[-1]
    assert booked(allowance) and (allowance.account_code, allowance.direction, allowance.gross) == (
        "7006", Direction.IN, Decimal("1776.40"))
    assert "Employment Allowance" in only_issue(allowance, "employment_allowance").message
    lines = [line for n, t in enumerate(ready) if booked(t) for line in journal_for(t, n)]
    balance = lambda code: sum((l.debit - l.credit for l in lines if l.code == code), Decimal(0))   # noqa: E731
    assert (balance("7006"), balance("2210")) == (0, Decimal("-3321.37"))


def test_the_allowance_the_p32_prints_is_taken_as_printed():
    rows, uploads = _month_of_payroll("3650.57", "PAYE and NI to HMRC (Employment Allowance of £1,447.20 applied)")
    *_, allowance = matched_from(rows, uploads)
    assert (allowance.account_code, allowance.gross) == ("7006", Decimal("1447.20"))


def test_a_p32_that_claims_no_allowance_is_not_booked():
    rows, uploads = _month_of_payroll("5097.77")
    *_, summary = matched_from(rows, uploads)
    assert not booked(summary) and summary.account_code == "2210"
    rows, uploads = _month_of_payroll("1000.00")   # more off than employer's NI: not an allowance, left as read
    *_, odd = matched_from(rows, uploads)
    assert not booked(odd) and odd.account_code == "2210"


def test_a_p32_read_on_paye_with_no_owed_to_still_gives_its_allowance():
    # June's P32 in the agency year was read on 2210 with owed_to left empty.
    rows, uploads = _month_of_payroll("3650.57", "PAYE and NI to HMRC (Employment Allowance of £1,447.20 applied)")
    rows[-1] = rows[-1].model_copy(update={"owed_to": None})
    *_, allowance = matched_from(rows, uploads)
    assert (allowance.account_code, allowance.gross) == ("7006", Decimal("1447.20"))


def test_a_p32_read_as_two_rows_books_its_allowance_row():
    # The paid run of 25 Nov 2026: April's and June's P32s were read as two rows, the tax and NI due (£5,097.77) and
    # "Employment Allowance claimed" (£1,776.40 in). The allowance only came off a P32 read as one row, so employer's
    # NI was £3,223.60 too high for the year.
    rows, uploads = _month_of_payroll("5097.77")
    rows.append(_payroll("2210", "paye_ni", "1776.40", "p2", "Employment Allowance claimed").model_copy(
        update={"direction": Direction.IN}))
    uploads.append(2)
    *_, due, allowance = matched_from(rows, uploads)
    assert not booked(due) and due.account_code == "2210"
    assert booked(allowance) and (allowance.account_code, allowance.direction, allowance.gross) == (
        "7006", Direction.IN, Decimal("1776.40"))
    assert "employment_allowance" in [i.code for i in allowance.issues]


# ─── Bad debts (design of 2026-11-24) ─────────────────────────────────────────

def _lowther(gross="4800.00", vat="800.00"):
    return row("invoice", "in", gross, "2023-06-05", "Lowther Interiors Ltd", "kf-1017", account="4000", vat=vat,
               description="Lowther Interiors Ltd – Showroom website build")


def _written_off(gross="4800.00", vat="800.00"):
    return row("write_off", "out", gross, "2024-01-31", "Lowther Interiors Ltd", "wo-1", account="8100", vat=vat,
               writes_off="kf-1017", description="Bad debt written off: Showroom website build")


def test_a_write_off_settles_its_invoice():
    invoice, off = matched(_lowther(), _written_off())
    assert invoice.owed == Decimal("0.00") and [p.kind for p in invoice.paid_by] == ["write_off"]
    assert booked(off) and off.vat_posted == Decimal("800.00")


def test_a_part_paid_invoice_is_written_off_for_what_is_owed():
    invoice, paid, off = matched(_lowther(), bank("1200.00", "2023-07-10", "Lowther Interiors Ltd", direction="in",
                                                  account="4000"), _written_off("3600.00", "600.00"))
    assert [p.ref for p in paid.pays] == ["kf-1017"] and invoice.owed == Decimal("0.00")


def test_a_later_payment_from_the_customer_is_a_recovery():
    # The administrator's dividend of £1,200 on 20 March 2024: booked as a sale with no VAT before.
    *_, back = matched(_lowther(), _written_off(), bank("1200.00", "2024-03-20", "Lowther Interiors Ltd",
                                                        direction="in", account="4000"))
    assert (back.account_code, back.vat_posted, back.recovers) == ("8100", Decimal("200.00"), "wo-1")
    assert "bad_debt_recovered" in [c for c, _ in codes(back)] and "sale_without_vat" not in [c for c, _ in codes(back)]


def test_a_payment_bigger_than_the_write_off_is_not_a_recovery():
    *_, back = matched(_lowther(), _written_off(), bank("6000.00", "2024-03-20", "Lowther Interiors Ltd",
                                                        direction="in", account="4000"))
    assert back.recovers is None and back.account_code == "4000"


def test_a_recovery_from_the_customers_administrators_name_is_still_a_recovery():
    # The agency year's dividend came from "Lowther Interiors in Admin".
    invoice, off, back = matched(_lowther(), _written_off(), bank("1200.00", "2024-03-20", "Lowther Interiors in Admin",
                                                                  direction="in", account="4000"))
    assert back.recovers == "wo-1" and off.owed is None   # the write-off is not itself a document owed


def test_a_recovery_is_found_once_the_customers_earlier_balance_is_paid():
    # The agency year: Lowther's £8,400 brought forward was paid in April, but the recovery was looked for before
    # payments were matched, so the balance still looked open and the dividend stayed a sale.
    from ledgersync.models import OpenItem
    rows = [_lowther(), _written_off(),
            bank("8400.00", "2023-04-27", "Lowther Interiors Ltd", "april", direction="in", account="4000"),
            bank("1200.00", "2024-03-20", "Lowther Interiors in Admin", "march", direction="in", account="4000")]
    ready = match([normalise(t, SETTINGS) for t in rows], SETTINGS,
                  open_items=[OpenItem(id="1", direction="in", counterparty="Lowther Interiors Ltd",
                                       amount=Decimal("8400.00"), date=dt.date(2023, 3, 31))])
    april, march = ready[2], ready[3]
    assert [p.ref for p in april.pays] == ["ob-1"] and march.recovers == "wo-1" and march.account_code == "8100"


def test_another_customer_sharing_a_word_is_not_a_recovery():
    *_, other = matched(_lowther(), _written_off(), bank("500.00", "2024-05-01", "Pinecrest Interiors",
                                                         direction="in", account="4000"))
    assert other.recovers is None


def test_two_write_offs_for_one_customer_recover_each_line_once():
    second = row("invoice", "in", "1200.00", "2023-07-05", "Lowther Interiors Ltd", "kf-1018", account="4000",
                 vat="200.00", description="Second invoice")
    off2 = row("write_off", "out", "1200.00", "2024-01-31", "Lowther Interiors Ltd", "wo-2", account="8100",
               vat="200.00", writes_off="kf-1018", description="Bad debt written off: second")
    *_, small, big = matched(_lowther(), second, _written_off(), off2,
                             bank("1000.00", "2024-03-20", "Lowther Interiors Ltd", "l1", direction="in", account="4000"),
                             bank("4000.00", "2024-03-27", "Lowther Interiors Ltd", "l2", direction="in", account="4000"))
    # pooled: £5,000 unrecovered between them, so both lines are recoveries, oldest write-off first
    assert small.recovers == big.recovers == "wo-1" and (small.vat_posted, big.vat_posted) == (
        Decimal("166.67"), Decimal("666.67"))


def test_a_payment_dated_before_the_write_off_settles_first():
    invoice, off, paid = matched(_lowther(), _written_off(), bank("1200.00", "2023-08-01", "Lowther Interiors Ltd",
                                                                  direction="in", account="4000"))
    assert [p.ref for p in paid.pays] == ["kf-1017"] and invoice.owed == Decimal("0.00")
    assert "write_off_more_than_owed" in [c for c, _ in codes(off)]   # it wrote off £1,200 more than was left


# ─── A card payment reaching the bank over a weekend ──────────────────────────

def test_a_receipt_pairs_with_its_bank_line_across_a_weekend():
    # The test books' agency year: a £16.07 taxi on Thursday 9 November 2023 reached the bank on Monday 13 November;
    # four days apart, the two were never paired, so the taxi was booked twice.
    taxi, line = matched(row("receipt", "out", "16.07", "2023-11-09", "Avon Street Taxis", "t", account="7400"),
                         bank("16.07", "2023-11-13", "AVON STREET TAXIS", "l", account="7400"))
    assert line.recorded_by is not None and booked(taxi) and not booked(line)


# ─── A card payment made before its invoice was dated ─────────────────────────

def test_a_card_payment_days_before_its_invoice_pays_it():
    # The test books' agency year (EC-0208): Shelfwise charged the card £89.99 on 12 June at the order; its invoice is
    # dated 19 June. Only suggested, both were booked: the cost twice, and Creditors £89.99 too high.
    invoice, line = matched(row("invoice", "out", "89.99", "2023-06-19", "Shelfwise Online", "swi", account="7504"),
                            bank("89.99", "2023-06-12", "Shelfwise Online", "card", account="7504", bank_account="1240"))
    assert [p.ref for p in line.pays] == ["swi"] and invoice.owed == Decimal("0.00")
    assert "paid_before_invoice" in [c for c, _ in codes(line)]


def test_a_payment_weeks_before_the_invoice_is_only_suggested():
    invoice, line = matched(row("invoice", "out", "89.99", "2023-06-30", "Shelfwise Online", "swi", account="7504"),
                            bank("89.99", "2023-06-05", "Shelfwise Online", "card", account="7504", bank_account="1240"))
    assert line.pays == [] and ("possible_payment", "warning") in codes(line)


# ─── A director's expense claim paid to them ──────────────────────────────────

def test_a_payment_to_a_director_of_exactly_an_unnamed_claim_pays_it():
    # The test books' agency year: Omar Kestrel's £212.40 claim named no claimant (only its file did); the bank's
    # £212.40 to him, read onto his director's loan account, paid nothing, so the claim stayed owed to staff.
    claim = [row("expense_claim", "out", gross, "2023-10-20", None, "omar-oct", account=account,
                 description=description)
             for gross, account, description in (("86.40", "7400", "Train to London"),
                                                 ("34.80", "7406", "Lunch while travelling"),
                                                 ("91.20", "7400", "Car park"))]
    *lines, paid = matched(*claim, bank("212.40", "2023-11-15", "Omar Kestrel", "pay", account="2251"))
    assert [p.ref for p in paid.pays] == ["omar-oct"] and {t.owed for t in lines} == {Decimal("0.00")}
    assert paid.paid_against == "2110"


def omar_claim():
    return [row("expense_claim", "out", gross, "2023-10-20", None, "omar-oct", account=account, description=description)
            for gross, account, description in (("86.40", "7400", "Train to London"),
                                                ("34.80", "7406", "Lunch while travelling"),
                                                ("91.20", "7400", "Car park"))]


def parked(who):
    """The bank's £212.40 to someone, which the reader parked in Suspense because it found no account."""
    return bank("212.40", "2023-11-15", who, "pay", account="9998", description="O KESTREL EXPENSES",
                issues=[Issue(code="account_unclear", message="Not sure which account.", severity="warning")])


def test_a_director_s_payment_parked_in_suspense_pays_their_unnamed_claim():
    # The agency run: "O KESTREL EXPENSES" was read into Suspense, so the claim stayed owed and the payment was held
    # for a receipt.
    settings = BusinessSettings(owner_names=("Hannah Finch", "Omar Kestrel"))
    *lines, paid = match([normalise(t, settings) for t in (*omar_claim(), parked("Omar Kestrel"))], settings)
    assert [p.ref for p in paid.pays] == ["omar-oct"] and {t.owed for t in lines} == {Decimal("0.00")}
    assert paid.paid_against == "2110" and codes(paid) == [("claim_paid", "info")]


def test_someone_else_s_payment_parked_in_suspense_pays_no_claim():
    settings = BusinessSettings(owner_names=("Hannah Finch", "Omar Kestrel"))
    *_, paid = match([normalise(t, settings) for t in (*omar_claim(), parked("Kestrel Joinery"))], settings)
    assert not paid.pays and paid.paid_against is None


def test_a_payroll_report_split_by_who_is_paid_is_not_short_of_its_total():
    # The agency run: every monthly report warned four times "Total doesn't add up": its rows go into a document for
    # each payee, and each was set against the whole report's total gross pay (£18,178.33). The pay lines are checked
    # against it when the report is read (adapter: payroll_total).
    def line(gross, account, who, owed_to):
        return row("payroll", "out", gross, "2023-04-28", who, None, account=account, owed_to=owed_to,
                   document_total=Decimal("18178.33"))
    rows = matched(line("2095.00", "7001", "Hannah Finch, Omar Kestrel", "net_pay"),
                   line("12095.01", "7000", "Staff", "net_pay"), line("3321.37", "7000", "HMRC", "paye_ni"),
                   line("666.95", "7000", "Pension provider", "pension"))
    assert not [c for t in rows for c, _ in codes(t) if c == "total_mismatch"]


def test_paid_the_oldest_names_what_was_open_on_it():
    # The website: "Paid the oldest… Brought forward: Brightwater Homes Ltd (£0.00, 31 Mar 2023)": the item it paid
    # was shown after the payment, with nothing left on it.
    older = row("invoice", "in", "7200.00", "2026-01-01", "Brightwater Homes", "kf-1", account="4000")
    newer = row("invoice", "in", "7200.00", "2026-02-01", "Brightwater Homes", "kf-2", account="4000")
    *_, line = matched(older, newer, bank("7200.00", "2026-02-10", "Brightwater Homes", "pay", direction="in",
                                          account="4000"))
    [said] = [i for i in line.issues if i.code == "paid_oldest"]
    assert "(£7,200.00, 01 Jan 2026)" in said.message and "£0.00" not in said.message


def test_a_long_list_of_what_a_line_may_pay_names_the_first_few():
    # The website: "May pay an open invoice" listed 45 Stripe statements in one sentence.
    from ledgersync.matching import _choices, _Document
    docs = [[_Document(ref=f"s{k}", kind="agent_statement", direction="in", account="1250", counterparty="Stripe",
                       description="Stripe's statement", open=Decimal("709.00"), date=dt.date(2023, 4, k + 1))]
            for k in range(25)]
    said = _choices(docs)
    assert said.count("Stripe's statement") == 3 and said.endswith("or 22 more")
    assert _choices(docs[:3]).count("Stripe's statement") == 3 and "more" not in _choices(docs[:3])


def test_an_unmatched_receipt_from_a_customer_owing_more_is_held_on_debtors():
    # The administrator's £1,200 for Lowther's £4,800 invoice, before any write-off: more than 120 days on, so not
    # paid automatically, and the reader coded it to Sales. Booked as a sale with no VAT, it overstated sales and left
    # Debtors £1,200 high (agency run, 25 Nov 2026). Held on Debtors as the customer's payment on account instead.
    invoice, back = matched(_lowther(), bank("1200.00", "2024-03-20", "LOWTHER INTERIORS IN ADMIN", direction="in",
                                             account="4000"))
    assert back.account_code == "1100" and not back.pays and invoice.owed == Decimal("4800.00")
    said = dict(codes(back))
    assert said.get("open_document") == "warning" and "sale_without_vat" not in said and "on_account" not in said
    assert "Debtors" in only_issue(back, "open_document").message


def test_a_receipt_for_more_than_the_customer_owes_keeps_its_account():
    _, back = matched(_lowther(), bank("6000.00", "2024-03-20", "Lowther Interiors Ltd", direction="in",
                                       account="4000"))
    assert back.account_code == "4000"
