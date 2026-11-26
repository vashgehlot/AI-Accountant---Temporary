import datetime as dt
import threading
from decimal import Decimal

import pytest
from pymongo import MongoClient

from ledgersync.checks import issue
from ledgersync.errors import ChangedMeanwhile, ClientArchived, LedgerSyncError, NotFound
from ledgersync.models import ClientFields, OpeningBalances, OpeningLine, OpenItem, Transaction
from ledgersync.store_mongo import MongoStore, _new_client

pytestmark = pytest.mark.mongo

CUBE = ClientFields(name="Business Cube Ltd", business_type="limited_company", contact_name="Jenny Clarke",
                    contact_email="jenny@businesscube.co.uk", first_year_end=dt.date(2027, 3, 31))
ROW = Transaction(date=dt.date(2026, 9, 1), description="BT Business Broadband", direction="out",
                  gross=Decimal("72.00"), account_code="7502")


class SpyClient:
    """Stands in for a MongoClient and records whether it was closed."""
    def __init__(self):
        self.closed = False

    def __getitem__(self, name):
        return MongoClient("mongodb://localhost:1", connect=False)[name]

    def close(self):
        self.closed = True


def test_store_uses_given_client_and_does_not_close_it(monkeypatch):
    spy = SpyClient()
    monkeypatch.setattr(MongoStore, "_init_indexes", lambda self: None)
    store = MongoStore("unused", "x", client=spy)
    store.close()
    assert store.client is spy and not spy.closed


def test_store_closes_the_client_it_opened(monkeypatch):
    spy = SpyClient()
    monkeypatch.setattr("ledgersync.store_mongo._new_client", lambda uri, max_pool: spy)
    monkeypatch.setattr(MongoStore, "_init_indexes", lambda self: None)
    store = MongoStore("mongodb://localhost:1", "x")
    store.close()
    assert store.client is spy and spy.closed


def test_store_default_pool_is_small():
    # __init__ creates indexes (it connects), so the pool is checked on the helper the store builds its client with.
    client = _new_client("mongodb://localhost:1", 7)
    try:
        pool = client.options.pool_options
        assert pool.max_pool_size == 7 and pool.min_pool_size == 0 and pool.max_idle_time_seconds == 60
    finally:
        client.close()


def test_revision_survives_a_new_store_on_the_same_database(mongo_store, mongo_client):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW])
    again = MongoStore(mongo_store.uri, mongo_store.db_name, client=mongo_client)
    assert again.revision(client.id) == mongo_store.revision(client.id) > 0


def test_every_write_moves_the_revision(mongo_store):
    client = mongo_store.create_client(CUBE)
    seen = [mongo_store.revision(client.id)]
    upload_id = mongo_store.add_upload(client.id, "a.csv", "table", [ROW]); seen.append(mongo_store.revision(client.id))
    row_id = mongo_store.rows(client.id)[0].id
    mongo_store.patch_row(client.id, row_id, {"account_code": "7500"}); seen.append(mongo_store.revision(client.id))
    mongo_store.delete_upload(client.id, upload_id); seen.append(mongo_store.revision(client.id))
    assert seen == sorted(set(seen))


def test_client_edits_and_row_deletes_move_the_revision(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW])
    before = mongo_store.revision(client.id)
    mongo_store.update_client(client.id, {"contact_name": "Jo"})
    after_edit = mongo_store.revision(client.id)
    mongo_store.delete_row(client.id, mongo_store.rows(client.id)[0].id)
    assert before < after_edit < mongo_store.revision(client.id)


def test_money_is_saved_as_an_exact_string(mongo_store, mongo_db):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW])
    saved = mongo_db.clients.find_one({"id": client.id})["rows"][0]["data"]
    assert saved["gross"] == "72.00"


class Interleaved:
    """The store's database with a clients collection that runs `meanwhile` just after patch_row reads the rows
    (its find_one on "rows.id"), as another writer would. `times` says for how many reads."""

    def __init__(self, db, meanwhile, times=1):
        self._db, self._meanwhile, self._left = db, meanwhile, times
        self.clients = self

    def find_one(self, query, *args, **kwargs):
        doc = self._db.clients.find_one(query, *args, **kwargs)
        if "rows.id" in query and self._left:
            self._left -= 1
            self._meanwhile()
        return doc

    def __getattr__(self, name):   # everything else goes to the real collection, or the real database
        return getattr(self._db.clients, name) if name in ("update_one", "find_one_and_update", "aggregate", "find") \
            else getattr(self._db, name)


