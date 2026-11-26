# Phase 1: one set of books, the same rules everywhere, and a record of changes. Implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** after any change to a client's data, from any page, the rule questions, the posted ledger and the trial
balance are brought up to date at once without the model. Every change is recorded for the AI to read.

**Architecture:**
- The rows' trial balance applies the same document rules (`evidence_rules`) as the posted ledger, so the two can
  no longer differ.
- A new `ledgersync/upkeep.py` holds `settle`: what the chat already does at the end of a turn
  (`record_automatic`, `questions.refresh`, `ledger_book.post`). It also holds `after_change`, which records a
  change and then settles every open year under the client's lock.
- Every data-changing route calls `after_change`.
- A `changes` collection (in `AgentRecords`) and a read-only agent tool, `list_changes`, give the AI the record.

**Tech Stack:** Python 3.11, FastAPI, MongoDB (pymongo), LangChain tools, Next.js/TypeScript (node test runner).

**Spec:** `docs/superpowers/specs/2026-11-04-background-review-and-fixes-design.md` (Phase 1). Background:
`docs/2026-11-04-accountant-test-findings.md` (F3, F4, F9).

**Later phases:** phases 2–5 of the spec get their own plans once this one lands. They build on `upkeep.after_change`,
`ChangeDraft` and `AgentRecords.changes`, defined here.

## Plan calls (where this plan reads the spec a particular way)

- **"Every page reads the posted ledger."**
  - This is met by making the rows' trial balance apply the same document rules (Task 1), and by posting after
    every change (Tasks 4–5). Both then give the same figures, and a test pins that.
  - The pages keep their existing endpoints, and Close year keeps its existing logic.
  - The posted ledger stays the append-only record.
- **"If the document doesn't fit, the question stays open and gains a note."**
  - Outside a chat there's no telling which question an upload was meant for. An upload that doesn't match leaves
    the question open, with no note.
  - The note stays on the chat's "Upload invoice" answer, where it exists today (`chat._mismatch`).
- **A change's `year_start`** is set only where the route knows the year. Row-level changes from the pages carry
  `None` and are listed with every year.

## Global Constraints

**Branch and environment:**
- Work on a new branch `background-review-phase-1`, cut from `ai-accountant-demo`.
- Don't add the untracked `eval/results/*` files or `frontend/next-env.d.ts`.
- Tests: `.venv/bin/pytest` (defaults to `-m "not llm"`). Mongo tests need `LEDGERSYNC_TEST_MONGODB_URI`.
- Frontend tests: `cd frontend && npm test`.
- **No real-model calls in this phase.** Ask the user before spending any OpenRouter credit.

**Behaviour that must not change:**
- The document rules: £50 (`NO_DOCUMENT_LIMIT`) and £250 (`SIMPLIFIED_LIMIT`) in `evidence_rules.py`.
- The services decide, not the model: the client and the actor come from the server, never from model arguments.

**Exact copy:**
- `"Held in Suspense: needs its receipt or invoice."`
- `"Held in Suspense: needs a full VAT invoice."`
- A resolved document question's answer: `"Matched to <upload name>"`.

**Rules for changes:**
- A person's change must never fail because the upkeep after it failed.
- Upkeep never posts into a closed year.

## Review Focus

These are the five cases most likely to bite a real user that no task would otherwise test. Each line names the
test that pins it.

1. **Upkeep raising** (Mongo hiccup, a bug): the person's PATCH or upload still succeeds, the change is recorded,
   and the next change settles. Test: Task 4 `test_a_failing_settle_is_logged_not_raised`, and Task 5
   `test_a_row_edit_succeeds_when_upkeep_fails`.
2. **A date edit that moves a row into another year:** both years are settled, not only the one the page shows.
   Test: Task 4 `test_after_change_settles_every_open_year`.
3. **A closed year:** nothing is posted into it after a change in a later year. Test: Task 4
   `test_after_change_skips_closed_years`.
4. **A row with an error** (posting blocked for the year): upkeep returns the problems, nothing raises, and the
   Overview says the books aren't up to date. Tests: Task 4 `test_settle_with_a_blocked_year_returns_problems`, and
   Task 6 `postedLedgerNote` tests.
