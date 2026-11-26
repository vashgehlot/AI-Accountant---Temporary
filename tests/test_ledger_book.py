"""The posted ledger: what each row should post is compared with what is already posted for it, and the difference
is written as reversals and new lines, once, after checking the batch."""
from datetime import date
from decimal import Decimal as D

import pytest
from bson import Decimal128
from pymongo.collection import Collection
from helpers import acme_with_a_non_gbp_row, add_rows, change_stationery_receipt_to, first_row_id, net, row  # noqa: F401

from ledgersync import books, ledger_book
from ledgersync.models import JournalLine, OpeningBalances, OpeningLine
from ledgersync.records import AgentRecords

pytestmark = pytest.mark.mongo

YEAR_1 = date(2025, 4, 1)
ZERO = D("0.00")


@pytest.fixture
def store(mongo_store):
    return mongo_store


@pytest.fixture
def records(mongo_db):
    return AgentRecords(mongo_db)


def stationery():
    """A £60.00 stationery receipt on 1 Jun 2025 showing £10.00 VAT and the supplier's VAT number: VAT reclaimed."""
    return row(date=date(2025, 6, 1), gross=D("60.00"), vat=D("10.00"), account_code="7504",
               supplier_vat_number="GB123456789", counterparty="Ryman")


def travel_line():
    """A £240.00 travel payment on the bank statement with no receipt behind it: held in Suspense."""
    return row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400", document_type="statement",
               counterparty="Trainline")


def entries(records, client_id):
    return list(records.db.ledger_entries.find({"client_id": client_id}).sort("seq", 1))


def lines_of(docs):
    return sorted((d["code"], d["debit"].to_decimal(), d["credit"].to_decimal()) for d in docs)


def counts(records):
    return records.db.ledger_entries.count_documents({}), records.db.posting_batches.count_documents({})


def test_post_writes_balanced_batch_as_decimal128(store, records, acme):
    add_rows(store, acme, stationery())
    result = ledger_book.post(store, records, acme, YEAR_1, decision_ids=["d1"])
    assert result.batch_id and result.problems == []
    assert (result.entries_added, result.reversals_added) == (3, 0)
    assert result.total_debits == result.total_credits == D("60.00")
    docs = entries(records, acme)
    assert all(isinstance(d["debit"], Decimal128) and isinstance(d["credit"], Decimal128) for d in docs)
    assert lines_of(docs) == [("1200", ZERO, D("60.00")), ("2201", D("10.00"), ZERO), ("7504", D("50.00"), ZERO)]
    assert {d["row_id"] for d in docs} == {first_row_id(store, acme)}
    batch = records.db.posting_batches.find_one({"_id": result.batch_id})
    assert batch["decision_ids"] == ["d1"] and batch["year_start"] == "2025-04-01"
    assert all(d["batch_id"] == result.batch_id and d["reverses"] is None for d in docs)
    unique = sorted(i["key"] for i in records.db.posting_batches.index_information().values() if i.get("unique"))
    assert unique == [[("client_id", 1), ("year_start", 1), ("after", 1)],   # batches form one chain
                      [("client_id", 1), ("year_start", 1), ("key", 1)]]


def test_post_twice_posts_nothing_second_time(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0
    again = ledger_book.post(store, records, acme, YEAR_1)
    assert (again.batch_id, again.entries_added, again.reversals_added, again.problems) == (None, 0, 0, [])
    assert counts(records) == (3, 1)


def test_held_payment_posts_to_suspense(store, records, acme):
    add_rows(store, acme, travel_line())
    ledger_book.post(store, records, acme, YEAR_1)
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert (net(tb, "9998"), net(tb, "1200"), net(tb, "7400")) == (D("240.00"), D("-240.00"), 0)
    [item] = tb.suspense
    assert (item.row_id, item.gross, item.needs) == (first_row_id(store, acme), D("240.00"), "receipt_or_invoice")
    assert item.description == "x"


def test_excluding_row_after_post_reverses_it(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"excluded": True})
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 1
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert (result.entries_added, result.reversals_added) == (0, 3)
    docs = entries(records, acme)
    originals = {d["_id"]: d for d in docs if d["reverses"] is None}
    reversals = [d for d in docs if d["reverses"] is not None]
    assert sorted(d["reverses"] for d in reversals) == sorted(originals)
    for d in reversals:   # each swaps its original's debit and credit
        o = originals[d["reverses"]]
        assert (d["code"], d["debit"], d["credit"]) == (o["code"], o["credit"], o["debit"])
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert tb.lines == [] and tb.is_balanced
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0


