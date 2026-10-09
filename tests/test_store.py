import datetime as dt
import json
import sqlite3
import threading
from contextlib import closing
from decimal import Decimal

import pytest

from ledgersync.checks import issue
from ledgersync.errors import ClientArchived, NotFound, StorageError
from ledgersync.models import ClientFields, Transaction
from ledgersync.store import Store

CUBE = ClientFields(name="Business Cube Ltd", business_type="limited_company", contact_name="Jenny Clarke",
                    contact_email="jenny@businesscube.co.uk")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data" / "ledgersync.db")


def test_the_database_is_created_on_first_use_with_its_schema_version(tmp_path):
    path = tmp_path / "new" / "ledgersync.db"
    store = Store(path)
    assert not path.exists()   # starting the API touches nothing until the database is used
    store.list_clients()
    with closing(sqlite3.connect(path)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert version == 1 and {"clients", "uploads", "rows"} <= tables


def test_a_database_that_cannot_be_opened_is_a_storage_error(tmp_path):
    (tmp_path / "taken").write_text("a file where the folder should be")
    with pytest.raises(StorageError):
        Store(tmp_path / "taken" / "ledgersync.db").list_clients()


def test_a_client_is_saved_and_read_back(store):
    client = store.create_client(CUBE)
    assert store.get_client(client.id) == client
    assert (client.name, client.vat_registered, client.archived, client.contact_phone) == (
        "Business Cube Ltd", True, False, "")


def test_clients_are_listed_by_name_and_archived_ones_apart(store):
    cube = store.create_client(CUBE)
    for name in ("Zeta Ltd", "acme trading"):
        store.create_client(CUBE.model_copy(update={"name": name}))
    assert [c.name for c in store.list_clients()] == ["acme trading", "Business Cube Ltd", "Zeta Ltd"]
    store.update_client(cube.id, {"archived": True})
    assert [c.name for c in store.list_clients()] == ["acme trading", "Zeta Ltd"]
    assert [c.name for c in store.list_clients(archived=True)] == ["Business Cube Ltd"]


def test_an_archived_client_can_only_be_restored(store):
    client = store.update_client(store.create_client(CUBE).id, {"archived": True})
    assert client.archived and client.archived_at
    with pytest.raises(ClientArchived):
        store.update_client(client.id, {"name": "Renamed"})
    assert store.update_client(client.id, {"archived": False}).archived is False


def test_editing_a_client_changes_only_what_is_sent_and_moves_updated(store, monkeypatch):
    client = store.create_client(CUBE)
    monkeypatch.setattr("ledgersync.store._now", lambda: "2030-01-01T00:00:00+00:00")
    changed = store.update_client(client.id, {"contact_phone": "07700 900123", "vat_registered": False})
    assert (changed.contact_phone, changed.vat_registered, changed.name) == ("07700 900123", False, "Business Cube Ltd")
    assert (changed.updated_at, changed.created_at) == ("2030-01-01T00:00:00+00:00", client.created_at)


def test_an_unknown_client_is_not_found(store):
    with pytest.raises(NotFound):
        store.get_client(99)


def bill(**changes) -> Transaction:
    fields = dict(direction="out", gross="72.00", account_code="7502", date=dt.date(2026, 9, 1),
                  description="BT Business, broadband", document_type="invoice", counterparty="BT Business")
    return Transaction(**{**fields, **changes})


def test_an_upload_keeps_its_rows_in_order_and_only_their_inputs(store):
    client = store.create_client(CUBE)
    worked_out = bill(document_ref="bt", document_number="BT-0905", agent="R+R PR Ltd", vat_posted="12.00",
                      net="60.00", owed="72.00", document_net="60.00", not_vat_invoice=True, vat_found="12.00",
                      apart_from=[7],
                      issues=[issue("mixed_items", "One VAT total."), issue("not_booked", "x", "info")])
    upload_id = store.add_upload(client.id, "BT-0905.pdf", "pdf", [worked_out, bill(document_ref="bt", gross="10.00")],
                                 sha256="ab12", model="fake-model", warnings=["Row 3 skipped"])
    first, second = store.rows(client.id)
    assert (first.upload_id, first.tx.gross, second.tx.gross) == (upload_id, Decimal("72.00"), Decimal("10.00"))
    assert (first.tx.vat_posted, first.tx.net, first.tx.owed, first.tx.vat_found) == (None,) * 4   # worked out
    assert (first.tx.document_number, first.tx.agent) == ("BT-0905", "R+R PR Ltd")    # read from the document
    assert (first.tx.document_net, first.tx.not_vat_invoice) == (Decimal("60.00"), True)
    assert first.tx.apart_from == [7]                                   # a person's decision, kept
    assert [i.code for i in first.tx.issues] == ["mixed_items"]                         # the adapter's own check
    [upload] = store.uploads(client.id)
    assert (upload["name"], upload["kind"], upload["sha256"], upload["model"], upload["warnings"],
            upload["row_count"]) == ("BT-0905.pdf", "pdf", "ab12", "fake-model", ["Row 3 skipped"], 2)


def test_a_row_saved_before_totals_were_kept_takes_its_total_from_its_old_warning(store):
    # Rows read before 2026-10-08 kept a document's printed total only in the words of their warning.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "claim.xlsx", "table", [bill(document_ref="claim")])
    old = {**json.loads(_raw(store)), "issues": [{"code": "total_mismatch", "severity": "warning", "message":
           "The rows from this document add up to £994.52 but its total is £1048.52; check the amounts against the "
           "document."}]}
    _raw(store, json.dumps(old))
    [row] = store.rows(client.id)
    assert row.tx.document_total == Decimal("1048.52")


def _raw(store, data=None):
    """The first row's saved JSON, or replaces it: data as an older version of the store wrote it."""
    with sqlite3.connect(store.path) as db:
        if data is None:
            return db.execute("SELECT data FROM rows ORDER BY id LIMIT 1").fetchone()[0]
        db.execute("UPDATE rows SET data = ? WHERE id = (SELECT MIN(id) FROM rows)", (data,))


def test_removing_a_row_removes_only_it_and_an_upload_left_empty(store):
    client = store.create_client(CUBE)
    first_upload = store.add_upload(client.id, "a.pdf", "pdf", [bill(document_ref="a"), bill(document_ref="b")])
    store.add_upload(client.id, "c.pdf", "pdf", [bill(document_ref="c")])
    a, b, c = store.rows(client.id)
    store.delete_row(client.id, a.id)
    assert [r.tx.document_ref for r in store.rows(client.id)] == ["b", "c"]
    store.delete_row(client.id, c.id)
    assert [u["id"] for u in store.uploads(client.id)] == [first_upload]   # c.pdf had nothing left
    with pytest.raises(NotFound):
        store.delete_row(client.id, c.id)


def test_a_row_saved_without_a_document_reference_gets_one(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "Manual entry", "manual", [bill(document_ref=None)])
    assert store.rows(client.id)[0].tx.document_ref


def test_uploads_are_listed_newest_first(store):
    client = store.create_client(CUBE)
    older = store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    newer = store.add_upload(client.id, "b.pdf", "pdf", [bill()])
    assert [u["id"] for u in store.uploads(client.id)] == [newer, older]


def test_removing_an_upload_removes_its_rows_and_nothing_else(store):
    client = store.create_client(CUBE)
    keep = store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    gone = store.add_upload(client.id, "b.pdf", "pdf", [bill(), bill()])
    store.delete_upload(client.id, gone)
    assert [r.upload_id for r in store.rows(client.id)] == [keep]
    with pytest.raises(NotFound):
        store.delete_upload(client.id, gone)


def test_another_clients_rows_and_uploads_are_not_found(store):
    mine, theirs = store.create_client(CUBE), store.create_client(CUBE)
    upload = store.add_upload(theirs.id, "b.pdf", "pdf", [bill()])
    row = store.rows(theirs.id)[0].id
    with pytest.raises(NotFound):
        store.delete_upload(mine.id, upload)
    with pytest.raises(NotFound):
        store.patch_row(mine.id, row, {"include": True})


def test_include_and_document_wide_fields_change_every_row_of_the_document(store):
    client = store.create_client(CUBE)
    quote = dict(document_type="quote", document_ref="q1")
    store.add_upload(client.id, "q.pdf", "pdf", [bill(**quote), bill(**quote, gross="5.00"), bill(document_ref="other")])
    first = store.rows(client.id)[0].id
    store.patch_row(client.id, first, {"include": True, "counterparty": "BT plc", "gross": "70.00"})
    assert [(r.tx.include, r.tx.counterparty, r.tx.gross) for r in store.rows(client.id)] == [
        (True, "BT plc", Decimal("70.00")), (True, "BT plc", Decimal("5.00")), (False, "BT Business", Decimal("72.00"))]


def test_include_on_an_expense_claim_books_only_that_line(store):
    # Ticking "book this line as well" on one line of Jenny's claim ticked all twelve, and each line's receipt was
    # booked twice.
    client = store.create_client(CUBE)
    claim = dict(document_type="expense_claim", document_ref="claim", counterparty="Jenny Hogg")
    store.add_upload(client.id, "claim.xlsx", "table", [bill(**claim), bill(**claim, gross="5.00")])
    first, second = (r.id for r in store.rows(client.id))
    store.patch_row(client.id, second, {"include": True, "counterparty": "J Hogg"})
    assert [(r.tx.include, r.tx.counterparty) for r in store.rows(client.id)] == [(False, "J Hogg"), (True, "J Hogg")]
    store.patch_row(client.id, second, {"include": False})
    assert [r.tx.include for r in store.rows(client.id)] == [False, False]


def test_a_rows_first_edit_keeps_what_it_held_and_revert_brings_the_document_back(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [bill(document_ref="a"), bill(document_ref="a", gross="10.00")])
    first, second = (r.id for r in store.rows(client.id))
    store.patch_row(client.id, first, {"gross": "70.00"})
    store.patch_row(client.id, first, {"account_code": "7504"})
    store.patch_row(client.id, second, {"document_type": "receipt"})   # a whole-document field
    one, two = store.rows(client.id)
    assert (one.tx.gross, one.tx.account_code, one.tx.document_type, two.tx.document_type) == (
        Decimal("70.00"), "7504", "receipt", "receipt")
    assert (one.original["gross"], one.original["account_code"], one.original["document_type"]) == (
        "72.00", "7502", "invoice")
    store.patch_row(client.id, second, {}, revert=True)
    one, two = store.rows(client.id)
    assert (one.tx.gross, one.tx.account_code, one.tx.document_type, one.original) == (
        Decimal("72.00"), "7502", "invoice", None)
    assert (two.tx.document_type, two.original) == ("invoice", None)


def test_a_link_is_not_an_edit(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "s.csv", "table", [bill(document_type="statement")])
    row = store.rows(client.id)[0].id
    store.patch_row(client.id, row, {"link": []})
    [saved] = store.rows(client.id)
    assert (saved.tx.link, saved.original) == ([], None)


def test_saving_rows_moves_the_clients_updated_time(store, monkeypatch):
    client = store.create_client(CUBE)
    monkeypatch.setattr("ledgersync.store._now", lambda: "2030-01-01T00:00:00+00:00")
    store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    assert store.get_client(client.id).updated_at == "2030-01-01T00:00:00+00:00"


def test_jobs_and_people_can_write_at_the_same_time(store):
    # Review focus: a background job saves uploads while a person links a row; neither may fail.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "s.csv", "table", [bill(document_type="statement")])
    row = store.rows(client.id)[0].id
    failures = []

    def save():
        try:
            for _ in range(15):
                store.add_upload(client.id, "s.csv", "table", [bill()])
        except Exception as exc:   # the assertion below reports it
            failures.append(exc)

    def link():
        try:
            for n in range(15):
                store.patch_row(client.id, row, {"link": [] if n % 2 else None})
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=save) for _ in range(3)] + [threading.Thread(target=link)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == [] and len(store.rows(client.id)) == 46


def test_a_persons_edit_clears_the_warnings_from_the_reading_and_revert_brings_them_back(store):
    # Final review #1: a Suspense row recoded by hand still said it went to Suspense, so it stayed in To review.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [bill(account_code="9998",
                                                      issues=[issue("account_not_recognised", "Went to Suspense.")])])
    row = store.rows(client.id)[0].id
    store.patch_row(client.id, row, {"account_code": "7500"})
    assert store.rows(client.id)[0].tx.issues == []
    store.patch_row(client.id, row, {}, revert=True)
    assert [i.code for i in store.rows(client.id)[0].tx.issues] == ["account_not_recognised"]
