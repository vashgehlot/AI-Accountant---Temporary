
## AI review as one to-do list (built 2026-11-15, not committed)

- Design: `docs/superpowers/specs/2026-11-15-ai-review-to-do-list-design.md`. Plan: `docs/superpowers/plans/2026-11-15-ai-review-to-do-list.md`. Ledger with the rulings: `.superpowers/sdd/2026-11-15-ai-review-to-do-list/progress.md`.
- All seven tasks are built. `npm test` 175 pass, `npx tsc --noEmit` clean, `tests/test_reviews_api.py` 19 pass. Checked in the preview app (`web-removed-lines-3016` + `api-removed-lines-8103`, seeded by `seed_review.py` in the session scratchpad).
- New: `POST /api/clients/{id}/reviews/retry` (`server.py`); `frontend/src/lib/todo.ts`; notice/history rules in `frontend/src/lib/reviews.ts`; `IssueList.tsx`, `useAccountChoices.ts`, `useRowDialogs.tsx`, `TodoList.tsx`, `ReviewHistory.tsx`; `AiReviewSection.tsx` rewritten; `ProblemsList.tsx`, `lib/problems.ts` and `runSaid` removed.
- Not done: no fresh reviewer has read it (self-review only); Apply and Undo were only seen being refused in the preview (the seeded decisions were not real ones); the user's own API behind port 3000 needs a restart for the new route.

## AI review: change in view, document beside it, one fix for many rows (built 2026-11-16, not committed)

- The to-do list above is committed as 540c6a3.
- Design: `docs/superpowers/specs/2026-11-15-ai-review-evidence-and-grouped-fixes-design.md`. Plan: `docs/superpowers/plans/2026-11-15-ai-review-evidence-and-grouped-fixes.md`. Ledger: `.superpowers/sdd/2026-11-15-ai-review-evidence-and-grouped-fixes/progress.md`.
- Built: `?show=1` on the file route (`server.py`, PDFs and images only); `frontend/src/lib/suggestions.ts`; `DocumentPanel.tsx`; `TodoList.tsx`, `AiReviewSection.tsx` and the stylesheet block.
- `npm test` 187 pass, `tsc` clean, the file-route tests pass; checked in the preview app. The whole `tests/test_clients_api.py` run was still going when this was written.

## A supplier's list of card charges read as a bank statement (reader fix committed as 4f71949)

- What happened: client 3's TfL "Payment Statement" (upload 117) was read as her bank statement, so matching moved the 21 receipts dated inside it to Suspense (£622.17) with a `not_on_statement` warning each.
- Fixed in the reader's instructions (`ledgersync/extractor.py`, rules 1 and 2): a supplier's own list of card charges is receipts, and a shop's receipt is a purchase though it prints "Sale". Tests: two in `tests/test_extractor.py`, two live ones in `tests/test_live_llm.py` (documents in `eval/private/jenny/`). The TfL PDF now reads as eight receipts in 4 reads of 4.
- Not done: the whole-suite run started after the fix had not reported when this was written; client 3's saved rows are unchanged (restart the API, delete the TfL upload and the 8 October Victoria Food upload, add both again).
- Shelved with the user: the safety net in matching. The design `docs/superpowers/specs/2026-11-16-doubted-statement-design.md` and the plan `docs/superpowers/plans/2026-11-16-doubted-statement.md` are both marked shelved; build only if another supplier's list is read as a bank statement. A smaller idea, not sized: have each `not_on_statement` warning name the file it relied on.

## View uploads, both documents on a two-row card, photos read at 2000 pixels (committed as 5219df9)

- Design: `docs/superpowers/specs/2026-11-16-view-uploads-and-both-documents-design.md`. Plan: `docs/superpowers/plans/2026-11-16-view-uploads-and-both-documents.md`.
- Built: `cardDocuments` and `viewable` in `frontend/src/lib/suggestions.ts`; `DocumentPanel` takes `documents: PanelDocument[]`; View on `UploadsList` / `DocumentsSection`; `prepare_image` at 2000 px (`ledgersync/pipeline.py`), with a live test on Jenny's Southgate receipt (`eval/private/jenny/`).
- Why the VAT was asked: the reader missed the VAT number at 1200 px on Jenny's two Southgate car park photos (0 of 8 reads); at 2000 it reads it in about 22 of 23. The Amazon order summary's VAT is rightly not reclaimed: no VAT number, "Estimated VAT".
- Not done: client 3's saved rows are unchanged (add the two Southgate photos again, or press Reclaim it). The second photo (upload 130) reads its number as 670 487 106 in 6 of 6; a mod-97 check of UK VAT numbers would catch that, not built.
- Checked in the preview app (`web-view-docs-3019`, a copy of the frontend in the session scratchpad, against the seeded API on 8103, whose row 4 was edited and upload 1 removed for the check).

