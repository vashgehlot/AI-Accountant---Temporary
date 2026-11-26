import datetime as dt
import random
from decimal import Decimal

import pytest

from helpers import SETTINGS as HELPER_SETTINGS, net, row
from ledgersync import accounts
from ledgersync.checks import normalise
from ledgersync.matching import match
from ledgersync.errors import InvalidTransactions
from ledgersync.models import BusinessSettings, Transaction
from ledgersync.posting import journal_for, trial_balance

REGISTERED = BusinessSettings()


def tx(direction, gross, account, **kw):
    return Transaction(direction=direction, gross=gross, account_code=account, description="t",
                       date=dt.date(2026, 9, 1), **kw)


def lines(t, settings=REGISTERED):
    return [(l.code, str(l.debit), str(l.credit)) for l in journal_for(normalise(t, settings), 0)]


@pytest.mark.parametrize("name, t, expected", [
    ("expense with VAT", tx("out", "120.00", "7502", vat="20.00"),
     [("7502", "100.00", "0.00"), ("2201", "20.00", "0.00"), ("1200", "0.00", "120.00")]),
    ("sale with document VAT", tx("in", "2400.00", "4000", vat="400.00"),
     [("4000", "0.00", "2000.00"), ("2200", "0.00", "400.00"), ("1200", "2400.00", "0.00")]),
    ("supplier refund", tx("in", "89.99", "0030", vat="15.00"),
     [("0030", "0.00", "74.99"), ("2201", "0.00", "15.00"), ("1200", "89.99", "0.00")]),
    ("customer refund", tx("out", "120.00", "4000", vat="20.00"),
     [("4000", "100.00", "0.00"), ("2200", "20.00", "0.00"), ("1200", "0.00", "120.00")]),
    ("HMRC VAT payment", tx("out", "1450.00", "2202"), [("2202", "1450.00", "0.00"), ("1200", "0.00", "1450.00")]),
    ("PAYE and NIC", tx("out", "2140.37", "2210"), [("2210", "2140.37", "0.00"), ("1200", "0.00", "2140.37")]),
    ("drawings", tx("out", "500.00", "3260"), [("3260", "500.00", "0.00"), ("1200", "0.00", "500.00")]),
    ("loan received", tx("in", "10000.00", "2300"), [("2300", "0.00", "10000.00"), ("1200", "10000.00", "0.00")]),
    ("transfer to savings", tx("out", "5000.00", "1210"), [("1210", "5000.00", "0.00"), ("1200", "0.00", "5000.00")]),
    ("mixed-VAT receipt", tx("out", "7.95", "8205", vat="0.70"),
     [("8205", "7.25", "0.00"), ("2201", "0.70", "0.00"), ("1200", "0.00", "7.95")]),
])
def test_postings(name, t, expected):
    assert lines(t) == expected


def test_not_vat_registered_posts_the_gross():
    assert lines(tx("out", "120.00", "7502"), BusinessSettings(vat_registered=False)) == [
        ("7502", "120.00", "0.00"), ("1200", "0.00", "120.00")]


def test_trial_balance_shows_net_balances_by_code():
    tb = trial_balance([tx("out", "120.00", "7502", vat="20.00"), tx("in", "2400.00", "4000", vat="400.00")], REGISTERED)
    assert [(l.code, l.name, str(l.debit), str(l.credit)) for l in tb.lines] == [
        ("1200", "Bank Current Account", "2280.00", "0.00"),
        ("4000", "Sales", "0.00", "2000.00"),
        ("7502", "Telephone and Internet", "100.00", "0.00"),
        ("2200", "Sales VAT", "0.00", "400.00"),
        ("2201", "Purchase VAT", "20.00", "0.00"),
    ]
    assert (str(tb.total_debits), str(tb.total_credits), tb.is_balanced) == ("2400.00", "2400.00", True)


