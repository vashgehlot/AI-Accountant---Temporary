import datetime as dt
from decimal import Decimal

import pytest

from helpers import payroll_row
from ledgersync.adapter import parse_date, to_transactions
from ledgersync.matching import match
from ledgersync.models import BusinessSettings
from ledgersync.posting import trial_balance

ROW = {"description": "BT Business Broadband", "date": "2026-09-01", "amount": 72.0, "direction": "out",
       "account": "7502 Telephone and Internet", "vat": None, "currency": "GBP"}


def adapt(*rows):
    return to_transactions(list(rows), source="table", settings=BusinessSettings())


def checked(*rows):
    """The rows as the ledger shows them: matching.match checks each document against its printed total."""
    return match(adapt(*rows), BusinessSettings())


def issues_of(t):
    return [(i.code, i.severity) for i in t.issues]


def test_model_rows_become_ledger_transactions():
    [t] = adapt(ROW)
    assert (t.direction.value, t.gross, t.account_code, t.date) == ("out", Decimal("72.00"), "7502", dt.date(2026, 9, 1))
    assert (t.vat_posted, t.source, t.method) == (Decimal("0.00"), "table", "llm")   # no VAT shown, none booked


def test_rows_that_do_not_add_up_to_the_document_total_are_flagged():
    # The note said Breakfast £20 and Travelling charges £50, but "Total £60".
    rows = [dict(ROW, description="Breakfast", amount=20.0, account="7406 Subsistence", document_total=60.0),
            dict(ROW, description="Travelling charges", amount=50.0, account="7400 Travel", document_total=60.0)]
    assert [t.document_total for t in adapt(*rows)] == [Decimal("60.00")] * 2         # each row keeps the total
    first, second = checked(*rows)
    [mismatch] = [i for i in first.issues if i.code == "total_mismatch"]
    assert mismatch.severity == "warning" and "70.00" in mismatch.message and "60.00" in mismatch.message
    assert "total_mismatch" not in [code for code, _ in issues_of(second)]           # said once, on its first row


def test_a_documents_price_before_vat_and_not_a_vat_invoice_are_kept_but_not_on_a_bank_line():
    receipt = dict(ROW, document_type="receipt", amount=17.99, document_total=17.99, document_net=14.99,
                   not_vat_invoice=True)
    [tx] = adapt(receipt)
    assert (tx.document_net, tx.not_vat_invoice) == (Decimal("14.99"), True)
    [line] = adapt(dict(receipt, document_type="statement"))
    assert (line.document_net, line.not_vat_invoice) == (None, False)


def test_rows_that_add_up_to_the_document_total_are_not_flagged():
    rows = [dict(ROW, amount=20.0, document_total=70.0), dict(ROW, amount=50.0, document_total=70.0)]
    assert not [i for t in checked(*rows) for i in t.issues if i.code == "total_mismatch"]


def test_statement_rows_without_a_document_total_are_not_checked():
    assert not [i for t in checked(ROW, dict(ROW, amount=10.0)) for i in t.issues if i.code == "total_mismatch"]


def test_a_split_that_loses_the_printed_vat_is_put_back_together():
    # WHSmith: coffee 3.00 + notebook 9.00, one VAT total of 2.00. The model split it as 11.00 and
    # 1.00 with no VAT: the VAT could not be divided, so the receipt stays one row, as printed.
    doc = {"document_total": 12.0, "document_vat": 2.0, "date": "2026-09-15"}
    rows = [dict(ROW, **doc, description="Whsmith for A4 notebook", amount=11.0, account="7504 Office Stationery"),
            dict(ROW, **doc, description="Whsmith for Coffee to go", amount=1.0, vat=0.0, account="7406 Subsistence")]
    [t] = checked(*rows)
    assert (t.gross, t.vat, t.account_code, t.description) == (
        Decimal("12.00"), Decimal("2.00"), "7504", "Whsmith for A4 notebook")
    assert ("mixed_items", "warning") in issues_of(t) and "total_mismatch" not in [c for c, _ in issues_of(t)]


def test_a_split_by_rate_that_carries_the_printed_vat_is_put_back_together():
    # Sainsbury's: groceries 3.75 (VAT 0.00) and cleaning supplies 4.20 (VAT 0.70). The VAT summary divides by
    # rate, not by account, so the receipt stays one row (mixed_items) for the agent to split.
    doc = {"document_total": 7.95, "document_vat": 0.70}
    rows = [dict(ROW, **doc, amount=3.75, vat=0.0, account="8205 Refreshments"),
            dict(ROW, **doc, amount=4.20, vat=0.70, account="7801 Cleaning")]
    [t] = adapt(*rows)
    assert (t.gross, t.vat, t.account_code) == (Decimal("7.95"), Decimal("0.70"), "7801")
    assert ("mixed_items", "warning") in issues_of(t)


def test_a_receipt_with_two_rates_split_across_accounts_is_one_row_on_the_biggest_vat_part():
    # Bulkbuy: the model divided one rate's VAT across two accounts (3.20 and 4.40, printed nowhere).
    doc = {"document_total": 64.0, "document_vat": 7.60, "date": "2026-10-05"}
    rows = [dict(ROW, **doc, amount=19.20, vat=3.20, account="7801 Cleaning"),
            dict(ROW, **doc, amount=26.40, vat=4.40, account="7504 Office Stationery"),
            dict(ROW, **doc, amount=18.40, vat=0.0, account="8205 Refreshments")]
    [t] = checked(*rows)
    assert (t.gross, t.vat, t.account_code) == (Decimal("64.00"), Decimal("7.60"), "7504")
    [mixed] = [i for i in t.issues if i.code == "mixed_items"]
    assert "VAT £7.60 is on £45.60; £18.40 has none" in mixed.message
    assert "total_mismatch" not in [c for c, _ in issues_of(t)]


