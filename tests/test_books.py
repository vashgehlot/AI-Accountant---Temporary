from datetime import date
from decimal import Decimal as D

import pytest
from helpers import (acme_two_years, acme_with_a_non_gbp_row, acme_with_statement_missing_a_line,  # noqa: F401 (fixtures)
                     acme_with_unpaid_bill_in_year_one, acme_with_year_one, add_rows, bill_row, change_stationery_receipt_to, first_row_id, net, row,
                     the_bills_payment_dated)

from ledgersync import books, ledger
from ledgersync.errors import InvalidInput, InvalidTransactions, NotFound, YearClosed
from ledgersync.models import BankAccount, ClientPatch, ManualUpload, OpeningBalances, OpeningLine, OpenItem, RowPatch

pytestmark = pytest.mark.mongo

YEAR_1, YEAR_2 = date(2025, 4, 1), date(2026, 4, 1)


@pytest.fixture
def store(mongo_store):
    return mongo_store


def test_the_second_year_opens_with_the_first_years_closing_and_its_profit_in_retained_earnings(store, acme):
    # acme: limited company, first year end 31 Mar 2026; one sale of £1,200 (VAT £200) paid into the bank in year 1,
    # one £60 stationery receipt in year 2
    add_rows(store, acme, row(date=date(2025, 6, 1), direction="in", gross=D("1200.00"), vat=D("200.00"),
                              account_code="4000", counterparty="Bright Cafe"),
             row(date=date(2026, 5, 1), gross=D("60.00"), account_code="7504"))
    tb = books.trial_balance(store, acme, date(2026,4,1))
    opening = {l.code: l.debit - l.credit for l in tb.opening}
    assert opening == {"1200": D("1200.00"), "2200": D("-200.00"), "3200": D("-1000.00")}
    assert net(tb, "7504") == D("60.00") and net(tb, "1200") == D("1140.00")


def test_a_payment_in_year_one_clears_an_unpaid_bill_brought_forward(store, acme):
    books.set_opening(store, acme, OpeningBalances(
        lines=[OpeningLine(code="1200", debit=D("500.00")), OpeningLine(code="2100", credit=D("500.00"))],
        unpaid=[OpenItem(id="1", direction="out", counterparty="Smith Solicitors Ltd", amount=D("500.00"))]))
    add_rows(store, acme, row(date=date(2025,5,2), counterparty="Smith Solicitors", gross=D("500.00"), document_type="statement"))
    tb = books.trial_balance(store, acme, date(2025,4,1))
    assert net(tb, "2100") == 0 and net(tb, "7600") == 0 and net(tb, "1200") == 0


def test_opening_balances_must_balance_and_agree_with_the_unpaid_invoices(store, acme):
    with pytest.raises(InvalidInput, match="must be the same"):
        books.set_opening(store, acme, OpeningBalances(lines=[OpeningLine(code="1200", debit=D("10.00"))]))
    # the invoices listed can be fewer than Debtors (the rest is brought forward not itemised), never more
    with pytest.raises(InvalidInput, match="more than Debtors, which is £300.00"):
        books.set_opening(store, acme, OpeningBalances(
            lines=[OpeningLine(code="1100", debit=D("300.00")), OpeningLine(code="3000", credit=D("300.00"))],
            unpaid=[OpenItem(id="1", direction="in", counterparty="Bright Cafe", amount=D("400.00"))]))


def test_a_statement_across_the_year_end_is_split_but_checked_whole(store, acme):
    # one statement upload: a line on 30 Mar 2026 and a line on 2 Apr 2026, opening and closing balances that add up
    line = dict(document_type="statement", counterparty="Shop")
    add_rows(store, acme, row(**line, date=date(2026, 3, 30), gross=D("10.00"), opening_balance=D("100.00"),
                              balance=D("90.00")),
             row(**line, date=date(2026, 4, 2), gross=D("20.00"), balance=D("70.00"), closing_balance=D("70.00")))
    year1, year2 = books.ledger(store, acme, date(2025,4,1)), books.ledger(store, acme, date(2026,4,1))
    assert len(year1.transactions) == len(year2.transactions) == 1
    assert year1.uploads[0].statement.status == year2.uploads[0].statement.status == "ok"


def test_an_undated_row_belongs_to_the_year_it_was_added_to(store, acme):
    add_rows(store, acme, row(date=None, gross=D("9.00")), year_start=date(2026,4,1))
    assert not books.ledger(store, acme, date(2025,4,1)).transactions
    [undated] = books.ledger(store, acme, date(2026,4,1)).transactions
    assert any(i.code == "date_missing" for i in undated.issues)


def test_the_years_run_to_the_latest_row_or_today(store, acme):
    assert [y.label for y in books.years_of(store, acme, date(2025, 6, 1))] == ["Year to 31 Mar 2026"]
    assert [y.start for y in books.years_of(store, acme, date(2026, 10, 25))] == [YEAR_1, YEAR_2]
    add_rows(store, acme, row(date=date(2028, 1, 5), gross=D("5.00")))
    assert len(books.years_of(store, acme, date(2026, 10, 25))) == 3


def test_each_year_says_how_many_rows_it_holds(store, acme):
    # The website: the client list opened the empty year holding today, not the year being worked on.
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("5.00")), row(date=date(2025, 7, 1), gross=D("6.00")))
    assert [(y.start, y.rows) for y in books.years_of(store, acme, date(2026, 10, 25))] == [(YEAR_1, 2), (YEAR_2, 0)]


def test_an_unknown_year_is_not_found(store, acme):
    with pytest.raises(NotFound, match="That year was not found."):
        books.ledger(store, acme, date(2025, 4, 2))


OPENING_BANK = OpeningBalances(lines=[OpeningLine(code="1200", debit=D("1000.00")),
                                      OpeningLine(code="3000", credit=D("1000.00"))])


def statement_across_the_first_year_start(store, acme, **march):
    """A statement with a £100.00 stationery line on 15 Mar 2025, before the first year, and a £50.00 one on 10 Apr."""
    line = dict(document_type="statement", account_code="7504", counterparty="Ryman")
    add_rows(store, acme, row(**line, date=date(2025, 3, 15), gross=D("100.00"), **march),
             row(**line, date=date(2025, 4, 10), gross=D("50.00")))


def test_a_statement_straddling_the_first_year_start_is_not_counted_twice(store, acme):
    books.set_opening(store, acme, OPENING_BANK)
    statement_across_the_first_year_start(store, acme)
    tb = books.trial_balance(store, acme, YEAR_1)
    # the £50.00 line has no document, so it sits in Suspense rather than on its cost account
    assert (net(tb, "1200"), net(tb, "7504"), net(tb, "9998")) == (D("950.00"), D("0.00"), D("50.00"))
    march, _ = books.ledger(store, acme, YEAR_1).transactions
    assert [(i.code, i.message) for i in march.issues] == [("before_first_year", (
        "Dated before the first year: already in the opening balances, so not booked. Tick Include to book it."))]


def test_ticking_include_books_a_row_dated_before_the_first_year(store, acme):
    books.set_opening(store, acme, OPENING_BANK)
    statement_across_the_first_year_start(store, acme, include=True)
    tb = books.trial_balance(store, acme, YEAR_1)
    # neither line has a document, so both sit in Suspense rather than on their cost account
    assert (net(tb, "1200"), net(tb, "7504"), net(tb, "9998")) == (D("850.00"), D("0.00"), D("150.00"))


