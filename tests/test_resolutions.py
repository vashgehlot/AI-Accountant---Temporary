"""The accountant chat's resolutions (R0–R5): each checked against its evidence, applied or refused, and recorded as
a decision. Rows like Northbridge Consulting's October: a mixed-VAT Costco receipt, the Inkwell invoice, and a staff
expenses sheet that repeats both."""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import net, row
from ledgersync import books, documents, ledger, ledger_book, undo
from ledgersync.agent.locks import ClientLocks
from ledgersync.models import ClientPatch, RowPatch
from ledgersync.blobs import GridFSBlobStore
from ledgersync.checks import booked
from ledgersync.errors import InvalidInput
from job_scoring import net_by_account
from ledgersync.models import ClientFields, ClosedYear, Evidence, Issue, Transaction
from ledgersync.records import AgentRecords
from ledgersync.resolutions import (ChangeAccount, suggest_account_changes, waiting_suggestions, KeepOne, SetDate, SplitPart, SplitVat, UsePrimary, VatFromDocument, WhoWasThere, record_automatic,
                                    resolve, set_date)

pytestmark = pytest.mark.mongo

YEAR = dt.date(2026, 4, 1)
ACTOR = "agent:qwen/qwen3.8-27b"

COSTCO = """COSTCO WHOLESALE   Watford
Printer paper        52.80 A
Biscuits             12.00 Z
TOTAL  £64.80
VAT @ 20%   8.80
VAT No GB 123 4567 89"""
INKWELL = """Inkwell Print Ltd
Invoice INK-1043   Date 10 October 2026
Business cards   25.18
VAT 5.04
Total £30.22"""
SHEET = """Staff expenses, October 2026: Priya Shah
07/10/2026  Costco office supplies   64.80
10/10/2026  Inkwell business cards   27.50"""
DEPOT = """Office Depot
Toner   15.00
VAT     3.00
Total  18.00"""


@pytest.fixture
def records(mongo_db):
    return AgentRecords(mongo_db)


def new_client(store, name: str) -> int:
    return store.create_client(ClientFields(name=name, business_type="limited_company", contact_name="Sam Patel",
                                            vat_registered=True, first_year_end=dt.date(2027, 3, 31))).id


@pytest.fixture
def pages() -> dict[int, list[str]]:
    """The text of each upload, by its id, as documents.text_of would read it."""
    return {}


def upload_named(store, client_id: int, name: str) -> int:
    return next(u["id"] for u in store.uploads(client_id) if u["name"] == name)


def add(store, client_id: int, pages: dict, name: str, text: str, *rows, kind: str = "document") -> list[int]:
    """Saves the rows as one upload whose document reads `text`; the rows' ids."""
    upload_id = store.add_upload(client_id, name, kind, list(rows), year_start=YEAR)
    pages[upload_id] = [text]
    return [r.id for r in store.rows(client_id) if r.upload_id == upload_id]


@pytest.fixture
def nb(mongo_store, pages):
    """Northbridge Consulting Ltd (year to 31 Mar 2027) with the Costco receipt, the Inkwell invoice and the staff
    expenses sheet repeating both, the Inkwell line at £27.50."""
    store = mongo_store
    client_id = new_client(store, "Northbridge Consulting Ltd")
    [receipt] = add(store, client_id, pages, "costco.txt", COSTCO, row(
        date=dt.date(2026, 10, 7), description="Costco Wholesale", counterparty="Costco Wholesale",
        gross=Decimal("64.80"), vat=Decimal("8.80"), account_code="7504", document_number="T-4471"))
    [invoice] = add(store, client_id, pages, "inkwell-invoice.pdf", INKWELL, row(
        date=dt.date(2026, 10, 10), description="Business cards", counterparty="Inkwell Print Ltd",
        gross=Decimal("30.22"), vat=Decimal("5.04"), account_code="7500", document_type="invoice",
        document_number="INK-1043"))
    sheet_costco, sheet_inkwell = add(store, client_id, pages, "staff-expenses-october.xlsx", SHEET,
                                      row(date=dt.date(2026, 10, 7), description="Costco office supplies",
                                          counterparty="Priya Shah", gross=Decimal("64.80"), account_code="7504",
                                          document_type="expense_claim", document_ref="sheet"),
                                      row(date=dt.date(2026, 10, 10), description="Inkwell business cards",
                                          counterparty="Priya Shah", gross=Decimal("27.50"), account_code="7500",
                                          document_type="expense_claim", document_ref="sheet"), kind="table")
    return SimpleNamespace(id=client_id, receipt=receipt, invoice=invoice, sheet_costco=sheet_costco,
                           sheet_inkwell=sheet_inkwell, upload=lambda name: upload_named(store, client_id, name))


def call(store, records, pages, nb, row_id, resolution, *quotes, upload=None, reason="Checked the documents.", **kw):
    """resolve() as the agent's tool calls it, citing quotes from one upload (the receipt's by default)."""
    upload_id = upload or nb.upload("costco.txt")
    return resolve(store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=row_id,
                   resolution=resolution, evidence=[Evidence(upload_id=upload_id, quote=q) for q in quotes],
                   reason=reason, texts=lambda uid: pages.get(uid, []), **kw)


def saved(store, client_id: int, row_id: int):
    return next(r.tx for r in store.rows(client_id) if r.id == row_id)


def shown(store, client_id: int, row_id: int):
    """The row as the ledger shows it, matched."""
    return next(r for r in books.all_rows(store, client_id) if r.id == row_id)


def keep_receipt(nb) -> KeepOne:
    return KeepOne(action="keep_one", keep_row_id=nb.receipt, drop_row_ids=[nb.sheet_costco])


# ─── keep_one (R2) ─────────────────────────────────────────────────────────────

def test_keep_one_excludes_lower_ranked_copy(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "total   £64.80")
    assert (decision.status, decision.actor, decision.action) == ("applied", ACTOR, "keep_one")
    assert decision.rule.startswith("R2")
    assert decision.row_ids == sorted([nb.receipt, nb.sheet_costco])
    assert decision.before == {str(nb.sheet_costco): {"excluded": False}}
    assert decision.after == {str(nb.sheet_costco): {"excluded": True}}
    assert decision.evidence == [Evidence(upload_id=nb.upload("costco.txt"), upload_name="costco.txt",
                                          quote="total   £64.80")]
    assert decision.year_start == YEAR and decision.thread_id == "t1"
    dropped = saved(mongo_store, nb.id, nb.sheet_costco)
    assert dropped.excluded and dropped.decision_ids == [decision.id]
    assert not booked(shown(mongo_store, nb.id, nb.sheet_costco))
    assert booked(shown(mongo_store, nb.id, nb.receipt))
    assert [d.id for d in records.decisions(nb.id)] == [decision.id]


def test_keep_one_refuses_dropping_higher_rank(mongo_store, records, pages, nb):
    wrong_way = KeepOne(action="keep_one", keep_row_id=nb.sheet_costco, drop_row_ids=[nb.receipt])
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, wrong_way, "TOTAL £64.80")
    assert decision.status == "refused" and "ranks" in decision.reason
    assert decision.before == decision.after
    assert not saved(mongo_store, nb.id, nb.receipt).excluded
    assert saved(mongo_store, nb.id, nb.receipt).decision_ids == []
    assert [d.status for d in records.decisions(nb.id)] == ["refused"]


def test_keep_one_refuses_rows_that_are_not_the_same_transaction(mongo_store, records, pages, nb):
    unrelated = KeepOne(action="keep_one", keep_row_id=nb.receipt, drop_row_ids=[nb.sheet_inkwell])
    decision = call(mongo_store, records, pages, nb, nb.receipt, unrelated, "TOTAL £64.80")
    assert decision.status == "refused" and not saved(mongo_store, nb.id, nb.sheet_inkwell).excluded


# ─── use_primary (R4) ──────────────────────────────────────────────────────────

def paid_by_bank(nb, store, pages) -> int:
    """The bank line paying the Inkwell invoice in full (£30.22, two days after it); its upload id."""
    _, statement = bank_line(nb, store, pages, "30.22", dt.date(2026, 10, 12))
    return statement


def use_invoice_over_sheet(store, records, pages, nb, *statement_quotes):
    primary = UsePrimary(action="use_primary", primary_row_id=nb.invoice, other_row_id=nb.sheet_inkwell)
    return resolve(store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=nb.sheet_inkwell,
                   resolution=primary, reason="Checked the documents.", texts=lambda uid: pages.get(uid, []),
                   evidence=[Evidence(upload_id=nb.upload("inkwell-invoice.pdf"), quote="Total £30.22"),
                             *(Evidence(upload_id=nb.upload("barclays-october.csv"), quote=q)
                               for q in statement_quotes)])


