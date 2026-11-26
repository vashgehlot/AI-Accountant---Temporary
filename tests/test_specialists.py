"""The specialists of the accountant chat (design of 2026-11-15): each one's tools and prompt, the middleware that
runs a turn as its specialist, handing a turn over to the lead accountant, and the briefing a specialist starts from."""
import re
from types import SimpleNamespace

import pytest

from ledgersync.agent.prompt import SYSTEM_PROMPT
from ledgersync.agent.router import BOOKKEEPER, LEAD, REPORTER, REVIEWER, TAX
from ledgersync.agent.specialists import (ALL_TOOLS, BRIEFED, HAND_OVER, HANDS_OVER, KEEP, LOOK_UPS, NO_CARDS, PARTS,
                                          PROFILES, profile_of, sections, whole)

SPECIALISTS = (REVIEWER, BOOKKEEPER, TAX, REPORTER)
CHANGES_THE_BOOKS = {"resolve_issue", "edit_row", "ask_user", "close_question"}


def bullets(prompt: str) -> list[str]:
    return [line for line in prompt.split("\n") if line.startswith("- ")]


# ─── Their tools and prompts ───────────────────────────────────────────────────

def test_the_prompt_splits_into_its_sections_and_goes_back_together_unchanged():
    opening, parts = sections(SYSTEM_PROMPT)
    assert opening.startswith("You are the client's accountant.")
    assert list(parts) == ["How you work", "Evidence", "Resolving", "Doing what the person tells you",
                           "What the rules already do", "Tax questions", "Background reviews", "Finishing"]
    assert whole(opening, parts) == SYSTEM_PROMPT


def test_the_lead_accountant_is_the_whole_agent():
    lead = PROFILES[LEAD]
    assert lead.prompt is SYSTEM_PROMPT and lead.tools == ALL_TOOLS and HAND_OVER not in lead.tools
    assert lead.status == "Working on it…"
    assert profile_of(None) is lead and profile_of(SimpleNamespace(specialist="nobody")) is lead
    assert profile_of(SimpleNamespace(specialist=TAX)) is PROFILES[TAX]


def test_each_specialist_has_its_own_tools_in_the_agents_order_and_can_hand_over():
    assert {name: PROFILES[name].tools for name in SPECIALISTS} == {
        REVIEWER: ("get_overview", "list_issues", "list_rows", "get_row", "list_documents", "read_document",
                   "resolve_issue", "ask_user", "close_question", "offer_answer", "list_questions", "list_decisions",
                   "list_changes", "hand_over"),
        BOOKKEEPER: ("get_overview", "list_issues", "list_rows", "get_row", "edit_row", "offer_answer", "list_questions",
                     "hand_over"),
        TAX: ("get_overview", "list_rows", "get_row", "get_trial_balance", "get_vat_figures", "hand_over"),
        REPORTER: ("get_overview", "list_issues", "list_rows", "get_row", "list_documents", "list_questions",
                   "list_decisions", "list_changes", "get_trial_balance", "hand_over"),
    }
    assert {name: PROFILES[name].status for name in SPECIALISTS} == {
        REVIEWER: "Reviewing the books…", BOOKKEEPER: "Making the change…", TAX: "Working out the tax…",
        REPORTER: "Looking it up…"}


def test_only_the_reviewer_and_the_bookkeeper_can_change_the_books_each_in_its_own_way():
    assert {name for name in SPECIALISTS if CHANGES_THE_BOOKS & set(PROFILES[name].tools)} == {REVIEWER, BOOKKEEPER}
    assert "edit_row" not in PROFILES[REVIEWER].tools            # never on its own judgement
    assert CHANGES_THE_BOOKS & set(PROFILES[BOOKKEEPER].tools) == {"edit_row"}   # only what the person says


def test_no_specialist_is_told_to_use_a_tool_it_does_not_have():
    for name in SPECIALISTS:
        profile = PROFILES[name]
        for bullet in bullets(profile.prompt):
            if any(phrase in bullet for phrase in KEEP):
                continue
            named = [t for t in ALL_TOOLS if t not in profile.tools and re.search(rf"\b{t}\b", bullet)]
            assert not named, (name, named, bullet[:90])


