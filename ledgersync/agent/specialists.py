"""The specialists of the accountant chat and the background review (design of 2026-11-15). Each is a part the one
agent plays for a turn: a prompt and the tools that part needs. The lead accountant is the whole agent, as it has
always been: every tool and the whole prompt. The router picks the part (router.py), the middleware plays it
(middleware.Specialists), and hand_over gives the rest of a turn back to the lead.

A specialist's prompt is cut from SYSTEM_PROMPT here, when this module loads, not written again: every line of that
prompt is there because a test round found a slip, so an edit to it reaches the specialists by itself. A line that
names a tool the specialist doesn't have is left out, unless it holds a phrase in KEEP."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .prompt import SYSTEM_PROMPT
from .router import BOOKKEEPER, LEAD, REPORTER, REVIEWER, TAX

# The agent's tools, in the order make_tools gives them (tests/test_specialists.py holds the two together).
ALL_TOOLS = ("get_overview", "list_issues", "list_rows", "get_row", "list_documents", "read_document", "resolve_issue",
             "edit_row", "ask_user", "close_question", "offer_answer", "list_questions", "list_decisions",
             "list_changes", "get_trial_balance", "get_vat_figures")
HAND_OVER = "hand_over"   # the specialists' one tool of their own: the rest of the turn goes to the lead accountant

# Lines kept though they name a tool the specialist lacks: each says what not to do, or what to tell the person.
KEEP = ("unusual_account", "Never use edit_row on your own judgement")

BRIEFED = ('What get_overview returns was fetched as this turn began and is given below under "The books now": don\'t '
           "call it again unless you have changed something since. Use get_row for a row's details, the rows it is "
           "matched with, and the decisions already made on it.")
LOOK_UPS = "When you need several look-ups that don't depend on each other, ask for them together in one step."
HANDS_OVER = ("hand_over gives the rest of this turn to the lead accountant, who has every tool. Call it straight away, "
              "before anything else, rather than attempt work outside your part or reply that you can't do it.")
NO_CARDS = ("You can't open a question card for the person: if you need something from them, ask in your reply, and "
            "never say a question was created.")
PARTS = {
    REVIEWER: "You are the reviewer: you settle what the evidence settles (dates, duplicates, records that disagree, "
              "mixed-VAT rows, VAT a document prints, who was at a meal) and ask only what it can't. If the person tells you what a row "
              "should be, or asks a tax question or for a report, call hand_over.",
    BOOKKEEPER: "You are the bookkeeper: you make the changes the person in this chat tells you to make, and nothing "
                "else. If they ask for a review of the evidence, a tax answer or a report, or haven't said what a row "
                "should be, call hand_over.",
    TAX: "You are the tax and VAT adviser: you answer tax questions from the books and the facts below, and change "
         "nothing. If the person asks for a change to the books or a review of the evidence, or answers one of the "
         "books' own questions (the VAT difference, the opening prepayments or accruals, a bad debt), call hand_over.",
    REPORTER: "You are the reporter: you say where the books stand (what changed, what needs the person, the balances) "
              "and change nothing. If the person asks for a change to the books, a review of the evidence or a tax "
              "answer, or answers one of the books' own questions (the VAT difference, the opening prepayments or "
              "accruals, a bad debt), call hand_over.",
}
_HOW, _FINISHING, _STARTS = "How you work", "Finishing", "- Start with get_overview"
# Lines of other sections every specialist but the reviewer needs too (the reviewer has their sections whole).
_ROW_IDS, _CLEAN_ROWS, _CHAT_START = ("Use only row ids that a tool gave you", "To see rows that have no issues",
                                      "At the start of a chat")


@dataclass(frozen=True)
class Profile:
    """A part the agent plays for a turn: what the chat says while it works, the tools it is offered (in the agent's
    order) and its system prompt."""
    name: str
    status: str
    tools: tuple[str, ...]
    prompt: str


def sections(prompt: str) -> tuple[str, dict[str, list[str]]]:
    """The prompt's opening paragraph and, under each heading in order, its lines (each "- ..."). ValueError when a
    section holds a line that isn't one, so a prompt edited out of this shape is noticed here."""
    opening, *blocks = prompt.rstrip("\n").split("\n\n")
    parts: dict[str, list[str]] = {}
    for block in blocks:
        heading, *lines = block.split("\n")
        if heading.startswith("- ") or not lines or not all(line.startswith("- ") for line in lines):
            raise ValueError(f"The prompt's section {heading[:40]!r} isn't a heading over lines that start '- '.")
        parts[heading] = lines
    return opening, parts


