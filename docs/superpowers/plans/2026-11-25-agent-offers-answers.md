# The agent offers an answer to the books' questions: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a chat, the agent fills in the answer card of a books question (the opening VAT difference, opening
prepayments or accruals, a bad debt) from the client's words and quoted documents. The client edits it if they want,
and presses Confirm.

**Architecture:** The offer is stored on the question (`Question.offer`). `questions.offer` checks it with the
answer service's own checks (`questions.check_answer`, run without booking), the quote checks and the source rules.
A chat-only agent tool `offer_answer` calls it. `QuestionCard` opens filled in from the offer, and Confirm posts
through the existing answer routes. The test runner confirms offers made in its chat.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, MongoDB (pymongo), LangChain tools (`@tool`, `ToolRuntime`),
Next.js and React (TypeScript), node:test.

**Spec:** `docs/superpowers/specs/2026-11-25-agent-offers-answers-design.md`

## Global Constraints

- Nothing is booked without the client's Confirm. `offer_answer` is refused outside a chat
  (`ctx.trigger != "chat"`), as `edit_row` is.
- An offer needs at least one `said` source: words of the person in this chat, quoted.
- Kinds covered: `opening_vat`, `opening_prepayments`, `opening_accruals`, `bad_debt`. Rules questions only.
- Document quotes may come from any of the client's uploads, in any year. Each quote must be 4 or more characters
  (spaces aside) and appear in its upload's text, normalised as `resolutions._normalised`.
- Every split line and the write-off date has a source: `said`, `document` (with `for`) or `question`. A worked-out
  figure carries its `working`.
- Answers keep going through `questions.answer` and its two routes. Nothing else books them.
- Work in the main checkout, on top of the uncommitted work there. Never discard or commit the user's own hunks
  (ledger.py, records.py, reviews.py, server.py, tests/test_reviews_api.py). Stage only this plan's lines.
- **Commit only with the user's yes.** Each commit message ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run only targeted tests: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest <files> -q`.
  Front end: `cd frontend && npm test` and `npx tsc --noEmit`. Runner:
  `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest testbooks_runner/tests -q -W error`
  in `.claude/worktrees/nostalgic-ptolemy-28a206`.
- Never read, print or log `.env`. No paid model calls.

## Review Focus

- **An offer quoting a note:** an offer whose `said` quote is from a note the app wrote into the chat (a
  `HumanMessage` with `additional_kwargs["note"]`), not the person. It is refused. Test in Task 3.
- **A stale amount:** an offer made, then a new row changes the amount still to release, so the question's text
  changes. The offer is cleared, and a stale Confirm is refused by the service, as today. Tests in Task 1 and Task 3.
- **Two offers:** the agent offers twice. The second replaces the first, and the change log shows both. Test in
  Task 3.
- **An offer arriving after the card shows:** the card refills when the offer changes, unless the person has
  already edited a field. Test in Task 5.
