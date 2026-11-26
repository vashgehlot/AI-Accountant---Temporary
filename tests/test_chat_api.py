"""The chat API (design of 2026-11-02, replies of 2026-11-03) on a scripted chat model (tests/agent_fakes.py) and a fake
model client that reads the files, never real ones: threads on a client's open year, a message streamed back as steps,
the agent's reply and its turn's result, a reopened chat's replies with their results, answers to questions, and one
run at a time on each thread."""
import datetime as dt
import json
import threading
import time
from pathlib import Path

import pytest
from agent_fakes import ScriptedChatModel, call, say
from fakes import FakeModel, transactions_json
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.mongodb import MongoDBSaver

from ledgersync import books, ledger, ledger_book
from ledgersync.agent import AgentDeps, build_agent
from ledgersync.agent import chat as chat_module
from ledgersync.blobs import MemoryBlobStore
from ledgersync.config import Settings
from ledgersync.models import ClientFields
from ledgersync.records import AgentRecords
from server import create_app

pytestmark = pytest.mark.mongo

CLIENT = Path(__file__).parent.parent / "eval" / "agent_cases" / "no-invoice-over-50-suspense" / "client.json"
YEAR = "2026-04-01"   # the client's first year, which holds today

# The files sent, and what the model client reads from each, as the model answers.
STATEMENT = ("barclays-october.csv", "Date,Amount,Memo\n22/10/2026,-240.00,BRIGHTLINE PRINT\n")
PAYMENT = {"description": "BRIGHTLINE PRINT", "date": "2026-10-22", "amount": 240.0, "direction": "out",
           "account": "7500 Printing", "vat": None, "currency": "GBP", "document_type": "statement",
           "counterparty": "Brightline Print"}
TAXI_RECEIPT = ("taxi.txt", "Leeds City Cabs. Leeds Station to Kirkstall. Fare £18.00")
TAXI = {"description": "Leeds City Cabs taxi", "date": None, "amount": 18.0, "direction": "out",
        "account": "7400 Travel", "vat": None, "currency": "GBP", "document_type": "receipt",
        "counterparty": "Leeds City Cabs"}
INVOICE_FILE = ("brightline-invoice-BP-2210.txt", "Brightline Print Ltd. Invoice BP-2210. £200.00 + VAT £40.00")
INVOICE = {"description": "Brightline: business cards and A5 brochures", "date": "2026-10-19", "amount": 240.0,
           "vat": 40.0, "direction": "out", "account": "7500 Printing", "currency": "GBP",
           "document_type": "invoice", "counterparty": "Brightline Print Ltd", "document_number": "BP-2210",
           "document_total": 240.0, "document_net": 200.0, "document_vat": 40.0,
           "supplier_vat_number": "GB999225861"}

def other_invoice(who: str, total: float, number: str) -> dict:
    """An invoice that isn't the £240.00 Brightline payment's: another payee, or another total."""
    return {**INVOICE, "description": f"{who}: leaflets", "amount": total, "vat": None, "counterparty": who,
            "document_number": number, "document_total": total, "document_net": None, "document_vat": None,
            "supplier_vat_number": None}


@pytest.fixture
def client_id(mongo_store) -> int:
    """Northbridge as the agent cases add it: a VAT registered company whose first year ends 31 Mar 2027, with one
    current account (1200)."""
    return ledger.add_client(mongo_store, ClientFields.model_validate(json.loads(CLIENT.read_text()))).id


@pytest.fixture
def make(mongo_store):
    """Starts the API on the test database, with the chat model answering `replies` in order and the model client
    reading each file as `reads` says, and returns a client for it (`.model` is the chat model). Each call is a new
    app on the same database, as after a restart; they share the original files."""
    blobs, opened = MemoryBlobStore(), []

    def _make(*replies, reads=(), header=True, **settings):
        model = ScriptedChatModel(replies=list(replies))
        app = create_app(Settings(warmup=False, **settings), model_client=FakeModel(list(reads)), store=mongo_store,
                         blobs=blobs, chat_model=model)
        api = TestClient(app, headers={"X-LedgerSync": "1"} if header else {})   # as the LedgerSync pages send
        api.__enter__()
        api.model = model
        opened.append(api)
        return api

    yield _make
    for api in opened:
        api.__exit__(None, None, None)


def new_thread(api, client_id: int) -> dict:
    created = api.post("/api/chat/threads", json={"client_id": client_id})
    assert created.status_code == 201, created.text
    return created.json()


def events_of(body: str) -> list[tuple[str, dict]]:
    """The server-sent events of a stream, as (type, data)."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def send(api, thread_id: str, text: str, *files: tuple[str, str]) -> list[tuple[str, dict]]:
    """Sends a message with its files (name, text) and returns the events streamed back."""
    sent = api.post(f"/api/chat/threads/{thread_id}/messages", data={"text": text},
                    files=[("files", (name, body.encode(), "text/plain")) for name, body in files])
    assert sent.status_code == 200, sent.text
    assert sent.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in sent.headers["cache-control"]   # or the web app's proxy gzips it and holds it back
    return events_of(sent.text)


def result_of(events) -> dict:
    """The result a turn ended with: the one result event of its stream."""
    [result] = [data for kind, data in events if kind == "result"]
    return result


# The result of a turn that sorted, raised, asked for and posted nothing.
EMPTY = {"sorted": [], "questions": [], "trial_balance": None, "post": None}


def net(found: dict, code: str) -> str:
    """Debit less credit of the posted trial balance's line for the account, as pounds and pence: found is anything
    with a trial_balance, such as a turn's result."""
    line = next((l for l in found["trial_balance"]["lines"] if l["code"] == code), None)
    return "0.00" if line is None else f"{float(line['debit']) - float(line['credit']):.2f}"


def held_payment(make, client_id: int, *more_reads: str):
    """A chat whose first message sent the statement with the £240.00 Brightline payment, which has no invoice:
    the API, the thread and the question asking for the invoice."""
    api = make(say("One payment needs its invoice."), reads=[transactions_json(PAYMENT), *more_reads])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", STATEMENT))["questions"]
    return api, thread, question


