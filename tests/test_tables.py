"""Bank, card and payment processor exports read in code (design of 2026-11-23)."""
import datetime as dt
from decimal import Decimal

from ledgersync.tables import parse, parse_amount, parse_date

HSBC = "Date,Type,Description,Amount,Balance\n28 Apr 2023,BP,LEAH MORGAN SALARY,-3149.87,8263.46\n"
AMEX_HEADER = ("Date,Description,Amount,Extended Details,Appears On Your Statement As,Address,Town/City,Postcode,"
               "Country,Reference,Category")
STRIPE_HEADER = ("automatic_payout_id,automatic_payout_effective_at,balance_transaction_id,created_utc,currency,"
                 "gross,fee,net,reporting_category,description,customer_name")


def test_the_test_books_hsbc_export():
    table = parse(HSBC)
    assert table.roles == {"date": [0], "type": [1], "description": [2], "amount": [3], "balance": [4]}
    assert table.rows == [["28 Apr 2023", "BP", "LEAH MORGAN SALARY", "-3149.87", "8263.46"]]


def test_a_heading_block_and_a_totals_row():
    text = ("Account: Business current\nSort code 40-11-22\n\nDate,Details,Paid out,Paid in,Balance\n"
            "03/04/2023,RENT,120.00,,880.00\n05/04/2023,CLIENT,,500.00,1380.00\n,Total,120.00,500.00,\n")
    table = parse(text)
    assert table.heading == ["Account: Business current", "Sort code 40-11-22"]
    assert len(table.rows) == 2 and table.roles["paid_out"] == [2] and table.roles["paid_in"] == [3]


def test_amounts_as_banks_write_them():
    assert [parse_amount(a) for a in ("£1,234.56", "(12.00)", "12.00 CR", "12.00 DR", "-5", "abc", "")] == [
        Decimal("1234.56"), Decimal("-12.00"), Decimal("12.00"), Decimal("-12.00"), Decimal("-5"), None, None]


def test_dates_are_read_day_first_with_one_format_a_column():
    assert parse_date(["09/04/2023", "11/04/2023"]) == [dt.date(2023, 4, 9), dt.date(2023, 4, 11)]
    assert parse_date(["2023-04-04 12:00:00"]) == [dt.date(2023, 4, 4)]
    assert parse_date(["28 Apr 2023"]) == [dt.date(2023, 4, 28)]
    assert parse_date(["3 April 2023"]) == [dt.date(2023, 4, 3)]
    assert parse_date(["04/13/2023"]) is None                 # month first: not a UK export, the model reads it
    assert parse_date(["09/04/2023", "2023-04-11"]) is None   # one format a column


def test_a_table_without_dates_or_amounts_is_not_recognised():
    assert parse("Name,Notes\nA,B\n") is None
    assert parse("Date,Description,Amount\nyesterday,TESCO,4.50\n") is None
    assert parse("Date,Description,Amount\n09/04/2023,TESCO,four pounds\n") is None


def test_the_amex_and_stripe_headings():
    amex = parse(AMEX_HEADER + "\n09/04/2023,STREAMFLIX.COM,10.99,,STREAMFLIX.COM,,,,,'AMEX2023040004',\n")
    assert (amex.roles["description"], amex.roles["amount"], amex.roles["date"]) == ([1, 9], [2], [0])
    stripe = parse(STRIPE_HEADER + "\n,,txn_1,2023-04-04 12:00:00,gbp,720.00,11.00,709.00,charge,Retainer,Moss\n")
    roles = stripe.roles
    assert (roles["date"], roles["gross"], roles["fee"], roles["net"], roles["category"], roles["description"],
            roles["id"]) == ([3], [5], [6], [7], [8], [9], [2])


# ─── Direction and balances ───────────────────────────────────────────────────

from ledgersync.tables import account_kind, statement  # noqa: E402


def lines_of(text, kind="current"):
    return statement(parse(text), kind)