def test_a_pre_year_invoice_doesnt_duplicate_its_brought_forward_item(store, acme):
    books.set_opening(store, acme, OpeningBalances(
        lines=[OpeningLine(code="1200", debit=D("500.00")), OpeningLine(code="2100", credit=D("500.00"))],
        unpaid=[OpenItem(id="1", direction="out", counterparty="Smith Solicitors Ltd", amount=D("500.00"))]))
    add_rows(store, acme, row(date=date(2025, 3, 1), gross=D("500.00"), document_type="invoice",
                              counterparty="Smith Solicitors Ltd", document_ref="bill"),
             row(date=date(2025, 5, 2), gross=D("500.00"), document_type="statement", counterparty="Smith Solicitors"))
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "2100"), net(tb, "7600"), net(tb, "1200")) == (0, 0, 0)
    _, line = books.ledger(store, acme, YEAR_1).transactions
    assert [s.ref for s in line.pays] == ["ob-1"]


def test_an_invoice_unpaid_at_the_year_end_is_owed_in_its_year_and_paid_in_the_next(store, acme):
    add_rows(store, acme, row(date=date(2026, 3, 1), gross=D("300.00"), document_type="invoice",
                              counterparty="Smith Solicitors", document_ref="bill"),
             row(date=date(2026, 6, 5), gross=D("300.00"), document_type="statement", counterparty="SMITH SOLICITORS"))
    year1, year2 = books.trial_balance(store, acme, YEAR_1), books.trial_balance(store, acme, YEAR_2)
    assert (net(year1, "2100"), net(year1, "7600")) == (D("-300.00"), D("300.00"))
    assert {l.code: l.debit - l.credit for l in year2.opening} == {"2100": D("-300.00"), "3200": D("300.00")}
    assert (net(year2, "2100"), net(year2, "1200"), net(year2, "7600")) == (0, D("-300.00"), 0)
    [line] = books.ledger(store, acme, YEAR_2).transactions
    assert [s.ref for s in line.pays] == ["bill"]


def test_a_sole_traders_profit_is_carried_into_the_owners_capital(store, acme):
    store.update_client(acme, {"business_type": "sole_trader"})
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("50.00")))
    opening = books.opening(store, acme, YEAR_2)
    assert opening == {"1200": D("-50.00"), "3100": D("50.00")}


def test_rows_to_fix_in_an_earlier_year_hold_up_the_next_years_trial_balance(store, acme):
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("50.00"), account_code="9999"))
    with pytest.raises(InvalidTransactions, match="Fix the earlier years first"):
        books.trial_balance(store, acme, YEAR_2)


@pytest.mark.parametrize("line, message", [
    (OpeningLine(code="4000", credit=D("1.00")),
     "Opening balances take balance sheet accounts only: 4000 Sales is income or a cost."),
    (OpeningLine(code="9999", debit=D("1.00")), "9999 isn't an account in the chart."),
])
def test_opening_balances_take_balance_sheet_accounts_only(store, acme, line, message):
    with pytest.raises(InvalidInput, match=message):
        books.set_opening(store, acme, OpeningBalances(lines=[line]))


def test_the_first_year_opens_with_last_years_retained_earnings(store, acme):
    # Ruling R4: the reserves are balance sheet accounts too.
    opening = OpeningBalances(lines=[OpeningLine(code="1200", debit=D("800.00")),
                                     OpeningLine(code="3200", credit=D("800.00"))])
    books.set_opening(store, acme, opening)
    assert store.opening(acme) == opening
    tb = books.trial_balance(store, acme, YEAR_1)
    assert [(l.code, l.debit, l.credit) for l in tb.opening] == [("1200", D("800.00"), 0), ("3200", 0, D("800.00"))]
    assert tb.is_balanced


def test_unpaid_bills_can_be_left_as_a_total_but_never_exceed_creditors(store, acme):
    # At takeover often only the total is known: it is brought forward as one balance, which the invoices list shows.
    books.set_opening(store, acme, OpeningBalances(lines=[OpeningLine(code="1200", debit=D("500.00")),
                                                          OpeningLine(code="2100", credit=D("500.00"))]))
    [rest] = books.invoices(store, acme, YEAR_1)
    assert (rest.kind, rest.counterparty, rest.owed, rest.brought_forward) == ("purchase", "Not itemised", D("500.00"), True)
    with pytest.raises(InvalidInput, match=r"add up to £600\.00, more than Creditors, which is £500\.00\."):
        books.set_opening(store, acme, OpeningBalances(
            lines=[OpeningLine(code="1200", debit=D("500.00")), OpeningLine(code="2100", credit=D("500.00"))],
            unpaid=[OpenItem(id="a", direction="out", counterparty="Acme", amount=D("600.00"))]))


# ─── Closing and reopening a year (Task 8) ─────────────────────────────────────

def test_a_closed_year_refuses_changes(store, acme_with_year_one):
    books.close(store, acme_with_year_one, date(2025,4,1))
    with pytest.raises(YearClosed, match="Reopen it"):
        ledger.change_row(store, acme_with_year_one, first_row_id(store, acme_with_year_one), RowPatch(account_code="7502"))


def test_a_year_with_a_fact_question_open_is_not_closed_until_it_is_answered(store, acme_with_year_one):
    # Who was at a meal changes its VAT and tax: the year waits for the answer, or for a person to accept it.
    add_rows(store, acme_with_year_one, row(date=date(2025, 6, 1), gross=D("28.15"), account_code="7406",
                                            description="ExCeL London Hospitality"))
    with pytest.raises(InvalidInput, match="1 question that changes the tax"):
        books.close(store, acme_with_year_one, date(2025, 4, 1))
    meal = next(t for t in books.ledger(store, acme_with_year_one, YEAR_1).transactions if t.account_code == "7406")
    ledger.change_row(store, acme_with_year_one, meal.id, RowPatch(accepted=["meal_check"]))
    books.close(store, acme_with_year_one, date(2025, 4, 1))


def test_years_close_in_order_and_reopen_from_the_latest(store, acme_two_years):
    with pytest.raises(InvalidInput, match="Close the year to 31 Mar 2026 first"):
        books.close(store, acme_two_years, date(2026,4,1))
    books.close(store, acme_two_years, date(2025,4,1)); books.close(store, acme_two_years, date(2026,4,1))
    with pytest.raises(InvalidInput, match="Reopen the year to 31 Mar 2027 first"):
        books.reopen(store, acme_two_years, date(2025,4,1))


def test_paying_a_closed_years_invoice_leaves_that_year_alone(store, acme_with_unpaid_bill_in_year_one):
    before = books.trial_balance(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    books.close(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,5,10)))
    after = books.ledger(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    assert books.trial_balance(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1)).lines == before.lines
    assert not after.year.changed_since_closed and bill_row(after).owed == 0


def test_reopen_edit_and_close_again_moves_the_next_years_opening(store, acme_two_years):
    # acme_two_years: year 1 holds a £60.00 stationery receipt paid from the bank (no VAT shown); year 2 one row
    def bank_opening():
        tb = books.trial_balance(store, acme_two_years, date(2026,4,1))
        return {l.code: l.debit - l.credit for l in tb.opening}["1200"]
    books.close(store, acme_two_years, date(2025,4,1))
    before = bank_opening()
    books.reopen(store, acme_two_years, date(2025,4,1))
    change_stationery_receipt_to(store, acme_two_years, D("80.00"))
    books.close(store, acme_two_years, date(2025,4,1))
    assert bank_opening() == before - D("20.00")