# ─── Threads ───────────────────────────────────────────────────────────────────

def test_new_thread_belongs_to_client(make, mongo_store, client_id):
    api = make()
    other = ledger.add_client(mongo_store, ClientFields(name="Other Ltd", business_type="limited_company",
                                                        contact_name="Ann", first_year_end=dt.date(2027, 3, 31))).id

    thread = new_thread(api, client_id)

    assert (thread["client_id"], thread["year_start"], thread["title"]) == (client_id, YEAR, "New chat")
    assert [t["id"] for t in api.get(f"/api/chat/threads?client_id={client_id}").json()] == [thread["id"]]
    assert api.get(f"/api/chat/threads?client_id={other}").json() == []
    assert api.get(f"/api/chat/threads/{thread['id']}").json() == {"thread": thread, "messages": [], "running": False}


def test_a_new_thread_can_name_an_earlier_open_year(make, mongo_store):
    # The test books: catching up the year to 31 Mar 2024, the chat opened on today's year and could not see the
    # question it was answered about.
    api = make()
    client = ledger.add_client(mongo_store, ClientFields(name="Kestrel & Finch Digital Ltd", business_type="limited_company",
                                                         contact_name="Hannah Finch", first_year_end=dt.date(2024, 3, 31))).id
    created = api.post("/api/chat/threads", json={"client_id": client, "year_start": "2023-04-01"})
    assert created.status_code == 201 and created.json()["year_start"] == "2023-04-01"
    assert new_thread(api, client)["year_start"] != "2023-04-01"   # none named: the open year holding today
    refused = api.post("/api/chat/threads", json={"client_id": client, "year_start": "2023-05-01"})
    assert refused.status_code == 422 and "isn't one of" in refused.json()["detail"]["message"]


def test_a_new_thread_with_no_year_opens_on_the_year_whose_questions_wait(make, mongo_store):
    # mind Limited: 22 questions waited in the year to 1 Nov 2021, but "What needs my attention?" opened on today's
    # empty year, and the agent said nothing needed attention.
    from ledgersync.models import QuestionDraft
    api = make()
    client = ledger.add_client(mongo_store, ClientFields(name="mind Limited", business_type="limited_company",
                                                         contact_name="Sandy", first_year_end=dt.date(2024, 3, 31))).id
    assert new_thread(api, client)["year_start"] != "2023-04-01"   # no questions anywhere: the year holding today
    records = AgentRecords(mongo_store.db)
    for year, key in (("2024-04-01", "a"), ("2023-04-01", "b")):
        records.upsert_question(QuestionDraft(client_id=client, year_start=dt.date.fromisoformat(year), row_ids=[],
                                              kind="other", text="Which account?", why="Unclear.", source="rules"), key)
    assert new_thread(api, client)["year_start"] == "2023-04-01"   # the earliest year with questions waiting


