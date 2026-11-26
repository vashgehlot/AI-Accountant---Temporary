# AI review: change in view, document beside it, one fix for many rows: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the AI review page a suggestion shows what it changes, its document opens in a panel beside the list, and suggestions that make the same change can be applied together.

**Architecture:** One new rules file in `frontend/src/lib` (change lines, same-fix groups, which files can be shown), tested with `node --test`. One new panel component; `TodoList` and `AiReviewSection` use them. The file route learns to send a PDF or an image for showing when asked.

**Tech stack:** Next.js / React / TypeScript (`frontend/`), FastAPI (`server.py`), pytest, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-15-ai-review-evidence-and-grouped-fixes-design.md`

## Global constraints

- No edit under `frontend/src/components/chat/`, nor to `frontend/src/lib/chat.ts`, `chat.test.ts` or `api.ts` (another session's uncommitted work is in them). Use what `chat.ts` already exports (`changedFields`, `Decision`, `Evidence`).
- Styles go in the existing `/* AI review: the to-do list */` block at the end of `frontend/src/app/globals.css`.
- Only `application/pdf`, `image/png`, `image/jpeg`, `image/webp` and `image/gif` are ever sent for showing in the page. Not SVG, not HTML, not text.
- `readOnly = year.closed || client.archived`: Apply and Apply to all are disabled; View document still works.
- Checks: `cd frontend && npm test` and `npx tsc --noEmit`; Python with `.venv/bin/python -m pytest <file>` (never the whole suite per task).
- Commit only when the person asks; stage only the files a task names.

## Review focus

Each line is pinned by a test in the task named.

1. An SVG or an HTML file asked for with `show=1` is sent as a download (Task 1).
2. A suggestion with nothing in `before` and `after` has no change lines and breaks nothing (Task 2).
3. A file named `SCAN.PDF` or `photo.JPG` counts as showable (Task 2).
4. A row typed in by hand, or pasted as text, has no document to view (Task 2).
5. One suggestion of a kind makes no group; the same kind with different new values makes two groups, not one (Task 2).

---

### Task 1: The file route can send a file for showing

**Files:**
- Modify: `server.py` (`download_original`, about line 579)
- Test: `tests/test_clients_api.py` (beside `test_an_analysed_file_can_be_downloaded_again`)

**Interfaces:**
- Produces: `GET /api/clients/{id}/uploads/{upload_id}/file?show=1` answers with `Content-Disposition: inline; …` when the blob's content type (before any `;`, lower-cased) is one of the five in Global constraints; in every other case, and without `show`, `attachment`, as now. Every answer of the route carries `X-Content-Type-Options: nosniff`.

- [ ] **Step 1: Write the failing test.** Upload the CSV as `test_an_analysed_file_can_be_downloaded_again` does, with a `MemoryBlobStore` the test holds; then, for each case, put a blob and point the upload at it:

```python
def kept(blobs, mongo_store, cid, upload_id, data, name, content_type):
    sha = blobs.put(data, name=name, content_type=content_type)
    mongo_store.db.clients.update_one({"id": cid, "uploads.id": upload_id}, {"$set": {"uploads.$.sha256": sha}})

@pytest.mark.parametrize("name, content_type, shown", [
    ("r.pdf", "application/pdf", True), ("r.png", "image/png", True), ("r.jpg", "image/jpeg; charset=binary", True),
    ("r.svg", "image/svg+xml", False), ("r.html", "text/html", False), ("r.csv", "text/csv", False),
])
def test_only_a_pdf_or_an_image_is_sent_for_showing(mongo_store, name, content_type, shown):
    ...
    disposition = lambda q: api.get(f"/api/clients/{cid}/uploads/{upload_id}/file{q}").headers["content-disposition"]
    assert disposition("?show=1").startswith("inline" if shown else "attachment")
    assert disposition("").startswith("attachment")
    assert api.get(f"/api/clients/{cid}/uploads/{upload_id}/file?show=1").headers["x-content-type-options"] == "nosniff"
