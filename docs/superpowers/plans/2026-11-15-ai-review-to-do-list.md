# AI review as one to-do list: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The AI review page becomes one list of what needs the person (a card per row, document or row-less question), one notice for failed runs with Try again, and the history collapsed below.

**Architecture:** The page already loads the year's rows, the waiting suggestions and the runs. Two pure rules in `frontend/src/lib` turn them into cards and into history lines, tested with `node --test`; thin components draw them. The Transactions page's issue list and its edit/add dialogs are moved into shared pieces so a card's controls are the same code. One new API route makes a client's review due now.

**Tech stack:** Next.js / React / TypeScript (`frontend/`), FastAPI (`server.py`), pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-15-ai-review-to-do-list-design.md`

## Global constraints

- Use `QuestionCard` and `DecisionLine` as they are: no edit under `frontend/src/components/chat/`.
- New styles go in one new block of `frontend/src/app/globals.css`, headed `/* AI review: the to-do list */`. Reuse `.notice`, `.badge`, `.issues`, `.question-row`, `.decisions`, `.btn-small`, `.link-btn`.
- No edit to `ledgersync/reviews.py` or anything under `ledgersync/agent/` (other uncommitted work lives there).
- A closed year or an archived client: `readOnly = year.closed || client.archived`; no control that changes anything is drawn or enabled.
- Opening the page still calls `markReviewsSeen` after the first successful load.
- Read `frontend/AGENTS.md` before touching a Next API you are not sure of.
- Checks: `cd frontend && npm test` and `npx tsc --noEmit`; Python with `.venv/bin/python -m pytest <file>` (never the whole suite per task: it takes 55 minutes).
- Commit only when the person asks. Other sessions' work is uncommitted in this checkout: when asked, stage only the files a task names.

## Review focus

Each line is pinned by a test in the task named.

1. A suggestion or a question names a row that is no longer in the year's rows: it still gets a card, titled by its own text, with no Show link (Task 2).
2. Two runs carry the same open question: one card (Task 2).
3. The newest run is still running after earlier failures: the notice says "Reviewing…", not that the review failed (Task 3).
4. Failures at the top with different errors: the notice counts all of them and gives the newest error; Activity folds only neighbours with the same error (Task 3).
5. Try again while a review is already running: nothing is changed and the call succeeds (Task 1).

---

### Task 1: Try again route

**Files:**
- Modify: `server.py` (after `reviews_seen`, about line 749)
- Modify: `frontend/src/lib/reviews.ts`
- Test: `tests/test_reviews_api.py`

**Interfaces:**
- Produces: `POST /api/clients/{client_id}/reviews/retry` → `{"due": true}`; `retryReview(clientId: number): Promise<unknown>` in `reviews.ts`.

- [ ] **Step 1: Write the failing tests** in `tests/test_reviews_api.py`, using the `app`, `records`, `nb` fixtures.

```python
def test_try_again_makes_the_review_due_now(app, records, nb):
    records.patch_review_state(nb.id, due_at=None, retry_at="2999-01-01T00:00:00+00:00")
    before = dt.datetime.now(dt.timezone.utc)
    assert app.post(f"/api/clients/{nb.id}/reviews/retry").json() == {"due": True}
    state = records.review_state(nb.id)
    assert state.retry_at is None
    assert dt.datetime.fromisoformat(state.due_at) <= dt.datetime.now(dt.timezone.utc)
    assert dt.datetime.fromisoformat(state.due_at) >= before - dt.timedelta(seconds=1)


def test_try_again_leaves_a_running_review_alone(app, records, nb):
    records.patch_review_state(nb.id, running=True, due_at=None, retry_at=None)
    assert app.post(f"/api/clients/{nb.id}/reviews/retry").status_code == 200
    state = records.review_state(nb.id)
    assert state.running and state.due_at is None


def test_try_again_is_refused_for_an_archived_client_and_an_unknown_one(app, records, nb):
    assert app.post("/api/clients/999999/reviews/retry").status_code == 404
    app.patch(f"/api/clients/{nb.id}", json={"archived": True})
    assert app.post(f"/api/clients/{nb.id}/reviews/retry").status_code == 409
    assert records.review_state(nb.id).due_at is None
