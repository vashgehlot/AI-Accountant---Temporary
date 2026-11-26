# A Claim's Note Decides, Without One Ask — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A receipt booked from an expense-claim line is coded by the claim line's note (staff → Staff Welfare, guests → Entertainment); with no note, food or drink from £20, Refreshments on a claim, and anything on Sundry ask the person.

**Architecture:** Matching copies the claim line's description onto each receipt it books (`Transaction.claim_note`) and re-runs `checks.normalise` on that receipt, recoded first when `checks.account_by_note` names an account. `normalise` reads `claim_note` in the who-was-there check and raises the new questions as row issues; it is re-runnable (derived codes are dropped and re-made), so this is the same pass a person's recode gets.

**Tech Stack:** Python 3 / pydantic / pytest (`.venv/bin/python -m pytest`); Next.js + TypeScript (`npm test`, `npx tsc --noEmit` in `frontend/`).

**Spec:** `docs/superpowers/specs/2026-11-17-claim-note-or-ask-design.md`

## Global Constraints

- Builds on the uncommitted meal-check work already in the tree (`_who_was_there`, `_STAFF`, `_GUESTS`, `STAFF_WELFARE` in `ledgersync/checks.py`; account texts in `ledgersync/accounts.py`). Commit it together with Task 1; leave the other uncommitted files (`globals.css`, `DocumentsSection.tsx`, `UploadsList.tsx`, `clientRules*`) out of every commit.
- `CLAIM_MEAL_CHECK = Decimal("20.00")` (gross). Rows not on a claim keep `MEAL_CHECK = Decimal("50.00")`.
- No change to the reader (`ledgersync/extractor.py`), no new account.
- Python suite is slow (~55 min): run the named test files per task; the full suite once, in the background, at the end.

## Review Focus

1. A claim note naming both staff and guests ("team and client dinner") → Entertainment, VAT blocked (guests win, as in `_who_was_there`). Test in Task 1.
2. A recode by note to Entertainment must post no VAT even when `_claim_vat` hands the receipt the claim's VAT. Test in Task 2.
3. A claim note on a non-food receipt (a train ticket "for team away day") must not recode it. Test in Task 1.
4. Re-matching the same rows twice gives the same account and issues (no duplicated `claim_note` issue; `_cleared` resets `claim_note`). Test in Task 2.
5. A claim with no note and a solo snack under £20 asks nothing. Test in Task 1.

---

### Task 1: The checks read a claim's note and ask without one

**Files:**
- Modify: `ledgersync/models.py` (`Transaction`, beside `claimed_in` at ~219)
- Modify: `ledgersync/checks.py` (constants ~82-88, `_who_was_there` ~90, `normalise` ~449-452, `_DERIVED` ~29)
- Modify: `ledgersync/agent/tools.py:60` (family of each new code: `"coding"`)
- Test: `tests/test_checks.py`

**Interfaces:**
- Produces: `Transaction.claim_note: Optional[str] = None` — the claim line's description for a receipt booked from it; `None` when not on a claim.
- Produces: `checks.account_by_note(tx: Transaction) -> Optional[str]` — `STAFF_WELFARE` / `ENTERTAINMENT` when `tx.account_code` is one of `SUBSISTENCE, ENTERTAINMENT, STAFF_WELFARE, REFRESHMENTS` (`"8205"`) and `tx.claim_note` names staff only / any guest; else `None`.
- Produces issue codes: `claim_note` (info), `claim_refreshments` (warning), `sundry_check` (warning); `meal_check` keeps its code.