def test_closing_saves_the_years_balances_and_marks_it_closed(store, acme_with_year_one):
    client = books.close(store, acme_with_year_one, YEAR_1)
    [closed] = client.closed_years
    assert (closed.start, closed.end, closed.closing) == (YEAR_1, date(2026, 3, 31),
                                                          {"1200": D("-60.00"), "7504": D("60.00")})
    assert store.get_client(acme_with_year_one).closed_years == client.closed_years
    year1, year2 = books.ledger(store, acme_with_year_one, YEAR_1).years
    assert (year1.closed, year2.closed) == (True, False)
    assert books.reopen(store, acme_with_year_one, YEAR_1).closed_years == []
    assert not books.ledger(store, acme_with_year_one, YEAR_1).year.closed


def test_a_year_whose_trial_balance_cant_be_built_isnt_closed(store, acme):
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("50.00"), account_code="9999"))
    with pytest.raises(InvalidInput, match="1 row of the year has a problem to fix before it can be closed: x"):
        books.close(store, acme, YEAR_1)
    assert store.get_client(acme).closed_years == []


def test_a_year_is_closed_or_reopened_once(store, acme_with_year_one):
    with pytest.raises(InvalidInput, match="The year to 31 Mar 2026 is open."):
        books.reopen(store, acme_with_year_one, YEAR_1)
    books.close(store, acme_with_year_one, YEAR_1)
    with pytest.raises(InvalidInput, match="The year to 31 Mar 2026 is already closed."):
        books.close(store, acme_with_year_one, YEAR_1)


def test_the_next_year_opens_from_the_saved_closing(store, acme_two_years):
    books.close(store, acme_two_years, YEAR_1)
    assert books.opening(store, acme_two_years, YEAR_2) == {"1200": D("-60.00"), "3200": D("60.00")}
    # The saved closing stands even when the rows behind it now work out otherwise (written past the guard).
    change = next(r for r in store.rows(acme_two_years) if r.tx.account_code == "7504")
    store.patch_row(acme_two_years, change.id, {"gross": "70.00"})
    assert books.opening(store, acme_two_years, YEAR_2) == {"1200": D("-60.00"), "3200": D("60.00")}
    assert books.ledger(store, acme_two_years, YEAR_1).year.changed_since_closed
    assert not books.ledger(store, acme_two_years, YEAR_2).year.changed_since_closed


def test_every_change_to_a_closed_years_rows_is_refused(store, acme_two_years):
    books.close(store, acme_two_years, YEAR_1)
    receipt = next(r for r in store.rows(acme_two_years) if r.tx.account_code == "7504")
    phone = next(r for r in store.rows(acme_two_years) if r.tx.account_code == "7502")
    refusals = [
        lambda: ledger.remove_row(store, acme_two_years, receipt.id),
        lambda: ledger.remove_upload(store, acme_two_years, receipt.upload_id),
        lambda: ledger.set_upload_bank(store, acme_two_years, receipt.upload_id, "1200"),
        lambda: ledger.add_manual(store, acme_two_years, ManualUpload(transactions=[row(date=date(2025, 7, 1),
                                                                                         gross=D("5.00"))])),
        lambda: ledger.add_manual(store, acme_two_years, ManualUpload(transactions=[row(date=date(2025, 3, 1),
                                                                                         gross=D("5.00"))])),
        # moving a row of an open year into the closed one
        lambda: ledger.change_row(store, acme_two_years, phone.id, RowPatch(date=date(2026, 3, 1))),
        lambda: books.set_opening(store, acme_two_years, OPENING_BANK),
    ]
    for refused in refusals:
        with pytest.raises(YearClosed, match=r"The year to 31 Mar 2026 is closed\. Reopen it to change it\."):
            refused()
    assert len(store.rows(acme_two_years)) == 2 and store.opening(acme_two_years) == OpeningBalances()
    # the open year still takes changes
    ledger.change_row(store, acme_two_years, phone.id, RowPatch(gross=D("30.00")))


def test_the_year_end_cant_change_once_a_year_is_closed(store, acme_with_year_one):
    books.close(store, acme_with_year_one, YEAR_1)
    with pytest.raises(InvalidInput, match="The year end can't change once a year is closed."):
        ledger.change_client(store, acme_with_year_one, ClientPatch(first_year_end=date(2026, 12, 31)))
    assert ledger.change_client(store, acme_with_year_one, ClientPatch(name="Acme Trading Ltd")).name == (
        "Acme Trading Ltd")


def test_vat_registration_and_business_type_cant_change_once_a_year_is_closed(store, acme_with_year_one):
    books.close(store, acme_with_year_one, YEAR_1)
    with pytest.raises(YearClosed, match="Reopen the closed years to change the client's VAT registration: it "
                                         "changes how they were booked."):
        ledger.change_client(store, acme_with_year_one, ClientPatch(vat_registered=False))
    with pytest.raises(YearClosed, match="Reopen the closed years to change the client's business type: it "
                                         "changes how they were booked."):
        ledger.change_client(store, acme_with_year_one, ClientPatch(business_type="sole_trader"))
    same = ledger.change_client(store, acme_with_year_one, ClientPatch(vat_registered=True,
                                                                       business_type="limited_company"))
    assert (same.vat_registered, same.business_type) == (True, "limited_company")
    books.reopen(store, acme_with_year_one, YEAR_1)
    changed = ledger.change_client(store, acme_with_year_one, ClientPatch(vat_registered=False,
                                                                          business_type="sole_trader"))
    assert (changed.vat_registered, changed.business_type) == (False, "sole_trader")


def test_a_bank_account_can_still_be_added_after_closing(store, acme_with_year_one):
    books.close(store, acme_with_year_one, YEAR_1)
    [current] = store.get_client(acme_with_year_one).bank_accounts
    changed = ledger.change_client(store, acme_with_year_one, ClientPatch(bank_accounts=[
        current.model_copy(update={"name": "Barclays current"}), BankAccount(name="Amex card", kind="credit_card")]))
    assert [(a.name, a.kind) for a in changed.bank_accounts] == [("Barclays current", "current"),
                                                                 ("Amex card", "credit_card")]


# ─── Invoices, bank checks and the year's summary (Task 9) ────────────────────

def test_an_invoice_paid_next_year_shows_as_owed_at_the_year_end_and_paid_now(store, acme_with_unpaid_bill_in_year_one):
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,5,10)))
    [bill] = books.invoices(store, acme_with_unpaid_bill_in_year_one, date(2026,4,1))
    assert bill.kind == "purchase" and bill.owed == 0 and bill.paid_by[0].date == date(2026,5,10)


def test_an_invoice_paid_after_its_year_end_says_what_was_owed_at_the_year_end(store, acme_with_unpaid_bill_in_year_one):
    # The agency's Mendip and Brightwater invoices of February and March 2024, paid in April: the year's list said
    # nothing was owed on them, and its "owed at 31 Mar 2024" total left out £32,880 the trial balance's Debtors
    # holds (agency run, 25 Nov 2026).
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026, 5, 10)))
    [bill] = books.invoices(store, acme_with_unpaid_bill_in_year_one, date(2025, 4, 1))
    assert (bill.owed, bill.owed_at_year_end) == (0, D("300.00"))
    [now] = books.invoices(store, acme_with_unpaid_bill_in_year_one, date(2026, 4, 1))
    assert now.brought_forward and now.owed_at_year_end == 0


def test_the_bank_check_compares_the_books_with_the_statement(store, acme_with_statement_missing_a_line):
    [check] = books.bank_checks(store, acme_with_statement_missing_a_line, date(2025,4,1))
    assert check.difference == D("-25.00") and check.statement_date == date(2025,9,30)


def test_a_blocked_trial_balance_shows_in_the_summary(store, acme_with_a_non_gbp_row):
    s = books.summary(store, acme_with_a_non_gbp_row, date(2025,4,1))
    assert s.trial_balance == "blocked" and "enter the amount in pounds" in s.problems[0]