def test_use_primary_invoice_beats_sheet(mongo_store, records, pages, nb):
    paid_by_bank(nb, mongo_store, pages)
    decision = use_invoice_over_sheet(mongo_store, records, pages, nb, "12/10/2026 INKWELL PRINT 30.22")
    assert decision.status == "applied" and decision.rule.startswith("R4")
    assert decision.after == {str(nb.sheet_inkwell): {"excluded": True}}
    assert booked(shown(mongo_store, nb.id, nb.invoice))
    assert not booked(shown(mongo_store, nb.id, nb.sheet_inkwell))
    tb = books.trial_balance(mongo_store, nb.id, YEAR)
    assert net(tb, "7500") == Decimal("25.18") and net(tb, "2100") == Decimal("0")   # the invoice, paid by the line


def test_use_primary_refuses_the_invoice_over_a_sheet_line_when_no_bank_line_pays_it(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.sheet_inkwell,
                    UsePrimary(action="use_primary", primary_row_id=nb.invoice, other_row_id=nb.sheet_inkwell),
                    "Total £30.22", upload=nb.upload("inkwell-invoice.pdf"))
    assert decision.status == "refused" and "No bank line pays the invoice's £30.22" in decision.reason
    assert "ask the person which amount is right" in decision.reason
    assert not saved(mongo_store, nb.id, nb.sheet_inkwell).excluded


def test_use_primary_links_a_bank_line_to_the_invoice(mongo_store, records, pages, nb):
    """With the sheet's line out of the books (it held the invoice back), a bank line that disagrees with the invoice
    pays it."""
    mongo_store.patch_row(nb.id, nb.sheet_inkwell, {"excluded": True})
    [line] = add(mongo_store, nb.id, pages, "barclays-october.csv", "12/10/2026 INKWELL PRINT 30.00",
                 row(date=dt.date(2026, 10, 12), description="INKWELL PRINT", counterparty="INKWELL PRINT",
                     gross=Decimal("30.00"), account_code="7500", document_type="statement"), kind="table")
    primary = UsePrimary(action="use_primary", primary_row_id=nb.invoice, other_row_id=line)
    decision = call(mongo_store, records, pages, nb, line, primary, "Total £30.22",
                    upload=nb.upload("inkwell-invoice.pdf"))
    ref = saved(mongo_store, nb.id, nb.invoice).document_ref
    assert decision.status == "applied" and decision.after == {str(line): {"link": [ref]}}
    after = saved(mongo_store, nb.id, line)
    assert after.link == [ref] and not after.excluded
    assert [p.ref for p in shown(mongo_store, nb.id, line).pays] == [ref]


def bank_line(nb, store, pages, gross: str, date: dt.date, who: str = "INKWELL PRINT") -> tuple[int, int]:
    """A barclays statement of one card/bank line out; its row id and upload id."""
    [line] = add(store, nb.id, pages, "barclays-october.csv", f"{date:%d/%m/%Y} {who} {gross}",
                 row(date=date, description=who, counterparty=who, gross=Decimal(gross), account_code="7500",
                     document_type="statement"), kind="table")
    return line, nb.upload("barclays-october.csv")


def test_use_primary_accepts_the_bank_line_that_pays_the_held_invoice(mongo_store, records, pages, nb):
    _, statement = bank_line(nb, mongo_store, pages, "30.22", dt.date(2026, 10, 12))
    primary = UsePrimary(action="use_primary", primary_row_id=nb.invoice, other_row_id=nb.sheet_inkwell)
    decision = resolve(mongo_store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=nb.sheet_inkwell,
                       resolution=primary, reason="Checked the documents.", texts=lambda uid: pages.get(uid, []),
                       evidence=[Evidence(upload_id=nb.upload("inkwell-invoice.pdf"), quote="Total £30.22"),
                                 Evidence(upload_id=statement, quote="12/10/2026 INKWELL PRINT 30.22")])
    assert decision.status == "applied"
    assert "12/10/2026 INKWELL PRINT 30.22" in [e.quote for e in decision.evidence]
    assert saved(mongo_store, nb.id, nb.sheet_inkwell).excluded


@pytest.mark.parametrize("gross, date, who", [("30.00", dt.date(2026, 10, 12), "INKWELL SUPPLIES"),
                                              ("30.22", dt.date(2026, 10, 9), "INKWELL SUPPLIES"),
                                              ("30.22", dt.date(2026, 10, 12), "ACME TOOLS")])
def test_use_primary_refuses_a_bank_line_that_does_not_pay_the_invoice(mongo_store, records, pages, nb, gross, date,
                                                                       who):
    _, statement = bank_line(nb, mongo_store, pages, gross, date, who)
    primary = UsePrimary(action="use_primary", primary_row_id=nb.invoice, other_row_id=nb.sheet_inkwell)
    quote = f"{date:%d/%m/%Y} {who} {gross}"
    decision = resolve(mongo_store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=nb.sheet_inkwell,
                       resolution=primary, reason="Checked the documents.", texts=lambda uid: pages.get(uid, []),
                       evidence=[Evidence(upload_id=statement, quote=quote)])
    assert decision.status == "refused"
    assert "This is only about which documents can be quoted" in decision.reason
    assert "inkwell-invoice.pdf" in decision.reason and "staff-expenses-october.xlsx" in decision.reason
    assert not saved(mongo_store, nb.id, nb.sheet_inkwell).excluded


def test_use_primary_refuses_a_bank_line_matching_would_only_suggest(mongo_store, records, pages, nb):
    """INKWELL SUPPLIES shares a word with Inkwell Print Ltd, but matching doesn't pay an invoice for that."""
    bank_line(nb, mongo_store, pages, "30.22", dt.date(2026, 10, 12), "INKWELL SUPPLIES")
    decision = use_invoice_over_sheet(mongo_store, records, pages, nb)
    assert decision.status == "refused" and "No bank line pays the invoice's £30.22" in decision.reason
    assert not saved(mongo_store, nb.id, nb.sheet_inkwell).excluded


def test_use_primary_names_the_document_total_it_looked_for(mongo_store, records, pages, nb):
    mongo_store.patch_row(nb.id, nb.invoice, {"document_total": "40.00"})
    decision = use_invoice_over_sheet(mongo_store, records, pages, nb)
    assert decision.status == "refused" and "No bank line pays the invoice's £40.00" in decision.reason


def use_receipt_over_sheet(store, records, pages, nb, *statement_quotes):
    primary = UsePrimary(action="use_primary", primary_row_id=nb.receipt, other_row_id=nb.sheet_costco)
    return resolve(store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=nb.sheet_costco,
                   resolution=primary, reason="Checked the documents.", texts=lambda uid: pages.get(uid, []),
                   evidence=[Evidence(upload_id=nb.upload("costco.txt"), quote="TOTAL  £64.80"),
                             *(Evidence(upload_id=nb.upload("barclays-october.csv"), quote=q)
                               for q in statement_quotes)])


def test_use_primary_receipt_over_a_sheet_line_needs_the_card_line(mongo_store, records, pages, nb):
    refused = use_receipt_over_sheet(mongo_store, records, pages, nb)
    assert refused.status == "refused" and "No bank line pays the receipt's £64.80" in refused.reason
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded
    bank_line(nb, mongo_store, pages, "64.80", dt.date(2026, 10, 7), "COSTCO WHOLESALE")
    applied = use_receipt_over_sheet(mongo_store, records, pages, nb, "07/10/2026 COSTCO WHOLESALE 64.80")
    assert applied.status == "applied" and saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_keep_one_accepts_the_card_line_that_pays_the_kept_receipt(mongo_store, records, pages, nb):
    _, statement = bank_line(nb, mongo_store, pages, "64.80", dt.date(2026, 10, 7), "COSTCO WHOLESALE")
    decision = resolve(mongo_store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=nb.receipt,
                       resolution=keep_receipt(nb), reason="Checked the documents.",
                       texts=lambda uid: pages.get(uid, []),
                       evidence=[Evidence(upload_id=nb.upload("costco.txt"), quote="TOTAL  £64.80"),
                                 Evidence(upload_id=statement, quote="07/10/2026 COSTCO WHOLESALE 64.80")])
    assert decision.status == "applied" and saved(mongo_store, nb.id, nb.sheet_costco).excluded


# ─── keep_one: the bank line that pays the receipt kept (the duplicate-receipt-spreadsheet case) ──

CASE = Path(__file__).parent.parent / "eval" / "agent_cases" / "duplicate-receipt-spreadsheet"