5. **A chat turn and a page edit settling the same client at once:** both go through `ClientLocks.hold`. Test:
   Task 4 `test_settle_runs_inside_the_clients_lock`.

---

### Task 1: The rows' trial balance applies the document rules

**Files:**
- Modify: `ledgersync/books.py`. `_Books.post` (line ~117) builds the journal with the document rules; imports go
  at the top.
- Test: `tests/test_books.py`

**Interfaces:**
- Consumes:
  - `evidence_rules.document_rule(tx, settings) -> DocumentRule`;
  - `evidence_rules.journal_with_rule(tx, index, rule) -> list[JournalLine]`;
  - `posting.matched_rows(...)` and `posting.summarise(journal, opening)`.
- Produces: `books.trial_balance`, `books.summary`, `books.bank_checks`, `books.close` and the Excel export now
  give the same figures as `ledger_book.posted_trial_balance` once posted. The signatures don't change.

- [ ] **Step 1: Write the failing tests** in `tests/test_books.py`. Use the `acme_with_year_one` fixture and the
  `add_rows`, `row` and `net` helpers.

```python
def test_a_purchase_of_50_or_more_without_its_document_is_held_in_suspense(mongo_store, acme_with_year_one):
    add_rows(mongo_store, acme_with_year_one, row(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400",
             document_type="statement", counterparty="Trainline", description="TRAINLINE"), year_start=date(2025, 4, 1))
    tb = books.trial_balance(mongo_store, acme_with_year_one, date(2025, 4, 1))
    assert net(tb, "9998") == D("240.00") and net(tb, "7400") == 0

def test_a_purchase_under_50_without_a_document_is_a_cost_with_no_vat(mongo_store, acme_with_year_one):
    add_rows(mongo_store, acme_with_year_one, row(date=date(2025, 7, 1), gross=D("38.50"), vat=D("6.42"),
             account_code="7300", document_type="statement", description="SHELL"), year_start=date(2025, 4, 1))
    tb = books.trial_balance(mongo_store, acme_with_year_one, date(2025, 4, 1))
    assert net(tb, "7300") == D("38.50") and net(tb, "2201") == 0

def test_the_rows_trial_balance_equals_the_posted_one(mongo_store, mongo_db, acme_with_year_one):
    # The two rows above, then ledger_book.post. Assert the lines of books.trial_balance equal the lines of
    # ledger_book.posted_trial_balance, by (code, debit, credit).
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_books.py -k "suspense or under_50 or equals_the_posted" -v`.
  Expected: FAIL. 7400 holds £240.00.

- [ ] **Step 3: Implement.** `_Books.post(self, settings, keep, opening) -> TrialBalance` returns
  `summarise([line for n, tx in matched_rows(...) for line in journal_with_rule(tx, n, document_rule(tx, settings))], opening)`.
  - Pass the same arguments `posting.trial_balance` is given today.
  - Drop the now-unused `trial_balance as post` import if nothing else uses it.

- [ ] **Step 4: Run** the three tests: PASS. Then run `.venv/bin/pytest -q`.
  - Expect failures in tests whose expected figures assumed an undocumented purchase of £50 or more is booked as a
    cost. Fix each one by confirming that the only difference is the amount moving to 9998.
  - Where a test is about something else, add the document row it lacks instead of changing its figures.
  - Never weaken a test to make it pass. List the tests you changed in the commit message.

- [ ] **Step 5: Commit.**
  `git commit -m "fix: the rows' trial balance holds undocumented purchases in Suspense, as the posted ledger does"`

### Task 2: "Held in Suspense" shown on the row

**Files:**
- Modify: `ledgersync/books.py`. `_saved_rows`, after the statement and file-date loop.
- Modify: `frontend/src/lib/ledger.ts`. Add the issue title next to `vat_not_booked: 'VAT not booked'` (line ~215).
- Test: `tests/test_books.py` and `frontend/src/lib/ledger.test.ts` (the code list at line ~262).