def test_paid_in_and_paid_out_columns_say_the_direction():
    s = lines_of("Date,Details,Paid out,Paid in\n03/04/2023,RENT,120.00,\n05/04/2023,CLIENT,,500.00\n", None)
    assert [(l.direction, l.amount, l.text) for l in s.lines] == [("out", Decimal("120.00"), "RENT"),
                                                                  ("in", Decimal("500.00"), "CLIENT")]


def test_one_amount_column_is_money_in_when_positive_on_a_bank_account():
    s = lines_of(HSBC)
    [line] = s.lines
    assert (line.direction, line.amount, line.balance, line.kind, line.date) == (
        "out", Decimal("3149.87"), Decimal("8263.46"), "BP", dt.date(2023, 4, 28))
    assert lines_of("Date,Description,Amount\n09/04/2023,CLIENT,500.00\n").lines[0].direction == "in"


def test_a_card_export_takes_positive_as_spending():
    s = lines_of(AMEX_HEADER + "\n09/04/2023,STREAMFLIX.COM,10.99,,,,,,,'A1',\n"
                               "20/04/2023,PAYMENT RECEIVED - THANK YOU,-250.00,,,,,,,'A2',\n", "credit_card")
    assert [(l.direction, l.amount) for l in s.lines] == [("out", Decimal("10.99")), ("in", Decimal("250.00"))]
    assert s.lines[0].text == "STREAMFLIX.COM 'A1'"


def test_the_balance_chain_settles_the_sign_when_the_account_is_unknown():
    # Amounts written as debits: the balance falls by each positive amount, so each is money out.
    s = lines_of("Date,Description,Amount,Balance\n03/04/2023,RENT,120.00,880.00\n05/04/2023,FEE,5.00,875.00\n",
                 None)
    assert [l.direction for l in s.lines] == ["out", "out"] and (s.opening_balance, s.closing_balance) == (
        Decimal("1000.00"), Decimal("875.00"))


def test_without_a_balance_an_unknown_account_is_not_recognised():
    assert lines_of("Date,Description,Amount\n09/04/2023,CLIENT,500.00\n", None) is None


def test_a_newest_first_export_has_its_balances_the_right_way_round():
    s = lines_of("Date,Description,Amount,Balance\n28/04/2023,A,-200.00,1000.00\n21/04/2023,B,-300.00,1200.00\n"
                 "14/04/2023,C,100.00,1500.00\n")
    assert (s.opening_balance, s.closing_balance) == (Decimal("1400.00"), Decimal("1000.00"))
    assert [l.text for l in s.lines] == ["A", "B", "C"]   # in file order


def test_a_chain_that_holds_neither_way_is_not_recognised():
    assert lines_of("Date,Description,Amount,Balance\n03/04/2023,A,-120.00,880.00\n05/04/2023,B,-5.00,900.00\n"
                    ) is None


def test_a_balance_brought_forward_line_is_the_opening_balance_not_a_line():
    s = lines_of("Date,Description,Amount,Balance\n01/04/2023,BALANCE BROUGHT FORWARD,,1000.00\n"
                 "03/04/2023,RENT,-120.00,880.00\n")
    assert len(s.lines) == 1 and s.opening_balance == Decimal("1000.00")


def test_a_line_in_another_currency_keeps_it():
    s = lines_of("Date,Description,Amount,Currency\n09/04/2023,AWS,-49.00,USD\n10/04/2023,TESCO,-4.50,GBP\n")
    assert [l.currency for l in s.lines] == ["USD", "GBP"]


def test_the_kind_of_an_account():
    assert [account_kind(c) for c in ("1200", "1210", "1240", "1230", "4000", None)] == [
        "current", "savings", "credit_card", "petty_cash", None, None]


def test_a_card_whose_balance_runs_against_its_amounts_opens_at_the_right_balance():
    s = lines_of("Date,Description,Amount,Balance\n09/04/2023,SHOP,10.99,-110.99\n10/04/2023,CAFE,4.01,-115.00\n",
                 "credit_card")
    assert [l.direction for l in s.lines] == ["out", "out"] and s.opening_balance == Decimal("-100.00")


