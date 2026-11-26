"""The accountant agent run on a scripted chat model (tests/agent_fakes.py), never a real one: its tools take the client
and the thread from the run's context, a tool error goes back to the model and the run carries on, a model that fails
or loops ends the turn with an error event, and no tool can set a date."""
import datetime as dt
import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import openrouter
import pytest
from agent_fakes import ScriptedChatModel, call, say
from langchain.agents.middleware import model_retry
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

import run_scripted_resolutions as scripted
from helpers import add_rows, row
from ledgersync import ledger_book
from ledgersync.agent import AgentDeps, ChatContext, ChatEvent, build_agent, stream_turn
from ledgersync.agent.llm import chat_model
from ledgersync.agent.locks import ClientLocks
from ledgersync.agent.prompt import SYSTEM_PROMPT
from ledgersync.agent.run import _STOP
from ledgersync.agent.tools import make_tools
from ledgersync.blobs import GridFSBlobStore
from ledgersync.checks import issue
from ledgersync.config import Settings
from ledgersync.errors import ModelUnavailable
from ledgersync.model_client import ModelClient
from ledgersync.models import ChangeDraft, ClientFields
from ledgersync.records import AgentRecords

ROOT = Path(__file__).parent.parent
STAPLES = ROOT / "eval" / "agent_cases" / "duplicate-receipt-spreadsheet"
YEAR = dt.date(2026, 4, 1)   # the case's first year
SETTINGS = Settings()


def context(client_id: int = 1) -> ChatContext:
    return ChatContext(client_id=client_id, thread_id=uuid4().hex, year_start=YEAR)


def offline_agent(model, **deps):
    """The agent on the scripted model, with its checkpoints in memory and no database behind its tools."""
    return build_agent(SETTINGS, AgentDeps(store=None, records=None, blobs=None, **deps), model=model,
                       checkpointer=InMemorySaver())


def answered(model: ScriptedChatModel, n: int) -> list[ToolMessage]:
    """The tool results model call n was given after the last call's tool calls."""
    messages = model.seen[n]
    return [m for m in messages[next(k for k in range(len(messages) - 1, -1, -1)
                                     if messages[k].type == "ai") + 1:] if isinstance(m, ToolMessage)]


def kinds(events) -> list[str]:
    return [e.type for e in events]


@pytest.fixture
def deps(mongo_store):
    return AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=GridFSBlobStore(mongo_store.db))


@pytest.fixture
def staples(mongo_store, deps) -> int:
    """The duplicate-receipt case's client, with its files added as the chat adds them: a Staples receipt, the
    expenses sheet line for it and the bank line that paid it."""
    client_id = scripted._client(STAPLES, mongo_store, deps.records)
    for path in scripted._documents(STAPLES):
        scripted._add_document(mongo_store, deps.blobs, client_id, YEAR, path)
    return client_id


def keep_the_receipt(store, client_id: int) -> dict:
    """resolve_issue's arguments for the case's own resolution: keep the receipt, drop the sheet line."""
    step = json.loads((STAPLES / "expected_decisions.json").read_text())["resolutions"][0]
    by_name = {u["name"]: u["id"] for u in store.uploads(client_id)}

    def row_id(name: dict) -> int:
        return scripted._row_id(store, client_id, name)

    return {"row_id": row_id(step["row"]),
            "resolution": {"action": "keep_one", **scripted._ARGUMENTS["keep_one"](step["arguments"], row_id)},
            "evidence": [{"upload_id": by_name[e["file"]], "quote": e["quote"]} for e in step["evidence"]],
            "reason": step["reason"]}


# ─── Tool errors go back to the model ──────────────────────────────────────────

def test_malformed_tool_args_become_error_message_and_run_continues():
    model = ScriptedChatModel(replies=[call("get_row", row_id="the taxi"), say("Row ids are numbers. Done.")])

    events = list(stream_turn(offline_agent(model), context(), "Look at the taxi."))

    [result] = answered(model, 1)
    assert result.status == "error" and "row_id" in result.content
    assert kinds(events) == ["token"] and events[0].data == {"text": "Row ids are numbers. Done."}


def test_unknown_tool_reported_back():
    model = ScriptedChatModel(replies=[call("set_date", row_id=1, date="2026-10-14"), say("I can't date it.")])

    events = list(stream_turn(offline_agent(model), context(), "Date the taxi 14 Oct."))

    [result] = answered(model, 1)
    assert result.status == "error" and "There is no tool called set_date" in result.content
    assert kinds(events) == ["token"]


class StreamedAgent:
    """Stands in for the agent's graph: stream() yields what it was given, as LangGraph's stream modes do."""

    def __init__(self, *chunks):
        self.chunks = chunks

    def stream(self, *args, **kwargs):
        yield from self.chunks


def said(message_id: str, text: str, **more):
    """A piece of a model call's reply as the "messages" stream mode sends it."""
    return "messages", (AIMessageChunk(content=text, id=message_id, **more), {"langgraph_node": "model"})


def test_a_reply_has_no_blank_runs_from_whitespace_the_model_sends_around_tool_calls():
    # Qwen sends "\n\n" before a tool call, and around its words: none of it is a reply, and replies of separate
    # model calls are apart by exactly one blank line.
    agent = StreamedAgent(
        said("a", "\n\n"),                                          # a call that only calls a tool
        said("b", "\n\n"), said("b", "Let me look"), said("b", ".\n"), said("b", "\n"),
        said("c", "\n\n\n"),                                        # another
        said("d", "Done."), said("d", "\n\nSecond"), said("d", " part."), said("d", "\n\n"),
    )

    events = list(stream_turn(agent, context(), "Review the books."))

    assert kinds(events) == ["token"] * len(events)
    assert "".join(e.data["text"] for e in events) == "Let me look.\n\nDone.\n\nSecond part."


def test_what_the_stop_says_is_trimmed_too():
    agent = StreamedAgent(said("a", "Looking.\n\n"), ("updates", {_STOP: {"messages": [AIMessage("\n\nStopped.\n")]}}))

    events = list(stream_turn(agent, context(), "Review the books."))

    assert "".join(e.data["text"] for e in events) == "Looking.\n\nStopped."


def test_a_fault_in_a_tool_is_answered_so_the_thread_stays_usable():
    model = ScriptedChatModel(replies=[call("list_questions"), say("Something failed.")])
    agent = offline_agent(model)   # no records behind the tool, so it raises AttributeError
    ctx = context()

    events = list(stream_turn(agent, ctx, "What is open?"))

    [result] = answered(model, 1)
    assert result.status == "error" and "list_questions couldn't finish" in result.content
    assert "AttributeError" not in result.content
    assert [(e.type, e.data.get("state")) for e in events] == [("step", "running"), ("step", "failed"),
                                                               ("token", None)]
    assert events[1].data["text"] == "Checking the open questions"
    kept = agent.get_state({"configurable": {"thread_id": ctx.thread_id}}).values["messages"]
    assert [m.type for m in kept] == ["human", "ai", "tool", "ai"]   # every tool call answered


# ─── A model that fails, loops or is stopped ───────────────────────────────────