def test_a_row_put_back_after_being_reversed_posts_again(store, records, acme):
    # The lines it posts the third time are the ones it posted the first: still a new batch.
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"excluded": True})
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"excluded": False})
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.batch_id and (result.entries_added, result.reversals_added) == (3, 0)
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert (net(tb, "7504"), net(tb, "2201"), net(tb, "1200")) == (D("50.00"), D("10.00"), D("-60.00"))


def test_edit_after_post_reverses_once(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    change_stationery_receipt_to(store, acme, D("72.00"))
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 1
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert (result.entries_added, result.reversals_added) == (3, 3)
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id is None
    assert sum(d["reverses"] is not None for d in entries(records, acme)) == 3
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert net(tb, "1200") == D("-72.00") and tb.is_balanced
    assert tb.lines == books.trial_balance(store, acme, YEAR_1).lines


def _line(row_id, code, debit="0.00", credit="0.00"):
    return JournalLine(transaction=row_id, code=code, debit=D(debit), credit=D(credit), description="x")


@pytest.mark.parametrize("wanted,problem", [
    ((("7504", "60.00", "0.00"), ("1200", "0.00", "50.00")), "do not balance"),
    ((("9999", "60.00", "0.00"), ("1200", "0.00", "60.00")), "9999 isn't an account in the chart"),
    ((("7504", "40.00", "0.00"), ("2201", "20.00", "0.00"), ("1200", "0.00", "60.00")), "more than a sixth"),
    ((("7504", "50.00", "0.00"), ("2202", "10.00", "0.00"), ("1200", "0.00", "60.00")), "only on 2200 or 2201"),
])
def test_invalid_batch_writes_nothing(store, records, acme, monkeypatch, wanted, problem):
    add_rows(store, acme, stationery())
    rid = first_row_id(store, acme)
    monkeypatch.setattr(ledger_book, "wanted_journal",
                        lambda *a, **k: {rid: [_line(rid, code, dr, cr) for code, dr, cr in wanted]})
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert (result.batch_id, result.entries_added, result.reversals_added) == (None, 0, 0)
    assert any(problem in p for p in result.problems), result.problems
    assert counts(records) == (0, 0)


def test_no_vat_leg_for_a_client_not_vat_registered(store, records, acme, monkeypatch):
    store.update_client(acme, {"vat_registered": False})
    add_rows(store, acme, stationery())
    rid = first_row_id(store, acme)
    monkeypatch.setattr(ledger_book, "wanted_journal", lambda *a, **k: {rid: [
        _line(rid, "7504", "50.00"), _line(rid, "2201", "10.00"), _line(rid, "1200", credit="60.00")]})
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.batch_id is None and any("isn't VAT registered" in p for p in result.problems)
    assert counts(records) == (0, 0)


def test_a_row_that_needs_fixing_is_left_out_and_the_rest_post(store, records, acme):
    # The agency run: one invoice read as USD 38.31 stopped every posting after May, for the whole year.
    add_rows(store, acme, stationery(), row(date=date(2025, 6, 2), gross=D("50.00"), currency="USD"))
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.batch_id is not None and not result.problems and result.entries_added == 3
    assert len(result.left_out) == 1 and "Read as USD 50.00" in result.left_out[0]
    assert {d["code"] for d in entries(records, acme)} == {"7504", "2201", "1200"}
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0   # the one left can't post until fixed


def test_reverse_charge_vat_rounded_to_the_penny_posts(store, records, acme):
    # The agency run: Tallgrass's $49 a month came to £39.28; its reverse-charge VAT, 20% of that, is £7.856, booked
    # as £7.86, which the check took as more than the fifth it allows, and the whole batch was refused.
    add_rows(store, acme, row(date=date(2025, 9, 15), gross=D("39.28"), account_code="8201", reverse_charge=True,
                              document_type="invoice", counterparty="Tallgrass Metrics Inc.", vat=D("0.00")))
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.batch_id is not None and not result.problems
    assert {d["code"]: d["debit"].to_decimal() for d in entries(records, acme)}.get("2201") == D("7.86")


def test_a_posted_row_that_comes_to_need_fixing_keeps_what_it_posted(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"currency": "USD"})
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.batch_id is None and result.left_out and counts(records) == (3, 1)   # nothing reversed