```

Also add `(f"/api/clients/{nb.id}/reviews/retry", None)` to the list in `test_writes_need_the_ledgersync_header`.

- [ ] **Step 2: Run them, expect 404/405 failures.** `.venv/bin/python -m pytest tests/test_reviews_api.py -k "try_again or header" -q`

- [ ] **Step 3: Add the route** `retry_review(client_id, x_ledgersync)`: `from_our_pages`, `ledger.require_active(store.get_client(client_id))`, then, unless `chat.records.review_state(client_id).running`, `patch_review_state(client_id, due_at=reviews.utcnow().isoformat(timespec="seconds"), retry_at=None)`. Returns `{"due": True}`.

- [ ] **Step 4: Run the whole file, expect all passing.** `.venv/bin/python -m pytest tests/test_reviews_api.py -q`

- [ ] **Step 5: Add** `export const retryReview = (clientId: number) => post(`/api/clients/${clientId}/reviews/retry`)` to `reviews.ts`; `npx tsc --noEmit` clean.

---

### Task 2: The rule that makes the cards

**Files:**
- Create: `frontend/src/lib/todo.ts`, `frontend/src/lib/todo.test.ts`

**Interfaces:**
- Consumes: `rowIssues`, `documentProblems`, `leftOut` from `ledger.ts`; `Decision`, `Question`, `formatMoney` from `chat.ts`; `dayMonth` from `clientRules.ts`; `ReviewDetail` from `reviews.ts`; `FAMILIES`/`TITLES` copied from `problems.ts` (that file is deleted in Task 6).
- Produces:

```ts
export interface TodoCard {
  key: string                  // 'row:7', 'doc:7' or 'q:<question id>' / 's:<decision id>' for a card with no row
  kind: 'row' | 'document' | 'other'
  row: SavedRow | null         // null only when the row it names is not in the year's rows, or it names none
  tag: string                  // 'Account', 'Recorded twice', …, 'Document total', 'Question', 'Suggestion'
  title: string
  issues: Issue[]              // warnings and errors only
  lines: number[]              // a document card: its lines
  suggestions: Decision[]
  questions: Question[]
  waiting: boolean             // nothing on it but questions answered "I don't have it" / "Not sure"
}
export function todoCards(rows: SavedRow[], suggestions: Decision[], questions: Question[],
                          fileOf: (row: SavedRow) => string): TodoCard[]