@pytest.fixture
def staples(mongo_store, mongo_db, records):
    """The case's files added with the rows their .rows.json give: the Staples receipt, the expenses sheet line for it
    and the Barclays card line that paid it."""
    store = mongo_store
    blobs = GridFSBlobStore(mongo_db)
    client_id = new_client(store, "Northbridge Consulting Ltd")
    for name in ("barclays-october.csv", "staff-expenses-october.xlsx", "staples-receipt.txt"):
        path = CASE / "documents" / name
        read = json.loads((CASE / "documents" / f"{name}.rows.json").read_text())
        sha256 = blobs.put(path.read_bytes(), name=name, content_type="application/octet-stream")
        store.add_upload(client_id, name, read["kind"], [Transaction.model_validate(t) for t in read["transactions"]],
                         sha256=sha256, bank_account=read["bank_account"], year_start=YEAR)
    uploads = {u["id"]: u for u in store.uploads(client_id)}
    by_name = {u["name"]: n for n, u in uploads.items()}
    by_text = {r.tx.description: r.id for r in store.rows(client_id)}
    return SimpleNamespace(
        id=client_id, receipt=by_text["Staples: A4 printer paper and toner"],
        sheet=by_text["Staples - printer paper and toner"], bank=by_text["STAPLES"],
        upload=by_name.__getitem__, texts=lambda uid: documents.text_of(uploads[uid], blobs, records))


def staples_call(store, records, staples, row_id, drop):
    keep = KeepOne(action="keep_one", keep_row_id=staples.receipt, drop_row_ids=drop)
    return resolve(store, records, client_id=staples.id, thread_id="t1", actor=ACTOR, row_id=row_id,
                   resolution=keep, reason="Checked the documents.", texts=staples.texts,
                   evidence=[Evidence(upload_id=staples.upload("staples-receipt.txt"), quote="TOTAL 64.80"),
                             Evidence(upload_id=staples.upload("barclays-october.csv"), quote="13/10/2026,")])


def test_keep_one_refuses_to_drop_the_bank_line_that_pays_the_receipt_kept(mongo_store, records, staples):
    decision = staples_call(mongo_store, records, staples, staples.bank, [staples.bank, staples.sheet])
    assert decision.status == "refused" and "is its payment, not a duplicate" in decision.reason
    assert f"Row {staples.bank}, the bank line, pays the receipt kept" in decision.reason
    assert not saved(mongo_store, staples.id, staples.bank).excluded
    assert not saved(mongo_store, staples.id, staples.sheet).excluded


def test_keep_one_refuses_a_payroll_line_and_the_bank_line_that_pays_it(mongo_store, records, pages, nb):
    # Kestrel's review dropped the January salary payments as copies of the payroll lines: the bank fell £4,750.00
    # short of its statement and the wages owed were never cleared.
    day = dt.date(2026, 10, 30)
    [pay] = add(mongo_store, nb.id, pages, "payroll-october.txt", "J Kestrel net pay 2,400.00",
                row(date=day, description="J Kestrel net pay", counterparty="J Kestrel", gross=Decimal("2400.00"),
                    account_code="7001", document_type="payroll", owed_to="net_pay"), kind="text")
    line, statement = bank_line(nb, mongo_store, pages, "2400.00", day, who="J Kestrel")
    keep = KeepOne(action="keep_one", keep_row_id=pay, drop_row_ids=[line])
    decision = call(mongo_store, records, pages, nb, line, keep, "J Kestrel net pay 2,400.00",
                    upload=nb.upload("payroll-october.txt"))
    assert decision.status == "refused" and "not a duplicate" in decision.reason and "Keep both" in decision.reason
    assert not saved(mongo_store, nb.id, line).excluded


def test_keep_one_refuses_to_drop_a_bank_line_already_paying_the_invoice_kept(mongo_store, records, pages, nb):
    line, _ = bank_line(nb, mongo_store, pages, "30.22", dt.date(2026, 10, 12))
    mongo_store.patch_row(nb.id, line, {"link": [saved(mongo_store, nb.id, nb.invoice).document_ref]})
    keep = KeepOne(action="keep_one", keep_row_id=nb.invoice, drop_row_ids=[line])
    decision = call(mongo_store, records, pages, nb, line, keep, "Total £30.22", upload=nb.upload("inkwell-invoice.pdf"))
    assert decision.status == "refused" and "pays the invoice kept" in decision.reason
    assert not saved(mongo_store, nb.id, line).excluded


def test_keep_one_asked_on_the_bank_line_points_to_the_receipt_as_the_row(mongo_store, records, staples):
    # The booked_twice issue sits on the bank line, so the call is aimed at it: the refusal must not say to drop it.
    decision = staples_call(mongo_store, records, staples, staples.bank, [staples.sheet])
    assert decision.status == "refused" and "pays the receipt kept" in decision.reason
    assert "with the receipt as row_id" in decision.reason and "among them" not in decision.reason
    assert not saved(mongo_store, staples.id, staples.sheet).excluded
    assert not saved(mongo_store, staples.id, staples.bank).excluded


def test_keep_one_keeps_the_receipt_and_the_bank_line_that_pays_it(mongo_store, records, staples):
    decision = staples_call(mongo_store, records, staples, staples.receipt, [staples.sheet])
    assert decision.status == "applied" and decision.row_ids == sorted([staples.receipt, staples.sheet])
    assert saved(mongo_store, staples.id, staples.sheet).excluded
    assert not saved(mongo_store, staples.id, staples.bank).excluded
    line, receipt = shown(mongo_store, staples.id, staples.bank), shown(mongo_store, staples.id, staples.receipt)
    assert line.recorded_by is not None and line.recorded_by.ref == receipt.document_ref and not booked(line)
    assert "booked_twice" not in [i.code for i in line.issues]
    assert booked(receipt) and [p.ref for p in receipt.paid_by] == [line.document_ref]
    ledger_book.post(mongo_store, records, staples.id, YEAR)
    tb = ledger_book.posted_trial_balance(mongo_store, records, staples.id, YEAR)
    expected = {k: Decimal(v) for k, v in json.loads((CASE / "expected_trial_balance.json").read_text()).items()}
    assert net_by_account(tb.model_dump()) == expected


def test_keep_one_still_drops_a_bank_line_read_twice(mongo_store, records, pages, nb):
    def inkwell():
        return row(date=dt.date(2026, 10, 12), description="INKWELL SUPPLIES", counterparty="INKWELL SUPPLIES",
                   gross=Decimal("30.22"), account_code="7500", document_type="statement")

    first, second = add(mongo_store, nb.id, pages, "barclays-october.csv", "12/10/2026 INKWELL SUPPLIES 30.22",
                        inkwell(), inkwell(), kind="table")
    statement = nb.upload("barclays-october.csv")
    twice = KeepOne(action="keep_one", keep_row_id=first, drop_row_ids=[second])
    decision = resolve(mongo_store, records, client_id=nb.id, thread_id="t1", actor=ACTOR, row_id=second,
                       resolution=twice, reason="The statement was read twice.", texts=lambda uid: pages.get(uid, []),
                       evidence=[Evidence(upload_id=statement, quote="12/10/2026 INKWELL SUPPLIES 30.22")])
    assert decision.status == "applied" and saved(mongo_store, nb.id, second).excluded


def test_use_primary_refuses_a_lower_ranked_primary(mongo_store, records, pages, nb):
    backwards = UsePrimary(action="use_primary", primary_row_id=nb.sheet_inkwell, other_row_id=nb.invoice)
    decision = call(mongo_store, records, pages, nb, nb.invoice, backwards, "Total £30.22",
                    upload=nb.upload("inkwell-invoice.pdf"))
    assert decision.status == "refused" and not saved(mongo_store, nb.id, nb.invoice).excluded


# ─── split_vat (R3) ────────────────────────────────────────────────────────────

def costco_split(zero_part: str = "12.00") -> SplitVat:
    return SplitVat(action="split_vat", parts=[
        SplitPart(description="Printer paper", account_code="7504", gross=Decimal("52.80"), rate="standard"),
        SplitPart(description="Biscuits", account_code="7406", gross=Decimal(zero_part), rate="zero")])


def test_split_vat_parts_must_sum(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.receipt, costco_split("11.99"), "Biscuits 12.00 Z")
    assert decision.status == "refused" and "£64.79" in decision.reason
    assert saved(mongo_store, nb.id, nb.receipt).superseded_by is None
    assert len(mongo_store.rows(nb.id)) == 4