def test_a_sale_part_paid_in_the_year_shows_what_is_paid_and_owed(store, acme):
    add_rows(store, acme, row(date=date(2025,6,1), direction="in", gross=D("1200.00"), vat=D("200.00"),
                              account_code="4000", document_type="invoice", counterparty="Bright Cafe",
                              document_number="INV-7", document_ref="sale"),
             row(date=date(2025,6,20), direction="in", gross=D("500.00"), document_type="statement",
                 counterparty="BRIGHT CAFE"))
    [sale] = books.invoices(store, acme, YEAR_1)
    assert (sale.kind, sale.counterparty, sale.number, sale.date) == ("sale", "Bright Cafe", "INV-7", date(2025,6,1))
    assert (sale.total, sale.paid, sale.owed, sale.brought_forward) == (D("1200.00"), D("500.00"), D("700.00"), False)
    assert books.summary(store, acme, YEAR_1).unpaid_sales == D("700.00")


def test_an_unpaid_item_brought_forward_is_listed_first_with_its_own_date_and_number(store, acme):
    books.set_opening(store, acme, OpeningBalances(
        lines=[OpeningLine(code="1200", debit=D("500.00")), OpeningLine(code="2100", credit=D("500.00"))],
        unpaid=[OpenItem(id="1", direction="out", counterparty="Smith Solicitors Ltd", amount=D("500.00"),
                         number="S-12", date=date(2025,2,14))]))
    add_rows(store, acme, row(date=date(2025,7,1), gross=D("40.00"), document_type="invoice", counterparty="BT",
                              document_ref="bt"))
    [old, new] = books.invoices(store, acme, YEAR_1)
    assert (old.kind, old.number, old.date, old.owed, old.brought_forward) == ("purchase", "S-12", date(2025,2,14),
                                                                              D("500.00"), True)
    assert (new.counterparty, new.brought_forward) == ("BT", False)


def test_a_bill_paid_before_the_year_started_is_not_listed_in_it(store, acme_with_unpaid_bill_in_year_one):
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,3,20)))
    assert books.invoices(store, acme_with_unpaid_bill_in_year_one, YEAR_2) == []
    [bill] = books.invoices(store, acme_with_unpaid_bill_in_year_one, YEAR_1)
    assert (bill.owed, bill.paid) == (0, D("300.00"))


def test_a_bank_account_without_a_statement_shows_its_books_at_the_year_end(store, acme_with_year_one):
    [check] = books.bank_checks(store, acme_with_year_one, YEAR_1)
    assert (check.code, check.books, check.statement, check.statement_date, check.difference) == (
        "1200", D("-60.00"), None, None, None)


def test_a_credit_card_is_shown_as_what_is_owed_on_it(store, acme):
    ledger.change_client(store, acme, ClientPatch(bank_accounts=[
        *store.get_client(acme).bank_accounts, BankAccount(name="Amex card", kind="credit_card")]))
    card = store.get_client(acme).bank_accounts[1].code
    line = dict(document_type="statement", bank_account=card, account_code="7504", counterparty="Paper Shop")
    add_rows(store, acme, row(**line, date=date(2025,8,1), gross=D("80.00"), opening_balance=D("0.00"),
                              balance=D("80.00")),
             row(**line, date=date(2025,8,9), gross=D("20.00"), balance=D("100.00"), closing_balance=D("100.00")),
             bank_account=card)
    current, amex = books.bank_checks(store, acme, YEAR_1)
    assert (current.books, current.statement) == (0, None)
    assert (amex.books, amex.statement, amex.difference) == (D("100.00"), D("100.00"), D("0.00"))


def test_the_summary_counts_the_rows_to_review_and_checks_the_banks(store, acme_with_statement_missing_a_line):
    s = books.summary(store, acme_with_statement_missing_a_line, YEAR_1)
    assert (s.rows, s.trial_balance, s.problems) == (2, "balanced", [])
    assert s.to_review == 1 and s.bank[0].difference == D("-25.00")
    assert not s.year.closed


def test_a_blocked_year_still_has_bank_checks_which_say_a_row_is_left_out(store, acme_with_a_non_gbp_row):
    [in_summary] = books.summary(store, acme_with_a_non_gbp_row, YEAR_1).bank
    [check] = books.bank_checks(store, acme_with_a_non_gbp_row, YEAR_1)
    assert in_summary == check and (check.books, check.left_out) == (D("0.00"), 1)


def test_an_unknown_year_is_not_found_for_each_view(store, acme):
    for view in (books.invoices, books.bank_checks, books.summary):
        with pytest.raises(NotFound, match="That year was not found."):
            view(store, acme, date(2025, 4, 2))


def test_a_years_summary_shows_what_was_owed_at_its_end(store, acme_with_unpaid_bill_in_year_one):
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,5,10)))
    assert books.summary(store, acme_with_unpaid_bill_in_year_one, YEAR_1).unpaid_purchases == D("300.00")
    [bill] = books.invoices(store, acme_with_unpaid_bill_in_year_one, YEAR_2)
    assert bill.owed == 0
    assert books.summary(store, acme_with_unpaid_bill_in_year_one, YEAR_2).unpaid_purchases == 0


def test_an_undated_manual_row_goes_in_the_year_it_was_added_to(store, acme_two_years):
    # "today" is in year 2 (the latest year), but the row is added while viewing year 1
    ledger.add_manual(store, acme_two_years, ManualUpload(year_start=YEAR_1, transactions=[row(date=None, gross=D("7.00"))]))
    in_year_1 = books.ledger(store, acme_two_years, YEAR_1)
    in_year_2 = books.ledger(store, acme_two_years, YEAR_2)
    assert [t.gross for t in in_year_1.transactions if t.date is None] == [D("7.00")]
    assert not [t for t in in_year_2.transactions if t.date is None]


def test_an_undated_manual_row_is_allowed_in_an_open_year_and_refused_in_a_closed_one(store, acme_two_years):
    books.close(store, acme_two_years, YEAR_1)
    undated = [row(date=None, gross=D("7.00"))]
    with pytest.raises(YearClosed, match=r"The year to 31 Mar 2026 is closed"):
        ledger.add_manual(store, acme_two_years, ManualUpload(year_start=YEAR_1, transactions=undated))
    added = ledger.add_manual(store, acme_two_years, ManualUpload(year_start=YEAR_2, transactions=undated))
    assert added.year.start == YEAR_2 and [t.gross for t in added.transactions if t.date is None] == [D("7.00")]


def test_a_manual_row_for_an_unknown_year_is_not_found(store, acme_two_years):
    with pytest.raises(NotFound, match="That year was not found."):
        ledger.add_manual(store, acme_two_years, ManualUpload(year_start=date(2020, 4, 1), transactions=[row(gross=D("5.00"))]))


def test_a_purchase_of_50_or_more_without_its_document_is_held_in_suspense(mongo_store, acme_with_year_one):
    add_rows(mongo_store, acme_with_year_one, row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400",
             document_type="statement", counterparty="Trainline", description="TRAINLINE"), year_start=date(2025, 4, 1))
    tb = books.trial_balance(mongo_store, acme_with_year_one, date(2025, 4, 1))
    assert net(tb, "9998") == D("240.00") and net(tb, "7400") == 0


def test_a_purchase_under_50_without_a_document_is_a_cost_with_no_vat(mongo_store, acme_with_year_one):
    add_rows(mongo_store, acme_with_year_one, row(date=date(2025, 7, 1), gross=D("38.50"), vat=D("6.42"),
             account_code="7300", document_type="statement", description="SHELL"), year_start=date(2025, 4, 1))
    tb = books.trial_balance(mongo_store, acme_with_year_one, date(2025, 4, 1))
    assert net(tb, "7300") == D("38.50") and net(tb, "2201") == 0