def test_each_specialists_prompt_says_its_part_and_how_it_starts():
    for name in SPECIALISTS:
        prompt = PROFILES[name].prompt
        assert prompt.startswith("You are the client's accountant.") and prompt.endswith("don't use markdown.\n")
        for said in (PARTS[name], HANDS_OVER, BRIEFED, LOOK_UPS, "name a row by what it is",
                     "Never state a figure, a date or a name that no tool returned."):
            assert said in prompt, (name, said[:50])
        assert "Start with get_overview" not in prompt
        assert (NO_CARDS in prompt) == (name != REVIEWER)        # only the reviewer can open a question card
        assert len(prompt) < len(SYSTEM_PROMPT)


def test_each_specialist_keeps_the_rules_of_its_own_work_and_not_the_others():
    has = lambda name, said: said in PROFILES[name].prompt
    quote, resolve = "Quote evidence exactly as the document prints it", "Call resolve_issue only for a change"
    told, boxes = "Never use edit_row on your own judgement", "The VAT return has nine boxes"
    assert [has(n, quote) for n in SPECIALISTS] == [True, False, False, False]
    assert [has(n, resolve) for n in SPECIALISTS] == [True, False, False, False]
    assert [has(n, told) for n in SPECIALISTS] == [False, True, False, False]
    assert [has(n, boxes) for n in SPECIALISTS] == [False, False, True, False]
    # what the rules already do is for all of them, less the lines about tools one doesn't have
    for name in SPECIALISTS:
        assert has(name, "is held in 1250 Payment Processor Clearing") and has(name, "issue unusual_account")
    totals = "use the account's line in get_trial_balance"
    assert [has(n, totals) for n in SPECIALISTS] == [False, False, True, True]
    asking = "Use ask_user only for what the evidence can't settle"
    assert [has(n, asking) for n in SPECIALISTS] == [True, False, False, False]
    reviews = "At the start of a chat, if get_overview lists background reviews"
    assert all(has(n, reviews) for n in SPECIALISTS)


def test_a_phrase_that_no_longer_picks_one_line_of_the_prompt_is_an_error():
    from ledgersync.agent.specialists import _one
    _, parts = sections(SYSTEM_PROMPT)
    assert _one(parts, "Use only row ids that a tool gave you").startswith("- Use only row ids")
    with pytest.raises(ValueError, match="no line"):
        _one(parts, "a line the prompt never had")
    with pytest.raises(ValueError, match="more than one"):
        _one(parts, "resolve_issue")


# ─── Playing the part ──────────────────────────────────────────────────────────

from agent_fakes import ScriptedChatModel, call, say   # noqa: E402
from langchain_core.messages import ToolMessage   # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver   # noqa: E402
from pydantic import Field   # noqa: E402

from ledgersync.agent import AgentDeps, build_agent   # noqa: E402
from ledgersync.agent.middleware import BOOKS_NOW   # noqa: E402
from ledgersync.agent.run import stream_turn   # noqa: E402
from ledgersync.agent.tools import ChatContext, make_tools   # noqa: E402
from ledgersync.config import Settings   # noqa: E402

import datetime as dt   # noqa: E402
from uuid import uuid4   # noqa: E402

YEAR = dt.date(2026, 4, 1)
NO_DATABASE = dict(store=None, records=None, blobs=None)


class Watched(ScriptedChatModel):
    """A scripted model that also keeps the tools each call was offered, by name."""
    offered: list = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        super().bind_tools(tools, tool_choice=tool_choice, **kwargs)
        self.offered.append(list(self.tools))
        return self


def playing(specialist: str, *replies, briefing: str = "", **more):
    """Runs one turn as the specialist on a scripted model, with no database behind the tools: the model, the
    run's context, and the events."""
    model = Watched(replies=list(replies))
    agent = build_agent(Settings(), AgentDeps(**NO_DATABASE), model=model, checkpointer=InMemorySaver())
    ctx = ChatContext(client_id=1, thread_id=uuid4().hex, year_start=YEAR, specialist=specialist, briefing=briefing,
                      **more)
    return model, ctx, list(stream_turn(agent, ctx, "Look."))


