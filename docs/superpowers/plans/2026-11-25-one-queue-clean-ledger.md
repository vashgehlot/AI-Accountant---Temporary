# One Queue, Clean Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI review the one work queue, Transactions a compact ledger with a side panel, and show one "to do" number.

**Architecture:** Front end only (`frontend/`). Pure display and grouping logic goes in `src/lib/ledger.ts` and
`src/lib/todo.ts`, tested first with `node --test`; the components are reworked around it and checked in the browser
on the agency copy (web 3030, API 8120).

**Tech Stack:** Next.js 16, React 18, TypeScript, plain CSS in `src/app/globals.css`, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-25-one-queue-clean-ledger-design.md`

## Global Constraints

- No backend change: the API, issue codes and messages stay as they are.
- No accept-all for warnings; "Apply all N suggestions" and "Apply to all N" stay.
- Every control a row has today stays reachable (list in the spec's Anti-goals).
- The "Ledger" look: the tokens in `globals.css` (`--accent`, `--warn`, `--error`, `--ok`, `--rule`, `--muted`, …),
  serif headings, mono figures; both themes.
- Tests: `cd frontend && npm test` (all `src/lib/*.test.ts`), and `npx tsc --noEmit`. No Python tests are touched.
- No commits per task: the user commits only on their yes. Leave the user's own uncommitted backend edits alone.
- After each component task: `rsync -a frontend/src/ <scratchpad>/web/src/` so the check server on 3030 picks it up.

## Review Focus

1. A left-out row (struck through) must never show as flagged, and its panel offers Put back, not fixes.
2. A closed year or archived client: the panel and queue show no control that changes anything.
3. `?row=<id>` for a row not on the first page of 200 still opens it (the page grows to include it).
4. The queue's "done since you opened" never goes negative when a review adds cards.
5. ↑/↓ in the panel must not fire while typing in an input, select or textarea.

---

### Task 1: Row display helpers

**Files:**
- Modify: `frontend/src/lib/ledger.ts`
- Test: `frontend/src/lib/ledger.test.ts`

**Interfaces:**
- Produces:
  - `tableDate(iso: string | null): string` → `'01 Apr 23'`, `'—'` for none.
  - `signedAmount(tx: Transaction): { text: string; tone: 'in' | 'out' | 'plain' }` → `'+4,800.00'` / `'−504.00'`
    (U+2212); a journal is `'plain'` with no sign.
  - `rowHeadline(tx: Transaction, issues: Issue[], documentIssue?: Issue | null): { text: string; severity: 'error' | 'warning' | 'info' | null }`
  - `capActions(actions: RowAction[], limit?: number): { shown: RowAction[]; rest: RowAction[] }` (default 3)
  - `filterChips(f: RowFilters, names: { account: (code: string) => string; type: (t: string) => string }): { field: keyof RowFilters | 'dates' | 'amounts'; label: string }[]`

- [ ] **Step 1: Write the failing tests**

```ts
test('the table date is day, short month and two-digit year', () => {
  assert.equal(tableDate('2023-04-01'), '01 Apr 23')
  assert.equal(tableDate(null), '—')
})
test('money in is signed + and money out −; a journal has no sign', () => {
  assert.deepEqual(signedAmount(tx({ direction: 'in', gross: '4800.00' })), { text: '+4,800.00', tone: 'in' })
  assert.deepEqual(signedAmount(tx({ direction: 'out', gross: '504' })), { text: '−504.00', tone: 'out' })
  assert.equal(signedAmount(tx({ document_type: 'journal', gross: '2400' })).tone, 'plain')
})
test('a flagged row is headed by its worst issue, with +N for the rest', () => {
  const h = rowHeadline(tx({}), [issue('payout_report'), issue('non_gbp_currency', 'error'), issue('possible_duplicate')])
  assert.deepEqual(h, { text: 'Not in pounds · +2', severity: 'error' })
})
test("a document's problem heads each of its lines when the line has none worse", () => {
  assert.deepEqual(rowHeadline(tx({}), [], issue('total_mismatch')), { text: "Total doesn't add up", severity: 'warning' })
})
test('a row with nothing wrong is headed by its type and first status', () => {
  const h = rowHeadline(tx({ document_type: 'invoice', owed: '0', paid_by: [{ kind: 'statement', date: '2023-04-24' }] }), [])
  assert.deepEqual(h, { text: 'Invoice · paid 24 Apr', severity: null })
})
test('a left-out row is headed left out, never flagged', () => {
  assert.equal(rowHeadline(tx({ excluded: true }), [issue('x', 'error')]).severity, null)
})
test('more than three candidates: three shown, the rest in a picker', () => {
  const acts = [1, 2, 3, 4, 5].map(n => ({ label: `Link ${n}`, change: {} }))
  const { shown, rest } = capActions(acts)
  assert.equal(shown.length, 3); assert.equal(rest.length, 2)
})
test('each filter set is one chip; the two dates and the two amounts are one chip each', () => {
  const chips = filterChips({ ...NO_FILTERS, direction: 'out', from: '2023-04-01', to: '2023-06-30', min: '100' }, names)
  assert.deepEqual(chips.map(c => c.label), ['Money out', '01 Apr 23 – 30 Jun 23', 'From £100.00'])
})
```

(Use the file's existing `tx`/`issue` builders; `names` maps codes to names.)

- [ ] **Step 2: Run and see them fail** — `cd frontend && npm test` → FAIL, the new names are not exported.
- [ ] **Step 3: Implement the five functions** in `ledger.ts`. The headline's severity order is error > warning;
  info issues don't head a row. Its text is `issueTitle(code)`, without a trailing full stop. The plain headline is
  `DOCUMENT_TYPES[type]` (capitalised) then the first `rowStatus` text shortened: "Paid by bank line on 24 Apr" →
  "paid 24 Apr". A left-out row's text is `leftOutLabel(tx).toLowerCase()`.
- [ ] **Step 4: Run** — `npm test` → all pass.

### Task 2: Queue groups and progress

**Files:**
- Modify: `frontend/src/lib/todo.ts`
- Test: `frontend/src/lib/todo.test.ts`

**Interfaces:**
- Produces:
  - `type QueueGroup = 'fix' | 'question' | 'suggestion' | 'check' | 'waiting'`
  - `GROUP_LABELS: Record<QueueGroup, { title: string; note: string }>` (`fix`: "Must fix", "stops the books being
    posted"; `question`: "Questions", "the AI needs an answer"; `suggestion`: "Suggestions", "changes to apply or
    leave"; `check`: "To check", "warnings, one by one"; `waiting`: "Waiting on you", "answered: not yet to hand")
  - `groupOf(card: TodoCard): QueueGroup` — the same order as `rank`.
  - `queueGroups(cards: TodoCard[]): { group: QueueGroup; cards: TodoCard[] }[]` — in that order, empty groups left out.
  - `checkKinds(cards: TodoCard[]): { kind: string; cards: TodoCard[] }[]` — 'check' cards by `issueTitle` of their first
    issue, most cards first, then by name.
  - `cardKind(card: TodoCard): string` — that title, or the card's tag when it has no issue.
  - `doneSince(first: number | null, now: number): number` — `max(0, first − now)`, 0 when first is null.

- [ ] **Step 1: Write the failing tests**

```ts
test('each card falls in one group, errors before questions before suggestions before warnings', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(2, [issue('date_missing', 'error')])],
                          [suggestion('s', [9])], [question('q', [8])], file)
  assert.deepEqual(queueGroups(cards).map(g => g.group), ['fix', 'question', 'suggestion', 'check'])
})
test('a card only waiting on the person is in the last group', () => {
  const cards = todoCards([], [], [question('q', [8], 'waiting')], file)
  assert.equal(groupOf(cards[0]), 'waiting')
})
test('warnings are folded by kind, the biggest first', () => {
  const cards = todoCards([row(1, [issue('unusual_account')]), row(2, [issue('date_missing')]), row(3, [issue('date_missing')])], [], [], file)
  assert.deepEqual(checkKinds(cards).map(k => [k.kind, k.cards.length]), [['No date', 2], ["Not this supplier's usual account", 1]])
})
test('done since opening never goes below nothing', () => {
  assert.equal(doneSince(113, 108), 5); assert.equal(doneSince(100, 104), 0); assert.equal(doneSince(null, 3), 0)
})
```


- [ ] **Step 2: Run and see them fail** — `npm test` → FAIL.
- [ ] **Step 3: Implement**; `groupOf` reuses `rank` (export nothing else from it).
- [ ] **Step 4: Run** — `npm test` → pass.

### Task 3: `useTodo` and the Overview

**Files:**
- Create: `frontend/src/components/useTodo.ts`
- Modify: `frontend/src/components/OverviewSection.tsx`, `frontend/src/components/AiReviewSection.tsx`,
  `frontend/src/app/globals.css`

**Interfaces:**
- Produces: `useTodo(): { cards: TodoCard[] | null; need: number | null; runs: ReviewDetail[] | null; suggestions: Decision[]; questions: Question[]; reload: () => Promise<boolean>; error: string }`
  — loads `listReviews`, `listSuggestions`, `clientQuestions` for the context's client and year, again whenever
  `ledger` changes; builds cards with `todoCards(..., openQuestions(runs, questions, year.start), fileOf)` exactly as
  `AiReviewSection` does now.

- [ ] **Step 1:** Move AI review's loading of runs, suggestions and questions and its `cards` memo into `useTodo`;
  AI review keeps its decisions/materiality loading and uses the hook's `reload` where it called `load`.
- [ ] **Step 2:** Overview: the year's card first. Its first line is `{need} to do` linking to AI review ("Nothing
  to do" at 0, "Counting…" while null); then the other years' waiting questions, missing paperwork, pointers and the
  posted-ledger note as now; then tiles (`.status-tiles`, a grid of auto-fit 200px columns) for each bank account,
  Trial balance, Unpaid sales and Unpaid purchases, each a label, a value (the warn colour when it is a difference or
  Blocked) and its link. "Rows to review" goes, and so does the "N questions are waiting" line for this year (the
  count includes them).
- [ ] **Step 3:** Client details second, in `<details className="card section client-details">` closed, its
  `<summary>` reading `{business type} · {contact} · VAT {vat_number}` and holding Edit details; opened, today's grid.
- [ ] **Step 4:** `npx tsc --noEmit` → no errors; `npm test` → pass; rsync; check Overview on 3030 shows the same
  number as AI review's head.

### Task 4: Issues as lines

**Files:**
- Modify: `frontend/src/app/globals.css` (`.issues`, `.issue*`)

- [ ] **Step 1:** An issue loses its tinted box: no background; the mark and the `<strong>` heading take the severity
  colour (`--error`, `--warn`, the accent for info); the message is `--text`; actions sit under it as
  `.btn-small`-sized buttons (`.issue-actions .link-btn` gets a 1px `--rule` border, 6px radius, 2px 8px padding);
  `max-width` goes. Both themes.
- [ ] **Step 2:** rsync; look at an AI review card and a Transactions panel (after Task 6) in light and dark.

### Task 5: The filter bar

**Files:**
- Create: `frontend/src/components/FilterBar.tsx`
- Modify: `frontend/src/components/TransactionsTable.tsx`, `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: `filterChips` (Task 1), `reviewSummary`, `RowFilters`, `NO_FILTERS`, `filtersSet`.
- Produces: `FilterBar({ filters, onFilters, review, only, onOnly, flagged, accounts, types, shown, total }: {
  filters: RowFilters; onFilters: (f: RowFilters) => void; review: ReviewItem[]; only: string | null;
  onOnly: (code: string | null) => void; flagged: number; accounts: [string, string][]; types: string[];
  shown: number; total: number })`

- [ ] **Step 1:** One line: the search input (grows), a "Filters" button (`Filters · N` when N are set, not counting
  text) toggling a panel below it with today's account, type, in/out, state, from/to, £ from/to controls in a grid,
  and a "Needs review" `<select>`: "All rows", "Needs review · {flagged} rows" (value `review`), then each
  `reviewSummary` item "{title} · {rows}" (errors first, as it sorts). Below the line, when anything is set: the
  chips from `filterChips`, each with a × button clearing its field(s), then "{shown} of {total} shown" and Clear.
- [ ] **Step 2:** TransactionsTable uses it in place of `.filter-bar` and `.review-bar`; the "side by side" bar for
  Show both stays. Remove the `.review-bar` chips' CSS no longer used.
- [ ] **Step 3:** `tsc` → clean; rsync; on 3030 the bar is one line at 1440px and wraps sensibly at 375px; every
  filter and the picker narrow the table as before.

### Task 6: The compact table and the row panel

**Files:**
- Create: `frontend/src/components/RowPanel.tsx`
- Modify: `frontend/src/components/TransactionsTable.tsx`, `frontend/src/components/TransactionsSection.tsx`,
  `frontend/src/components/DocumentPanel.tsx` (export `OneDocument`), `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: `tableDate`, `signedAmount`, `rowHeadline`, `capActions` (Task 1); `OneDocument`.
- Produces: `RowPanel({ row, issues, documentIssue, readOnly, ... })` holding every control the row's `<td>`s hold
  today (move them, don't rewrite them: `AgentBadge`, `originalText`, the without-receipt form, `rowStatus`/
  `apartStatus` with Include and actions, `IssueList` with the same props, Reclaim it, Put back, Edit, Add line,
  Revert, Remove), plus the figures (in/out, amount, VAT with `VAT_SHORT`, net, account) and the document.

- [ ] **Step 1:** The table's columns become Date (`tableDate`, `.mono`, `white-space: nowrap`), Description (the
  description cut to one line with its full text in `title`, and a `.row-sub` line from `rowHeadline` in its
  severity's colour), Amount (`signedAmount`, `.amount-in` in `--ok`), Account (`accountName`, one line), Check
  (`checkOf`). A flagged row keeps `row-flag-error`/`row-flag-warn`, drawn as a 3px left edge on the first cell.
  The document-problems block above the table goes; `documentProblems` feeds `rowHeadline`'s third argument for
  each of a document's lines (and stays in the Needs review counts as today). Totals at the foot: one cell spanning
  the row, "{label} ({count}) · {gross} · VAT {vat} · net {net}{ · still owed}".
- [ ] **Step 2:** `selected: number | null` state; clicking a row (not a control in it) selects it and opens
  `RowPanel` beside the table (`.ledger-with-panel`, a grid `minmax(0,1fr) 380px`; panel `position: sticky; top: 12px;
  max-height: calc(100vh - 24px); overflow: auto`; below 1000px the panel is `position: fixed; inset: 0 0 0 auto;
  width: min(100%, 420px)` over the table). The selected row gets `aria-selected` and `--hover`. Esc closes; ↑/↓
  select the previous/next listed row when `document.activeElement` is not an input, select or textarea, and scroll
  it into view.
- [ ] **Step 3:** In the panel, a status with more than three actions shows `capActions(...).shown` as buttons and
  the rest as a `<select>` "Link to another…" whose choice runs that action's change.
- [ ] **Step 4:** `?row=` and Show both: `show` still narrows the table (as now) and also selects `show[0]`; when
  the wanted row is beyond `limit`, raise `limit` to include it (Review Focus 3).
- [ ] **Step 5:** `tsc` → clean; `npm test` → pass; rsync; on 3030: rows are one line high (two with a sub-line),
  the payout row's panel shows three links and a picker, Tallgrass's panel offers "Enter it in pounds", a left-out
  row's panel offers Put back and no fixes, a closed year shows no changing control, AI review's "Show" lands on the
  row with its panel open.

### Task 7: AI review as the queue

**Files:**
- Modify: `frontend/src/components/AiReviewSection.tsx`, `frontend/src/components/TodoList.tsx`,
  `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: `useTodo` (Task 3); `queueGroups`, `checkKinds`, `cardKind`, `groupOf`, `GROUP_LABELS`, `doneSince`
  (Task 2).

- [ ] **Step 1:** Head: "{need} to do", " · {waiting} waiting on you" when any, " · {done} done since you opened this
  page" when > 0 (`first` = `need` at the first load, kept in a ref), a 4px bar of `done / (done + need)` in `--ok`,
  Apply all suggestions on the right. The materiality line under it, muted.
- [ ] **Step 2:** Tabs: All · {need}, then each group from `queueGroups` with its count (`.queue-tab`, `aria-pressed`).
  A "Kind" `<select>`: "Any kind", then each `cardKind` with its count; it narrows every group.
- [ ] **Step 3:** With All or a group chosen, each group is a heading with its `GROUP_LABELS` note, then its cards —
  except `check`, which lists `checkKinds` as one line each ("{kind} · {n} rows", button). Opening a kind shows one
  card at a time with "{i} of {n}", Previous and Next; when the shown card leaves the list the same index shows the
  next one (clamped); Back to the kinds closes it.
- [ ] **Step 4:** `TodoList` cards: the class `todo-{group}` gives a 3px left edge (`--error`, `--accent`, `--ok`,
  `--warn`, `--rule`) on a white card with no tint; "Show" reads "Show row". The waiting badge stays.
- [ ] **Step 5:** `tsc` → clean; `npm test` → pass; rsync; on 3030: the counts on the tabs add up to the head, the
  "Another account?" kind steps 1 of 30 → 2 of 30, answering a question moves "done" up, the documents panel and
  Undo history still work.

### Task 8: Whole check

- [ ] **Step 1:** `cd frontend && npm test && npx tsc --noEmit` → pass, no errors.
- [ ] **Step 2:** In the browser on 3030 (agency copy): Overview, AI review, Transactions, Documents, Bank, Invoices,
  Trial balance at 1440px, at 375px, and in dark; no console errors; the to-do number is the same on Overview and AI
  review; every Review Focus line checked.
- [ ] **Step 3:** Screenshot the three pages for the user; ask before committing (stage only `frontend/` files, the
  spec and this plan).
