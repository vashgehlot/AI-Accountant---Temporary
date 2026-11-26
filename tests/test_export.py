import datetime as dt
import io

import pytest
from openpyxl import load_workbook

from ledgersync import books, ledger
from ledgersync.export import MONEY, file_name
from ledgersync.models import ClientFields, RowPatch, Transaction

DAY = dt.date(2026, 10, 6)
CUBE = ClientFields(name="Business Cube Ltd", business_type="limited_company", contact_name="Jenny Clarke",
                    first_year_end=dt.date(2027, 3, 31))
YEAR = dt.date(2026, 4, 1)


pytestmark = pytest.mark.mongo


@pytest.fixture
def store(mongo_store):
    return mongo_store


def receipt(**changes):
    fields = dict(direction="out", gross="72.00", vat="12.00", account_code="7502", date=dt.date(2026, 9, 1),
                  description="BT Business, broadband", document_type="receipt", counterparty="BT Business",
                  supplier_vat_number="GB123456789")
    return Transaction(**{**fields, **changes})


def sheets(store, client_id):
    content, name = books.export(store, client_id, YEAR, DAY)
    book = load_workbook(io.BytesIO(content))
    return book["Trial balance"], book["Transactions"], name


def test_the_workbook_has_the_trial_balance_and_the_transactions(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "BT-0905.pdf", "pdf", [receipt()])
    tb, txs, name = sheets(store, client.id)
    assert name == "Business Cube Ltd 2026-10-06.xlsx"
    title = tb["A1"].value   # the year the figures are for, and the day they were worked out
    assert title.startswith("Business Cube Ltd — trial balance — Year to ") and title.endswith(", as at 6 Oct 2026")
    assert [[c.value for c in row] for row in tb.iter_rows(min_row=2)] == [
        ["Code", "Account", "Debit", "Credit", "Heading", "Tax", "SA103F box"],
        ["1200", "Bank Current Account", 0, 72, "Cash at bank and in hand", None, None],
        ["7502", "Telephone and Internet", 60, 0, "Administrative expenses", "Check: part may be disallowable", 23],
        ["2201", "Purchase VAT", 12, 0, "Creditors: amounts falling due within one year", None, None],
        [None, "Totals", 72, 72, None, None, None]]
    assert (tb["C3"].number_format, tb.freeze_panes) == (MONEY, "A3")
    assert [c.value for c in txs[2]] == ["Date", "Description", "Counterparty", "Document type", "In/Out", "Amount",
                                         "VAT", "Net", "Account", "Account name", "Other side", "Still owed",
                                         "Issues", "Upload", "Edited", "Left out"]
    assert [c.value for c in txs[3]] == [dt.datetime(2026, 9, 1), "BT Business, broadband", "BT Business", "Receipt",
                                         "Out", 72, 12, 60, "7502", "Telephone and Internet", "1200", None, None,
                                         "BT-0905.pdf", None, None]
    assert (txs["A3"].number_format, txs["F3"].number_format, txs.freeze_panes) == ("dd/mm/yyyy", MONEY, "A3")


def test_while_rows_need_fixing_the_trial_balance_sheet_says_what(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [receipt(account_code="9999")])
    tb, _, _ = sheets(store, client.id)
    assert tb["A2"].value == "The trial balance can't be produced yet:"
    assert tb["A3"].value.endswith("): This account isn't in the chart.")   # after the row's name, date and amount


def test_an_edited_row_says_so(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [receipt()])
    ledger.change_row(store, client.id, store.rows(client.id)[0].id, RowPatch(account_code="7504"))
    _, txs, _ = sheets(store, client.id)
    assert (txs["I3"].value, txs["O3"].value) == ("7504", "Yes")


def test_a_row_left_out_of_the_books_says_so(store):
    # The sheet listed a dropped duplicate like any other row, so adding up the amounts counted it twice.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [receipt(), receipt(), receipt()])
    first, second, third = (r.id for r in store.rows(client.id))
    store.patch_row(client.id, second, {"excluded": True})
    store.patch_row(client.id, third, {"superseded_by": "d1"})
    _, txs, _ = sheets(store, client.id)
    assert [txs[f"P{n}"].value for n in (2, 3, 4, 5)] == ["Left out", None, "Left out", "Replaced by a split"]


def test_a_row_a_person_removed_says_so(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [receipt(), receipt()])
    store.patch_row(client.id, store.rows(client.id)[1].id, {"excluded": True, "removed": True})
    _, txs, _ = sheets(store, client.id)
    assert [txs[f"P{n}"].value for n in (3, 4)] == [None, "Removed by a person"]


