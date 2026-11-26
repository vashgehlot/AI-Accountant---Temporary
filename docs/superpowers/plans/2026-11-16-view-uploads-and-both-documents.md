# View uploads, both documents on a two-row card, photos read larger: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person look at any upload from the Documents page, see every document a two-row AI review card is about, and have receipt photos read at a size where a printed VAT number is read.

**Architecture:** `DocumentPanel` takes a list of documents instead of one. A pure helper in `lib/suggestions.ts` works out which documents a card is about; the AI review page and the Documents page both feed the panel. The reader's image preparation sends photos at 2000 pixels on the long side instead of 1200.

**Tech Stack:** Next.js / React (TypeScript, `node --test` for `src/lib`), FastAPI + Python (pytest, `.venv/bin/python`).

**Spec:** `docs/superpowers/specs/2026-11-16-view-uploads-and-both-documents-design.md`

## Global Constraints

- The document rules (`ledgersync/evidence_rules.py`) are not changed.
- Photos and scanned pages: at most 2000 pixels on the long side (was 1200).
- A hand-typed upload (`kind === 'manual'`) has nothing to view; every other upload can be viewed (the panel already shows the read lines when the file wasn't kept or can't be shown).
- No commits: the user commits. The working tree already holds uncommitted reader changes (`ledgersync/extractor.py`, `tests/test_extractor.py`, `tests/test_live_llm.py`) from other work; leave them as they are.
- Python: targeted test files only, with `.venv/bin/python -m pytest`; the whole suite takes about 55 minutes.

## Review Focus

