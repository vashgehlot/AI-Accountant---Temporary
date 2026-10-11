import pytest

from ledgersync.matching import names_match


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
])
def test_names_that_do_not_match(a, b):
    assert not names_match(a, b)


import datetime as dt
from decimal import Decimal

from ledgersync.checks import booked, normalise
from ledgersync.matching import match
from ledgersync.models import BusinessSettings, Direction, Transaction

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
    return [(i.code, i.severity) for i in t.issues]


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


def test_an_unpaid_bill_is_still_owed():
    [open_bill] = matched(bill())
    assert open_bill.owed == Decimal("12000.00") and open_bill.paid_by == []


def test_two_bills_that_fit_ask_a_person_to_choose():
    october, later, line = matched(bill(), bill(date="2026-10-10", ref="bill-later"), bank(date="2026-10-20"))
    assert codes(line) == [("choose_payment", "error")] and line.pays == []
    assert [[c.ref for c in option] for option in line.candidates] == [["bill-oct"], ["bill-later"]]
    assert october.owed == later.owed == Decimal("12000.00")


@pytest.mark.parametrize("paid_on", ["2026-09-30", "2026-11-02"])
def test_a_payment_before_the_bill_or_more_than_31_days_after_is_not_matched(paid_on):
    open_bill, line = matched(bill(), bank(date=paid_on))
    assert line.pays == [] and open_bill.owed == Decimal("12000.00")


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
    undated = row("expense_claim", "out", "50.00", "2026-09-20", "Jenny Hogg", "claim").model_copy(update={"date": None})
    *_, late = matched(first, undated, bank("150.00", "2026-10-03", "J HOGG EXPENSES"))
    *_, in_time = matched(first, undated, bank("150.00", "2026-10-02", "J HOGG EXPENSES"))
    assert late.pays == [] and [p.ref for p in in_time.pays] == ["claim"]


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
    assert codes(first) == [("part_payment", "warning")] and codes(second) == []


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
    assert booked(reminder) and codes(line) == [("choose_payment", "error")]


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
    # A £300 claim (owed to staff) and a £200 bill (owed to a supplier), both named like "M BARNES", must not be
    # settled together by one £500 line: the whole £500 would post against just one of the two accounts.
    claim = row("expense_claim", "out", "300.00", "2026-10-01", "Matt Barnes", "claim", account="7402")
    plumber = bill("200.00", date="2026-10-01", ref="plumber", who="Barnes Plumbing", account="7800")
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
    return row("receipt", "out", gross, date, who, ref, account="7406", **kw)


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
    assert all(d in receipt.issues[0].message for d in ("23 Feb 2026", "22 Jan 2026"))


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


def test_a_claim_line_its_claims_total_confirms_says_what_the_bills_amount_would_do_to_it():
    # Use £30.22 on Matt's EE line put his claim £2.72 over its total without a word: the choice stays, said plainly.
    line, bill = matched(claim_line("27.50", "2026-09-03", "EE, mobile phone bill", account="7502", document_total="27.50"),
                         row("invoice", "out", "30.22", "2026-09-03", "EE", "bill", account="7502"))
    assert codes(line) == codes(bill) == [("amount_conflict", "warning")]
    assert all(s in line.issues[0].message for s in ("confirms", "£2.72"))


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
     row("receipt", "out", "6.00", "2026-09-14", "M6toll", "toll", account="7406")],        # Use can't say which row
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


def test_vat_on_the_claim_that_the_receipt_does_not_show_is_flagged():
    # The hotel "receipt" was a check-in email; the claim added VAT £28.96 from colleagues' folios.
    _, receipt = matched(claim_line("173.75", "2026-09-14", "Clayton Hotel Manchester", account="7402", vat="28.96"),
                         row("receipt", "out", "173.75", "2026-09-14", "Clayton Hotel Manchester City Centre", "email",
                             account="7402"))
    assert codes(receipt) == [("claim_vat", "warning")] and "£28.96" in receipt.issues[0].message


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


@pytest.mark.parametrize("prices", [{}, {"document_net": "15.00"},     # no price before VAT, or £2.99 of VAT
                                    {"document_net": "14.99", "vat": "0.00"}])   # or it shows no VAT charged
def test_prices_that_do_not_show_the_claims_vat_leave_it_unbooked(prices):
    receipt = amazon_order(**prices)
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