def test_split_vat_refuses_vat_that_does_not_match_the_document(mongo_store, records, pages, nb):
    both_standard = SplitVat(action="split_vat", parts=[
        SplitPart(description="Printer paper", account_code="7504", gross=Decimal("52.80"), rate="standard"),
        SplitPart(description="Biscuits", account_code="7406", gross=Decimal("12.00"), rate="standard")])
    decision = call(mongo_store, records, pages, nb, nb.receipt, both_standard, "VAT @ 20% 8.80")
    assert decision.status == "refused" and "VAT" in decision.reason


def test_split_vat_supersedes_original(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Printer paper 52.80 A",
                    "Biscuits 12.00 Z")
    assert decision.status == "applied" and decision.rule.startswith("R3")
    assert saved(mongo_store, nb.id, nb.receipt).superseded_by == decision.id
    parts = [r for r in books.all_rows(mongo_store, nb.id) if r.id in decision.row_ids and r.id != nb.receipt]
    assert [(p.description, p.account_code, p.gross, p.vat_posted) for p in parts] == [
        ("Printer paper", "7504", Decimal("52.80"), Decimal("8.80")),
        ("Biscuits", "7406", Decimal("12.00"), Decimal("0.00"))]
    assert all(booked(p) and p.decision_ids == [decision.id] for p in parts)
    assert not booked(shown(mongo_store, nb.id, nb.receipt))
    assert decision.before == {str(nb.receipt): {"superseded_by": None}}
    assert decision.after[str(nb.receipt)] == {"superseded_by": decision.id}
    assert decision.after[str(parts[0].id)] == {"description": "Printer paper", "account_code": "7504",
                                                "gross": "52.80", "vat": "8.80", "vat_treatment": "standard"}


def test_split_vat_applies_to_a_receipt_the_reader_kept_whole(mongo_store, records, pages, nb):
    # Bulkbuy as the reader gives it: three rows the adapter puts back together as one 64.00 / 7.60 row.
    from ledgersync.adapter import to_transactions
    from ledgersync.models import BusinessSettings
    text = "BULKBUY\nPens 19.20 A\nBin bags 26.40 A\nWater 18.40 Z\nTOTAL 64.00\nVAT 7.60"
    doc = {"document_total": 64.0, "document_vat": 7.6, "date": "2026-10-05", "direction": "out", "currency": "GBP",
           "description": "Bulkbuy"}
    [whole] = to_transactions(
        [dict(doc, amount=19.2, vat=3.2, account="7801 Cleaning"),
         dict(doc, amount=26.4, vat=4.4, account="7504 Office Stationery"),
         dict(doc, amount=18.4, vat=0.0, account="8205 Refreshments")], "document", BusinessSettings())
    [row_id] = add(mongo_store, nb.id, pages, "bulkbuy.txt", text, whole)
    split = SplitVat(action="split_vat", parts=[
        SplitPart(description="Pens and bin bags", account_code="7504", gross=Decimal("45.60"), rate="standard"),
        SplitPart(description="Water", account_code="8205", gross=Decimal("18.40"), rate="zero")])
    decision = call(mongo_store, records, pages, nb, row_id, split, "TOTAL 64.00", "VAT 7.60",
                    upload=nb.upload("bulkbuy.txt"))
    assert decision.status == "applied" and decision.rule.startswith("R3")
    assert saved(mongo_store, nb.id, row_id).superseded_by == decision.id


# ─── set_vat_from_document (R5) ────────────────────────────────────────────────

@pytest.fixture
def depot(mongo_store, pages, nb) -> int:
    """An Office Depot receipt read without its VAT."""
    [receipt] = add(mongo_store, nb.id, pages, "depot.pdf", DEPOT, row(
        date=dt.date(2026, 10, 20), description="Toner", counterparty="Office Depot", gross=Decimal("18.00"),
        account_code="7504"))
    return receipt


def test_vat_from_document_must_appear_in_text(mongo_store, records, pages, nb, depot):
    cite = dict(upload=nb.upload("depot.pdf"))
    refused = call(mongo_store, records, pages, nb, depot,
                   VatFromDocument(action="set_vat_from_document", vat=Decimal("2.50")), "Total 18.00", **cite)
    assert refused.status == "refused" and saved(mongo_store, nb.id, depot).vat is None
    applied = call(mongo_store, records, pages, nb, depot,
                   VatFromDocument(action="set_vat_from_document", vat=Decimal("3.00")), "VAT 3.00", **cite)
    assert applied.status == "applied" and applied.rule.startswith("R5")
    assert applied.before == {str(depot): {"vat": None}} and applied.after == {str(depot): {"vat": "3.00"}}
    assert saved(mongo_store, nb.id, depot).vat == Decimal("3.00")


def test_vat_printed_with_a_thousands_comma_is_found(mongo_store, records, pages, nb):
    text = "Big Machines\nVAT 1,200.00\nTotal 7,200.00"
    [big] = add(mongo_store, nb.id, pages, "big.pdf", text, row(
        date=dt.date(2026, 10, 20), description="Machine", counterparty="Big Machines", gross=Decimal("7200.00"),
        account_code="7504"))
    decision = call(mongo_store, records, pages, nb, big,
                    VatFromDocument(action="set_vat_from_document", vat=Decimal("1200.00")), "VAT 1,200.00",
                    upload=nb.upload("big.pdf"))
    assert decision.status == "applied" and saved(mongo_store, nb.id, big).vat == Decimal("1200.00")


def test_vat_above_a_sixth_of_the_amount_is_refused(mongo_store, records, pages, nb, depot):
    pages[nb.upload("depot.pdf")] = [DEPOT + "\nVAT 3.60"]
    decision = call(mongo_store, records, pages, nb, depot,
                    VatFromDocument(action="set_vat_from_document", vat=Decimal("3.60")), "VAT 3.60",
                    upload=nb.upload("depot.pdf"))
    assert decision.status == "refused" and saved(mongo_store, nb.id, depot).vat is None


# ─── R0, every action ──────────────────────────────────────────────────────────

def test_quote_not_in_document_refused(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £99.99")
    assert decision.status == "refused" and "TOTAL £99.99" in decision.reason
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_a_quote_with_spaces_after_commas_is_found_in_a_csv_line(mongo_store, records, pages, nb):
    pages[nb.upload("costco.txt")].append("07/10/2026,-58.00,Card Purchase,COSTCO WHOLESALE")
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb),
                    "-58.00, Card Purchase, COSTCO WHOLESALE")
    assert decision.status == "applied", decision.reason


def test_evidence_from_another_clients_upload_refused(mongo_store, records, pages, nb):
    other = new_client(mongo_store, "Other Ltd")
    add(mongo_store, other, pages, "theirs.txt", COSTCO, row(gross=Decimal("1.00")))
    theirs = next(u["id"] for u in mongo_store.uploads(other))
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80",
                    upload=theirs)
    assert decision.status == "refused" and not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_closed_year_refused(mongo_store, records, pages, nb):
    mongo_store.close_year(nb.id, ClosedYear(start=YEAR, end=dt.date(2027, 3, 31), closed_at="2027-04-30T00:00:00",
                                             closing={}))
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    assert decision.status == "refused" and "closed" in decision.reason
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_other_clients_row_refused(mongo_store, records, pages, nb):
    other = new_client(mongo_store, "Other Ltd")
    [theirs] = add(mongo_store, other, pages, "theirs.txt", COSTCO, row(
        date=dt.date(2026, 10, 7), counterparty="Costco Wholesale", gross=Decimal("64.80"), account_code="7504",
        document_type="expense_claim"))
    stray = KeepOne(action="keep_one", keep_row_id=nb.receipt, drop_row_ids=[theirs])
    decision = call(mongo_store, records, pages, nb, theirs, stray, "TOTAL £64.80")
    assert decision.status == "refused" and decision.client_id == nb.id
    assert not saved(mongo_store, other, theirs).excluded
    assert records.decisions(other) == []


def test_resolve_twice_is_one_decision(mongo_store, records, pages, nb):
    first = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    again = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    assert again.id == first.id and len(records.decisions(nb.id)) == 1
    assert saved(mongo_store, nb.id, nb.sheet_costco).decision_ids == [first.id]


def test_a_refusal_does_not_stick(mongo_store, records, pages, nb):
    """A refusal is kept but not returned for a retry: corrected, the same resolution applies."""
    first = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £99.99")
    again = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    assert (first.status, again.status) == ("refused", "applied") and again.id != first.id
    assert [d.status for d in records.decisions(nb.id)] == ["refused", "applied"]
    assert call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80").id == again.id


