# Phase 2: the background AI review. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** after a person changes a client's books from any page, the AI reviews what changed on its own, a short
while later. It fixes what a document supports and asks the rest. Every change it makes shows in a new "AI review"
section with Undo, and it never overrides a person.

**Architecture:**
- A per-client review state in MongoDB gets the work done:
  - `upkeep.after_change` marks the client due;
  - a worker thread in the API process picks a client up once it is quiet;
  - the worker runs the existing agent headless (same model, prompt and tools), with no chat thread.
- The deterministic services gain:
  - a "suggest" mode;
  - an Undo;
  - refusals for rows a person changed and for changes a person undid;
  - a `close_question` action.
- A new client section lists the runs, using the chat's cards.

**Tech Stack:** Python 3.11, FastAPI, MongoDB (pymongo), LangChain `create_agent` (existing), Next.js/TypeScript.

**Spec:** `docs/superpowers/specs/2026-11-04-background-review-and-fixes-design.md`. Its **Phase 2** section, the
three rules under "The rule behind the background review", and the my-calls on locking, triggers, closing
questions, AI review modes and the daily limit.

**Builds on Phase 1 (merged, 0675acd):**
- `upkeep.after_change(store, records, locks, change, *, today=None)` and
  `upkeep.settle_open_years(store, records, client_id, *, except_year=None, today=None)`;
- `ChangeDraft`/`Change` and `AgentRecords.add_change`/`changes(client_id, *, year_start, since, limit)`;
- the agent tool `list_changes`;
- `Chat._write`;
- `ClientLocks`.

## Plan calls (where this plan reads the spec a particular way)

