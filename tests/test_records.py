"""The agent's records: decisions (append-only, hash-chained, idempotent), questions, chat threads and cached
document texts, and splitting a row in the store."""
import datetime as dt
import hashlib
import json
from decimal import Decimal

import pytest
from pymongo.errors import DuplicateKeyError

from ledgersync.checks import booked
from ledgersync.errors import ChangedMeanwhile, NotFound
from ledgersync.models import ChangeDraft, ClientFields, DecisionDraft, Evidence, QuestionDraft, Transaction
from ledgersync.records import AgentRecords
from ledgersync.store_mongo import MongoStore
from tests.test_store_mongo import CUBE, Interleaved

pytestmark = pytest.mark.mongo

YEAR = dt.date(2025, 4, 1)


@pytest.fixture
def records(mongo_db):
    return AgentRecords(mongo_db)


def draft(**changes) -> DecisionDraft:
    fields = dict(client_id=1, thread_id="t1", year_start=YEAR, action="exclude", rule="R2 Duplicate: kept the receipt",
                  status="applied", row_ids=[4], evidence=[Evidence(upload_id=2, upload_name="a.pdf", quote="Total 9.00")],
                  reason="Same payment twice", before={"4": {"excluded": False}}, after={"4": {"excluded": True}},
                  actor="agent:test-model")
    return DecisionDraft(**{**fields, **changes})


def question(**changes) -> QuestionDraft:
    fields = dict(client_id=1, year_start=YEAR, row_ids=[4], kind="date", text="When was this taxi?",
                  why="It has no date.", source="rules")
    return QuestionDraft(**{**fields, **changes})


def test_decision_is_idempotent(records):
    d1, new1 = records.append_decision(draft(), "k")
    d2, new2 = records.append_decision(draft(), "k")
    assert (new1, new2) == (True, False) and d1.id == d2.id and len(records.decisions(1)) == 1


def test_a_decision_is_found_by_its_clients_key_and_can_be_given_its_id(records):
    d, _ = records.append_decision(draft(), "k", id="d-1")
    assert d.id == "d-1" and records.decision_by_key(1, "k") == d
    assert records.decision_by_key(2, "k") is None and records.decision_by_key(1, "other") is None


def test_decisions_are_hash_chained(records):
    a, _ = records.append_decision(draft(), "a")
    b, _ = records.append_decision(draft(), "b")
    assert (a.prev_hash, b.prev_hash) == ("", a.hash)
    body = b.model_dump(mode="json", exclude={"hash", "trigger", "review_id", "resolution"})
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    assert b.hash == hashlib.sha256((a.hash + canonical).encode()).hexdigest()


def test_each_client_has_its_own_chain(records):
    a, _ = records.append_decision(draft(client_id=1), "a")
    other, _ = records.append_decision(draft(client_id=2), "b")
    assert (a.prev_hash, other.prev_hash) == ("", "")


def test_decisions_are_filtered_by_year_and_time_and_kept_in_order(records):
    first, _ = records.append_decision(draft(), "a")
    later, _ = records.append_decision(draft(year_start=dt.date(2026, 4, 1)), "b")
    assert [d.id for d in records.decisions(1)] == [first.id, later.id]
    assert [d.id for d in records.decisions(1, YEAR)] == [first.id]
    assert [d.id for d in records.decisions(1, since=first.created_at)] == [first.id, later.id]
    assert records.decisions(1, since="9999-01-01") == []
    assert records.decisions(2) == []
    assert records.decisions(1)[0].evidence[0].quote == "Total 9.00"
    assert records.decisions(1)[0].year_start == YEAR


def test_the_idempotency_key_is_unique_per_client_in_the_database(records, mongo_db):
    d, _ = records.append_decision(draft(), "k")
    with pytest.raises(DuplicateKeyError):
        mongo_db.decisions.insert_one({"_id": "x", "client_id": 1, "idempotency_key": "k"})
    assert records.decisions(1)[0].id == d.id