def test_vat_comes_last_in_the_trial_balance():
    # Asked for on 2026-10-07: the VAT accounts close the trial balance, after every other account.
    tb = trial_balance([tx("out", "120.00", "7502", vat="20.00"), tx("in", "2400.00", "4000", vat="400.00"),
                        tx("out", "1450.00", "2202"), tx("out", "50.00", "9998")], REGISTERED)
    assert [l.code for l in tb.lines] == ["1200", "4000", "7502", "9998", "2200", "2201", "2202"]


def test_cancelling_transactions_leave_no_zero_lines():
    tb = trial_balance([tx("out", "120.00", "7502", vat="20.00"), tx("in", "120.00", "7502", vat="20.00")], REGISTERED)
    assert tb.lines == [] and tb.is_balanced and len(tb.journal) == 6


def test_unknown_account_blocks_the_trial_balance():
    with pytest.raises(InvalidTransactions, match="isn't in the chart") as info:
        trial_balance([tx("out", "10.00", "7502"), tx("out", "10.00", "9999")], REGISTERED)
    # the row is named by what it is, its date and amount, so a person can find it
    assert "t (1 Sep 2026, £10.00): This account isn't in the chart." in info.value.message


def test_trial_balance_always_balances_for_random_ledgers():
    rng = random.Random(3)
    codes = [a.code for a in accounts.CHART if a.code != accounts.BANK]
    ledger = []
    for n in range(1000):
        gross = f"{rng.randrange(1, 10**6) / 100:.2f}"
        extra = {"vat": f"{float(gross) * rng.choice([0, 0.05, 0.1, 0.16]):.2f}"} if n % 4 == 0 else {}
        ledger.append(tx(rng.choice(["in", "out"]), gross, rng.choice(codes), **extra))
    tb = trial_balance(ledger, REGISTERED)
    assert tb.is_balanced and tb.total_debits == tb.total_credits
    for n in range(len(ledger)):
        mine = [l for l in tb.journal if l.transaction == n]
        assert sum(l.debit for l in mine) == sum(l.credit for l in mine)


def test_a_bill_received_is_owed_to_the_supplier_not_paid_from_the_bank():
    rent = tx("out", "12000.00", "7100", vat="2000.00", document_type="invoice")
    assert lines(rent) == [("7100", "10000.00", "0.00"), ("2201", "2000.00", "0.00"), ("2100", "0.00", "12000.00")]


def test_a_claim_is_owed_to_the_employee():
    assert lines(tx("out", "173.75", "7402", vat="28.96", document_type="expense_claim")) == [
        ("7402", "144.79", "0.00"), ("2201", "28.96", "0.00"), ("2110", "0.00", "173.75")]


def test_documents_that_are_not_transactions_stay_out_until_included():
    assert trial_balance([tx("out", "360.00", "0030", vat="60.00", document_type="pro_forma")], REGISTERED).lines == []
    included = trial_balance([tx("out", "360.00", "0030", vat="60.00", document_type="pro_forma", include=True)],
                             REGISTERED)
    assert [(l.code, str(l.debit), str(l.credit)) for l in included.lines] == [
        ("0030", "300.00", "0.00"), ("2100", "0.00", "360.00"), ("2201", "60.00", "0.00")]


def test_errors_on_a_row_that_is_not_booked_do_not_block_the_trial_balance():
    assert trial_balance([tx("out", "10.00", "9999", document_type="quote")], REGISTERED).lines == []


def bank_line(gross, who, day, **kw):
    return Transaction(direction="out", gross=gross, account_code="7100", description=who, counterparty=who,
                       date=dt.date(2026, 9, day), document_type="statement", document_ref=f"line-{day}", **kw)


def test_a_bank_line_that_pays_a_bill_clears_creditors_and_counts_the_rent_once():
    rent = tx("out", "12000.00", "7100", vat="2000.00", document_type="invoice",
              counterparty="Business Cube Management Solutions", document_ref="bill")
    tb = trial_balance([rent, bank_line("12000.00", "BUSINESS CUBE MGMT", 3)], REGISTERED)
    assert [(l.code, str(l.debit), str(l.credit)) for l in tb.lines] == [
        ("1200", "0.00", "12000.00"), ("7100", "10000.00", "0.00"), ("2201", "2000.00", "0.00")]