def test_vat_a_receipt_does_not_reclaim_stays_in_the_amount(store):
    # The test books' live run: a till receipt that isn't a VAT invoice made the export fail with a server error.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [receipt(not_vat_invoice=True)])
    _, txs, _ = sheets(store, client.id)
    assert [txs[f"{c}3"].value for c in "FGH"] == [72, 0, 72]   # amount, VAT, net: as the books hold it


def test_the_file_name_drops_characters_file_names_cannot_hold():
    # Review focus: a client name with characters a file name can't hold, or letters outside ASCII.
    assert file_name('A/B: "Trading" Ltd', DAY) == "A B Trading Ltd 2026-10-06.xlsx"
    assert file_name("Café £ Ltd", DAY) == "Café £ Ltd 2026-10-06.xlsx"
    assert file_name("???", DAY) == "Client 2026-10-06.xlsx"


def test_document_text_never_becomes_a_formula_or_breaks_the_export(store):
    # Final review #3: "=HYPERLINK(…)" read from a document became a live formula, and a stray control character
    # failed the whole export.
    client = store.create_client(CUBE.model_copy(update={"name": "=Evil Ltd"}))
    store.add_upload(client.id, "=cmd.pdf", "pdf", [receipt(description='=HYPERLINK("http://example.invalid","x")'),
                                                    receipt(description="Paper\x0cand toner", document_ref="p")])
    tb, txs, _ = sheets(store, client.id)
    assert (txs["B3"].value, txs["B3"].data_type) == ('=HYPERLINK("http://example.invalid","x")', "s")
    assert txs["B4"].value == "Paperand toner"
    assert (tb["A1"].data_type, txs["A1"].data_type, txs["N3"].data_type) == ("s", "s", "s")


def test_the_workbook_has_a_profit_and_loss_and_a_balance_sheet_that_balance(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "BT-0905.pdf", "pdf", [receipt()])
    content, _ = books.export(store, client.id, YEAR, DAY)
    book = load_workbook(io.BytesIO(content))
    assert book.sheetnames == ["Trial balance", "Transactions", "Profit and loss", "Balance sheet"]
    pl = {row[1]: row[2] for row in book["Profit and loss"].iter_rows(min_row=2, values_only=True)}
    bs = {row[1]: row[2] for row in book["Balance sheet"].iter_rows(min_row=2, values_only=True)}
    assert pl["Net loss"] < 0 and pl["Net loss"] == bs["Loss for the year"]
    assert bs["Net assets"] == bs["Capital and reserves"]


def test_the_statements_follow_the_companies_act_headings():
    from decimal import Decimal
    from ledgersync.export import statement_lines
    from ledgersync.posting import _line
    from ledgersync.models import TrialBalance
    pounds = {"0030": 2000, "0031": -500, "1100": 900, "1200": 3000, "2250": 400, "2100": -700, "2301": -1500,
              "2310": -300, "3000": -100, "3200": 1000, "4000": -10000, "4902": -50, "5000": 4000, "7100": 2000,
              "7903": 150, "8800": 1300, "2320": -1300, "9998": -300}
    lines = [_line(code, Decimal(amount)) for code, amount in sorted(pounds.items())]
    pl, bs = statement_lines(TrialBalance(lines=lines, total_debits=0, total_credits=0, is_balanced=True, journal=[]))
    p = {label: amount for _, label, amount, _ in pl}
    b = {label: amount for _, label, amount, _ in bs}
    assert (p["Turnover"], p["Gross profit"], p["Operating profit"], p["Profit before tax"], p["Net profit"]) == (
        10000, 6000, 4000, 3900, 2600)
    assert p["Interest receivable and similar income"] == 50 and p["Tax on profit"] == 1300
    # The corporation tax charge comes after profit before tax, not among the overheads.
    labels = [label for _, label, _, _ in pl]
    assert labels.index("Profit before tax") < labels.index("Corporation Tax Charge")
    assert (b["Tangible assets"], b["Fixed assets"]) == (1500, 1500)
    assert b["Debtors"] == 1300   # the director owes the company 400: a debtor, not a negative creditor
    assert b["Creditors: amounts falling due within one year"] == 2600   # with what Suspense holds in credit
    assert b["Creditors: amounts falling due after more than one year"] == 1500
    assert b["Net current assets"] == 1300 + 3000 - 2600
    assert b["Net assets"] == b["Capital and reserves"] == 1500 + 1700 - 1500   # shares 100, losses 1,000, profit