export const needCount = (cards: TodoCard[]): number          // cards that are not waiting
export const waitingSuggestions = (cards: TodoCard[]): Decision[]
export function openQuestions(runs: ReviewDetail[]): Question[]   // status not 'resolved', one per id
```

Rules the tests pin:
- A row card for every row in the books with at least one of its own warnings or errors (`rowIssues`, `severity !== 'info'`); its tag is the family title of its first issue after sorting errors first (`'Other'` for an unknown code); its title is `description, 12 Oct, £86.40` as `whatOf` in `problems.ts` writes it.
- A document card for every `documentProblems` entry: tag `'Document total'`, title `fileOf(row)`.
- A suggestion or a question goes to the first of its `row_ids` that has a row card; failing that, a document card whose `lines` hold one of them; failing that, a card of its own: kind `'other'`, `row` the first of its rows found in `rows` (left-out rows count) or null, title that row's `whatOf`, or the question's `text` / the decision's `rule` without its `R\d+ ` prefix when there is no row; tag `'Question'` or `'Suggestion'`. Two that fall to the same row share that card.
- Order: 0 a card with an error; 1 with a question of status `'open'`; 2 with a suggestion; 3 the rest; 4 `waiting`. Within a rank by the row's date ascending, undated and row-less last, then by `key`.

- [ ] **Step 1: Write the failing tests** in `todo.test.ts`, with the row and suggestion factories of `problems.test.ts`. One test per name, asserting as shown:

```ts
test('a row with two warnings is one card, tagged by the first', () => {
  const cards = todoCards([row(1, ['unusual_account', 'date_missing'])], [], [], file)
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].key, cards[0].kind, cards[0].tag, cards[0].issues.length], ['row:1', 'row', 'Account', 2])
})
test('a note alone, or a row left out, makes no card', …)            // info only; excluded: true  → []
test('a document problem is a card named by its file', …)            // about: 'document' → key 'doc:1', tag 'Document total', title 'claim.xlsx, expense claim', lines [1, 2]
test('a suggestion and a question land on their row’s card', …)      // one card; suggestions.length 1, questions.length 1
test('a suggestion for a line of a document with a problem lands on the document’s card', …)
test('a question about a row with no problem gets its own card, named by the row', …)   // key 'q:Q1', tag 'Question', row.id 5
test('a question that names no row is titled by its text', …)        // row null, title 'Is there a payroll report?'
test('a suggestion whose row is gone is titled by its rule', …)      // row_ids [99]; row null, title 'Duplicate: kept the receipt', key 's:D1'
test('errors come first, then questions, then suggestions, then the rest by date, waiting last', …)   // deepEqual on keys
test('a card with only a waiting question is waiting and not counted', …)   // waiting true; needCount 0
test('the same question in two runs is listed once; a resolved one is not', …)   // openQuestions
test('waitingSuggestions lists each suggestion once', …)
```

- [ ] **Step 2: Run, expect "Cannot find module ./todo.ts".** `cd frontend && npm test`
- [ ] **Step 3: Implement `todo.ts`** to the interface and rules above.
- [ ] **Step 4: Run, expect all passing;** `npx tsc --noEmit` clean.

---

### Task 3: The rules for the notice and the history

**Files:**
- Modify: `frontend/src/lib/reviews.ts`, `frontend/src/lib/reviews.test.ts`

**Interfaces** (all take runs newest first, as `newestFirst` returns them):

```ts
export interface ReviewNotice { kind: 'reviewing' | 'failed' | 'limited' | 'off'; text: string; retry: boolean }
export function reviewNotice(runs: ReviewDetail[], now?: Date): ReviewNotice | null
export interface ActivityLine { key: string; text: string; failed: boolean }
export function activityLines(runs: ReviewDetail[], now?: Date): ActivityLine[]
export interface AiChange { decision: Decision; fresh: boolean }
export function aiChanges(runs: ReviewDetail[], reversed: Set<string>, freshRuns: Set<string>): AiChange[]
export function lastReviewed(runs: ReviewDetail[], now?: Date): string | null   // runWhen of the newest 'done' run
```

Exact copy:
- `reviewNotice`, by the newest run's status: `running` → `Reviewing…`; `limited` → `AI review is paused for today: limit reached.`; `off` → `AI review is off for this client.`; `failed` → `The review hasn't finished since ${runWhen(oldest of the unbroken failures)}: ${newest error} (${n} ${n === 1 ? 'try' : 'tries'}).`, without `: error` when the error is empty, `retry: true`. `done` or no runs → null. Only `failed` has `retry`.
- `activityLines`: a `done` or `running` run → `runTitle(run)`, plus ` ${n} other change(s) the AI tried was/were stopped by the checks and not made.` when it has refused decisions (move `refusedLine` here from `AiReviewSection.tsx`); `limited` → `${runWhen}: paused for today: limit reached`; `off` → `${runWhen}: AI review is off for this client`; one failure → `${runWhen}${trigger ? ', ' + trigger : ''} · didn't finish${error ? ': ' + error : ''}`; neighbouring failures with the same error → one line `${runWhen(oldest)} to ${newest's clock, or its runWhen when on another day} · ${n} runs didn't finish${error ? ': ' + error : ''}`, `key` the newest's id.
- `aiChanges`: every decision of a `done` or `running` run with `status === 'applied'`, no `reverses`, its id not in `reversed` and not reversed inside its own run; newest run first; `fresh` when its run's id is in `freshRuns`.

- [ ] **Step 1: Write the failing tests** in `reviews.test.ts`, with its existing run factory and a fixed `now`:

```ts
test('five failures at the top are one notice with Try again', …)
// text "The review hasn't finished since Fri 13 Nov 16:33: API key expired (5 tries).", retry true
test('one failure says 1 try; no error leaves the colon out', …)
test('a run still going after failures says Reviewing…', …)          // kind 'reviewing', retry false
test('a success at the top, or no runs, has no notice', …)
test('paused and off are notices without a button', …)
test('failures with different errors: the notice counts all three and gives the newest error', …)
test('five failures with one error fold into one activity line', …)
// ["Fri 13 Nov 16:33 to 17:13 · 5 runs didn't finish: API key expired"]
test('a success between failures breaks the fold', …)                 // 3 lines: failed, done, failed
test('failures with different errors are separate lines', …)
test('a finished run reads as its title, with what the checks stopped', …)
test('aiChanges lists applied changes newest first and leaves out undos, undone and refused', …)
test('aiChanges marks the changes of runs not yet seen', …)
test('lastReviewed is the newest finished run, null when none finished', …)
```