def test_the_rows_trial_balance_equals_the_posted_one(mongo_store, mongo_db, acme_with_year_one):
    from ledgersync import ledger_book
    from ledgersync.records import AgentRecords
    add_rows(mongo_store, acme_with_year_one,
             row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400", document_type="statement",
                 counterparty="Trainline", description="TRAINLINE"),
             row(date=date(2025, 7, 2), gross=D("38.50"), vat=D("6.42"), account_code="7300",
                 document_type="statement", description="SHELL"), year_start=date(2025, 4, 1))
    records = AgentRecords(mongo_db)
    ledger_book.post(mongo_store, records, acme_with_year_one, date(2025, 4, 1))
    rows = books.trial_balance(mongo_store, acme_with_year_one, date(2025, 4, 1))
    posted = ledger_book.posted_trial_balance(mongo_store, records, acme_with_year_one, date(2025, 4, 1))
    lines = lambda tb: sorted((l.code, l.debit, l.credit) for l in tb.lines)
    assert lines(rows) and lines(rows) == lines(posted)


def test_a_held_purchase_says_what_it_needs(mongo_store, acme_with_year_one):
    # The firm's materiality, so the fixture's £60 stationery receipt is too small to ask about as equipment.
    ledger.change_client(mongo_store, acme_with_year_one, ClientPatch(materiality=D("1500")))
    add_rows(mongo_store, acme_with_year_one,
             row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400", document_type="statement",
                 counterparty="Trainline", description="TRAINLINE"),
             row(date=date(2025, 7, 2), gross=D("300.00"), account_code="7504", document_type="statement",
                 counterparty="Currys", description="CURRYS"),
             row(date=date(2025, 7, 4), gross=D("310.00"), account_code="7400", document_type="statement",
                 counterparty="Trainline", description="TRAINLINE"),
             row(date=date(2025, 7, 3), gross=D("38.50"), vat=D("6.42"), account_code="7300",
                 document_type="statement", description="SHELL"), year_start=date(2025, 4, 1))
    rows = books.ledger(mongo_store, acme_with_year_one, date(2025, 4, 1)).transactions
    said = {r.gross: [i.message for i in r.issues if i.code == "needs_document"] for r in rows}
    assert said[D("240.00")] == ["Held in Suspense: needs its receipt or invoice."]
    assert said[D("300.00")] == ["Held in Suspense: needs a full VAT invoice."]
    # a fare is zero-rated, so over £250 it still only needs its receipt: no VAT invoice exists to wait for
    assert said[D("310.00")] == ["Held in Suspense: needs its receipt or invoice."]
    assert said[D("38.50")] == []
    assert all(i.severity == "warning" for r in rows for i in r.issues if i.code == "needs_document")
    assert books.summary(mongo_store, acme_with_year_one, date(2025, 4, 1)).to_review == 3


# ─── Closed is closed: a year closed before the document rules stays as it closed ──────────────────────────────

def close_without_the_rules(store, client_id: int, start: date) -> None:
    """Closes the year as it was closed before the document rules: its figures worked out without them, no stamp."""
    from ledgersync.models import ClosedYear
    from ledgersync.rows import now_iso
    b = books._books(store, client_id)
    n = b.index(start)
    tb = b.post(b.settings_in(n), keep=[p == n for p in b.placed], opening=books._opening(b, n), rules=False)
    store.close_year(client_id, ClosedYear(start=b.years[n].start, end=b.years[n].end, closed_at=now_iso(),
                                           closing=books._balances(tb)))


def a_legacy_year_with_a_statement_line(mongo_store, acme_with_year_one) -> int:
    add_rows(mongo_store, acme_with_year_one, row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400",
             document_type="statement", counterparty="Trainline", description="TRAINLINE"), year_start=YEAR_1)
    close_without_the_rules(mongo_store, acme_with_year_one, YEAR_1)
    return acme_with_year_one


def test_a_year_closed_before_the_rules_keeps_its_figures_and_holds_nothing(mongo_store, acme_with_year_one):
    client_id = a_legacy_year_with_a_statement_line(mongo_store, acme_with_year_one)

    tb = books.trial_balance(mongo_store, client_id, YEAR_1)
    built = books.ledger(mongo_store, client_id, YEAR_1)

    assert (net(tb, "7400"), net(tb, "9998")) == (D("240.00"), D("0.00"))
    assert built.year.changed_since_closed is False
    assert not [i for r in built.transactions for i in r.issues if i.code == "needs_document"]
    assert books.summary(mongo_store, client_id, YEAR_1).year.changed_since_closed is False
    assert books.export(mongo_store, client_id, YEAR_1, date(2026, 1, 1))[0]


def test_reopening_a_year_closed_before_the_rules_applies_them(mongo_store, acme_with_year_one):
    client_id = a_legacy_year_with_a_statement_line(mongo_store, acme_with_year_one)

    books.reopen(mongo_store, client_id, YEAR_1)

    tb = books.trial_balance(mongo_store, client_id, YEAR_1)
    assert (net(tb, "7400"), net(tb, "9998")) == (D("0.00"), D("240.00"))
    built = books.ledger(mongo_store, client_id, YEAR_1)
    assert [i for r in built.transactions for i in r.issues if i.code == "needs_document"]


def test_a_year_closed_now_is_stamped_with_the_rules(mongo_store, acme_with_year_one):
    client = books.close(mongo_store, acme_with_year_one, YEAR_1)

    assert client.closed_years[0].rules == "document_rules"


# ─── Statements that print only running balances, and missing paperwork ──────

def _october_statement(**extra):
    """A statement for October 2025 printing only running balances: it opens at £1,000.00 (before its first line) and
    closes at £950.00."""
    line = dict(document_type="statement", **extra)
    return (row(**line, date=date(2025, 10, 1), gross=D("100.00"), account_code="7504", counterparty="Paper Shop",
                balance=D("900.00")),
            row(**line, date=date(2025, 10, 2), direction="in", gross=D("50.00"), account_code="4000",
                counterparty="Bright Cafe", balance=D("950.00")))


def test_a_statement_with_only_running_balances_is_checked_against_its_last_one(store, acme):
    add_rows(store, acme, *_october_statement())
    [check] = books.bank_checks(store, acme, YEAR_1)
    assert (check.statement, check.statement_date, check.books, check.difference) == (
        D("950.00"), date(2025, 10, 2), D("-50.00"), D("-1000.00"))


def test_statements_missing_before_the_first_one_are_named_with_the_gap(store, acme):
    add_rows(store, acme, *_october_statement())
    name = store.get_client(acme).bank_accounts[0].name
    assert books.summary(store, acme, YEAR_1).missing_paperwork == [
        f"{name}: no statements for April to September 2025. The statement from 1 Oct 2025 opens at £1,000.00; "
        "the books have £0.00 then."]


def test_a_statement_that_follows_on_from_the_books_needs_nothing_more(store, acme_with_statement_missing_a_line):
    assert books.summary(store, acme_with_statement_missing_a_line, YEAR_1).missing_paperwork == []


def test_a_gap_between_two_statements_is_named(store, acme):
    line = dict(document_type="statement", account_code="7504", counterparty="Paper Shop")
    add_rows(store, acme, row(**line, date=date(2025, 4, 3), gross=D("10.00"), opening_balance=D("0.00"),
                              balance=D("-10.00"), closing_balance=D("-10.00")))
    add_rows(store, acme, *_october_statement())
    name = store.get_client(acme).bank_accounts[0].name
    assert books.summary(store, acme, YEAR_1).missing_paperwork == [
        f"{name}: no statements for May to September 2025. The statement from 1 Oct 2025 opens at £1,000.00; "
        "the one before closed at -£10.00."]