- **The review is per client and year.** A run covers one open year (the agent's tools are year-scoped). Changes
  with no year are listed in every open year's run.
- **"A person's change wins" is enforced in background runs only.** A row is a person's when:
  - it was edited (`SavedRow.edited`);
  - or a person linked it (`link` is set);
  - or a person marked it "not the same" (`apart_from` isn't empty).

  In a chat the person is there and can ask for it.
- **An undone decision is never repeated by any AI run, chat or background.** Its idempotency key is stored as
  rejected, and `resolve` refuses it.
- **Suggest only** checks a resolution in full, then records it as `status="suggested"` with its before and after,
  without changing a row. **Apply** reruns the same resolution, now as the person's (`actor="user"`), so its
  checks run again against the rows as they are.
- **The wait** is `LEDGERSYNC_REVIEW_WAIT` seconds (default 20) after the last triggering change, and only while
  no file of the client is being read.
- **The daily limit** is `LEDGERSYNC_REVIEW_DAILY_LIMIT` (default 20) runs per client per day.
- **A failed run** (model unavailable or timed out) keeps the client due, retried after 10 minutes.
- **Answering a question outside a chat** uses new client-level routes. They call the same services as the chat's,
  with `thread_id=None`.

## Global Constraints

**Branch and environment:**
- Work on a new branch `background-review-phase-2`, cut from `ai-accountant-demo` (0675acd), in a worktree under
  `.claude/worktrees/`.
- Tests: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://127.0.0.1:27027 .venv/bin/pytest -q -p no:cacheprovider`.
- Frontend: `cd frontend && npm test && npx tsc --noEmit`.
- **No real-model calls. Ask the user before spending OpenRouter credit.** Every agent test uses the fakes in
  `tests/agent_fakes.py`.

**Rules the code must keep:**
- The services decide, not the model. The client, year, actor, trigger and mode come from the server
  (`ChatContext`), never from model arguments.
- **A person's change wins:** a background run never changes a row a person changed, and no AI run repeats a
  change a person undid.
- **Visible and reversible:** every background decision is in the decisions log with `trigger="background"`, shows
  in AI review, and can be undone. Undo writes a reversing decision (`reverses`) and posts.
- **Closed is closed:** nothing touches a closed year.
- **Spend:**
  - at most one background run per client at a time;
  - the existing limits apply (30 model calls and 80 tool calls per run);
  - a batch of uploads causes one run.
- **The agent's own changes never trigger a review,** and neither do files read in a chat.

**Exact copy:**
- the section title `"AI review"`;
- the client setting label `"AI review"`, with options `"Automatic"`, `"Suggest only"`, `"Off"`;
- the paused note `"AI review paused for today: limit reached"`;
- the refusals `"A person changed row {n}; a background review leaves it to them."` and
  `"A person undid this change."`;
- the Overview line ``AI review: last run {HH:MM}. ${n} ${n === 1 ? 'change' : 'changes'} you haven't looked at``;
- a run with nothing to do: `"Nothing to change."`.

## Review Focus

These are the five cases most likely to bite a real user that no task would otherwise test. Each line names the
test that pins it.

1. **Thirty files dropped at once:** one run, after the last file is read, not thirty. Task 4,
   `test_a_batch_of_uploads_causes_one_run_after_the_last_is_read`.
2. **A person edits a row while a run is thinking about it:** the AI's decision on that row is refused, and the
   edit stands. Task 2, `test_a_background_resolution_on_a_row_a_person_changed_is_refused`, plus the existing R0
   "unchanged since read" check.
3. **Undo after a person changed the row again:** Undo refuses, saying which row changed, rather than overwriting
   the person. Task 2, `test_undo_refuses_when_a_row_changed_since`.
4. **The API restarts while a client is due or a run is running:** the review still happens, once. Task 4,
   `test_a_restart_keeps_a_due_review_and_retries_a_running_one`.
5. **The model is down:** the run is recorded as failed with the reason, the client stays due, and nothing else
   breaks. Task 4, `test_a_failed_run_is_recorded_and_retried_later`.

---

### Task 1: Records for reviews, modes and rejected changes

**Files:**
- Modify: `ledgersync/models.py`, `ledgersync/records.py`, `ledgersync/config.py` (two settings),
  `ledgersync/demo.py` (clear the new collections on reset).
- Test: `tests/test_records.py`, `tests/test_config.py`.

**Interfaces (produces):**
- `ClientFields.ai_review: Literal["automatic", "suggest", "off"] = "automatic"`, and the same `Optional` field on
  `ClientPatch`.
- `DecisionDraft` gains:
  - `trigger: Literal["chat", "background"] = "chat"`;
  - `review_id: Optional[str] = None`;
  - `resolution: Optional[dict] = None` (the resolution's JSON, kept for suggested decisions);
  - `status` becomes `Literal["applied", "refused", "suggested"]`.
- `ChangeDraft` gains `in_chat: bool = False`. `ChangeKind` gains `"decision_undone"`, `"decision_applied"` and
  `"question_closed"`.
- `ReviewRun(BaseModel)` has:
  - `id`, `client_id`, `year_start`;
  - `status: Literal["running", "done", "failed", "limited", "off"]`;
  - `started_at`, `finished_at: Optional[str]`;
  - `trigger_summary: str` (for example "after 3 files were added");
  - `from_seq: int`, `to_seq: int`;
  - `decision_ids: list[str]`, `question_ids: list[str]`;
  - `looked_at: list[int] = []`, the row ids the run was pointed at;
  - `summary: str = ""`, `error: Optional[str] = None`;
  - `seen: bool = False`.
- `AgentRecords.looked_at(client_id, year_start) -> set[int]`: every row id in that year's earlier runs'
  `looked_at`.
- `ReviewState(BaseModel)` has `client_id`, `last_seq: int = 0`, `due_at: Optional[str]`, `running: bool = False`
  and `retry_at: Optional[str] = None`.
- New `AgentRecords` methods:
  - `review_state(client_id) -> ReviewState`;
  - `set_review_state(state) -> None`;
  - `start_review(client_id, year_start, *, from_seq, to_seq, trigger_summary) -> ReviewRun`;
  - `finish_review(id, *, status, decision_ids=(), question_ids=(), summary="", error=None) -> ReviewRun`;
  - `reviews(client_id, *, year_start=None, limit=50) -> list[ReviewRun]` (newest first);
  - `runs_on(client_id, day: date) -> int` (counts `done` and `failed` runs started that day);
  - `mark_reviews_seen(client_id) -> int`;
  - `unseen_background_changes(client_id) -> int` (applied plus suggested decisions in unseen `done` runs);
  - `reject_key(client_id, key) -> None`;
  - `is_rejected(client_id, key) -> bool`.
- Collections: `review_runs` and `review_state`; rejected keys live in `review_rejected`.
- Settings: `review_wait_seconds: int = 20` (`LEDGERSYNC_REVIEW_WAIT`) and `review_daily_limit: int = 20`
  (`LEDGERSYNC_REVIEW_DAILY_LIMIT`), both added to `ENV_NAMES`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_review_run_is_started_finished_and_listed_newest_first`.
  - `test_runs_on_counts_a_days_finished_runs`: count done and failed, not limited or off.
  - `test_marking_reviews_seen_clears_the_unseen_count`: two done runs with one applied and one suggested decision
    give a count of 2, and 0 after marking.
  - `test_a_rejected_key_is_rejected_for_that_client_only`.
  - `test_review_state_defaults_and_round_trips`.
  - `test_a_client_defaults_to_automatic_ai_review`.
  - `test_review_settings_read_from_env`.
- [ ] **Step 2: Run** them: FAIL.
- [ ] **Step 3: Implement.**
  - Existing decisions without `trigger` read as `"chat"`.
  - The demo reset clears `review_runs`, `review_state` and `review_rejected` for the client.
- [ ] **Step 4: Run** the focused tests, then the full suite: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: records for background reviews, review modes and changes a person undid"`

### Task 2: Suggest, Apply, Undo and the refusals in the services

**Files:**
- Modify: `ledgersync/resolutions.py`.
- Create: `ledgersync/undo.py`.
- Test: `tests/test_resolutions.py`, `tests/test_undo.py` (new).

**Interfaces:**
- Consumes: Task 1's `DecisionDraft` fields, `reject_key`, `is_rejected` and `ChangeKind`; `upkeep.after_change`.
- Produces:
  - `resolutions.resolve(...)` gains three keyword arguments: `trigger: str = "chat"`, `review_id: Optional[str] = None`
    and `suggest: bool = False`. Each is passed into the decision. The checks run in this order:
    1. the existing idempotency check;
    2. `is_rejected(client_id, key)`: refuse with `"A person undid this change."`;
    3. when `trigger == "background"`, any named row that is a person's (see Plan calls): refuse with
       `"A person changed row {n}; a background review leaves it to them."`;
    4. the existing R0 checks.
  - After `_ACTIONS[...]` builds the change, `suggest=True` records `status="suggested"`, the before and after
    worked out from the change, and `resolution=resolution.model_dump(mode="json")`. It doesn't call `_commit`.
    A suggestion's idempotency key is stored as `f"{key}|suggested"`, so the later Apply isn't answered by it.
  - `resolutions.key_of(client_id, row_id, resolution) -> str`: the existing key computation, extracted for Undo.
  - `undo.undo_decision(store, records, locks, *, client_id, decision_id) -> Decision`:
    - It refuses (`InvalidInput`) when the decision isn't the client's, isn't `applied`, is already reversed, or
      any row in its `after` no longer holds those values. That message is
      `"Row {n} has changed since; change it by hand instead."`.
    - Otherwise it puts each patched row back to its `before` values (`store.patch_row`).
    - For a split, it deletes the parts (`store.delete_row`) and clears the original's `superseded_by`.
    - For `close_question` (Task 3), it reopens the question.
    - It records an `applied` decision `action="undo"`, `reverses=decision_id`, `actor="user"`.
    - It calls `records.reject_key` with the undone decision's key (`key_of`). For `set_date` decisions, use the
      key stored on the decision document.
    - It calls `upkeep.after_change(... kind="decision_undone", actor="user", row_ids, after={"decision_id": ...})`.
  - `undo.apply_suggestion(store, records, locks, *, client_id, decision_id, texts) -> Decision`:
    - It re-runs `resolve` with the stored resolution and evidence, `actor="user"`, `trigger="background"`,
      `review_id` as before, and `suggest=False`.
    - It refuses (`InvalidInput`) when the decision isn't a `suggested` one of the client's.
    - It records the change `kind="decision_applied"`.

- [ ] **Step 1: Write the failing tests**, using the Northbridge-style rows in `tests/test_resolutions.py` and the
  `KeepOne` duplicate case from it.
  - `test_a_suggested_resolution_changes_no_row_and_records_before_and_after`.
  - `test_applying_a_suggestion_makes_the_change_as_the_person`.
  - `test_a_background_resolution_on_a_row_a_person_changed_is_refused`: edit the row through
    `ledger.change_row` first. The same resolution with `trigger="chat"` still applies.
  - `test_undo_puts_the_rows_back_and_records_a_reversal`: the rows' values equal `before`, there is an `undo`
    decision with `reverses`, and the posted trial balance is back to its earlier lines.
  - `test_an_undone_change_is_refused_when_asked_again`, for both triggers.
  - `test_undo_refuses_when_a_row_changed_since`: the message names the row.
  - `test_undoing_a_split_removes_its_parts`.
- [ ] **Step 2: Run** them: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_resolutions.py tests/test_undo.py tests/test_questions.py`, then the full suite:
  PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: suggest, apply and undo an AI decision; never redo what a person undid"`

### Task 3: The agent runs in the background: context, tools and prompt

**Files:**
- Modify: `ledgersync/agent/tools.py` (`ChatContext`, `resolve_issue`, a new `close_question`, `get_overview`).
- Modify: `ledgersync/questions.py` (a new `close`).
- Modify: `ledgersync/agent/prompt.py`.
- Test: `tests/test_agent.py`, `tests/test_questions.py`.

**Interfaces:**
- `ChatContext` gains three fields: `trigger: Literal["chat", "background"] = "chat"`,
  `mode: Literal["apply", "suggest"] = "apply"` and `review_id: Optional[str] = None`. `resolve_issue` passes
  `trigger`, `review_id` and `suggest=(ctx.mode == "suggest")` into `resolve`.
- `questions.close(store, records, *, client_id, question_id, reason, evidence: list[Evidence], texts, actor, trigger, review_id=None, suggest=False) -> Decision`:
  - It is allowed only for an `open` or `waiting` question with `source == "agent"`.
  - **Either** a change with actor `"user"`, recorded after the question's `created_at`, shares a row with the
    question (that change's summary becomes the decision's evidence quote, with `upload_id=0` and
    `upload_name="change record"`);
  - **or** each evidence quote passes the same document check `resolve` uses. Extract it from `resolve` into
    `resolutions.check_quotes(b, rows, named, evidence, texts) -> Optional[str]`, which returns the refusal, if
    any.
  - It records a decision `action="close_question"`. `before` is `{"question": {"status": <old>}}` and `after` is
    `{"question": {"status": "resolved"}}`.
  - It resolves the question with the answer `f"Closed by the AI: {reason}"`, unless `suggest` is set.
  - It records the change `kind="question_closed"`.
  - Otherwise it refuses with `"Nothing since the question was asked answers it."`.
- The agent tool `close_question(runtime, question_id: str, reason: str, evidence: list[EvidenceIn] = [])` wraps
  `questions.close` with the context's actor, trigger, review and mode.
- `get_overview` adds `"background_reviews_since_last_chat"`: up to 5 runs, each with `ran_at`, `summary`, `sorted`
  (the count of applied decisions) and `asked`. "Since the last chat" means `finished_at` is later than the
  client's previous thread's `updated_at`.
- The prompt gains two passages:
  - A **background passage:** "In a background review no person is reading. Look at what changed (list_changes)
    and the rows it touched; settle what the evidence supports; ask only what you must; end with one short line
    saying what you did."
  - A **chat passage:** "At the start of a chat, if get_overview lists background reviews since the last chat,
    say in one line what they did."

- [ ] **Step 1: Write the failing tests.**
  - `test_resolve_issue_carries_the_contexts_trigger_and_mode`: with `ChatContext(..., trigger="background", mode="suggest")`
    the decision is `suggested` and `trigger == "background"`.
  - `test_close_question_after_a_persons_change_to_its_rows`.
  - `test_close_question_refused_without_a_change_or_document`.
  - `test_get_overview_lists_background_reviews_since_the_last_chat`.
  - A prompt test: both new passages are in the system prompt.
- [ ] **Step 2: Run** them: FAIL.
- [ ] **Step 3: Implement.** Register `close_question` in `make_tools`. Extend the expected tool-name set in
  `test_no_tool_can_set_a_date`.
- [ ] **Step 4: Run** the focused tests, then the full suite: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: the agent works in a background review: its context, close_question and what it tells a new chat"`

### Task 4: When reviews run: triggers, the wait, the worker and the run itself

**Files:**
- Create: `ledgersync/reviews.py`.
- Modify: `ledgersync/upkeep.py` (`after_change` notes triggering changes).
- Modify: `server.py`:
  - start and stop the worker in the app's lifespan;
  - `read_chat_file`'s change gets `in_chat=True`;
  - pass the `reading` counter's "is this client's file being read" check to the worker.
- Test: `tests/test_reviews.py` (new), `tests/test_upkeep.py`.

**Interfaces:**
- `reviews.triggers(change: Change) -> bool`. It is false when:
  - `change.actor` starts with `"agent:"`;
  - `change.in_chat`;
  - `change.kind` is `"year_closed"`, `"decision_applied"` or `"question_closed"`;
  - `change.kind == "row_edited"` and every key of `change.after` is `"description"`;
  - `change.kind == "client_changed"` and no key of `change.after` is one of `"vat_registered"`,
    `"business_type"`, `"first_year_end"` or `"bank_accounts"`. A name, contact, folder or `ai_review` change
    doesn't need a review.

  Otherwise it is true.
- `reviews.note(records, change, *, now: datetime, wait: int) -> None`: when `triggers(change)`, it sets the
  client's `due_at = now + wait`, keeping an earlier `retry_at` if there is one.
- `upkeep.after_change` gains a keyword argument, `wait: int = 20`. It calls `reviews.note(records, change, now=..., wait=wait)`
  after recording the change, inside its existing try. `server.py`'s `changed(...)` passes
  `wait=settings.review_wait_seconds`. Existing callers don't change.
- `reviews.run(chat, client_id, *, now: datetime) -> list[ReviewRun]`:
  - Read the client's `ai_review`:
    - **`"off"`:** record one run, `status="off"`, `summary=""`, once per day only. Set `last_seq` to the latest
      change.
    - **The daily limit reached:** record one `status="limited"` run with summary
      `"AI review paused for today: limit reached"`, once per day.
  - Otherwise, for each open year with triggering changes after `last_seq`:
    1. `start_review(...)`, with `trigger_summary` worked out from the kinds. For example
       `"after 3 files were added"`, `"after 2 rows were changed"` or `"after the client's details changed"`: one
       phrase per kind group, joined with " and ".
    2. Run `stream_turn(chat.agent, ChatContext(client_id, f"review-{run.id}", year, trigger="background", mode=…, review_id=run.id), text)`
       and drain its events. `text`:
       - lists the change summaries and the row ids they touched;
       - adds `"Not yet reviewed: rows …"`, listing the year's rows with an issue that aren't in
         `records.looked_at(client_id, year)`;
       - for the first review of a year, says "First review of this year: look at everything."

       The run's `looked_at` is the touched rows plus the not-yet-reviewed ones.
    3. Under `chat.locks.hold(client_id)`, call `upkeep.settle_open_years(...)`.
    4. `finish_review(...)` with:
       - the decision ids from the run (`records.decisions` filtered by `review_id`);
       - the questions asked during the run;
       - the agent's last line as `summary`, or `"Nothing to change."` when nothing was decided or asked.
  - Then set `last_seq = to_seq` (the latest change seen when the run started) and `running=False`.
  - Clear `due_at` **only** when no triggering change has a `seq` above `to_seq`. A change that arrived during the
    run leaves the client due, so exactly one more run follows.
  - **A model error:** `finish_review(status="failed", error=<message>)`, `retry_at = now + 10 min`, and the client
    stays due.
- `reviews.Worker(chat, settings, *, busy: Callable[[int], bool], clock=…)`:
  - `tick(now) -> list[ReviewRun]` runs every client whose `due_at <= now`, isn't `running`, isn't `busy`, and has
    `retry_at` unset or past. It sets `running=True` before a run, and runs one client at a time.
  - `start()` and `stop()` run `tick` every 2 seconds on a daemon thread.
  - `recover()`, called by `start()`, turns `running=True` back into due-now (`due_at=now`). It is for a restart.
- The worker isn't started when `settings.warmup` is false and `LEDGERSYNC_REVIEW_WORKER=0`. Tests drive `tick`
  directly.

- [ ] **Step 1: Write the failing tests.** Use `tests/agent_fakes.py` for a scripted agent that calls
  `resolve_issue` with a `KeepOne` on a duplicate.
  - `test_triggers_ignores_the_agent_chat_reads_closing_and_description_only_edits`.
  - `test_a_batch_of_uploads_causes_one_run_after_the_last_is_read`:
    - three `after_change` calls at t, t+5s and t+10s;
    - `busy` is true until t+12s;
    - `tick` at t+25s runs nothing;
    - `tick` at t+31s runs once.
  - `test_a_run_applies_what_the_evidence_supports_and_records_it_as_background`: the decision has
    `trigger == "background"` and the run's id. The run's status is `done`, and the posted books are settled.
  - `test_suggest_only_records_suggestions_and_changes_nothing`.
  - `test_off_records_one_quiet_run_a_day_and_moves_the_mark`.
  - `test_the_daily_limit_pauses_with_the_exact_note`.
  - `test_a_failed_run_is_recorded_and_retried_later`.
  - `test_a_restart_keeps_a_due_review_and_retries_a_running_one`: a new `Worker` calls `recover()`, and the next
    `tick` runs it once.
  - `test_the_agents_own_changes_cause_no_further_run`.
  - `test_a_change_during_a_run_causes_exactly_one_more_run`.
  - `test_a_name_change_causes_no_run_and_a_vat_change_does`.
  - `test_a_later_run_is_pointed_at_issues_no_run_has_looked_at`.
  - `test_a_run_with_nothing_to_do_says_so`.
- [ ] **Step 2: Run** them: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_reviews.py tests/test_upkeep.py tests/test_upkeep_api.py tests/test_chat_api.py`,
  then the full suite: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: review a client in the background once it is quiet, within a daily limit"`

### Task 5: The API for AI review

**Files:**
- Modify: `server.py`, `ledgersync/agent/chat.py`.
  - Extract the core of `Chat.document` into
    `Chat.answer_with_document(client, year_start, question_id, file, *, thread_id=None) -> AnswerResult`, which
    `document` calls.
- Modify: `ledgersync/ledger.py`. `summaries` adds `ai_unseen`.
- Test: `tests/test_reviews_api.py` (new).

**Interfaces (routes; writes need `X-LedgerSync`):**
- `GET /api/clients/{id}/reviews?year_start=` returns
  `list[ReviewDetail]`, where `ReviewDetail = ReviewRun + decisions: list[Decision] + questions: list[Question]`.
- `POST /api/clients/{id}/reviews/seen` returns `{"marked": int}`.
- `POST /api/clients/{id}/decisions/{decision_id}/undo` returns `Decision` (from `undo.undo_decision`).
- `POST /api/clients/{id}/decisions/{decision_id}/apply` returns `Decision` (from `undo.apply_suggestion`, with
  `texts` from the document-text service the tools use).
- `POST /api/clients/{id}/questions/{question_id}/answer` (body `Answer`) returns
  `{"questions": list[Question]}`. It calls `questions.answer(..., thread_id=None)`.
- `POST /api/clients/{id}/questions/{question_id}/document` (multipart `file`) returns `AnswerResult`. It calls
  `chat.answer_with_document`.
- `ClientSummary.ai_unseen: int = 0`.
- The `ai_review` client setting goes through `PATCH /api/clients/{id}` (it is a client field) and records
  `client_changed`.

- [ ] **Step 1: Write the failing tests:**
  - list reviews with their decisions and questions;
  - mark them seen, after which `ai_unseen` is 0 on `GET /api/clients`;
  - undo through the route (200, and the rows are back);
  - undo refused (422 with the row's message);
  - apply a suggestion;
  - answer a question by date, and by uploading a document, with no chat;
  - the setting round-trips.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the focused tests, then the full suite: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: AI review in the API: list, mark seen, undo, apply, and answers without a chat"`

### Task 6: The AI review section and its signals in the site

**Files:**
- Modify: `frontend/src/lib/years.ts` (`SECTIONS` adds `{ slug: 'ai-review', title: 'AI review' }` after
  Overview).
- Create: `frontend/src/components/AiReviewSection.tsx` and `frontend/src/lib/reviews.ts`.
- Modify:
  - `frontend/src/app/clients/[id]/[year]/[section]/page.tsx`;
  - `frontend/src/components/chat/QuestionCard.tsx` (an optional `answerer` prop; the thread routes stay the
    default);
  - `frontend/src/components/OverviewSection.tsx`;
  - the clients list page (the badge);
  - `frontend/src/components/ClientDialog.tsx` (the setting);
  - `frontend/src/components/TransactionsTable.tsx` (the Agent popover says `"From a chat"` or
    `"From a background review"`).
- Test: `frontend/src/lib/reviews.test.ts`.

**Interfaces:**
- `lib/reviews.ts` exports:
  - `listReviews(clientId, yearStart)`, `markReviewsSeen(clientId)`, `undoDecision(clientId, id)` and
    `applySuggestion(clientId, id)`;
  - `clientAnswerer(clientId)`, giving `{ answer(qid, a), upload(qid, file) }` for `QuestionCard`;
  - `runTitle(run): string`, for example `"Today 10:42, after 3 files were added: sorted 2, asked 1"`. Use
    `"Yesterday"` or `"Mon 3 Nov"` for older runs, `"sorted"` for the applied count, and `"suggested"` instead in
    suggest mode. It omits zero parts, and a run with neither reads `"…: Nothing to change."`;
  - `overviewReviewLine(lastRunAt: string | null, unseen: number): string | null`, which gives the exact copy from
    Global Constraints, or `null` when there's no run.
- In `AiReviewSection`:
  - the runs list newest first, each opening to its decision cards (`DecisionLine`), with **Undo** (applied) or
    **Apply** (suggested), and its `QuestionCard`s using `clientAnswerer`;
  - a `limited` or `off` run shows its one line;
  - opening the section calls `markReviewsSeen`.

- [ ] **Step 1: Write the failing tests** in `reviews.test.ts`:
  - `runTitle` for today, yesterday and older, with and without parts, and suggest mode;
  - `overviewReviewLine` for null, 0 unseen, 1 and 2.
- [ ] **Step 2: Run** `npm test`: FAIL.
- [ ] **Step 3: Implement** the lib, then the components.
- [ ] **Step 4: Run** `npm test` and `npx tsc --noEmit`: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: the AI review section, its Overview line, the client list badge and the review setting"`

### Task 7: Check it end to end in the site, with the fake model

**Files:** none changed, unless the check finds a bug, which goes back to the task that owns it.

- [ ] **Step 1:** Start an isolated API and site on a fresh database and the local MongoDB:
  - `LEDGERSYNC_REVIEW_WAIT=3`;
  - a fake chat model scripted to `KeepOne` the duplicate. Use the existing `browser_check_server.py` pattern in
    `.superpowers/sdd/2026-11-02-accountant-chat/tools/`, or add a small `tools/fake_review_server.py` in the
    worktree's scratch folder. No real model.
- [ ] **Step 2:** Through the API, add a client and a receipt plus an expense-sheet line for the same spend (a
  duplicate). Wait about 5 seconds. Expect:
  - one `done` run;
  - the AI review section showing `"Today HH:MM, after 2 rows were added: sorted 1"`;
  - the duplicate excluded;
  - the Overview line with 1 unseen;
  - the client list badge 1.
- [ ] **Step 3:** Undo it in the browser. Expect:
  - the row is back;
  - the AI review section shows the undo;
  - after the next wait no run repeats it, because the key is rejected.
- [ ] **Step 4:** Set the client to "Suggest only" and repeat with a new duplicate. Expect an **Apply** button and
  no change until it is clicked.
- [ ] **Step 5:** Take screenshots of the AI review section and the Overview for the user.
- [ ] **Step 6: Before any real-model run, ask the user.** If they agree, run Northbridge and Ashdown once through
  Documents only, and compare with the hand-worked figures.