def test_a_row_change_never_loses_rows_another_writer_added_meanwhile(mongo_store, mongo_client):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW])
    row_id = mongo_store.rows(client.id)[0].id
    other = MongoStore(mongo_store.uri, mongo_store.db_name, client=mongo_client)   # the client's upload, saved by another thread
    mongo_store.db = Interleaved(mongo_store.db, lambda: other.add_upload(client.id, "b.csv", "table", [ROW, ROW]))
    mongo_store.patch_row(client.id, row_id, {"account_code": "7500"})
    rows = other.rows(client.id)
    assert len(rows) == 3
    assert [r.tx.account_code for r in rows if r.id == row_id] == ["7500"]


def test_a_row_change_that_keeps_losing_the_race_asks_the_person_to_try_again(mongo_store, mongo_client):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW])
    row_id = mongo_store.rows(client.id)[0].id
    other = MongoStore(mongo_store.uri, mongo_store.db_name, client=mongo_client)
    mongo_store.db = Interleaved(mongo_store.db, lambda: other.add_upload(client.id, "b.csv", "table", [ROW]), times=5)
    with pytest.raises(LedgerSyncError, match="Try again"):
        mongo_store.patch_row(client.id, row_id, {"account_code": "7500"})
    assert len(other.rows(client.id)) == 6
    assert all(r.tx.account_code == "7502" for r in other.rows(client.id))


def test_a_client_is_saved_and_read_back(mongo_store):
    client = mongo_store.create_client(CUBE)
    assert mongo_store.get_client(client.id) == client
    assert (client.name, client.vat_registered, client.archived, client.contact_phone) == (
        "Business Cube Ltd", True, False, "")


def test_clients_are_listed_by_name_and_archived_ones_apart(mongo_store):
    cube = mongo_store.create_client(CUBE)
    for name in ("Zeta Ltd", "acme trading"):
        mongo_store.create_client(CUBE.model_copy(update={"name": name}))
    assert [c.name for c in mongo_store.list_clients()] == ["acme trading", "Business Cube Ltd", "Zeta Ltd"]
    mongo_store.update_client(cube.id, {"archived": True})
    assert [c.name for c in mongo_store.list_clients()] == ["acme trading", "Zeta Ltd"]
    assert [c.name for c in mongo_store.list_clients(archived=True)] == ["Business Cube Ltd"]


def test_an_archived_client_can_only_be_restored(mongo_store):
    client = mongo_store.update_client(mongo_store.create_client(CUBE).id, {"archived": True})
    assert client.archived and client.archived_at
    with pytest.raises(ClientArchived):
        mongo_store.update_client(client.id, {"name": "Renamed"})
    assert mongo_store.update_client(client.id, {"archived": False}).archived is False


def test_editing_a_client_changes_only_what_is_sent_and_moves_updated(mongo_store, monkeypatch):
    client = mongo_store.create_client(CUBE)
    monkeypatch.setattr("ledgersync.store_mongo.now_iso", lambda: "2030-01-01T00:00:00+00:00")
    changed = mongo_store.update_client(client.id, {"contact_phone": "07700 900123", "vat_registered": False})
    assert (changed.contact_phone, changed.vat_registered, changed.name) == ("07700 900123", False, "Business Cube Ltd")
    assert (changed.updated_at, changed.created_at) == ("2030-01-01T00:00:00+00:00", client.created_at)


def test_an_unknown_client_is_not_found(mongo_store):
    with pytest.raises(NotFound):
        mongo_store.get_client(99)


def bill(**changes) -> Transaction:
    fields = dict(direction="out", gross="72.00", account_code="7502", date=dt.date(2026, 9, 1),
                  description="BT Business, broadband", document_type="invoice", counterparty="BT Business")
    return Transaction(**{**fields, **changes})