def test_an_account_with_no_statement_is_named(store, acme):
    ledger.change_client(store, acme, ClientPatch(bank_accounts=[
        *store.get_client(acme).bank_accounts, BankAccount(name="Starling savings", kind="savings")]))
    add_rows(store, acme, *_october_statement())
    missing = books.summary(store, acme, YEAR_1).missing_paperwork
    assert missing[-1] == "Starling savings: no statement for this year yet."


def test_an_overdrawn_directors_loan_is_pointed_out(store, acme):
    add_rows(store, acme, row(date=date(2025, 10, 9), gross=D("2000.00"), account_code="2250",
                              document_type="statement", counterparty="P ASHDOWN"))
    assert books.summary(store, acme, YEAR_1).pointers == [
        "The Director's Loan Account is overdrawn by £2,000.00 (the director owes the company). If it is still owed "
        "nine months after the year end, s455 tax is due on it."]


def test_a_directors_loan_owed_to_the_director_needs_no_pointer(store, acme):
    add_rows(store, acme, row(date=date(2025, 10, 9), direction="in", gross=D("500.00"), account_code="2250",
                              document_type="statement", counterparty="P ASHDOWN"))
    assert books.summary(store, acme, YEAR_1).pointers == []


def test_the_same_payment_from_two_uploads_says_it_may_be_a_duplicate_where_the_ai_sees_it(store, acme):
    add_rows(store, acme, row(gross=D("12.88"), description="Chopstix", date=date(2025, 9, 14)))
    add_rows(store, acme, row(gross=D("12.88"), description="Chopstix again", date=date(2025, 9, 15)))
    first, second = books.ledger(store, acme, YEAR_1).transactions
    assert not any(i.code == "possible_duplicate" for i in first.issues)
    [said] = [i for i in second.issues if i.code == "possible_duplicate"]
    assert said.severity == "warning" and said.related == [first.id] and '"Chopstix"' in said.message


def test_an_undated_bill_takes_the_day_its_file_name_and_its_claim_line_share(store, acme):
    from ledgersync.models import Transaction
    sheet = [row(gross=D(g), date=date(2025, 9, d), description="EE, mobile phone bill", counterparty="Matt Barnes",
                 document_type="expense_claim", document_ref="sheet") for g, d in (("27.50", 3), ("27.50", 4))]
    add_rows(store, acme, *sheet)
    upload = store.add_upload(acme, "EE-2025-09-04_00_00_00.jpg", "image", [Transaction(
        date=None, description="EE monthly charges", direction="out", gross=D("27.50"), account_code="7502",
        document_type="invoice", counterparty="EE")], year_start=YEAR_1)
    [bill] = [r for r in books.ledger(store, acme, YEAR_1).transactions if r.upload_id == upload]
    assert bill.date == date(2025, 9, 4) and bill.claimed_in is not None
    assert not any(i.code in ("date_missing", "file_date") for i in bill.issues)
    # The trial balance pairs them alike: the 4 Sep line and its bill count once (£27.50 + £27.50, not £82.50).
    assert books.trial_balance(store, acme, YEAR_1).total_expenses == D("55.00")


def test_two_statements_that_overlap_are_not_a_gap_and_their_shared_line_counts_once(store, acme):
    add_rows(store, acme, *_october_statement())
    line = dict(document_type="statement")
    add_rows(store, acme,
             row(**line, date=date(2025, 10, 2), direction="in", gross=D("50.00"), account_code="4000",
                 counterparty="Bright Cafe", balance=D("950.00")),
             row(**line, date=date(2025, 10, 3), gross=D("20.00"), account_code="7504", counterparty="Paper Shop",
                 balance=D("930.00")))
    name = store.get_client(acme).bank_accounts[0].name
    assert books.summary(store, acme, YEAR_1).missing_paperwork == [
        f"{name}: no statements for April to September 2025. The statement from 1 Oct 2025 opens at £1,000.00; "
        "the books have £0.00 then."]
    [check] = books.bank_checks(store, acme, YEAR_1)
    assert (check.statement, check.books, check.difference) == (D("930.00"), D("-70.00"), D("-1000.00"))
    repeated = books.ledger(store, acme, YEAR_1).transactions[2]
    assert repeated.copy_of is not None and [i.code for i in repeated.issues] == ["duplicate_document"]


def test_a_revised_invoice_under_the_old_number_is_said_on_the_later_one(store, acme):
    bill = dict(document_type="invoice", counterparty="Ashdown Supplies Ltd", document_number="A-551",
                account_code="5000")
    add_rows(store, acme, row(**bill, date=date(2025, 5, 10), gross=D("360.00"), document_total=D("360.00"),
                              description="Plasterboard x 60"))
    add_rows(store, acme, row(**bill, date=date(2025, 5, 12), gross=D("240.00"), document_total=D("240.00"),
                              description="Plasterboard x 40"))
    original, revised = books.ledger(store, acme, YEAR_1).transactions
    [said] = [i for i in revised.issues if i.code == "possible_duplicate"]
    assert said.related == [original.id] and said.message == (
        'Same invoice number (A-551) as "Plasterboard x 60" of 10 May 2025 for £360.00. If this one replaces it, '
        "leave that one out; if they are two invoices, keep both.")
    assert not any(i.code == "possible_duplicate" for i in original.issues)



# ─── UAT round 2, high issues ──────────────────────────────────────────────────

def test_one_problem_row_doesnt_hide_the_bank_check(store, acme_with_a_non_gbp_row):
    # One row to fix blocked Bank and Overview for the whole client, while the trial balance page still showed.
    add_rows(store, acme_with_a_non_gbp_row, row(date=date(2025, 6, 2), direction="in", gross=D("400.00"),
                                                  document_type="statement", account_code="4000"))
    [check] = books.bank_checks(store, acme_with_a_non_gbp_row, YEAR_1)
    assert check.books == D("400.00")
    s = books.summary(store, acme_with_a_non_gbp_row, YEAR_1)
    assert s.trial_balance == "blocked" and [c.books for c in s.bank] == [D("400.00")]


def test_the_vat_figures_include_the_reverse_charge(store, acme):
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("55.20"), account_code="7502", document_type="invoice",
                              counterparty="Google Cloud EMEA Ltd", document_ref="g", reverse_charge=True))
    v = books.vat_figures(store, acme, YEAR_1)
    assert (v.box1, v.box4, v.box5, v.box6, v.box7) == (D("11.04"), D("11.04"), D("0.00"), D("55.20"), D("55.20"))
    assert any("reverse-charge" in note for note in v.notes)


def test_a_client_registered_for_vat_part_way_through_the_year(store, acme):
    ledger.change_client(store, acme, ClientPatch(vat_from=date(2025, 10, 1)))
    for day, ref in ((date(2025, 6, 1), "a"), (date(2025, 11, 1), "b")):
        add_rows(store, acme, row(date=day, direction="in", gross=D("1200.00"), vat=D("200.00"), account_code="4000",
                                  document_type="invoice", counterparty="Bright Cafe", document_ref=ref))
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "4000"), net(tb, "2200")) == (D("-2200.00"), D("-200.00"))
    v = books.vat_figures(store, acme, YEAR_1)
    assert (v.box1, v.box6) == (D("200.00"), D("1000.00"))
    assert store.get_client(ledger.change_client(store, acme, ClientPatch(vat_from=None)).id).vat_from is None


