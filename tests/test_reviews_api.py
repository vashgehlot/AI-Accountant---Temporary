"""The API for the background AI review: the runs with their decisions and questions, marking them seen, Undo and
Apply, answers without a chat, and the unseen count on the clients list."""
import datetime as dt

import pytest
from agent_fakes import ScriptedChatModel, say
from fakes import FakeModel, transactions_json
from fastapi.testclient import TestClient

from ledgersync import ledger_book
from ledgersync.blobs import MemoryBlobStore
from ledgersync.config import Settings
from ledgersync.records import AgentRecords
from server import create_app
from test_chat_api import (INVOICE, other_invoice, INVOICE_FILE, TAXI, TAXI_RECEIPT, client_id, held_payment, make,  # noqa: F401
                           new_thread, result_of, send)
from test_resolutions import YEAR, call, keep_receipt, nb, pages, records, saved  # noqa: F401

pytestmark = pytest.mark.mongo

QUOTE = "total   £64.80"


@pytest.fixture
def app(mongo_store, pages, nb):
    """The API on the nb client, whose Costco upload has a document whose text the API can read."""
    mongo_store.db.clients.update_one({"id": nb.id, "uploads.id": nb.upload("costco.txt")},
                                      {"$set": {"uploads.$.sha256": "costco-sha"}})
    AgentRecords(mongo_store.db).save_document_text("costco-sha", pages[nb.upload("costco.txt")], "text", "")
    api = TestClient(create_app(Settings(warmup=False), model_client=FakeModel([]), store=mongo_store,
                                blobs=MemoryBlobStore(), chat_model=ScriptedChatModel()),
                     headers={"X-LedgerSync": "1"})
    api.__enter__()
    yield api
    api.__exit__(None, None, None)


@pytest.fixture
def app_other(make, mongo_store, client_id, pages, nb):
    """Two clients on one API: client_id (mine) and nb (theirs), with theirs' applied decision and open question."""
    from ledgersync import questions
    api = make()
    api.records = AgentRecords(mongo_store.db)
    decision = call(mongo_store, api.records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    question = questions.ask(api.records, client_id=nb.id, year_start=YEAR, row_ids=[nb.receipt],
                             text="For the office?", why="?")
    return api, client_id, nb.id, decision, question


def review_with(records, nb, *decisions, questions=()):
    """A finished, unseen run holding the decisions and questions."""
    run = records.start_review(nb.id, YEAR, from_seq=0, to_seq=1, trigger_summary="after 1 file was added")
    return records.finish_review(run.id, status="done", decision_ids=[d.id for d in decisions],
                                 question_ids=[q.id for q in questions], summary="Looked.")


def suggestion(mongo_store, records, pages, nb):
    return call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background",
                review_id="r1", suggest=True)


def test_reviews_are_listed_with_their_decisions_and_questions(app, mongo_store, records, pages, nb):
    from ledgersync import questions
    q = questions.ask(records, client_id=nb.id, year_start=YEAR, row_ids=[nb.receipt], text="For the office?", why="?")
    s = suggestion(mongo_store, records, pages, nb)
    run = review_with(records, nb, s, questions=[q])

    listed = app.get(f"/api/clients/{nb.id}/reviews")

    assert listed.status_code == 200, listed.text
    [got] = listed.json()
    assert got["id"] == run.id and got["summary"] == "Looked." and got["seen"] is False
    assert [d["id"] for d in got["decisions"]] == [s.id] and got["decisions"][0]["status"] == "suggested"
    assert [x["id"] for x in got["questions"]] == [q.id]
    assert got["applied"] == {}
    assert app.get(f"/api/clients/{nb.id}/reviews", params={"year_start": "2025-04-01"}).json() == []
    assert app.get("/api/clients/9999/reviews").status_code == 404


def test_marking_reviews_seen_clears_the_unseen_count(app, mongo_store, records, pages, nb):
    review_with(records, nb, suggestion(mongo_store, records, pages, nb))
    unseen = lambda: next(c for c in app.get("/api/clients").json() if c["id"] == nb.id)["ai_unseen"]
    assert unseen() == 1

    marked = app.post(f"/api/clients/{nb.id}/reviews/seen")

    assert marked.status_code == 200 and marked.json() == {"marked": 1}
    assert unseen() == 0
    assert app.post(f"/api/clients/{nb.id}/reviews/seen").json() == {"marked": 0}