**Interfaces:**
- Produces: issue code `needs_document`, severity `warning`, on a booked row that the rules hold. The issue title is
  `'Needs its document'`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_held_purchase_says_what_it_needs`:
    - the £240.00 Trainline line has one `needs_document` issue, with message
      `"Held in Suspense: needs its receipt or invoice."`;
    - a £300.00 line has the same issue, with `"Held in Suspense: needs a full VAT invoice."`;
    - the £38.50 line has none;
    - `books.summary(...).to_review` counts the two held rows.
  - In `ledger.test.ts`, add `'needs_document'` to the list asserting every code has a title.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_books.py -k held_purchase -v` and `cd frontend && npm test`.
  Both FAIL.
- [ ] **Step 3: Implement.**
  - In `_saved_rows`, for each `k` where `booked(ready[k])` and `document_rule(ready[k], settings).action == "hold"`,
    replace `ready[k]` with a copy whose `issues` gain `checks.issue("needs_document", HELD[rule.needs], "warning")`.
  - `HELD` is a module constant mapping `"receipt_or_invoice"` and `"vat_invoice"` to the two messages above.
  - Add `needs_document: 'Needs its document'` to the titles map in `ledger.ts`.
- [ ] **Step 4: Run** both commands again: PASS. Then `.venv/bin/pytest -q`: PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: a purchase held for its document says so on the row"`

### Task 3: The record of changes

**Files:**
- Modify: `ledgersync/models.py`. Add after `Decision` (line ~548).
- Modify: `ledgersync/records.py`. Add methods, an index in `__init__`, and a change in `append_decision`.
- Test: `tests/test_records.py`

**Interfaces:**
- Produces:

```python
ChangeKind = Literal["upload_read", "upload_removed", "upload_bank_changed", "row_edited", "row_added",
                     "row_removed", "row_linked", "row_included", "rows_apart", "row_reverted", "client_changed",
                     "opening_balances_changed", "question_answered", "decision", "year_reopened"]

class ChangeDraft(BaseModel):
    client_id: int
    year_start: Optional[dt.date] = None   # None: the whole client, or a year the caller doesn't know
    actor: str                             # "user", "import", "rules" or "agent:<model>"
    kind: ChangeKind
    row_ids: list[int] = Field(default_factory=list)
    upload_id: Optional[int] = None
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    summary: str                           # one line, plain English: "Row 25 changed: account 8201 → 2250"

class Change(ChangeDraft):
    id: str
    seq: int          # time.time_ns() when added; orders changes
    created_at: str   # rows.now_iso()
```

- `AgentRecords.add_change(self, c: ChangeDraft) -> Change`
- `AgentRecords.changes(self, client_id: int, *, year_start: Optional[dt.date] = None, since: Optional[str] = None, limit: int = 200) -> list[Change]`
  - returns changes oldest first;
  - with `year_start`, it returns that year's changes **and** those with no year;
  - with `since`, only those whose `created_at` is later;
  - with `limit`, the latest that many.

- [ ] **Step 1: Write the failing tests.**
  - `test_changes_are_kept_in_order_and_filtered_by_year`: three changes (year 2025, year 2026, no year).
    `changes(id, year_start=2025)` returns the 2025 one and the no-year one, in order.
  - `test_changes_since_a_time_are_the_later_ones`.
  - `test_a_new_decision_adds_one_change_and_a_retried_one_none`:
    - `append_decision` twice with the same key gives one change, `kind == "decision"`;
    - the change's `actor` is the decision's actor and its `row_ids` are the decision's;
    - `after == {"decision_id": <id>}`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_records.py -k change -v`. FAIL.
- [ ] **Step 3: Implement.**
  - The collection is `changes`, indexed on `(client_id, seq)`.
  - In `append_decision`, add the change only on the path that returns `(decision, True)`, with
    `summary=f"{d.rule}: {d.status}"`.
- [ ] **Step 4: Run** the tests again, then `.venv/bin/pytest -q`. PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: keep a record of every change to a client's books"`

### Task 4: Settle after a change

**Files:**
- Create: `ledgersync/upkeep.py`
- Modify: `ledgersync/questions.py`. `_wanted` also returns the built ledger. `refresh` answers a resolved document
  question with the file that settled it. `rule_questions` takes `[0]`.