@pytest.mark.parametrize("small_first", [True, False])
def test_each_lines_own_rate_decides_whatever_the_order_of_the_lines(small_first):
    # 0.59 of VAT on 3.54 is a rounded 20% (3.54/6 = 0.59, but the line was priced 0.10 on 0.59: a penny of
    # rounding); 200.00 on 1200.00 is 20%. One rate throughout, with VAT per item: it stays split either way.
    doc = {"document_total": 1200.59, "document_vat": 200.10, "date": "2026-10-21"}
    lines = [dict(ROW, **doc, amount=0.59, vat=0.10, account="7504 Office Stationery"),
             dict(ROW, **doc, amount=1200.0, vat=200.0, account="7801 Cleaning")]
    if not small_first:
        lines.reverse()
    assert sorted((t.gross, t.vat, t.account_code) for t in adapt(*lines)) == [
        (Decimal("0.59"), Decimal("0.10"), "7504"), (Decimal("1200.00"), Decimal("200.00"), "7801")]


@pytest.mark.parametrize("standard_first", [True, False])
def test_lines_at_the_standard_and_the_reduced_rate_are_one_row_whatever_the_order(standard_first):
    doc = {"document_total": 126.0, "document_vat": None, "date": "2026-10-21"}
    lines = [dict(ROW, **doc, amount=120.0, vat=20.0, account="7504 Office Stationery"),
             dict(ROW, **doc, amount=6.0, vat=0.29, account="8205 Refreshments")]   # 0.29 is 5% of a 6.00 gross
    if not standard_first:
        lines.reverse()
    [t] = adapt(*lines)
    assert (t.gross, t.vat, t.account_code) == (Decimal("126.00"), Decimal("20.29"), "7504")


def test_parts_that_do_not_add_up_to_the_printed_total_are_not_collapsed():
    # Two separate 5.00 receipts from one shop on one day, one with VAT and one without.
    doc = {"document_total": 5.0, "document_vat": None, "date": "2026-10-21"}
    rows = [dict(ROW, **doc, amount=5.0, vat=0.83, account="7504 Office Stationery"),
            dict(ROW, **doc, amount=5.0, vat=0.0, account="8205 Refreshments")]
    assert [t.gross for t in adapt(*rows)] == [Decimal("5.00"), Decimal("5.00")]


def test_a_receipt_with_a_vat_part_and_a_part_without_is_one_row_even_with_no_document_vat():
    # The reader does not always give document_vat; the parts themselves show VAT on one and none on the other.
    doc = {"document_total": 58.0, "document_vat": None, "date": "2026-10-21"}
    rows = [dict(ROW, **doc, description="Costco", amount=36.0, vat=6.0, account="7504 Office Stationery"),
            dict(ROW, **doc, description="Costco", amount=22.0, vat=0.0, account="8205 Refreshments")]
    [t] = adapt(*rows)
    assert (t.gross, t.vat, t.account_code) == (Decimal("58.00"), Decimal("6.00"), "7504")
    assert ("mixed_items", "warning") in issues_of(t)


def test_a_receipt_with_vat_on_two_accounts_at_different_rates_is_one_row():
    doc = {"document_total": 40.0, "document_vat": None, "date": "2026-10-21"}
    rows = [dict(ROW, **doc, amount=24.0, vat=4.0, account="7504 Office Stationery"),
            dict(ROW, **doc, amount=16.0, vat=0.76, account="8205 Refreshments")]
    [t] = adapt(*rows)
    assert (t.gross, t.vat, t.account_code) == (Decimal("40.00"), Decimal("4.76"), "7504")


def test_a_split_with_per_item_vat_at_one_rate_stays_split():
    # VAT shown per item (20% on each) and adding up to the printed VAT: nothing is guessed, so it stays split.
    doc = {"document_total": 60.0, "document_vat": 10.0, "date": "2026-10-21"}
    rows = [dict(ROW, **doc, amount=24.0, vat=4.0, account="7504 Office Stationery"),
            dict(ROW, **doc, amount=36.0, vat=6.0, account="7801 Cleaning")]
    assert [(t.gross, t.vat, t.account_code) for t in adapt(*rows)] == [
        (Decimal("24.00"), Decimal("4.00"), "7504"), (Decimal("36.00"), Decimal("6.00"), "7801")]


def test_the_lines_of_an_expense_claim_keep_their_own_vat():
    doc = {"document_total": 150.0, "document_type": "expense_claim", "counterparty": "Jenny"}
    rows = [dict(ROW, **doc, amount=120.0, vat=20.0, account="7406 Subsistence", date="2026-10-01"),
            dict(ROW, **doc, amount=30.0, vat=0.0, account="7400 Travel", date="2026-10-02")]
    assert len(adapt(*rows)) == 2


def test_a_split_of_a_document_without_vat_stays_split():
    doc = {"document_total": 50.0, "document_vat": None}
    rows = [dict(ROW, **doc, amount=18.0, account="7406 Subsistence"),
            dict(ROW, **doc, amount=32.0, account="7400 Travel")]
    assert [t.account_code for t in adapt(*rows)] == ["7406", "7400"]


def test_a_receipt_kept_whole_because_of_mixed_items_is_flagged():
    [t] = adapt(dict(ROW, document_total=72.0, mixed_items=True))
    assert ("mixed_items", "warning") in issues_of(t)


