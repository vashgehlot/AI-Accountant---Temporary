import datetime as dt
from decimal import Decimal

from ledgersync.models import Transaction
from ledgersync.statements import check_statement


def line(direction, gross, balance=None, opening=None, closing=None, kind="statement"):
    return Transaction(direction=direction, gross=gross, account_code="7502", date=dt.date(2026, 9, 1),
                       description="line", document_type=kind, balance=balance,
                       opening_balance=opening, closing_balance=closing)


def test_a_skipped_line_is_flagged_where_the_balance_breaks():
    # Opening £1,000.00; out £20, out £60, [out £12.40 skipped by the model], in £100; closing £1,007.60.
    both = dict(opening="1000.00", closing="1007.60")
    rows = [line("out", "20.00", "980.00", **both), line("out", "60.00", "920.00", **both),
            line("in", "100.00", "1007.60", **both)]
    checked, summary = check_statement(rows)
    assert (summary.status, summary.difference) == ("gap", Decimal("12.40"))
    assert [[i.code for i in tx.issues] for tx in checked] == [[], [], ["statement_gap", "statement_total"]]
    assert checked[2].issues[0].message == "Balance should be £1,020.00; the statement shows £1,007.60."
    assert checked[2].issues[1].message == "Opening £1,000.00 plus these rows is £1,020.00; the statement closes at £1,007.60."


def test_a_statement_that_adds_up_is_ok():
    both = dict(opening="1000.00", closing="1030.00")
    checked, summary = check_statement([line("in", "100.00", "1100.00", **both), line("out", "70.00", "1030.00", **both)])
    assert (summary.status, summary.difference) == ("ok", None) and [tx.issues for tx in checked] == [[], []]


def test_a_statement_listed_newest_first_adds_up_too():
    rows = [line("in", "100.00", "1007.60"), line("out", "12.40", "907.60"), line("out", "60.00", "920.00"),
            line("out", "20.00", "980.00", opening="1000.00", closing="1007.60")]
    checked, summary = check_statement(rows)
    assert summary.status == "ok" and all(not tx.issues for tx in checked)


def test_a_balance_printed_once_a_day_is_followed_across_the_lines_without_one():
    rows = [line("out", "20.00", "980.00"), line("out", "30.00"), line("out", "50.00", "900.00")]
    assert check_statement(rows)[1].status == "ok"


def test_an_overdrawn_balance_reads_as_a_minus():
    [_, second], summary = check_statement([line("out", "50.00", "-30.00"), line("out", "20.00", "-60.00")])
    assert second.issues[0].message == "Balance should be -£50.00; the statement shows -£60.00."
    assert (summary.status, summary.difference) == ("gap", Decimal("10.00"))


def test_a_statement_without_balances_has_nothing_to_check():
    checked, summary = check_statement([line("out", "20.00"), line("in", "5.00")])
    assert (summary.status, summary.difference) == ("none", None)


def test_only_bank_lines_are_checked_and_an_upload_without_any_has_no_summary():
    receipt = line("out", "20.00", kind="receipt")
    assert check_statement([receipt]) == ([receipt], None)
    checked, summary = check_statement([receipt, line("out", "20.00", "980.00"), line("out", "30.00", "950.00")])
    assert summary.status == "ok" and checked[0] is receipt


def test_checking_again_replaces_the_earlier_warnings():
    once, _ = check_statement([line("out", "20.00", "980.00"), line("out", "30.00", "900.00")])
    twice, _ = check_statement(once)
    assert [len(tx.issues) for tx in twice] == [0, 1]