def test_an_upload_keeps_its_rows_in_order_and_only_their_inputs(mongo_store):
    client = mongo_store.create_client(CUBE)
    worked_out = bill(document_ref="bt", document_number="BT-0905", agent="R+R PR Ltd", vat_posted="12.00",
                      net="60.00", owed="72.00", document_net="60.00", not_vat_invoice=True, vat_found="12.00",
                      apart_from=[7],
                      issues=[issue("mixed_items", "One VAT total."), issue("not_booked", "x", "info")])
    upload_id = mongo_store.add_upload(client.id, "BT-0905.pdf", "pdf", [worked_out, bill(document_ref="bt", gross="10.00")],
                                 sha256="ab12", model="fake-model", warnings=["Row 3 skipped"])
    first, second = mongo_store.rows(client.id)
    assert (first.upload_id, first.tx.gross, second.tx.gross) == (upload_id, Decimal("72.00"), Decimal("10.00"))
    assert (first.tx.vat_posted, first.tx.net, first.tx.owed, first.tx.vat_found) == (None,) * 4   # worked out
    assert (first.tx.document_number, first.tx.agent) == ("BT-0905", "R+R PR Ltd")    # read from the document
    assert (first.tx.document_net, first.tx.not_vat_invoice) == (Decimal("60.00"), True)
    assert first.tx.apart_from == [7]                                   # a person's decision, kept
    assert [i.code for i in first.tx.issues] == ["mixed_items"]                         # the adapter's own check
    [upload] = mongo_store.uploads(client.id)
    assert (upload["name"], upload["kind"], upload["sha256"], upload["model"], upload["warnings"],
            upload["row_count"]) == ("BT-0905.pdf", "pdf", "ab12", "fake-model", ["Row 3 skipped"], 2)


def test_what_a_decision_set_and_the_suppliers_vat_number_are_kept(mongo_store):
    client = mongo_store.create_client(CUBE)
    decided = bill(excluded=True, superseded_by="d2", decision_ids=["d1", "d2"], supplier_vat_number="GB123456789")
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [decided])
    [stored] = mongo_store.rows(client.id)
    assert (stored.tx.excluded, stored.tx.superseded_by, stored.tx.decision_ids, stored.tx.supplier_vat_number) == (
        True, "d2", ["d1", "d2"], "GB123456789")


def test_a_row_saved_before_totals_were_kept_takes_its_total_from_its_old_warning(mongo_store):
    # Rows read before 2026-10-08 kept a document's printed total only in the words of their warning.
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "claim.xlsx", "table", [bill(document_ref="claim")])
    old = {**_raw(mongo_store), "issues": [{"code": "total_mismatch", "severity": "warning", "message":
           "The rows from this document add up to £994.52 but its total is £1048.52; check the amounts against the "
           "document."}]}
    _raw(mongo_store, old)
    [row] = mongo_store.rows(client.id)
    assert row.tx.document_total == Decimal("1048.52")


def _raw(mongo_store, data=None):
    """The first row's saved JSON, or replaces it: data as an older version of the store wrote it."""
    [doc] = mongo_store.db.clients.find({}, {"rows": 1})
    if data is None:
        return doc["rows"][0]["data"]
    mongo_store.db.clients.update_one({"_id": doc["_id"]}, {"$set": {"rows.0.data": data}})


def test_removing_a_row_removes_only_it_and_an_upload_left_empty(mongo_store):
    client = mongo_store.create_client(CUBE)
    first_upload = mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill(document_ref="a"), bill(document_ref="b")])
    mongo_store.add_upload(client.id, "c.pdf", "pdf", [bill(document_ref="c")])
    a, b, c = mongo_store.rows(client.id)
    mongo_store.delete_row(client.id, a.id)
    assert [r.tx.document_ref for r in mongo_store.rows(client.id)] == ["b", "c"]
    mongo_store.delete_row(client.id, c.id)
    assert [u["id"] for u in mongo_store.uploads(client.id)] == [first_upload]   # c.pdf had nothing left
    with pytest.raises(NotFound):
        mongo_store.delete_row(client.id, c.id)


def test_a_row_saved_without_a_document_reference_gets_one(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "Manual entry", "manual", [bill(document_ref=None)])
    assert mongo_store.rows(client.id)[0].tx.document_ref


def test_uploads_are_listed_newest_first(mongo_store):
    client = mongo_store.create_client(CUBE)
    older = mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    newer = mongo_store.add_upload(client.id, "b.pdf", "pdf", [bill()])
    assert [u["id"] for u in mongo_store.uploads(client.id)] == [newer, older]


def test_removing_an_upload_removes_its_rows_and_nothing_else(mongo_store):
    client = mongo_store.create_client(CUBE)
    keep = mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    gone = mongo_store.add_upload(client.id, "b.pdf", "pdf", [bill(), bill()])
    mongo_store.delete_upload(client.id, gone)
    assert [r.upload_id for r in mongo_store.rows(client.id)] == [keep]
    with pytest.raises(NotFound):
        mongo_store.delete_upload(client.id, gone)


