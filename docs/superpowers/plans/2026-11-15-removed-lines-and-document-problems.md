# Removed Lines and Document Problems Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A line a person removes is set aside (and can be put back) instead of deleted, a problem with a whole document is shown against the document, and any total that doesn't add up can be left as it is.

**Architecture:** Three new inputs on the row (`removed`, `total_accepted`) and two new fields on an issue (`about`, `difference`), all worked through the existing paths: `ledger.remove_row` / `change_row` write them, `matching._checked_totals` reads them, and the pages read them off the ledger they already load. A removed row is also `excluded`, so every existing "left out of the books" path treats it correctly without change.

**Tech Stack:** Python 3 (FastAPI, pydantic, pytest, MongoDB store), Next.js/React/TypeScript (tests: `node --test` on `frontend/src/lib/*.test.ts`).

**Spec:** `docs/superpowers/specs/2026-11-15-removed-lines-and-document-problems-design.md`

## Global Constraints

- No commits: the branch holds unrelated uncommitted work. The person commits.
- Do not touch `ledgersync/agent/` (its `FAMILIES`, prompts and tools) or `eval/`.
- The AI never changes a removed row.
- A removed row is in no total, trial balance, VAT figure or "to review" count (it is `excluded`, which already guarantees this).
- Copy, exactly: "Removed by you", "Put back", "Leave it as it is", "Undo", "Document totals", "Show its lines".
- `frontend/AGENTS.md`: this Next.js differs from the usual; read `node_modules/next/dist/docs/` before using a Next API not already used in the file being edited.
- Comments and docstrings follow the files' style: what the thing is, in plain words.

## Review Focus

1. A removed bank statement line must not raise a new statement warning (`statement_gap`) on its neighbours beyond what an AI-excluded line raises today. (Task 1 test.)
2. Put back on a closed year or an archived client is refused like any edit. (Task 1 test.)
3. An accepted difference that no longer matches (a line put back, an amount edited) is ignored silently: the problem comes back, or nothing shows if the document now adds up. (Task 3 tests.)
4. Rows saved before this change have no `removed`, `total_accepted`, `about` or `difference`: all read as their defaults. (Covered by pydantic defaults; Task 4 test for the page's helpers with the fields absent.)
5. A document problem whose first line is hidden by the table's filters is still listed in the strip. (Task 4 test: `documentProblems` takes all the year's rows, not the filtered ones.)

---

### Task 1: Remove sets a read row aside; Put back