def test_rename_and_delete_thread(make, mongo_store, client_id):
    api = make(say("Done."))
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Anything to do?")
    checkpoints = mongo_store.client[f"{mongo_store.db_name}_checkpoints"].checkpoints

    renamed = api.patch(f"/api/chat/threads/{thread['id']}", json={"title": "October review"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "October review"
    assert checkpoints.count_documents({"thread_id": thread["id"]}) > 0

    assert api.delete(f"/api/chat/threads/{thread['id']}").status_code == 204
    assert api.get(f"/api/chat/threads/{thread['id']}").status_code == 404
    assert checkpoints.count_documents({"thread_id": thread["id"]}) == 0


# ─── A message ─────────────────────────────────────────────────────────────────

def test_message_streams_steps_then_result_then_done(make, client_id):
    api = make(say("I read the statement."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)

    events = send(api, thread["id"], "Review October.", STATEMENT, ("empty.txt", ""))

    kinds = [kind for kind, _ in events]
    assert kinds[0] == "status" and kinds[-2:] == ["result", "done"]
    assert max(k for k, kind in enumerate(kinds) if kind == "step") < kinds.index("token") < kinds.index("result")
    steps = [data for kind, data in events if kind == "step"]
    statement = [s for s in steps if s["file"] == "barclays-october.csv"]
    assert [(s["text"], s["state"]) for s in statement] == [("Reading barclays-october.csv…", "running"),
                                                            ("Read barclays-october.csv (1 row)", "done")]
    assert statement[0]["id"] == statement[1]["id"] and statement[1]["rows"] == 1
    empty = [s for s in steps if s["file"] == "empty.txt"]
    assert [(s["text"], s["state"]) for s in empty] == [("Reading empty.txt…", "running"),
                                                        ("Couldn't read empty.txt: 'empty.txt' is empty.", "failed")]
    assert empty[1]["reason"] == "'empty.txt' is empty."
    assert "".join(data["text"] for kind, data in events if kind == "token") == "I read the statement."
    detail = api.get(f"/api/chat/threads/{thread['id']}").json()
    assert detail["thread"]["title"] == "Review October."
    assert sorted(detail["messages"][0]["files"], key=lambda f: f["name"]) == [   # each file's reading is kept
        {"name": "barclays-october.csv", "state": "done", "rows": 1, "reason": None},
        {"name": "empty.txt", "state": "failed", "rows": None, "reason": "'empty.txt' is empty."}]


def test_a_file_already_saved_for_the_client_is_skipped_not_booked_again(make, mongo_store, client_id):
    # A spreadsheet sent to the chat a second time was read and booked again: every line was in the books twice.
    api = make(say("I read the statement."), say("That one is in already."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Review October.", STATEMENT)
    [saved] = mongo_store.uploads(client_id)
    day = dt.datetime.fromisoformat(saved["created_at"])

    events = send(api, thread["id"], "Here it is again.", STATEMENT)

    skipped = (f"Skipped barclays-october.csv: same file as barclays-october.csv, uploaded {day.day} {day:%b}, so its "
               "rows are already in the books.")
    assert [(s["text"], s["state"]) for kind, s in events if kind == "step" and s.get("file")] == [
        ("Reading barclays-october.csv…", "running"), (skipped, "failed")]
    assert (len(mongo_store.uploads(client_id)), len(mongo_store.rows(client_id))) == (1, 1)


def test_a_file_sent_twice_in_one_message_is_read_once(make, mongo_store, client_id):
    api = make(say("I read the statement."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)

    events = send(api, thread["id"], "Review October.", STATEMENT, STATEMENT)

    last = [s["text"] for kind, s in events if kind == "step" and s.get("file") and s["state"] != "running"]
    assert sorted(text.split(":")[0] for text in last) == ["Read barclays-october.csv (1 row)",
                                                           "Skipped barclays-october.csv"]
    assert (len(mongo_store.uploads(client_id)), len(mongo_store.rows(client_id))) == (1, 1)


def test_a_review_result_holds_its_questions_and_posting(make, client_id):
    api = make(say("One payment needs its invoice."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)

    result = result_of(send(api, thread["id"], "Review October.", STATEMENT))

    [held] = result["trial_balance"]["suspense"]
    assert (held["gross"], held["needs"]) == ("240.00", "receipt_or_invoice")
    [question] = result["questions"]
    assert (question["kind"], question["status"], question["row_ids"]) == ("receipt_or_invoice", "open",
                                                                          [held["row_id"]])
    assert question["text"] == "Can you upload the receipt or invoice?"
    assert net(result, "9998") == "240.00" and net(result, "1200") == "-240.00"
    assert result["trial_balance"]["is_balanced"]
    assert result["post"]["batch_id"] and result["post"]["problems"] == []
    assert result["sorted"] == []


def test_a_plain_message_after_a_review_has_an_empty_result(make, client_id):
    api = make(say("One payment needs its invoice."), say("You're welcome."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Review October.", STATEMENT)   # raises the question for the invoice

    assert result_of(send(api, thread["id"], "Thanks.")) == EMPTY


def test_listing_the_open_items_shows_them_as_cards(make, client_id):
    api = make(say("One payment needs its invoice."), call("list_questions"), say("One thing needs you."),
               reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    first = result_of(send(api, thread["id"], "Review October.", STATEMENT))

    listed = result_of(send(api, thread["id"], "What needs my attention?"))

    assert [q["id"] for q in first["questions"]] != []
    assert [q["id"] for q in listed["questions"]] == [q["id"] for q in first["questions"]]
    assert listed["trial_balance"] is None and listed["sorted"] == []


def test_fetching_the_trial_balance_shows_it(make, client_id):
    api = make(say("Hi."), call("get_trial_balance"), say("Here it is."))
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Hello")   # this turn's posting is done, so the next has nothing new to post

    shown = result_of(send(api, thread["id"], "Show the trial balance"))

    assert shown["trial_balance"]["is_balanced"] and shown["post"] is None and shown["questions"] == []


def test_a_new_chat_does_not_bring_up_earlier_items(make, client_id):
    api = make(say("One payment needs its invoice."), say("Hello."), reads=[transactions_json(PAYMENT)])
    a = new_thread(api, client_id)
    raised = result_of(send(api, a["id"], "Review October.", STATEMENT))
    assert raised["questions"] != []
    b = new_thread(api, client_id)   # another chat on the same client, which still has the question open

    assert result_of(send(api, b["id"], "Hello")) == EMPTY


def test_without_the_openrouter_key_a_turn_says_the_model_is_unavailable(mongo_store, client_id):
    app = create_app(Settings(warmup=False), model_client=FakeModel([transactions_json(PAYMENT)]), store=mongo_store,
                     blobs=MemoryBlobStore())
    with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
        thread = new_thread(api, client_id)
        events = send(api, thread["id"], "Review October.", STATEMENT)

        detail = api.get(f"/api/chat/threads/{thread['id']}").json()

    [error] = [data for kind, data in events if kind == "error"]
    assert error["code"] == "model_unavailable" and "OPENROUTER_API_KEY" in error["message"]
    assert [kind for kind, _ in events][-2:] == ["result", "done"]   # the file was read, and the year posted
    assert result_of(events)["trial_balance"]["suspense"][0]["gross"] == "240.00"
    assert detail["messages"][0]["text"] == "Review October."   # kept, for when the model is back


def test_a_turn_with_no_reply_keeps_its_result(mongo_store, client_id):
    app = create_app(Settings(warmup=False), model_client=FakeModel([transactions_json(PAYMENT)]), store=mongo_store,
                     blobs=MemoryBlobStore())
    with TestClient(app, headers={"X-LedgerSync": "1"}) as api:   # no model, so no reply
        thread = new_thread(api, client_id)
        send(api, thread["id"], "Review October.", STATEMENT)   # the turn still reads, refreshes and posts

        messages = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]

    assert [(m["role"], m["text"]) for m in messages] == [("user", "Review October."), ("assistant", "")]
    assert messages[0]["files"] == [{"name": "barclays-october.csv", "state": "done", "rows": 1, "reason": None}]
    assert [q["kind"] for q in messages[1]["result"]["questions"]] == ["receipt_or_invoice"]


# ─── Reopening a chat ──────────────────────────────────────────────────────────

def test_reload_keeps_each_reply_with_its_result(make, client_id):
    api = make(say("One payment needs its invoice."), say("You're welcome."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Review October.", STATEMENT)
    send(api, thread["id"], "Thanks.")

    messages = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]

    assert [(m["role"], m["text"]) for m in messages] == [
        ("user", "Review October."), ("assistant", "One payment needs its invoice."),
        ("user", "Thanks."), ("assistant", "You're welcome.")]
    assert messages[0]["files"] == [{"name": "barclays-october.csv", "state": "done", "rows": 1, "reason": None}]
    assert [q["kind"] for q in messages[1]["result"]["questions"]] == ["receipt_or_invoice"]
    assert messages[2]["files"] == [] and messages[3]["result"] is None


def test_a_reloaded_reply_has_no_blank_runs_from_whitespace_around_tool_calls():
    def tool_call(call_id: str) -> dict:
        return {"name": "list_rows", "args": {}, "id": call_id, "type": "tool_call"}

    messages = [HumanMessage("Review the books.", id="m1"),
                AIMessage("\n\n", tool_calls=[tool_call("c1")]), ToolMessage("[]", tool_call_id="c1"),
                AIMessage("\n\nLet me look.\n\n", tool_calls=[tool_call("c2")]), ToolMessage("[]", tool_call_id="c2"),
                AIMessage("Done.\n\nSecond part.\n")]

    shown = chat_module._messages(messages, {})

    assert [(m.role, m.text) for m in shown] == [("user", "Review the books."),
                                                 ("assistant", "Let me look.\n\nDone.\n\nSecond part.")]


@pytest.mark.parametrize("raw", ["Model call limits exceeded: run limit (30/30)",
                                 "Tool call limit reached: run limit exceeded (81/80 calls).",
                                 "'read_document' tool call limit reached: run limit exceeded (21/20 calls)."])
def test_a_reloaded_turn_stopped_by_a_call_limit_says_so_in_plain_words(raw):
    messages = [HumanMessage("Review the books.", id="m1"), AIMessage("Looking."), AIMessage(raw)]

    shown = chat_module._messages(messages, {})

    assert shown[-1].text == "Looking.\n\nI stopped after too many steps, before finishing."


def test_a_card_shows_the_question_as_it_stands_now(make, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    assert question["status"] == "open"
    api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
             json={"kind": "date", "date": "2026-10-09"})   # answered after the reply was written

    [card] = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"][1]["result"]["questions"]

    assert (card["status"], card["answer"]) == ("resolved", "9 Oct 2026")


def test_a_reply_never_gains_questions_from_another_chat(make, client_id):
    api = make(say("One payment needs its invoice."), say("The taxi has no date."),
               reads=[transactions_json(PAYMENT), transactions_json(TAXI)])
    a, b = new_thread(api, client_id), new_thread(api, client_id)
    send(api, a["id"], "Review October.", STATEMENT)      # asks for the receipt or invoice
    send(api, b["id"], "Review the taxi.", TAXI_RECEIPT)   # asks for the date

    [card] = api.get(f"/api/chat/threads/{a['id']}").json()["messages"][1]["result"]["questions"]

    assert card["kind"] == "receipt_or_invoice"


def test_a_chat_from_before_this_change_shows_its_messages_without_cards(make, mongo_store, client_id):
    api = make()
    thread = new_thread(api, client_id)
    # A chat saved before the turns were kept: the thread has a last "summary" and no "turns", and its messages are in
    # the checkpoints.
    mongo_store.db.chat_threads.update_one({"_id": thread["id"]}, {"$set": {"summary": {
        "sorted": [], "questions": [], "trial_balance": None, "post": None}}})
    saved = build_agent(Settings(), AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=None),
                        model=ScriptedChatModel(), checkpointer=MongoDBSaver(
                            mongo_store.client, db_name=f"{mongo_store.db_name}_checkpoints"))
    saved.update_state({"configurable": {"thread_id": thread["id"]}},
                       {"messages": [HumanMessage("Hello"), AIMessage("Hi.")]}, as_node="model")

    detail = api.get(f"/api/chat/threads/{thread['id']}").json()

    assert [(m["role"], m["text"], m["files"], m["result"]) for m in detail["messages"]] == [
        ("user", "Hello", [], None), ("assistant", "Hi.", [], None)]


def test_a_turn_record_that_cannot_be_read_does_not_stop_the_chat_loading(make, mongo_store, client_id):
    api = make(say("One payment needs its invoice."), say("You're welcome."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Review October.", STATEMENT)
    send(api, thread["id"], "Thanks.")
    mongo_store.db.chat_threads.update_one({"_id": thread["id"]}, {"$set": {"turns.0.result": {"sorted": 1}}})

    response = api.get(f"/api/chat/threads/{thread['id']}")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["text"] for m in messages] == ["Review October.", "One payment needs its invoice.", "Thanks.", "You're welcome."]
    assert messages[1]["result"] is None and messages[0]["files"] == []


def test_a_note_for_the_agent_is_kept_in_its_memory_but_not_shown(make, mongo_store, client_id):
    api = make(say("Hi."))
    thread = new_thread(api, client_id)
    send(api, thread["id"], "Hello")
    config = {"configurable": {"thread_id": thread["id"]}}
    memory = build_agent(Settings(), AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=None),
                         model=ScriptedChatModel(), checkpointer=MongoDBSaver(
                             mongo_store.client, db_name=f"{mongo_store.db_name}_checkpoints"))

    said = "Answered: When was this taxi? → 9 Oct 2026"

    chat_module._say(memory, thread["id"], said, note=True)

    kept = memory.get_state(config).values["messages"][-1]
    assert (kept.type, kept.text, kept.additional_kwargs) == ("human", said, {"note": True})
    messages = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]
    assert [(m["role"], m["text"]) for m in messages] == [("user", "Hello"), ("assistant", "Hi.")]


# ─── Answers ───────────────────────────────────────────────────────────────────

def test_answer_date_returns_the_question_and_its_effect(make, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    assert question["kind"] == "date"

    answered = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
                        json={"kind": "date", "date": "2026-10-09"})

    assert answered.status_code == 200, answered.text
    answered = answered.json()
    assert (answered["question"]["id"], answered["question"]["status"], answered["question"]["answer"]) == (
        question["id"], "resolved", "9 Oct 2026")
    [decision] = answered["sorted"]
    [row_id] = question["row_ids"]
    assert decision["rule"] == "R1 Date from the person" and decision["after"] == {str(row_id): {"date": "2026-10-09"}}
    # The turn posted the taxi already and its date moves no line: the posting wrote nothing, so nothing is shown.
    assert (answered["trial_balance"], answered["post"]) == (None, None)
    assert set(answered) == {"question", "sorted", "trial_balance", "post"}


def test_answering_a_question_already_resolved_returns_it_with_no_effect(make, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    route = f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer"
    api.post(route, json={"kind": "date", "date": "2026-10-09"})

    again = api.post(route, json={"kind": "date", "date": "2026-10-09"})

    assert again.status_code == 200, again.text
    assert again.json()["question"]["status"] == "resolved"
    assert {k: v for k, v in again.json().items() if k != "question"} == {
        "sorted": [], "trial_balance": None, "post": None}


def test_the_answer_note_is_for_the_agent_not_the_history(make, client_id):
    api = make(say("The taxi has no date."), say("Noted."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    note = "Answered: When was this Leeds City Cabs taxi? → 9 Oct 2026"

    api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
             json={"kind": "date", "date": "2026-10-09"})
    send(api, thread["id"], "Thanks.")

    assert [(m.type, m.text) for m in api.model.seen[1][-3:]] == [
        ("ai", "The taxi has no date."), ("human", note), ("human", "Thanks.")]   # the agent has the note...
    detail = api.get(f"/api/chat/threads/{thread['id']}").json()
    assert [(m["role"], m["text"]) for m in detail["messages"]] == [
        ("user", "Review October."), ("assistant", "The taxi has no date."), ("user", "Thanks."),
        ("assistant", "Noted.")]   # ...and the chat's history doesn't


def test_the_next_turn_sees_the_answer(make, client_id):
    api = make(say("The taxi has no date."), say("Noted."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
             json={"kind": "date", "date": "2026-10-09"})

    events = send(api, thread["id"], "Thanks.")

    assert len(api.model.seen) == 2   # one model call each turn
    assert [(m.type, m.text) for m in api.model.seen[1][-3:]] == [
        ("ai", "The taxi has no date."), ("human", "Answered: When was this Leeds City Cabs taxi? → 9 Oct 2026"),
        ("human", "Thanks.")]
    assert [data["text"] for kind, data in events if kind == "token"] == ["Noted."]


def test_upload_answer_moves_out_of_suspense(make, client_id):
    api, thread, question = held_payment(make, client_id, transactions_json(INVOICE))

    uploaded = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/document",
                        files={"file": (INVOICE_FILE[0], INVOICE_FILE[1].encode(), "text/plain")})

    assert uploaded.status_code == 200, uploaded.text
    answered = uploaded.json()
    assert (answered["question"]["id"], answered["question"]["status"]) == (question["id"], "resolved")
    assert answered["trial_balance"]["suspense"] == [] and net(answered, "9998") == "0.00"
    assert (net(answered, "7500"), net(answered, "2201"), net(answered, "1200")) == ("200.00", "40.00", "-240.00")
    assert answered["post"]["batch_id"]


@pytest.mark.parametrize("who, total, file", [
    ("Acme Print Ltd", 240.0, "acme-invoice-A-17.txt"),           # another payee sharing a trade word
    ("Acme Print Ltd", 200.0, "acme-invoice-A-17.txt"),           # and another total
    ("Brightline Print Ltd", 200.0, "brightline-invoice-BP-2199.txt"),   # the payee, but another total
])
def test_upload_that_does_not_fit_says_why(make, client_id, who, total, file):
    api, thread, question = held_payment(make, client_id, transactions_json(other_invoice(who, total, "A-17")))

    uploaded = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/document",
                        files={"file": (file, b"An invoice.", "text/plain")})

    assert uploaded.status_code == 200, uploaded.text
    answered = uploaded.json()
    assert (answered["question"]["id"], answered["question"]["status"]) == (question["id"], "open")
    assert answered["question"]["why"] == (
        f"Read {file}, but it doesn't match: {who}, £{total:.2f} against Brightline Print, £240.00. "
        "It's saved and booked; remove it in Transactions if it isn't theirs.")
    assert answered["trial_balance"] is None or answered["trial_balance"]["suspense"][0]["gross"] == "240.00"


def test_no_document_leaves_the_question_waiting(make, client_id):
    api, thread, question = held_payment(make, client_id)

    answered = api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
                        json={"kind": "no_document"})

    assert answered.status_code == 200, answered.text
    answered = answered.json()
    assert (answered["question"]["id"], answered["question"]["status"], answered["question"]["answer"]) == (
        question["id"], "waiting", "I don't have it")
    assert (answered["sorted"], answered["trial_balance"], answered["post"]) == ([], None, None)   # nothing changed


def test_questions_survive_restart(make, client_id):
    # The Brightline invoice has no date, so it can't be the payment's yet: the £240.00 is held, and both ask.
    api = make(say("Two things need you."),
               reads=[transactions_json(PAYMENT), transactions_json({**INVOICE, "date": None})],
               max_parallel_jobs=1)   # the files are read in turn, so each gets its own reading
    thread = new_thread(api, client_id)
    asked = result_of(send(api, thread["id"], "Review October.", STATEMENT, INVOICE_FILE))
    assert sorted(q["kind"] for q in asked["questions"]) == ["date", "receipt_or_invoice"]
    assert net(asked, "9998") == "240.00"
    [dating] = [q for q in asked["questions"] if q["kind"] == "date"]

    restarted = make()   # a new app on the same database
    listed = restarted.get(f"/api/clients/{client_id}/questions").json()
    assert sorted(q["id"] for q in listed) == sorted(q["id"] for q in asked["questions"])
    answered = restarted.post(f"/api/chat/threads/{thread['id']}/questions/{dating['id']}/answer",
                              json={"kind": "date", "date": "2026-10-19"})

    assert answered.status_code == 200, answered.text
    answered = answered.json()   # dated, the invoice is the payment's: both questions go, and so does the Suspense
    assert answered["question"]["status"] == "resolved" and answered["trial_balance"]["suspense"] == []
    assert restarted.get(f"/api/clients/{client_id}/questions").json() == []
    assert (net(answered, "9998"), net(answered, "7500"), net(answered, "2201")) == ("0.00", "200.00", "40.00")
    assert answered["post"]["batch_id"] and answered["post"]["reversals_added"] > 0


def test_thread_history_survives_restart(make, client_id):
    api = make(say("One payment needs its invoice."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    result = result_of(send(api, thread["id"], "Review October.", STATEMENT))
    before = api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]

    detail = make().get(f"/api/chat/threads/{thread['id']}").json()   # a new app on the same database

    assert [(m["role"], m["text"]) for m in detail["messages"]] == [
        ("user", "Review October."), ("assistant", "One payment needs its invoice.")]
    assert detail["messages"] == before
    assert detail["messages"][1]["result"] == result   # kept as the turn streamed it


# ─── One run at a time ─────────────────────────────────────────────────────────

def test_second_message_while_running_409(make, client_id):
    started, release = threading.Event(), threading.Event()

    def slow(messages):
        started.set()
        release.wait(30)
        return say("Done.")

    api = make(slow, say("Done again."))
    thread = new_thread(api, client_id)
    first = threading.Thread(target=send, args=(api, thread["id"], "Review October."))
    first.start()
    try:
        assert started.wait(30)
        second = api.post(f"/api/chat/threads/{thread['id']}/messages", data={"text": "And again?"})
        stopped = api.post(f"/api/chat/threads/{thread['id']}/stop")
    finally:
        release.set()
        first.join(30)

    assert second.status_code == 409
    assert second.json()["detail"]["message"] == "Still working on the last message."
    assert stopped.status_code == 200 and stopped.json() == {"stopping": True}
    assert [kind for kind, _ in send(api, thread["id"], "And again?")][-1] == "done"   # the run was let go


def test_an_answer_waits_for_the_message_running_on_its_chat(make, client_id):
    started, release = threading.Event(), threading.Event()

    def slow(messages):
        started.set()
        release.wait(30)
        return say("Done.")

    api = make(say("One payment needs its invoice."), slow, reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", STATEMENT))["questions"]
    running = threading.Thread(target=send, args=(api, thread["id"], "Anything else?"))
    answered = []
    answering = threading.Thread(target=lambda: answered.append(api.post(
        f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer", json={"kind": "no_document"})))
    running.start()
    try:
        assert started.wait(30)
        answering.start()
        answering.join(1)
        assert answering.is_alive()   # waiting for the run, not refused
    finally:
        release.set()
        running.join(30)
        answering.join(60)

    assert answered[0].status_code == 200, answered[0].text
    assert answered[0].json()["question"]["status"] == "waiting"


def test_two_chats_on_one_client_run_together_and_post_in_turn(make, client_id, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(messages):
        started.set()
        release.wait(30)
        return say("Done.")

    writes, lock = [], threading.Lock()
    write = chat_module.Chat._write

    def timed(self, thread, since):   # the write steps, timed
        begun = time.monotonic()
        time.sleep(0.3)
        done = write(self, thread, since)
        with lock:
            writes.append((begun, time.monotonic()))
        return done

    monkeypatch.setattr(chat_module.Chat, "_write", timed)
    api = make(slow, say("Done too."))
    first, second = new_thread(api, client_id), new_thread(api, client_id)
    events = {}
    running = threading.Thread(target=lambda: events.update(first=send(api, first["id"], "Review October.")))
    running.start()
    try:
        assert started.wait(30)
        other = threading.Thread(target=lambda: events.update(second=send(api, second["id"], "Anything else?")))
        other.start()   # the second chat isn't refused while the first runs
        time.sleep(0.1)
    finally:
        release.set()
        running.join(30)
        other.join(30)

    assert [kind for kind, _ in events["first"]][-1] == [kind for kind, _ in events["second"]][-1] == "done"
    (a_start, a_end), (b_start, b_end) = sorted(writes)
    assert a_end <= b_start   # one chat's write steps after the other's, never at once


def test_stop_ends_the_run_before_its_next_model_call(make, client_id):
    started, release = threading.Event(), threading.Event()

    def looks(messages):
        started.set()
        release.wait(30)
        return call("list_questions")

    api = make(looks)
    thread = new_thread(api, client_id)
    events = []
    run = threading.Thread(target=lambda: events.extend(send(api, thread["id"], "Review October.")))
    run.start()
    try:
        assert started.wait(30)
        assert api.post(f"/api/chat/threads/{thread['id']}/stop").json() == {"stopping": True}
    finally:
        release.set()
        run.join(30)

    assert len(api.model.seen) == 1
    assert "".join(data["text"] for kind, data in events if kind == "token") == "I stopped there, as you asked."
    assert [kind for kind, _ in events][-2:] == ["result", "done"]


def test_a_tool_call_left_by_a_crash_is_closed_before_the_next_turn(make, mongo_store, client_id):
    api = make(say("Carrying on."))
    thread = new_thread(api, client_id)
    # A server that died while a tool ran left the call with no result in the thread's checkpoints.
    crashed = build_agent(Settings(), AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=None),
                          model=ScriptedChatModel(), checkpointer=MongoDBSaver(
                              mongo_store.client, db_name=f"{mongo_store.db_name}_checkpoints"))
    crashed.update_state({"configurable": {"thread_id": thread["id"]}}, {"messages": [
        HumanMessage("Look at the taxi."),
        AIMessage("", tool_calls=[{"name": "list_questions", "args": {}, "id": "call_1", "type": "tool_call"}])]},
        as_node="model")

    events = send(api, thread["id"], "Carry on.")

    seen = api.model.seen[0]
    assert [m.type for m in seen] == ["system", "human", "ai", "tool", "human"]
    assert (seen[3].tool_call_id, seen[3].content) == ("call_1", "Stopped before this finished.")
    assert [data["text"] for kind, data in events if kind == "token"] == ["Carrying on."]
    assert not [data for kind, data in events if kind == "error"]


# ─── Who may write ─────────────────────────────────────────────────────────────

def test_writes_need_header(make, client_id):
    api, thread, question = held_payment(make, client_id)
    bare = make(header=False)
    chat = f"/api/chat/threads/{thread['id']}"

    refused = [
        bare.post("/api/chat/threads", json={"client_id": client_id}),
        bare.patch(chat, json={"title": "Renamed"}),
        bare.delete(chat),
        bare.post(f"{chat}/messages", data={"text": "Hello"}),
        bare.post(f"{chat}/questions/{question['id']}/answer", json={"kind": "not_sure"}),
        bare.post(f"{chat}/questions/{question['id']}/document", files={"file": ("a.txt", b"x", "text/plain")}),
        bare.post(f"{chat}/stop"),
    ]

    assert [r.status_code for r in refused] == [403] * len(refused)
    assert bare.get(chat).status_code == 200   # reading needs no header
    assert api.get(f"/api/clients/{client_id}/questions").json()[0]["status"] == "open"


def test_demo_reset_hidden_unless_demo(make, mongo_store):
    plain = make()
    assert plain.get("/api/health").json()["demo"] is False
    assert plain.post("/api/demo/reset").status_code == 404

    demo = make(demo=True)
    assert demo.get("/api/health").json()["demo"] is True
    assert make(header=False, demo=True).post("/api/demo/reset").status_code == 403
    reset = demo.post("/api/demo/reset")
    assert reset.status_code == 200, reset.text
    assert mongo_store.get_client(reset.json()["client_id"]).name == "Northbridge Consulting Ltd"


# ─── The client's records ──────────────────────────────────────────────────────

def test_client_routes_list_questions_decisions_and_posted_trial_balance(make, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
             json={"kind": "date", "date": "2026-10-09"})

    assert api.get(f"/api/clients/{client_id}/questions").json() == []
    [decision] = api.get(f"/api/clients/{client_id}/decisions?year_start={YEAR}").json()
    assert decision["rule"] == "R1 Date from the person"
    posted = api.get(f"/api/clients/{client_id}/years/{YEAR}/posted-trial-balance").json()
    assert posted["is_balanced"] and net({"trial_balance": posted}, "7400") == "18.00"


def test_posted_trial_balance_reports_unposted_changes(make, mongo_store, mongo_db, client_id):
    api = make(say("The taxi has no date."), reads=[transactions_json(TAXI)])
    thread = new_thread(api, client_id)
    [question] = result_of(send(api, thread["id"], "Review October.", TAXI_RECEIPT))["questions"]
    api.post(f"/api/chat/threads/{thread['id']}/questions/{question['id']}/answer",
             json={"kind": "date", "date": "2026-10-09"})
    route = f"/api/clients/{client_id}/years/{YEAR}/posted-trial-balance"
    assert api.get(route).json()["unposted_changes"] == 0   # answering posted the row

    [row_id] = question["row_ids"]
    mongo_store.patch_row(client_id, row_id, {"excluded": True})   # a person drops the row after it was posted
    records, start = AgentRecords(mongo_db), dt.date.fromisoformat(YEAR)
    assert ledger_book.unposted_changes(mongo_store, records, client_id, start) == 1   # the posted ledger is behind
    assert api.get(route).json()["unposted_changes"] == 0   # reading an open year brings it up to date
    assert ledger_book.unposted_changes(mongo_store, records, client_id, start) == 0


def test_a_chat_detail_says_whether_a_turn_is_running(make, client_id):
    started, release = threading.Event(), threading.Event()

    def slow(messages):
        started.set()
        release.wait(30)
        return say("Done.")

    api = make(slow)
    thread = new_thread(api, client_id)
    assert api.get(f"/api/chat/threads/{thread['id']}").json()["running"] is False   # a fresh chat
    first = threading.Thread(target=send, args=(api, thread["id"], "Review October."))
    first.start()
    try:
        assert started.wait(30)
        while_running = api.get(f"/api/chat/threads/{thread['id']}").json()["running"]
    finally:
        release.set()
        first.join(30)
    assert while_running is True
    assert api.get(f"/api/chat/threads/{thread['id']}").json()["running"] is False


def test_a_chat_file_with_rows_in_two_years_leaves_both_posted(make, mongo_store, client_id):
    later = {**PAYMENT, "description": "BRIGHTLINE PRINT", "date": "2027-05-04"}
    api = make(say("Read both months."), reads=[transactions_json(PAYMENT, later)])
    thread = new_thread(api, client_id)
    # A statement with a line in each year: its dates are read from the file.
    both = (STATEMENT[0], STATEMENT[1] + "04/05/2027,-240.00,BRIGHTLINE PRINT\n")

    send(api, thread["id"], "Review the statement.", both)

    records = AgentRecords(mongo_store.db)
    years = [y.start for y in books.years_of(mongo_store, client_id, dt.date(2027, 6, 1))]
    assert len(years) == 2
    assert [ledger_book.unposted_changes(mongo_store, records, client_id, y) for y in years] == [0, 0]


def test_files_read_in_a_turn_are_settled_even_if_the_stream_raises(make, mongo_store, client_id, monkeypatch):
    api = make(say("Read it."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)

    def boom(*a, **k):
        raise RuntimeError("the stream broke")
    monkeypatch.setattr(chat_module, "stream_turn", boom)
    api.post(f"/api/chat/threads/{thread['id']}/messages", data={"text": "Review."},
             files=[("files", (STATEMENT[0], STATEMENT[1].encode(), "text/plain"))])   # the turn runs in a worker

    records = AgentRecords(mongo_store.db)
    assert ledger_book.unposted_changes(mongo_store, records, client_id, dt.date(2026, 4, 1)) == 0
    assert ledger_book.posted_trial_balance(mongo_store, records, client_id, dt.date(2026, 4, 1)).suspense


# ─── Specialists (design of 2026-11-15) ────────────────────────────────────────

from ledgersync.agent.middleware import BOOKS_NOW   # noqa: E402
from ledgersync.agent.prompt import SYSTEM_PROMPT   # noqa: E402
from ledgersync.agent.specialists import ALL_TOOLS, PROFILES   # noqa: E402


def statuses(events) -> list[str]:
    return [data["text"] for kind, data in events if kind == "status"]


def test_a_turn_goes_to_its_specialist_who_starts_from_a_briefing(make, client_id, mongo_store):
    api = make(say("Nothing needs you."), say("Still nothing."))
    thread = new_thread(api, client_id)
    events = send(api, thread["id"], "What needs my attention?")
    assert statuses(events) == ["Looking it up…", "Posting the books…"]
    assert api.model.tools == list(PROFILES["reporter"].tools)
    prompt, told = api.model.seen[0][0].content.split(BOOKS_NOW)
    assert prompt == PROFILES["reporter"].prompt
    told = json.loads(told)
    assert set(told) == {"overview", "open_questions", "latest_changes"} and "accounts" not in told["overview"]
    assert told["overview"]["rows"] == 0 and told["open_questions"] == []
    [turn] = AgentRecords(mongo_store.db).turns(thread["id"])
    assert (turn["specialist"], turn["handed_over"]) == ("reporter", False)
    # a follow-up no rule places stays with the specialist of the turn before
    assert statuses(send(api, thread["id"], "yes"))[0] == "Looking it up…"
    assert api.model.tools == list(PROFILES["reporter"].tools)
    assert [m["role"] for m in api.get(f"/api/chat/threads/{thread['id']}").json()["messages"]] == [
        "user", "assistant", "user", "assistant"]


def test_a_message_no_specialist_takes_goes_to_the_lead_accountant(make, client_id, mongo_store):
    api = make(say("Hello."))
    thread = new_thread(api, client_id)
    assert statuses(send(api, thread["id"], "Hello"))[0] == "Working on it…"
    assert api.model.tools == list(ALL_TOOLS) and api.model.seen[0][0].content == SYSTEM_PROMPT
    [turn] = AgentRecords(mongo_store.db).turns(thread["id"])
    assert (turn["specialist"], turn["handed_over"]) == ("lead", False)


def test_a_turn_handed_over_is_kept_as_such_and_its_follow_up_goes_to_the_lead(make, client_id, mongo_store):
    api = make(call("hand_over", why="They want a row changed."), say("Which row do you mean?"), say("Thanks."))
    thread = new_thread(api, client_id)
    events = send(api, thread["id"], "What needs my attention?")
    assert "Passed to the lead accountant" in [data["text"] for kind, data in events if kind == "step"]
    [turn] = AgentRecords(mongo_store.db).turns(thread["id"])
    assert (turn["specialist"], turn["handed_over"]) == ("reporter", True)
    assert statuses(send(api, thread["id"], "yes"))[0] == "Working on it…"
    assert api.model.tools == list(ALL_TOOLS)


def test_when_the_briefing_cannot_be_built_the_lead_accountant_takes_the_turn(make, client_id, monkeypatch):
    def stuck(deps, ctx):
        raise AssertionError("One row can't be posted")   # as the books say when a row's debits and credits differ

    monkeypatch.setattr(chat_module, "briefing", stuck)
    api = make(say("I'll look."))
    thread = new_thread(api, client_id)
    assert statuses(send(api, thread["id"], "What needs my attention?"))[0] == "Working on it…"
    assert api.model.tools == list(ALL_TOOLS) and api.model.seen[0][0].content == SYSTEM_PROMPT


def test_files_sent_with_a_message_go_to_the_reviewer_whose_briefing_has_their_rows(make, client_id):
    api = make(say("Read it."), reads=[transactions_json(PAYMENT)])
    thread = new_thread(api, client_id)
    events = send(api, thread["id"], "Here is the statement", STATEMENT)
    assert statuses(events) == ["Reading 1 file…", "Reviewing the books…", "Posting the books…"]
    told = json.loads(api.model.seen[0][0].content.split(BOOKS_NOW)[1])
    assert told["overview"]["rows"] == 1 and [r["gross"] for r in told["need_a_look"]["rows"]] == ["240.00"]


# ─── The agent offers a books question's answer for the person to confirm (design of 2026-11-25) ──────────

def owing_vat_at_the_start(mongo_store, client_id: int):
    """Northbridge opening its first year owing £27,100 of VAT, and paying £27,412 on 13 Apr 2026: the books ask
    what the £312 was for."""
    from helpers import add_rows, row
    from decimal import Decimal
    from ledgersync import questions
    from ledgersync.models import OpeningBalances, OpeningLine
    books.set_opening(mongo_store, client_id, OpeningBalances(lines=[
        OpeningLine(code="1200", debit=Decimal("30000.00")), OpeningLine(code="2202", credit=Decimal("27100.00")),
        OpeningLine(code="3200", credit=Decimal("2900.00"))]))
    add_rows(mongo_store, client_id, row(date=dt.date(2026, 4, 13), gross=Decimal("27412.00"), account_code="2202",
                                         document_type="statement", counterparty="HMRC", description="HMRC VAT"))
    records = AgentRecords(mongo_store.db)
    [q] = [q for q in questions.refresh(mongo_store, records, client_id, dt.date(2026, 4, 1)) if q.kind == "opening_vat"]
    return q


def test_the_agent_fills_in_a_books_question_for_the_person_to_confirm(make, mongo_store, client_id):
    # The agency's £312 (25 Nov 2026): the client said in the chat where it went, and the books' question stayed
    # open. Now the agent fills in its card from their words, and the person's Confirm books it.
    q = owing_vat_at_the_start(mongo_store, client_id)
    offer = dict(question_id=q.id, answer={"kind": "split", "lines": [{"account": "8250", "amount": "312.00"}]},
                 sources=[{"kind": "said", "quote": "Fine to correct it this year"}, {"kind": "question"}],
                 reason="The client says the previous accountant left an invoice off the VAT figure.")
    api = make(call("offer_answer", **offer), say("I've filled in the VAT question's card for you to confirm."))
    thread = new_thread(api, client_id)
    said = "Redland & Co say a February invoice was left off their VAT figure. Fine to correct it this year."
    [card] = [x for x in result_of(send(api, thread["id"], said))["questions"] if x["id"] == q.id]
    assert card["status"] == "open" and card["offer"]["answer"]["lines"] == [{"account": "8250", "amount": "312.00"}]
    assert card["offer"]["sources"][0]["quote"] == "Fine to correct it this year"
    assert not [r for r in mongo_store.rows(client_id) if r.tx.document_type == "journal"]   # nothing booked yet

    done = api.post(f"/api/chat/threads/{thread['id']}/questions/{q.id}/answer", json=card["offer"]["answer"])
    assert done.status_code == 200, done.text
    asked = AgentRecords(mongo_store.db).question(q.id)
    assert asked.status == "resolved" and asked.offer is None
    assert [r.tx.account_code for r in mongo_store.rows(client_id) if r.tx.document_type == "journal"] == ["8250"]