def test_another_clients_rows_and_uploads_are_not_found(mongo_store):
    mine, theirs = mongo_store.create_client(CUBE), mongo_store.create_client(CUBE)
    upload = mongo_store.add_upload(theirs.id, "b.pdf", "pdf", [bill()])
    row = mongo_store.rows(theirs.id)[0].id
    with pytest.raises(NotFound):
        mongo_store.delete_upload(mine.id, upload)
    with pytest.raises(NotFound):
        mongo_store.patch_row(mine.id, row, {"include": True})


def test_include_and_document_wide_fields_change_every_row_of_the_document(mongo_store):
    client = mongo_store.create_client(CUBE)
    quote = dict(document_type="quote", document_ref="q1")
    mongo_store.add_upload(client.id, "q.pdf", "pdf", [bill(**quote), bill(**quote, gross="5.00"), bill(document_ref="other")])
    first = mongo_store.rows(client.id)[0].id
    mongo_store.patch_row(client.id, first, {"include": True, "counterparty": "BT plc", "gross": "70.00"})
    assert [(r.tx.include, r.tx.counterparty, r.tx.gross) for r in mongo_store.rows(client.id)] == [
        (True, "BT plc", Decimal("70.00")), (True, "BT plc", Decimal("5.00")), (False, "BT Business", Decimal("72.00"))]


def test_include_on_an_expense_claim_books_only_that_line(mongo_store):
    # Ticking "book this line as well" on one line of Jenny's claim ticked all twelve, and each line's receipt was
    # booked twice.
    client = mongo_store.create_client(CUBE)
    claim = dict(document_type="expense_claim", document_ref="claim", counterparty="Jenny Hogg")
    mongo_store.add_upload(client.id, "claim.xlsx", "table", [bill(**claim), bill(**claim, gross="5.00")])
    first, second = (r.id for r in mongo_store.rows(client.id))
    mongo_store.patch_row(client.id, second, {"include": True, "counterparty": "J Hogg"})
    assert [(r.tx.include, r.tx.counterparty) for r in mongo_store.rows(client.id)] == [(False, "J Hogg"), (True, "J Hogg")]
    mongo_store.patch_row(client.id, second, {"include": False})
    assert [r.tx.include for r in mongo_store.rows(client.id)] == [False, False]


def test_a_rows_first_edit_keeps_what_it_held_and_revert_brings_the_document_back(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill(document_ref="a"), bill(document_ref="a", gross="10.00")])
    first, second = (r.id for r in mongo_store.rows(client.id))
    mongo_store.patch_row(client.id, first, {"gross": "70.00"})
    mongo_store.patch_row(client.id, first, {"account_code": "7504"})
    mongo_store.patch_row(client.id, second, {"document_type": "receipt"})   # a whole-document field
    one, two = mongo_store.rows(client.id)
    assert (one.tx.gross, one.tx.account_code, one.tx.document_type, two.tx.document_type) == (
        Decimal("70.00"), "7504", "receipt", "receipt")
    assert (one.original["gross"], one.original["account_code"], one.original["document_type"]) == (
        "72.00", "7502", "invoice")
    mongo_store.patch_row(client.id, second, {}, revert=True)
    one, two = mongo_store.rows(client.id)
    assert (one.tx.gross, one.tx.account_code, one.tx.document_type, one.original) == (
        Decimal("72.00"), "7502", "invoice", None)
    assert (two.tx.document_type, two.original) == ("invoice", None)


def test_a_link_is_not_an_edit(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "s.csv", "table", [bill(document_type="statement")])
    row = mongo_store.rows(client.id)[0].id
    mongo_store.patch_row(client.id, row, {"link": []})
    [saved] = mongo_store.rows(client.id)
    assert (saved.tx.link, saved.original) == ([], None)


def test_saving_rows_moves_the_clients_updated_time(mongo_store, monkeypatch):
    client = mongo_store.create_client(CUBE)
    monkeypatch.setattr("ledgersync.store_mongo.now_iso", lambda: "2030-01-01T00:00:00+00:00")
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill()])
    assert mongo_store.get_client(client.id).updated_at == "2030-01-01T00:00:00+00:00"