def test_the_same_key_for_two_clients_makes_two_decisions(records):
    a, new_a = records.append_decision(draft(client_id=1), "k")
    b, new_b = records.append_decision(draft(client_id=2, reason="Other client's"), "k")
    assert (new_a, new_b) == (True, True) and a.id != b.id
    assert (b.client_id, b.reason, b.prev_hash) == (2, "Other client's", "")
    again_a, new_again_a = records.append_decision(draft(client_id=1), "k")
    again_b, new_again_b = records.append_decision(draft(client_id=2), "k")
    assert (again_a.id, new_again_a, again_b.id, new_again_b) == (a.id, False, b.id, False)
    assert records.decision_by_key(1, "k").id == a.id and records.decision_by_key(2, "k").id == b.id
    assert records.decision_by_key(3, "k") is None
    assert [d.id for d in records.decisions(1)] == [a.id] and [d.id for d in records.decisions(2)] == [b.id]


def test_a_database_with_the_old_key_only_index_is_upgraded(mongo_db):
    mongo_db.decisions.create_index("idempotency_key", unique=True)
    records = AgentRecords(mongo_db)
    _, new_a = records.append_decision(draft(client_id=1), "k")
    _, new_b = records.append_decision(draft(client_id=2), "k")
    assert (new_a, new_b) == (True, True)
    AgentRecords(mongo_db)   # a second start on an upgraded database is fine


def test_a_refused_decision_and_a_reversal_are_kept_as_given(records):
    d, _ = records.append_decision(draft(status="refused", reverses="abc"), "r")
    assert (d.status, d.reverses) == ("refused", "abc")


def test_question_upsert_keeps_one_per_key(records):
    q1 = records.upsert_question(question(), "date:4")
    records.set_question(q1.id, "waiting", "Not sure")
    q2 = records.upsert_question(question(text="What day was the taxi?", why="Still no date.", row_ids=[4, 5]), "date:4")
    assert (q2.id, q2.status, q2.answer, q2.created_at) == (q1.id, "waiting", "Not sure", q1.created_at)
    assert (q2.text, q2.why, q2.row_ids) == ("What day was the taxi?", "Still no date.", [4, 5])
    assert len(records.questions(1, YEAR)) == 1
    other = records.upsert_question(question(), "date:9")
    assert other.id != q1.id and q1.status == "open"


def test_a_question_is_found_by_id_in_any_status(records):
    q = records.upsert_question(question(), "date:4")
    assert records.question(q.id) == q and records.question("nope") is None
    done = records.set_question(q.id, "resolved", "14 Aug 2025")
    assert records.question(q.id) == done


def test_questions_are_listed_by_status_and_resolving_sets_the_time(records):
    a = records.upsert_question(question(), "a")
    b = records.upsert_question(question(kind="vat_invoice"), "b")
    c = records.upsert_question(question(), "c")
    records.upsert_question(question(client_id=2), "a")      # another client may use the same key
    assert a.status == "open" and a.resolved_at is None and a.answer is None
    done = records.set_question(b.id, "resolved", "Here it is")
    assert (done.status, done.answer) == ("resolved", "Here it is") and done.resolved_at
    records.set_question(c.id, "waiting")
    assert [q.id for q in records.questions(1, YEAR)] == [a.id, c.id]
    assert [q.id for q in records.questions(1, YEAR, statuses=("resolved",))] == [b.id]
    assert records.questions(1, dt.date(2026, 4, 1)) == []
    with pytest.raises(NotFound):
        records.set_question("nope", "resolved")