- Modify: `ledgersync/agent/chat.py`. `Chat._write` (line ~461) calls `upkeep.settle`.
- Test: `tests/test_upkeep.py` (new; `pytestmark = pytest.mark.mongo`; fixtures as in `tests/test_questions.py`).

**Interfaces:**
- Consumes:
  - `resolutions.record_automatic(store, records, *, client_id, year_start, thread_id)`;
  - `questions.refresh(store, records, client_id, year_start)`;
  - `ledger_book.post(store, records, client_id, year_start, *, decision_ids)`;
  - `books.years_of(store, client_id, today)`;
  - `ClientLocks.hold(client_id)`;
  - `AgentRecords.add_change` (Task 3).
- Produces:
  - `upkeep.settle(store, records, client_id: int, year_start: dt.date, *, thread_id: Optional[str] = None, decision_ids: Sequence[str] = ()) -> PostResult`.
    This is the three calls above, in that order; the caller holds the lock.
  - `upkeep.after_change(store, records, locks: ClientLocks, change: ChangeDraft, *, today: Optional[dt.date] = None) -> dict[dt.date, PostResult]`:
    - records the change first;
    - then, for every year of the client that isn't closed, takes `locks.hold(change.client_id)` and settles it;
    - a year whose settle raises is logged on logger `ledgersync.upkeep` (with the exception) and left out of the
      result;
    - it never raises after the change is recorded.

- [ ] **Step 1: Write the failing tests** with `travel_line` and `trainline_invoice`, as defined in
  `tests/test_questions.py`.
  - `test_a_document_added_later_closes_its_question_and_clears_suspense`:
    1. Add `travel_line()`, then call `after_change(... kind="upload_read")`. Assert one open
       `receipt_or_invoice` question, and posted Suspense of £240.00.
    2. Add `trainline_invoice()` as a second upload, then call `after_change` again. Assert:
       - the question is resolved, with answer `"Matched to rows.csv"`;
       - `posted_trial_balance(...).suspense == []`;
       - `ledger_book.unposted_changes(...) == 0`;
       - `books.trial_balance` lines equal the posted lines.
  - `test_after_change_records_the_change_before_settling`: the change is in `records.changes(acme)` even when
    `settle` is monkeypatched to raise.
  - `test_after_change_settles_every_open_year` (fixture `acme_two_years`): both years get a posting batch.
  - `test_after_change_skips_closed_years`:
    - close year one with `books.close`;
    - make a change in year two;
    - the count of `posting_batches` for year one doesn't change.
  - `test_a_failing_settle_is_logged_not_raised`: with `caplog`, the monkeypatched `settle` raises `RuntimeError`.
    `after_change` returns `{}` and a `ledgersync.upkeep` record is logged.
  - `test_settle_with_a_blocked_year_returns_problems`:
    - a row with an error-level issue (use an existing fixture, such as `acme_with_a_non_gbp_row`);
    - `after_change` returns a `PostResult` with `problems` and `batch_id is None`.
  - `test_settle_runs_inside_the_clients_lock`:
    - a stand-in `locks` whose `hold` is a context manager recording `(client_id, "enter"/"exit")`;
    - the monkeypatched `settle` asserts it is called between enter and exit.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_upkeep.py -v`. FAIL: there is no module `ledgersync.upkeep`.
- [ ] **Step 3: Implement `upkeep.py`.**
  - In `questions.refresh`, when a `rules` question of kind `receipt_or_invoice` or `vat_invoice` is no longer
    wanted, find the held row in the built ledger. If it now `pays` a document, find the row whose `document_ref`
    equals `pays[0].ref`. Resolve the question with `f"Matched to {name}"`, where `name` is that row's upload name
    from `built.uploads`. Otherwise resolve it with `None`, as now.
  - Change `Chat._write` to
    `return upkeep.settle(self.store, self.records, thread.client_id, thread.year_start, thread_id=thread.id, decision_ids=[d.id for d in sorted_since(self.records, thread, since)])`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_upkeep.py tests/test_questions.py tests/test_chat_api.py -v`,
  then `.venv/bin/pytest -q`. PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: settle a client's books after any change, not only at the end of a chat turn"`

### Task 5: Every data-changing route records a change and settles

