# Ask by Facts and Stakes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fact questions (who was at a meal, an account choice that changes tax or VAT) are asked at any amount when the evidence doesn't answer them; presentation questions (Sundry, name-only account choice, asset or cost, a bill past the year end) are asked only from the client's own trivial level, worked out from its figures.

**Architecture:** The reader adds `people` and `alternatives` to each row. `checks.normalise` raises the fact questions (one row is enough). A new `ledgersync/materiality.py` works out each year's levels from the matched rows, and a presentation pass in `books._saved_rows` (beside `unusual_account`) asks or leaves each presentation candidate that `checks.presentation_candidates` names, and adds up what it left.

**Tech Stack:** Python 3 / pydantic / pytest (`.venv/bin/python -m pytest … -q -p no:cacheprovider`); Next.js + TypeScript (`cd frontend && npm test && npx tsc --noEmit`).

**Spec:** `docs/superpowers/specs/2026-11-17-ask-by-facts-and-stakes-design.md`

## Global Constraints

- Method: overall = 5% of profit before tax when positive, else 1% of total costs; working = 50% of overall; trivial = 3% of overall. Pennies rounded half up.
- Figures: the year before when it has booked rows, else this year so far × 12 ÷ months (months from the year's start to its latest dated booked row, at least 1). Profit = booked income − booked costs, net of VAT posted.
- No levels (no booked income or costs) → nothing is trivial: every candidate is asked.
- `Client.materiality` (Decimal, optional) overrides overall; basis then says "set by the firm".
- No new fixed pound limit anywhere. `MEAL_CHECK`, `CLAIM_MEAL_CHECK`, `SMALL_ASSET`, `LARGE_COST`, `PREPAYMENT_FROM` and the `claim_refreshments` code are removed.
- Commit only this plan's files; `tests/test_ledger.py` and the frontend files `globals.css`, `DocumentsSection.tsx`, `UploadsList.tsx`, `clientRules*` hold others' uncommitted work.
- Python suite is slow: named files per task; the whole suite once at the end, in the background.

## Review Focus

1. A meal on Entertainment that names its guests asks nothing; one that names nobody asks at any amount (£3). Test in Task 2.
2. `people == "one"` on Entertainment still asks (one person "entertaining" is a contradiction). Test in Task 2.
3. An alternative that is the same account, or not in the chart, raises nothing. Test in Task 3.
4. A loss-making client gets levels from costs, and a client with no booked rows gets none (every candidate asked). Test in Task 4.
5. A row accepted by a person (`accepted`) is not asked again by the presentation pass, and `left_small` items on an accepted row still count in the running total. Test in Task 5.

---

### Task 1: The reader says how many a meal was for and what else it considered

**Files:** `ledgersync/extractor.py` (the row model ~40-120, the JSON example at ~203, the reading rules), `ledgersync/adapter.py:317` (Transaction built), `ledgersync/models.py` (`Transaction`), `ledgersync/rows.py` (`INPUTS`); tests `tests/test_extractor.py`, `tests/test_adapter.py`, `tests/test_live_llm.py`; documents `eval/private/jenny/` (ExCeL group receipt, Bagel Factory receipt exported from the store's blobs for client 3).

**Interfaces — Produces:** `Transaction.people: Optional[Literal["one", "several"]] = None`; `Transaction.alternatives: list[str] = []` (4-digit chart codes, at most two, never the row's own); both in `rows.INPUTS`.

- [ ] Step 1: tests. `test_extractor.py`: the row model takes `people: "One"` → `"one"`, anything else → `None`; `alternatives: ["8206 Staff Welfare", "7403"]` → `["8206", "7403"]`, more than two kept to two. `test_adapter.py`: a row with `people` and `alternatives` reaches the Transaction; an alternative equal to the row's account or not in `BY_CODE` is dropped. `test_live_llm.py`: the ExCeL receipt (fruit salad, pastries, tea, coffee) reads `people == "several"`; the Bagel Factory receipt (one Chicken Club) reads `"one"`.
- [ ] Step 2: run → fail (unknown fields). Live: `.venv/bin/python -m pytest tests/test_live_llm.py -k people -q` fails.
- [ ] Step 3: implement. Reader fields with descriptions: people — "For food or drink: one when the items are one person's (one meal, one drink), several when they are for more than one, null when unclear or not food or drink"; alternatives — "Up to two other accounts from the chart this could fairly be on, code and name; none when the account is clear". Add both to the JSON example. Validators normalise. Adapter maps and filters. Model fields with comments. `INPUTS` gains both.
- [ ] Step 4: run `tests/test_extractor.py tests/test_adapter.py` → pass; live test → pass.
- [ ] Step 5: commit "feat: the reader says how many a meal was for, and the other accounts it considered".

### Task 2: Who was at a meal, by evidence, at any amount

**Files:** `ledgersync/checks.py` (`_who_was_there`, constants, `normalise` claim block), `ledgersync/matching.py` (`_noted`), `ledgersync/agent/tools.py`, tests `tests/test_checks.py`, `tests/test_matching.py`.

**Interfaces — Consumes:** `Transaction.people` (Task 1). **Produces:** `checks.account_on_claim(tx) -> Optional[str]` (replaces `account_by_note`: the note's account, else `SUBSISTENCE` for `REFRESHMENTS` on a claim, else None); issue `claim_note` keeps its code, text names why (the note, or "bought while working away, on an expense claim").

- [ ] Step 1: tests (replace the amount tests at ~572-600 and the claim ones added on 2026-11-17):
  - Subsistence £3.40 no evidence → `meal_check`; same with `people="one"` → nothing; with `people="several"` → `meal_check` whose text says the receipt looks to be for more than one.
  - Entertainment £3.00 "The Gun" → `meal_check`; "drinks with clients" → nothing; `people="one"` "The Gun" → `meal_check`.
  - Staff Welfare £5 no staff words, no note → `meal_check`; "Team drinks" → nothing; "Drinks with clients" → `meal_check` naming Entertainment.
  - Refreshments £8.19 with `claim_note` → `account_on_claim == "7406"`; through `matched` (test_matching) the receipt lands on 7406 with `claim_note` info "working away", and asks `meal_check` (no `people`).
  - `claim_refreshments` appears nowhere.
- [ ] Step 2: run `tests/test_checks.py tests/test_matching.py` → the new ones fail.
- [ ] Step 3: implement. Evidence order: the note's account decides (no question); words naming guests or staff point the question (texts as today); `people == "one"` on Subsistence answers it; otherwise ask. Remove `MEAL_CHECK`, `CLAIM_MEAL_CHECK`, `claim_refreshments` (from `_DERIVED`, `ACCEPTABLE`, tools.py). `_noted` calls `account_on_claim`.
- [ ] Step 4: run → pass.
- [ ] Step 5: commit "feat: who was at a meal is asked whenever the claim, the words and the receipt don't say".

### Task 3: An account choice that changes the tax is asked

**Files:** `ledgersync/checks.py`, `ledgersync/agent/tools.py`, tests `tests/test_checks.py`.

**Interfaces — Consumes:** `Transaction.alternatives`. **Produces:** `checks.what_differs(tx: Transaction, other: Account) -> Optional[str]` — the plain-words difference that changes tax or VAT between the row's account and `other`, or None when only the name (or cost against asset with the same tax) differs. Differences, in order: tax treatment (`Account.tax`), VAT reclaim (`reclaim_vat`, only when `tx.vat`), cost against `DRAWINGS`/`DIRECTORS_LOANS` accounts, income against a liability. Issue `account_fact` (warning): `f"Could also be {other.code} {other.name}: {difference}. Which is it?"`, one per such alternative.

- [ ] Step 1: tests: `what_differs` for 7406 vs 7403 with VAT → mentions VAT and tax; 7502 vs 7504 → None; 8207 vs 7504 → None; 7502 (check) vs 8207 → mentions tax; a cost vs the drawings account → mentions the owner; normalise with `alternatives=["7403"]` on 7400 Travel with VAT → `account_fact`; alternatives on two meal accounts → no `account_fact` (the meal check asks); alternative equal to own account or unknown → nothing.
- [ ] Step 2: run → fail.
- [ ] Step 3: implement; add `account_fact` to `_DERIVED`, `ACCEPTABLE`, tools.py (`"coding"`).
- [ ] Step 4: run → pass. Step 5: commit "feat: an account choice that changes the tax or VAT is asked".

### Task 4: Each client's levels

**Files:** create `ledgersync/materiality.py`; modify `ledgersync/models.py` (`ClientFields`/`Client`, `ClientPatch`: `materiality: Optional[Decimal] = None`), `server.py` (route), `ledgersync/books.py` (`levels_of(store, client_id, year_start) -> Optional[Levels]`); tests create `tests/test_materiality.py`, modify `tests/test_clients_api.py`.

**Interfaces — Produces:**
- `materiality.Levels(BaseModel)`: `overall, working, trivial: Decimal`, `benchmark: Literal["profit", "costs", "firm"]`, `figure: Optional[Decimal]`, `basis: str` (e.g. "5% of profit before tax, £30,000, last year").
- `materiality.levels(income: Decimal, costs: Decimal, *, months: int = 12, which: str, firm: Optional[Decimal] = None) -> Optional[Levels]`.
- `materiality.year_levels(rows: list[Transaction], placed: list[int], years: list[Year], n: int, firm: Optional[Decimal]) -> Optional[Levels]` (uses `checks.booked`, account types from `BY_CODE`).
- `GET /api/clients/{client_id}/years/{start}/materiality` → `Optional[Levels]`.

- [ ] Step 1: tests: income 100,000, costs 70,000 → overall 1,500.00, working 750.00, trivial 45.00, benchmark profit; a loss (income 10,000, costs 20,000) → overall 200.00 (1% of costs); none booked → None; 6 months of 15,000 income / 9,000 costs → annualised profit 12,000 → overall 600.00 and basis says "this year so far, scaled to 12 months"; firm 2,000 → overall 2,000, working 1,000, trivial 60, basis "set by the firm". `year_levels` prefers the year before when it has booked rows. API: PATCH a client's materiality, then GET materiality shows benchmark firm.
- [ ] Step 2: run `tests/test_materiality.py tests/test_clients_api.py -k materiality` → fail.
- [ ] Step 3: implement (Decimal, `ROUND_HALF_UP` to pennies).
- [ ] Step 4: run → pass. Step 5: commit "feat: each client's materiality, from its own figures or the firm's".

### Task 5: Presentation questions from the client's levels

**Files:** `ledgersync/checks.py` (move the Sundry, `small_asset`, `asset_check`, `prepayment` blocks out of `normalise` into `presentation_candidates`), `ledgersync/materiality.py` (`decide`), `ledgersync/books.py` (`_saved_rows`, after `unusual_account`), `ledgersync/agent/tools.py`; tests `tests/test_checks.py` (~560-775 rewritten onto the new functions), `tests/test_books.py:697` area, `tests/test_materiality.py`.

**Interfaces — Consumes:** `Levels`, `year_levels` (Task 4), `what_differs` (Task 3). **Produces:**
- `checks.Candidate(NamedTuple)`: `code: str, stake: Decimal, asked: str, left: str` (the question's text, and the note's text when left).
- `checks.presentation_candidates(tx: Transaction, settings: BusinessSettings) -> list[Candidate]`: `sundry_check` (on 8207, stake gross); `account_choice` (an alternative `what_differs` returns None for, stake gross); `small_asset` (on an asset account, stake gross; asked when the stake is *under* the trivial level: "small to keep as an asset"); `asset_check` (on `ASSET_CANDIDATES`, asked when stake ≥ working level); `prepayment` (stake = gross × months after the year end ÷ 12). Same eligibility guards as today (money out, purchase document, GBP, not mixed, not journal, not accepted).
- `materiality.decide(rows, placed, levels_by_year: dict[int, Optional[Levels]]) -> list[Transaction]`: asks (warning) or leaves (`left_small`, info: "£6.99 is under this client's trivial level of £45.00: left on Sundry Expenses.") each candidate; per year and account, when the left stakes reach the working level, adds `small_items_add_up` (warning, on the largest, `related` = the rest).

- [ ] Step 1: tests: with trivial 45: Sundry £6.99 → `left_small`; £60 → `sundry_check`; levels None → `sundry_check` at £1; small asset £30 → `small_asset`, £200 → nothing; equipment on 7504 £800 with working 750 → `asset_check`, £700 → nothing; annual insurance £1,200 dated 1 Nov with year end 1 May → stake £600 → `prepayment`, £60 bill → `left_small`; three `left_small` of £300 on one account with working 750 → `small_items_add_up` naming £900; an accepted code is neither asked nor left. Port the existing guard tests (currency, mixed, statement, direction, document_total) onto `presentation_candidates`.
- [ ] Step 2: run → fail.
- [ ] Step 3: implement; remove the constants; `_saved_rows` builds `levels_by_year` with `year_levels` for each year the rows fall in and calls `decide`. Add `left_small`, `small_items_add_up`, `account_choice` to `_DERIVED`, `ACCEPTABLE` (not `left_small`), tools.py.
- [ ] Step 4: run `tests/test_checks.py tests/test_materiality.py tests/test_books.py tests/test_resolutions.py` → pass.
- [ ] Step 5: commit "feat: presentation questions are asked from the client's own trivial level".

### Task 6: The page shows the levels and names the questions

**Files:** `frontend/src/lib/ledger.ts` (titles, `ACCEPTABLE`), `frontend/src/lib/todo.ts` (Account tag), `frontend/src/lib/api.ts` (`getMateriality`), `frontend/src/lib/clients.ts` + `frontend/src/components/ClientDialog.tsx` (materiality field), `frontend/src/components/AiReviewSection.tsx` (line above the to-do list); tests `ledger.test.ts`, `todo.test.ts`, `api.test.ts`.

- [ ] Step 1: tests: titles `account_fact` 'Which account?', `account_choice` 'Another account?', `left_small` 'Left: under the trivial level', `small_items_add_up` 'Small items add up'; `claim_refreshments` gone; `account_fact`, `account_choice`, `small_items_add_up` acceptable and tagged Account; `getMateriality` calls `/api/clients/3/years/2026-05-02/materiality`; a helper `levelsLine(levels)` → "Materiality £1,500.00 (5% of profit before tax, £30,000, last year) · items under £45.00 left as coded", and `null` → "No figures yet: every item is asked about".
- [ ] Step 2: `npm test` → fail. Step 3: implement (ClientDialog: a number input "Materiality (£, optional)" saved as `materiality`, empty = null). Step 4: `npm test && npx tsc --noEmit` → pass. Step 5: commit "feat: the to-do list shows the client's materiality, and a firm can set it".

### Task 7: Jenny replayed, whole suite, handoff

- [ ] Replay client 3 (scratchpad script as before): her meals without a note ask `meal_check`; the Victoria Food buys sit on 7406 with a `claim_note` "working away" note; the Amazon vest is `left_small` or `sundry_check` by her levels; totals 849.34 each side.
- [ ] Whole Python suite in the background → pass. Live reader tests for Task 1 → pass.
- [ ] HANDOFF.md section: what was built, commits, replay, restart needed.