def test_a_person_can_say_a_judgement_warning_is_fine(store, acme):
    ledger.change_client(store, acme, ClientPatch(materiality=D("1500")))   # trivial £45: a £9.67 cable is small
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("9.67"), account_code="0030"))
    [cable] = books.ledger(store, acme, YEAR_1).transactions
    assert [i.code for i in cable.issues] == ["small_asset"]
    [cable] = ledger.change_row(store, acme, cable.id, RowPatch(accepted=["small_asset"])).transactions
    assert cable.issues == []
    with pytest.raises(InvalidInput, match="matter of judgement"):
        ledger.change_row(store, acme, cable.id, RowPatch(accepted=["vat_arithmetic"]))


# ─── UAT round 2, medium issues ────────────────────────────────────────────────

def test_a_document_dated_after_this_year_is_asked_about(store, acme):
    import datetime
    ahead = date(datetime.date.today().year + 2, 6, 1)
    add_rows(store, acme, row(date=ahead, gross=D("96.00"), document_type="invoice", document_ref="hss"))
    cid = acme
    [future] = [r for y in books.years_of(store, cid, datetime.date.today())
                for r in books.ledger(store, cid, y.start).transactions]
    assert [i.code for i in future.issues] == ["future_date"]
    [fine] = [r for r in ledger.change_row(store, cid, future.id, RowPatch(accepted=["future_date"])).transactions]
    assert fine.issues == []


def test_a_first_year_end_must_be_sensible_and_keep_the_rows(store, acme):
    with pytest.raises(InvalidInput, match="Enter a first year end between"):
        ledger.change_client(store, acme, ClientPatch(first_year_end=date(1990, 3, 31)))
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("10.00")))
    with pytest.raises(InvalidInput, match="1 row of the books is dated before"):
        ledger.change_client(store, acme, ClientPatch(first_year_end=date(2027, 3, 31)))
    assert ledger.change_client(store, acme, ClientPatch(first_year_end=date(2025, 12, 31))).first_year_end == date(2025, 12, 31)


@pytest.mark.parametrize("change, message", [
    ({"company_number": "ABC"}, "A company number has 8 characters"),
    ({"vat_number": "GB 12"}, "A VAT number has 9 digits"),
    ({"utr": "12345"}, "A UTR has 10 digits"),
    ({"paye_reference": "abc"}, "A PAYE reference looks like"),
])
def test_a_reference_is_written_as_its_issuer_writes_it(store, acme, change, message):
    with pytest.raises(InvalidInput, match=message):
        ledger.change_client(store, acme, ClientPatch(**change))
    good = ClientPatch(company_number="sc123456", vat_number="GB 123 4567 89", utr="1234567890", paye_reference="123/AB456")
    assert ledger.change_client(store, acme, good).vat_number == "GB 123 4567 89"


def test_a_journal_far_ahead_or_for_billions_is_refused(store, acme):
    import datetime
    def entry(**kw):
        fields = dict(date=date(2025, 6, 1), gross=D("100.00"), account_code="8000", contra_account_code="0031",
                      document_type="journal", description="Depreciation")
        return ManualUpload(name="Journal", kind="manual", transactions=[row(**{**fields, **kw})])
    with pytest.raises(InvalidInput, match="more than a year ahead"):
        ledger.add_manual(store, acme, entry(date=date(datetime.date.today().year + 5, 4, 30)))
    with pytest.raises(InvalidInput, match="too large"):
        ledger.add_manual(store, acme, entry(gross=D("99999999999.99")))
    ledger.add_manual(store, acme, entry())


# ─── A bill coded away from its supplier's usual account ───────────────────────

def vodafone(n, code, first=date(2025, 4, 20), **more):
    """n Vodafone Ltd invoices of £86.40 on the account, a month apart from `first`, each its own document."""
    return [row(**{**dict(document_type="invoice", counterparty="Vodafone Ltd", description="Vodafone bill",
                          gross=D("86.40"), account_code=code, document_ref=f"voda-{code}-{first}-{k}",
                          date=date(first.year + (first.month - 1 + k) // 12, (first.month - 1 + k) % 12 + 1, first.day)),
                   **more}) for k in range(n)]


def test_a_bill_on_the_wrong_account_says_the_usual_one(store, acme):
    add_rows(store, acme, *vodafone(11, "7502"), *vodafone(1, "7400", first=date(2026, 3, 20)))
    rows = books.ledger(store, acme, YEAR_1).transactions
    usual, odd = rows[:11], rows[11]
    assert not any(i.code == "unusual_account" for r in usual for i in r.issues)
    [said] = [i for i in odd.issues if i.code == "unusual_account"]
    assert said.severity == "warning"
    assert said.message == ("Coded to 7400 Travel. The other 11 bills from Vodafone Ltd went to "
                            "7502 Telephone and Internet.")
    assert len(said.related) == 5 and set(said.related) <= {r.id for r in usual}


def test_most_but_not_all_of_the_other_bills_says_how_many(store, acme):
    add_rows(store, acme, *vodafone(4, "7502"), *vodafone(1, "7600", first=date(2025, 9, 20)),
             *vodafone(1, "7400", first=date(2025, 10, 20)))
    odd = books.ledger(store, acme, YEAR_1).transactions[5]
    [said] = [i for i in odd.issues if i.code == "unusual_account"]
    assert said.message == ("Coded to 7400 Travel. 4 of the other 5 bills from Vodafone Ltd went to "
                            "7502 Telephone and Internet.")


def test_an_accepted_unusual_account_is_quiet(store, acme):
    add_rows(store, acme, *vodafone(11, "7502"),
             *vodafone(1, "7400", first=date(2026, 3, 20), accepted=["unusual_account"]))
    assert not any(i.code == "unusual_account" for r in books.ledger(store, acme, YEAR_1).transactions for i in r.issues)


def test_a_closed_years_row_is_history_but_never_flagged(store, acme):
    add_rows(store, acme, *vodafone(4, "7502"), *vodafone(1, "7400", first=date(2025, 9, 20)))
    add_rows(store, acme, *vodafone(1, "7400", first=date(2026, 5, 20)))
    books.close(store, acme, YEAR_1)
    assert not any(i.code == "unusual_account" for r in books.ledger(store, acme, YEAR_1).transactions for i in r.issues)
    [later] = books.ledger(store, acme, YEAR_2).transactions
    [said] = [i for i in later.issues if i.code == "unusual_account"]
    assert said.message.startswith("Coded to 7400 Travel. 4 of the other 5 bills")


@pytest.mark.mongo
def test_vat_the_rules_do_not_reclaim_is_said_on_the_row_and_the_books_hold_none(store, acme):
    # A £547.84 receipt for phones with £91.31 VAT on it: over £250 with no full VAT invoice, so it is held whole in
    # Suspense. A £9.72 receipt with the supplier's VAT number reclaims its £1.62, and says nothing. (A hotel stay in
    # the UK is booked with its VAT at once: the test after next.)
    add_rows(store, acme,
             row(date=date(2025, 6, 1), gross=D("547.84"), vat=D("91.31"), account_code="7502", description="Phones"),
             row(date=date(2025, 6, 2), gross=D("9.72"), vat=D("1.62"), account_code="7406", description="Bap",
                 supplier_vat_number="123456789"))
    phones, bap = books.ledger(store, acme, YEAR_1).transactions
    assert (phones.vat_posted, phones.vat_not_reclaimed) == (D("91.31"), D("91.31")) and "VAT invoice" in phones.vat_not_reclaimed_why
    assert (bap.vat_posted, bap.vat_not_reclaimed, bap.vat_not_reclaimed_why) == (D("1.62"), None, None)
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "9998"), net(tb, "7502"), net(tb, "2201")) == (D("547.84"), D("0"), D("1.62"))