def sent(model, n: int) -> str:
    """The system prompt model call n was sent."""
    return model.seen[n][0].content


def answers(model, n: int) -> list[ToolMessage]:
    """The tool results model call n was given since the model last spoke."""
    messages = model.seen[n]
    last = next(k for k in range(len(messages) - 1, -1, -1) if messages[k].type == "ai")
    return [m for m in messages[last + 1:] if isinstance(m, ToolMessage)]


def test_the_agents_tools_are_the_ones_the_specialists_are_cut_from():
    assert [t.name for t in make_tools(AgentDeps(**NO_DATABASE), actor="agent:test")] == [*ALL_TOOLS, HAND_OVER]


def test_the_lead_accountant_is_sent_the_whole_prompt_and_every_tool_as_the_agent_always_was():
    model, ctx, _ = playing(LEAD, say("Done."), briefing='{"overview": {}}')
    assert sent(model, 0) == SYSTEM_PROMPT and model.offered == [list(ALL_TOOLS)]
    assert ChatContext(client_id=1, thread_id="t", year_start=YEAR).specialist == LEAD   # unless a turn is routed


@pytest.mark.parametrize("name", SPECIALISTS)
def test_a_specialist_is_sent_its_own_prompt_with_the_briefing_and_only_its_tools(name):
    model, _, _ = playing(name, say("Done."), briefing='{"overview": {"rows": 8}}')
    assert sent(model, 0) == PROFILES[name].prompt + BOOKS_NOW + '{"overview": {"rows": 8}}'
    assert model.offered == [list(PROFILES[name].tools)]
    bare, _, _ = playing(name, say("Done."))
    assert sent(bare, 0) == PROFILES[name].prompt        # no briefing: nothing is added


def test_a_tool_outside_a_specialists_part_is_refused_before_it_runs():
    # With no database behind them, a tool that ran would fail on it: the refusal comes first.
    model, _, events = playing(REPORTER, call("ask_user", row_ids=[1], question="Is this right?", why="To be sure."),
                               say("I can't ask that."))
    [refused] = answers(model, 1)
    assert refused.status == "error"
    assert refused.content == ("Error: ask_user isn't one of your tools in this turn. Call hand_over if the request "
                               "needs it.")
    assert [e.type for e in events if e.type == "step"] == []      # nothing ran, so no step is shown
    model, _, _ = playing(TAX, call("list_questions"), say("Done."))
    assert answers(model, 1)[0].content.startswith("Error: list_questions isn't one of your tools")


def test_handing_over_gives_the_rest_of_the_turn_to_the_lead_accountant():
    model, ctx, events = playing(REPORTER, call("hand_over", why="They want a row changed."), say("Changed."),
                                 briefing='{"overview": {}}')
    assert model.offered == [list(PROFILES[REPORTER].tools), list(ALL_TOOLS)]
    assert sent(model, 0).startswith(PROFILES[REPORTER].prompt) and sent(model, 1) == SYSTEM_PROMPT
    assert (ctx.specialist, ctx.handed_over) == (LEAD, True)
    [handed] = answers(model, 1)
    assert handed.status != "error" and "lead accountant" in handed.content
    assert [e.data["text"] for e in events if e.type == "step"][-1] == "Passed to the lead accountant"


def test_the_lead_accountant_has_no_one_to_hand_over_to():
    model, ctx, _ = playing(LEAD, call("hand_over", why="Not mine."), say("Done."))
    assert answers(model, 1)[0].content == "Error: There is no tool called hand_over. Use one of the tools you were given."
    assert not ctx.handed_over



# ─── The briefing ──────────────────────────────────────────────────────────────

import json   # noqa: E402
from decimal import Decimal   # noqa: E402

from helpers import add_rows, row   # noqa: E402
from pydantic_core import to_jsonable_python   # noqa: E402

from ledgersync.agent import briefing as briefing_module   # noqa: E402
from ledgersync.agent.briefing import briefing   # noqa: E402
from ledgersync.agent.tools import changes, issues, open_questions, overview, trial_balance   # noqa: E402
from ledgersync.blobs import MemoryBlobStore   # noqa: E402
from ledgersync.records import AgentRecords   # noqa: E402