## One claim line for several receipts (committed 20db45b..818a6d8, 2026-11-16)

- Why: Jenny's one TfL claim line (£55.40, row 393) covers 7 of the 8 daily charges on her TfL Payment Statement (upload 199); a claim line paired with one receipt only, so her TfL travel was booked twice.
- Design: `docs/superpowers/specs/2026-11-16-claim-line-for-several-receipts-design.md`. Plan: `docs/superpowers/plans/2026-11-16-claim-line-for-several-receipts.md`. Ledger with rulings: `.superpowers/sdd/2026-11-16-claim-line-for-several-receipts/progress.md`.
- Built: `upload_ids` threaded into matching; `_one_set`, `_pair_sets`, `_book_set`, `_unclear` in `ledgersync/matching.py`; `recorded_by_refs` and `left_off_claim` on `Transaction`; issues `not_claimed`, `claim_receipts_unclear`; initials of any run of 3+ words in `names_match`; AI review `_related`; frontend statuses, titles, to-do groups.
- Checked: Jenny's saved rows replayed through the new matching: 393 not booked (7 refs), 416-422 claimed on 2110, 423 (5 Oct) not booked with `not_claimed`; Travel £768.84 → £707.34. Her live books change once the API on port 8085 is restarted.
- Someone else's uncommitted meal_check work sits in checks.py, ledger.ts, accounts.py and frontend files: it was left out of every commit here.
- Reviewed by a fresh Opus reviewer (Fable limit reached): four fixes in e52afb3. Deferred minors: `_book_set` builds from `rows[r]` not `marked[r]` (can drop a `claim_receipts_unclear` note); `questions._partners` and `_paid_again` look only at `recorded_by.ref`, not `recorded_by_refs`.
- Tests: full suite 1783 passed; its one real failure (a test_ledger stand-in without `upload_ids`) fixed in 818a6d8; the rest were test-database timeouts, and test_ledger, test_reviews, test_reviews_api re-run all pass (95). Not pushed.

## A claim's note decides who a meal was for; without one, ask (committed 0b5418d..4e28418, 2026-11-17)