@pytest.mark.mongo
def test_vat_a_person_enters_on_a_held_row_books_it_and_reclaims_the_vat_until_they_take_it_back(store, acme):
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("547.84"), account_code="7502", description="Phones",
                              not_vat_invoice=True))
    rid = first_row_id(store, acme)

    def books_now():
        [phones] = books.ledger(store, acme, YEAR_1).transactions
        tb = books.trial_balance(store, acme, YEAR_1)
        return phones, (net(tb, "9998"), net(tb, "7502"), net(tb, "2201"))

    phones, figures = books_now()
    assert figures == (D("0"), D("547.84"), D("0"))             # shows no VAT: booked whole, none to reclaim
    assert [(i.code, i.severity) for i in phones.issues] == [("vat_unclaimed", "info")]
    ledger.change_row(store, acme, rid, RowPatch(vat=D("91.31")))                # the person types the VAT
    phones, figures = books_now()
    assert figures == (D("0"), D("456.53"), D("91.31"))                          # on its account, VAT reclaimed
    assert phones.vat_confirmed and phones.vat_not_reclaimed is None
    assert [i.code for i in phones.issues if i.severity != "info"] == [] and "vat_confirmed" in [i.code for i in phones.issues]
    ledger.change_row(store, acme, rid, RowPatch(vat_confirmed=False))           # Don't reclaim it
    phones, figures = books_now()
    assert figures == (D("547.84"), D("0"), D("0")) and phones.vat_not_reclaimed == D("91.31")
    ledger.change_row(store, acme, rid, RowPatch(vat_confirmed=True))            # Reclaim it
    assert books_now()[1] == (D("0"), D("456.53"), D("91.31"))
    ledger.change_row(store, acme, rid, RowPatch(revert=True))                   # as read: nobody vouches for VAT
    phones, figures = books_now()
    assert figures == (D("0"), D("547.84"), D("0")) and not phones.vat_confirmed and phones.vat is None
    with pytest.raises(InvalidInput):                                            # no VAT on the row to reclaim
        ledger.change_row(store, acme, rid, RowPatch(vat_confirmed=True))


@pytest.mark.mongo
def test_a_uk_hotel_stay_is_booked_with_its_vat_until_a_person_says_it_carries_none(store, acme):
    # Booking.com's receipt for a London hotel, £785.60, "not a VAT invoice": a stay in the UK carries 20% VAT, so the
    # books reclaim it at once and ask for the property's VAT invoice (the accountant's ruling, 2026-11-18).
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("785.60"), account_code="7402", not_vat_invoice=True,
                              description="Booking.com - hotel stay at Bermonds Locke, Tower Bridge"))
    rid = first_row_id(store, acme)

    def books_now():
        [stay] = books.ledger(store, acme, YEAR_1).transactions
        tb = books.trial_balance(store, acme, YEAR_1)
        return stay, (net(tb, "9998"), net(tb, "7402"), net(tb, "2201"))

    stay, figures = books_now()
    assert figures == (D("0"), D("654.67"), D("130.93")) and stay.vat_not_reclaimed is None
    assert [(i.code, i.severity) for i in stay.issues] == [("hotel_vat", "warning")]
    ledger.change_row(store, acme, rid, RowPatch(vat=D("0.00")))                 # No VAT on it
    stay, figures = books_now()
    assert figures == (D("0"), D("785.60"), D("0")) and "hotel_vat" not in [i.code for i in stay.issues]


def test_a_years_figures_are_worked_out_from_one_read_of_the_client(store, acme, monkeypatch):
    # Each read is a round trip to the database, which may be far away: the ledger, the trial balance and the rest
    # each make one, where they made four.
    from pymongo.collection import Collection
    add_rows(store, acme, row(date=date(2025, 6, 1), gross=D("60.00"), account_code="7504"), year_start=YEAR_1)
    reads = []
    for name in ("find", "aggregate"):
        real = getattr(Collection, name)
        monkeypatch.setattr(Collection, name,
                            lambda self, *a, _real=real, _name=name, **k: reads.append(_name) or _real(self, *a, **k))
    for work in (books.ledger, books.trial_balance, books.summary, books.invoices, books.bank_checks):
        reads.clear()
        work(store, acme, YEAR_1)
        assert reads == ["find"], work.__name__
    reads.clear()
    books.years_of(store, acme, date(2025, 6, 1))
    assert reads == ["find"]


def test_vat_a_rule_keeps_in_the_cost_is_not_in_box_7(store, acme):
    # The test books' EC-0330: a £190.75 client dinner (VAT £31.79, not reclaimable) put £190.75 in box 7; box 7 is
    # purchases excluding VAT, reclaimable or not, so £158.96. A car lease's blocked half is VAT too.
    add_rows(store, acme, row(date=date(2025, 6, 10), gross=D("190.75"), vat=D("31.79"), account_code="7403",
                              document_type="invoice", counterparty="Harbour Kitchen", description="Client dinner"),
             row(date=date(2025, 6, 12), gross=D("504.00"), vat=D("84.00"), account_code="7304",
                 document_type="invoice", counterparty="Avon Vehicle Leasing", description="Car lease"))
    v = books.vat_figures(store, acme, date(2025, 4, 1), date(2025, 6, 1), date(2025, 6, 30))
    assert (v.box4, v.box7) == (D("42.00"), D("158.96") + D("420.00"))


# ─── A VAT quarter across the year end ────────────────────────────────────────

def sale(day, gross="1200.00", vat="200.00"):
    return row(date=day, direction="in", gross=D(gross), vat=D(vat), account_code="4000", document_type="invoice",
               counterparty="Brightline Print Ltd", description="Design work", document_ref=f"s-{day}")


def test_a_vat_quarter_across_the_year_end_adds_up_both_years(store, acme):
    # The test books' agency year: its VAT quarters run March to May, and a quarter crossing the year end was
    # refused ("Choose a period inside this year"), so March to May had no figures at all.
    add_rows(store, acme, sale(date(2026, 3, 20)), sale(date(2026, 4, 15), "600.00", "100.00"))
    v = books.vat_figures(store, acme, date(2025, 4, 1), date(2026, 3, 1), date(2026, 5, 31))
    assert (v.start, v.end, v.box1, v.box6) == (date(2026, 3, 1), date(2026, 5, 31), D("300.00"), D("1500.00"))


def test_a_vat_quarter_starting_before_the_books_says_what_it_leaves_out(store, acme):
    add_rows(store, acme, sale(date(2025, 4, 15)))
    v = books.vat_figures(store, acme, date(2025, 4, 1), date(2025, 3, 1), date(2025, 5, 31))
    assert v.box1 == D("200.00")
    assert any("1 Mar 2025 to 31 Mar 2025 is before these books start" in note for note in v.notes)


def test_the_vat_before_the_books_start_comes_from_the_opening_vat_balances(store, acme):
    # The agency's March to May 2023: March is before its books, but the VAT booked for it and not yet returned is in
    # the opening balances on Sales VAT and Purchase VAT (£10,560 and £1,980 there).
    books.set_opening(store, acme, OpeningBalances(lines=[
        OpeningLine(code="1200", debit=D("10000.00")), OpeningLine(code="2201", debit=D("300.00")),
        OpeningLine(code="2200", credit=D("1000.00")), OpeningLine(code="3200", credit=D("9300.00"))]))
    add_rows(store, acme, sale(date(2025, 4, 15)))
    v = books.vat_figures(store, acme, date(2025, 4, 1), date(2025, 3, 1), date(2025, 5, 31))
    assert (v.box1, v.box4, v.box5) == (D("1200.00"), D("300.00"), D("900.00"))
    assert any("opening balances" in note and "boxes 6 and 7" in note for note in v.notes)