- [ ] **Step 2: Run, expect the new names undefined.** `npm test`
- [ ] **Step 3: Implement** the four functions in `reviews.ts`.
- [ ] **Step 4: Run, expect all passing;** `npx tsc --noEmit` clean.

---

### Task 4: One issue list for both pages

A move with no change in behaviour.

**Files:**
- Create: `frontend/src/components/IssueList.tsx`, `frontend/src/components/useAccountChoices.ts`
- Modify: `frontend/src/components/TransactionsTable.tsx`

**Interfaces:**
- Produces: `export default function IssueList(props)` with the props it has today (lines 51-63 of `TransactionsTable.tsx`), and `export const MARKS`; `useAccountChoices(wanted: boolean): AccountChoice[]`, the effect at `TransactionsTable.tsx` lines 151-165 as a hook (reads the client from `useClientYear`).

- [ ] **Step 1:** Move `IssueList`, `SEVERITY_ORDER` and `MARKS` to `IssueList.tsx` unchanged; move the accounts effect to `useAccountChoices.ts`; `TransactionsTable` imports both and passes `wantsAccounts`.
- [ ] **Step 2:** `npx tsc --noEmit` clean; `npm test` passing; `git diff --stat` shows `TransactionsTable.tsx` only losing lines.
- [ ] **Step 3:** In the preview app, the Transactions page of a client with issues draws its issues, the account chooser lists accounts, and the document strip is there, with no console error.

---

### Task 5: Edit and Add line from either page

A move with no change in behaviour on Transactions.

**Files:**
- Create: `frontend/src/components/useRowDialogs.tsx`
- Modify: `frontend/src/components/TransactionsSection.tsx`

**Interfaces:**
- Produces: `useRowDialogs(): { edit: (row: SavedRow) => void; add: (lineOf: SavedRow | null) => void; dialogs: ReactNode }`. It holds `editing`, `adding`, `startAdding`, `saveNew`, `saveRow` and the two `EditRowDialog`s of `TransactionsSection.tsx`, unchanged, taking `client`, `year` and `show` from `useClientYear`.

- [ ] **Step 1:** Move them; `TransactionsSection` uses `const { edit, add, dialogs } = useRowDialogs()`, passes `onEdit={edit} onAdd={add}` and renders `{dialogs}`.
- [ ] **Step 2:** `npx tsc --noEmit` clean; `npm test` passing.
- [ ] **Step 3:** In the preview app: Edit a row and save; Add line on a claim and cancel. Both behave as before.

---

### Task 6: The page

**Files:**
- Create: `frontend/src/components/TodoList.tsx`, `frontend/src/components/ReviewHistory.tsx`
- Modify: `frontend/src/components/AiReviewSection.tsx`, `frontend/src/app/globals.css`
- Delete: `frontend/src/components/ProblemsList.tsx`, `frontend/src/lib/problems.ts`, `frontend/src/lib/problems.test.ts`; `runSaid` and its tests if nothing imports it after this task

**Interfaces:**
- Consumes: Task 1 `retryReview`; Task 2 `todoCards`, `needCount`, `waitingSuggestions`, `openQuestions`, `TodoCard`; Task 3 `reviewNotice`, `activityLines`, `aiChanges`, `lastReviewed`; Task 4 `IssueList`, `useAccountChoices`; Task 5 `useRowDialogs`; `clientDecisions` from `lib/api`.
- Produces: `TodoList({ cards, rows, readOnly, working, refused, effects, rowHref, onChange, onApply, onEdit, onAddLine, answerer, onAnswered, onSay })` and `ReviewHistory({ changes, made, lines, readOnly, working, refused, onUndo })`.