- **Answered on the page:** the question is answered on the client page while the chat card still shows the offer.
  The chat card shows it resolved (the existing refresh of the turn's questions), and the offer is gone. Test in
  Task 1.

---

### Task 1: The offer on the question

**Files:**
- Modify: `ledgersync/models.py` (`Question`; new `OfferSource`, `Offer`; `ChangeKind` gains `"question_offered"`)
- Modify: `ledgersync/records.py` (`set_offer`, `clear_offer`; `set_question` and `upsert_question` clear it)
- Test: `tests/test_questions.py`

**Interfaces:**
- Produces:
  - `class OfferSource(BaseModel)`: `kind: Literal["said", "document", "question"]`, `quote: str = ""`,
    `upload_id: Optional[int] = None`, `upload_name: str = ""`, `for_: Optional[str] = Field(None, alias="for")`
    (`"line:<n>"` or `"date"`), `working: str = ""`.
  - `class Offer(BaseModel)`: `answer: dict` (a `SplitAnswer` or `WriteOffAnswer` as JSON),
    `sources: list[OfferSource]`, `reason: str`, `thread_id: str`, `offered_at: str`, `offered_by: str`.
  - `Question.offer: Optional[Offer] = None`.
  - `AgentRecords.set_offer(question_id: str, offer: Offer) -> Question` and
    `AgentRecords.clear_offer(question_id: str) -> None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_questions.py`:
  - `test_an_offer_is_kept_on_its_question_and_read_back`: `records.set_offer(q.id, offer)`, then
    `records.question(q.id).offer == offer`.
  - `test_answering_or_waiting_clears_the_offer`: after `set_question(q.id, "resolved", "x")`, and separately after
    `set_question(q.id, "waiting", "Not sure")`, `question(q.id).offer is None`.
  - `test_an_offer_goes_when_the_question_text_changes`: `upsert_question` with new text clears it; the same text
    keeps it.
- [ ] **Step 2: Run them** and expect them to fail with `AttributeError` (no `set_offer`).
- [ ] **Step 3: Implement.** Add the models. `set_offer` does `$set` on `offer` (by alias, `mode="json"`).
  `clear_offer` does `$unset`. In `set_question`, add `"offer": None` to the `$set`. In `upsert_question`, before its
  `find_one_and_update`, run `update_one({"client_id": ..., "key": key, "text": {"$ne": q.text}}, {"$unset":
  {"offer": ""}})`.
- [ ] **Step 4: Run** `tests/test_questions.py` and expect every test to pass.
- [ ] **Step 5: Commit** (with the user's yes): `feat: a question can hold an answer offered for the person to confirm`.

### Task 2: Checking an answer without booking it

**Files:**
- Modify: `ledgersync/questions.py` (`_release`, `_release_vat`, `_write_off` split into a check and a post)
- Test: `tests/test_questions.py`

**Interfaces:**
- Produces: `questions.check_answer(store: MongoStore, client_id: int, q: Question, answer: Answer) -> Optional[str]`.
  It returns the refusal message `questions.answer` would raise as `InvalidInput`, or None. It writes nothing.

- [ ] **Step 1: Write the failing tests:**
  - `test_checking_an_answer_writes_nothing_and_says_what_would_be_refused`. For an opening prepayments question of
    £6,558.46 (`opened_with_prepayments_and_an_accrual`):
    - a split of 5,538.46 to 7100 plus 1,020.00 to 8204 gives None;
    - a split adding up to £6,000.00 gives "The lines add up to £6,000.00; the opening prepayments still to release
      are £6,558.46.";
    - `store.rows(acme)` is unchanged.
  - The same for an `opening_vat` question (a line to 2202 gives "Choose an account for each line, not the VAT
    liability or a bank.").
  - The same for `bad_debt` (a date before the six months gives the existing refusal).
- [ ] **Step 2: Run them** and expect them to fail (`check_answer` not defined).
- [ ] **Step 3: Implement.** Move the validation at the top of each poster into
  `_release_problem(...)`, `_release_vat_problem(...)` and `_write_off_problem(...)`, each returning
  `Optional[str]`. The posters raise `InvalidInput` on a problem, then post as before. `check_answer` dispatches on
  `q.kind` and the answer's `kind`, and refuses a kind that isn't one of the four.
- [ ] **Step 4: Run** `tests/test_questions.py tests/test_upkeep.py tests/test_chat_api.py` and expect them to pass,
  with the existing answer tests unchanged.
- [ ] **Step 5: Commit** (with the user's yes): `refactor: the answer service can check an answer without booking it`.

### Task 3: The offer service

**Files:**
- Modify: `ledgersync/questions.py` (new `offer`)
- Test: `tests/test_questions.py`

**Interfaces:**
- Consumes: Task 1 (`Offer`, `OfferSource`, `set_offer`), Task 2 (`check_answer`).
- Produces: `questions.offer(store, records, *, client_id: int, thread_id: str, question_id: str, answer: Answer,
  sources: list[OfferSource], reason: str, texts: Texts, said: list[str], actor: str) -> Question`.
  `said` is the person's own messages in the thread (notes left out). It raises `InvalidInput(<why>)` on a refusal.
  It records a `question_offered` change with the agent as actor.

- [ ] **Step 1: Write the failing tests** (one each, refusal text checked by a key phrase):
  - not one of the four kinds, or `source == "agent"`: "isn't a books question that takes an answer";
  - resolved: "already answered";
  - `check_answer` refuses: its message;
  - no `said` source: "needs the person's own words";
  - a `said` quote not in `said` (including one only in a note): "isn't in what the person said";
  - a document quote not in its upload, or under 4 characters: the `check_quotes`-style messages;
  - a line or the date with no source: "line 2 has no source".
  - Accepted:
    - the £312 VAT offer, with one line to 8250 sourced `question`, plus a `said` quote of "Fine to correct it this
      year". It sets the offer and records a `question_offered` change.
    - Offered twice: the second replaces the first.
    - A question in another open year of the client (`YEAR_2`) is accepted too.
- [ ] **Step 2: Run them** and expect them to fail.
- [ ] **Step 3: Implement** `offer`.
  - Find the question with `records.question` and check its client.
  - Run the checks in the order of the tests above. Document quotes are checked against
    `store.uploads(client_id)` and `texts`; this is not limited to the question's rows.
  - A line's source is any `OfferSource` with `for_ == f"line:{n}"` (1-based) or `kind == "question"`. The date's
    source is `for_ == "date"`, `kind == "question"`, or a `said` quote when the answer has no date (the default).
- [ ] **Step 4: Run** `tests/test_questions.py` and expect it to pass.
- [ ] **Step 5: Commit** (with the user's yes): `feat: an answer to a books question can be offered, checked as an answer is`.

### Task 4: The agent's tool

**Files:**
- Modify: `ledgersync/agent/tools.py` (new `offer_answer`; `open_questions` covers every open year and includes
  `offer`; `list_documents`/`read_document` reach the client's other years for these questions)
- Modify: `ledgersync/agent/chat.py` (the turn's result carries every question offered in the turn, whatever its year)
- Modify: `ledgersync/agent/prompt.py` (one rule)
- Test: `tests/test_agent.py` (with `tests/agent_fakes.py`)

**Interfaces:**
- Consumes: Task 3 (`questions.offer`).
- Produces: the tool `offer_answer(question_id: str, answer: SplitAnswer | WriteOffAnswer,
  sources: list[OfferSource], reason: str, runtime) -> dict`, returning `{"status": "offered", "question_id": ...}`
  or `{"status": "refused", "why": ...}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_offer_answer_is_refused_outside_a_chat`: with `trigger="background"`, the result is refused with "Only a
    person in a chat"; no offer is kept.
  - `test_offer_answer_takes_the_persons_words_from_the_chat`: the state has a `HumanMessage("Fine to correct it this
    year")` and a note message. The offer quoting the first is accepted; quoting the note is refused.
  - `test_list_questions_shows_an_offer_and_other_years`: a books question in `YEAR_2` and one with an offer both
    appear, with `year_start` and `offer`.
  - `test_a_turn_shows_the_question_it_offered_an_answer_to`: the turn's result questions include the offered one.
- [ ] **Step 2: Run them** and expect them to fail.
- [ ] **Step 3: Implement.**
  - **The tool:** read `said` from `runtime.state["messages"]`, keeping each `HumanMessage` whose
    `additional_kwargs` has no `"note"`. Call `questions.offer` under `deps.locks.hold`. Its docstring follows the
    spec's "The agent" section, ending "The person confirms on the card: never say it is booked."
  - **Listing questions:** `open_questions` lists `records.questions(client_id, None)` for the client's open years.
  - **Other years' documents:** `list_documents` and `read_document` take an optional `year_start`, so the agent
    can read last year's invoices for an opening question (default: the chat's year).
  - **The prompt:** add one line under the question rules: "When the person answers one of the books' own questions
    (the VAT difference, the opening prepayments or accruals, a bad debt) in the chat, fill in its answer with
    offer_answer: quote their words, and work out any amounts from documents you quote. Say you've filled in the card
    for them to confirm; never ask for something new instead."
- [ ] **Step 4: Run** `tests/test_agent.py tests/test_chat_api.py tests/test_questions.py` and expect them to pass.
- [ ] **Step 5: Commit** (with the user's yes): `feat: the agent can fill in a books question's answer for the person to confirm`.

### Task 5: The card

**Files:**
- Modify: `frontend/src/lib/chat.ts` (`Question.offer`; pure helpers)
- Modify: `frontend/src/components/chat/QuestionCard.tsx`
- Test: `frontend/src/lib/chat.test.ts`

**Interfaces:**
- Consumes: the API's `Question.offer` (Task 1's JSON, with `for` as the key).
- Produces:
  - `offerLines(q: Question): { account: string; amount: string }[] | null`
  - `offerDate(q: Question): string | null`
  - `sourcesFor(q: Question, part: string): OfferSource[]`
  - `changedLines(offered, current): boolean[]`

- [ ] **Step 1: Write the failing tests** in `chat.test.ts`:
  - `offerLines` turns `{kind: 'split', lines: [{account: '7100', amount: '5538.46'}]}` into the form's lines;
    `offerLines` of a question with no offer is null.
  - `sourcesFor(q, 'line:1')` returns that line's document source and any `question` source.
  - `changedLines` marks only the edited line.
  - The card refills when `question.offer` changes and no field has been touched (a pure `nextLines(prev, offer,
    touched)` helper).
- [ ] **Step 2: Run** `cd frontend && npm test` and expect it to fail.
- [ ] **Step 3: Implement.**
  - **Helpers:** add them in `chat.ts`.
  - **The card:** when `question.offer` is set, the split lines and the write-off date start from it.
  - **Sources:** "From what you said: “…”" shows under the form, each line's document quote (and its working)
    beside it, and the reason.
  - **Buttons:** the primary button reads "Confirm".
  - **Edits:** an edited line shows "changed by you" (muted, small).
  - **Without an offer:** the card is unchanged.
- [ ] **Step 4: Run** `npm test` and `npx tsc --noEmit`, and expect both to pass.
- [ ] **Step 5: Check it in a preview:** the `api-recheck-8131` copy with a seeded offer, plus a front-end copy on a
  free port (never port 3000). The card shows the offer, editing marks the line, and Confirm books it.
- [ ] **Step 6: Commit** (with the user's yes): `feat: a question card opens with the agent's offered answer, to change or confirm`.

### Task 6: The runner confirms offers (runner branch)

**Files:**
- Modify: `.claude/worktrees/nostalgic-ptolemy-28a206/testbooks_runner/driver.py` (`send_replies`)
- Modify: `.claude/worktrees/nostalgic-ptolemy-28a206/testbooks_runner/api.py` (`answer_question(thread_id, question_id, answer)`)
- Modify: `.claude/worktrees/nostalgic-ptolemy-28a206/testbooks_runner/report.py` (an "Offers confirmed" list)
- Test: `.claude/worktrees/nostalgic-ptolemy-28a206/testbooks_runner/tests/test_driver_replies.py`
  (or the file holding the `send_replies` tests)

**Interfaces:**
- Consumes: the API's `Question.offer` and `POST /api/chat/threads/{t}/questions/{q}/answer`.
- Produces: `progress.replies[qid]["confirmed"]: list[{question_id, answer}]`.

- [ ] **Step 1: Write the failing test:** after a reply turn, the fake API lists a question with an offer whose
  `thread_id` is the runner's. `send_replies` posts that offer's answer unchanged and records it. An offer from
  another thread is left alone.
- [ ] **Step 2: Run** the runner tests and expect them to fail.
- [ ] **Step 3: Implement** in `send_replies`, after each reply turn ends, and add the report section.
- [ ] **Step 4: Run** the runner tests and expect them all to pass.
- [ ] **Step 5: Commit** (with the user's yes, on the runner branch):
  `feat(runner): confirm the answers the app offers in the runner's chat`.