- Why: Jenny's October claim matched the accountant's £849.34, but £46.89 sat elsewhere and nothing asked: ExCeL coffees for the team (Subsistence, not Staff Welfare), three Victoria Food buys (Refreshments, not Subsistence), the Amazon hi-viz vest (Sundry).
- Design: `docs/superpowers/specs/2026-11-17-claim-note-or-ask-design.md`. Plan: `docs/superpowers/plans/2026-11-17-claim-note-or-ask.md`. Ledger with rulings: `.superpowers/sdd/2026-11-17-claim-note-or-ask/progress.md`.
- Built: `Transaction.claim_note` and `account_chosen`; `checks.account_by_note`, `_claim_words`, `_WITH_GUESTS`, `CLAIM_MEAL_CHECK` (£20), issues `claim_note`, `claim_refreshments`, `sundry_check`; `matching._noted`, `_RECEIPTS_SAY`; `_claim_vat` skips accounts that reclaim none; frontend titles and the Account tag. The uncommitted meal-check work went in with the first commit.
- Replay of Jenny's saved rows: asks on ExCeL £28.15, the three Victoria buys and Amazon £6.99, nothing else; totals unchanged. Her live books change once the API is restarted.
- Reviewed by a fresh reviewer; four findings fixed (claim VAT after a recode, a person's account kept, "at client site" not Entertainment, claim lines without a receipt ask).
- Not done: the whole-suite run after the fixes had not reported when this was written. Jenny's Amazon claim line says "Stationery": a claim's category could suggest an account; not built. `tests/test_ledger.py` has someone else's uncommitted spy fix for `upload_ids`.

## Ask by facts and stakes, from the client's own materiality (committed 5fd2a35..ff21da0, 2026-11-17)

- Why: the fixed limits (£20/£50 meals, £100/£500 equipment, £300 insurance, every Sundry) are not how UK firms work (research: `reports/Materiality and client queries.md`, notes in `research_notes/`). Facts that change the tax are asked at any amount; presentation choices go by the client's own materiality.
- Design: `docs/superpowers/specs/2026-11-17-ask-by-facts-and-stakes-design.md`. Plan: `docs/superpowers/plans/2026-11-17-ask-by-facts-and-stakes.md`. Ledger with rulings: `.superpowers/sdd/2026-11-17-ask-by-facts-and-stakes/progress.md`.
- Built: reader fields `people` and `alternatives` (rule 6 of the instructions; live tests on Jenny's ExCeL and Bagel receipts in `eval/private/jenny/`); `meal_check` by evidence at any amount; `account_on_claim` (Refreshments on a claim → Subsistence); `what_differs` / `account_fact`; `ledgersync/materiality.py` (`levels`, `year_levels`, `decide`), `Transaction.presentation`, `Client.materiality`, `GET .../materiality`; the to-do list's materiality line and the client dialog's field.
- Replay of client 3: levels £16.18 / £8.09 / £0.49 (1% of costs, no income booked); every meal without a note asks (her rows predate `people`; re-reading them would answer the one-person ones); Victoria Food on Subsistence with a note; Amazon asks; totals £849.34.
- Review: a fresh reviewer's four Important findings fixed test-first in 0c3e81c (prepayment by days, a P&L-against-balance-sheet choice is a fact, an accepted small_items_add_up stays answered, unbooked claim lines drop account_fact). Seven minors deferred, listed in the ledger.
- The 10 suite failures were fixed in 3d3061e: asset-or-cost is asked only when the reader names a fixed-asset account (a tiny client's levels made every phone bill ask), and a small asset is asked with no levels. Rows read before 2026-11-17 have no alternatives, so get no asset-or-cost question until re-read. Whole suite at 3d3061e: 1848 passed, 0 failed.
- Year close (user's decision, 2026-11-17): open fact questions (meal_check, account_fact) hold up closing a year until answered or accepted; presentation ones don't (books.close, FACT_QUESTIONS). Committed as a later commit with its tests; the close tests in test_books, test_owners, test_upkeep, test_undo, test_upkeep_api, test_clients_api and test_resolutions pass.
- Checked in the preview app (api-site-preview-8092 on its own database, web-site-preview-3005): the materiality line above the to-do list, the client dialog's Materiality field (saving £1,000 gives levels £1,000 / £500 / £30, "set by the firm"), a meal question card, a £6.99 Sundry row left under the trivial level. `.claude/launch.json`'s api-site-preview-8092 no longer forces a local MongoDB (none runs here): it uses .env's server with the database ledgersync_site_preview.
- Not done: the deferred minors in the ledger; the client question list; learning rules from answers; a cash-basis setting; the user's live API needs a restart to pick all this up.

## Jenny's live page: three fixes, then meals decided like an accountant (2026-11-17/18)

- **Duplicates**: two receipts on separate lines of one expense claim are not duplicates (duplicates.py compares the claim lines' upload, not the line refs). **Chat**: `edit_row` takes `not_same_as` (the page's Not the same), so the AI can record "different purchases"; the open agent question on those rows then closes (SAID_APART). **Materiality**: a year's figures set levels only when they hold booked income (Jenny's held only her claims: trivial £0.49); with no levels, presentation questions wait as `left_unset` notes and the to-do line asks once for the firm's figure.
- **Meals** (design `docs/superpowers/specs/2026-11-17-meals-like-an-accountant-design.md`; replaces "always ask who was there without a note"): groceries, one person's food and food to go are the buyer's own (`meal_decided` note, no question); a meal nothing points to guests on is left under the trivial level (`left_small`); the AI review settles the rest with `who_was_there` (R7, quoted evidence, undoable). Reader field `bought` (groceries / food_to_go / meal_out / drinks_out / catering), judged from the items: live tests on the public fixtures pass; the shop-name list is only a fallback for rows read before.
- **Accountant cases** (`eval/accountant_cases`, `tests/test_accountant_cases.py`): a builder, a cafe, a landlord, a consultancy, a partnership, expectations written as an accountant's. Found: an asset was questioned only under the trivial level; now under the working level.
- Tests: the affected files pass (the last rerun 466 passed; the full set's other files passed in the run before it, whose only failures were the test cluster's 500-collection limit, cleared by dropping 79 leftover `ledgersync_test_<hex>` databases). npm test and tsc pass.
- Jenny's uploads were removed by the user at 16:56 on 2026-11-17, so the replay used her rows as printed before. Uncommitted work not from this session (ledger.py, records.py, reviews.py, server.py, test_reviews_api.py: AI review history for deleted documents) was left out of this commit.