def test_a_payment_waiting_for_a_choice_blocks_the_trial_balance():
    # Part of one of two bills: which one is for a person (two of the same amount pay the oldest).
    bills = [tx("out", gross, "7100", document_type="invoice", counterparty="Landmark Properties",
                document_ref=ref) for ref, gross in (("a", "500.00"), ("b", "450.00"))]
    with pytest.raises(InvalidTransactions, match="Choose one"):
        trial_balance([*bills, bank_line("300.00", "LANDMARK PROPERTIES", 5)], REGISTERED)


def test_a_reminder_of_an_unpaid_bill_is_owed_once():
    # The reminder repeats the bill's number; booked again, the rent and Creditors were both counted twice.
    bill, reminder = (tx("out", "610.63", "7100", document_type="invoice", counterparty="HML PM Ltd",
                         document_number="SC-2026-00718", document_ref=ref).model_copy(update={"date": day})
                      for ref, day in (("bill", dt.date(2026, 3, 25)), ("reminder", dt.date(2026, 4, 15))))
    tb = trial_balance([bill, reminder], BusinessSettings(vat_registered=False))
    assert [(l.code, str(l.debit), str(l.credit)) for l in tb.lines] == [("2100", "0.00", "610.63"),
                                                                        ("7100", "610.63", "0.00")]


def test_a_letting_agents_statement_books_the_rent_gross_and_its_costs_once():
    # May's rent came as £526.75 after the agent's fees and a £280 boiler repair. The statement was read as a bank
    # statement, so the rent was counted twice (£925 and £526.75) and the bank was £526.75 too high.
    def item(direction, gross, account, who):
        return Transaction(direction=direction, gross=gross, account_code=account, description=who, counterparty=who,
                           date=dt.date(2025, 5, 9), document_type="agent_statement", agent="R+R PR Ltd",
                           document_ref="statement")
    boiler = Transaction(direction="out", gross="280.00", account_code="7800", description="Boiler repair",
                         counterparty="Parkside Heating & Plumbing", date=dt.date(2025, 5, 8), document_type="invoice",
                         document_ref="boiler")
    paid_over = Transaction(direction="in", gross="526.75", account_code="4904", description="R+R PR LTD",
                            counterparty="R+R PR LTD", date=dt.date(2025, 5, 13), document_type="statement",
                            document_ref="line")
    rows = [boiler, item("in", "925.00", "4904", "22 Telecom Ltd"), item("out", "111.00", "7603", "R+R PR Ltd"),
            item("out", "7.25", "7901", "R+R PR Ltd"), item("out", "280.00", "7800", "Parkside Heating & Plumbing"),
            paid_over]
    tb = trial_balance(rows, BusinessSettings(vat_registered=False))
    assert [(l.code, str(l.debit), str(l.credit)) for l in tb.lines] == [
        ("1200", "526.75", "0.00"), ("4904", "0.00", "925.00"), ("7603", "111.00", "0.00"),
        ("7800", "280.00", "0.00"), ("7901", "7.25", "0.00")]


def test_a_receipt_and_its_card_payment_post_once_with_the_receipts_vat():
    meal = Transaction(direction="out", gross="21.35", vat="3.56", account_code="7406", description="McDonald's",
                       counterparty="McDonald's", date=dt.date(2026, 2, 22), document_type="receipt", document_ref="r")
    card = Transaction(direction="out", gross="21.35", account_code="7406", description="MCDONALDS",
                       counterparty="MCDONALDS", date=dt.date(2026, 2, 23), document_type="statement",
                       document_ref="line")
    tb = trial_balance([meal, card], REGISTERED)
    assert [(l.code, str(l.debit), str(l.credit)) for l in tb.lines] == [
        ("1200", "0.00", "21.35"), ("7406", "17.79", "0.00"), ("2201", "3.56", "0.00")]