@pytest.mark.mongo
def test_model_exception_mid_run_emits_error_event_keeps_steps(monkeypatch, deps, acme):
    monkeypatch.setattr(model_retry, "time", SimpleNamespace(sleep=lambda seconds: None))   # retry at once
    model = ScriptedChatModel(replies=[call("list_questions")], then=ConnectionError("OpenRouter hung up"))
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    events = list(stream_turn(agent, context(acme), "Review the books."))

    assert len(model.seen) == 4   # the tool call, then a failing call and its two retries
    assert kinds(events) == ["step", "step", "error"]
    assert events[1].data["state"] == "done" and events[0].data["id"] == events[1].data["id"]
    assert events[2].data["code"] == "model_unavailable" and "OpenRouter hung up" in events[2].data["message"]


@pytest.mark.mongo
def test_model_call_limit_stops_with_message(deps, acme):
    model = ScriptedChatModel(then=lambda messages: call("list_questions"))
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    events = list(stream_turn(agent, context(acme), "Review the books."))

    assert len(model.seen) == 30
    assert events[-1].type == "error"
    assert events[-1].data == {"code": "loop_limit", "message": "Stopped after 30 steps, before finishing.",
                               "steps": 30}
    assert [e.type for e in events[:-1]] == ["step"] * 60   # each step running, then done


def test_a_stopped_chat_stops_before_its_next_model_call():
    model = ScriptedChatModel(replies=[say("Never said.")])
    agent = offline_agent(model, is_cancelled=lambda thread_id: True)

    events = list(stream_turn(agent, context(), "Review the books."))

    assert model.seen == []
    assert [(e.type, e.data) for e in events] == [("token", {"text": "I stopped there, as you asked."})]


# ─── The tools ─────────────────────────────────────────────────────────────────