def whole(opening: str, parts: dict[str, list[str]]) -> str:
    """A prompt of the opening paragraph and the sections, as sections() reads one."""
    return "\n\n".join([opening, *("\n".join([heading, *lines]) for heading, lines in parts.items())]) + "\n"


def _one(parts: dict[str, list[str]], phrase: str) -> str:
    """The one line of the prompt that holds the phrase; ValueError when none or several do."""
    found = [line for lines in parts.values() for line in lines if phrase in line]
    if len(found) != 1:
        raise ValueError(f"{phrase!r} picks {'no line' if not found else 'more than one line'} of the agent's prompt.")
    return found[0]


def _has(line: str, tools: tuple[str, ...]) -> bool:
    """Whether the specialist can do what the line says: it names no tool the specialist lacks, or is kept anyway."""
    return any(phrase in line for phrase in KEEP) or not any(
        re.search(rf"\b{name}\b", line) for name in ALL_TOOLS if name not in tools)


def _prompt(name: str, tools: tuple[str, ...], headings: tuple[str, ...], also: tuple[str, ...] = ()) -> str:
    """The specialist's prompt: the opening paragraph, its part, how it works (starting from the briefing), the
    sections named, and how to finish."""
    opening, parts = sections(SYSTEM_PROMPT)
    if sum(line.startswith(_STARTS) for line in parts[_HOW]) != 1:
        raise ValueError("The agent's prompt no longer says to start with get_overview in one line of How you work.")
    how = [f"- {BRIEFED}" if line.startswith(_STARTS) else line for line in parts[_HOW]]
    how += [_one(parts, phrase) for phrase in also] + [f"- {LOOK_UPS}"]
    part = [PARTS[name], HANDS_OVER] + ([NO_CARDS] if "ask_user" not in tools else [])
    cut = {"Your part": [f"- {line}" for line in part], _HOW: how,
           **{heading: parts[heading] for heading in headings}, _FINISHING: parts[_FINISHING]}
    return whole(opening, {heading: [line for line in lines if _has(line, tools)] for heading, lines in cut.items()})


def _profile(name: str, status: str, tools: set[str], headings: tuple[str, ...], also: tuple[str, ...] = ()) -> Profile:
    offered = tuple(t for t in ALL_TOOLS if t in tools or t == "get_overview") + (HAND_OVER,)
    return Profile(name, status, offered, _prompt(name, offered, headings, also))


_RULES = "What the rules already do"
PROFILES: dict[str, Profile] = {
    LEAD: Profile(LEAD, "Working on it…", ALL_TOOLS, SYSTEM_PROMPT),
    REVIEWER: _profile(REVIEWER, "Reviewing the books…",
                       {"list_issues", "list_rows", "get_row", "list_documents", "read_document", "resolve_issue",
                        "ask_user", "close_question", "offer_answer", "list_questions", "list_decisions",
                        "list_changes"},
                       ("Evidence", "Resolving", _RULES, "Background reviews")),
    BOOKKEEPER: _profile(BOOKKEEPER, "Making the change…",
                         {"list_issues", "list_rows", "get_row", "edit_row", "offer_answer", "list_questions"},
                         ("Doing what the person tells you", _RULES), (_ROW_IDS, _CHAT_START)),
    TAX: _profile(TAX, "Working out the tax…", {"list_rows", "get_row", "get_trial_balance", "get_vat_figures"},
                  ("Tax questions", _RULES), (_ROW_IDS, _CLEAN_ROWS, _CHAT_START)),
    REPORTER: _profile(REPORTER, "Looking it up…",
                       {"list_issues", "list_rows", "get_row", "list_documents", "list_questions", "list_decisions",
                        "list_changes", "get_trial_balance"},
                       (_RULES,), (_ROW_IDS, _CLEAN_ROWS, _CHAT_START)),
}


def profile_of(ctx: Optional[object]) -> Profile:
    """The part a run is playing, from its context (ChatContext.specialist); the lead accountant when it has no
    context or names no specialist."""
    return PROFILES.get(getattr(ctx, "specialist", LEAD), PROFILES[LEAD])