def test_threads_are_created_listed_touched_and_deleted(records):
    t = records.create_thread(1, YEAR, "Taxis")
    other = records.create_thread(2, YEAR, "Rent")
    assert records.thread(t.id) == t and records.thread("nope") is None
    assert {x.id for x in records.threads()} == {t.id, other.id}
    assert [x.id for x in records.threads(1)] == [t.id]
    touched = records.touch_thread(t.id, title="Taxis 2025")
    assert touched.title == "Taxis 2025" and touched.updated_at >= t.updated_at and touched.created_at == t.created_at
    assert records.touch_thread(t.id).title == "Taxis 2025"
    records.delete_thread(t.id)
    assert records.thread(t.id) is None and [x.id for x in records.threads()] == [other.id]
    with pytest.raises(NotFound):
        records.touch_thread("nope")


def test_a_threads_turns_are_kept_in_order_and_its_reads_give_the_thread_alone(records):
    t = records.create_thread(1, YEAR, "Taxis")
    assert records.turns(t.id) == [] and records.turns("nope") == []
    first = {"message_id": "m1", "files": [], "result": {"sorted": [], "questions": [], "post": None}}
    second = {"message_id": "m2", "files": [{"name": "a.csv", "state": "done", "rows": 2}], "result": {}}
    records.add_turn(t.id, first)
    touched = records.touch_thread(t.id, title="Taxis 2025")   # touching a thread keeps its turns
    records.add_turn(t.id, second)

    assert records.turns(t.id) == [first, second]
    assert records.thread(t.id) == touched and records.threads(1) == [touched]


def test_document_text_is_cached_by_hash(records, mongo_db):
    assert records.document_text("ab") is None
    records.save_document_text("ab", ["page one", "page two"], "vlm", "m1")
    records.save_document_text("ab", ["page one", "page two"], "vlm", "m1")   # saved again: no error
    assert records.document_text("ab") == ["page one", "page two"]
    saved = mongo_db.document_texts.find_one({"_id": "ab"})
    assert (saved["method"], saved["model"], saved["created_at"]) == ("vlm", "m1", saved["created_at"])


def test_records_use_the_database_they_are_given(records, mongo_db):
    assert records.db is mongo_db


# ─── MongoStore.add_split ──────────────────────────────────────────────────────

def lunch(**changes) -> Transaction:
    fields = dict(direction="out", gross="30.00", account_code="7500", date=dt.date(2025, 9, 1),
                  description="Cafe, lunch and wine", document_type="receipt", counterparty="Cafe", document_ref="cafe")
    return Transaction(**{**fields, **changes})


def test_add_split_supersedes_and_adds_parts(mongo_store, acme):
    mongo_store.add_upload(acme, "cafe.pdf", "pdf", [lunch(decision_ids=["d0"])], sha256="ab", year_start=YEAR)
    [original] = mongo_store.rows(acme)
    parts = [lunch(gross="20.00", vat="3.33", description="Lunch"), lunch(gross="10.00", vat="0.00", description="Wine")]
    new_ids = mongo_store.add_split(acme, original.id, parts, "dec1")
    rows = {r.id: r for r in mongo_store.rows(acme)}
    assert len(new_ids) == 2 and set(rows) == {original.id, *new_ids}
    old = rows[original.id].tx
    assert (old.superseded_by, old.decision_ids) == ("dec1", ["d0", "dec1"])
    assert not booked(old)
    assert [booked(rows[i].tx) for i in new_ids] == [True, True]
    assert sum(rows[i].tx.gross for i in new_ids) == old.gross == Decimal("30.00")
    assert [rows[i].tx.decision_ids for i in new_ids] == [["dec1"], ["dec1"]]
    assert rows[new_ids[0]].upload_id == rows[new_ids[1]].upload_id != original.upload_id
    split = next(u for u in mongo_store.uploads(acme) if u["id"] == rows[new_ids[0]].upload_id)
    assert (split["kind"], split["name"], split["sha256"], split["year_start"], split["row_count"]) == (
        "split", "cafe.pdf (split)", "", YEAR, 2)