```

- [ ] **Step 2: Run, expect the `shown` cases to fail on `attachment`.** `.venv/bin/python -m pytest tests/test_clients_api.py -k "sent_for_showing or downloaded_again or no_file_to_download" -q`
- [ ] **Step 3: Implement:** add `show: bool = False` to `download_original`; a module constant `SHOWN_IN_PAGE` of the five types; the disposition word from it; the `nosniff` header.
- [ ] **Step 4: Run the same command, expect all passing.**

---

### Task 2: The rules

**Files:**
- Create: `frontend/src/lib/suggestions.ts`, `frontend/src/lib/suggestions.test.ts`

**Interfaces:**
- Consumes: `changedFields(d)` from `chat.ts` → `{ row: number; field: string; before: string; after: string }[]` (an empty value reads `—`).
- Produces:

```ts
// One line for each field a suggestion changes: "Date: none → 2 Sep 2026"; "Row 12 · Account: 7500 → 7400" when it
// changes more than one row. At most `most` lines; `more` is how many were left out.
export function changeLines(d: Decision, most = 4): { lines: string[]; more: number }

// Suggestions that make the same change: the same action and the same new values. Only groups of two or more.
export interface FixGroup { key: string; label: string; suggestions: Decision[]; rows: number }
export function sameFixGroups(suggestions: Decision[]): FixGroup[]

// Whether a browser can show the file in the page, by its name: .pdf, .png, .jpg, .jpeg, .webp, .gif.
export const canShow = (name: string): boolean
export const isPdf = (name: string): boolean
// The upload a row's document can be viewed from: not a row typed in by hand ('manual') or pasted ('text').
export function documentOf(row: { upload_id: number }, uploads: Upload[]): Upload | null
export const fileHref = (clientId: number, uploadId: number, show = false): string   // …/file or …/file?show=1
```

Rules the tests pin:
- `changeLines` writes `—` as `none`. Rows are named only when the suggestion's lines span more than one row.
- A group's `key` is the action and its new values: `${d.action}|` + the sorted, de-duplicated `${field}=${after}` of `changedFields(d)`. A suggestion with no changed fields joins no group. `label` is those `${field} → ${after}` joined with `, `, then ` on ${rows} rows`; `rows` counts distinct `row_ids` across the group. Groups keep the order of their first suggestion.
- `documentOf` finds the upload by id; null when there is none or its `kind` is `'manual'` or `'text'`. (Check the kind a pasted upload is saved with in `ledgersync` and use that word.)

- [ ] **Step 1: Write the failing tests** (the `suggestion` factory of `todo.test.ts`, with `before`/`after` given):

```ts
test('one changed field is one line, and nothing reads as none', …)
// after {'4': {date: '2026-09-02'}}, before {'4': {date: null}} → { lines: ['Date: none → 2 Sep 2026'], more: 0 }
test('a change to two rows names each row', …)           // ['Row 4 · Account: 7500 → 7400', 'Row 9 · Account: 7500 → 7400']
test('more than four lines are cut, and say how many more', …)   // 6 fields → lines.length 4, more 2
test('a suggestion that changes nothing has no lines', …)        // { lines: [], more: 0 }
test('two suggestions that move rows to the same account are one group', …)
// [{ key: 'change_account|Account=7400', label: 'Account → 7400 on 2 rows', rows: 2, suggestions: [D1, D2] }]
test('one suggestion of a kind makes no group', …)               // []
test('the same kind with different new values is two groups, each of two', …)
test('a suggestion that changes nothing joins no group', …)
test('canShow goes by the name, whatever its case', …)   // 'SCAN.PDF', 'photo.JPG', 'a.webp' true; 'claim.xlsx', 'x.svg', 'noext' false
test('a row typed in or pasted has no document; a row from a file has its upload', …)
test('fileHref asks for showing only when told', …)      // '/api/clients/1/uploads/3/file' and '…/file?show=1'
```

- [ ] **Step 2: Run, expect "Cannot find module ./suggestions.ts".** `cd frontend && npm test`
- [ ] **Step 3: Implement `suggestions.ts`.**
- [ ] **Step 4: Run, expect all passing;** `npx tsc --noEmit` clean.

---

### Task 3: The page

**Files:**
- Create: `frontend/src/components/DocumentPanel.tsx`
- Modify: `frontend/src/components/TodoList.tsx`, `frontend/src/components/AiReviewSection.tsx`, `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: Task 1's `?show=1`; Task 2's `changeLines`, `sameFixGroups`, `canShow`, `isPdf`, `documentOf`, `fileHref`.
- Produces: `DocumentPanel({ upload, rows, rowId, quotes, onClose })`; `TodoList` gains `onView: (card: TodoCard) => void` and `viewing: string | null` (the key of the card whose document is open).

