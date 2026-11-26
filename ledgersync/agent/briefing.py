"""What a specialist starts its turn from (design of 2026-11-15): the state of the books as the turn began, fetched
here in code, so the specialist doesn't spend its first model calls fetching it. It is built by the functions behind
the tools (tools.overview and the rest), so it says exactly what the tools would, and it is given under the
specialist's prompt for that turn only (middleware.Specialists): the chat's memory never holds it."""
from __future__ import annotations

import json

from pydantic_core import to_jsonable_python

from .router import BOOKKEEPER, REPORTER, REVIEWER, TAX
from .tools import AgentDeps, ChatContext, changes, issues, open_questions, overview, trial_balance

MAX_BRIEFING = 24_000   # characters; over this only the overview is given, and the tools give the rest
LATEST_CHANGES = 20     # the changes the reporter is given
LEFT_OUT = "More than fits here: your tools give the rest."
_CODE_ROWS = (REVIEWER, BOOKKEEPER)   # the specialists who give a row an account, and so need the accounts listed


def _text(told: dict) -> str:
    """As JSON, money and dates as strings, with no spaces to pay for."""
    return json.dumps(to_jsonable_python(told), ensure_ascii=False, separators=(",", ":"))


def briefing(deps: AgentDeps, ctx: ChatContext) -> str:
    """The briefing for the run's specialist (ctx.specialist), as JSON. Everyone gets the overview (get_overview's
    answer; its list of accounts only for the reviewer and the bookkeeper, who code rows). Besides: the reviewer in
    a chat, the first rows that need a look (a background review's message names them itself); the bookkeeper, the
    open questions; the reporter, the open questions and the latest changes; the tax and VAT adviser, the trial
    balance. The client is read once for all of it."""
    with deps.store.reading():
        told = {"overview": overview(deps, ctx)}
        if ctx.specialist not in _CODE_ROWS:
            del told["overview"]["accounts"]
        if ctx.specialist == REVIEWER and ctx.trigger == "chat":
            told["need_a_look"] = issues(deps, ctx)
        elif ctx.specialist == BOOKKEEPER:
            told["open_questions"] = open_questions(deps, ctx)["questions"]
        elif ctx.specialist == REPORTER:
            told["open_questions"] = open_questions(deps, ctx)["questions"]
            told["latest_changes"] = changes(deps, ctx)["changes"][-LATEST_CHANGES:]
        elif ctx.specialist == TAX:
            told["trial_balance"] = trial_balance(deps, ctx)
    text = _text(told)
    if len(text) > MAX_BRIEFING:
        text = _text({"overview": told["overview"], "left_out": LEFT_OUT})
    return text