`AiReviewSection` keeps its loading, `change`, `applyAll`, `answered`, `say` and `markReviewsSeen`, and gains:
- `clientDecisions(client.id, year.start)` in `load`; `reversed` is the set of ids some decision `reverses`, joined with the local `undone`.
- `freshRuns`: the ids of runs with `!seen`, captured from the first load only (a ref), so "new since you last looked" survives the reloads that follow an action.
- `onChange(rowId, change)`: `show(await changeRow(client.id, rowId, change))` from `useClientYear`, errors to the page's notice. It replaces `leave`.
- `retry`: `retryReview(client.id)`, then reload the runs every 3 seconds while the newest run is the one that was newest at the click or is `running`, for at most 2 minutes; when it finishes, `load()` and `reload()`.

Layout, top to bottom:
1. The notice (`reviewNotice`): `notice notice-error` with a `Try again` button for `failed`; `notice notice-info` otherwise; "Reviewing…" with the spinner while a retry is waiting.
2. Lines for what was answered on this visit: each `effects` entry as a muted line.
3. Heading: `${needCount} thing(s) need you`, and `Apply all ${n} suggestions` when `waitingSuggestions(cards).length > 1` (disabled when `readOnly`). With no cards: `Nothing needs you.` and `Last reviewed ${lastReviewed}.` when there is one, else `No review has run on this year yet. One runs after the books change and go quiet.`
4. `TodoList`.
5. `ReviewHistory`: two `<details>`, closed: `Changed by the AI (${n})` with `· ${k} new` when any are fresh, and `Activity`.

`TodoList`, per card (`<li className="todo-card">`, plus `todo-waiting` when `card.waiting`):
- Head: `<span className="badge badge-muted">{tag}</span>`, the title in bold, `Waiting on you` badge when waiting, and, when `card.row`, a `Show` link to `rowHref(card.row.id)` (`Show its lines` on a document card).
- A row card: `IssueList` wired as `TransactionsTable.tsx` lines 410-417 wire it, with `onShowBoth` going to `rowHref(row.id)` and `onChange` for Not the same, It's fine and the fixes; `onEdit` from `useRowDialogs`. A document card: wired as lines 318-323, `onAddLine` when `takesLines(row)`. Every handler is left out when `readOnly`, as the table does.
- Each suggestion: `DecisionLine`, then a `question-row` with `Apply` (`Applying…` while `working === d.id`) and `refused[d.id]`.
- Each question: `QuestionCard` with `number` its place on the card, `effect={effects[q.id] ?? null}`, `busy={readOnly}`.

`ReviewHistory`: each change as `DecisionLine` with `Undo` (`Undoing…`) and `refused[d.id]` (no badge per change: "new" is said once, on the summary); `made` (applied on this visit) listed first in the same way; each activity line a `<li>`, `field-error` when failed.

- [ ] **Step 1:** Build `TodoList.tsx` and `ReviewHistory.tsx`.
- [ ] **Step 2:** Rewire `AiReviewSection.tsx`; render `{dialogs}` from `useRowDialogs`; delete the files listed.
- [ ] **Step 3:** Add the stylesheet block: `.todo-list` (a grid, no bullets), `.todo-card` (the card border and radius, 12px padding), `.todo-head` (flex, wraps, 8px gap), `.todo-waiting` (muted), `.review-history` (top margin, summary as a small bold line).
- [ ] **Step 4:** `npx tsc --noEmit` clean; `npm test` passing; `grep -rn "ProblemsList\|lib/problems" frontend/src` finds nothing.

---

### Task 7: See it work

**Files:** none (the preview app set up for the last change: `web-removed-lines-3016` and `api-removed-lines-8103` in `.claude/launch.json`; copy `frontend/` to the scratchpad copy again and restart the API so it has the new route).

- [ ] **Step 1:** Seed the client with: a row with two warnings, a claim whose total doesn't add up, a waiting suggestion on a row with a problem, an open question on a row with none, a question with no row, a waiting question, five failed runs with one error, and one finished run with an applied change.
- [ ] **Step 2:** Check on the AI review page, by reading the page: the count; each card once, in order; the failed notice with its count; Try again turns it to "Reviewing…"; Apply and Leave it as it is take their card off the list; an answered question shows its line; Changed by the AI lists the change with Undo and says it is new; Activity folds the five failures into one line. No console error. Narrow width holds.
- [ ] **Step 3:** Open the same page for a closed year: no button that changes anything is enabled.
- [ ] **Step 4:** `npm test`, `npx tsc --noEmit`, `.venv/bin/python -m pytest tests/test_reviews_api.py -q`, then the whole Python suite once in the background.