def test_vat_printed_on_the_document_is_booked_as_printed():
    [t] = adapt({**ROW, "vat": 10.0})
    assert (t.vat, t.vat_posted, t.net) == (Decimal("10.00"), Decimal("10.00"), Decimal("62.00"))
    assert "vat_estimated" not in [code for code, _ in issues_of(t)]


def test_money_in_stays_money_in():
    [t] = adapt({**ROW, "direction": "in", "account": "4000 Sales"})
    assert (t.direction.value, t.account_code) == ("in", "4000")


def test_negative_amounts_become_money_out():
    # Baseline: bank rows the model kept negative were dropped, so bank exports scored 20%.
    [t] = adapt({**ROW, "amount": -72.0, "direction": "in", "vat": -12.0})
    assert (t.direction.value, t.gross, t.vat) == ("out", Decimal("72.00"), Decimal("12.00"))
    assert "direction_conflict" in [code for code, _ in issues_of(t)]


@pytest.mark.parametrize("account", ["9999 Nonsense", "1200 Bank Current Account", "", None])
def test_accounts_that_cannot_be_posted_to_go_to_suspense(account):
    [t] = adapt({**ROW, "account": account})
    assert t.account_code == "9998" and ("account_not_recognised", "warning") in issues_of(t)
    assert not [i for i in t.issues if i.severity == "error"]


def test_a_suspense_choice_is_flagged_as_an_account_that_is_unclear():
    [t] = adapt({**ROW, "account": "9998 Suspense"})
    assert t.account_code == "9998" and ("account_unclear", "warning") in issues_of(t)
    assert "account_not_recognised" not in [code for code, _ in issues_of(t)]


def test_the_banks_own_code_on_a_statement_line_is_not_recognised_rather_than_unclear():
    [t] = adapt({**ROW, "account": "1200", "document_type": "statement"})
    assert ("account_not_recognised", "warning") in issues_of(t)
    assert "account_unclear" not in [code for code, _ in issues_of(t)]


def test_zero_or_unreadable_amounts_are_skipped():
    assert adapt({**ROW, "amount": 0}, {**ROW, "amount": None}) == []


def test_uk_dates_are_read_day_first():
    assert parse_date("03/09/2026") == dt.date(2026, 9, 3)
    assert parse_date("2026-09-03 00:00:00") == dt.date(2026, 9, 3)
    assert parse_date("sometime") is None


def test_one_absurd_amount_does_not_sink_the_other_rows():
    # A model row of 1e26 used to raise inside to_money and fail the whole analysis job.
    assert [t.gross for t in adapt({**ROW, "amount": 1e26}, ROW)] == [Decimal("72.00")]


def test_negative_vat_printed_on_a_credit_note_is_still_vat():
    # The prompt asks for a positive amount but the VAT "as printed": a refund prints "VAT -2.00".
    [t] = adapt({**ROW, "amount": 12.0, "direction": "in", "vat": -2.0})
    assert (t.vat, t.vat_posted) == (Decimal("2.00"), Decimal("2.00"))
    assert not [i for i in t.issues if i.severity == "error"]
    assert trial_balance([t], BusinessSettings()).is_balanced


def test_rows_carry_the_document_type_and_counterparty():
    [t] = adapt(dict(ROW, document_type="invoice", counterparty=" BT plc "))
    assert (t.document_type, t.counterparty, t.contra_account_code) == ("invoice", "BT plc", "2100")


def test_rows_carry_the_number_printed_on_their_document():
    [bill] = adapt(dict(ROW, document_type="invoice", document_number=" SC-2026-00718 "))
    [line] = adapt(dict(ROW, document_type="statement", document_number="SC-2026-00718"))
    assert (bill.document_number, line.document_number) == ("SC-2026-00718", None)   # a bank line is no document


AGENT = {"document_type": "agent_statement", "date": "2025-05-09"}


def agent_rows(total=526.75):
    # A letting agent's statement: the rent it collected, its fees and a bill it paid, netting to what it paid over.
    items = [dict(ROW, **AGENT, description="Rent", amount=925.0, direction="in", account="4904 Rent Income",
                  counterparty="22 Telecom Ltd"),
             dict(ROW, **AGENT, description="Fees", amount=118.25, account="7603 Professional Fees",
                  counterparty="R+R PR Ltd"),
             dict(ROW, **AGENT, description="Boiler", amount=280.0, account="7800 Repairs and Renewals",
                  counterparty="Parkside Heating & Plumbing")]
    return to_transactions([dict(item, document_total=total) for item in items], source="pdf",
                           settings=BusinessSettings(), agent="R+R PR Ltd")


def test_an_agents_statement_is_one_document_held_by_the_agent():
    rows = agent_rows()
    assert len({t.document_ref for t in rows}) == 1 and {t.agent for t in rows} == {"R+R PR Ltd"}
    assert [(t.account_code, t.contra_account_code) for t in rows] == [("4904", "1100"), ("7603", "1100"),
                                                                       ("7800", "1100")]
    assert "total_mismatch" not in [code for t in match(rows, BusinessSettings()) for code, _ in issues_of(t)]


def test_an_agents_statement_that_does_not_net_to_what_it_paid_over_is_flagged():
    first, *_ = match(agent_rows(total=600.0), BusinessSettings())
    assert ("total_mismatch", "warning") in issues_of(first) and "£526.75" in first.issues[-1].message