**Files:**
- Modify: `server.py`.
  - Add a helper inside `create_app`, `changed(client_id, kind, summary, *, actor="user", year_start=None, row_ids=(), upload_id=None, before=None, after=None) -> None`.
    It builds a `ChangeDraft` and calls `upkeep.after_change(store, chat.records, chat.locks, draft)`.
  - Call `changed` after each route below succeeds.
  - Give `submit_analysis` and `run_analysis` an `actor: str = "user"` parameter. The folder import passes
    `"import"`.
- Modify: `ledgersync/questions.py`. `answer` adds a `question_answered` change: actor `"user"`, the question's
  rows, summary `f"Answered: {q.text}"`.
- Test: `tests/test_upkeep_api.py` (new), using the `api` fixture pattern from `tests/test_clients_api.py`.

**Routes, kinds and summaries:**

| Route | kind | summary | before/after |
|---|---|---|---|
| `PATCH /rows/{id}` | `row_reverted` if `revert`; else `row_linked` if `link` is sent; else `row_included` if `include`; else `rows_apart` if `apart_from`; else `row_edited` | `f"Row {id} changed: {', '.join(fields sent)}"` | the stored values of the fields sent, then the values sent |
| `DELETE /rows/{id}` | `row_removed` | `f"Row {id} removed"` | the row's `description`, `gross`, `account_code` |
| `POST /uploads` (manual) | `row_added` | `f"{n} {'row' if n == 1 else 'rows'} added by hand"` | — |
| `PATCH /uploads/{id}` | `upload_bank_changed` | `f"{name} moved to {code}"` | `bank_account` before and after |
| `DELETE /uploads/{id}` | `upload_removed` | `f"{name} removed"` | — |
| `PATCH /clients/{id}` | `client_changed` | `f"Client details changed: {', '.join(fields sent)}"` | the stored values of the fields sent, then the values sent |
| `PUT /opening-balances` | `opening_balances_changed` | `"Opening balances changed"` | — |
| `POST /years/{start}/reopen` | `year_reopened` | `f"Year to {long_date(end)} reopened"` | — |
| `run_analysis`, after `store.add_upload` | `upload_read` | `f"{name} read: {n} {'row' if n == 1 else 'rows'}"` | — |

- `year_start` is the year when the route has it (`run_analysis`, reopen); otherwise `None`.
- `upload_id` is set for upload routes and `upload_read`.
- Read the "before" values before the change is made.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_receipt_uploaded_outside_the_chat_clears_its_question` (the F4 case from the findings):
    1. Use `manual` to add a bank line: 3 Oct 2026, £86.40, out, `document_type="statement"`, counterparty
       `"Screwfix Direct"`, account `5000`, in a year the client has.
    2. Assert that `GET /api/clients/{id}/questions` has one open `receipt_or_invoice` question, and that
       `GET .../posted-trial-balance` shows Suspense £86.40 and `unposted_changes == 0`.
    3. Use `manual` again to add the receipt: same date and amount, `document_type="receipt"`, counterparty
       `"Screwfix Direct"`.
    4. Assert the question is resolved (no longer listed), `posted-trial-balance.suspense == []`, and
       `GET .../trial-balance` has no 9998 line.
  - `test_each_route_records_one_change`, parametrised over the table above (except `run_analysis`): call the
    route, then `AgentRecords(mongo_db).changes(client_id)[-1].kind` is the expected kind and its `summary` is the
    expected text.
  - `test_reading_an_upload_records_upload_read`: `POST /api/analyze` with `FakeModel` (as `tests/test_api.py`
    does). After the job finishes, the last change is `upload_read` with the upload's id.
  - `test_a_row_edit_succeeds_when_upkeep_fails`: monkeypatch `upkeep.settle` to raise. `PATCH` a row gets 200, and
    the edit is saved.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_upkeep_api.py -v`. FAIL.
- [ ] **Step 3: Implement** as in the table.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. PASS.
  - Tests that asserted `unposted_changes > 0` after a page edit (in `tests/test_chat_api.py` and
    `tests/test_ledger_book.py`) now see 0. Update them to the new behaviour and say so in the commit message.