@pytest.mark.parametrize("flag", [{"superseded_by": "dec0"}, {"excluded": True}])
def test_add_split_of_a_row_already_superseded_or_excluded_is_refused(mongo_store, acme, flag):
    mongo_store.add_upload(acme, "cafe.pdf", "pdf", [lunch(**flag)], year_start=YEAR)
    [original] = mongo_store.rows(acme)
    before = mongo_store.revision(acme)
    with pytest.raises(ChangedMeanwhile):
        mongo_store.add_split(acme, original.id, [lunch()], "dec1")
    assert mongo_store.revision(acme) == before and len(mongo_store.rows(acme)) == 1


def test_add_split_moves_the_revision_once(mongo_store, acme):
    mongo_store.add_upload(acme, "cafe.pdf", "pdf", [lunch()], year_start=YEAR)
    row_id = mongo_store.rows(acme)[0].id
    before = mongo_store.revision(acme)
    mongo_store.add_split(acme, row_id, [lunch(gross="30.00")], "dec1")
    assert mongo_store.revision(acme) == before + 1


def test_add_split_of_a_row_that_is_not_there_is_not_found(mongo_store, acme):
    with pytest.raises(NotFound):
        mongo_store.add_split(acme, 999, [lunch()], "d")
    other = mongo_store.create_client(ClientFields(name="Other Ltd", business_type="sole_trader", contact_name="Bo",
                                                      first_year_end=dt.date(2026, 3, 31)))
    mongo_store.add_upload(acme, "cafe.pdf", "pdf", [lunch()], year_start=YEAR)
    with pytest.raises(NotFound):
        mongo_store.add_split(other.id, mongo_store.rows(acme)[0].id, [lunch()], "d")


def test_add_split_keeps_rows_another_writer_added_meanwhile(mongo_store, mongo_client):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [lunch()], year_start=YEAR)
    row_id = mongo_store.rows(client.id)[0].id
    other = MongoStore(mongo_store.uri, mongo_store.db_name, client=mongo_client)
    mongo_store.db = Interleaved(mongo_store.db, lambda: other.add_upload(client.id, "b.pdf", "pdf", [lunch()]))
    mongo_store.add_split(client.id, row_id, [lunch(gross="30.00")], "d1")
    assert len(other.rows(client.id)) == 3


def test_add_split_that_keeps_losing_the_race_gives_up_and_changes_nothing(mongo_store, mongo_client):
    client = mongo_store.create_client(CUBE)
    mongo_store.add_upload(client.id, "a.pdf", "pdf", [lunch()], year_start=YEAR)
    row_id = mongo_store.rows(client.id)[0].id
    other = MongoStore(mongo_store.uri, mongo_store.db_name, client=mongo_client)
    mongo_store.db = Interleaved(mongo_store.db, lambda: other.add_upload(client.id, "b.pdf", "pdf", [lunch()]), times=5)
    with pytest.raises(ChangedMeanwhile):
        mongo_store.add_split(client.id, row_id, [lunch()], "d1")
    assert all(r.tx.superseded_by is None for r in other.rows(client.id))


# ─── The record of changes ─────────────────────────────────────────────────────

def change_draft(**changes) -> ChangeDraft:
    fields = dict(client_id=1, year_start=YEAR, actor="user", kind="row_edited", row_ids=[25],
                  before={"account": 8201}, after={"account": 2250}, summary="Row 25 changed: account 8201 → 2250")
    return ChangeDraft(**{**fields, **changes})


def test_changes_are_kept_in_order_and_filtered_by_year(records):
    first = records.add_change(change_draft(summary="a"))
    records.add_change(change_draft(year_start=dt.date(2026, 4, 1), summary="b"))
    third = records.add_change(change_draft(year_start=None, kind="client_changed", summary="c"))
    assert first.id and first.seq and first.created_at
    assert [c.summary for c in records.changes(1)] == ["a", "b", "c"]
    assert [c.id for c in records.changes(1, year_start=YEAR)] == [first.id, third.id]
    assert records.changes(2) == []
    assert [c.summary for c in records.changes(1, limit=2)] == ["b", "c"]


