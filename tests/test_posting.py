import datetime as dt
import random

import pytest

from ledgersync import accounts
from ledgersync.checks import normalise
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
    with pytest.raises(InvalidTransactions, match="#2") as info:
        trial_balance([tx("out", "10.00", "7502"), tx("out", "10.00", "9999")], REGISTERED)
    assert "#2: This account isn't in the chart." in info.value.message   # the row, not the code


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
    bills = [tx("out", "500.00", "7100", document_type="invoice", counterparty="Landmark Properties",
                document_ref=ref) for ref in ("a", "b")]
    with pytest.raises(InvalidTransactions, match="Choose one"):
        trial_balance([*bills, bank_line("500.00", "LANDMARK PROPERTIES", 5)], REGISTERED)


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


def test_a_claim_and_its_receipts_owe_the_claimant_once_with_the_receipts_vat():
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
        ("2110", "0.00", "240.65"), ("7400", "60.90", "0.00"), ("7402", "173.75", "0.00"), ("2201", "6.00", "0.00")]



def test_trial_balance_financial_summaries():
    sale = Transaction(direction="in", gross="1200.00", vat="200.00", account_code="4000", counterparty="Acme Corp",
                       description="Consultancy", date=dt.date(2026, 9, 14), document_type="invoice")
    expense = Transaction(direction="out", gross="300.00", vat="50.00", account_code="7500", counterparty="Software Co",
                          description="SaaS Subscription", date=dt.date(2026, 9, 14), document_type="receipt")
    tb = trial_balance([sale, expense], REGISTERED)
    assert str(tb.total_income) == "1000.00"
    assert str(tb.total_expenses) == "250.00"
    assert str(tb.net_profit) == "750.00"