def test_a_claim_and_its_receipts_owe_the_claimant_once_with_the_vat_the_receipt_or_the_claim_shows():
    def line(gross, account, merchant, vat=None):
        return Transaction(direction="out", gross=gross, vat=vat, account_code=account, counterparty="Jenny Hogg",
                           description=f"Jenny Hogg - {merchant}", date=dt.date(2026, 9, 14),
                           document_type="expense_claim", document_ref="claim")
    def receipt(gross, account, shop, vat=None):
        return Transaction(direction="out", gross=gross, vat=vat, account_code=account, counterparty=shop,
                           description=shop, date=dt.date(2026, 9, 14), document_type="receipt", document_ref=shop)
    rows = [line("36.00", "7400", "Southgate Bath Car Park", vat="6.00"),
            line("173.75", "7402", "Clayton Hotel Manchester", vat="28.96"), line("30.90", "7400", "Transport for London"),
            receipt("36.00", "7400", "Southgate Bath Car Park", vat="6.00"),
            receipt("173.75", "7402", "Clayton Hotel Manchester City Centre")]
    tb = trial_balance(rows, REGISTERED)
    assert [(l.code, str(l.debit), str(l.credit)) for l in tb.lines] == [
        ("2110", "0.00", "240.65"), ("7400", "60.90", "0.00"), ("7402", "144.79", "0.00"), ("2201", "34.96", "0.00")]
    # (the hotel receipt shows no VAT, so the £28.96 the claim shows is booked, and a VAT invoice asked for)



def test_trial_balance_financial_summaries():
    sale = Transaction(direction="in", gross="1200.00", vat="200.00", account_code="4000", counterparty="Acme Corp",
                       description="Consultancy", date=dt.date(2026, 9, 14), document_type="invoice")
    expense = Transaction(direction="out", gross="300.00", vat="50.00", account_code="7500", counterparty="Software Co",
                          description="SaaS Subscription", date=dt.date(2026, 9, 14), document_type="receipt")
    tb = trial_balance([sale, expense], REGISTERED)
    assert str(tb.total_income) == "1000.00"
    assert str(tb.total_expenses) == "250.00"
    assert str(tb.net_profit) == "750.00"


def receipt_and_card_line():
    """A receipt and the bank line that pays it: the same shop, amount and day."""
    return [Transaction(direction="out", gross="36.00", account_code="7400", description="Parking",
                        counterparty="Southgate Bath Car Park", date=dt.date(2026, 9, 9), document_type="receipt",
                        document_ref="photo"),
            Transaction(direction="out", gross="36.00", account_code="7400", description="SOUTHGATE BATH",
                        counterparty="SOUTHGATE BATH CAR PARK", date=dt.date(2026, 9, 9), document_type="statement",
                        document_ref="card")]


def test_without_decisions_the_trial_balance_is_worked_out_as_it_always_was():
    # Pasted or unsaved rows have no decisions: the same result as no decisions at all, said either way.
    rows = receipt_and_card_line()
    plain = trial_balance(rows, REGISTERED)
    assert plain == trial_balance(rows, REGISTERED, read=None, apart=None)
    assert plain == trial_balance(rows, REGISTERED, read=[None, None], apart=[set(), set()])
    assert [(l.code, str(l.debit), str(l.credit)) for l in plain.lines] == [
        ("1200", "0.00", "36.00"), ("7400", "36.00", "0.00")]   # the receipt, once
    assert [l.transaction for l in plain.journal] == [0, 0]


def test_rows_said_not_to_be_the_same_are_both_posted():
    # Passed on to the match: the bank line is not the receipt's payment, so its money is posted too.
    balance = trial_balance(receipt_and_card_line(), REGISTERED, apart=[{1}, {0}])
    assert [(l.code, str(l.debit), str(l.credit)) for l in balance.lines] == [
        ("1200", "0.00", "72.00"), ("7400", "72.00", "0.00")]
    assert {l.transaction for l in balance.journal} == {0, 1}


def test_an_exact_payment_clears_an_invoice_paid_45_days_later():
    invoice = row(date=dt.date(2026, 1, 10), counterparty="Smith Solicitors Ltd", gross=Decimal("1200.00"),
                  vat=Decimal("200.00"), document_type="invoice", document_ref="d1")
    paid = row(date=dt.date(2026, 2, 24), counterparty="Smith Solicitors", gross=Decimal("1200.00"),
               document_type="statement", document_ref="b1")
    tb = trial_balance([invoice, paid], HELPER_SETTINGS)
    assert net(tb, "7600") == Decimal("1000.00") and net(tb, "2100") == 0