def test_an_unexpected_document_type_is_left_for_a_person():
    [t] = adapt(dict(ROW, document_type="delivery note"))
    assert t.document_type == "other" and ("not_booked", "info") in issues_of(t)


def test_rows_of_one_invoice_share_a_reference_and_bank_lines_do_not():
    doc = {"document_total": 60.0, "document_type": "invoice", "counterparty": "Hilton", "date": "2026-09-01"}
    bill = adapt(dict(ROW, **doc, amount=20.0, account="7406 Subsistence"),
                 dict(ROW, **doc, amount=40.0, account="7400 Travel"))
    lines = adapt(dict(ROW, document_type="statement"), dict(ROW, document_type="statement"))
    assert bill[0].document_ref == bill[1].document_ref and lines[0].document_ref != lines[1].document_ref


def test_two_invoices_with_the_same_total_on_different_dates_are_two_documents():
    doc = {"document_total": 12000.0, "document_type": "invoice", "counterparty": "Business Cube"}
    first, second = checked(dict(ROW, **doc, amount=12000.0, date="2026-10-01"),
                            dict(ROW, **doc, amount=12000.0, date="2026-11-01"))
    assert first.document_ref != second.document_ref
    assert "total_mismatch" not in [code for t in (first, second) for code, _ in issues_of(t)]


def test_a_claims_lines_share_one_reference_whatever_their_dates():
    claim = {"document_total": 50.0, "document_type": "expense_claim", "counterparty": "Matt Barnes"}
    lines = adapt(dict(ROW, **claim, amount=18.0, date="2026-09-12"),
                  dict(ROW, **claim, amount=32.0, date="2026-09-14"))
    assert lines[0].document_ref is not None and lines[0].document_ref == lines[1].document_ref


def test_a_bank_line_keeps_the_balances_its_statement_prints():
    [t] = to_transactions([dict(ROW, document_type="statement", balance=1240.5)], source="table",
                          settings=BusinessSettings(), opening_balance=1500, closing_balance=-20)
    assert (t.balance, t.opening_balance, t.closing_balance) == (Decimal("1240.50"), Decimal("1500.00"), Decimal("-20.00"))


def test_balances_on_any_other_row_are_dropped():
    [t] = to_transactions([dict(ROW, document_type="receipt", balance=10)], source="table",
                          settings=BusinessSettings(), opening_balance=5, closing_balance=1)
    assert (t.balance, t.opening_balance, t.closing_balance) == (None, None, None)


def test_owed_to_sets_the_payroll_rows_other_account():
    rows = to_transactions([payroll_row(owed_to="net_pay"), payroll_row(owed_to="pension", account="7007"),
                            payroll_row(owed_to="paye_ni", account="7006")], "text", BusinessSettings())
    assert [r.owed_to for r in rows] == ["net_pay", "pension", "paye_ni"]
    assert [r.contra_account_code for r in rows] == ["2220", "2230", "2210"]
    assert all(r.document_type == "payroll" and not r.issues for r in rows)



def test_the_suppliers_vat_number_is_kept_without_spaces_in_upper_case():
    [t] = adapt(dict(ROW, supplier_vat_number=" gb 123 4567 89 "))
    assert t.supplier_vat_number == "GB123456789"
    [t] = adapt(ROW)
    assert t.supplier_vat_number is None


SHEET = [dict(ROW, description=d, amount=a, direction="out", document_type="expense_claim", counterparty="Matt",
              document_total=60.0, date=dt.date(2026, 10, n).isoformat())
         for n, d, a in ((2, "Pagecraft", 42.0), (3, "Taxi", 18.0))]


def test_a_claim_total_the_sheet_does_not_print_is_dropped():
    # The reader added the lines up to make 60.00; the sheet prints no such figure.
    rows = to_transactions(SHEET, source="table", settings=BusinessSettings(),
                           text="Date,Item,Amount\n2026-10-02,Pagecraft,42.00\n2026-10-03,Taxi,18.00")
    assert [t.document_total for t in rows] == [None, None]
    assert len({t.document_ref for t in rows}) == 2


def test_a_claim_total_the_sheet_prints_is_kept():
    rows = to_transactions(SHEET, source="table", settings=BusinessSettings(),
                           text="Pagecraft,42.00\nTaxi,18.00\nTotal 60.00")
    assert [t.document_total for t in rows] == [Decimal("60.00")] * 2
    assert len({t.document_ref for t in rows}) == 1


@pytest.mark.parametrize("printed", ["Total 60", "Total £60.00", "Total: 60.00.", "(60.00)", "60.00"])
def test_a_printed_total_is_found_however_it_is_written(printed):
    rows = to_transactions(SHEET, source="table", settings=BusinessSettings(), text=f"Pagecraft 42.00\n{printed}")
    assert rows[0].document_total == Decimal("60.00")


def test_a_printed_total_with_thousands_is_found():
    rows = to_transactions([dict(r, document_total=1234.5) for r in SHEET], source="table",
                           settings=BusinessSettings(), text="Total £1,234.50")
    assert rows[0].document_total == Decimal("1234.50")


@pytest.mark.parametrize("text", ["Total 1160.00", "Total 160.00", "Total 60.005", "Total 600", "Total 6.00"])
def test_a_total_inside_a_longer_number_is_not_printed(text):
    rows = to_transactions(SHEET, source="table", settings=BusinessSettings(), text=text)
    assert rows[0].document_total is None


def test_a_total_read_from_an_image_is_not_checked_against_text():
    rows = to_transactions(SHEET, source="image", settings=BusinessSettings())
    assert rows[0].document_total == Decimal("60.00")