def test_evidence_from_an_unrelated_upload_of_the_client_refused(mongo_store, records, pages, nb):
    """The invoice's upload is the client's, but neither row kept nor row dropped comes from it."""
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "Total £30.22",
                    upload=nb.upload("inkwell-invoice.pdf"))
    assert decision.status == "refused" and not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_a_quote_too_short_to_show_anything_refused(mongo_store, records, pages, nb):
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), " 6 ")
    assert decision.status == "refused" and not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_amounts_must_be_whole_pennies(mongo_store, records, pages, nb, depot):
    split = SplitVat(action="split_vat", parts=[
        SplitPart(description="Printer paper", account_code="7504", gross=Decimal("52.805"), rate="standard"),
        SplitPart(description="Biscuits", account_code="7406", gross=Decimal("11.995"), rate="zero")])
    assert call(mongo_store, records, pages, nb, nb.receipt, split, "Biscuits 12.00 Z").status == "refused"
    vat = VatFromDocument(action="set_vat_from_document", vat=Decimal("3.001"))
    assert call(mongo_store, records, pages, nb, depot, vat, "VAT 3.00", upload=nb.upload("depot.pdf")).status \
        == "refused"
    assert saved(mongo_store, nb.id, depot).vat is None and saved(mongo_store, nb.id, nb.receipt).superseded_by is None


def test_use_primary_refuses_to_drop_the_bank_payment_of_a_payroll_report(mongo_store, records, pages, nb):
    [wages] = add(mongo_store, nb.id, pages, "payroll-october.pdf", "Net pay 2,400.00", row(
        date=dt.date(2026, 10, 28), description="Net pay", counterparty="Staff", gross=Decimal("2400.00"),
        account_code="7000", document_type="payroll", owed_to="net_pay"))
    [line] = add(mongo_store, nb.id, pages, "barclays-october.csv", "28/10/2026 SALARIES 2,350.00",
                 row(date=dt.date(2026, 10, 28), description="SALARIES", counterparty="Staff",
                     gross=Decimal("2350.00"), account_code="2220", document_type="statement"), kind="table")
    primary = UsePrimary(action="use_primary", primary_row_id=wages, other_row_id=line)
    decision = call(mongo_store, records, pages, nb, line, primary, "Net pay 2,400.00",
                    upload=nb.upload("payroll-october.pdf"))
    assert decision.status == "refused" and not saved(mongo_store, nb.id, line).excluded


def with_new_error_on(monkeypatch, row_ids):
    """Makes the ledger show an error on these rows from now on, as if the change caused it."""
    real = books.all_rows

    def all_rows(store, client_id):
        return [r.model_copy(update={"issues": r.issues + [Issue(code="same_account", severity="error",
                                                                 message="Posts to and from the same account.")]})
                if r.id in row_ids() else r for r in real(store, client_id)]
    monkeypatch.setattr(books, "all_rows", all_rows)


def test_a_change_that_leaves_a_new_error_is_put_back(mongo_store, records, pages, nb, monkeypatch):
    with_new_error_on(monkeypatch, lambda: {nb.sheet_costco})
    decision = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    assert decision.status == "refused" and "same account" in decision.reason
    assert decision.before == decision.after
    dropped = saved(mongo_store, nb.id, nb.sheet_costco)
    assert not dropped.excluded and dropped.decision_ids == []


def test_a_split_that_leaves_a_new_error_is_put_back(mongo_store, records, pages, nb, monkeypatch):
    before = {r.id for r in mongo_store.rows(nb.id)}
    with_new_error_on(monkeypatch, lambda: {r.id for r in mongo_store.rows(nb.id)} - before)   # on the parts
    decision = call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Biscuits 12.00 Z")
    assert decision.status == "refused"
    original = saved(mongo_store, nb.id, nb.receipt)
    assert original.superseded_by is None and original.decision_ids == []
    assert {r.id for r in mongo_store.rows(nb.id)} == before
    assert not any(u["kind"] == "split" for u in mongo_store.uploads(nb.id))


def test_vat_put_back_leaves_the_row_exactly_as_stored(mongo_store, records, pages, nb, depot, monkeypatch):
    """VAT is a field a person edits, so setting it keeps what was read; putting it back drops that again."""
    before = mongo_store.row_data(nb.id, [depot])
    with_new_error_on(monkeypatch, lambda: {depot})
    decision = call(mongo_store, records, pages, nb, depot,
                    VatFromDocument(action="set_vat_from_document", vat=Decimal("3.00")), "VAT 3.00",
                    upload=nb.upload("depot.pdf"))
    assert decision.status == "refused" and mongo_store.row_data(nb.id, [depot]) == before
    assert "original" not in before[depot]


def test_set_date_put_back_leaves_the_row_exactly_as_stored(mongo_store, records, nb, taxi, monkeypatch):
    before = mongo_store.row_data(nb.id, [taxi])
    with_new_error_on(monkeypatch, lambda: {taxi})
    decision = set_date(mongo_store, records, client_id=nb.id, thread_id="t1", row_id=taxi,
                        date=dt.date(2026, 10, 16), question_id="q1")
    assert decision.status == "refused" and mongo_store.row_data(nb.id, [taxi]) == before


def test_a_failure_while_changing_rows_puts_them_back(mongo_store, records, pages, nb, monkeypatch):
    """The change is written, then something fails before it is recorded: the rows go back and nothing is
    recorded, and the error is raised."""
    before = mongo_store.row_data(nb.id, [nb.receipt, nb.sheet_costco])

    def fails(store, client_id):
        raise RuntimeError("lost the connection")
    monkeypatch.setattr(books, "all_rows", fails)
    with pytest.raises(RuntimeError):
        call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), "TOTAL £64.80")
    assert mongo_store.row_data(nb.id, [nb.receipt, nb.sheet_costco]) == before
    assert records.decisions(nb.id) == []


def test_a_failure_after_a_split_removes_its_parts(mongo_store, records, pages, nb, monkeypatch):
    before = mongo_store.row_data(nb.id, [r.id for r in mongo_store.rows(nb.id)])

    def fails(store, client_id):
        raise RuntimeError("lost the connection")
    monkeypatch.setattr(books, "all_rows", fails)
    with pytest.raises(RuntimeError):
        call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Biscuits 12.00 Z")
    assert mongo_store.row_data(nb.id, [r.id for r in mongo_store.rows(nb.id)]) == before
    assert not any(u["kind"] == "split" for u in mongo_store.uploads(nb.id)) and records.decisions(nb.id) == []


# ─── set_date (R1, from an answer) ─────────────────────────────────────────────

@pytest.fixture
def taxi(mongo_store, pages, nb) -> int:
    """An undated taxi receipt, waiting in the year it was added to."""
    [receipt] = add(mongo_store, nb.id, pages, "taxi.jpg", "Taxi fare £18.00", row(
        date=None, description="Taxi", counterparty="City Cars", gross=Decimal("18.00"), account_code="7400"))
    return receipt


def test_set_date_outside_books_refused(mongo_store, records, nb, taxi):
    with pytest.raises(InvalidInput) as refused:
        set_date(mongo_store, records, client_id=nb.id, thread_id="t1", row_id=taxi, date=dt.date(2026, 3, 31),
                 question_id="q1")
    assert refused.value.message == "That date is outside the books, which run from 1 Apr 2026 to 31 Mar 2027."
    assert saved(mongo_store, nb.id, taxi).date is None and records.decisions(nb.id) == []


def test_set_date_from_an_answer_is_recorded(mongo_store, records, nb, taxi):
    decision = set_date(mongo_store, records, client_id=nb.id, thread_id="t1", row_id=taxi,
                        date=dt.date(2026, 10, 16), question_id="q1")
    assert (decision.status, decision.actor, decision.action) == ("applied", "user", "set_date")
    assert decision.rule.startswith("R1") and decision.reason == "Dated 16 Oct 2026 from the person's answer."
    assert decision.before == {str(taxi): {"date": None}} and decision.after == {str(taxi): {"date": "2026-10-16"}}
    assert saved(mongo_store, nb.id, taxi).date == dt.date(2026, 10, 16)
    again = set_date(mongo_store, records, client_id=nb.id, thread_id="t1", row_id=taxi,
                     date=dt.date(2026, 10, 16), question_id="q1")
    assert again.id == decision.id and len(records.decisions(nb.id)) == 1


# ─── record_automatic (R1, from the bank) ──────────────────────────────────────