def test_jobs_and_people_can_write_at_the_same_time(mongo_store):
    # Review focus: a background job saves uploads while a person links a row; no row is lost and nothing fails
    # but a change that is asked to be tried again.
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "s.csv", "table", [bill(document_type="statement")])
    row = mongo_store.rows(client.id)[0].id
    failures = []

    def save():
        try:
            for _ in range(15):
                mongo_store.add_upload(client.id, "s.csv", "table", [bill()])
        except Exception as exc:   # the assertion below reports it
            failures.append(exc)

    def link():
        try:
            for n in range(15):
                while True:
                    try:
                        mongo_store.patch_row(client.id, row, {"link": [] if n % 2 else None})
                        break
                    except ChangedMeanwhile:   # lost five races to the saves: the person tries again
                        pass
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=save) for _ in range(3)] + [threading.Thread(target=link)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == [] and len(mongo_store.rows(client.id)) == 46


def test_a_persons_edit_clears_the_warnings_from_the_reading_and_revert_brings_them_back(mongo_store):
    # Final review #1: a Suspense row recoded by hand still said it went to Suspense, so it stayed in To review.
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [bill(account_code="9998",
                                                      issues=[issue("account_not_recognised", "Went to Suspense.")])])
    row = mongo_store.rows(client.id)[0].id
    mongo_store.patch_row(client.id, row, {"account_code": "7500"})
    assert mongo_store.rows(client.id)[0].tx.issues == []
    mongo_store.patch_row(client.id, row, {}, revert=True)
    assert [i.code for i in mongo_store.rows(client.id)[0].tx.issues] == ["account_not_recognised"]


# ─── Years and opening balances ──────────────────────────────────────────────

def test_a_client_keeps_its_first_year_end_and_opening_balances(mongo_store):
    client = mongo_store.create_client(CUBE)
    assert mongo_store.get_client(client.id).first_year_end == dt.date(2027, 3, 31)
    assert mongo_store.opening(client.id) == OpeningBalances()
    opening = OpeningBalances(lines=[OpeningLine(code="1100", debit="10.00"), OpeningLine(code="3200", credit="10.00")],
                              unpaid=[OpenItem(id="1", direction="in", counterparty="Bright Cafe", amount="10.00",
                                               number="INV-7", date=dt.date(2026, 3, 2))])
    mongo_store.set_opening(client.id, opening)
    assert mongo_store.opening(client.id) == opening
    changed = mongo_store.update_client(client.id, {"first_year_end": dt.date(2026, 12, 31)})
    assert changed.first_year_end == mongo_store.get_client(client.id).first_year_end == dt.date(2026, 12, 31)


def test_an_upload_keeps_the_year_it_was_added_to(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW], year_start=dt.date(2026, 4, 1))
    mongo_store.add_upload(client.id, "b.csv", "table", [ROW])
    assert [u["year_start"] for u in mongo_store.uploads(client.id)] == [None, dt.date(2026, 4, 1)]


def test_a_client_saved_before_year_ends_reads_with_the_31_march_after_its_earliest_row(mongo_store):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.csv", "table", [ROW, ROW.model_copy(update={"date": dt.date(2025, 2, 3)})])
    mongo_store.db.clients.update_one({"id": client.id}, {"$unset": {"first_year_end": "", "opening": ""}})
    assert mongo_store.get_client(client.id).first_year_end == dt.date(2025, 3, 31)
    assert mongo_store.opening(client.id) == OpeningBalances()


def test_the_whole_client_is_read_in_one_go_as_its_parts_are_read_alone(mongo_store):
    # A calculation that needs the client, its rows, its uploads and its opening balances reads them together: one
    # round trip to the database instead of four, and one moment of the client.
    store = mongo_store
    client = store.create_client(CUBE)
    store.set_opening(client.id, OpeningBalances(lines=[OpeningLine(code="1200", debit=Decimal("50.00")),
                                                        OpeningLine(code="3000", credit=Decimal("50.00"))]))
    store.add_upload(client.id, "a.pdf", "pdf", [ROW, ROW.model_copy(update={"description": "Second"})],
                     sha256="abc", warnings=["Row 3 skipped."])
    store.add_upload(client.id, "empty.pdf", "pdf", [])
    store.patch_row(client.id, store.rows(client.id)[0].id, {"gross": "80.00"})   # keeps what was first read
    found, rows, uploads, opening = store.whole(client.id)
    assert found == store.get_client(client.id)
    assert rows == store.rows(client.id) and rows[0].original["gross"] == "72.00"
    assert uploads == store.uploads(client.id) and [u["row_count"] for u in uploads] == [0, 2]
    assert opening == store.opening(client.id)
    with pytest.raises(NotFound):
        store.whole(client.id + 1)


def test_the_whole_of_a_client_saved_without_a_first_year_end_reads_as_get_client_does(mongo_store):
    store = mongo_store
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [ROW])
    store.db.clients.update_one({"id": client.id}, {"$set": {"first_year_end": None}})   # as old data was saved
    assert store.whole(client.id)[0] == store.get_client(client.id)
    assert store.whole(client.id)[0].first_year_end == dt.date(2027, 3, 31)   # the 31 March on or after its row