def test_only_a_claims_total_is_checked_against_the_text():
    rows = to_transactions([dict(ROW, document_total=72.0)], source="pdf", settings=BusinessSettings(),
                           text="no figure here")
    assert rows[0].document_total == Decimal("72.00")


CUT_OFF = dict(ROW, description="Screwfix", amount=-86.40, account="5000 Purchases", document_type="receipt",
               counterparty="Screwfix Direct", document_total=86.40, document_net=72.00)


def test_a_total_the_receipt_does_not_print_is_marked_worked_out():
    [t] = to_transactions([CUT_OFF], source="text", settings=BusinessSettings(),
                          text="SCREWFIX DIRECT\nSubtotal 72.00\nVAT 20")
    assert t.total_worked_out is True


@pytest.mark.parametrize("text", ["Subtotal 72.00\nVAT 14.40\nTotal 86.40", None])   # printed; an image: no text
def test_a_printed_total_or_one_read_from_an_image_is_not_marked_worked_out(text):
    [t] = to_transactions([CUT_OFF], source="text", settings=BusinessSettings(), text=text)
    assert t.total_worked_out is False


def test_a_bank_line_is_never_marked_worked_out():
    [t] = to_transactions([dict(CUT_OFF, document_type="statement")], source="table", settings=BusinessSettings(),
                          text="03/10/2026,Screwfix,-86.4")
    assert t.total_worked_out is False


CIS_SALE = dict(ROW, description="Fenwick Builders, first fix joinery", amount=3400.0, direction="in",
                account="4000 Sales", document_type="invoice", counterparty="Fenwick Builders Ltd",
                document_number="AJ-2041", document_total=3400.0, document_net=4000.0)
CIS_TEXT = ("Labour 3,000.00\nMaterials 1,000.00\nNet 4,000.00\nVAT: Reverse charge\n"
            "CIS deduction 20% on labour (600.00)\nAmount due 3,400.00")


def test_a_cis_deduction_read_from_the_invoice_is_kept():
    [t] = to_transactions([dict(CIS_SALE, cis_deducted=600.0)], source="pdf", settings=BusinessSettings(), text=CIS_TEXT)
    assert (t.gross, t.cis_deducted) == (Decimal("3400.00"), Decimal("600.00"))


def test_a_cis_deduction_the_reader_missed_is_found_from_the_printed_net_and_the_word_cis():
    [t] = to_transactions([CIS_SALE], source="pdf", settings=BusinessSettings(), text=CIS_TEXT)
    assert (t.gross, t.cis_deducted) == (Decimal("3400.00"), Decimal("600.00"))


def test_an_amount_read_before_the_cis_deduction_becomes_the_amount_due():
    [t] = to_transactions([dict(CIS_SALE, amount=4000.0, cis_deducted=600.0)], source="pdf",
                          settings=BusinessSettings(), text=CIS_TEXT)
    assert (t.gross, t.cis_deducted) == (Decimal("3400.00"), Decimal("600.00"))


def test_a_discount_without_cis_is_not_taken_for_cis():
    [t] = to_transactions([CIS_SALE], source="pdf", settings=BusinessSettings(),
                          text="Net 4,000.00\nEarly payment discount (600.00)\nAmount due 3,400.00")
    assert t.cis_deducted is None


PAYOUT = dict(ROW, description="Stripe payout", amount=1163.10, direction="in", account="4000 Sales",
              document_type="statement", counterparty="Stripe Payments UK", date="2026-10-15")


def test_a_payment_processors_payout_goes_to_clearing_not_sales():
    # Ashdown's £1,163.10 Stripe payout was booked as one sale, with "choose its VAT rate": a payout is sales less
    # Stripe's fees and refunds, and only its payout report shows each.
    [t] = to_transactions([PAYOUT], source="table", settings=BusinessSettings())
    assert t.account_code == "1250"


CARD_PAID = dict(ROW, description="PAYMENT RECEIVED - THANK YOU", amount=850.00, direction="in",
                 account="4000 Sales", document_type="statement", counterparty="PAYMENT RECEIVED - THANK YOU")
ON_CARD = BusinessSettings(bank_account="1240", bank_accounts=("1200", "1210", "1240"))


def test_a_payment_to_a_card_is_a_transfer_from_the_bank_not_a_sale():
    # Kestrel's Amex statement: the £850 paid to the card was booked as a sale, and again from the bank line.
    [paid] = to_transactions([CARD_PAID], source="table", settings=ON_CARD)
    assert (paid.account_code, issues_of(paid)) == ("1200", [])
    # A refund from a shop is not worded as a payment: left as read, and said to be neither a sale nor a payment.
    [refund] = to_transactions([dict(CARD_PAID, description="DELL UK REFUND", counterparty="DELL UK")],
                               source="table", settings=ON_CARD)
    assert refund.account_code == "4000"
    [on_card] = match([refund.model_copy(update={"bank_account": "1240"})], ON_CARD)
    assert "card_credit" in [code for code, _ in issues_of(checked_again(on_card))]
    # The same words on a current account's statement are a customer's payment.
    [sale] = to_transactions([CARD_PAID], source="table", settings=BusinessSettings())
    assert sale.account_code == "4000"


def checked_again(t):
    from ledgersync.checks import normalise
    return normalise(t, ON_CARD)


@pytest.mark.parametrize("change", [{"direction": "out", "amount": -20.0, "account": "7504 Office Stationery"},
                                    {"counterparty": "Fenwick Builders Ltd", "description": "Fenwick Builders, AJ-2041"}])