`TodoList`:
- Under each suggestion's `DecisionLine`, its `changeLines` as `<p className="todo-change mono small">`, then `and N more` when `more > 0`.
- In a card's head, when `card.row` and `documentOf(card.row, ledger.uploads)`: a `View document` link-button calling `onView(card)`; the card gets `todo-viewing` while `viewing === card.key`.

`AiReviewSection`:
- `viewing: TodoCard | null` in state; it is cleared when its card leaves the list.
- The list and the panel sit in `<div className="todo-with-panel">`: the list, then `DocumentPanel` when viewing, given the upload, the year's rows of that upload, the card's row id, and the quotes of the card's suggestions whose `upload_id` is that upload.
- Above the list, under the heading: one `question-row` for each `sameFixGroups(waiting)`: the label, and `Apply to all ${n}` (`Applying…` while `working === group.key`). It runs the existing apply-one-after-another loop over that group's suggestions only: turn `applyAll` into `applyThese(list: Decision[], key: string)`, used by both buttons.

`DocumentPanel`:
- Head: the file's name, `Download` (`fileHref` without show, hidden when the upload has no `sha256`), `Close`.
- Each quote as `<blockquote className="evidence">`.
- When the upload has a `sha256` and `canShow(name)`: `<iframe title={name} src={fileHref(…, true)}>` for a PDF, `<img alt={name}>` otherwise. Else, when there is no `sha256`: `The original file wasn't kept.` In both of those other cases, the lines read from it: a table of date, description and amount, the card's row with `aria-current` and a tint.

Styles: `.todo-with-panel` (one column; two, `minmax(0, 1fr) minmax(320px, 44%)`, from 1100px when the panel is open); `.document-panel` (the card border, sticky to the top, its own scroll, `max-height: calc(100vh - 32px)`; below 1100px `position: fixed; inset: 0; z-index` above the page, the page's background); `.document-panel iframe` (full width, 70vh); `.document-panel img` (max-width 100%); `.todo-change`; `.todo-viewing` (the accent border).

- [ ] **Step 1:** Build `DocumentPanel.tsx`; change `TodoList.tsx` and `AiReviewSection.tsx`; add the styles.
- [ ] **Step 2:** `npx tsc --noEmit` clean; `npm test` passing.

---

### Task 4: See it work

**Files:** none (the preview app: `web-removed-lines-3016` and `api-removed-lines-8103`; sync `frontend/` to the preview copy and restart the API for Task 1).

- [ ] **Step 1:** Extend the scratchpad seed: a PDF and a PNG kept in the API's blob store with an upload pointing at each; two suggestions that change the account of two rows to the same account, and one that sets a date; a quote on one of them.
- [ ] **Step 2:** On the AI review page, by reading the page: each suggestion shows its change line; the group line says `… on 2 rows` and `Apply to all 2` leaves the date suggestion waiting; View document on the PDF's card shows the PDF in the panel with the quote above it, on the PNG's card the image, on the claim's (`.xlsx`) the lines read with the card's row marked; Close closes it. No console error. At 375px the panel covers the list and closes.
- [ ] **Step 3:** `npm test`, `npx tsc --noEmit`, `.venv/bin/python -m pytest tests/test_clients_api.py -q`.
