"""Which specialist takes a turn (design of 2026-11-15), worked out from the message in code: no model call is spent
on it. The first rule that fits wins. A message no rule places stays with the specialist of the turn before, or goes
to the lead accountant, which is the whole agent: a rule that misses costs speed, never correctness."""
from __future__ import annotations

import re
from typing import Optional

LEAD, REVIEWER, BOOKKEEPER, TAX, REPORTER = "lead", "reviewer", "bookkeeper", "tax", "reporter"

# What the chat page sends for an answer typed on a question card (QuestionCard.tsx).
_ANSWER = 'answer to "'
# The chat page's suggested prompts (chat/[threadId]/page.tsx), and who takes each.
_SUGGESTED = {"what needs my attention?": REPORTER, "show the trial balance": REPORTER,
              "review the documents i'm adding": REVIEWER}
# A message that tells the agent what a row should be: it opens with what to do, or says a warning is fine or that
# the person holds the document.
_INSTRUCTION = re.compile(
    r"^(?:please |can you |could you )?(?:put|move|change|set|recode|code|book|reclaim|mark|accept|use|switch|update|"
    r"correct)\b|\b(?:is|are) fine\b|'s fine\b|\bi have the (?:vat )?(?:invoice|receipt)\b")
_QUESTION = re.compile(r"\?\s*$|^(?:what|why|how|can|could|is|are|does|do|should|when|which|who|will|would)\b")
_TAX = re.compile(r"\b(?:vat|box \d|boxes|dividends?|corporation tax|director'?s'? loan|s455|reverse charge|"
                  r"depreciation|accruals?|prepayments?|journals?|allowable|disallowable|capital allowances?|tax)\b")
_STATE = re.compile(r"\b(?:what(?:'s| is| has)? changed|changes|summary|summarise|summarize|overview|balanced?|"
                    r"balances|how much|how many|outstanding|unpaid|owes?|owed|profit|totals?)\b")
_REVIEW = re.compile(r"\b(?:review|check|go through|sort out|look (?:at|over|through)|duplicates?|issues?|problems?|"
                     r"fix|resolve|tidy)\b")


def route(trigger: str, text: str, has_files: bool = False, previous: Optional[str] = None) -> str:
    """The specialist for a turn. trigger: "chat" or "background"; text: the person's message (the review's own, in
    the background); has_files: files came with it; previous: the specialist of the chat's turn before, which keeps
    a follow-up no rule places ("yes", "Travel", "Continue")."""
    if trigger == "background":
        return REVIEWER
    said = " ".join(text.lower().split())
    if said.startswith(_ANSWER):
        return BOOKKEEPER
    if has_files:
        return REVIEWER
    if said in _SUGGESTED:
        return _SUGGESTED[said]
    if _INSTRUCTION.search(said):
        return BOOKKEEPER
    if _QUESTION.search(said) and _TAX.search(said):
        return TAX
    if _STATE.search(said):
        return REPORTER
    if _REVIEW.search(said):
        return REVIEWER
    return previous or LEAD