- A card whose other row is hand-typed or no longer in the year: only the documents that exist are shown; with none, no View button.
- Two rows of one card from the same upload (booked twice on one statement, a document's total): that document once, not twice.
- Removing, on the Documents page, the upload being viewed: the panel closes, nothing breaks.
- A closed year or an archived client: View is still offered on the Documents page (it changes nothing).
- A photo already smaller than 2000 pixels: sent at its own size, never enlarged.

---

### Task 1: The documents a card is about, all shown in the panel

**Files:**
- Modify: `frontend/src/lib/suggestions.ts` (beside `documentOf`)
- Modify: `frontend/src/components/DocumentPanel.tsx`
- Modify: `frontend/src/components/AiReviewSection.tsx:113-116, 234-241`
- Modify: `frontend/src/components/TodoList.tsx:59-63`
- Test: `frontend/src/lib/suggestions.test.ts`

**Interfaces:**
- Produces, in `lib/suggestions.ts`:
  - `viewable(upload: Upload): boolean` — `upload.kind !== 'manual'`; `documentOf` uses it.
  - `cardDocuments(card: { row: { id: number; upload_id: number } | null; issues: { related?: number[] }[]; suggestions: { row_ids: number[] }[]; questions: { row_ids: number[] }[] }, rows: { id: number; upload_id: number }[], uploads: Upload[]): { upload: Upload; rowId: number }[]` — the card's own row first, then every row id named by its issues' `related`, its suggestions' `row_ids` and its questions' `row_ids`, in that order; each row looked up in `rows` (skipped when absent), its upload via `documentOf` (skipped when null); each upload once, with the first row that named it.
- Produces, in `DocumentPanel.tsx`: `export interface PanelDocument { upload: Upload; rows: SavedRow[]; rowId: number | null; quotes: string[] }` and props `{ documents: PanelDocument[]; onClose: () => void }`. `rowId` null marks no row.

- [ ] **Step 1: Write the failing tests** in `suggestions.test.ts` (reuse its `upload` helper; `card` builds `{ row, issues, suggestions: [], questions: [] }`):

```ts
test('a card about two rows from two files shows both, its own first', () => {
  const uploads = [upload(1, 'pdf', 'a.pdf'), upload(2, 'image', 'b.jpg')]
  const rows = [{ id: 10, upload_id: 2 }, { id: 11, upload_id: 1 }]
  const docs = cardDocuments(card(rows[0], [{ related: [11] }]), rows, uploads)
  assert.deepEqual(docs.map(d => [d.upload.id, d.rowId]), [[2, 10], [1, 11]])
})

test('rows from one file show it once', () => {
  const uploads = [upload(1, 'pdf')]
  const rows = [{ id: 10, upload_id: 1 }, { id: 11, upload_id: 1 }]
  assert.deepEqual(cardDocuments(card(rows[0], [{ related: [11] }]), rows, uploads).map(d => d.upload.id), [1])
})

test("a typed-in row and a row that's gone add nothing; a suggestion's or a question's rows add theirs", () => {
  const uploads = [upload(1, 'manual', 'Manual entry'), upload(2, 'pdf'), upload(3, 'pdf')]
  const rows = [{ id: 10, upload_id: 1 }, { id: 11, upload_id: 2 }, { id: 12, upload_id: 3 }]
  const c = { row: rows[0], issues: [{ related: [99] }], suggestions: [{ row_ids: [11] }], questions: [{ row_ids: [12] }] }
  assert.deepEqual(cardDocuments(c, rows, uploads).map(d => d.upload.id), [2, 3])
  assert.deepEqual(cardDocuments(card(rows[0], []), rows, uploads), [])
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npm test`
Expected: FAIL, `cardDocuments` is not exported.

- [ ] **Step 3: Implement `viewable` and `cardDocuments`** in `lib/suggestions.ts` per the Interfaces block.

- [ ] **Step 4: Run them to see them pass**

Run: `cd frontend && npm test`
Expected: all pass (187 before, 190 after).

- [ ] **Step 5: `DocumentPanel` shows every document it is given.** One head with Close (and the Escape key, as now); then, for each document, a block with its name, Download (when kept), its quotes, and the file or its lines exactly as the panel shows one today, marking `rowId` when it is not null. `aria-label`: `Document: <name>` for one, `Documents: <name>, <name>` for several.

- [ ] **Step 6: The AI review page feeds it.** In `AiReviewSection.tsx`, replace `viewedUpload` with `viewedDocuments = viewed ? cardDocuments(viewed, ledger.transactions, ledger.uploads).map(...)` building each `PanelDocument` (its upload's rows, its `rowId`, and the quotes of `viewed.suggestions` evidence whose `upload_id` is that upload's). The panel is open when `viewedDocuments.length > 0`.

- [ ] **Step 7: The button says how many.** In `TodoList.tsx`, show the button when `cardDocuments(card, rows, ledger.uploads).length > 0`; label `View document` for one, `View both documents` for two, `View <n> documents` for more.

- [ ] **Step 8: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no output.

---

### Task 2: View on the Documents page

**Files:**
- Modify: `frontend/src/components/UploadsList.tsx`
- Modify: `frontend/src/components/DocumentsSection.tsx`

**Interfaces:**
- Consumes: `viewable(upload)` and `PanelDocument` / `DocumentPanel` from Task 1.
- Produces: `UploadsList` props gain `viewing: number | null` (the upload open beside the list) and `onView: (upload: Upload) => void`.

- [ ] **Step 1: `UploadsList` offers View.** A `View` link-button before Remove on every upload where `viewable(upload)`, shown in read-only years too, with `aria-pressed={viewing === upload.id}`; the viewed upload's `<li>` gets the existing highlight (`aria-current="true"` styled like `.todo-viewing`, or that class).

- [ ] **Step 2: `DocumentsSection` opens the panel beside the list.** State `viewing: number | null`, toggled by `onView`. The panel's document is `ledger.uploads.find(u => u.id === viewing && !removing.has(u.id))`, with `rows: ledger.transactions.filter(r => r.upload_id === viewing)`, `rowId: null`, `quotes: []`; when it isn't found the panel isn't shown. Wrap `UploadsList` and the panel in the AI review page's layout classes (`todo-with-panel`, plus `todo-panel-open` while open), so it sits beside the list on a wide screen and over it on a narrow one.

- [ ] **Step 3: Type-check and test**

Run: `cd frontend && npx tsc --noEmit && npm test`
Expected: no type errors; 190 pass.

---

### Task 3: Photos read at 2000 pixels

**Files:**
- Modify: `ledgersync/pipeline.py:31` (`prepare_image`)
- Test: `tests/test_pipeline.py:102-105`
- Test: `tests/test_live_llm.py` (new live test beside the Victoria Food one)
- Copy: the receipt photo to `eval/private/jenny/Southgate_Bath_Car_Park-2026-10-08_20_30_00.jpg` (git-ignored; check `git check-ignore` before copying), from client 3's upload 128: `curl -s -o <path> localhost:3000/api/clients/3/uploads/128/file`

**Interfaces:**
- Produces: `prepare_image(data: bytes, max_side: int = 2000) -> str` — unchanged otherwise.

- [ ] **Step 1: Change the tests first.** In `test_pipeline.py`, the sideways photo is now sent with `max(sent.size) == 2000` (rename the test's "small" to "at most 2000 pixels"), and add:

```python
def test_a_photo_smaller_than_the_limit_is_not_enlarged():
    sent = Image.open(io.BytesIO(base64.b64decode(prepare_image(photo((800, 600))))))
    assert sent.size == (800, 600)
```

In `test_live_llm.py`:

```python
def test_a_receipt_photos_small_vat_number_is_read():
    # Southgate car park prints "V.A.T No. 870 487 106" in small type at the foot of a long receipt: at 1200 pixels it
    # was missed in 8 reads of 8, so its VAT was left in the cost; at 2000 it was read in 3 of 3 (2026-11-16).
    path = PRIVATE / "jenny" / "Southgate_Bath_Car_Park-2026-10-08_20_30_00.jpg"
    # skip when missing, as the Victoria Food test does; read 4 times side by side; each read is one row with
    # amount 72.0, vat 12.0, and supplier_vat_number whose digits are "870487106"
```

- [ ] **Step 2: Run the pipeline tests to see the first fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q`
Expected: the sideways-photo test fails (1200 != 2000); the new one passes.

- [ ] **Step 3: Set `max_side` to 2000** and update the module docstring's "downscaled" wording if it names a size.

- [ ] **Step 4: Run the tests to see them pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -q && .venv/bin/python -m pytest tests/test_live_llm.py -q -m llm -k "vat_number or victoria or receipt_photo"`
Expected: all pass (the live ones need the API key in `.env`).

---

### Task 4: Check it in the app

- [ ] **Step 1:** In the preview app, on client 3's Documents page: View a PDF and a photo, View again closes it, Remove the one being viewed and the panel goes.
- [ ] **Step 2:** On an AI review card about two rows from two files (seed one if none exists), View both documents shows both, each with its name.
- [ ] **Step 3:** Screenshot both for the user.