def test_record_automatic_turns_bank_dating_into_decision(mongo_store, records, pages, nb):
    [receipt] = add(mongo_store, nb.id, pages, "parking.jpg", "NCP  £6.50", row(
        date=None, description="Parking", counterparty="Addison Lee", gross=Decimal("6.50"), account_code="7400"))
    add(mongo_store, nb.id, pages, "barclays-october.csv", "14/10/2026 ADDISON LEE LONDON 6.50",
        row(date=dt.date(2026, 10, 14), description="ADDISON LEE LONDON", counterparty="ADDISON LEE",
            gross=Decimal("6.50"), account_code="7400", document_type="statement"), kind="table")
    bank = nb.upload("barclays-october.csv")
    [decision] = record_automatic(mongo_store, records, client_id=nb.id, year_start=YEAR, thread_id="t1")
    assert (decision.rule, decision.actor, decision.status) == ("R1 Date from the bank", "rules", "applied")
    assert decision.row_ids == [receipt]
    assert decision.evidence == [Evidence(upload_id=bank, upload_name="barclays-october.csv",
                                          quote="ADDISON LEE LONDON")]
    assert decision.before == {str(receipt): {"date": None}}
    assert decision.after == {str(receipt): {"date": "2026-10-14"}}
    assert saved(mongo_store, nb.id, receipt).date is None   # matching dates it; the row is not changed
    assert record_automatic(mongo_store, records, client_id=nb.id, year_start=YEAR, thread_id="t1") == []
    assert len(records.decisions(nb.id)) == 1


SCREWFIX = """SCREWFIX DIRECT
VAT Reg No GB 232 4155 08
03/10/2026 09:12
Subtotal 72.00
VAT 20"""


def test_use_primary_never_lets_a_receipt_replace_a_bank_line_of_another_amount(mongo_store, records, pages, nb):
    # Ashdown's Screwfix receipt was read at its £72.00 subtotal; the bank paid £86.40. The AI kept the receipt and
    # dropped the bank line, so £14.40 that left the bank vanished from the books and the bank stopped agreeing.
    [receipt] = add(mongo_store, nb.id, pages, "screwfix.txt", SCREWFIX,
                    row(date=dt.date(2026, 10, 3), description="Screwfix", counterparty="Screwfix Direct",
                        gross=Decimal("72.00"), account_code="5000", document_total=Decimal("72.00")))
    line, statement = bank_line(nb, mongo_store, pages, "86.40", dt.date(2026, 10, 3), "SCREWFIX DIRECT")
    decision = call(mongo_store, records, pages, nb, receipt,
                    UsePrimary(action="use_primary", primary_row_id=receipt, other_row_id=line),
                    "Subtotal 72.00", upload=nb.upload("screwfix.txt"))
    assert decision.status == "refused"
    assert decision.reason == ("The bank paid £86.40 and the receipt reads £72.00: what left the bank stays as the "
                               "bank shows it, so the receipt can't replace the bank line.")
    assert not saved(mongo_store, nb.id, line).excluded


# ─── set_date (R1 from another record, the file name or the document) ──────────

CLAIM = """Expenses: Matt Barnes
03/09/2026  EE Mobile Phone Bill  27.50
04/09/2026  EE Mobile Phone Bill  27.50"""


@pytest.fixture
def ee(mongo_store, pages, nb):
    """An undated EE bill of £27.50 whose file name holds no day, and an expenses sheet with two EE lines of £27.50 (3
    and 4 Sep), so matching can't tell which line the bill dates from."""
    [bill] = add(mongo_store, nb.id, pages, "ee-bill.jpg", "EE Limited\nMonthly charges\nTotal £27.50",
                 row(date=None, description="EE monthly charges", counterparty="EE Limited", gross=Decimal("27.50"),
                     account_code="7502", document_type="invoice"))
    third, fourth = add(mongo_store, nb.id, pages, "matt.xlsx", CLAIM, *[
        row(date=dt.date(2026, 9, day), description="EE Mobile Phone Bill", counterparty="Matt Barnes",
            gross=Decimal("27.50"), account_code="7502", document_type="expense_claim", document_ref="matt")
        for day in (3, 4)], kind="table")
    return SimpleNamespace(bill=bill, third=third, fourth=fourth)


def dated(day: int, source=None) -> SetDate:
    return SetDate(action="set_date", date=dt.date(2026, 9, day), source_row_id=source)


def test_an_undated_bill_takes_the_date_of_another_record_of_the_same_purchase(mongo_store, records, pages, nb, ee):
    assert any(i.code == "date_missing" for i in shown(mongo_store, nb.id, ee.bill).issues)
    applied = call(mongo_store, records, pages, nb, ee.bill, dated(4, ee.fourth), "04/09/2026 EE Mobile Phone Bill",
                   upload=nb.upload("matt.xlsx"))
    assert (applied.status, applied.rule) == ("applied", "R1 Date from another record")
    assert applied.after == {str(ee.bill): {"date": "2026-09-04"}}
    assert saved(mongo_store, nb.id, ee.bill).date == dt.date(2026, 9, 4)


def test_a_date_from_a_record_of_another_amount_or_another_day_is_refused(mongo_store, records, pages, nb, ee):
    wrong_day = call(mongo_store, records, pages, nb, ee.bill, dated(5, ee.fourth), "04/09/2026 EE Mobile Phone Bill",
                     upload=nb.upload("matt.xlsx"))
    other_amount = call(mongo_store, records, pages, nb, ee.bill, dated(10, nb.receipt), "COSTCO WHOLESALE")
    assert wrong_day.status == other_amount.status == "refused"
    assert saved(mongo_store, nb.id, ee.bill).date is None


def test_an_undated_document_takes_the_date_in_its_file_name(mongo_store, records, pages, nb):
    # 5 Sep: no claim line that day, so the rules leave the date to the AI, which may take it from the name.
    name = "EE-2026-09-05_00_00_00.jpg"
    [bill] = add(mongo_store, nb.id, pages, name, "EE Limited\nMonthly charges\nTotal £31.00",
                 row(date=None, description="EE monthly charges", counterparty="EE Limited", gross=Decimal("31.00"),
                     account_code="7502", document_type="invoice"))
    refused = call(mongo_store, records, pages, nb, bill, dated(3), name, upload=nb.upload(name))
    assert refused.status == "refused"
    applied = call(mongo_store, records, pages, nb, bill, dated(5), name, upload=nb.upload(name))
    assert applied.status == "applied" and saved(mongo_store, nb.id, bill).date == dt.date(2026, 9, 5)


def test_an_undated_row_takes_a_date_printed_in_its_document(mongo_store, records, pages, nb):
    [bill] = add(mongo_store, nb.id, pages, "hotel.pdf", "Fawsley Hall\nInvoice date 15/09/2026\nTotal £2,308.50",
                 row(date=None, description="Rooms", counterparty="Fawsley Hall", gross=Decimal("2308.50"),
                     account_code="7402", document_type="invoice"))
    cite = dict(upload=nb.upload("hotel.pdf"))
    refused = call(mongo_store, records, pages, nb, bill, dated(15), "Total £2,308.50", **cite)
    assert refused.status == "refused"
    applied = call(mongo_store, records, pages, nb, bill, dated(15), "Invoice date 15/09/2026", **cite)
    assert applied.status == "applied" and saved(mongo_store, nb.id, bill).date == dt.date(2026, 9, 15)


def test_a_row_with_no_question_about_its_date_keeps_it(mongo_store, records, pages, nb):
    refused = call(mongo_store, records, pages, nb, nb.receipt, dated(9), "COSTCO WHOLESALE")
    assert refused.status == "refused" and "date" in refused.reason
    assert saved(mongo_store, nb.id, nb.receipt).date == dt.date(2026, 10, 7)


def test_a_date_read_from_a_receipt_is_not_replaced_by_an_expenses_sheets(mongo_store, records, pages, nb):
    [receipt] = add(mongo_store, nb.id, pages, "staples.txt", "STAPLES 01/10/2026 Total 19.99", row(
        date=dt.date(2026, 10, 1), description="Staples", counterparty="Staples", gross=Decimal("19.99"),
        account_code="7504"))
    [line] = add(mongo_store, nb.id, pages, "sept.xlsx", "20/10/2026 Staples 19.99", row(
        date=dt.date(2026, 10, 20), description="Staples", counterparty="Priya Shah", gross=Decimal("19.99"),
        account_code="7504", document_type="expense_claim", document_ref="sept"), kind="table")
    assert any(i.code == "date_conflict" for i in shown(mongo_store, nb.id, receipt).issues)
    refused = call(mongo_store, records, pages, nb, receipt,
                   SetDate(action="set_date", date=dt.date(2026, 10, 20), source_row_id=line), "20/10/2026 Staples",
                   upload=nb.upload("sept.xlsx"))
    assert refused.status == "refused" and saved(mongo_store, nb.id, receipt).date == dt.date(2026, 10, 1)
    applied = call(mongo_store, records, pages, nb, line,
                   SetDate(action="set_date", date=dt.date(2026, 10, 1), source_row_id=receipt), "STAPLES 01/10/2026",
                   upload=nb.upload("staples.txt"))
    assert applied.status == "applied" and saved(mongo_store, nb.id, line).date == dt.date(2026, 10, 1)