def test_money_paid_out_through_a_processor_or_a_customers_payment_is_left_as_read(change):
    [t] = to_transactions([dict(PAYOUT, **change)], source="table", settings=BusinessSettings())
    assert t.account_code == str(change.get("account", "4000"))[:4]


NETFLIX = dict(ROW, description="Netflix subscription", amount=-12.99, account="8201 Subscriptions and Software",
               document_type="statement", counterparty="Netflix.com", date="2026-10-22")


@pytest.mark.parametrize("business_type, code", [("limited_company", "2250"), ("sole_trader", "3260"),
                                                  (None, "8201")])
def test_a_streaming_subscription_is_booked_to_the_owner(business_type, code):
    [t] = to_transactions([NETFLIX], source="table", settings=BusinessSettings(business_type=business_type))
    assert t.account_code == code


@pytest.mark.parametrize("who", ["STREAMFLIX.COM", "Streamflix.com", "Paramount Plus", "Apple TV"])
def test_any_streaming_service_on_the_company_card_is_the_directors(who):
    # The agency run: Streamflix's £10.99 a month went to Subscriptions; only services named on a list were caught.
    [t] = to_transactions([dict(NETFLIX, counterparty=who, description=who)], source="table",
                          settings=BusinessSettings(business_type="limited_company"))
    assert t.account_code == "2250" and ("personal", "info") in issues_of(t)


def test_a_coach_ticket_is_not_a_streaming_service():
    [t] = to_transactions([dict(NETFLIX, counterparty="FlixBus", description="FLIXBUS LONDON", account="7400 Travel")],
                          source="table", settings=BusinessSettings(business_type="limited_company"))
    assert t.account_code == "7400"


def test_vat_the_document_does_not_print_is_not_taken():
    # On a third reading the reader worked out Screwfix's £14.40 VAT (20% of £72.00), and it was reclaimed: the
    # receipt never prints it, so there's nothing to reclaim it with.
    [t] = to_transactions([dict(CUT_OFF, vat=14.40, document_vat=14.40)], source="text", settings=BusinessSettings(),
                          text="SCREWFIX DIRECT\nSubtotal 72.00\nVAT 20")
    assert t.vat is None


@pytest.mark.parametrize("text", ["Subtotal 72.00\nVAT 14.40\nTotal 86.40", None])   # printed; an image: no text
def test_vat_the_document_prints_or_read_from_an_image_is_kept(text):
    [t] = to_transactions([dict(CUT_OFF, vat=14.40, document_vat=14.40)], source="text", settings=BusinessSettings(),
                          text=text)
    assert t.vat == Decimal("14.40")


def test_a_rows_vat_that_is_its_share_of_a_printed_vat_total_is_kept():
    rows = [dict(ROW, amount=-60.0, vat=10.0, document_vat=15.0, document_total=90.0, document_type="invoice",
                 account="7504 Office Stationery"),
            dict(ROW, amount=-30.0, vat=5.0, document_vat=15.0, document_total=90.0, document_type="invoice",
                 account="7502 Telephone and Internet")]
    texts = to_transactions(rows, source="pdf", settings=BusinessSettings(), text="Paper 50.00\nCalls 25.00\nVAT 15.00\n"
                                                                                  "Total 90.00")
    assert [t.vat for t in texts] == [Decimal("10.00"), Decimal("5.00")]


APPLE = dict(ROW, description="MacBook Pro", amount=2400.0, vat=400.0, account="0030 Office Equipment",
             document_type="receipt", counterparty="Apple Retail UK Limited", document_total=2400.0)


def test_a_receipt_that_calls_itself_a_vat_invoice_is_an_invoice():
    # Kestrel's Apple "Receipt / VAT Invoice" was held in Suspense and asked for again as "the full VAT invoice".
    [t] = to_transactions([APPLE], source="text", settings=BusinessSettings(),
                          text="Apple Retail UK Limited\nReceipt / VAT Invoice R123\nTotal £2,400.00 VAT 400.00")
    assert t.document_type == "invoice"
    [kept] = to_transactions([APPLE], source="text", settings=BusinessSettings(),
                             text="Card receipt\nTHIS IS NOT A VAT INVOICE\nTotal £2,400.00 VAT 400.00")
    assert kept.document_type == "receipt"
    [plain] = to_transactions([APPLE], source="text", settings=BusinessSettings(), text="Till receipt Total £2,400.00 400.00")
    assert plain.document_type == "receipt"


SOLE = BusinessSettings(business_type="sole_trader", vat_registered=False)
COMPANY = BusinessSettings(business_type="limited_company")


def bank_out(description, account, **kw):
    return dict(ROW, description=description, counterparty=description, amount=-850.0, account=account,
                document_type="statement", **kw)


def test_the_owners_own_bills_go_to_the_owner_not_to_loans_or_suspense():
    # Hollis Plumbing: the mortgage went to Loans and the Self Assessment payment to Suspense, asking for a VAT invoice.
    mortgage, tax = to_transactions([bank_out("NATIONWIDE MORTGAGE", "2300 Loans"),
                                     bank_out("HMRC SELF ASSESSMENT 1234567890K", "9998 Suspense")],
                                    source="table", settings=SOLE)
    assert (mortgage.account_code, tax.account_code) == ("3260", "3260")
    assert "personal" in [code for code, _ in issues_of(tax)] and "account_unclear" not in [c for c, _ in issues_of(tax)]
    # A company may have a mortgage of its own; its director's Self Assessment is still the director's.
    mortgage, tax = to_transactions([bank_out("NATIONWIDE MORTGAGE", "2300 Loans"),
                                     bank_out("HMRC SELF ASSESSMENT 1234567890K", "9998 Suspense")],
                                    source="table", settings=COMPANY)
    assert (mortgage.account_code, tax.account_code) == ("2300", "2250")