def test_writes_need_the_ledgersync_header(app, mongo_store, records, pages, nb):
    s = suggestion(mongo_store, records, pages, nb)
    bare = {"X-LedgerSync": ""}
    for route, body in [(f"/api/clients/{nb.id}/reviews/seen", None), (f"/api/clients/{nb.id}/decisions/{s.id}/undo", None),
                        (f"/api/clients/{nb.id}/reviews/retry", None),
                        (f"/api/clients/{nb.id}/decisions/{s.id}/apply", None),
                        (f"/api/clients/{nb.id}/questions/x/answer", {"kind": "not_sure"})]:
        assert app.post(route, json=body, headers=bare).status_code == 403, route
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_an_applied_decision_is_undone_through_the_route(app, mongo_store, records, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded

    undone = app.post(f"/api/clients/{nb.id}/decisions/{d.id}/undo")

    assert undone.status_code == 200, undone.text
    assert undone.json()["reverses"] == d.id
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_an_undo_that_is_refused_says_why(app, mongo_store, records, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    mongo_store.patch_row(nb.id, nb.sheet_costco, {"excluded": False})

    refused = app.post(f"/api/clients/{nb.id}/decisions/{d.id}/undo")

    assert refused.status_code == 422
    assert refused.json()["detail"]["message"] == f"Row {nb.sheet_costco} has changed since; change it by hand instead."


def test_a_suggestion_is_applied_and_shown_as_applied(app, mongo_store, records, pages, nb):
    s = suggestion(mongo_store, records, pages, nb)
    run = review_with(records, nb, s)

    applied = app.post(f"/api/clients/{nb.id}/decisions/{s.id}/apply")

    assert applied.status_code == 200, applied.text
    made = applied.json()
    assert (made["status"], made["actor"]) == ("applied", "user") and made["id"] != s.id
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded
    [got] = app.get(f"/api/clients/{nb.id}/reviews").json()
    assert got["applied"] == {s.id: made["id"]} and got["decisions"][0]["status"] == "suggested"
    again = app.post(f"/api/clients/{nb.id}/decisions/{s.id}/apply")
    assert again.status_code == 422 and "applied already" in again.json()["detail"]["message"]


def test_a_question_is_answered_by_date_with_no_chat(make, mongo_store, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]

    answered = api.post(f"/api/clients/{client_id}/questions/{question['id']}/answer",
                        json={"kind": "date", "date": "2026-10-09"})

    assert answered.status_code == 200, answered.text
    # What the page's question card reads, as a chat's answer gives it: the question as it stands now, what was sorted,
    # and the posting.
    got = answered.json()
    assert got["question"]["id"] == question["id"] and got["question"]["status"] == "resolved"
    assert set(got) == {"question", "sorted", "trial_balance", "post"}
    assert api.get(f"/api/clients/{client_id}/questions").json() == []
    [decision] = [d for d in api.get(f"/api/clients/{client_id}/decisions").json() if d["rule"].startswith("R1")]
    assert decision["thread_id"] is None   # no chat
    assert mongo_store.db.review_state.find_one({"client_id": client_id})["due_at"]   # due a review


def test_another_clients_decision_and_question_are_out_of_reach(make, app_other):
    api, mine, theirs, decision, question = app_other
    base = f"/api/clients/{mine}"

    assert api.post(f"{base}/decisions/{decision.id}/undo").status_code == 422
    assert api.post(f"{base}/decisions/{decision.id}/apply").status_code == 422
    assert api.post(f"{base}/questions/{question.id}/answer", json={"kind": "date", "date": "2026-10-09"}
                    ).status_code == 404
    assert api.post(f"{base}/questions/{question.id}/document",
                    files={"file": ("a.txt", b"x", "text/plain")}).status_code == 404
    assert api.get(f"{base}/reviews").json() == []
    assert api.records.question(question.id).status == "open"


def test_a_document_answers_a_question_with_no_chat(make, mongo_store, client_id):
    api, thread, question = held_payment(make, client_id, transactions_json(INVOICE))

    uploaded = api.post(f"/api/clients/{client_id}/questions/{question['id']}/document",
                        files={"file": (INVOICE_FILE[0], INVOICE_FILE[1].encode(), "text/plain")})

    assert uploaded.status_code == 200, uploaded.text
    answered = uploaded.json()
    assert (answered["question"]["id"], answered["question"]["status"]) == (question["id"], "resolved")
    assert answered["trial_balance"]["suspense"] == []
    assert api.get(f"/api/clients/{client_id}/questions").json() == []
    assert mongo_store.db.review_state.find_one({"client_id": client_id})["due_at"]   # due a review


def test_a_document_answer_in_a_chat_makes_no_review_due(make, mongo_store, client_id):
    api, thread, question = held_payment(make, client_id, transactions_json(INVOICE))
    mongo_store.db.review_state.delete_many({"client_id": client_id})

    uploaded = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/document",
                        files={"file": (INVOICE_FILE[0], INVOICE_FILE[1].encode(), "text/plain")})

    assert uploaded.status_code == 200, uploaded.text
    state = mongo_store.db.review_state.find_one({"client_id": client_id})
    assert not state or not state.get("due_at")


def test_the_ai_review_setting_round_trips_and_is_recorded(make, mongo_store, client_id):
    api = make()

    changed = api.patch(f"/api/clients/{client_id}", json={"ai_review": "suggest"})

    assert changed.status_code == 200 and changed.json()["ai_review"] == "suggest"
    assert api.get(f"/api/clients/{client_id}").json()["ai_review"] == "suggest"
    [change] = [c for c in AgentRecords(mongo_store.db).changes(client_id) if c.kind == "client_changed"]
    assert change.after == {"ai_review": "suggest"} and change.before == {"ai_review": "automatic"}


def test_decisions_and_questions_are_fetched_by_ids_for_one_client(mongo_store, records, pages, nb):
    from ledgersync import ledger, questions
    from ledgersync.models import ClientFields
    other = {**mongo_store.get_client(nb.id).model_dump(mode="json"), "name": "Another Client Ltd"}
    client_id = ledger.add_client(mongo_store, ClientFields.model_validate(other)).id   # two clients can't share a name
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    q = questions.ask(records, client_id=nb.id, year_start=YEAR, row_ids=[nb.receipt], text="For?", why="?")

    assert [x.id for x in records.decisions_by_ids(nb.id, [d.id, "none"])] == [d.id]
    assert [x.id for x in records.questions_by_ids(nb.id, ["none", q.id])] == [q.id]
    assert records.decisions_by_ids(client_id, [d.id]) == [] and records.questions_by_ids(client_id, [q.id]) == []


def answered_changes(records, client_id):
    return [c for c in records.changes(client_id) if c.kind == "question_answered"]


def test_a_document_answer_records_an_answer_not_in_a_chat(make, mongo_store, client_id):
    api, thread, question = held_payment(make, client_id, transactions_json(INVOICE))

    api.post(f"/api/clients/{client_id}/questions/{question['id']}/document",
             files={"file": (INVOICE_FILE[0], INVOICE_FILE[1].encode(), "text/plain")})

    [change] = answered_changes(AgentRecords(mongo_store.db), client_id)
    assert (change.actor, change.in_chat, change.after) == ("user", False, {"answer": INVOICE_FILE[0]})


def test_a_document_that_does_not_fit_records_no_answer_and_makes_no_review_due(make, mongo_store, client_id):
    api, thread, question = held_payment(make, client_id, transactions_json(other_invoice("Acme Print Ltd", 200.0, "A-17")))
    mongo_store.db.review_state.delete_many({"client_id": client_id})

    uploaded = api.post(f"/api/clients/{client_id}/questions/{question['id']}/document",
                        files={"file": ("acme.txt", b"An invoice.", "text/plain")})

    assert uploaded.status_code == 200 and uploaded.json()["question"]["status"] == "open"
    assert answered_changes(AgentRecords(mongo_store.db), client_id) == []
    state = mongo_store.db.review_state.find_one({"client_id": client_id})
    assert not state or not state.get("due_at")


def test_a_failure_recording_the_document_answer_does_not_fail_the_request(make, mongo_store, client_id, monkeypatch):
    api, thread, question = held_payment(make, client_id, transactions_json(INVOICE))
    original = AgentRecords.add_change

    def failing(self, c):
        if c.kind == "question_answered":
            raise RuntimeError("write failed")
        return original(self, c)
    monkeypatch.setattr(AgentRecords, "add_change", failing)

    uploaded = api.post(f"/api/clients/{client_id}/questions/{question['id']}/document",
                        files={"file": (INVOICE_FILE[0], INVOICE_FILE[1].encode(), "text/plain")})

    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["question"]["status"] == "resolved"


def test_the_years_waiting_suggestions_are_listed(app, mongo_store, records, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background",
             review_id="r1", suggest=True)
    listed = app.get(f"/api/clients/{nb.id}/years/{YEAR}/suggestions")
    assert listed.status_code == 200
    assert [(s["id"], s["status"], s["action"]) for s in listed.json()] == [(d.id, "suggested", "keep_one")]
    assert app.get(f"/api/clients/{nb.id}/years/2031-04-01/suggestions").status_code == 404
    assert app.get(f"/api/clients/999999/years/{YEAR}/suggestions").status_code == 404


def test_try_again_makes_the_review_due_now(app, records, nb):
    records.patch_review_state(nb.id, due_at=None, retry_at="2999-01-01T00:00:00+00:00")
    before = dt.datetime.now(dt.timezone.utc)

    assert app.post(f"/api/clients/{nb.id}/reviews/retry").json() == {"due": True}

    state = records.review_state(nb.id)
    assert state.retry_at is None
    assert before - dt.timedelta(seconds=1) <= dt.datetime.fromisoformat(state.due_at) <= dt.datetime.now(dt.timezone.utc)


def test_try_again_leaves_a_running_review_alone(app, records, nb):
    records.patch_review_state(nb.id, running=True, due_at=None, retry_at=None)

    assert app.post(f"/api/clients/{nb.id}/reviews/retry").status_code == 200

    state = records.review_state(nb.id)
    assert state.running and state.due_at is None


def test_try_again_is_refused_for_an_archived_client_and_an_unknown_one(app, records, nb):
    records.patch_review_state(nb.id, due_at=None)
    assert app.post("/api/clients/999999/reviews/retry").status_code == 404
    app.patch(f"/api/clients/{nb.id}", json={"archived": True})

    assert app.post(f"/api/clients/{nb.id}/reviews/retry").status_code == 409
    assert records.review_state(nb.id).due_at is None