def test_posted_trial_balance_includes_opening(store, records, acme):
    books.set_opening(store, acme, OpeningBalances(lines=[OpeningLine(code="1200", debit=D("1000.00")),
                                                          OpeningLine(code="3000", credit=D("1000.00"))]))
    add_rows(store, acme, stationery())
    unposted = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert unposted.lines == unposted.opening == books.trial_balance(store, acme, YEAR_1).opening   # the opening alone
    ledger_book.post(store, records, acme, YEAR_1)
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert {l.code: l.debit - l.credit for l in tb.opening} == {"1200": D("1000.00"), "3000": D("-1000.00")}
    assert net(tb, "1200") == D("940.00") and tb.total_debits == tb.total_credits == D("1000.00")
    assert tb.suspense == [] and len(tb.journal) == 3
    assert tb.lines == books.trial_balance(store, acme, YEAR_1).lines


YEAR_2 = date(2026, 4, 1)


def test_a_payment_no_longer_held_stays_in_suspense_until_posted(store, records, acme):
    add_rows(store, acme, travel_line())
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"document_type": "receipt"})   # a receipt under £250: books
    [item] = ledger_book.posted_trial_balance(store, records, acme, YEAR_1).suspense
    assert (item.gross, item.needs, item.description) == (D("240.00"), None, "x")
    ledger_book.post(store, records, acme, YEAR_1)
    assert ledger_book.posted_trial_balance(store, records, acme, YEAR_1).suspense == []


def test_two_posts_from_the_same_state_write_one_batch(store, records, acme, monkeypatch):
    # Both postings read the ledger after the first batch; the first to write wins and the other writes nothing.
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    change_stationery_receipt_to(store, acme, D("72.00"))
    stale = ledger_book._posted(records.db, acme, YEAR_1)
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id
    change_stationery_receipt_to(store, acme, D("80.00"))
    monkeypatch.setattr(ledger_book, "_posted", lambda *a: stale)
    late = ledger_book.post(store, records, acme, YEAR_1)
    assert (late.batch_id, late.entries_added, late.reversals_added) == (None, 0, 0)
    assert counts(records) == (9, 2)
    monkeypatch.undo()
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert net(tb, "1200") == D("-80.00") and tb.is_balanced