def test_a_payment_on_account_is_held_on_the_customer_not_booked_as_a_sale():
    # Kestrel: "Orbit Media Ltd, payment on account" £1,000 went straight to Sales with no invoice.
    paid = dict(ROW, description="Orbit Media Ltd, payment on account", counterparty="Orbit Media Ltd", amount=1000.0,
                direction="in", account="4000 Sales", document_type="statement")
    [t] = to_transactions([paid], source="table", settings=BusinessSettings())
    assert t.account_code == "1100" and ("on_account", "info") in issues_of(t)
    [sale] = to_transactions([dict(paid, description="Orbit Media Ltd KD-101")], source="table", settings=BusinessSettings())
    assert sale.account_code == "4000"


def test_a_persons_payroll_lines_that_add_up_to_no_printed_gross_are_flagged():
    # Kestrel's January payroll: the totals agreed, but £35 had moved from one person to the other.
    def line(who, amount, owed_to):
        return payroll_row(description=f"{who} {owed_to}", counterparty=who, amount=amount, owed_to=owed_to, account="7000")
    text = "J Kestrel gross 3,000.00  A Patel gross 3,000.00  Total 6,000.00"
    rows = [line("J Kestrel", 2400.0, "net_pay"), line("J Kestrel", 560.0, "paye_ni"), line("J Kestrel", 75.0, "pension"),
            line("A Patel", 2350.0, "net_pay"), line("A Patel", 575.0, "paye_ni"), line("A Patel", 75.0, "pension")]
    read = to_transactions(rows, source="text", settings=BusinessSettings(), text=text)
    flagged = [t.counterparty for t in read if any(i.code == "payroll_person" for i in t.issues)]
    assert flagged == ["J Kestrel"]      # 3,035.00 is nobody's gross; A Patel's 3,000.00 is printed


def test_only_a_person_on_the_report_has_their_pay_checked():
    # The agency run: "Check this person's pay" on "Hannah Finch, Omar Kestrel", on HMRC and on the pension provider,
    # every month. Only a payee the report names, with net pay of their own, is one person's pay.
    def line(who, amount, owed_to, account="7000"):
        return payroll_row(description=f"{who} {owed_to}", counterparty=who, amount=amount, owed_to=owed_to,
                           account=account)
    text = ("Hannah Finch £1,047.50  Omar Kestrel £1,047.50  Priya Nair £2,333.33  Daniel Okoro £2,666.67\n"
            "Total gross pay £7,095.00")
    rows = [line("Hannah Finch, Omar Kestrel", 2095.0, "net_pay", "7001"), line("HMRC", 3321.37, "paye_ni"),
            line("Pension provider", 666.95, "pension"), line("Priya Nair", 1875.33, "net_pay")]
    read = to_transactions(rows, source="text", settings=BusinessSettings(), text=text)
    flagged = [t.counterparty for t in read if any(i.code == "payroll_person" for i in t.issues)]
    assert flagged == ["Priya Nair"]   # her net pay alone isn't her printed gross; the rest are not one person


def january_payroll(employees_net: float) -> list[dict]:
    """The agency's January 2024 payroll report as the model read it: the five employees' net pay in one row."""
    def line(description, amount, owed_to, account="7000"):
        return payroll_row(description=description, amount=amount, owed_to=owed_to, account=account,
                           document_total=18178.33)
    return [line("Net pay to directors", 2095.0, "net_pay", "7001"), line("Net pay to employees", employees_net, "net_pay"),
            line("Employees' tax and NI", 3107.39, "paye_ni"), line("Employees' pension", 666.95, "pension"),
            line("Employer's NI", 1776.40, "paye_ni", "7006"), line("Employer's pension", 400.17, "pension", "7007")]


def test_payroll_pay_lines_that_do_not_add_up_to_the_printed_total_gross_are_flagged():
    # The agency run: the model added the five employees' net pay to £12,309.00, not £12,308.99, and nothing said so.
    text = "Leah Morgan £3,212.69 ... Total gross pay £18,178.33"
    read = to_transactions(january_payroll(12309.00), source="text", settings=BusinessSettings(), text=text)
    [flagged] = [i for t in read for i in t.issues if i.code == "payroll_total"]
    assert "£18,178.34" in flagged.message and "£18,178.33" in flagged.message and flagged.severity == "warning"
    right = to_transactions(january_payroll(12308.99), source="text", settings=BusinessSettings(), text=text)
    assert not [i for t in right for i in t.issues if i.code == "payroll_total"]


def test_pay_lines_that_add_up_to_the_printed_total_gross_need_no_checking_one_by_one():
    # The paid run of 25 Nov 2026: the reader added each month's pay lines up from every person's figures and gave no
    # document total, so each line said "The payroll doesn't print £2,095.00: it was worked out ... Check it against
    # the document": 42 warnings in the year, though the report's printed total gross pay confirmed them.
    text = ("Hannah Finch £1,047.50 £0.00 £0.00 £39.95 ... Leah Morgan £4,333.33 £620.20 £379.81 £493.40 £183.45 "
            "£110.07 £3,149.87 Total gross pay £18,178.33")

    def lines(employees_net):
        return [dict(row, document_total=None) for row in january_payroll(employees_net)]

    right = to_transactions(lines(12308.99), source="text", settings=BusinessSettings(), text=text)
    pay = [t for t in right if t.account_code in ("7000", "7001")]
    assert len(pay) == 4 and not [i for t in pay for i in t.issues if i.code == "total_worked_out"]
    wrong = to_transactions(lines(12309.00), source="text", settings=BusinessSettings(), text=text)
    assert any(i.code == "total_worked_out" for t in wrong if t.account_code == "7000" for i in t.issues)