def test_keep_one_keeps_a_revised_invoice_and_drops_the_one_it_replaces(mongo_store, records, pages, nb):
    # The same invoice number at another total: the books say so on the later one, which lets R2 keep it alone.
    revised_text = "ASHDOWN SUPPLIES LTD\nTAX INVOICE A-551 (REVISED - replaces the invoice A-551 dated 10 May 2026)\nTotal 240.00"
    bill = dict(counterparty="Ashdown Supplies Ltd", document_type="invoice", document_number="A-551", account_code="5000")
    [original] = add(mongo_store, nb.id, pages, "a551.txt", "TAX INVOICE A-551\nTotal 360.00", row(
        **bill, date=dt.date(2026, 5, 10), description="Plasterboard x 60", gross=Decimal("360.00"),
        document_total=Decimal("360.00")))
    [revised] = add(mongo_store, nb.id, pages, "a551-revised.txt", revised_text, row(
        **bill, date=dt.date(2026, 5, 12), description="Plasterboard x 40", gross=Decimal("240.00"),
        document_total=Decimal("240.00")))
    decision = call(mongo_store, records, pages, nb, revised,
                    KeepOne(action="keep_one", keep_row_id=revised, drop_row_ids=[original]),
                    "REVISED - replaces the invoice A-551", upload=nb.upload("a551-revised.txt"))
    assert (decision.status, decision.rule) == ("applied", "R2 Duplicate: kept the invoice")
    assert saved(mongo_store, nb.id, original).excluded and not saved(mongo_store, nb.id, revised).excluded


def test_the_date_a_document_prints_settles_another_date_in_its_file_name(mongo_store, records, pages, nb):
    # The rent invoice printed 1 Sep; its file name held another day. The AI "set" the date it already had, which
    # changed nothing and left the question open.
    name = "rent-2026-09-19.pdf"
    [bill] = add(mongo_store, nb.id, pages, name, "Parkside Estates\nInvoice date 01/09/2026\nTotal £900.00",
                 row(date=dt.date(2026, 9, 1), description="Rent", counterparty="Parkside Estates",
                     gross=Decimal("900.00"), account_code="7100", document_type="invoice"))
    asked = lambda: [i.code for r in books.all_rows(mongo_store, nb.id) if r.id == bill for i in r.issues]
    assert "file_date" in asked()
    applied = call(mongo_store, records, pages, nb, bill, dated(1), "Invoice date 01/09/2026", upload=nb.upload(name))
    assert applied.status == "applied" and "file_date" not in asked()
    assert saved(mongo_store, nb.id, bill).date == dt.date(2026, 9, 1)


# ─── Changing a row's account (R6): always a suggestion until a person applies it ───────────────────────────────

USUAL = "The other 11 bills from Vodafone Ltd went to 7502 Telephone and Internet."
DELL = """Dell Corporation Ltd
Invoice 77120   Date 3 November 2026
Latitude 5450 laptop   1500.00
VAT 300.00
Total £1,800.00"""


def to(code: str) -> ChangeAccount:
    return ChangeAccount(action="change_account", account_code=code)