def _amazon_invoice_receipt_and_card_line(invoice_date):
    invoice = row(date=invoice_date, counterparty="Amazon", gross=Decimal("500.00"), document_type="invoice",
                  document_ref="inv")
    receipt = row(date=dt.date(2026, 3, 1), counterparty="Amazon", gross=Decimal("30.00"), document_ref="rcpt")
    card = row(date=dt.date(2026, 3, 2), counterparty="AMAZON", gross=Decimal("30.00"), document_type="statement",
               document_ref="card")
    rows = [invoice, receipt, card]
    matched_card = match([normalise(t, HELPER_SETTINGS) for t in rows], HELPER_SETTINGS)[2]
    return trial_balance(rows, HELPER_SETTINGS), matched_card


def test_a_card_payment_pairs_with_its_receipt_despite_an_old_open_invoice_from_the_shop():
    tb, card = _amazon_invoice_receipt_and_card_line(dt.date(2025, 9, 10))
    assert net(tb, "7600") == Decimal("530.00") and net(tb, "2100") == Decimal("-500.00")   # the invoice, the receipt
    assert card.recorded_by is not None and card.recorded_by.ref == "rcpt"
    assert not [i for i in card.issues if i.code == "open_document"]


def test_a_card_payment_pairs_with_its_receipt_rather_than_part_paying_a_recent_invoice():
    tb, card = _amazon_invoice_receipt_and_card_line(dt.date(2026, 2, 1))
    assert net(tb, "7600") == Decimal("530.00") and net(tb, "2100") == Decimal("-500.00")
    assert card.recorded_by is not None and card.recorded_by.ref == "rcpt" and not card.pays
    assert not [i for i in card.issues if i.code in ("part_payment", "open_document")]


def test_net_pay_and_paye_from_the_report_and_the_bank_book_wages_in_full():
    pay = dict(date=dt.date(2026, 3, 28), document_type="payroll", document_ref="p1")
    report = [row(**pay, gross=Decimal("3000.00"), account_code="7000", owed_to="net_pay"),
              row(**pay, gross=Decimal("1000.00"), account_code="7000", owed_to="paye_ni"),
              row(**pay, gross=Decimal("100.00"), account_code="7006", owed_to="paye_ni")]
    bank = [row(date=dt.date(2026, 3, 28), gross=Decimal("3000.00"), account_code="2220", document_type="statement"),
            row(date=dt.date(2026, 4, 19), gross=Decimal("1100.00"), account_code="2210", document_type="statement")]
    tb = trial_balance(report + bank, HELPER_SETTINGS)
    assert net(tb, "7000") == Decimal("4000.00") and net(tb, "7006") == Decimal("100.00")
    assert net(tb, "2220") == net(tb, "2210") == 0 and net(tb, "1200") == Decimal("-4100.00")


# ─── CIS: tax a contractor takes off an invoice and pays to HMRC ──────────────

def test_a_sale_with_cis_taken_off_books_the_whole_sale_and_the_tax_withheld():
    # Ashdown's invoice AJ-2041: £4,000 of work (reverse charge, no VAT), CIS 20% on the £3,000 labour, £3,400 due.
    # It was booked as a £3,400 sale, and the £600 the customer paid to HMRC vanished.
    sale = tx("in", "3400.00", "4000", document_type="invoice", cis_deducted="600.00")
    assert lines(sale) == [("4000", "0.00", "4000.00"), ("1104", "600.00", "0.00"), ("1100", "3400.00", "0.00")]


def test_a_subcontractors_invoice_with_cis_taken_off_owes_the_tax_to_hmrc():
    bill = tx("out", "800.00", "7602", document_type="invoice", cis_deducted="200.00")
    assert lines(bill) == [("7602", "1000.00", "0.00"), ("2215", "0.00", "200.00"), ("2100", "0.00", "800.00")]