YEAR_1 = dt.date(2025, 4, 1)   # acme's first year


@pytest.fixture
def books_with_a_held_line(mongo_store, acme):
    """Acme with one £240.00 bank line to Trainline that has no receipt: held in Suspense, so it needs a look."""
    add_rows(mongo_store, acme, row(date=dt.date(2025, 7, 1), gross=Decimal("240.00"), account_code="7400",
                                    document_type="statement", counterparty="Trainline", description="TRAINLINE"),
             year_start=YEAR_1)
    return AgentDeps(store=mongo_store, records=AgentRecords(mongo_store.db), blobs=MemoryBlobStore())


@pytest.mark.mongo
def test_the_briefing_says_what_the_tools_would_for_each_specialists_work(books_with_a_held_line, acme):
    deps = books_with_a_held_line

    def told(name: str, trigger: str = "chat"):
        ctx = ChatContext(client_id=acme, thread_id="t", year_start=YEAR_1, specialist=name, trigger=trigger)
        return json.loads(briefing(deps, ctx)), ctx

    as_json = to_jsonable_python
    whole_overview = as_json(overview(deps, ChatContext(client_id=acme, thread_id="t", year_start=YEAR_1)))
    less = {k: v for k, v in whole_overview.items() if k != "accounts"}   # for those who code no rows
    assert whole_overview["need_a_look"] == {"documents": 1} and whole_overview["accounts"]

    reviewer, ctx = told(REVIEWER)
    assert reviewer == {"overview": whole_overview, "need_a_look": as_json(issues(deps, ctx))}
    assert [r["gross"] for r in reviewer["need_a_look"]["rows"]] == ["240.00"]
    assert told(REVIEWER, "background")[0] == {"overview": whole_overview}   # its message names the issues itself
    bookkeeper, ctx = told(BOOKKEEPER)
    assert bookkeeper == {"overview": whole_overview, "open_questions": as_json(open_questions(deps, ctx)["questions"])}
    reporter, ctx = told(REPORTER)
    assert reporter == {"overview": less, "open_questions": as_json(open_questions(deps, ctx)["questions"]),
                        "latest_changes": as_json(changes(deps, ctx)["changes"])}
    tax, ctx = told(TAX)
    assert tax == {"overview": less, "trial_balance": as_json(trial_balance(deps, ctx))}


@pytest.mark.mongo
def test_a_briefing_too_long_to_give_keeps_the_overview_and_says_the_tools_have_the_rest(books_with_a_held_line, acme,
                                                                                       monkeypatch):
    monkeypatch.setattr(briefing_module, "MAX_BRIEFING", 200)
    ctx = ChatContext(client_id=acme, thread_id="t", year_start=YEAR_1, specialist=REVIEWER)
    told = json.loads(briefing(books_with_a_held_line, ctx))
    assert set(told) == {"overview", "left_out"} and "tools" in told["left_out"]


@pytest.mark.mongo
def test_the_reporters_briefing_gives_only_the_latest_twenty_changes(books_with_a_held_line, acme):
    from ledgersync.models import ChangeDraft
    deps = books_with_a_held_line
    for n in range(25):
        deps.records.add_change(ChangeDraft(client_id=acme, year_start=YEAR_1, actor="user", kind="row_edited",
                                            row_ids=[1], summary=f"Change {n}"))
    ctx = ChatContext(client_id=acme, thread_id="t", year_start=YEAR_1, specialist=REPORTER)
    latest = json.loads(briefing(deps, ctx))["latest_changes"]
    assert [c["summary"] for c in latest] == [f"Change {n}" for n in range(5, 25)]


def test_a_reply_to_a_books_question_can_be_answered_whoever_takes_the_turn():
    # Final review, 25 Nov 2026: a reply with its document attached goes to the reviewer, and one with a VAT word and
    # "?" to the tax adviser: neither could fill in the books question's answer, so it stayed open.
    assert "offer_answer" in PROFILES[REVIEWER].tools and "offer_answer" in PROFILES[REVIEWER].prompt
    for name in (TAX, REPORTER):
        assert "answers one of the books' own questions" in PROFILES[name].prompt, name