def test_changes_since_a_time_are_the_later_ones(records):
    records.add_change(change_draft(summary="a"))
    records.add_change(change_draft(summary="b"))
    records.db.changes.update_one({"summary": "a"}, {"$set": {"created_at": "2020-01-01T00:00:00+00:00"}})
    records.db.changes.update_one({"summary": "b"}, {"$set": {"created_at": "2030-01-01T00:00:00+00:00"}})
    assert [c.summary for c in records.changes(1, since="2025-01-01T00:00:00+00:00")] == ["b"]


def test_a_new_decision_adds_one_change_and_a_retried_one_none(records):
    decision, new = records.append_decision(draft(), "k1")
    assert new
    again, new_again = records.append_decision(draft(), "k1")
    assert not new_again
    found = records.changes(1)
    assert len(found) == 1
    c = found[0]
    assert c.kind == "decision" and c.actor == decision.actor and c.row_ids == decision.row_ids
    assert c.after == {"decision_id": decision.id}
    assert c.summary == f"{decision.rule}: {decision.status}"


# ─── Background reviews ────────────────────────────────────────────────────────

def start(records, client_id=1, **changes):
    fields = dict(from_seq=1, to_seq=5, trigger_summary="after 3 files were added")
    return records.start_review(client_id, YEAR, **{**fields, **changes})


def test_a_review_run_is_started_finished_and_listed_newest_first(records):
    first = start(records)
    assert first.status == "running" and first.finished_at is None and first.seen is False
    assert (first.from_seq, first.to_seq, first.looked_at) == (1, 5, [])
    second = start(records, from_seq=5, to_seq=9)
    done = records.finish_review(first.id, status="done", decision_ids=["d1"], question_ids=["q1"], summary="ok")
    assert done.status == "done" and done.finished_at and done.decision_ids == ["d1"] and done.question_ids == ["q1"]
    assert done.summary == "ok" and done.error is None
    failed = records.finish_review(second.id, status="failed", error="timed out")
    assert failed.error == "timed out"
    assert [r.id for r in records.reviews(1)] == [second.id, first.id]
    assert [r.id for r in records.reviews(1, limit=1)] == [second.id]
    assert records.reviews(1, year_start=dt.date(2024, 4, 1)) == []
    assert [r.id for r in records.reviews(1, year_start=YEAR)] == [second.id, first.id]
    assert records.reviews(2) == []


def test_runs_on_counts_a_days_finished_runs(records):
    for status in ("done", "failed", "limited", "off"):
        run = start(records)
        records.finish_review(run.id, status=status)
    start(records)   # still running
    today = dt.date.today()
    assert records.runs_on(1, today) == 2
    assert records.runs_on(1, today - dt.timedelta(days=1)) == 0
    assert records.runs_on(2, today) == 0


def test_marking_reviews_seen_clears_the_unseen_count(records):
    one = start(records)
    two = start(records)
    records.finish_review(one.id, status="done", decision_ids=["a"])
    records.finish_review(two.id, status="done", decision_ids=["b"])
    for key, status in (("a", "applied"), ("b", "suggested")):
        records.append_decision(draft(status=status, trigger="background"), key)
    # decision ids are the stored ones; point the runs at them
    ids = [d.id for d in records.decisions(1)]
    records.db.review_runs.update_one({"_id": one.id}, {"$set": {"decision_ids": [ids[0]]}})
    records.db.review_runs.update_one({"_id": two.id}, {"$set": {"decision_ids": [ids[1]]}})
    assert records.unseen_background_changes(1) == 2
    assert records.unseen_background_changes(2) == 0
    assert records.mark_reviews_seen(1) == 2
    assert records.unseen_background_changes(1) == 0
    assert records.mark_reviews_seen(1) == 0