def test_a_cis_sale_paid_in_full_leaves_nothing_owed_and_the_tax_withheld_as_an_asset():
    sale = tx("in", "3400.00", "4000", document_type="invoice", cis_deducted="600.00", counterparty="Fenwick Builders Ltd",
              document_number="AJ-2041", document_ref="aj")
    paid = Transaction(direction="in", gross="3400.00", account_code="4000", description="t",
                       document_type="statement", counterparty="Fenwick Builders Ltd", date=dt.date(2026, 10, 2))
    tb = trial_balance([sale, paid], REGISTERED)
    assert (net(tb, "4000"), net(tb, "1104"), net(tb, "1100"), net(tb, "1200")) == (
        Decimal("-4000.00"), Decimal("600.00"), 0, Decimal("3400.00"))
    assert tb.is_balanced


def test_a_cis_sale_says_where_the_tax_went():
    sale = normalise(tx("in", "3400.00", "4000", document_type="invoice", cis_deducted="600.00"), REGISTERED)
    assert [(i.code, i.severity, i.message) for i in sale.issues] == [
        ("cis_deducted", "info", "CIS £600.00 taken off by the customer: booked to CIS Deducted, so the sale is "
                                 "£4,000.00.")]
    assert sale.net == Decimal("4000.00")


def test_money_held_in_suspense_is_not_counted_as_a_liability():
    # Kestrel's £6,721.48 held in Suspense made total liabilities read -£4,590.80.
    tb = trial_balance([tx("out", "240.00", "9998"), tx("in", "1000.00", "2300")], REGISTERED)
    assert (tb.total_assets, tb.total_liabilities) == (Decimal("1000.00"), Decimal("1000.00"))   # 760 bank + 240 held


def test_a_journal_debits_one_account_and_credits_another_with_no_vat_and_no_document():
    from ledgersync.evidence_rules import document_rule
    from ledgersync.checks import normalise as check
    # Depreciation for the year: Dr 8000 Depreciation, Cr 0031 Office Equipment Depreciation. Nothing touches the bank.
    entry = tx("out", "525.00", "8000", document_type="journal", contra_account_code="0031")
    ready = check(entry, REGISTERED)
    assert (ready.contra_account_code, ready.vat_posted, ready.issues) == ("0031", Decimal("0.00"), [])
    assert document_rule(ready, REGISTERED).action == "book"   # over £250, and still not held for an invoice
    tb = trial_balance([entry], REGISTERED)
    assert {(l.code, l.debit, l.credit) for l in tb.lines} == {("8000", Decimal("525.00"), Decimal("0.00")),
                                                              ("0031", Decimal("0.00"), Decimal("525.00"))}
    # An accrual credits Accruals, which the rules otherwise work out afresh: a journal's accounts are kept.
    accrual = check(tx("out", "300.00", "7601", document_type="journal", contra_account_code="2109"), REGISTERED)
    assert accrual.contra_account_code == "2109"


# ─── Bad debts (design of 2026-11-24) ─────────────────────────────────────────

def test_a_write_off_books_the_bad_debt_and_its_vat_relief_against_debtors():
    # The test books' agency year: Lowther Interiors Ltd's £4,800 (VAT £800), written off on 31 January 2024.
    off = tx("out", "4800.00", "8100", vat="800.00", document_type="write_off", writes_off="inv")
    assert lines(off) == [("8100", "4000.00", "0.00"), ("2201", "800.00", "0.00"), ("1100", "0.00", "4800.00")]


def test_without_vat_registration_a_write_off_has_no_relief():
    off = tx("out", "4800.00", "8100", vat="800.00", document_type="write_off", writes_off="inv")
    assert lines(off, BusinessSettings(vat_registered=False)) == [("8100", "4800.00", "0.00"), ("1100", "0.00", "4800.00")]


def test_a_recovery_credits_bad_debts_and_sales_vat():
    back = tx("in", "1200.00", "8100", vat="200.00", document_type="statement", recovers="wo")
    assert lines(back) == [("8100", "0.00", "1000.00"), ("2200", "0.00", "200.00"), ("1200", "1200.00", "0.00")]
