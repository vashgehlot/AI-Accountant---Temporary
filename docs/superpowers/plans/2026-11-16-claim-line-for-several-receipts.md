# One Claim Line for Several Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A claim line that names a supplier is booked from the one set of that supplier's receipts on one upload that adds up to it; the upload's charges the claim leaves out are not booked and ask.

**Architecture:** Matching learns each row's upload (`upload_ids`, threaded like `name_days`). A new pass in `_with_claims`, after the one-to-one passes and before the "differs" pass, counts the sets of an open claim line's candidate receipts that add up to it, and pairs only a set that is the one way. Two new matching outputs on `Transaction` (`recorded_by_refs`, `left_off_claim`) carry the result to `booked()`, the AI review tools and the table.

**Tech Stack:** Python 3.11, pydantic, pytest (`.venv/bin/python -m pytest`); Next.js/TypeScript, `node --test` (`cd frontend && npm test`).

**Spec:** `docs/superpowers/specs/2026-11-16-claim-line-for-several-receipts-design.md`

## Global Constraints

- Only an exact total, to the penny. Only receipts of one upload. At least two receipts in a set (one is today's pairing).
- Candidates are dated no later than `CARD_DAYS` (3 days) after the claim line and no earlier than `COVERED` (35 days) before it; undated receipts are never candidates.
- Skip an upload with more than 60 candidates for a line, as if no set fitted.
- Issue codes: `not_claimed` (warning), `claim_receipts_unclear` (warning). Both are matching issues (`checks.MATCHING_ISSUES`).
- Today's one-receipt pairing, Include, and Not the same (`apart`) behave exactly as before.
- Run Python tests by file, not the whole suite, while working (the whole suite takes about 55 minutes; run it once, in the background, in Task 6).

## Review Focus

1. A claim line whose set is on one upload while another upload has a set that also fits: nothing pairs, both warn. (Task 3 test `test_sets_on_two_uploads_pair_nothing`.)
2. A receipt already paired one-to-one with another claim line, or with a bank line, is never in a set. (Task 2 test `test_a_receipt_paired_on_its_own_is_never_in_a_set`.)
3. Rows excluded or split by a decision (`_without_left_out`) keep their upload ids in step with the kept rows. (Task 2 test `test_upload_ids_follow_rows_a_decision_left_out`.)
4. A leftover charge that a business bank line pays is booked as a receipt paid by that line, not left off. (Task 3 test `test_a_leftover_a_bank_line_pays_is_booked_from_the_bank`.)
5. A credit (money in) on the upload never cancels a charge out: only receipts the same way as the line are candidates. (Task 2 test `test_a_refund_on_the_statement_is_not_a_candidate`.)

---

### Task 1: TfL's initials name "Transport for London, Train"

**Files:**
- Modify: `ledgersync/matching.py` (`_initials`, `names_match`)
- Test: `tests/test_matching.py` (`test_names_that_match`, `test_names_that_do_not_match`)

**Interfaces:**
- Produces: `names_match(a, b)` is also True when a word of one name (three letters or more) is the initials of three or more consecutive words of the other, legal forms set aside.

- [ ] **Step 1: Add the failing cases**

To `test_names_that_match`: `("TfL Customer Services", "Transport for London, Train")`.
To `test_names_that_do_not_match`: `("CPS", "National Car Parks Ltd")` and `("NCP", "Car Parks National Ltd")` (initials out of order).

- [ ] **Step 2: Run and see the first fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -k "names_that" -q`
Expected: one FAIL, on the TfL case.

- [ ] **Step 3: Implement**

Replace the initials test in `names_match` with one against every run of three or more consecutive words of the other name (`_initials` gains a helper `_initial_runs(name) -> set[str]`, same word filter as `_initials`). The whole-name initials stay among the runs, so NCP still matches.

- [ ] **Step 4: Run the name tests and the whole matching file**

Run: `.venv/bin/python -m pytest tests/test_matching.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/matching.py tests/test_matching.py
git commit -m "fix: TfL's initials name a claim line for Transport for London"
```

---

### Task 2: A claim line booked from the one set of receipts that adds up to it

**Files:**
- Modify: `ledgersync/models.py` (`Transaction`: two fields after `documented_by`)
- Modify: `ledgersync/checks.py` (`booked`, `MATCHING_ISSUES`)
- Modify: `ledgersync/matching.py` (`match`, `match_documents`, `_without_left_out`, `_cleared`, `_with_claims`, new `_one_set`)
- Modify: `ledgersync/posting.py` (`matched_rows`)
- Modify: `ledgersync/books.py` (the three calls that pass `name_days`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `Transaction.recorded_by_refs: list[str] = Field(default_factory=list)`: on a claim line booked from a set, every receipt's `document_ref`, in date order.
  - `Transaction.left_off_claim: Optional[Settlement] = None`: on a receipt the claim leaves out, the claim line (`ref` the line's `document_ref`, `amount` its gross, `date`, `kind="expense_claim"`, `description` `_claim_name(line)`).
  - `booked(tx)`: a row with `left_off_claim` is booked only when `tx.include`, as with `recorded_by`.
  - `match(..., upload_ids: Optional[list[Optional[int]]] = None)`, `match_documents(..., upload_ids=...)`, `matched_rows(..., upload_ids=...)`: each row's upload id, or None. With None, the set pass does not run.
  - `_one_set(amounts: list[int], target: int) -> tuple[int, Optional[list[int]]]`: the number of sets (of two or more) of the amounts, in pence, that add up to target, counting up to 2, and the indices of the set when it is exactly 1.
  - The claim line's `recorded_by` for a set: `Settlement(ref=<first receipt's ref>, amount=<set total>, date=<latest receipt's date>, kind="receipt", description="<supplier>, <n> charges, <d1> to <d2>")`.

- [ ] **Step 1: Write the failing tests**

Add a helper and tests to `tests/test_matching.py`:

```python
TFL_DAYS = [("2026-10-27", "6.20"), ("2026-10-21", "8.90"), ("2026-10-20", "6.60"), ("2026-10-10", "6.00"),
            ("2026-10-08", "7.20"), ("2026-10-07", "10.00"), ("2026-10-06", "10.50"), ("2026-10-05", "6.10")]

def tfl_rows(claimed="55.40"):
    """Jenny's October claim line for TfL and the eight daily charges on her TfL Payment Statement (upload 199)."""
    line = claim_line(claimed, "2026-10-31", "Transport for London, Train", ref="claim")
    charges = [row("receipt", "out", gross, day, "TfL Customer Services", f"tfl-{day}", account="7400")
               for day, gross in TFL_DAYS]
    return [line, *charges], [176, *[199] * len(charges)]

def matched_from(rows, uploads, **kw):
    return match([normalise(t, SETTINGS) for t in rows], SETTINGS, upload_ids=uploads, **kw)
```

- `test_a_claim_line_is_booked_from_the_charges_that_add_up_to_it`: with `tfl_rows()`, the line is not booked, `line.recorded_by_refs` is the seven refs other than `tfl-2026-10-05` in date order, `line.recorded_by.amount == Decimal("55.40")`; each of the seven has `claimed_in.ref == "claim"`, `contra_account_code == "2110"`, `booked(...)` True.
- `test_a_charge_the_claim_leaves_out_is_not_booked_and_asks`: the 5 Oct row has `left_off_claim.ref == "claim"`, `booked(...)` False, `contra_account_code == "2110"`, `("not_claimed", "warning") in codes(row)`; with `include=True` on that row, `booked(...)` True.
- `test_the_whole_statement_claimed_pairs_every_charge`: `tfl_rows("61.50")`: eight refs, no `not_claimed` anywhere.
- `test_no_set_that_adds_up_changes_nothing`: `tfl_rows("55.41")`: line booked, `recorded_by is None`, every charge `claimed_in is None` and `left_off_claim is None`, no `not_claimed`.
- `test_a_line_for_another_supplier_takes_no_charges`: as `tfl_rows()` with the line's merchant `"Trainline"`: nothing pairs.
- `test_without_uploads_the_set_pass_does_not_run`: `matched(*tfl_rows()[0])` (no `upload_ids`): nothing pairs.
- `test_one_receipt_of_the_amount_pairs_as_today`: a claim line of £6.20 dated 27 Oct and the TfL rows: the line's `recorded_by.ref == "tfl-2026-10-27"`, `recorded_by_refs == []`, no `not_claimed`.
- `test_a_receipt_paired_on_its_own_is_never_in_a_set`: `tfl_rows()` plus a second claim line of £10.50 on 6 Oct ("Transport for London"): that line takes `tfl-2026-10-06` alone; the £55.40 line finds no set (55.40 needs 6 Oct) and stays booked.
- `test_a_charge_kept_apart_is_never_in_the_set`: `tfl_rows()` with `apart` saying the line and the 6 Oct row are not the same: nothing pairs.
- `test_a_line_ticked_include_is_booked_as_well_and_warns`: line `include=True`: booked, set paired, `"booked_twice"` in `codes(line)`.
- `test_a_refund_on_the_statement_is_not_a_candidate`: `tfl_rows("55.40")` plus an "in" receipt of £6.10 from TfL on 5 Oct on upload 199: the same result as the first test.
- `test_the_order_of_rows_makes_no_difference`: the rows reversed (and their uploads): the same refs paired and left off.
- `test_upload_ids_follow_rows_a_decision_left_out`: `tfl_rows()` with an extra excluded row (`excluded=True`) placed first, upload 300: the same result as the first test.
- `test_one_set_counts`: `_one_set([620, 890, 660, 600, 720, 1000, 1050, 610], 5540) == (1, [0, 1, 2, 3, 4, 5, 6])`; `_one_set([100, 100, 200], 200)[0] == 1` (only {100,100}: a set is two or more); `_one_set([100, 100, 100], 200)[0] == 2`; `_one_set([100, 300], 250) == (0, None)`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -k "claim_line_is_booked_from or leaves_out or whole_statement or no_set or another_supplier or without_uploads or one_receipt_of or paired_on_its_own or kept_apart_is_never or ticked_include_is_booked_as_well or refund_on_the or order_of_rows_makes or upload_ids_follow or one_set_counts" -q`
Expected: FAIL (`upload_ids` unknown, `_one_set` missing).

- [ ] **Step 3: The records**

Add the two fields to `Transaction` with comments in the style of their neighbours; `booked()` checks `tx.recorded_by is not None or tx.left_off_claim is not None or tx.in_opening`; add `"not_claimed"` and `"claim_receipts_unclear"` to `MATCHING_ISSUES`; `_cleared` resets `recorded_by_refs=[]` and `left_off_claim=None`.

- [ ] **Step 4: Thread `upload_ids`**

Through `match`, `match_documents`, `_without_left_out` (sliced by `kept`, as `name_days`), into `_with_claims`, and `posting.matched_rows`. In `books.py`, each of the three calls passes `upload_ids=[row.upload_id for row in b.stored]` (`self.stored` in `post`).

- [ ] **Step 5: Implement `_one_set`**

Not determined by the tests, so the approach: a forward table over prefixes, `ways[i]: dict[int, int]` from a reachable sum (≤ target) to the number of subsets of the first i amounts reaching it, each count capped at 2, with how many items each subset holds tracked only as "one" or "two or more" so single items don't count as a set. Give up and return `(0, None)` if any table exceeds 200,000 sums. Reconstruct the one set by walking the table back from `target`.

- [ ] **Step 6: Implement the pass in `_with_claims`**

After the `settled` pairs and before the `differs` pass. For each open line (not in `paired_lines`, dated), group its candidates by upload: receipts (document type "receipt", booked, a `_Document` of one row not in `paired_documents`), same direction, `named(line, d)`, not `kept_apart`, dated in `[line.date - COVERED, line.date + CARD_DAYS]`, upload id not None. On an upload with 2 to 60 candidates, call `_one_set`. Pair the line only when the counts across its uploads total exactly 1; then call a new `pair_set(n, documents: list[_Document])` that does for each document what `pair` does (claimed_in, 2110, issues), runs `_claim_vat` once against a `_Document` made of all the set's rows, sets the line's `recorded_by` (the Settlement above), `recorded_by_refs` and the `booked_twice` warning when ticked, and marks every other candidate on that upload with `left_off_claim` (the line), `contra_account_code` 2110 and `not_claimed`:

```
On {supplier}'s statement with {n} charges on {claimant}'s claim, but not claimed itself. Not booked: {claimant} paid it and hasn't asked for it back. If it was a business expense missed from the claim, tick Include.
```

(`{claimant}` is the line's counterparty; "the claimant" without one.) Lines in date order then row order; a receipt paired here is added to `paired_documents`.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_matching.py tests/test_checks.py tests/test_posting.py tests/test_books.py -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add ledgersync tests/test_matching.py
git commit -m "feat: a claim line is booked from the receipts on one document that add up to it"
```

---

### Task 3: When the app can't tell, and a leftover the bank pays

**Files:**
- Modify: `ledgersync/matching.py` (the pass from Task 2; `_pair_receipts`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: Task 2's pass, `_one_set`, `left_off_claim`.
- Produces: `claim_receipts_unclear` on the line (`related`: all its candidates) and on the first candidate of each upload involved (`related`: `[line]`).

- [ ] **Step 1: Write the failing tests**

- `test_two_sets_that_add_up_pair_nothing_and_ask`: a claim line of £12.00 and four TfL receipts on one upload, £6.00, £6.00, £6.00, £3.00 (three sets of two make £12): line booked, nothing paired, `("claim_receipts_unclear", "warning")` in `codes(line)`, `about(line, "claim_receipts_unclear")` names the four rows, the first receipt warns the same about the line.
- `test_sets_on_two_uploads_pair_nothing`: `tfl_rows()` plus a second TfL statement on upload 201, two receipts of £30.00 (15 Oct) and £25.40 (16 Oct), refs `tfl2-…` (different amounts, so not taken as copies): nothing pairs, the line and both uploads' first candidates warn.
- `test_two_lines_that_could_share_charges_pair_neither`: `tfl_rows()` plus a second claim line of £12.80 on 31 Oct ("Transport for London"), whose one set is 27 Oct + 20 Oct (£6.20 + £6.60), both in the £55.40 line's set: neither line pairs, both warn `claim_receipts_unclear`, every charge stays booked as today.
- `test_a_leftover_a_bank_line_pays_is_booked_from_the_bank`: `tfl_rows()` plus a business bank line (statement, out, £6.10, 7 Oct, "TFL TRAVEL CH", upload 210): the 5 Oct row has `left_off_claim is None`, no `not_claimed`, `paid_by[0].ref` is the bank line's ref, `contra_account_code == "1200"`, booked; the bank line's `recorded_by` is the 5 Oct receipt.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -k "two_sets or two_uploads or could_share or leftover_a_bank" -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In the pass: work out every open line's counts and sets first, then pair. A line with a total count of 2 or more, or of exactly 1 on more than one upload, warns. A line whose one set shares a receipt with the candidates of another line that has a count of 1 or more warns too, as does that other line; neither pairs. Message on the line: `{n} sets of {supplier}'s charges on its statement add up to {amount}: can't tell which this line claims.` (`{n}` "Several" when capped at 2.) On the receipt: `Some of these charges add up to {claimant}'s claim line of {amount} in more than one way: can't tell which it claims.`

In `_pair_receipts`: a receipt with `left_off_claim` is a candidate as if booked; when a bank line records it, its `left_off_claim` and `not_claimed` go and `_record` sets its contra to the line's account as for any receipt.

- [ ] **Step 4: Run the matching file**

Run: `.venv/bin/python -m pytest tests/test_matching.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/matching.py tests/test_matching.py
git commit -m "feat: a claim line whose charges add up more than one way asks, and a charge the bank pays is booked"
```

---

### Task 4: The AI review sees the set and the leftover

**Files:**
- Modify: `ledgersync/agent/tools.py` (`_MATCHES` use in `_related`; the issue family map)
- Modify: `ledgersync/agent/prompt.py` (one rule)
- Modify: `ledgersync/duplicates.py:30` (`found`)
- Test: `tests/test_agent.py`, `tests/test_duplicates.py`

**Interfaces:**
- Consumes: `recorded_by_refs`, `left_off_claim`, the two issue codes.

- [ ] **Step 1: Write the failing tests**

- `test_a_claim_line_is_related_to_every_receipt_it_is_booked_from` (`tests/test_agent.py`, with that file's saved-row builders): `_related(line, rows)` holds all seven receipts; `_related(receipt, rows)` holds the line.
- `test_a_leftover_is_related_to_its_claim_line`: `_related(leftover, rows)` holds the line.
- `test_a_claim_line_and_its_receipts_are_not_duplicates` (`tests/test_duplicates.py`): with the matched `tfl_rows()`, no `possible_duplicate` between the line and any receipt, nor between the receipts.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_agent.py tests/test_duplicates.py -k "booked_from or leftover or not_duplicates" -q`
Expected: the `_related` tests FAIL.

- [ ] **Step 3: Implement**

`refs(r)` in `_related` also takes `r.recorded_by_refs` and `r.left_off_claim`; `duplicates.found` adds `tx.left_off_claim` and a Settlement per `recorded_by_refs` ref (or compares refs directly); the family map gives `"not_claimed": "documents"` and `"claim_receipts_unclear": "duplicate"` (the family `booked_twice` is in). Prompt rule, beside the `recorded_by` one:

```
- A charge on a supplier's statement that the claimant's claim leaves out (issue not_claimed) is not booked: the claimant paid it. Only the person can say it was a business expense missed from the claim: don't ask, and don't book it.
```

- [ ] **Step 4: Run the agent and duplicate files**

Run: `.venv/bin/python -m pytest tests/test_agent.py tests/test_duplicates.py tests/test_specialists.py tests/test_resolutions.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/agent ledgersync/duplicates.py tests/test_agent.py tests/test_duplicates.py
git commit -m "feat: the AI review sees a claim line's receipts and the charge the claim leaves out"
```

---

### Task 5: The table says it

**Files:**
- Modify: `frontend/src/lib/api.ts` (`Transaction`)
- Modify: `frontend/src/lib/ledger.ts` (`kindOf`, `statusLines`, `ISSUE_TITLES`, `ABOUT_ANOTHER_ROW`, `claimLineOf`)
- Modify: `frontend/src/lib/todo.ts` (`TAGS`)
- Test: `frontend/src/lib/ledger.test.ts`, `frontend/src/lib/todo.test.ts`

**Interfaces:**
- Consumes: `recorded_by_refs?: string[]`, `left_off_claim?: Settlement | null` from the API.

- [ ] **Step 1: Write the failing tests**

- A claim line with `recorded_by` (description "TfL Customer Services, 7 charges, 6 to 27 Oct 2026", amount "55.40", date "2026-10-27") and seven `recorded_by_refs`: its status text is `` `Booked from 7 receipts: ${optionLabel([tx.recorded_by])}. Tick to book this line as well` `` (the test checks it starts with `Booked from 7 receipts: TfL Customer Services, 7 charges` and ends with `Tick to book this line as well`); ticked, `Booked as well as 7 receipts: …. Untick to book it from the receipts only`; `kindOf` is `'not booked'` unticked.
- `claimLineOf(receipt, rows)` finds the line when the receipt's ref is in `recorded_by_refs` but not `recorded_by.ref`.
- A row with `left_off_claim` and no `include`: `kindOf` is `'not booked'`; its status text is `Not on ${left_off_claim.description}, not booked. Tick to include it`, with the tick.
- `issueTitle('not_claimed') === 'Not claimed'`, `issueTitle('claim_receipts_unclear') === "Can't tell which charges"`; `aboutAnotherRow('claim_receipts_unclear')` true; `tagOf('not_claimed') === 'Documents'`, `tagOf('claim_receipts_unclear') === 'Recorded twice'`.

- [ ] **Step 2: Run and see them fail**

Run: `cd frontend && npm test`
Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

The two fields in `api.ts` with comments like their neighbours. In `statusLines`, the claim-line branch says `Booked from {n} receipts: …` when `recorded_by_refs` has two or more (otherwise as today); a `left_off_claim` branch before `copy_of`. `kindOf` treats `left_off_claim` as `recorded_by`. `claimLineOf` matches `r.recorded_by?.ref === tx.document_ref || r.recorded_by_refs?.includes(tx.document_ref)`.

- [ ] **Step 4: Run the frontend tests and types**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: all pass, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib
git commit -m "feat: a claim line lists the receipts it is booked from, and an unclaimed charge says so"
```

---

### Task 6: Jenny's books, and the whole suite

- [ ] **Step 1: The whole Python suite, in the background**

Run: `.venv/bin/python -m pytest -q` (about 55 minutes; run in the background).
Expected: all pass, or only failures known before this work (compare with `git stash` if any look unrelated).

- [ ] **Step 2: Jenny (client 3), after the user restarts their API**

Fetch `/api/clients/3/years/2026-05-02/ledger` from the user's API and check: row 393 (£55.40 TfL line) has `recorded_by_refs` of seven refs and is not booked; rows 416 to 422 have `claimed_in` and contra 2110; row 423 (5 Oct, £6.10) has `left_off_claim` and `not_claimed`. Travel in the trial balance is £61.50 lower than before.

- [ ] **Step 3: Look at it in the app**

The Transactions page for client 3 in the preview: the claim line's status lists 7 receipts; the 5 Oct row shows not booked with its tick and warning; the AI review to-do list has the `not_claimed` card under Documents.