- [ ] **Step 1: Write the failing tests** (use the file's `tx`, `codes`, `REGISTERED`)

```python
def test_a_claim_note_for_the_team_points_a_meal_at_staff_welfare():
    t = tx(gross="28.15", account="7406", claim_note="Jenny Hogg - ExCeL - Coffees for team at DAS")
    assert account_by_note(t) == "8206"

def test_a_claim_note_with_guests_points_at_entertainment_even_with_staff():
    t = tx(gross="80.00", account="8206", claim_note="Jenny Hogg - Dishoom - team and client dinner")
    assert account_by_note(t) == "7403"

def test_a_claim_note_does_not_recode_what_is_not_food_or_drink():
    assert account_by_note(tx(gross="54.00", account="7400", claim_note="Jenny Hogg - Trainline - team away day")) is None

def test_a_receipt_on_staff_welfare_by_its_claim_note_says_so_and_is_not_asked():
    t = normalise(tx(gross="28.15", account="8206", claim_note="Jenny Hogg - ExCeL - Coffees for team at DAS"), REGISTERED)
    assert codes(t) == [("claim_note", "info")] and "Coffees for team at DAS" in t.issues[0].message

def test_a_meal_from_20_on_a_claim_with_no_note_asks_who_was_there():
    t = normalise(tx(gross="28.15", account="7406", claim_note="Jenny Hogg - ExCeL London Hospitality"), REGISTERED)
    assert codes(t) == [("meal_check", "warning")] and "doesn't say who" in t.issues[0].message

def test_a_snack_under_20_on_a_claim_is_not_asked():
    assert codes(normalise(tx(gross="8.69", account="7406", claim_note="Jenny Hogg - Bagel Factory"), REGISTERED)) == []

def test_a_meal_under_50_not_on_a_claim_is_still_not_asked():
    assert codes(normalise(tx(gross="28.15", account="7406"), REGISTERED)) == []

def test_refreshments_claimed_back_ask_if_it_was_food_while_away():
    t = normalise(tx(gross="8.19", account="8205", claim_note="Jenny Hogg - Victoria Food & Groceries"), REGISTERED)
    assert codes(t) == [("claim_refreshments", "warning")] and "Subsistence" in t.issues[0].message

def test_refreshments_not_on_a_claim_are_not_asked():
    assert codes(normalise(tx(gross="8.19", account="8205"), REGISTERED)) == []

def test_anything_on_sundry_asks_what_it_was_for():
    t = normalise(tx(gross="6.99", account="8207"), REGISTERED)
    assert ("sundry_check", "warning") in codes(t)

def test_the_checks_do_not_duplicate_when_run_again():
    once = normalise(tx(gross="8.19", account="8205", claim_note="Jenny Hogg - Victoria Food"), REGISTERED)
    assert codes(normalise(once, REGISTERED)) == codes(once)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_checks.py -k "claim_note or claim or sundry or refreshments or snack or meal_under" -q`
Expected: FAIL (`claim_note` unknown field / `account_by_note` not defined).

- [ ] **Step 3: Implement**

- `models.py`: add `claim_note: Optional[str] = None` to `Transaction` with a one-line comment.
- `checks.py`: `REFRESHMENTS, SUNDRY = "8205", "8207"`; `CLAIM_MEAL_CHECK = Decimal("20.00")`; `_FOOD_AND_DRINK = {SUBSISTENCE, ENTERTAINMENT, STAFF_WELFARE, REFRESHMENTS}`.
- `account_by_note` as in Interfaces, using `_STAFF` / `_GUESTS` on `tx.claim_note` (guests win).
- `_who_was_there`: words are `tx.description` plus `tx.claim_note`; the Subsistence threshold is `CLAIM_MEAL_CHECK` when `tx.claim_note is not None`, else `MEAL_CHECK`; when on a claim and neither words found, the Subsistence message reads: `f"A meal of {amount} on Subsistence, and the claim doesn't say who it was for: for staff only it is Staff Welfare (VAT reclaimed); with clients or other guests it is Entertainment (VAT can't be reclaimed). Recode it if so."` Return `None` when `account_by_note(tx) == tx.account_code` (the note already decided).
- `normalise`, beside the meal check (same guard: not journal, money out, receipt/invoice/expense_claim):
  - `account_by_note(tx) == tx.account_code` → `issue("claim_note", f"Booked to {account.name}: the claim says “{tx.claim_note}”.", "info")`.
  - account `REFRESHMENTS` and `tx.claim_note is not None` and no note decision → `issue("claim_refreshments", f"£{tx.gross:,.2f} on Refreshments, claimed back on an expense claim: Refreshments is for the workplace. If it was food or drink while working away, recode it to Subsistence.")`.
  - account `SUNDRY` → `issue("sundry_check", f"£{tx.gross:,.2f} on Sundry Expenses, the account for what fits no other: what was it for? Recode it if another account fits.")`.
- Add `claim_note`, `claim_refreshments`, `sundry_check` to `_DERIVED`; add the three to `agent/tools.py:60` as `"coding"`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_checks.py tests/test_accounts.py -q`
Expected: all pass (including the existing meal-check tests at ~572-600).

- [ ] **Step 5: Commit** (with the meal-check work it builds on)

```bash
git add ledgersync/models.py ledgersync/checks.py ledgersync/accounts.py ledgersync/agent/tools.py tests/test_checks.py tests/test_accounts.py
git commit -m "feat: a claim's note says who a meal was for; without one, food from £20, claimed refreshments and sundry ask"
```

### Task 2: Matching carries the claim's note onto its receipts

**Files:**
- Modify: `ledgersync/matching.py` (`_cleared` reset dict ~564; `pair()` ~798-822; `_book_set` ~1053-1056)
- Test: `tests/test_matching.py` (use `matched`, `claim_line`, `row`, `booked`)

**Interfaces:**
- Consumes: `Transaction.claim_note`, `checks.account_by_note`, `checks.normalise` (Task 1).
- Produces: a receipt booked from a claim line carries `claim_note == line.description`, its account is `account_by_note(...)` when that names one, and its issues are a fresh `normalise` of that.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_receipt_takes_its_claim_lines_note_and_is_recoded_by_it():
    line, receipt = matched(claim_line("28.15", "2026-10-08", "ExCeL London Hospitality - Coffees for team at DAS", account="7406"),
                            row("receipt", "out", "28.15", "2026-10-08", "ExCeL London Hospitality", "excel", account="7406", vat="3.25"))
    assert receipt.claim_note == "Jenny Hogg - ExCeL London Hospitality - Coffees for team at DAS"
    assert (receipt.account_code, receipt.vat_posted) == ("8206", Decimal("3.25"))
    assert "claim_note" in [i.code for i in receipt.issues] and "meal_check" not in [i.code for i in receipt.issues]

def test_a_receipt_recoded_to_entertainment_by_its_note_posts_no_vat():
    line, receipt = matched(claim_line("60.00", "2026-10-07", "The Gun - drinks with clients", account="7406"),
                            row("receipt", "out", "60.00", "2026-10-07", "The Gun", "gun", account="7406", vat="10.00"))
    assert (receipt.account_code, receipt.vat_posted) == ("7403", Decimal("0"))

def test_a_receipt_whose_claim_says_nothing_asks_who_was_there():
    line, receipt = matched(claim_line("28.15", "2026-10-08", "ExCeL London Hospitality", account="7406"),
                            row("receipt", "out", "28.15", "2026-10-08", "ExCeL London Hospitality", "excel", account="7406"))
    assert receipt.account_code == "7406" and "meal_check" in [i.code for i in receipt.issues]

def test_receipts_booked_from_one_claim_line_together_take_its_note():
    # as test_a_claim_line_is_booked_from_the_receipts_that_add_up_to_it (several receipts, one upload), with the line's
    # merchant "Transport for London - team trip": every chosen receipt's claim_note is the line's description
    ...

def test_matching_the_same_rows_again_gives_the_same_receipt():
    rows = [claim_line("28.15", "2026-10-08", "ExCeL - Coffees for team", account="7406"),
            row("receipt", "out", "28.15", "2026-10-08", "ExCeL", "excel", account="7406", vat="3.25")]
    once = matched(*rows)
    assert matched(*once)[1].model_dump() == once[1].model_dump()
```

(The fourth test follows the existing several-receipts test's setup in `tests/test_matching.py`; copy it and change the merchant and the assertion. If `row`/`claim_line` don't take `vat=`, pass the VAT the way the file's existing claim-VAT tests do.)

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -k "note or says_nothing or same_rows_again" -q`
Expected: FAIL (`claim_note` is `None`).

- [ ] **Step 3: Implement `_noted(tx: Transaction, line: Transaction, settings: BusinessSettings) -> Transaction` in `matching.py`**

Returns `normalise(tx.model_copy(update={"claim_note": line.description, **({"account_code": a} if (a := account_by_note(...)) else {})}), settings)`, where `account_by_note` is asked of the receipt with the note set. In `pair()` and `_book_set()`, build each document row from `_noted(rows[r], line, settings)` before the existing `claimed_in` / `contra_account_code` / `issues` / `vat` update (add `found` to the re-normalised issues, not the old ones). Apply `_claim_vat`'s `vat` update only when the recoded account reclaims VAT (`checks.reclaims_vat`). Add `"claim_note": None` to `_cleared`'s reset dict.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_matching.py tests/test_checks.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/matching.py tests/test_matching.py
git commit -m "feat: a receipt booked from a claim line takes the line's note, and is coded by it"
```

### Task 3: The page names the new questions

**Files:**
- Modify: `frontend/src/lib/ledger.ts` (titles map ~251; `ACCEPTABLE` ~301)
- Modify: `frontend/src/lib/todo.ts:27` (`Account` tag)
- Test: `frontend/src/lib/ledger.test.ts`, `frontend/src/lib/todo.test.ts`

**Interfaces:**
- Consumes: issue codes `claim_note`, `claim_refreshments`, `sundry_check` (Task 1).

- [ ] **Step 1: Write the failing tests**
  - `ledger.test.ts`: the title of `claim_refreshments` is `'Refreshments: for the workplace?'`, of `sundry_check` `'Sundry: what was it for?'`, of `claim_note` `'Coded by the claim'`; `acceptChange` accepts `claim_refreshments` and `sundry_check` (as the existing `meal_check` test at ~322 does).
  - `todo.test.ts`: a row with `issue('sundry_check')` makes a card tagged `Account`.

- [ ] **Step 2: Run them to see them fail** — `cd frontend && npm test` → the new tests fail.

- [ ] **Step 3: Implement** — add the three titles; add `claim_refreshments`, `sundry_check` to `ACCEPTABLE`; add `claim_refreshments`, `sundry_check` to the `Account` tag (and `meal_check` if absent).

- [ ] **Step 4: Run** — `cd frontend && npm test && npx tsc --noEmit` → all pass, clean.

- [ ] **Step 5: Commit** — `git add frontend/src/lib/ledger.ts frontend/src/lib/ledger.test.ts frontend/src/lib/todo.ts frontend/src/lib/todo.test.ts` (the uncommitted `ledger.ts` hunk from the meal-check work goes in too; `clientRules*` stays out), message `feat: the to-do list names the claim and sundry questions`.

### Task 4: Jenny's rows replayed

**Files:** a script in the session scratchpad (not committed).

- [ ] **Step 1:** Load client 3's year from 2 May 2026 through `books.trial_balance_shown` (as `scratchpad/j2.py` did) and list every row with `meal_check`, `claim_refreshments`, `sundry_check` or `claim_note`.
  Expected: `meal_check` on ExCeL £28.15 (24.90 + 3.25), and not on The Gun (recoded to Staff Welfare by hand, no guests named); `claim_refreshments` on the three Victoria Food rows (£3.99, £8.19, £3.99); `sundry_check` on Amazon hi-viz (£6.99); no other row gains one; totals still £849.34 each side.
- [ ] **Step 2:** Start the full Python suite in the background: `.venv/bin/python -m pytest -q -x` → all pass.
- [ ] **Step 3:** Add a HANDOFF.md section: what was built, the commits, the replay result, and that the live API needs a restart.