@pytest.mark.mongo
def test_resolve_retried_records_once(mongo_store, deps, staples):
    args = keep_the_receipt(mongo_store, staples)
    model = ScriptedChatModel(replies=[call("resolve_issue", **args), call("resolve_issue", **args),
                                       say("Kept the receipt.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    events = list(stream_turn(agent, context(staples), "Review the books."))

    [decision] = deps.records.decisions(staples)
    assert decision.status == "applied" and decision.actor == "agent:qwen/qwen3.8-27b"
    first, again = (json.loads(answered(model, n)[0].content) for n in (1, 2))
    assert first == again and first["decision_id"] == decision.id and first["status"] == "applied"
    assert [e.data["text"] for e in events if e.type == "step" and e.data["state"] == "done"] == [
        f"Row {args['row_id']}: R2 Duplicate: kept the receipt"] * 2
    dropped = args["resolution"]["drop_row_ids"][0]
    assert next(r for r in mongo_store.rows(staples) if r.id == dropped).tx.excluded


@pytest.mark.mongo
def test_a_step_names_the_document_opened(mongo_store, deps, staples):
    receipt = next(u for u in mongo_store.uploads(staples) if u["name"] == "staples-receipt.txt")
    model = ScriptedChatModel(replies=[call("read_document", upload_id=receipt["id"]), say("Read it.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    events = list(stream_turn(agent, context(staples), "Open the receipt."))

    assert [(e.data["text"], e.data["state"]) for e in events if e.type == "step"] == [
        ("Opening staples-receipt.txt…", "running"), ("Opened staples-receipt.txt", "done")]
    [result] = answered(model, 1)
    page = json.loads(result.content)
    assert (page["name"], page["page"], page["pages"]) == ("staples-receipt.txt", 1, 1)
    assert "STAPLES" in page["text"] and "64.80" in page["text"]


@pytest.mark.mongo
def test_list_changes_returns_the_years_changes_since_a_time(mongo_store, deps, staples):
    from ledgersync.models import ChangeDraft
    first, second = (deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user", kind="row_edited",
                                                         row_ids=[n], summary=f"Row {n} changed")) for n in (1, 2))
    for change, when in ((first, "2030-01-01T10:00:00+00:00"), (second, "2030-01-01T12:00:00+00:00")):
        mongo_store.db.changes.update_one({"_id": change.id}, {"$set": {"created_at": when}})
    model = ScriptedChatModel(replies=[call("list_changes", since="2030-01-01T11:00:00+00:00"), say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    events = list(stream_turn(agent, context(staples), "What has changed?"))

    [result] = answered(model, 1)
    [change] = json.loads(result.content)["changes"]
    assert (change["by"], change["kind"], change["summary"], change["row_ids"]) == ("user", "row_edited", "Row 2 changed", [2])
    assert change["changed_at"] == "2030-01-01T12:00:00+00:00"
    assert [e.data["text"] for e in events if e.type == "step"] == ["Checking what has changed…", "Read 1 change"]


def test_the_prompt_says_to_read_the_changes_first():
    assert "list_changes" in SYSTEM_PROMPT


@pytest.mark.mongo
def test_list_issues_by_family(mongo_store, deps, staples):
    model = ScriptedChatModel(replies=[call("list_issues", family="duplicate"), call("list_issues", family="documents"),
                                       say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(staples), "What needs a look?"))

    names = {r.id: (r.tx.document_type, r.tx.description) for r in mongo_store.rows(staples)}
    duplicate, documents = (json.loads(answered(model, n)[0].content) for n in (1, 2))
    assert [names[r["row_id"]][0] for r in duplicate["rows"]] == ["statement"]
    # (the bank line is also held for its document, which the row now says last)
    assert [i["code"] for i in duplicate["rows"][0]["issues"] if i["code"] != "needs_document"][-1] == "booked_twice"
    # The bank line is held for its receipt; the sheet line is booked from the receipt, so it isn't held.
    assert [(names[r["row_id"]][0], r["held"]["needs"]) for r in documents["rows"]] == [
        ("statement", "receipt_or_invoice")]


def rows_of_the_year(mongo_store, deps, client_id: int, upload_id=None, **args) -> dict:
    """What list_rows answers when called on the client's first year."""
    model = ScriptedChatModel(replies=[call("list_rows", **({"upload_id": upload_id} if upload_id else {}), **args),
                                       say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    list(stream_turn(agent, context(client_id), "Show the rows."))
    [result] = answered(model, 1)
    return json.loads(result.content)


def three_clean_rows(mongo_store, acme) -> tuple[int, int]:
    """Two clean receipts in one upload and one in another; the ids of the two uploads."""
    first = add_rows(mongo_store, acme,
                     row(date=dt.date(2026, 10, 1), gross=Decimal("12.00"), vat=Decimal("2.00"), account_code="7504"),
                     row(date=dt.date(2026, 10, 2), gross=Decimal("24.00"), vat=Decimal("4.00"), account_code="7504"),
                     year_start=YEAR)
    second = add_rows(mongo_store, acme,
                      row(date=dt.date(2026, 10, 3), gross=Decimal("36.00"), vat=Decimal("6.00"), account_code="7504"),
                      year_start=YEAR)
    return first, second


@pytest.mark.mongo
def test_list_rows_lists_rows_that_have_no_issues(mongo_store, deps, acme):
    three_clean_rows(mongo_store, acme)

    listed = rows_of_the_year(mongo_store, deps, acme)

    assert [r["gross"] for r in listed["rows"]] == ["12.00", "24.00", "36.00"]
    assert all(r["kind"] == "receipt" and r["booked"] is True and "issues" not in r for r in listed["rows"])
    assert listed["rows"][0]["vat"] == "2.00" and "next_after_row_id" not in listed
    ids = [r["row_id"] for r in listed["rows"]]
    assert ids == sorted(ids)
    model = ScriptedChatModel(replies=[call("get_row", row_id=ids[1]), say("Looked.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    list(stream_turn(agent, context(acme), "Look."))
    [result] = answered(model, 1)
    assert result.status != "error" and json.loads(result.content)["row_id"] == ids[1]


@pytest.mark.mongo
def test_a_row_that_pays_an_invoice_says_what_it_posts_against(mongo_store, deps, acme):
    # The agency run: a Stripe charge paying invoice KF-1014 showed only its own account, Sales, so the review asked
    # each month whether the sale was booked twice.
    add_rows(mongo_store, acme,
             row(date=dt.date(2026, 6, 1), direction="in", gross=Decimal("720.00"), vat=Decimal("120.00"),
                 account_code="4000", document_type="invoice", document_number="KF-1014",
                 counterparty="Moss & Pine Florists"),
             row(date=dt.date(2026, 6, 6), direction="in", gross=Decimal("720.00"), account_code="4000",
                 document_type="statement", counterparty="Moss & Pine Florists"), year_start=YEAR)
    invoice, line = rows_of_the_year(mongo_store, deps, acme)["rows"]
    assert (line["account_code"], line["posts_against"], line["posts_against_name"]) == ("4000", "1100", "Debtors")
    assert "posts_against" not in invoice


@pytest.mark.mongo
def test_list_rows_by_document_lists_only_its_rows(mongo_store, deps, acme):
    first, second = three_clean_rows(mongo_store, acme)

    listed = rows_of_the_year(mongo_store, deps, acme, upload_id=second)

    assert [(r["upload_id"], r["gross"]) for r in listed["rows"]] == [(second, "36.00")]
    assert len(rows_of_the_year(mongo_store, deps, acme, upload_id=first)["rows"]) == 2


@pytest.mark.mongo
def test_list_rows_leaves_out_excluded_and_replaced_rows(mongo_store, deps, acme):
    three_clean_rows(mongo_store, acme)
    first, second, third = (r.id for r in sorted(mongo_store.rows(acme), key=lambda r: r.id))
    mongo_store.patch_row(acme, first, {"excluded": True})
    mongo_store.patch_row(acme, second, {"superseded_by": "d1"})

    listed = rows_of_the_year(mongo_store, deps, acme)

    assert [r["row_id"] for r in listed["rows"]] == [third]


@pytest.mark.mongo
def test_list_rows_pages(mongo_store, deps, acme):
    three_clean_rows(mongo_store, acme)

    page = rows_of_the_year(mongo_store, deps, acme, limit=1)
    after = rows_of_the_year(mongo_store, deps, acme, limit=2, after_row_id=page["next_after_row_id"])

    assert len(page["rows"]) == 1 and page["next_after_row_id"] == page["rows"][0]["row_id"]
    assert [r["gross"] for r in after["rows"]] == ["24.00", "36.00"] and "next_after_row_id" not in after


@pytest.mark.mongo
def test_an_empty_trial_balance_says_nothing_is_posted_yet(mongo_store, deps, acme):
    three_clean_rows(mongo_store, acme)

    def trial_balance() -> dict:
        model = ScriptedChatModel(replies=[call("get_trial_balance"), say("Looked.")])
        agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
        list(stream_turn(agent, context(acme), "Is it posted?"))
        return json.loads(answered(model, 1)[0].content)

    before = trial_balance()
    assert "list_rows" in before["note"] and "Nothing is posted yet" in before["note"]

    ledger_book.post(mongo_store, deps.records, acme, YEAR)
    after = trial_balance()
    assert "note" not in after and after["entries_posted"] > 0


@pytest.mark.mongo
def test_a_bank_line_its_receipt_records_is_not_listed_as_needing_a_look(mongo_store, deps, acme):
    add_rows(mongo_store, acme,
             row(date=dt.date(2026, 10, 19), gross=Decimal("64.00"), account_code="7504", counterparty="Costco",
                 document_ref="r", document_total=Decimal("64.00")),
             row(date=dt.date(2026, 10, 19), gross=Decimal("64.00"), account_code="9998", counterparty="COSTCO",
                 document_ref="card", document_type="statement",
                 issues=[issue("account_not_recognised", "Account unclear: put in Suspense. Choose one.")]),
             year_start=dt.date(2026, 4, 1))
    model = ScriptedChatModel(replies=[call("list_issues"), call("get_overview"), say("Looked.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(acme), "What needs a look?"))

    listed, overview = (json.loads(answered(model, n)[0].content) for n in (1, 2))
    assert listed.get("rows", []) == [] and overview["need_a_look"] == {}


@pytest.mark.mongo
def test_get_overview_lists_the_accounts_a_row_can_be_coded_to(mongo_store, deps, acme):
    model = ScriptedChatModel(replies=[call("get_overview"), say("Looked.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(acme), "Look over the books."))

    [result] = answered(model, 1)
    accounts = json.loads(result.content)["accounts"]
    assert {"code": "8205", "name": next(a["name"] for a in accounts if a["code"] == "8205")} in accounts
    assert all(set(a) == {"code", "name"} for a in accounts)


@pytest.mark.mongo
def test_get_overview_gives_each_bank_against_its_statement_and_the_missing_paperwork(mongo_store, deps, acme):
    add_rows(mongo_store, acme,
             row(date=dt.date(2025, 10, 1), gross=Decimal("100.00"), account_code="7504", counterparty="Paper Shop",
                 document_type="statement", balance=Decimal("900.00")),
             year_start=dt.date(2025, 4, 1))
    model = ScriptedChatModel(replies=[call("get_overview"), say("Looked.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, ChatContext(client_id=acme, thread_id=uuid4().hex, year_start=dt.date(2025, 4, 1)),
                     "Look over the books."))

    overview = json.loads(answered(model, 1)[0].content)
    [bank] = overview["bank"]
    assert (bank["statement"], bank["books"], bank["difference"], bank["agrees"]) == ("900.00", "-100.00",
                                                                                      "-1000.00", False)
    assert overview["missing_paperwork"][0].endswith("opens at £1,000.00; the books have £0.00 then.")


def ask_about(deps, client_id: int, *row_ids: int) -> tuple[dict, list]:
    """What ask_user answers when called on the rows in the client's first year, and the agent's questions then."""
    model = ScriptedChatModel(replies=[call("ask_user", row_ids=list(row_ids), question="When was it?",
                                            why="No date."), say("Asked.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    list(stream_turn(agent, ChatContext(client_id=client_id, thread_id=uuid4().hex, year_start=dt.date(2025, 4, 1)),
                     "Ask."))
    [result] = answered(model, 1)
    mine = [q for q in deps.records.questions(client_id, dt.date(2025, 4, 1)) if q.source == "agent"]
    return json.loads(result.content), mine


@pytest.mark.mongo
def test_ask_user_leaves_out_what_the_books_already_ask(mongo_store, deps, acme):
    add_rows(mongo_store, acme, row(date=None, gross=Decimal("12.00"), account_code="7400", description="taxi"),
             row(date=dt.date(2025, 6, 1), gross=Decimal("12.00"), account_code="7400", description="bus",
                 document_type="statement"), year_start=dt.date(2025, 4, 1))
    taxi, bus = (next(r.id for r in mongo_store.rows(acme) if r.tx.description == d) for d in ("taxi", "bus"))

    result, mine = ask_about(deps, acme, taxi)
    assert result["asked"] is False and f"row {taxi} (a date)" in result["message"] and mine == []

    result, mine = ask_about(deps, acme, taxi, bus)
    assert [q.row_ids for q in mine] == [[bus]] and f"row {taxi} (a date)" in result["note"]


@pytest.mark.mongo
def test_ask_user_asks_about_a_row_the_books_do_not_ask_about(mongo_store, deps, acme):
    add_rows(mongo_store, acme, row(date=dt.date(2025, 6, 1), gross=Decimal("12.00"), account_code="7400",
                                    description="bus", document_type="statement"), year_start=dt.date(2025, 4, 1))
    bus = mongo_store.rows(acme)[0].id

    result, mine = ask_about(deps, acme, bus)

    assert result["status"] == "open" and [q.row_ids for q in mine] == [[bus]]


def the_tool(name: str):
    return next(t for t in make_tools(AgentDeps(store=None, records=None, blobs=None), actor="agent:test")
                if t.name == name)


def ask_user_args(question: str, why: str) -> dict:
    return {"row_ids": [1], "question": question, "why": why}


def test_ask_user_takes_the_longer_questions_the_model_writes():
    schema = the_tool("ask_user").tool_call_schema
    schema.model_validate(ask_user_args("q" * 290, "w" * 390))
    schema.model_validate(ask_user_args("q" * 300, "w" * 400))
    for question, why in (("q" * 301, "why"), ("q", "w" * 401)):
        with pytest.raises(ValueError):
            schema.model_validate(ask_user_args(question, why))


def test_resolve_issue_takes_a_reason_of_up_to_600_characters():
    schema = the_tool("resolve_issue").tool_call_schema
    args = {"row_id": 1, "resolution": {"action": "keep_one", "keep_row_id": 1, "drop_row_ids": [2]},
            "evidence": [{"upload_id": 5, "quote": "q"}]}
    schema.model_validate({**args, "reason": "r" * 600})
    with pytest.raises(ValueError):
        schema.model_validate({**args, "reason": "r" * 601})


def evidence_of(value):
    args = {"row_id": 1, "resolution": {"action": "keep_one", "keep_row_id": 1, "drop_row_ids": [2]}, "reason": "Same purchase.",
            "evidence": value}
    return the_tool("resolve_issue").tool_call_schema.model_validate(args).evidence


def test_resolve_issue_takes_evidence_sent_as_a_json_string():
    from ledgersync.models import Evidence
    want = [Evidence(upload_id=516, quote="of which VAT @ 20%")]
    assert evidence_of('[{"upload_id": 516, "quote": "of which VAT @ 20%"}]') == want
    # The one slip live runs made: a stray quote after the upload id.
    assert evidence_of('[{"upload_id": 516", "quote": "of which VAT @ 20%"}]') == want
    assert evidence_of(want) == want                                  # a list passes unchanged
    assert evidence_of([{"upload_id": 516, "quote": "of which VAT @ 20%"}]) == want


@pytest.mark.parametrize("broken", [
    '[{"upload_id": 516, "quote": "of which VAT @ 20%"',            # cut off
    '[{"upload_id": "516", "quote": "x"}, {"upload_id": 7", "quote": x}]',   # a second slip the repair doesn't cover
    '[{"upload_id": 516, "quote": "an "odd" quote"}]',              # a stray quote elsewhere is not repaired
    "not json",
])
def test_resolve_issue_still_refuses_evidence_broken_any_other_way(broken):
    with pytest.raises(ValueError):
        evidence_of(broken)


def test_resolve_issue_still_tells_the_model_evidence_is_a_list():
    schema = the_tool("resolve_issue").tool_call_schema.model_json_schema()
    evidence = schema["properties"]["evidence"]
    assert evidence["type"] == "array" and "anyOf" not in evidence and "oneOf" not in evidence
    item = schema["$defs"][evidence["items"]["$ref"].rsplit("/", 1)[-1]]
    assert item["properties"].keys() >= {"upload_id", "quote"}


def test_the_prompt_names_the_rules_the_live_runs_broke():
    for rule in ("Never quote a row's description", "Use only row ids that a tool gave you", "list_rows",
                 "the books ask the person about those automatically", "from the accounts get_overview lists",
                 "Use the invoice over an expenses-sheet line (use_primary): the service checks that a bank line pays it, "
                 "and says to ask when none does."):
        assert rule in " ".join(SYSTEM_PROMPT.split())


def test_the_prompt_answers_what_was_asked():
    assert "earlier chats" not in SYSTEM_PROMPT
    assert "When the person asks what needs their attention, call list_questions." in SYSTEM_PROMPT
    assert "adds a card for each thing this turn sorted, raised or posted" in SYSTEM_PROMPT


def test_tools_use_context_client_not_args():
    for tool in make_tools(AgentDeps(store=None, records=None, blobs=None), actor="agent:test"):
        schema = json.dumps(tool.tool_call_schema.model_json_schema())
        assert "client_id" not in schema and "thread_id" not in schema, tool.name


@pytest.mark.mongo
def test_a_row_of_another_client_is_not_found(mongo_store, deps, staples):
    other = mongo_store.create_client(ClientFields(name="Other Ltd", business_type="limited_company",
                                                   contact_name="O", first_year_end=dt.date(2027, 3, 31))).id
    row_id = mongo_store.rows(staples)[0].id
    model = ScriptedChatModel(replies=[call("get_row", row_id=row_id, client_id=staples), say("Not found.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(other), "Look at it."))

    [result] = answered(model, 1)
    assert result.status == "error" and "not found" in result.content


def test_only_a_checked_resolution_can_set_a_date():
    def properties(schema) -> list[tuple[str, dict]]:
        """Every property of the schema and of the schemas it nests, by name."""
        found = []
        if isinstance(schema, dict):
            found += list((schema.get("properties") or {}).items())
            for value in schema.values():
                found += properties(value)
        elif isinstance(schema, list):
            for value in schema:
                found += properties(value)
        return found

    tools = make_tools(AgentDeps(store=None, records=None, blobs=None), actor="agent:test")
    assert {t.name for t in tools} == {"get_overview", "list_issues", "list_rows", "get_row", "list_documents", "read_document",
                                       "resolve_issue", "edit_row", "ask_user", "close_question", "offer_answer",
                                       "list_questions",
                                       "list_decisions", "list_changes", "get_trial_balance", "get_vat_figures",
                                       "hand_over"}   # the specialists' own: it changes who works, never a row
    dated = [(tool.name, name) for tool in tools for name, field in properties(tool.tool_call_schema.model_json_schema())
             if "date" in name or field.get("format") in ("date", "date-time")]
    # The dates a tool takes: set_date's, which resolutions.resolve checks against another record, the file name or
    # the document before it changes the row (R1), the one a person in the chat tells edit_row to set, and a bad
    # debt's write-off date offer_answer fills in, which the answer service checks and only the person's Confirm books.
    assert dated == [("resolve_issue", "date"), ("edit_row", "date"), ("offer_answer", "date")]


# ─── Threads ───────────────────────────────────────────────────────────────────

@pytest.mark.mongo
def test_two_threads_share_no_messages(deps, acme):
    model = ScriptedChatModel(replies=[say("Hello from the first chat."), say("Hello from the second chat.")])
    agent = build_agent(SETTINGS, deps, model=model)   # checkpoints in <db>_checkpoints, on the one client
    first, second = context(acme), context(acme)

    list(stream_turn(agent, first, "First chat: the Staples receipt."))
    list(stream_turn(agent, second, "Second chat: the taxi."))

    assert [m.content for m in model.seen[1] if isinstance(m, HumanMessage)] == ["Second chat: the taxi."]
    kept = agent.get_state({"configurable": {"thread_id": first.thread_id}}).values["messages"]
    assert [m.content for m in kept] == ["First chat: the Staples receipt.", "Hello from the first chat."]


# ─── The chat model ────────────────────────────────────────────────────────────

def test_chat_model_sends_openrouter_the_agreed_settings():
    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "gen-1", "object": "chat.completion", "created": 1,
                                         "model": "qwen/qwen3.8-27b", "system_fingerprint": None,
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "Hello."}}]})

    model = chat_model(Settings(openrouter_api_key="test-key"))
    model.client = openrouter.OpenRouter(api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(answer)))

    assert model.invoke("Hi").content == "Hello."
    assert model.request_timeout == 60_000 and model.max_retries == 2   # milliseconds, as ChatOpenRouter takes them
    [body] = sent
    assert body["max_tokens"] == 8192   # a degenerate generation is cut off, not left to run
    assert body["model"] == "qwen/qwen3.8-27b" and body["reasoning"] == {"effort": "medium"}
    # The reader's hosts, a full-precision one first and never a 4-bit one (tests/test_model_client.py), and none that
    # keeps the data.
    assert body["provider"] == {"order": ["deepinfra/bf16"], "quantizations": ["bf16", "fp16", "fp32", "fp8"],
                                "require_parameters": True, "data_collection": "deny"}


@pytest.mark.parametrize("env, route", [
    ({}, {"order": ["deepinfra/bf16"], "quantizations": ["bf16", "fp16", "fp32", "fp8"]}),
    ({"OPENROUTER_PROVIDERS": "parasail/fp8, wafer", "OPENROUTER_QUANTIZATIONS": "bf16"},
     {"order": ["parasail/fp8", "wafer"], "quantizations": ["bf16"]}),
    ({"OPENROUTER_PROVIDERS": "", "OPENROUTER_QUANTIZATIONS": ""}, {}),   # blank: left to OpenRouter, as for the reader
], ids=["defaults", "set", "blank"])
def test_the_agent_goes_to_the_hosts_the_reader_does(env, route):
    # Left to choose, OpenRouter sent reads of this one model to a 4-bit host that dropped lines: the agent must not
    # land there either, and follows the same two settings.
    settings = Settings.from_env({"OPENROUTER_API_KEY": "test-key", **env})
    assert chat_model(settings).openrouter_provider == {"require_parameters": True, "data_collection": "deny", **route}


def connected(model, answer):
    """The chat model with its OpenRouter client answering every request through `answer`, a function of the request."""
    model.client = openrouter.OpenRouter(api_key="test-key", client=httpx.Client(transport=httpx.MockTransport(answer)))
    return model


def sse(*chunks) -> bytes:
    """What OpenRouter streams back: a chunk for each (delta, finish_reason) given."""
    return b"".join(
        b"data: " + json.dumps({"id": "gen-1", "object": "chat.completion.chunk", "created": 1,
                                "model": "qwen/qwen3.8-27b",
                                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}).encode() + b"\n\n"
        for delta, finish in chunks) + b"data: [DONE]\n\n"


def test_the_agent_runs_on_the_model_that_reads_the_files():
    settings = Settings.from_env({"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "some/model",
                                  "LEDGERSYNC_AGENT_MODEL": "x/y"})   # the old variable changes nothing
    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "gen-1", "object": "chat.completion", "created": 1,
                                         "model": "some/model", "system_fingerprint": None,
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "Hello."}}]})

    connected(chat_model(settings), answer).invoke("Hi")

    assert sent[0]["model"] == ModelClient(settings).model == "some/model"


def test_reasoning_sent_the_openrouter_way_is_kept_apart_from_the_reply():
    # OpenRouter streams a reasoning model's thinking in its own fields (`reasoning`, `reasoning_details`), apart from
    # the reply's content, whichever model it is: the person never gets it as a token, and the run carries on.
    thought = "A row id is a number, not a name."
    tool_call = {"index": 0, "id": "call_1", "type": "function",
                 "function": {"name": "get_row", "arguments": '{"row_id": "the taxi"}'}}
    answers = iter([
        sse(({"role": "assistant", "reasoning": thought,
              "reasoning_details": [{"type": "reasoning.text", "text": thought, "index": 0, "format": "unknown"}]},
             None),
            ({"tool_calls": [tool_call]}, None), ({}, "tool_calls")),
        sse(({"role": "assistant", "reasoning": "The tool wants a number."}, None),
            ({"content": "Row ids are "}, None), ({"content": "numbers."}, None), ({}, "stop")),
    ])
    model = connected(chat_model(Settings(openrouter_api_key="test-key")),
                      lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                                     content=next(answers)))
    agent, ctx = offline_agent(model), context()

    events = list(stream_turn(agent, ctx, "Look at the taxi."))

    assert set(kinds(events)) == {"token"} and "".join(e.data["text"] for e in events) == "Row ids are numbers."
    assert "number, not a name" not in "".join(e.sse() for e in events)
    kept = agent.get_state({"configurable": {"thread_id": ctx.thread_id}}).values["messages"]
    assert [m.type for m in kept] == ["human", "ai", "tool", "ai"] and kept[2].status == "error"
    assert kept[1].content == "" and kept[1].additional_kwargs["reasoning_content"] == thought   # kept, not said
    assert kept[3].text == "Row ids are numbers."


def test_chat_model_needs_the_openrouter_key():
    with pytest.raises(ModelUnavailable, match="OPENROUTER_API_KEY"):
        chat_model(Settings())


def test_an_event_is_sent_as_sse():
    event = ChatEvent("step", {"id": "call_1", "text": "Opened costco-receipt-21-10.txt", "state": "done"})
    assert event.sse() == ('event: step\ndata: {"id": "call_1", "text": "Opened costco-receipt-21-10.txt", '
                           '"state": "done"}\n\n')


def test_a_held_row_is_a_documents_issue_and_never_saved_with_the_row():
    from ledgersync.agent.tools import family_of
    from ledgersync.checks import is_derived, issue
    assert family_of("needs_document") == "documents"
    assert is_derived(issue("needs_document", "Held in Suspense: needs its receipt or invoice."))


@pytest.mark.mongo
def test_a_held_row_is_in_the_documents_family_only(mongo_store, deps, acme):
    from ledgersync import books
    from ledgersync.agent.tools import _to_look_at
    add_rows(mongo_store, acme, row(date=dt.date(2026, 10, 1), gross=Decimal("300.00"), vat=Decimal("0.00"),
                                    account_code="7504", document_type="statement"), year_start=YEAR)

    [(held_row, held, families)] = _to_look_at(books.ledger(mongo_store, acme, YEAR))

    assert held is not None and [i.code for i in held_row.issues if i.code == "needs_document"]
    assert families == {"documents"}


@pytest.mark.mongo
def test_list_changes_since_accepts_z_and_offsets_and_says_when_it_cannot_read_it(mongo_store, deps, staples):
    from ledgersync.models import ChangeDraft
    change = deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user", kind="row_edited",
                                                 row_ids=[1], summary="Row 1 changed"))
    mongo_store.db.changes.update_one({"_id": change.id}, {"$set": {"created_at": "2030-01-01T12:00:00+00:00"}})
    model = ScriptedChatModel(replies=[call("list_changes", since="2030-01-01T11:00:00Z"),
                                       call("list_changes", since="2030-01-01T13:30:00+02:00"),   # 11:30 UTC
                                       call("list_changes", since="last Tuesday"), say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(staples), "What has changed?"))

    z, offset, bad = (json.loads(answered(model, n)[0].content) for n in (1, 2, 3))
    assert [c["summary"] for c in z["changes"]] == ["Row 1 changed"] and "more" not in z
    assert [c["summary"] for c in offset["changes"]] == ["Row 1 changed"]
    assert bad == {"error": "since must be an ISO date and time, for example 2026-11-04T10:00:00"}


@pytest.mark.mongo
def test_list_changes_since_says_when_there_are_more_than_it_returns(mongo_store, deps, staples):
    from ledgersync.models import ChangeDraft
    for n in range(201):
        deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user", kind="row_edited",
                                            row_ids=[1], summary=f"Change {n}"))
    model = ScriptedChatModel(replies=[call("list_changes", since="2000-01-01T00:00:00"), say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(staples), "What has changed?"))

    page = json.loads(answered(model, 1)[0].content)
    assert len(page["changes"]) == 200 and page["more"] is True


# ─── The agent in a background review ──────────────────────────────────────────

def background(client_id: int, **fields) -> ChatContext:
    return ChatContext(client_id=client_id, thread_id=uuid4().hex, year_start=YEAR, trigger="background",
                       review_id="rev1", **fields)


@pytest.mark.mongo
def test_resolve_issue_carries_the_contexts_trigger_and_mode(mongo_store, deps, staples):
    args = keep_the_receipt(mongo_store, staples)
    model = ScriptedChatModel(replies=[call("resolve_issue", **args), say("Suggested.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, background(staples, mode="suggest"), "Review."))

    [decision] = deps.records.decisions(staples)
    assert (decision.status, decision.trigger, decision.review_id) == ("suggested", "background", "rev1")
    assert json.loads(answered(model, 1)[0].content)["status"] == "suggested"
    assert not next(r for r in mongo_store.rows(staples) if r.id == args["resolution"]["drop_row_ids"][0]).tx.excluded


@pytest.mark.mongo
def test_edit_row_changes_a_row_as_the_person_said_and_its_question_goes(mongo_store, deps, staples):
    import time
    from ledgersync import questions
    receipt = next(r for r in mongo_store.rows(staples) if r.tx.document_type == "receipt")
    to = "7400" if receipt.tx.account_code != "7400" else "7504"
    asked = questions.ask(deps.records, client_id=staples, year_start=YEAR, row_ids=[receipt.id],
                          text="Which account should this go to?", why="Its account is unclear.")
    time.sleep(1.1)   # times are kept to the second
    args = dict(row_id=receipt.id, change={"account_code": to}, reason="You said to put it to that account.")
    model = ScriptedChatModel(replies=[call("edit_row", **args), call("edit_row", **args), say("Moved it.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    ctx = context(staples)

    list(stream_turn(agent, ctx, f'Answer to "{asked.text}": that account'))

    assert next(r for r in mongo_store.rows(staples) if r.id == receipt.id).tx.account_code == to
    made, again = deps.records.decisions(staples)
    assert (made.action, made.status, made.thread_id, made.row_ids) == ("edit_row", "applied", ctx.thread_id, [receipt.id])
    assert made.before == {str(receipt.id): {"account_code": receipt.tx.account_code}}
    assert made.after == {str(receipt.id): {"account_code": to}}
    assert again.status == "refused" and "already says that" in again.reason   # asked twice, changed once
    assert receipt.id in deps.records.person_rows(staples)   # the person's own change: a review leaves it to them
    questions.refresh(mongo_store, deps.records, staples, YEAR)
    assert deps.records.question(asked.id).status == "resolved"


@pytest.mark.mongo
def test_edit_row_refuses_what_the_books_cannot_take_and_a_background_review(mongo_store, deps, staples):
    receipt = next(r for r in mongo_store.rows(staples) if r.tx.document_type == "receipt")
    bad = dict(row_id=receipt.id, change={"account_code": "0000"}, reason="You said so.")
    model = ScriptedChatModel(replies=[call("edit_row", **bad), say("Couldn't.")])
    list(stream_turn(build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver()), context(staples), "Do it."))
    assert json.loads(answered(model, 1)[0].content)["status"] == "refused"

    fine = dict(row_id=receipt.id, change={"description": "Paper"}, reason="Tidier.")
    model = ScriptedChatModel(replies=[call("edit_row", **fine), say("Left it.")])
    list(stream_turn(build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver()), background(staples), "Review."))
    assert json.loads(answered(model, 1)[0].content)["status"] == "refused"
    assert next(r for r in mongo_store.rows(staples) if r.id == receipt.id).tx == receipt.tx


@pytest.mark.mongo
def test_edit_row_keeps_a_row_apart_from_one_the_person_says_is_not_the_same(mongo_store, deps, staples):
    receipt = next(r for r in mongo_store.rows(staples) if r.tx.document_type == "receipt")
    other = next(r for r in mongo_store.rows(staples) if r.id != receipt.id)
    told = dict(row_id=receipt.id, change={"not_same_as": [other.id]}, reason="You said they are different purchases.")
    stray = dict(row_id=receipt.id, change={"not_same_as": [receipt.id]}, reason="You said so.")
    model = ScriptedChatModel(replies=[call("edit_row", **told), call("edit_row", **stray), say("Kept apart.")])
    list(stream_turn(build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver()), context(staples), "Do it."))

    assert next(r for r in mongo_store.rows(staples) if r.id == receipt.id).tx.apart_from == [other.id]
    assert json.loads(answered(model, 1)[0].content)["status"] == "applied"
    assert json.loads(answered(model, 2)[0].content)["status"] == "refused"   # only another of the client's rows


def agent_question(deps, client_id: int, row_id: int):
    """A question of the agent's own about the row, asked on the first of January 2030 (for the changes after it)."""
    from ledgersync import questions
    q = questions.ask(deps.records, client_id=client_id, year_start=YEAR, row_ids=[row_id], text="Is it personal?",
                      why="Unclear.")
    deps.records.db.questions.update_one({"id": q.id}, {"$set": {"created_at": "2030-01-01T10:00:00+00:00"}})
    return q


def close_it(deps, ctx, question_id: str, **args) -> dict:
    model = ScriptedChatModel(replies=[call("close_question", question_id=question_id, reason="Answered.", **args),
                                       say("Closed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    list(stream_turn(agent, ctx, "Close it."))
    return json.loads(answered(model, 1)[0].content)


@pytest.mark.mongo
def test_close_question_after_a_persons_change_to_its_rows(mongo_store, deps, staples):
    row_id = mongo_store.rows(staples)[0].id
    q = agent_question(deps, staples, row_id)
    change = deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user", kind="row_edited",
                                                 row_ids=[row_id], summary=f"Row {row_id} changed: account 7504"))
    mongo_store.db.changes.update_one({"_id": change.id}, {"$set": {"created_at": "2030-01-01T12:00:00+00:00"}})

    result = close_it(deps, background(staples), q.id)

    assert result["status"] == "applied"
    closed = deps.records.question(q.id)
    assert (closed.status, closed.answer) == ("resolved", "Closed by the AI: Answered.")
    [d] = deps.records.decisions(staples)
    assert (d.action, d.trigger, d.review_id, d.actor) == ("close_question", "background", "rev1",
                                                           "agent:qwen/qwen3.8-27b")
    assert d.before == {"question": {"status": "open", "answer": None}} and d.after == {"question": {"status": "resolved"}}
    [quote] = d.evidence
    assert (quote.upload_id, quote.upload_name, quote.quote) == (0, "change record", change.summary)
    assert any(c.kind == "question_closed" and c.row_ids == [row_id] for c in deps.records.changes(staples))


@pytest.mark.mongo
def test_close_question_refused_without_a_change_or_document(mongo_store, deps, staples):
    row = mongo_store.rows(staples)[0]
    row_id = row.id
    q = agent_question(deps, staples, row_id)
    other = deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user", kind="row_edited",
                                                row_ids=[row_id + 100], summary="Another row changed"))
    earlier = deps.records.add_change(ChangeDraft(client_id=staples, year_start=YEAR, actor="user",
                                                  kind="row_edited", row_ids=[row_id], summary="Before it was asked"))
    for c, when in ((other, "2030-01-01T12:00:00+00:00"), (earlier, "2029-12-31T12:00:00+00:00")):
        mongo_store.db.changes.update_one({"_id": c.id}, {"$set": {"created_at": when}})

    result = close_it(deps, background(staples), q.id)

    assert result == {"status": "refused", "why": "Nothing since the question was asked answers it."}
    assert deps.records.question(q.id).status == "open"
    [d] = deps.records.decisions(staples)
    assert (d.status, d.action) == ("refused", "close_question")
    quote = close_it(deps, background(staples), q.id,
                     evidence=[{"upload_id": row.upload_id, "quote": "no such words in it"}])
    assert quote["status"] == "refused" and "isn't in" in quote["why"]
    assert deps.records.question(q.id).status == "open"


@pytest.mark.mongo
def test_get_overview_lists_background_reviews_since_the_last_chat(mongo_store, deps, staples):
    records = deps.records
    old = records.create_thread(staples, YEAR, "Earlier chat")
    mongo_store.db.chat_threads.update_one({"_id": old.id}, {"$set": {"updated_at": "2030-01-02T00:00:00+00:00"}})

    def run(when: str, summary: str, decisions=(), asked=()):
        r = records.start_review(staples, YEAR, from_seq=0, to_seq=1, trigger_summary="after a file")
        records.finish_review(r.id, status="done", decision_ids=decisions, question_ids=asked, summary=summary)
        mongo_store.db.review_runs.update_one({"_id": r.id}, {"$set": {"finished_at": when}})

    from ledgersync.models import DecisionDraft
    applied = records.append_decision(DecisionDraft(client_id=staples, year_start=YEAR, action="keep_one", rule="R2",
                                                    status="applied", actor="agent:x"), "k1")[0]
    suggested = records.append_decision(DecisionDraft(client_id=staples, year_start=YEAR, action="keep_one", rule="R2",
                                                      status="suggested", actor="agent:x"), "k2")[0]
    run("2030-01-01T00:00:00+00:00", "Before the last chat.")
    run("2030-01-03T00:00:00+00:00", "Sorted the receipt.", decisions=[applied.id, suggested.id], asked=["q1"])
    model = ScriptedChatModel(replies=[call("get_overview"), say("Hello.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, context(staples), "Hi."))

    shown = json.loads(answered(model, 1)[0].content)["background_reviews_since_last_chat"]
    assert shown == [{"ran_at": "2030-01-03T00:00:00+00:00", "summary": "Sorted the receipt.", "sorted": 1,
                      "asked": 1}]


def test_the_prompt_has_the_background_and_chat_passages():
    assert ("In a background review no person is reading. Look at what changed (list_changes) and the rows it "
            "touched; settle what the evidence supports; ask only what you must; end with one short line saying "
            "what you did.") in SYSTEM_PROMPT
    assert ("At the start of a chat, if get_overview lists background reviews since the last chat, say in one line "
            "what they did.") in SYSTEM_PROMPT


class RecordingLocks(ClientLocks):
    """The client locks, noting each client held and whether the lock was still held while the block ran."""

    def __init__(self):
        super().__init__()
        self.held: list[int] = []
        self.inside: list[int] = []

    @contextmanager
    def hold(self, client_id: int):
        with super().hold(client_id):
            self.held.append(client_id)
            self.inside.append(client_id)
            yield
        self.inside.remove(client_id)


@pytest.mark.mongo
def test_resolve_issue_and_close_question_work_under_the_client_lock(mongo_store, staples):
    locks = RecordingLocks()
    deps = AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=GridFSBlobStore(mongo_store.db),
                     locks=locks)
    args = keep_the_receipt(mongo_store, staples)
    q = agent_question(deps, staples, mongo_store.rows(staples)[0].id)
    model = ScriptedChatModel(replies=[call("resolve_issue", **args),
                                       call("close_question", question_id=q.id, reason="Answered."), say("Done.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())

    list(stream_turn(agent, background(staples, mode="suggest"), "Go."))

    assert locks.held == [staples, staples] and locks.inside == []


def test_agent_deps_have_their_own_client_locks_unless_given_one():
    assert AgentDeps(store=None, records=None, blobs=None).locks is not AgentDeps(store=None, records=None,
                                                                                    blobs=None).locks


def garbled_call() -> AIMessage:
    return AIMessage(content="", invalid_tool_calls=[{"name": "resolve_issue", "args": '{"row_id": 1,', "id": "call_x",
                                                      "error": "Invalid JSON", "type": "invalid_tool_call"}])


def test_a_last_step_whose_arguments_are_not_json_ends_with_an_error():
    events = list(stream_turn(offline_agent(ScriptedChatModel(replies=[garbled_call()])), context(), "Go."))

    assert kinds(events) == ["error"]
    assert events[0].data == {"code": "agent_failed",
                              "message": "My last step came out garbled, so I stopped. Send it again."}



def test_an_answer_cut_off_at_its_length_limit_ends_with_an_error_not_silence():
    # The 14:43 review: 6,703 of the 8,192 tokens went on thinking, and the answer came out empty.
    cut = AIMessage(content="", response_metadata={"finish_reason": "length"})
    events = list(stream_turn(offline_agent(ScriptedChatModel(replies=[cut])), context(), "Go."))

    assert kinds(events) == ["error"] and events[0].data["code"] == "cut_off"


def test_a_storage_failure_says_the_database_did_not_answer():
    from pymongo.errors import ServerSelectionTimeoutError

    from ledgersync.agent.run import STORAGE_TEXT, _failure
    event = _failure(ServerSelectionTimeoutError("No primary available for writes"))
    assert event.data == {"code": "storage_unavailable", "message": STORAGE_TEXT}


def test_the_key_is_blanked_in_the_error_a_failing_model_gives(monkeypatch):
    monkeypatch.setattr(model_retry, "time", SimpleNamespace(sleep=lambda seconds: None))
    key = "sk-or-v1-0123456789abcdef"
    model = ScriptedChatModel(then=ConnectionError(f"401 for key {key} at the provider"))
    agent = build_agent(Settings(openrouter_api_key=key),
                        AgentDeps(store=None, records=None, blobs=None), model=model, checkpointer=InMemorySaver())

    [error] = list(stream_turn(agent, context(), "Go."))

    assert error.data["code"] == "model_unavailable"
    assert key not in error.data["message"] and "401 for key *** at the provider" in error.data["message"]


def test_the_prompt_carries_the_tax_facts_the_chat_got_wrong():
    # Asked for the VAT boxes and about s455, the chat invented box meanings, a £10,000 threshold, 32.5% and 30 days.
    for said in ("Box 4: VAT reclaimed on purchases", "Box 6: total sales and other outputs, excluding VAT",
                 "nine months and one day", "There is no minimum amount", "33.75%",
                 "Never give a tax rate, a threshold or a deadline from memory"):
        assert said in " ".join(SYSTEM_PROMPT.split()), said


# ─── One read of the client for each tool call ─────────────────────────────────

@pytest.mark.mongo
def test_each_tool_call_reads_the_client_once(mongo_store, deps, acme, monkeypatch):
    # Each read is a round trip to the database, which may be far away: a tool works several figures out of one copy
    # of the client. (The trial balance tool made nineteen reads, the overview eleven.)
    from pymongo.collection import Collection
    three_clean_rows(mongo_store, acme)
    ledger_book.post(mongo_store, deps.records, acme, YEAR)
    reads = []
    for name in ("find", "aggregate"):
        real = getattr(Collection, name)
        monkeypatch.setattr(Collection, name, lambda self, *a, _real=real, **k: (
            reads.append(self.name) if self.name == "clients" else None) or _real(self, *a, **k))
    for tool, args in (("get_trial_balance", {}), ("get_overview", {}), ("get_vat_figures", {}), ("list_issues", {}),
                       ("get_row", {"row_id": mongo_store.rows(acme)[0].id})):
        model = ScriptedChatModel(replies=[call(tool, **args), say("Looked.")])
        agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
        reads.clear()
        list(stream_turn(agent, context(acme), "Look."))
        assert answered(model, 1)[0].status != "error", tool
        assert reads == ["clients"], tool


def test_a_claim_line_is_related_to_every_receipt_it_is_booked_from():
    # Jenny's TfL claim line is booked from seven charges on her TfL statement. The AI review reads a row with the
    # rows matching paired it with, so it must see all seven, and each of them the line.
    from ledgersync.agent.tools import _related
    from ledgersync.models import SavedRow, Settlement
    claim = Settlement(ref="claim", amount=Decimal("55.40"), kind="expense_claim")
    refs = [f"tfl-{k}" for k in range(7)]
    line = SavedRow(**row(description="Jenny Hogg - Transport for London", gross=Decimal("55.40"),
                          document_type="expense_claim", document_ref="claim",
                          recorded_by=Settlement(ref=refs[0], amount=Decimal("55.40")),
                          recorded_by_refs=refs).model_dump(), id=1, upload_id=176)
    receipts = [SavedRow(**row(description="TfL", gross=Decimal("6.00"), document_ref=ref,
                               claimed_in=claim).model_dump(), id=2 + k, upload_id=199)
                for k, ref in enumerate(refs)]
    rows = [line, *receipts]
    assert {r.id for r in _related(line, rows)} == {r.id for r in receipts}
    assert {r.id for r in _related(receipts[3], rows)} == {1}


# ─── offer_answer (design of 2026-11-25) ─────────────────────────────────────

def _vat_question(mongo_store, deps, client_id):
    from test_questions import opened_owing_vat
    from ledgersync import questions
    opened_owing_vat(mongo_store, client_id)
    return next(q for q in questions.refresh(mongo_store, deps.records, client_id, dt.date(2025, 4, 1))
                if q.kind == "opening_vat")


def _offer_args(q, quote="Fine to correct it this year"):
    return dict(question_id=q.id, answer={"kind": "split", "lines": [{"account": "8250", "amount": "312.00"}]},
                sources=[{"kind": "said", "quote": quote}, {"kind": "question"}], reason="As the client said.")


def _offer_turn(deps, client_id, q, text, *, trigger="chat", note=None, quote="Fine to correct it this year"):
    from ledgersync.agent.chat import _say
    model = ScriptedChatModel(replies=[call("offer_answer", **_offer_args(q, quote)), say("Done.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    ctx = ChatContext(client_id=client_id, thread_id=uuid4().hex, year_start=dt.date(2025, 4, 1), trigger=trigger)
    if note:
        _say(agent, ctx.thread_id, note, note=True)
    list(stream_turn(agent, ctx, text))
    return json.loads(answered(model, 1)[0].content)


@pytest.mark.mongo
def test_offer_answer_is_refused_outside_a_chat(mongo_store, deps, acme):
    q = _vat_question(mongo_store, deps, acme)
    result = _offer_turn(deps, acme, q, "Fine to correct it this year.", trigger="background")
    assert result["status"] == "refused" and "Only a person in a chat" in result["why"]
    assert deps.records.question(q.id).offer is None


@pytest.mark.mongo
def test_offer_answer_takes_the_persons_words_from_the_chat_not_a_note(mongo_store, deps, acme):
    q = _vat_question(mongo_store, deps, acme)
    noted = _offer_turn(deps, acme, q, "Have a look.", note="Fine to correct it this year (the app's note)")
    assert noted["status"] == "refused" and "isn't in what the person said" in noted["why"]
    made = _offer_turn(deps, acme, q, "Redland & Co left an invoice off. Fine to correct it this year.")
    assert made["status"] == "offered" and deps.records.question(q.id).offer is not None


@pytest.mark.mongo
def test_list_questions_shows_an_offer_and_the_other_open_years(mongo_store, deps, acme):
    from test_questions import books_question
    q = _vat_question(mongo_store, deps, acme)
    later = books_question(deps.records, acme, kind="opening_accruals", year_start=dt.date(2026, 4, 1),
                           text="Opening accruals of £2,400.00: which costs are they for?")
    _offer_turn(deps, acme, q, "Fine to correct it this year.")
    model = ScriptedChatModel(replies=[call("list_questions"), say("Listed.")])
    agent = build_agent(SETTINGS, deps, model=model, checkpointer=InMemorySaver())
    list(stream_turn(agent, ChatContext(client_id=acme, thread_id=uuid4().hex, year_start=dt.date(2025, 4, 1)), "List."))
    listed = {x["question_id"]: x for x in json.loads(answered(model, 1)[0].content)["questions"]}
    assert later.id in listed and listed[later.id]["year_start"] == "2026-04-01"
    assert listed[q.id]["offer"]["answer"]["lines"] == [{"account": "8250", "amount": "312.00"}]


def test_the_persons_words_leave_out_the_question_their_reply_quotes():
    # Final review, 25 Nov 2026: a card's answer is sent as 'Answer to "<question>": <words>', and the runner's as
    # "> <question>" then the words, so the app's own question passed as something the person said.
    from langchain_core.messages import HumanMessage
    from ledgersync.agent.tools import person_said
    said = person_said({"messages": [
        HumanMessage('Answer to "Opening prepayments of £6,558.46: which costs are they for?": no idea'),
        HumanMessage("> The VAT payment of £27,412.00 is £312.00 more: what was the difference for?\n\nFine to correct it"),
        HumanMessage("A note", additional_kwargs={"note": True})]})
    assert said == ["no idea", "Fine to correct it"]


def test_list_questions_keeps_a_closed_years_own_questions_in_its_chat():
    # Final review: listing every open year's books questions left out the chat year's own when that year is closed.
    from types import SimpleNamespace
    from ledgersync.agent.tools import open_questions
    from ledgersync.models import Question
    year = dt.date(2025, 4, 1)
    asked = Question(id="q1", client_id=1, year_start=year, kind="date", text="When?", why="No date.", source="rules",
                     status="open", created_at="2026-11-25T10:00:00+00:00")
    deps = SimpleNamespace(store=SimpleNamespace(get_client=lambda _: SimpleNamespace(
        closed_years=[SimpleNamespace(start=year)])), records=SimpleNamespace(questions=lambda *_: [asked]))
    listed = open_questions(deps, ChatContext(client_id=1, thread_id="t", year_start=year))["questions"]
    assert [x["question_id"] for x in listed] == ["q1"]