def test_a_line_reversed_already_cannot_be_reversed_again(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    store.patch_row(acme, first_row_id(store, acme), {"excluded": True})
    ledger_book.post(store, records, acme, YEAR_1)
    posted = ledger_book._posted(records.db, acme, YEAR_1)
    original, reversal = posted.entries[0], posted.entries[3]
    again = [dict(row_id=d["row_id"], code=d["code"], description="x", debit=d["credit"], credit=d["debit"],
                  reverses=d["_id"]) for d in (original, reversal)]
    problems = ledger_book._problems(again, {}, True, posted)
    assert any("already reversed" in p for p in problems) and any("is itself a reversal" in p for p in problems)


def test_a_failed_entries_write_takes_back_only_its_own_batch(store, records, acme, monkeypatch):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    change_stationery_receipt_to(store, acme, D("72.00"))

    def half_written(self, docs, *a, **k):   # writes the first entry, then the connection drops
        self.insert_one(docs[0])
        raise ConnectionError("lost")

    monkeypatch.setattr(Collection, "insert_many", half_written)
    with pytest.raises(ConnectionError):
        ledger_book.post(store, records, acme, YEAR_1)
    monkeypatch.undo()
    assert counts(records) == (3, 1)
    assert all(d["reverses"] is None for d in entries(records, acme))
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 1


def test_the_posted_trial_balance_shows_while_rows_need_fixing(store, records, acme):
    add_rows(store, acme, stationery())
    ledger_book.post(store, records, acme, YEAR_1)
    add_rows(store, acme, row(date=date(2025, 6, 2), gross=D("50.00"), currency="USD"))   # needs converting
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert (net(tb, "7504"), net(tb, "1200")) == (D("50.00"), D("-60.00")) and tb.problems
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0   # the one row needing fixing can't post
    later = ledger_book.posted_trial_balance(store, records, acme, YEAR_2)   # its opening can't be worked out
    assert later.lines == [] and later.problems and later.problems[0].startswith("Fix the earlier years first")


STILL_WRITING = "Another posting is still being written; try again."


@pytest.mark.parametrize("after_first", [True, False])
def test_a_posting_still_being_written_stops_the_next(store, records, acme, after_first):
    # A batch whose entries haven't all landed is the end of the chain: posting after it would miss its lines.
    add_rows(store, acme, stationery())
    after = ledger_book.post(store, records, acme, YEAR_1).batch_id if after_first else None
    if after_first:
        change_stationery_receipt_to(store, acme, D("72.00"))
    before = counts(records)
    records.db.posting_batches.insert_one({"_id": "writing", "client_id": acme, "year_start": "2025-04-01",
                                           "key": "k", "after": after, "entries": 3, "reversals": 3 * after_first})
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert (result.batch_id, result.entries_added, result.problems) == (None, 0, [STILL_WRITING])
    assert counts(records) == (before[0], before[1] + 1)
    ledger_book.posted_trial_balance(store, records, acme, YEAR_1)   # still reads what is there
    ledger_book.unposted_changes(store, records, acme, YEAR_1)


def test_two_first_posts_write_one_batch(store, records, acme, monkeypatch):
    add_rows(store, acme, stationery())
    stale = ledger_book._posted(records.db, acme, YEAR_1)   # nothing posted yet
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id
    change_stationery_receipt_to(store, acme, D("72.00"))   # so the late one's lines differ from the first's
    monkeypatch.setattr(ledger_book, "_posted", lambda *a: stale)
    late = ledger_book.post(store, records, acme, YEAR_1)
    assert (late.batch_id, late.entries_added) == (None, 0)
    assert counts(records) == (3, 1)


def test_a_wanted_amount_finer_than_a_penny_is_not_a_change_forever(store, records, acme, monkeypatch):
    add_rows(store, acme, stationery())
    rid = first_row_id(store, acme)
    monkeypatch.setattr(ledger_book, "wanted_journal", lambda *a, **k: {rid: [
        _line(rid, "7504", "50.004"), _line(rid, "2201", "10.00"), _line(rid, "1200", credit="60.004")]})
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0
    assert ledger_book.post(store, records, acme, YEAR_1).batch_id is None


def test_a_cis_sale_posts_the_tax_withheld_to_cis_deducted(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 9, 20), direction="in", gross=D("3400.00"), account_code="4000",
                              document_type="invoice", counterparty="Fenwick Builders Ltd", cis_deducted=D("600.00")))
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.problems == []
    assert lines_of(entries(records, acme)) == [("1100", D("3400.00"), ZERO), ("1104", D("600.00"), ZERO),
                                                ("4000", ZERO, D("4000.00"))]