def test_paid_in_and_paid_out_columns_are_never_flipped_by_the_balance():
    assert lines_of("Date,Details,Paid out,Paid in,Balance\n03/04/2023,RENT,120.00,,1120.00\n"
                    "05/04/2023,FEE,5.00,,1125.00\n") is None


# ─── Payment processor exports, in code ───────────────────────────────────────

from ledgersync.tables import processor  # noqa: E402

STRIPE_APRIL = STRIPE_HEADER + """
,,txn_stripe2023040002,2023-04-04 12:00:00,gbp,720.00,11.00,709.00,charge,Moss & Pine Florists retainer Apr 2023,Moss & Pine Florists
po_stripe2023040006,2023-04-04,txn_stripe2023040006,2023-04-04 12:00:00,gbp,-640.00,0.00,-640.00,payout,Payout to Severn Bank,
,,txn_stripe2023040004,2023-04-05 12:00:00,gbp,1080.00,16.40,1063.60,charge,Redcliffe Bakehouse retainer Apr 2023,Redcliffe Bakehouse
,,txn_stripe2023040001,2023-04-06 12:00:00,gbp,540.00,8.30,531.70,charge,Hartley Yoga retainer Apr 2023,Hartley Yoga
,,txn_stripe2023040003,2023-04-07 12:00:00,gbp,900.00,13.70,886.30,charge,Quayside Physio retainer Apr 2023,Quayside Physio
po_stripe2023040010,2023-04-11,txn_stripe2023040010,2023-04-11 12:00:00,gbp,-3190.60,0.00,-3190.60,payout,Payout to Severn Bank,
"""
STRIPE_JANUARY = STRIPE_HEADER + """
,,txn_stripe2024010002,2024-01-05 12:00:00,gbp,720.00,11.00,709.00,charge,Moss & Pine Florists retainer Jan 2024,Moss & Pine Florists
,,txn_stripe2024010004,2024-01-05 12:00:00,gbp,1080.00,16.40,1063.60,charge,Redcliffe Bakehouse retainer Jan 2024,Redcliffe Bakehouse
,,txn_stripe2024010003,2024-01-07 12:00:00,gbp,900.00,13.70,886.30,charge,Quayside Physio retainer Jan 2024,Quayside Physio
po_stripe2024010008,2024-01-09,txn_stripe2024010008,2024-01-09 12:00:00,gbp,-1772.60,0.00,-1772.60,payout,Payout to Severn Bank,
,,txn_stripe2024010001,2024-01-10 12:00:00,gbp,540.00,8.30,531.70,charge,Hartley Yoga retainer Jan 2024,Hartley Yoga
po_stripe2024010010,2024-01-16,txn_stripe2024010010,2024-01-16 12:00:00,gbp,-1418.00,0.00,-1418.00,payout,Payout to Severn Bank,
"""


def test_stripes_export_books_each_charge_and_fee_on_its_own_day():
    result = processor(parse(STRIPE_APRIL), "2023-04-01_stripe-statement_2023-04-30.csv")
    rows = result.data
    assert len(rows) == 8 and {r.document_type for r in rows} == {"agent_statement"} and result.agent == "Stripe"
    sales = [r for r in rows if r.direction == "in"]
    fees = [r for r in rows if r.direction == "out"]
    assert [(r.date, r.amount, r.account) for r in sales] == [
        ("2023-04-04", 720.0, "4000"), ("2023-04-05", 1080.0, "4000"), ("2023-04-06", 540.0, "4000"),
        ("2023-04-07", 900.0, "4000")]
    assert [(r.amount, r.account) for r in fees] == [(11.0, "7901"), (16.4, "7901"), (8.3, "7901"), (13.7, "7901")]
    assert [(r.document_number, r.document_total) for r in sales] == [
        ("txn_stripe2023040002", 709.0), ("txn_stripe2023040004", 1063.6), ("txn_stripe2023040001", 531.7),
        ("txn_stripe2023040003", 886.3)]
    assert [r.document_number for r in fees] == [r.document_number for r in sales]
    assert sales[0].counterparty == "Moss & Pine Florists" and fees[0].counterparty == "Stripe"
    assert "Payout" not in " ".join(r.description for r in rows)