def test_a_rejected_key_is_rejected_for_that_client_only(records):
    assert not records.is_rejected(1, "k")
    records.reject_key(1, "k")
    records.reject_key(1, "k")
    assert records.is_rejected(1, "k")
    assert not records.is_rejected(2, "k")
    assert not records.is_rejected(1, "other")


def test_review_state_defaults_and_round_trips(records):
    state = records.review_state(1)
    assert (state.client_id, state.last_seq, state.due_at, state.running, state.retry_at) == (1, 0, None, False, None)
    state.last_seq, state.due_at, state.running, state.retry_at = 7, "2026-01-01T00:00:00+00:00", True, "x"
    records.set_review_state(state)
    assert records.review_state(1) == state
    assert records.review_state(2).last_seq == 0


def test_looked_at_is_the_row_ids_of_that_years_earlier_runs(records):
    one = start(records)
    records.db.review_runs.update_one({"_id": one.id}, {"$set": {"looked_at": [3, 4]}})
    other = records.start_review(1, dt.date(2024, 4, 1), from_seq=0, to_seq=1, trigger_summary="x")
    records.db.review_runs.update_one({"_id": other.id}, {"$set": {"looked_at": [9]}})
    assert records.looked_at(1, YEAR) == {3, 4}
    assert records.looked_at(2, YEAR) == set()


def test_a_decision_without_a_trigger_reads_as_chat_and_new_kinds_are_accepted(records):
    decision, _ = records.append_decision(draft(), "k1")
    records.db.decisions.update_one({"_id": decision.id}, {"$unset": {"trigger": ""}})
    stored = records.decisions(1)[0]
    assert stored.trigger == "chat" and stored.review_id is None and stored.resolution is None
    suggested, _ = records.append_decision(draft(status="suggested", trigger="background", review_id="r",
                                                 resolution={"a": 1}), "k2")
    assert records.decisions(1)[1].resolution == {"a": 1}
    for kind in ("decision_undone", "decision_applied", "question_closed"):
        c = records.add_change(change_draft(kind=kind, in_chat=True))
        assert c.in_chat
    assert records.changes(1)[-1].in_chat is True
    assert records.add_change(change_draft()).in_chat is False


def test_a_client_defaults_to_automatic_ai_review(mongo_store):
    client = mongo_store.create_client(ClientFields(name="X Ltd", business_type="sole_trader", contact_name="Bo",
                                                    first_year_end=dt.date(2026, 3, 31)))
    assert client.ai_review == "automatic"
    assert mongo_store.update_client(client.id, {"ai_review": "suggest"}).ai_review == "suggest"
    assert mongo_store.get_client(client.id).ai_review == "suggest"
    mongo_store.db.clients.update_one({"id": client.id}, {"$unset": {"ai_review": ""}})
    assert mongo_store.get_client(client.id).ai_review == "automatic"


def test_a_legacy_decisions_hash_is_reproduced_and_a_background_decisions_includes_its_new_fields(records):
    from ledgersync.records import _hash
    decision, _ = records.append_decision(draft(), "legacy")
    old_body = decision.model_dump(mode="json", exclude={"hash", "trigger", "review_id", "resolution"})
    old = hashlib.sha256(("" + json.dumps(old_body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
    assert decision.hash == old
    stored = records.decisions(1)[0]   # read back through Decision
    assert _hash(stored.prev_hash, stored) == old
    bg, _ = records.append_decision(draft(trigger="background", review_id="r1"), "bg")
    with_fields = bg.model_dump(mode="json", exclude={"hash", "resolution"})
    assert bg.hash == hashlib.sha256((bg.prev_hash + json.dumps(
        with_fields, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
    assert '"trigger":"background"' in json.dumps(with_fields, sort_keys=True, separators=(",", ":"))


def test_finish_review_refuses_a_bad_status(records):
    run = start(records)
    with pytest.raises(ValueError):
        records.finish_review(run.id, status="bogus")
