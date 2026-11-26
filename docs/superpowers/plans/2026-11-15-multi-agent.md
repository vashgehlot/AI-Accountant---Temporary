# Specialist Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each chat turn and background review is run by one specialist (reviewer, bookkeeper, tax and VAT adviser,
reporter) with its own prompt, tools and a briefing, behind a setting that ships as `single` (today's agent).

**Architecture:** One compiled agent, as now. A router in code picks the turn's specialist and puts it on the run's
context; a middleware swaps in that specialist's prompt plus a briefing and offers only its tools on every model
call, and refuses a tool call outside them. `hand_over` gives the rest of a turn to the lead accountant, which is
today's agent unchanged.

**Tech Stack:** Python 3.11, LangChain 1.4.6 `create_agent` middleware (`ModelRequest.override`), LangGraph, pytest.

**Spec:** `docs/superpowers/specs/2026-11-15-multi-agent-design.md`

**Changed after the build (15 Nov, at the user's request):** Task 1's setting was removed, so specialists are
always on, and the models by effort of Tasks 3 to 5 were removed, so every agent runs on the one chat model.
`Settings.agents`, `Profile.effort`, `build_agent(models=)`, `chat_model(effort=)` and `TurnRecord.kept()` no longer
exist; a turn's record always keeps its specialist.

## Global Constraints

- With `LEDGERSYNC_AGENTS=single` (the default) the model is sent exactly what it is sent today: `SYSTEM_PROMPT`
  and the 15 tools in the same order. Every existing test passes unchanged.
- The rules and services (`resolutions`, `questions`, `evidence_rules`, posting) are not touched.
- A read-only specialist (tax, reporter) can never run `resolve_issue`, `edit_row`, `ask_user` or `close_question`:
  refused in code, not by the prompt.
- Specialist prompts are derived from `SYSTEM_PROMPT` at import, not copied: an edit to `SYSTEM_PROMPT` reaches them.
- No new events for the chat page: only the text of `status` changes.
- No live model call in any test. Live eval runs need the user's say-so each time.
- Nothing is committed unless the user asks.

## Changes from the spec, made while planning

- Every specialist also has `get_overview`. The prompt names it in several rules; the briefing holds what it returned
  as the turn began, so the first call is saved without rewriting those rules.
- A message no rule places stays with the specialist of the turn before ("yes", "Travel", "Continue"); the lead
  accountant when there is none or that turn was handed over.
- If the briefing can't be built (rows that need fixing block the figures), the turn goes to the lead accountant.
- One line is added to the specialists' "How you work": ask for look-ups that don't depend on each other together.

## Review Focus

1. A follow-up of one word ("yes", "Travel") after a specialist asked something: stays with that specialist.
2. A specialist asked for work outside its part: hands over, and the lead finishes the turn with every tool.
3. A year whose figures can't be worked out (a row that can't post): the turn still runs, as the lead.
4. A chat reopened after the setting changes: old turn records without `specialist` still load.
5. A message that is both an instruction and a tax word ("reclaim the VAT on the hotel"): the bookkeeper's.

Each is pinned by a test in the task that owns the code (Tasks 2, 4, 5, 5, 2).

---

### Task 1: The setting

**Files:** Modify `ledgersync/config.py`, `.env.example`; Test `tests/test_config.py`.

**Produces:** `Settings.agents: str` — `"single"` (default) or `"specialists"`; env `LEDGERSYNC_AGENTS`; any other
value reads as `"single"`.

- [ ] Test: `Settings.from_env({}).agents == "single"`; `{"LEDGERSYNC_AGENTS": " Specialists "}` gives
      `"specialists"`; `{"LEDGERSYNC_AGENTS": "many"}` gives `"single"`.
- [ ] Add the field, the `ENV_NAMES` entry and the commented `.env.example` line `# LEDGERSYNC_AGENTS=single`.
- [ ] Run `pytest tests/test_config.py -q`: all pass.

### Task 2: The router

**Files:** Create `ledgersync/agent/router.py`; Test `tests/test_router.py`.

**Produces:** `LEAD, REVIEWER, BOOKKEEPER, TAX, REPORTER = "lead", "reviewer", "bookkeeper", "tax", "reporter"` and
`route(trigger: str, text: str, has_files: bool = False, previous: Optional[str] = None) -> str`.

First rule that fits wins (text lower-cased, whitespace collapsed):
1. `trigger == "background"`: reviewer.
2. starts with `answer to "`: bookkeeper.
3. `has_files`: reviewer.
4. `what needs my attention?`, `show the trial balance`: reporter; `review the documents i'm adding`: reviewer.
5. an instruction: optional `please|can you|could you`, then `put|move|change|set|recode|code|book|reclaim|mark|
   accept|use|switch|update|correct`; or contains `is fine`, `are fine`, `'s fine`, `i have the vat invoice`,
   `i have the invoice`, `i have the receipt`: bookkeeper.
6. a question (ends `?` or starts with `what|why|how|can|could|is|are|does|do|should|when|which|who|will|would`)
   with a tax word (`vat`, `box <n>`, `dividend`, `corporation tax`, `director's loan`, `s455`, `reverse charge`,
   `depreciation`, `accrual`, `prepayment`, `journal`, `allowable`, `capital allowance`, `tax`): tax.
7. a state-of-the-books word (`what changed`, `what's changed`, `what has changed`, `summary`, `summarise`,
   `overview`, `balance`, `how much`, `how many`, `outstanding`, `unpaid`, `owes`, `owed`, `profit`, `total`):
   reporter.
8. a review word (`review`, `check`, `go through`, `sort out`, `look at`, `look over`, `look through`,
   `duplicate`, `issue`, `problem`, `fix`, `resolve`, `tidy`): reviewer.
9. otherwise `previous or LEAD`.

- [ ] Test: one table, `(trigger, text, has_files, previous) -> name`, covering each rule, plus:
      `"Reclaim the VAT on the hotel"` bookkeeper; `"Can I reclaim VAT on a van?"` tax; `"Can you move the Shell
      receipt to motor expenses?"` bookkeeper; `"Check the VAT on the Booker invoice"` reviewer; `"Why is the bank
      £499 out?"` lead; `"yes"` with `previous="bookkeeper"` bookkeeper and with none lead; `"Continue"` with
      `previous="reviewer"` reviewer; a background message full of tax words reviewer.
- [ ] Implement with compiled regular expressions, word boundaries on every word list.
- [ ] Run `pytest tests/test_router.py -q`.

### Task 3: The specialists' prompts and tools

**Files:** Create `ledgersync/agent/specialists.py`; Test `tests/test_specialists.py`.

**Consumes:** `SYSTEM_PROMPT` (unchanged), the names from Task 2.

**Produces:**
- `ALL_TOOLS: tuple[str, ...]` — the 15 tool names in `make_tools` order; `HAND_OVER = "hand_over"`.
- `@dataclass(frozen=True) Profile(name, status, tools: tuple[str, ...], prompt: str, effort: str = "medium")`.
- `PROFILES: dict[str, Profile]`; `profile_of(ctx) -> Profile` (the lead for `None` or an unknown name).
- `sections(prompt: str) -> tuple[str, dict[str, list[str]]]` — the opening paragraph, and each heading's bullets.

Values:

| name | status | tools (besides `get_overview` and `hand_over`) | effort |
|---|---|---|---|
| lead | `Working on it…` | all 15, no `hand_over`; `prompt is SYSTEM_PROMPT` | medium |
| reviewer | `Reviewing the books…` | list_issues, list_rows, get_row, list_documents, read_document, resolve_issue, ask_user, close_question, list_questions, list_decisions, list_changes | medium |
| bookkeeper | `Making the change…` | list_issues, list_rows, get_row, edit_row, list_questions | low |
| tax | `Working out the tax…` | list_rows, get_row, get_trial_balance, get_vat_figures | medium |
| reporter | `Looking it up…` | list_issues, list_rows, get_row, list_documents, list_questions, list_decisions, list_changes, get_trial_balance | low |

Each profile's `tools` is kept in `make_tools` order, `hand_over` last.

A specialist's prompt is: the opening paragraph; `Your part` (its two or three lines, below); `How you work`; its
sections; `Finishing`. From each section a bullet is dropped when it names a tool the specialist lacks, unless it
contains a keep phrase: `unusual_account`, `Never use edit_row on your own judgement`. In `How you work` the bullet
that starts `Start with get_overview` is replaced by the briefed line, and the look-ups line is added last.

| name | sections | also these bullets, by phrase |
|---|---|---|
| reviewer | Evidence; Resolving; What the rules already do; Background reviews | |
| bookkeeper | Doing what the person tells you; What the rules already do | `Use only row ids that a tool gave you`; `At the start of a chat` |
| tax | Tax questions; What the rules already do | `Use only row ids that a tool gave you`; `To see rows that have no issues`; `At the start of a chat` |
| reporter | What the rules already do | the same three as tax |

A phrase that matches no bullet, or more than one, raises at import, so an edit to `SYSTEM_PROMPT` can't drop a
line unnoticed.

Exact copy:
- Briefed line: `What get_overview returns was fetched as this turn began and is given below under "The books now":
  don't call it again unless you have changed something since. Use get_row for a row's details, the rows it is
  matched with, and the decisions already made on it.`
- Look-ups line: `When you need several look-ups that don't depend on each other, ask for them together in one step.`
- Hand-over line (all four): `hand_over gives the rest of this turn to the lead accountant, who has every tool.
  Call it straight away, before anything else, rather than attempt work outside your part or reply that you can't
  do it.`
- No-cards line (bookkeeper, tax, reporter): `You can't open a question card for the person: if you need something
  from them, ask in your reply, and never say a question was created.`
- Reviewer: `You are the reviewer: you settle what the evidence settles (dates, duplicates, records that disagree,
  mixed-VAT rows, VAT a document prints) and ask only what it can't. If the person tells you what a row should be,
  or asks a tax question or for a report, call hand_over.`
- Bookkeeper: `You are the bookkeeper: you make the changes the person in this chat tells you to make, and nothing
  else. If they ask for a review of the evidence, a tax answer or a report, or haven't said what a row should be,
  call hand_over.`
- Tax: `You are the tax and VAT adviser: you answer tax questions from the books and the facts below, and change
  nothing. If the person asks for a change to the books or a review of the evidence, call hand_over.`
- Reporter: `You are the reporter: you say where the books stand (what changed, what needs the person, the
  balances) and change nothing. If the person asks for a change to the books, a review of the evidence or a tax
  answer, call hand_over.`

- [ ] Tests: `PROFILES["lead"].prompt is SYSTEM_PROMPT` and its tools are `ALL_TOOLS`; no specialist bullet names
      a tool it lacks except by a keep phrase; no specialist prompt contains `Start with get_overview`; each
      contains its part line, the briefed line, `name a row by what it is` and `don't use markdown`; reviewer has
      `Quote evidence exactly`; tax has `nine boxes`; bookkeeper has `Never use edit_row on your own judgement`;
      reporter and tax lack `Call resolve_issue only`; `sections(SYSTEM_PROMPT)` rebuilds `SYSTEM_PROMPT` exactly.
- [ ] Implement; run `pytest tests/test_specialists.py -q`.

### Task 4: The tools' figures as functions, `hand_over`, and the middleware

**Files:** Modify `ledgersync/agent/tools.py`, `middleware.py`, `__init__.py`, `llm.py`; Test `tests/test_specialists.py`.

**Produces:**
- `ChatContext` gains `specialist: str = "lead"`, `briefing: str = ""`, `handed_over: bool = False`.
- In `tools.py`, module level, each returning what its tool returns before `_out`: `overview(deps, ctx) -> dict`,
  `issues(deps, ctx, family=None, after_row_id=0, limit=20) -> dict`, `open_questions(deps, ctx) -> dict`,
  `changes(deps, ctx, when=None, limit=50) -> dict`, `trial_balance(deps, ctx) -> dict`. The tools call them.
- Tool `hand_over(why: str)`: sets `ctx.specialist = "lead"`, `ctx.handed_over = True`; step
  `Passed to the lead accountant`; returns `{"handed_over": True, "note": "You are now the lead accountant, with
  every tool. Carry on with the person's request; don't mention the hand-over."}`. Last in `make_tools`.
- `middleware.Specialists(models: Optional[dict[str, BaseChatModel]] = None)`:
  `wrap_model_call` offers only the profile's tools; for a specialist it also sets the system message to
  `profile.prompt + BOOKS_NOW + ctx.briefing` (`BOOKS_NOW = '\n\nThe books now (as this turn began; a tool gives
  the state after a change)\n'`; nothing appended when the briefing is empty) and uses `models[profile.effort]`
  when there is one. `wrap_tool_call` answers a known tool outside the profile with the error
  `"{name} isn't one of your tools in this turn. Call hand_over if the request needs it."` (for the lead:
  `"There is no tool called hand_over. Use one of the tools you were given."`).
- `build_agent(settings, deps, *, model=None, checkpointer=None, models=None)`: `Specialists(models)` second in the
  middleware list. `chat_model(settings, effort: str = "medium")`.

- [ ] Tests (scripted model, in-memory checkpoints): the lead is offered `ALL_TOOLS` and sent `SYSTEM_PROMPT`; each
      specialist is offered exactly its tools and its prompt, ending with the briefing; the reporter calling
      `edit_row` gets the refusal, the row is unchanged and no decision is recorded; after `hand_over` the next
      model call has `SYSTEM_PROMPT` and `ALL_TOOLS`, and `ctx.handed_over` is true; the lead calling `hand_over`
      is told there is no such tool.
- [ ] Implement; run `pytest tests/test_specialists.py tests/test_agent.py -q`.

### Task 5: The briefing, and the chat and the review using it

**Files:** Create `ledgersync/agent/briefing.py`; Modify `ledgersync/agent/chat.py`, `run.py`, `ledgersync/reviews.py`;
Test `tests/test_specialists.py`, `tests/test_chat_api.py`.

**Produces:**
- `briefing(deps, ctx) -> str`: compact JSON of `{"overview": …}` plus, by `ctx.specialist`: reviewer in a chat
  `need_a_look` (`issues` first 20); bookkeeper `open_questions`; reporter `open_questions` and `latest_changes`
  (the last 20); tax `trial_balance`. `overview` keeps `accounts` only for the reviewer and the bookkeeper. Over
  `MAX_BRIEFING = 24_000` characters, only the overview is kept, with `"left_out"` naming the tools for the rest.
- `Chat.brief(ctx, text, has_files=False) -> None`: with `settings.agents == "specialists"`, sets `ctx.specialist`
  (`route`, with the last turn's specialist as `previous`, the lead if it was handed over) and `ctx.briefing`; on any
  error building it, logs and leaves the lead. With `single` it does nothing.
- `Chat.turn`: calls `brief` after the files are read; the status before the run is the profile's; `TurnRecord`
  gains `specialist: Optional[str] = None` (set only with `specialists`) and `handed_over: bool = False`.
- `Chat.agent`: with the real model, `models={"low": chat_model(settings, "low")}`.
- `reviews._review_year`: `chat.brief(ctx, message)` before the run.
- `stream_turn`: one INFO line at the end: specialist, handed over, model calls, tool calls, seconds.

- [ ] Tests: the briefing's overview equals `get_overview`'s result less `accounts` for tax and reporter; a chat
      turn with `agents="specialists"` for `What needs my attention?` says `Looking it up…`, offers the reporter's
      tools and keeps `specialist: "reporter"`; `"yes"` after it stays with the reporter; the same turn with the
      default settings says `Working on it…` and keeps no specialist; a year with a row that can't post runs as the
      lead; a turn record without the new fields loads; a background review with `specialists` offers the
      reviewer's tools.
- [ ] Implement; run `pytest -q` (whole suite) and `npm test` in `frontend/`.

### Task 6: Say it in the README

**Files:** Modify `README.md` (under "The AI model"), `.env.example` (done in Task 1).

- [ ] A short section: the five agents, what each is for, the setting, and that it is off until the eval passes.