def test_the_january_export_keeps_each_charge_on_its_own_day():
    # The model dated January's charges by their payouts (9 and 16 January) and grouped them wrongly.
    rows = processor(parse(STRIPE_JANUARY), "2024-01-01_stripe-statement_2024-01-31.csv").data
    assert [r.date for r in rows if r.direction == "in"] == ["2024-01-05", "2024-01-05", "2024-01-07", "2024-01-10"]


def test_charges_on_the_same_day_print_the_days_net_as_their_total():
    # The agency run: the app takes a processor's items of one day as one document, and each 5 Jan charge printed
    # only its own net, so the day's items (£1,772.60) "did not match" £709.00 and the review asked about them.
    rows = processor(parse(STRIPE_JANUARY), "2024-01-01_stripe-statement_2024-01-31.csv").data
    assert {r.date: r.document_total for r in rows} == {"2024-01-05": 1772.6, "2024-01-07": 886.3,
                                                        "2024-01-10": 531.7}


def test_a_refund_and_an_unknown_category():
    text = STRIPE_HEADER + """
,,txn_1,2023-04-08 12:00:00,gbp,-720.00,0.00,-720.00,refund,Refund Moss & Pine,Moss & Pine Florists
,,txn_2,2023-04-09 12:00:00,gbp,-15.00,0.00,-15.00,adjustment,Dispute fee,
"""
    result = processor(parse(text), "stripe.csv")
    refund, other = result.data
    assert (refund.direction, refund.amount, refund.account) == ("out", 720.0, "4000")
    assert (other.direction, other.amount, other.account) == ("out", 15.0, "9998")
    assert any("adjustment" in w for w in result.warnings)


def test_the_processor_is_named_from_the_file_or_the_heading_else_generically():
    assert processor(parse(STRIPE_APRIL), "export.csv").agent == "Payment processor"
    assert processor(parse("PayPal business account\n" + STRIPE_APRIL), "export.csv").agent == "PayPal"
    assert processor(parse(HSBC), "stripe.csv") is None   # no gross, fee and net: not a processor's export


def test_a_starling_style_export_with_opening_and_closing_lines():
    # Found by the eval cases: "Opening Balance" and "Closing Balance" lines of 0.00 were taken as payments, so
    # every answer after them went to the wrong line; "Counter Party" and "Balance (GBP)" weren't recognised.
    text = ("Date,Counter Party,Reference,Type,Amount (GBP),Balance (GBP),Spending Category,Notes\n"
            "28/10/2026,Opening Balance,,,0.00,12000.00,,\n"
            "28/10/2026,Elif Demir,Salary October,FASTER PAYMENT,-1750.00,10250.00,GENERAL,\n"
            "30/10/2026,Bank charges,Monthly account fee,FEE,-6.50,10243.50,BILLS_AND_SERVICES,\n"
            "22/11/2026,Closing Balance,,,0.00,10243.50,,\n")
    table = parse(text)
    assert (table.roles["description"], table.roles["balance"]) == ([1, 2], [5])
    s = statement(table, "current")
    assert [(l.text, l.amount) for l in s.lines] == [("Elif Demir Salary October", Decimal("1750.00")),
                                                     ("Bank charges Monthly account fee", Decimal("6.50"))]
    assert (s.opening_balance, s.closing_balance) == (Decimal("12000.00"), Decimal("10243.50"))


# ─── Final review fixes ───────────────────────────────────────────────────────

def test_a_card_export_signed_as_a_bank_writes_it():
    # NatWest-style: spending negative, the balance owed shown negative.
    s = lines_of("Date,Type,Description,Value,Balance\n09/04/2023,PUR,SHOP,-10.99,-110.99\n"
                 "10/04/2023,PUR,CAFE,-4.01,-115.00\n", "credit_card")
    assert [l.direction for l in s.lines] == ["out", "out"]