OKAFOR = dict(ROW, direction="out", document_type="invoice", counterparty="D Okafor Bricklaying", document_number="17",
              document_total=1000.0, document_net=1200.0, not_vat_invoice=True, cis_deducted=200.0)
OKAFOR_TEXT = ("Labour 1,000.00\nMaterials 200.00\nInvoice total 1,200.00\n"
               "Less CIS deduction at 20% on labour only (200.00)\nAmount payable 1,000.00")


def test_one_cis_deduction_on_an_invoice_of_two_lines_is_booked_once():
    # The reader took the deduction off the labour line and repeated the figure on both lines.
    labour, materials = to_transactions([
        dict(OKAFOR, description="Labour", amount=800.0, account="5002 Subcontractor Costs"),
        dict(OKAFOR, description="Materials", amount=200.0, account="5000 Purchases")],
        source="text", settings=BusinessSettings(), text=OKAFOR_TEXT)
    assert (labour.gross, labour.cis_deducted, labour.net) == (Decimal("800.00"), Decimal("200.00"), Decimal("1000.00"))
    assert (materials.gross, materials.cis_deducted, materials.net) == (Decimal("200.00"), None, Decimal("200.00"))


def test_lines_read_before_the_cis_deduction_come_to_the_amount_due():
    labour, materials = to_transactions([
        dict(OKAFOR, description="Materials", amount=200.0, account="5000 Purchases"),
        dict(OKAFOR, description="Labour", amount=1000.0, account="5002 Subcontractor Costs")][::-1],
        source="text", settings=BusinessSettings(), text=OKAFOR_TEXT)
    assert (labour.gross, labour.cis_deducted, labour.net) == (Decimal("800.00"), Decimal("200.00"), Decimal("1000.00"))
    assert (materials.gross, materials.cis_deducted) == (Decimal("200.00"), None)


def test_a_line_of_a_longer_invoice_is_not_given_a_cis_deduction_from_its_text():
    # Only an invoice of one row can have its deduction worked out from the printed net: a line's own gap means nothing.
    labour, materials = to_transactions([
        dict(OKAFOR, description="Labour", amount=800.0, account="5002 Subcontractor Costs", cis_deducted=200.0),
        dict(OKAFOR, description="Materials", amount=200.0, account="5000 Purchases", cis_deducted=None)],
        source="text", settings=BusinessSettings(), text=OKAFOR_TEXT)
    assert (labour.cis_deducted, materials.cis_deducted) == (Decimal("200.00"), None)


def test_how_many_a_meal_was_for_and_its_other_accounts_reach_the_row():
    [t] = adapt({**ROW, "account": "7406 Subsistence", "people": "several",
                 "alternatives": ["8206 Staff Welfare", "7406 Subsistence", "9999 Made Up"]})
    assert (t.people, t.alternatives) == ("several", ["8206"])
    [plain] = adapt(ROW)
    assert (plain.people, plain.alternatives) == (None, [])


def test_what_kind_of_food_was_bought_reaches_the_row():
    [t] = adapt({**ROW, "account": "7406 Subsistence", "bought": "meal_out"})
    assert t.bought == "meal_out"
    assert adapt({**ROW, "bought": "banquet"})[0].bought is None


def test_a_purchase_the_reader_saw_was_made_abroad_says_so_on_the_row():
    [t] = adapt({**ROW, "account": "7402 Hotels", "abroad": True})
    assert t.abroad is True
    assert adapt(ROW)[0].abroad is False


# What the business does decides a streaming subscription (user, 26 Nov 2026): a film, TV, music or media business
# may subscribe for its work; any other company's is the director's.

@pytest.mark.parametrize("trade, sic", [("Film and TV production", ""), ("Music streaming platform", ""),
                                        ("", "59111"), ("", "60200")])
def test_a_media_business_keeps_a_streaming_subscription_as_a_cost(trade, sic):
    settings = BusinessSettings(business_type="limited_company", nature_of_business=trade, sic_code=sic)
    [t] = to_transactions([dict(NETFLIX, counterparty="STREAMFLIX.COM", description="STREAMFLIX.COM")],
                          source="table", settings=settings)
    assert t.account_code == "8201" and ("for_the_trade", "info") in issues_of(t)


@pytest.mark.parametrize("trade, sic", [("Bakery and café", ""), ("Web design agency", "62012"), ("", "")])
def test_another_business_puts_a_streaming_subscription_to_the_director(trade, sic):
    settings = BusinessSettings(business_type="limited_company", nature_of_business=trade, sic_code=sic)
    [t] = to_transactions([NETFLIX], source="table", settings=settings)
    assert t.account_code == "2250" and ("personal", "info") in issues_of(t)


def test_what_the_business_does_never_makes_the_owners_own_tax_a_cost():
    settings = BusinessSettings(business_type="sole_trader", nature_of_business="Film production", sic_code="59111")
    [t] = to_transactions([dict(NETFLIX, counterparty="HMRC", description="HMRC SELF ASSESSMENT")], source="table",
                          settings=settings)
    assert t.account_code == "3260"