@pytest.fixture
def voda(mongo_store, pages):
    """A client with eleven Vodafone bills on 7502 and one, the odd one, on 7400; a £1,800 Dell invoice on 7504; and
    a £9.67 cable on 0030."""
    store = mongo_store
    client_id = new_client(store, "Harbour Lane Ltd")
    store.update_client(client_id, {"materiality": Decimal("1500")})   # the firm's: trivial £45, so the cable is small
    bills = [row(date=dt.date(2026, 4 + k % 9, 12 + k // 9), description="Vodafone bill", counterparty="Vodafone Ltd",
                 gross=Decimal("86.40"), account_code="7502", document_type="invoice", document_ref=f"v{k}")
             for k in range(11)]
    usual = add(store, client_id, pages, "vodafone.csv", "", *bills, kind="table")
    [odd] = add(store, client_id, pages, "vodafone-march.pdf", "Vodafone   Total 86.40", row(
        date=dt.date(2027, 3, 12), description="Vodafone bill", counterparty="Vodafone Ltd", gross=Decimal("86.40"),
        account_code="7400", document_type="invoice", document_ref="v-odd"))
    [dell] = add(store, client_id, pages, "dell.pdf", DELL, row(
        date=dt.date(2026, 11, 3), description="Dell laptop", counterparty="Dell Corporation Ltd",
        gross=Decimal("1800.00"), vat=Decimal("300.00"), account_code="7504", document_type="invoice",
        alternatives=["0030"],   # the reader saw a laptop: it could be Office Equipment
        document_number="77120", document_total=Decimal("1800.00"), supplier_vat_number="GB123456789"))
    [cable] = add(store, client_id, pages, "cable.txt", "USB cable 9.67", row(
        date=dt.date(2026, 11, 4), description="USB cable", counterparty="Currys", gross=Decimal("9.67"),
        account_code="0030"))
    return SimpleNamespace(id=client_id, usual=usual, odd=odd, dell=dell, cable=cable,
                           upload=lambda name: upload_named(store, client_id, name))


def change(store, records, pages, c, row_id, code, *quotes, upload=None, actor="rules", **kw):
    return resolve(store, records, client_id=c.id, thread_id=None, actor=actor, row_id=row_id, resolution=to(code),
                   evidence=[Evidence(upload_id=upload, quote=q) for q in quotes], reason=USUAL,
                   texts=lambda uid: pages.get(uid, []), **kw)


def account_of(store, client_id: int, row_id: int) -> str:
    return saved(store, client_id, row_id).account_code


def test_the_rules_suggestion_changes_nothing(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.odd, "7502")
    assert (d.status, d.rule, d.action) == ("suggested", "R6 Account changed", "change_account")
    assert d.before == {str(voda.odd): {"account_code": "7400"}}
    assert d.after == {str(voda.odd): {"account_code": "7502"}}
    assert d.resolution == {"action": "change_account", "account_code": "7502"}
    assert account_of(mongo_store, voda.id, voda.odd) == "7400"


def test_an_agent_cannot_apply_an_account_change_either(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.odd, "7502", actor=ACTOR, suggest=False)
    assert d.status == "suggested" and account_of(mongo_store, voda.id, voda.odd) == "7400"


def test_a_person_applies_an_account_change_and_can_undo_it(mongo_store, records, pages, voda):
    locks = ClientLocks()
    d = change(mongo_store, records, pages, voda, voda.odd, "7502")
    made = undo.apply_suggestion(mongo_store, records, locks, client_id=voda.id, decision_id=d.id,
                                 texts=lambda uid: pages.get(uid, []), wait=0)
    assert (made.status, made.actor) == ("applied", "user")
    assert account_of(mongo_store, voda.id, voda.odd) == "7502"
    undo.undo_decision(mongo_store, records, locks, client_id=voda.id, decision_id=made.id, wait=0)
    assert account_of(mongo_store, voda.id, voda.odd) == "7400"


def test_a_person_can_apply_it_to_a_row_they_coded_by_hand(mongo_store, records, pages, voda):
    """The slip this is for: someone picked the wrong account from the list."""
    ledger.change_row(mongo_store, voda.id, voda.odd, RowPatch(account_code="7403"))
    d = change(mongo_store, records, pages, voda, voda.odd, "7502")
    made = undo.apply_suggestion(mongo_store, records, ClientLocks(), client_id=voda.id, decision_id=d.id,
                                 texts=lambda uid: pages.get(uid, []), wait=0)
    assert made.status == "applied" and account_of(mongo_store, voda.id, voda.odd) == "7502"


def test_another_target_than_the_usual_account_is_refused(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.odd, "7600")
    assert d.status == "refused"
    assert d.reason == "The usual account for Vodafone Ltd is 7502 Telephone and Internet."


def test_a_row_nothing_is_said_about_is_refused(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.usual[0], "7400")
    assert (d.status, d.reason) == ("refused", "Nothing says this row is on the wrong account.")


def test_applying_after_the_history_changed_is_refused(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.odd, "7502")
    for row_id in voda.usual:   # the person decides Travel is right after all, and moves the others
        ledger.change_row(mongo_store, voda.id, row_id, RowPatch(account_code="7400"))
    made = undo.apply_suggestion(mongo_store, records, ClientLocks(), client_id=voda.id, decision_id=d.id,
                                 texts=lambda uid: pages.get(uid, []), wait=0)
    assert (made.status, made.reason) == ("refused", "Nothing says this row is on the wrong account.")
    assert account_of(mongo_store, voda.id, voda.odd) == "7400"


def test_an_asset_change_needs_a_quote_from_the_document(mongo_store, records, pages, voda):
    bare = change(mongo_store, records, pages, voda, voda.dell, "0030")
    assert (bare.status, bare.reason) == ("refused", "No evidence was cited.")
    wrong = change(mongo_store, records, pages, voda, voda.dell, "0030", "Macbook Pro", upload=voda.upload("dell.pdf"))
    assert wrong.status == "refused" and "isn't in dell.pdf" in wrong.reason
    d = change(mongo_store, records, pages, voda, voda.dell, "0030", "Latitude 5450 laptop",
               upload=voda.upload("dell.pdf"), actor=ACTOR)
    assert d.status == "suggested" and d.after == {str(voda.dell): {"account_code": "0030"}}


def test_an_asset_change_must_go_to_a_fixed_asset(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.dell, "7800", "Latitude 5450 laptop",
               upload=voda.upload("dell.pdf"))
    assert (d.status, d.reason) == ("refused", "Equipment kept for use goes to 0020 Plant and Machinery, 0030 Office "
                                               "Equipment or 0040 Furniture and Fixtures.")


def test_a_small_asset_goes_to_a_cost_account(mongo_store, records, pages, voda):
    assert change(mongo_store, records, pages, voda, voda.cable, "7504").status == "suggested"
    d = change(mongo_store, records, pages, voda, voda.cable, "0040")
    assert (d.status, d.reason) == ("refused", "A small item goes to a cost account.")


def test_an_account_that_does_not_exist_is_refused(mongo_store, records, pages, voda):
    d = change(mongo_store, records, pages, voda, voda.cable, "7999")
    assert (d.status, d.reason) == ("refused", "7999 isn't an account.")


def test_an_account_change_in_a_closed_year_is_refused(mongo_store, records, pages, voda):
    d0 = change(mongo_store, records, pages, voda, voda.odd, "7502")
    mongo_store.close_year(voda.id, ClosedYear(start=YEAR, end=dt.date(2027, 3, 31), closed_at="2027-04-30T00:00:00",
                                               closing={}))
    made = undo.apply_suggestion(mongo_store, records, ClientLocks(), client_id=voda.id, decision_id=d0.id,
                                 texts=lambda uid: pages.get(uid, []), wait=0)
    assert made.status == "refused" and account_of(mongo_store, voda.id, voda.odd) == "7400"


# ─── The rules suggest the usual account; what waits for a person ──────────────────────────────────────────────

def suggested(store, records, c):
    return suggest_account_changes(store, records, client_id=c.id, year_start=YEAR)


def waiting(store, records, c):
    return waiting_suggestions(store, records, client_id=c.id, year_start=YEAR)


def test_the_rules_suggest_the_usual_account(mongo_store, records, voda):
    [d] = suggested(mongo_store, records, voda)
    assert (d.status, d.actor, d.action, d.row_ids) == ("suggested", "rules", "change_account", [voda.odd])
    assert d.reason == USUAL
    assert d.resolution == {"action": "change_account", "account_code": "7502"}
    assert account_of(mongo_store, voda.id, voda.odd) == "7400"


def test_run_again_the_rules_add_nothing(mongo_store, records, voda):
    suggested(mongo_store, records, voda)
    before = len(records.decisions(voda.id))
    assert suggested(mongo_store, records, voda) == []
    assert len(records.decisions(voda.id)) == before


def test_a_row_coded_by_hand_is_still_suggested(mongo_store, records, voda):
    ledger.change_row(mongo_store, voda.id, voda.odd, RowPatch(account_code="7403"))
    [d] = suggested(mongo_store, records, voda)
    assert d.before == {str(voda.odd): {"account_code": "7403"}}


def test_an_undone_account_change_is_not_suggested_again(mongo_store, records, pages, voda):
    locks = ClientLocks()
    [d] = suggested(mongo_store, records, voda)
    made = undo.apply_suggestion(mongo_store, records, locks, client_id=voda.id, decision_id=d.id,
                                 texts=lambda uid: pages.get(uid, []), wait=0)
    undo.undo_decision(mongo_store, records, locks, client_id=voda.id, decision_id=made.id, wait=0)
    before = len(records.decisions(voda.id))
    for _ in range(3):
        assert suggested(mongo_store, records, voda) == []
    assert len(records.decisions(voda.id)) == before
    assert waiting(mongo_store, records, voda) == []


def test_an_archived_client_gets_no_suggestion(mongo_store, records, voda):
    ledger.change_client(mongo_store, voda.id, ClientPatch(archived=True))
    assert suggested(mongo_store, records, voda) == []
    assert records.decisions(voda.id) == []


def test_a_closed_year_gets_no_suggestion(mongo_store, records, voda):
    mongo_store.close_year(voda.id, ClosedYear(start=YEAR, end=dt.date(2027, 3, 31), closed_at="2027-04-30T00:00:00",
                                               closing={}))
    assert suggested(mongo_store, records, voda) == []
    assert records.decisions(voda.id) == []


def test_what_waits_leaves_out_the_applied_and_the_stale(mongo_store, records, pages, voda):
    [second] = add(mongo_store, voda.id, pages, "vodafone-feb.pdf", "Vodafone   Total 86.40", row(
        date=dt.date(2027, 2, 12), description="Vodafone bill", counterparty="Vodafone Ltd", gross=Decimal("86.40"),
        account_code="7400", document_type="invoice", document_ref="v-odd-2"))
    first, other = sorted(suggested(mongo_store, records, voda), key=lambda d: d.row_ids != [voda.odd])
    assert [d.id for d in waiting(mongo_store, records, voda)] == [first.id, other.id] or \
        {d.id for d in waiting(mongo_store, records, voda)} == {first.id, other.id}
    undo.apply_suggestion(mongo_store, records, ClientLocks(), client_id=voda.id, decision_id=first.id,
                          texts=lambda uid: pages.get(uid, []), wait=0)
    assert [d.id for d in waiting(mongo_store, records, voda)] == [other.id]
    ledger.change_row(mongo_store, voda.id, second, RowPatch(accepted=["unusual_account"]))   # "It's fine"
    assert waiting(mongo_store, records, voda) == []


def test_what_waits_keeps_a_reviews_suggestion(mongo_store, records, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, KeepOne(action="keep_one", keep_row_id=nb.receipt,
             drop_row_ids=[nb.sheet_costco]), "TOTAL  £64.80", trigger="background", review_id="r1", suggest=True)
    assert d.status == "suggested"
    assert [w.id for w in waiting_suggestions(mongo_store, records, client_id=nb.id, year_start=YEAR)] == [d.id]


def test_a_decision_on_a_row_a_person_removed_is_refused(mongo_store, records, staples):
    # A person's Remove is theirs: the AI never drops, keeps or changes such a row.
    mongo_store.patch_row(staples.id, staples.sheet, {"excluded": True, "removed": True})
    decision = staples_call(mongo_store, records, staples, staples.sheet, [staples.sheet])
    assert decision.status == "refused" and f"Row {staples.sheet} was removed by a person." in decision.reason


# ─── who_was_there (R7) ────────────────────────────────────────────────────────

EXCEL = """ExCeL London Hospitality
2 Mocha        8.40
Milk           0.80
Total £9.20
Table: Hall S6 stand"""


def test_who_was_there_settles_a_meal_question_from_the_documents(mongo_store, records, pages, nb, depot):
    [coffees] = add(mongo_store, nb.id, pages, "excel.jpg", EXCEL, row(
        date=dt.date(2026, 10, 22), description="ExCeL London Hospitality, coffee (2 mocha)",
        counterparty="ExCeL London Hospitality", gross=Decimal("9.20"), account_code="7406", people="several"))
    assert "meal_check" in [i.code for i in shown(mongo_store, nb.id, coffees).issues]
    cite = dict(upload=nb.upload("excel.jpg"))
    staff = WhoWasThere(action="who_was_there", present="staff")

    none = call(mongo_store, records, pages, nb, coffees, staff, "Lunch with clients", **cite)
    assert none.status == "refused"   # R0: the quote isn't in the receipt
    toner = call(mongo_store, records, pages, nb, depot, staff, "Toner", upload=nb.upload("depot.pdf"))
    assert toner.status == "refused" and "who was there" in toner.reason

    applied = call(mongo_store, records, pages, nb, coffees, staff, "2 Mocha", "Hall S6 stand", **cite)
    assert applied.status == "applied" and applied.rule.startswith("R7")
    after = shown(mongo_store, nb.id, coffees)
    assert after.account_code == "8206" and "meal_check" not in [i.code for i in after.issues]