# ─── Reading a client once for several calculations ────────────────────────────

@pytest.fixture
def reads(monkeypatch):
    """The reads of the clients collection, as they are made: each is a round trip to the database."""
    from pymongo.collection import Collection
    made = []
    for name in ("find", "aggregate"):
        real = getattr(Collection, name)
        monkeypatch.setattr(Collection, name, lambda self, *a, _real=real, _name=name, **k: (
            made.append(_name) if self.name == "clients" else None) or _real(self, *a, **k))
    return made


def test_inside_a_reading_block_the_client_is_fetched_once_however_it_is_read(mongo_store, reads):
    store = mongo_store
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [ROW], sha256="abc")
    alone = (store.get_client(client.id), store.rows(client.id), store.uploads(client.id), store.opening(client.id),
             store.revision(client.id))
    reads.clear()
    with store.reading():
        together = (store.get_client(client.id), store.rows(client.id), store.uploads(client.id),
                    store.opening(client.id), store.revision(client.id))
        assert store.whole(client.id) == alone[:4]
        with store.reading():   # a block inside a block shares the copy
            assert store.rows(client.id) == alone[1]
    assert together == alone and reads == ["find"]
    reads.clear()
    store.get_client(client.id), store.rows(client.id)   # outside a block every read asks the database, as before
    assert reads == ["find", "find"]


def test_a_write_inside_a_reading_block_is_seen_by_the_next_read(mongo_store):
    store = mongo_store
    client = store.create_client(CUBE)
    with store.reading():
        assert store.rows(client.id) == []
        upload_id = store.add_upload(client.id, "a.pdf", "pdf", [ROW, ROW])
        first, second = store.rows(client.id)
        assert [u["row_count"] for u in store.uploads(client.id)] == [2]
        store.patch_row(client.id, first.id, {"gross": "80.00"})
        assert store.rows(client.id)[0].tx.gross == Decimal("80.00")
        store.put_row_data(client.id, {second.id: {**store.row_data(client.id, [second.id])[second.id],
                                                   "description": "Put back"}})
        assert store.rows(client.id)[1].tx.description == "Put back"
        store.add_split(client.id, second.id, [ROW], "d1")
        assert len(store.rows(client.id)) == 3 and len(store.uploads(client.id)) == 2
        store.delete_row(client.id, first.id)
        assert [r.id for r in store.rows(client.id)][0] == second.id
        store.set_upload_bank(client.id, upload_id, "1210")
        assert store.uploads(client.id)[-1]["bank_account"] == "1210"
        store.set_opening(client.id, OpeningBalances(lines=[OpeningLine(code="1200", debit=Decimal("5.00")),
                                                            OpeningLine(code="3000", credit=Decimal("5.00"))]))
        assert store.opening(client.id).lines[0].debit == Decimal("5.00")
        assert store.update_client(client.id, {"contact_name": "Sam"}).contact_name == "Sam"
        assert store.get_client(client.id).contact_name == "Sam"
        kept = store.raw_rows(client.id, [second.id])
        store.delete_upload(client.id, upload_id)
        assert [r.id for r in store.rows(client.id)] != [second.id]
        store.restore_rows(client.id, *kept)
        assert second.id in [r.id for r in store.rows(client.id)]
        before = store.revision(client.id)
        store.update_client(client.id, {"archived": True})
        assert store.get_client(client.id).archived and store.revision(client.id) == before + 1


def test_a_write_from_another_thread_is_seen_inside_a_reading_block(mongo_store):
    store = mongo_store
    client = store.create_client(CUBE)
    with store.reading():
        assert store.rows(client.id) == []
        writer = threading.Thread(target=store.add_upload, args=(client.id, "a.pdf", "pdf", [ROW]))
        writer.start()
        writer.join()
        assert len(store.rows(client.id)) == 1


def test_a_client_that_is_not_there_is_not_found_inside_a_reading_block_either(mongo_store):
    with mongo_store.reading():
        for read in (mongo_store.get_client, mongo_store.rows, mongo_store.uploads, mongo_store.opening,
                     mongo_store.whole):
            with pytest.raises(NotFound):
                read(999)
        assert mongo_store.revision(999) == 0
        created = mongo_store.create_client(CUBE)   # a client made inside the block is found
        assert mongo_store.get_client(created.id).name == CUBE.name