**Files:**
- Modify: `ledgersync/models.py` (`Transaction`, `RowPatch`), `ledgersync/rows.py` (`INPUTS`), `ledgersync/ledger.py` (`remove_row`, `change_row`, `_check_edit`, `add_manual`), `ledgersync/resolutions.py` (`_usable`), `ledgersync/export.py` (`_left_out`), `server.py` (`change_row`'s kind)
- Test: `tests/test_clients_api.py`, `tests/test_resolutions.py`, `tests/test_export.py`

**Interfaces:**
- Produces: `Transaction.removed: bool = False` (a person removed it; always with `excluded=True`). `RowPatch.removed: Optional[bool] = None`, of which only `False` is accepted (Put back). `DELETE /api/clients/{id}/rows/{row_id}` returns the ledger with the row still listed (`excluded` and `removed` true) unless its upload's kind is `"manual"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_clients_api.py`, using the `api` fixture's store to add a read upload (`store.add_upload(cid, "claim.pdf", "pdf", [...])`, as `tests/helpers.py:56` does):

  - `test_removing_a_read_line_sets_it_aside_and_its_claim_still_adds_up`: a claim of two lines (£36.00, £54.00, `document_total` £90.00, kind `"pdf"`). `DELETE` the £54.00 line. The ledger still lists two rows; the removed one has `excluded is True and removed is True`; no row has a `total_mismatch` issue.
  - `test_put_back_books_a_removed_line_again`: after the above, `PATCH {"removed": false}` gives `excluded is False and removed is False`, and no `total_mismatch`.
  - `test_a_row_added_by_hand_is_still_deleted`: a `manual()` row, `DELETE`, the ledger no longer lists it.
  - `test_put_back_is_refused_on_a_row_that_was_not_removed` (400) and `test_removed_true_is_refused` (`PATCH {"removed": true}` → 400, "Use Remove to take a row out of the books.").
  - `test_put_back_is_refused_for_an_archived_client` (the same status an edit gets).
  - `test_a_removed_statement_line_raises_nothing_new`: three statement lines with balances; remove the middle one; the issue codes on the other two equal those raised when the middle one is `excluded` by hand in the store.

  In `tests/test_resolutions.py`: `test_a_decision_on_a_removed_row_is_refused`: a row with `excluded=True, removed=True`; the cheapest existing action in that file that names a row (use the one its neighbouring "already out of the books" test uses) is refused with "Row N was removed by a person."

  In `tests/test_export.py`: `test_a_removed_row_says_so`: `_left_out` of a `removed` row is `"Removed by a person"`.

- [ ] **Step 2: Run them, expect failures**

  Run: `pytest tests/test_clients_api.py tests/test_resolutions.py tests/test_export.py -q`
  Expected: the new tests FAIL (unknown field / row deleted).

- [ ] **Step 3: Implement**

  - `Transaction.removed: bool = False`, beside `excluded`, commented as an input a person's Remove sets and Put back clears. Add `"removed"` to `rows.INPUTS`.
  - `ledger.remove_row`: after `ensure_open`, look up the row's upload kind in `store.uploads(client_id)`; `"manual"` → `store.delete_row` as now; anything else → `store.patch_row(client_id, row_id, {"excluded": True, "removed": True})`.
  - `RowPatch.removed`; in `_check_edit`: sent with `True` → `InvalidInput("Use Remove to take a row out of the books.")`; sent with `False` on a row whose `tx.removed` is false → `InvalidInput("This row was not removed.")`. In `change_row`, when `"removed"` is sent the values written are `{"excluded": False, "removed": False}` plus anything else sent.
  - `add_manual`'s `fresh` reset also sets `removed=False`.
  - `resolutions._usable`: before its other checks, `if row.removed: raise _Refused(f"Row {row.id} was removed by a person.")`.
  - `export._left_out`: `"Removed by a person"` when `tx.removed`, checked before `excluded`.
  - `server.change_row`: kind is `"row_included"` when `"removed"` is sent.

- [ ] **Step 4: Run the three files, then the whole suite**

  Run: `pytest -q`
  Expected: all pass (live tests skip as they do today).

### Task 2: An issue says what it is about, and by how much

**Files:**
- Modify: `ledgersync/models.py` (`Issue`), `ledgersync/checks.py` (`issue`), `ledgersync/matching.py` (`_checked_totals`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Produces: `Issue.about: Literal["row", "document"] = "row"`; `Issue.difference: Optional[Decimal] = None` (on `total_mismatch`: the printed total less the lines and what is set aside; positive is short, negative is over). `checks.issue(code, message, severity="warning", related=(), *, about="row", difference=None)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_matching.py`, beside `test_a_document_that_does_not_add_up_says_once_what_is_missing`:

  - Extend that test: `first.issues[0].about == "document"` and `first.issues[0].difference == Decimal("54.00")`.
  - `test_a_total_problem_a_row_explains_stays_about_the_row`: the "Repeats another line" case (lines 36.00, 54.00, 54.00 against 90.00): the issue on the third line has `about == "row"` and `difference == Decimal("-54.00")`.
  - `test_an_agents_statement_that_does_not_net_is_about_the_document`: using the file's existing agent-statement helper, `about == "document"`, `difference == printed - net`.

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_matching.py -q -k "add_up or explains or agents_statement"`

- [ ] **Step 3: Implement.** In `_checked_totals`, `about="document"` exactly when the issue lands on `doc.rows[0]` by fall-back (none of `changed`, read-twice, or single `same` chose the row) and for the agent's statement; `difference` is `gap` (for the agent's statement, `printed - net`).

- [ ] **Step 4: Run** `pytest tests/test_matching.py tests/test_adapter.py tests/test_books.py -q` — all pass.

### Task 3: Leave it as it is

**Files:**
- Modify: `ledgersync/models.py` (`Transaction`, `RowPatch`), `ledgersync/rows.py` (`INPUTS`, `WHOLE_DOCUMENT`), `ledgersync/checks.py` (`MATCHING_ISSUES`), `ledgersync/ledger.py` (`_check_edit`), `ledgersync/matching.py` (`_checked_totals`)
- Test: `tests/test_matching.py`, `tests/test_clients_api.py`

**Interfaces:**
- Consumes: `Issue.difference` (Task 2).
- Produces: `Transaction.total_accepted: Optional[Decimal] = None` (the difference a person said to leave, kept on every row of the document). `RowPatch.total_accepted: Optional[Decimal] = None` (a number accepts; `null` is Undo). A new info issue code `total_accepted`, on the document's first kept row, with message `"{Lines|Rows} total £X, £G {under|over} the {kind}'s £Y."`.

- [ ] **Step 1: Write the failing tests**

  `tests/test_matching.py`:
  - `test_a_difference_a_person_left_raises_a_note_not_a_warning`: lines 36.00 and 30.90 against 120.90, both with `total_accepted="54.00"` → `codes(first) == [("total_accepted", "info")]`, message `"Lines total £66.90, £54.00 under the claim's £120.90."`, `codes(second) == []`.
  - `test_an_accepted_difference_that_changed_is_asked_about_again`: same with `total_accepted="10.00"` → `codes(first) == [("total_mismatch", "warning")]`.
  - `test_an_accepted_difference_is_forgotten_once_the_document_adds_up`: lines 36.00 and 54.00 against 90.00 with `total_accepted="54.00"` → no issues on either.

  `tests/test_clients_api.py`:
  - `test_leave_it_as_it_is_clears_a_total_and_undo_brings_it_back`: the manual claim of `test_a_line_added_by_hand_...` (36.00 against 90.00) plus a second manual line of the same `document_ref` (10.00). `PATCH {"total_accepted": "44.00"}` on the second line: neither row has `total_mismatch`; the first has `total_accepted`. `PATCH {"total_accepted": null}`: `total_mismatch` is back.
  - `test_a_zero_difference_is_refused`: `PATCH {"total_accepted": "0.00"}` → 400.

- [ ] **Step 2: Run, expect FAIL** — `pytest tests/test_matching.py tests/test_clients_api.py -q -k "accepted or leave or zero_difference"`

- [ ] **Step 3: Implement**

  - `Transaction.total_accepted`; add to `rows.INPUTS` and `rows.WHOLE_DOCUMENT` (so `store._patched` writes it to every row of the document, a claim's lines included). Add `"total_accepted"` to `checks.MATCHING_ISSUES`.
  - `RowPatch.total_accepted`; `_check_edit`: sent, not `None`, and `== 0` or `abs(...) >= MOST` → `InvalidInput("There is no difference to leave.")`.
  - `_checked_totals`: once `gap` (or the agent's statement's `printed - net`) is known, read `accepted` as the first non-`None` `total_accepted` among `doc.rows`; when `accepted == gap`, add `issue("total_accepted", message, "info")` to `doc.rows[0]` and continue, before any row is chosen for the warning.

- [ ] **Step 4: Run** `pytest -q` — all pass.

### Task 4: The page's rules (`frontend/src/lib`)

**Files:**
- Modify: `frontend/src/lib/api.ts` (`Issue`, `Transaction`), `frontend/src/lib/clients.ts` (`RowChange`), `frontend/src/lib/ledger.ts`, `frontend/src/lib/problems.ts`
- Test: `frontend/src/lib/ledger.test.ts`, `frontend/src/lib/problems.test.ts`

**Interfaces:**
- Produces, in `ledger.ts`:
  - `rowIssues(tx: Transaction): Issue[]` — its issues that are not about its document.
  - `interface DocumentProblem { row: Transaction & { id: number }; issue: Issue; lines: number[] }` and `documentProblems(rows: SavedRow[]): DocumentProblem[]` — one per warning or error with `about === 'document'` on a row in the books; `lines` are the ids of every row in the books with that row's `document_ref`.
  - `leftOutLabel(tx: Transaction): 'Replaced' | 'Removed by you' | 'Left out'`.
  - `removedForGood(row: SavedRow, uploads: Upload[]): boolean` — its upload's kind is `'manual'`.
  - `issueFixes` additions: `total_mismatch` with a `difference` → `[{ label: 'Leave it as it is', change: { total_accepted: issue.difference } }]`; `total_accepted` (checked before the `info` return) → `[{ label: 'Undo', change: { total_accepted: null } }]`.
  - `ISSUE_TITLES.total_accepted = 'Total left as it is'`.
- Produces, in `problems.ts`: family `'totals'` titled `'Document totals'`, listed after `'duplicate'`; `Problem` gains `document: boolean` and `leave: string | null` (the difference to accept, for a `total_mismatch` that has one); `groupProblems(rows, suggestions, fileOf?: (row: SavedRow) => string)` — a problem about a document is in `'totals'` and its `what` is `fileOf(row)` when given.
- `api.ts`: `Issue.about?: 'row' | 'document'`, `Issue.difference?: string | null`; `Transaction.removed?: boolean`, `Transaction.total_accepted?: string | null`. `clients.ts` `RowChange`: `removed?: false`, `total_accepted?: string | null`.

- [ ] **Step 1: Write the failing tests** (in each file's existing style and row builders):

  `ledger.test.ts`:
  - `rowIssues` drops an issue with `about: 'document'`, keeps one with `about: 'row'` and one with no `about`.
  - `documentProblems`: two lines of one `document_ref`, the first carrying a document `total_mismatch`, plus an unrelated row → one problem, `lines` the two ids; a third line of that document that is `excluded` is not in `lines`; an `info` issue about a document gives none.
  - `leftOutLabel`: `{ superseded_by: 'd1' }` → `'Replaced'`; `{ excluded: true, removed: true }` → `'Removed by you'`; `{ excluded: true }` → `'Left out'`.
  - `issueFixes`: `total_mismatch` with `difference: '457.20'` → the Leave fix with `total_accepted: '457.20'`; without `difference` → `[]`; `total_accepted` → the Undo fix.
  - `needsReview(row, rowIssues(row))` is false for a row whose only issue is about its document.

  `problems.test.ts`:
  - A document `total_mismatch` is grouped under `'Document totals'`, `what` is the `fileOf` text, `document === true`, `leave === '457.20'`.
  - A `total_mismatch` with `about: 'row'` stays under `'Recorded twice'`, `document === false`.

- [ ] **Step 2: Run, expect FAIL** — `cd frontend && npm test`

- [ ] **Step 3: Implement** the helpers above. `groupProblems` decides the family as `issue.about === 'document' ? 'totals' : familyOf(issue.code)`.

- [ ] **Step 4: Run** `cd frontend && npm test` — all pass.

### Task 5: The pages

**Files:**
- Modify: `frontend/src/components/TransactionsTable.tsx`, `frontend/src/components/TransactionsSection.tsx`, `frontend/src/components/ProblemsList.tsx`, `frontend/src/components/AiReviewSection.tsx`, `frontend/src/app/globals.css` (only if no existing notice/issue class fits the strip)

**Interfaces:**
- Consumes: everything Task 4 produces; `changeRow(clientId, rowId, change)` from `@/lib/clients`.

- [ ] **Step 1: `TransactionsTable.tsx`**
  - `issuesOf` is `rows.map(rowIssues)`, so a document's problem no longer marks, flags or lists under its first line.
  - `const docs = documentProblems(rows)`. `flagged` adds `docs.length`. The chips' `reviewSummary` is fed the rows' issues plus each document problem's issue (one entry per document), so "Total doesn't add up 1" is still offered.
  - A chip's filter, and "Only these", also keep every row whose id is in the `lines` of a document problem with that code (any code, for "Only these").
  - A strip between the review bar and the table, shown whenever `docs.length`, not narrowed by the filters: per document, a line `{file name} · {DOCUMENT_TYPES[type]}`, then `IssueList` for its one issue with `onShowBoth={() => setFocus(lines)}`, `fixesOf`/`onFix` on its row (which gives Leave it as it is), `askHref`, and an **Add line** button (`onAdd(row)`) when not read-only.
  - The left-out status line uses `leftOutLabel(row)`; when `row.removed` and not read-only it is followed by a **Put back** link: `onChange(row.id, { removed: false })`. A removed row shows no Remove link.
- [ ] **Step 2: `TransactionsSection.tsx`** — the confirm reads, for a row not `removedForGood`: `Remove "…" (£x)? It is taken out of the books and stays listed, crossed out, so you can put it back.`; for one that is, the text it has today.
- [ ] **Step 3: `ProblemsList.tsx` and `AiReviewSection.tsx`** — `groupProblems` is given `fileOf` (`"{upload name}, {document kind in lower case}"`). A document problem's link reads "Show its lines". A problem with `leave` shows a **Leave it as it is** button (disabled like Apply), which `AiReviewSection` handles with `changeRow(client.id, p.rowId, { total_accepted: p.leave })` then `reload()`, reporting a failure in the section's `error`.
- [ ] **Step 4: Check** — `cd frontend && npm test && npx tsc --noEmit && npm run lint` (use the lint script only if `package.json` has one): no errors.

### Task 6: Verify in the app

- [ ] **Step 1:** `pytest -q` and `cd frontend && npm test` — all pass.
- [ ] **Step 2:** With the API and the page running, on Mark's year (`/clients/2/2026-09-02/transactions`): the claim's problem is in the strip, not on the Booking.com line; **Leave it as it is** clears it and leaves the note with Undo; Undo brings it back. Remove a read line and see it crossed out with "Removed by you · Put back" and no new warning; Put back restores it. On AI review, the problem is under "Document totals", titled by the file. Leave Mark's data as it was found unless the person says otherwise (Undo and Put back after checking).