def test_a_card_export_without_a_balance_and_mostly_negative_is_signed_as_a_bank_writes_it():
    s = lines_of("Date,Description,Amount\n09/04/2023,SHOP,-10.99\n10/04/2023,CAFE,-4.01\n"
                 "20/04/2023,PAYMENT THANK YOU,250.00\n", "credit_card")
    assert [l.direction for l in s.lines] == ["out", "out", "in"]


def test_a_dr_cr_type_column_gives_the_sign():
    s = lines_of("Date,Description,Type,Amount\n03/04/2023,RENT,DR,120.00\n05/04/2023,CLIENT,CR,500.00\n")
    assert [l.direction for l in s.lines] == ["out", "in"]


def test_a_debit_credit_indicator_column_gives_the_sign():
    s = lines_of("Date,Description,Amount,Debit/Credit\n03/04/2023,RENT,120.00,Debit\n05/04/2023,CLIENT,500.00,Credit\n")
    assert [l.direction for l in s.lines] == ["out", "in"]


def test_stripes_balance_history_export_is_a_processors_export():
    text = ("id,Type,Source,Amount,Fee,Net,Currency,Created (UTC),Description\n"
            "txn_1,charge,ch_1,720.00,11.00,709.00,gbp,2023-04-04 12:00,Retainer Apr 2023\n"
            "txn_2,payout,po_1,-709.00,0.00,-709.00,gbp,2023-04-11 12:00,STRIPE PAYOUT\n")
    rows = processor(parse(text), "balance_history.csv").data
    assert [(r.direction, r.amount, r.account) for r in rows] == [("in", 720.0, "4000"), ("out", 11.0, "7901")]


def test_a_paypal_export_books_payments_and_fees_and_leaves_withdrawals_out():
    text = ("Date,Time,TimeZone,Name,Type,Status,Currency,Gross,Fee,Net,Transaction ID\n"
            "04/04/2023,10:00:00,GMT,Moss & Pine,Express Checkout Payment,Completed,GBP,100.00,-3.20,96.80,T1\n"
            "06/04/2023,10:00:00,GMT,,General Withdrawal,Completed,GBP,-96.80,0.00,-96.80,T2\n")
    result = processor(parse(text), "paypal.csv")
    assert [(r.direction, r.amount, r.account) for r in result.data] == [("in", 100.0, "4000"), ("out", 3.2, "7901")]
    assert result.warnings == []


def test_a_heading_in_another_currency_is_not_read_in_code():
    assert parse("Date,Description,Amount (EUR)\n09/04/2023,HOTEL,-120.00\n") is None


def test_same_day_lines_whose_order_the_balance_cannot_settle_are_left_to_the_model():
    assert lines_of("Date,Description,Amount,Balance\n03/04/2023,SO A,-10.00,80.00\n"
                    "03/04/2023,SO B,-10.00,90.00\n") is None


def test_an_undated_line_named_like_a_total_is_not_dropped():
    assert parse("Date,Description,Amount\n09/04/2023,TESCO,-4.50\n,TOTALENERGIES,-60.00\n") is None


def test_an_amount_with_a_decimal_comma_is_not_read():
    assert [parse_amount(a) for a in ("12,5", "1.234,56", "1,234.56", "12,345,678.90")] == [
        None, None, Decimal("1234.56"), Decimal("12345678.90")]


def test_a_statement_with_no_lines_is_read_as_empty():
    # The agency year's savings account: months with no movement export only the heading row. Sent to the model,
    # one ran to its output limit for 16 minutes and failed.
    table = parse("Date,Type,Description,Amount,Balance\n")
    assert table is not None and table.rows == []
    s = statement(table, "savings")
    assert (s.lines, s.opening_balance, s.closing_balance) == ([], None, None)
    brought = statement(parse("Date,Description,Amount,Balance\n01/04/2023,BALANCE BROUGHT FORWARD,,500.00\n"),
                        None)
    assert (brought.lines, brought.opening_balance, brought.closing_balance) == ([], Decimal("500.00"),
                                                                                 Decimal("500.00"))
    assert processor(parse(STRIPE_HEADER + "\n"), "stripe.csv").data == []