- [ ] **Step 5: Commit.** `git commit -m "feat: every change from the pages is recorded and settles the books at once"`

### Task 6: The agent reads the changes; the Overview stops talking about two ledgers

**Files:**
- Modify: `ledgersync/agent/tools.py`. Add `list_changes`, next to `list_decisions` (line ~414).
- Modify: `ledgersync/agent/prompt.py`. Add one rule line.
- Modify: `frontend/src/lib/ledger.ts`. Add `postedLedgerNote`.
- Modify: `frontend/src/components/OverviewSection.tsx`. Line ~96 uses `postedLedgerNote`.
- Modify: `README.md`. Add a short "Books kept up to date" paragraph under "The site": after any change the
  questions and the posted ledger are brought up to date at once, and every change is recorded.
- Test: `tests/test_agent.py` (follow the existing `list_decisions` tool test there),
  `frontend/src/lib/ledger.test.ts`.

**Interfaces:**
- `list_changes(runtime: ToolRuntime[ChatContext], since: Optional[str] = None) -> dict`.
  - It returns `{"changes": [{"changed_at", "by", "kind", "summary", "row_ids", "upload_id", "before", "after"}]}`
    for `ctx.client_id` and `ctx.year_start`.
  - It returns changes later than `since` (an ISO time), or the latest 50 when `since` is left out.
  - Its step lines are `"Checking what has changed…"`, then `"Read N changes"` or `"Nothing has changed"`.
  - Docstring: "What has changed on the client's year, oldest first: who changed it (the person, an import, the
    rules or the agent), what kind of change, the rows and file it touched, the values before and after, and a
    one-line summary. since: an ISO time; leave it out for the latest 50. Use it to say what has changed since the
    last review."
- The prompt line: "When asked what has changed, call list_changes first and say what changed and who changed it
  before anything else."
- `postedLedgerNote(unposted: number | null): string | null`:
  - `null` when `unposted` is `null` or `0`;
  - otherwise `` `Not up to date: ${n} ${n === 1 ? 'change' : 'changes'} not posted. See Trial balance.` ``.

- [ ] **Step 1: Write the failing tests.**
  - `test_list_changes_returns_the_years_changes_since_a_time`: two changes, then `since` set between them. Only
    the later one is returned, with `by == "user"`.
  - A prompt test: `"list_changes" in SYSTEM_PROMPT` (use whatever the constant is called in `prompt.py`).
  - `ledger.test.ts`: `postedLedgerNote(0) === null`, `postedLedgerNote(null) === null`, and
    `postedLedgerNote(2) === 'Not up to date: 2 changes not posted. See Trial balance.'`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_agent.py -k list_changes -v` and `cd frontend && npm test`. FAIL.
- [ ] **Step 3: Implement.** Register `list_changes` in `make_tools`' returned list. The Overview renders
  `<p className="muted small">{note}</p>` only when the note isn't `null`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`, `cd frontend && npm test`, and `cd frontend && npx tsc --noEmit`.
  PASS.
- [ ] **Step 5: Commit.** `git commit -m "feat: the agent can say what has changed; the Overview drops the posted-ledger count"`

### Task 7: Check it in the site (no model credit)

**Files:** none changed, unless the check finds a bug. A bug goes back to the task that owns it.

- [ ] **Step 1:** Start an isolated API and site against a local MongoDB, as in findings section 5 (the
  `api-accountant-test-8095` and `web-accountant-test-3007` entries in `.claude/launch.json`, on a fresh database
  name).
- [ ] **Step 2:** Through the API, add a client and a manual bank line (Screwfix £86.40, as in Task 5). Open its
  Overview and Transactions in the browser. Expect:
  - "1 thing needs you";
  - the row titled "Needs its document" with "Held in Suspense: needs its receipt or invoice.";
  - no "Posted ledger" line;
  - Trial balance showing 9998 £86.40.
- [ ] **Step 3:** Add the receipt as a manual row. Reload. Expect:
  - no question;
  - no warning on the bank line;
  - no 9998 in the Trial balance;
  - the chat's posted trial balance agrees.
- [ ] **Step 4:** Take a screenshot of the Overview and Trial balance for the user. Report anything that differs.
