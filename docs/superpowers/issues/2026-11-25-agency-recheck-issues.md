# Issues from the agency re-check of 25 Nov 2026 (`2026-11-25-recheck`, `2026-11-25-recheck-fixed`)

No new paid run yet: its price was put to the user (the runner's plan: **$1.53, about 4 h**; the last real cost was
$1.27 over 3 h 7 m; the guard pauses at 1.5 times the estimate, about $2.30), and it waits on their yes. This check
cost nothing. The last run's books (`tbrun_cc7b5a84_1`, read on 24 Nov at 7560d43) were copied to `ls_recheck`,
served by today's app (dc4ebdc plus the uncommitted edits below) with the model unreachable
(`OPENROUTER_BASE_URL=http://127.0.0.1:9/v1`, launch config `api-recheck-8131`), re-posted, snapshotted with the
runner's own `take_snapshot` and scored with `score`. Rows are as the 24 Nov reader saved them, so fixes that act when
a file is read (A4 streaming, A5 payroll total, A6 Streamflix, A7 meals, U4 payroll warnings, the CT/PAYE reference)
don't show here. Only a fresh read shows those.

**The key is still unreviewed**: an accountant has not signed it off (`testbooks/out/review/signed-off.txt`).

| | 24 Nov run | Today's code on its rows | After today's fixes |
|---|---|---|---|
| Entries right | 89 / 711 | 520 / 711 | **622 / 711** |
| Documents right | 82 / 528 | 490 / 528 | 491 / 528 |
| Trial balance difference, before replies | £64,360.90 | £72,156.66 | £72,156.66 |
| Trial balance difference, after replies | £1,248,482.28 | £88,233.08 | £83,979.08 |
| Unpaid at the year end, faults | 1 | 5 | 0 (runner fix R8) |
| VAT box differences | £273.43 | £273.43 | £273.43 |

The 24 Nov "fixed, not committed" items (A1, A3–A7, R4, U1–U8) were all committed since (7e4a99f … a18f2d2). The
uncommitted edits in the main checkout before today (ledger.py, records.py, reviews.py, server.py,
tests/test_reviews_api.py) are the user's own AI-review-history work for deleted documents, not these fixes.

## The independent check

The plugin catalog has no UK VAT, HMRC or UK bookkeeping plugin. Countz Accounting and Finance are installed already,
but both work on US GAAP and need the books in their own data room or connector, so neither was used to recompute UK
figures. The independent working was done here from the key's own files, as an accountant would:

- **Trial balance.** Every remaining difference after the fixes, account by account: Freelancers (key 5100, app 5002
  + 7602 + 7603) £40,650; Debtors / Bad debts £1,200 / £1,000 plus £200 output VAT, the Lowther write-off
  unanswered; output and input VAT £7.66, the May Tallgrass reverse charge; Hannah's loan / Subscriptions £131.88,
  Streamflix; Stationery / Suspense £53.33, the chairs. All five are explained below. Nothing is left unexplained.
- **Debtors at 31 Mar 2024.** The key's list is £84,600. The app's, at the year end, is £89,400, which is the key's
  plus Lowther's £4,800 (not written off). The app's Debtors balance is £88,200 (£89,400 less the £1,200
  administrator's payment held on account). Once the bad-debt question is answered, the app books what the key does:
  £4,800 off Debtors, £3,000 net to Bad Debts, the £1,200 as a recovery with its £200 VAT.
- **Payment Processor Clearing.** The Stripe charges of 25–31 Mar 2024 not paid out until April come to £2,127. The
  key and the app (after A-N3) now both hold that.
- **VAT boxes.** Box 6 is £93.49 / £113.48 over: savings interest, which HMRC says is exempt (VATFIN3115), so the
  app is right and the key query stands (A2). Box 7 is £33.08 / £33.38 over: Streamflix, three months at £10.99, plus
  pence. Boxes 1–5 agree in every quarter.

## App

| # | Issue | Root cause | Fix | Status |
|---|---|---|---|---|
| A-N1 | Kite & Quill KQ-107 (£4,625) on Professional Fees while its other ten invoices are on Consultancy Fees, and no "usual account" suggestion | `coding.usual_accounts` counted the bank lines that pay a supplier's bills as their "bills". Those lines post against Creditors, and the account the reader guessed for them (7602 or 5002) posts nothing. That made 7602 only 14 of 20 (70%), under the 80% needed, so the odd invoice was never flagged | Lines that pay a document (`pays` and `paid_against`) are no longer history (`coding._checked`). Test: `test_bank_lines_that_pay_a_bill_are_not_history`. On the copy, the suggestion "The other 10 bills from Kite & Quill Design went to 7602" now appears | fixed, not committed |
| A-N2 | The administrator's £1,200 for Lowther (20 Mar 2024) was booked as Sales with no VAT: sales £1,200 high, Debtors £1,200 high, and a `sale_without_vat` warning | More than 120 days after the £4,800 invoice and for less than it, so not paid automatically. The `open_document` warning left the line on the account the reader chose (4000) | A receipt from a customer surely named (or named in the line, as "LOWTHER INTERIORS IN ADMIN" is) who owes more on an invoice it doesn't match is held on Debtors as their payment on account. The warning says so and asks for Link (`matching._on_account`). A receipt for more than any open invoice keeps its account, since it may be a new sale. After a write-off it is a recovery, as before. Tests: `test_an_unmatched_receipt_from_a_customer_owing_more_is_held_on_debtors`, `test_a_receipt_for_more_than_the_customer_owes_keeps_its_account`. Sales now match the key | fixed, not committed |
| A-N3 | Stripe takings held on Debtors (£2,127 at the year end; key 1250 Payment Processor Clearing), and 147 Stripe entries posted against 1100 | `checks.other_side` put every agent's statement on Debtors, the letting-agent rule. A payout with no report already went to 1250, so the same Stripe money sat on two different accounts | A payment processor's statement (`payees.processor` names the agent: Stripe, PayPal, SumUp…) is held in 1250, so its payout clears 1250. A letting or managing agent stays on Debtors. Test: `test_what_a_processor_holds_is_in_payment_processor_clearing_not_debtors`. 1100 and 1250 now match the key. This was listed on 24 Nov as a decision; it follows the app's own payout rule, so it was made here. **Say if you want it the other way** | fixed, not committed |
| A-N4 | The year to 31 Mar 2025 posted nothing (16 unposted changes) | One 2023 row needing a fix (Tallgrass TM-202305, read as USD) makes `books._opening` raise "Fix the earlier years first". `upkeep.settle` ran `questions.refresh` first, which needs the opening VAT, so it raised and settling gave up before posting. Posting itself works | The questions of a year whose opening can't be worked out wait, and the year still posts (`upkeep.settle`). Test: `test_a_row_to_fix_in_an_earlier_year_does_not_stop_the_next_year_posting`. On the copy, 2024-25 now posts 33 lines. The next year's shown trial balance still says "Fix the earlier years first", as designed | fixed, not committed |
| A-N5 | The Invoices page for a past year: an invoice paid after the year end showed nothing owed, and "£X owed at 31 Mar 2024" left out £32,880 (Mendip KF-1096/1097, Brightwater KF-1098) and £5,593.58 of bills that Debtors and Creditors hold | `InvoiceSummary.owed` is "after every payment, in any year", while the page ages it to the year end | New `owed_at_year_end` (payments after the year's last day left out) in `books._invoices`, the API and the TS type. Once a year has ended, `ageing(…, atYearEnd)` uses it, and a row paid since shows "£X at 31 Mar 2024" under Owed (`InvoicesSection`). Tests: `test_an_invoice_paid_after_its_year_end_says_what_was_owed_at_the_year_end`, the sections test "once the year has ended…" | fixed, not committed |
| A-N6 | The agent's question "Were the receipts dated 6–25 Apr 2023 … paid by the company credit card?" stayed open all year, though the card statement came in the next batch and paired every receipt | `_close_answered` closes an agent question only when its rows go, a person sets them apart, or a person changes one. The papers it waited for arriving was not one of those | A fourth reason, `PAIRED_SINCE`: every row of the question still in the books is now paired with a record from an upload added after it was asked. Rows already paired when asked keep their question. The costly full match runs only when a person changed something or papers came in since. Tests: `test_an_agent_question_goes_once_the_lines_it_waited_for_pair_with_its_rows`, `test_an_agent_question_about_rows_already_paired_when_asked_stays`. This needed no new agent tool: its `close_question` needs quotes or a person's change, and neither fits here | fixed, not committed |
| A-N7 | Four Moss & Pine questions ("is the Stripe charge the same sale as KF-1014?") are still open on these books | A3: the agent read the charge as a second sale. Its row view now says `posts_against`, so a fresh run shouldn't ask. These rows already paid the invoice when asked, so A-N6 rightly leaves them | none more (A3) | explained, check on a fresh run |
| A-N8 | Kite & Quill's invoices coded 7602 Consultancy Fees (£36,025) and one 7603 (£4,625); Wyvern and Tobias Lane on 5002; the key puts all freelancers on 5100 (Subcontractor Costs). Gross profit is understated by £40,650 | The reader's coding judgement; nothing ties one kind of supplier to cost of sales | Not fixed. A-N1 now flags KQ-107 toward 7602, not 5002. Options: a reader rule "freelance or studio work for client projects → 5002", or a review step that compares suppliers of the same kind. Either needs a paid run to check | open, needs a decision |
| A-N9 | Tallgrass TM-202305: no reverse charge for May (£7.66 in boxes 1 and 4), and the invoice isn't booked | The invoice prints "$38.31" beside a $49.00 total. The app reads it as USD 38.31 and holds it for a fix (A1). The bank line (USD 49.00, £38.31) books to 8201 with no VAT. The other eleven months' invoices post with the reverse charge | none: a person fixes the row (the page says how) | needs a person |
| A-N10 | Streamflix £10.99 a month to Subscriptions, not Hannah's loan (£131.88; box 7 £33 a quarter) | These rows were read before A6 (364eee5). The rule acts when a file is read | none more (A6) | fixed for fresh reads, check on the paid run |
| A-N11 | Brunel Energy BE-24049 (9 Apr 2024, £1,876.44, Jan–Mar electricity) is not accrued (EC-0505) | Year-end accruals are a missing feature | needs a design | open |
| A-N12 | The Kingsdown notice of administration was not read (two 504s) | A4: the reader ran to the token cap on an empty answer. Streaming (de3c64b) now stops it, but these rows are from before | none more (A4) | fixed for fresh reads, check on the paid run |
| A-N13 | The chairs' £53.33 VAT is reclaimed from a till receipt (EC-0346, AG-Q0580 never asked) | The user's 18 Nov "VAT invoice wanted" design, not built yet (worktree `vat-invoice-wanted`) | the design | waits on the user |

## Runner

| # | Issue | Root cause | Fix | Status |
|---|---|---|---|---|
| R8 | Five "owed at the year end" faults (£38,473.58): Mendip, Brightwater, Avonside, Kite & Quill | `check_unpaid` read the app's `owed` (after every payment, in any year) | It reads `owed_at_year_end` when the app gives it (`checks._owed`). Test: `test_unpaid_counts_what_was_owed_at_the_year_end_when_the_app_says_it`. 442 runner tests pass. On rescoring, 0 unpaid faults | fixed, not committed (runner branch) |
| R9 | 70 of the 89 wrong entries: Stripe payouts (23 bank + 23 Stripe-side) and card repayments (12 + 12, EC-0420) | The key posts a move between the company's own accounts in two steps through 1290 Transfers in transit. The app posts it once, bank to card or 1250 to bank. The trial balances agree | Entries should net 1290 within a deal before comparing, as the presentation notes already do for 1210/1290 | open |
| R10 | 11 Tallgrass documents "gross 49.00 vs 38.31" | The key gives a foreign invoice's gross in its own currency. The app books it at the pounds paid (6a2511f) | Compare a foreign document in pounds, or by currency and amount | open |
| R11 | 12 payroll reports "gross 18,178.33 vs 20,354.90" | The key's document gross is the total gross pay. The app's document total includes employer's NI and pension. The entries agree (apart from A5's 1p) | Compare payroll documents by their entries | open |
| R12 | P32s for Apr–Jun 2023 "booked" (key: not booked) | The app books the £5,000 Employment Allowance from those three P32s (dbfbcd8). The key books it elsewhere, and the trial balances agree | Accept a P32 that books only the Employment Allowance | open |
| R13 | Omar's October claim "not booked", its three receipts "booked" (EC-0602) | The key books the claim. The app books the receipts the claim lines record. The entries agree, though they post to 2110 Expense claims, not 2251 Omar's loan | Count a claim booked through its receipts; map 2110 to 2251 for a director's claim | open |
| R14 | 23 Stripe payout lines "not read" | The app books payouts from the bank side only (the processor table builds charges and fees) | Don't expect payout lines from a processor's export | open |
| R15 | Four dividend minutes "not booked" (EC-0230) | The minutes give no row. The bank payments book the dividends to 3260 (an interim dividend is recognised when paid), and the trial balances agree | Count minutes booked when their deal's entries are there | open |
| R16 | The "after replies" key expects a recovery (8100 −£1,000, VAT £200) with no write-off (1100 £89,400) | The runner doesn't answer the app's own questions (R4), so the write-off isn't made, yet the recovery stays in the expected figures | Design replies to the app's own questions (bad debt, opening prepayments and accruals, opening VAT, payout report); until then, leave out the deals that depend on them | open |

## Answer key

Audited on 25 Nov against the source papers and the 2023-24 rules: everything recomputed from the key's own files
and the generated PDFs, with no model calls. What it found:

| # | Issue | Root cause | Fix | Status |
|---|---|---|---|---|
| K1 | Box 6 leaves out the deposit interest (£93.49 / £113.48 / £75.57 a quarter, £357.45 in the year) | The key codes interest 4906 `outside` the scope. Deposit interest a business earns is an exempt supply, and exempt supplies go in box 6 (VAT Notice 700/12; practitioners' guidance agrees). The app includes it | `exempt` in `clients/agency._interest`, and interest counted as an output in `rules/vat.py` | fixed in the generator, set rebuilt |
| K2 | EC-0230 says an interim dividend is "booked from the minutes" | An interim dividend is recognised when it is paid, not when the board minutes it (only a final dividend binds when declared). Here the minutes and the payments fall on the same days, so the figures don't change | case reworded in `catalogue/cases.csv` and the edge-cases spec: "Booked when paid (an interim dividend); the minutes support it" | fixed (wording) |
| K3 | The café and deli receipts print Reading, Cardiff, Swindon and Gloucester, but their card lines all say BRISTOL (125 meals, £2,225, £466 VAT reclaimed as Subsistence) | `render/documents.py` gives each supplier a random town, while the card statement's merchant line prints the company's own town. Subsistence (and its VAT) is allowable only on a business journey. On the card statement the meals look like Bristol lunches by the office (the eater's own, or staff welfare); on the receipts they look like trips | new `testbooks/places.py`: the address and the card line take the town from one place (`card_town`), for the cafés and every other card line (Lumenhaus said LONDON, its invoice Bath; Corrib now prints its Irish town). The meals now print READING, CARDIFF and SWINDON on the card too, which fits Subsistence on journeys | fixed in the generator, set rebuilt |
| K4 | EC-0601 is "a director's streaming subscription **and groceries** on the company card", but the year has only Streamflix (£131.88); no grocery receipts or card lines | the case's groceries were never generated | two household shops at a made-up supermarket on the company card (16 Sep 2023 £70.65, 17 Feb 2024 £35.65), with itemised receipts, booked to Hannah's loan, and a query on the first (AG-Q0311). Hannah's loan closes at £961.82 | fixed in the generator, set rebuilt |
| K5 | PAYE is on a month-1 basis for everyone on code 1257L, so each employee's year's tax is £2.00–£3.60 under the annual liability (£16.80 in all) | `rules/payroll.py` is written that way ("month 1 basis") | none needed for testing (the payroll reports print these figures, and the books follow them). A real bureau runs cumulative tax on 1257L | noted |

**What the audit confirmed:**
- **The key ties to itself.** Its 2,550 entries sum to its trial balance in every column; the year-end journal equals
  the year-end column; profit before tax is £116,269.45.
- **Payroll** (84 payslips): employee NI at 12%, then 10% from 6 Jan 2024, with 2% above the upper earnings limit
  (Leah Morgan); employer NI at 13.8% above £758; the directors on the annual earnings period, trued up in March
  (£478.86 each); pension on qualifying earnings above £520, at 5% and 3%; tax on the net pay arrangement, with
  1257L's £1,048.25 a month free; the £5,000 Employment Allowance used April to June. The wages, NI, pension and
  PAYE-owed lines agree with the trial balance.
- **VAT returns** (Jun–Aug, Sep–Nov, Dec–Feb) recompute from the entries:
  - box 1 exactly;
  - box 4 exactly, with the £800 bad debt relief in Dec–Feb;
  - box 6, with the reverse-charge values (Notice 741A), apart from K1;
  - box 7 net of the VAT blocked on the car lease and entertainment.

  Mar–May 2023 agrees once March's opening VAT balances (£10,560 / £1,980) are added. Due and direct debit dates
  are right.
- **Reverse charge** on Tallgrass (US) and Corrib Cloud (Dublin), standard VAT on Lumenhaus (London); half the
  VAT on the car lease is blocked. The car is 32 g/km, so none of the lease is disallowed for corporation tax (that
  starts above 50 g/km).
- **Bad debt** (Lowther): written off over six months past due; VAT relief £800; the £1,200 recovery pays back
  £200 (1,200 × 800 / 4,800).
- **Year end:**
  - depreciation, straight line with a full year in the year bought, for all five assets;
  - prepayments by days: insurance 183/366, the software licence 306/366, rent 84/91;
  - the electricity accrual for the 91 days of January to March, the accountancy fee accrual, and the April
    retainers deferred (£12,700) with their VAT left where the invoices put it;
  - the prior year's corporation tax over-provided by £223.
- **Corporation tax** £27,914.26: 25% less marginal relief (3/200 × (£250,000 − £119,487.78)), on profit plus
  depreciation and client entertainment, less full expensing of the laptop and chair. FRS 105 suits the company
  (turnover £541,607, 7 staff).
- **Banks:** the year-end reconciliations (£23.14 and £53.90 booked in March, cleared in April); dividends
  (£32,000) within the reserves; Hannah's loan in credit, so no s455.

**The rebuild (25 Nov).** Generator tests: 76 pass, 4 of them new (`test_vat`, `test_simulate_agency`). Build: seed 7,
agency plus the five packs, and every key check passes. Made in the `testbooks` worktree (branch `testbooks`), with the
same source and the new `out/` copied to the runner's worktree. The old set is kept at
`/private/tmp/claude-501/-Users-sandeepjala-ACTING-OFFICE--WORK-AI-Accountant---Temporary/a25a28bc-45db-4c81-9f28-332134cb3940/scratchpad/testbooks-out-2026-11-24`.

What changed in the key:
- Box 6 is now £138,009, £137,679 and £144,439: the app's figures, so that difference is gone.
- Box 7, the corporation tax and the profit are unchanged.
- The two grocery deals add 2 documents, 2 entries and 1 query, and every later deal's number moves up by one (the
  chairs are now AG-0581 and AG-Q0581).

Scored against the new key, the re-checked books (`2026-11-25-recheck-newkey`):
- VAT box differences fall from £273.43 to £66.46 (Streamflix only).
- New gaps of £106.30 on the bank and £238.18 on Hannah's loan come from the groceries, which the 24 Nov run never
  had. A fresh run reads them.
- The paid run on the new set: 580 files, $1.54, about 4 h.

Not checked: the capital allowances history of the three older assets (taken as fully claimed, which is consistent
with a nil pool); whether any project work was unbilled at the year end (no papers show any).

## Missing features (need a design first, unchanged since 24 Nov)

- Corporation tax charge (EC-0707), the year's accountancy fee accrual (EC-0506), year-end accruals for bills dated
  after the year end (EC-0505).
- The runner's replies to the app's own questions (R4/R16).
- One question for a repeating pattern; payment terms read from the invoice; insolvency notices; part write-offs.

## Where it stands

- **Uncommitted, main checkout (this session):** `ledgersync/coding.py` (A-N1), `ledgersync/matching.py` (A-N2),
  `ledgersync/checks.py` (A-N3), `ledgersync/upkeep.py` (A-N4), `ledgersync/books.py` + `ledgersync/models.py` +
  `frontend/src/lib/sections.ts` + `frontend/src/lib/clients.ts` + `frontend/src/components/InvoicesSection.tsx`
  (A-N5), `ledgersync/questions.py` (A-N6). Tests are in test_coding, test_matching, test_upkeep, test_books,
  test_questions and `frontend/src/lib/sections.test.ts`. The user's own uncommitted edits are untouched.
- **Tests run (targeted):** test_coding + test_resolutions 93; test_matching + test_posting + test_tables + test_checks
  548; test_adapter, test_checks, test_posting, test_questions, test_accountant_cases 370; test_agent, test_ledger,
  test_pipeline, test_questions, test_specialists, test_materiality 229; test_upkeep + test_upkeep_api 29;
  test_questions, test_upkeep, test_chat_api, test_agent 193; test_books -k invoice 7. All pass. Front end: 227
  pass, `tsc --noEmit` clean. The whole suite was not run.
- **Uncommitted, runner branch** (`claude/nostalgic-ptolemy-28a206`): `testbooks_runner/checks.py` and its test (R8).
- **Not checked in a browser:** the Invoices page's year-end figures (A-N5).
- **Waiting on the user:** the paid run's yes ($1.54, about 4 h, on the rebuilt set); A-N3 (keep processors on 1250?); A-N8 (how to code
  freelancers); A-N13 (the VAT-invoice-wanted design); nothing more on the key (K1–K4 fixed in the generator,
  not committed: `testbooks` worktree and the runner worktree).

## The paid run on the rebuilt set (`2026-11-25-agency-newkey`, app dc4ebdc + today's fixes)

$1.09 (from each answer's own cost; 37 calls carried none), 1 h 40 m, 619 calls. Entries right 635 / 713, documents
495 / 530, every file read (the Kingsdown notice too: A4 works), key questions asked 1 / 4. VAT differences £72.96.
Trial balance difference £91,927 before the replies, £100,810 after. Traced:

| # | Seen | First reading | Status |
|---|---|---|---|
| P1 | Employer's NI £3,223.60 high (7006 and 2210) | April's and June's P32s were read as two rows: the tax and NI due (£5,097.77) and "Employment Allowance claimed" (£1,776.40 / £1,447.20 in). `matching._payroll_summaries` took the allowance only from a P32 read as one row (May's), so the other two were left unbooked as summaries | `_allowance_line`: in a P32 of several rows, the row that is the Employment Allowance books it. Test: `test_a_p32_read_as_two_rows_books_its_allowance_row` | fixed, not committed |
| P2 | Hannah's loan £106.30 short | Streamflix now goes to her loan (A6 verified on a fresh read). The two household shops didn't: September's was read as two rows, food on 5000 Cost of sales (£59.25) and cleaning on 7801 (£9.50 + £1.90 VAT reclaimed); February's went to Subsistence under the 17–18 Nov meals rule ("groceries are the buyer's own food while working"). That rule was made for expense claims; on a company card there is no claimant, and with two directors no one owner | Asked, the user's decision of 25 Nov: groceries the company paid for itself (a receipt or invoice not on anyone's claim) no longer count as "the claimant's own" (`checks._company_bought`); they ask whose they were, at any amount: a director's own shopping goes to their loan, the office's is Staff Welfare, a trip's Subsistence. It is the meal question (`meal_check`, a fact question), answered by choosing the account; its card title is now "Who was it for?". Tests: `test_groceries_the_company_paid_for_ask_whose_they_were_at_any_amount`, the ledger.test title test. September's shop still goes wrong when the reader splits it onto 5000 and 7801 and doesn't say `groceries` | fixed (February's kind), not committed |
| P3 | Freelancers: £45,875 on 7602 (up from £36,025) | the reader's coding again (A-N8) | waits on a decision |
| P4 | 5000 £59.25, 7801 £9.50, 7406 £33.57, box 4 £1.90 and most of box 7's £69.16 in Sep–Nov | all the two grocery shops (P2) | follows P2 |
| P5 | Debtors £1,200, Bad debts £1,000, output VAT £200 | the Lowther write-off question is unanswered (R16) | known |
| P6 | Streamflix, groceries and chairs questions "never asked" | the app notes personal spending but doesn't ask; the chairs wait on the VAT-invoice-wanted design | known |

Box 6 agrees in every quarter now (K1).

### More found in the paid run (checked 25 Nov, after P1 and P2)

The app's log has no errors or warnings, and every request answered 2xx. The 37 model calls without a cost were
health checks (free), so $1.09 is the run's whole cost.

| # | Seen | Root cause | Fix | Status |
|---|---|---|---|---|
| P7 | The opening prepayments and accruals questions were asked for the year from 1 Apr 2026 ("released on 1 Apr 2026"), and Lowther's bad debt for 2024-25, not for the years they belong to. Answered there, the release or the write-off would have gone into the wrong year | Their keys name no year (`open:opening_prepayments`, `debt:<row>`). An unanswered opening prepayment is carried into every later year, so each later year wanted the same question too, and the last year worked out took it over. It shows now because A-N4 lets the later years settle | A question about the books brought in (opening prepayments, accruals and VAT) is asked only in the earliest open year. A bad debt is asked in the year it went bad if that year is still open (`questions._wanted`). Test: `test_a_question_about_an_earlier_year_stays_in_that_year_when_a_later_year_is_worked_out`. A later year's opening VAT question now waits until the earlier year is closed | fixed, not committed |
| P8 | The £720 credit note Kestrel & Finch gave Northgate Dental was flagged "Addressed to Northgate Dental Group … recode it to Director's Loan Account" | `matching._with_addressee` took any money-out invoice as a purchase; a credit note to a customer is money out on a sales account | sales accounts are left out. Test: `test_a_credit_note_the_company_gives_its_customer_is_not_asked_whose_it_is` | fixed, not committed |
| P9 | The £1,299 laptop and £624 chair were flagged "small to keep as an asset", though the client capitalises from £500 | `small_asset` (materiality) ran even with a capitalisation policy; the model's own comment says the policy decides. The old test looked for it among the issues, but it is a presentation question | asked only when the client has no policy; the test now looks in the presentation questions | fixed, not committed |
| P10 | The £186 client dinner at Marlowe's Kitchen, rightly on Entertainment, was flagged against the restaurant's usual Subsistence, and the rules suggested moving it (which would reclaim blocked VAT) | `coding.usual_accounts` treated meals like any supplier's bills | a move between two meal accounts is never suggested; who was there decides. A Vodafone bill on Entertainment is still flagged. Test: `test_a_meal_is_coded_by_who_was_there_not_by_the_restaurant` | fixed, not committed |
| P11 | The two £4.50 coffees (EC-0430, receipts QC-301 and QC-302) were flagged as a possible duplicate | `duplicates.possible_duplicates` compared amount, way and date only | two receipts from one shop with different printed numbers are two purchases (`_numbered_apart`); a second photo of one receipt is still flagged. Test: `test_two_till_receipts_with_different_numbers_are_two_purchases` | fixed, not committed |
| P12 | 42 "The payroll doesn't print £2,095.00: it was worked out … Check it against the document" warnings, about four a month | The report prints each person's figures and one total, the total gross pay. The reader added up the columns and gave no document total, so the payroll-total check (A5) never ran | with no document total, a printed figure the pay lines add up to confirms them, as the document total does (`adapter._with_payroll_total`). Test: `test_pay_lines_that_add_up_to_the_printed_total_gross_need_no_checking_one_by_one`. The employer's NI and pension lines (24 a year) are still flagged: the total gross pay doesn't cover them | fixed in part, not committed |
| P13 | The client answered the £312 VAT question in chat ("Redland & Co say a February invoice was left off their VAT figure. Fine to correct it this year"). The agent then asked for that February invoice, and the books' own opening VAT question stayed open | The agent has no tool to answer a rules question on the person's word: `close_question` closes only its own questions | a tool to answer a books' question from the person's quoted words (opening VAT, opening prepayments and accruals, bad debt), checked by the same service as the page's answer | open, needs a design |
| P14 | "Paid the oldest of 2 open items" ×12, "whose account" on each of the 12 Streamflix months, 31 presentation "account choice" questions on the freelancers | by design: one question for a repeating pattern is a missing feature | none | known |
| P15 | 70 of the wrong entries are the key's two-step postings through 1290 (Stripe payouts, card repayments); 23 Stripe payout lines "not read"; foreign and payroll document totals | the runner's comparison (R9–R14) | runner | open (runner) |

Tests after all the fixes: 1,008 pass across the 15 test files they touch (matching, checks, coding, duplicates,
adapter, questions, upkeep, resolutions, books, accountant cases, ledger, materiality, pipeline, posting, tables).
Front end: 228 pass, `tsc` clean.

## The five packs again (`2026-11-26-packs-today`, app f841d43)

$0.04 (estimate $0.37), 7 min, 36 calls. Every file was read.

| | 23 Nov | 26 Nov |
|---|---|---|
| Entries right | 20 of 21 | 20 of 21 |
| Documents right | 21 of 22 | 21 of 22 |
| VAT box differences | £31.79 | £0.00 |

- **EC-0301 laptop, EC-0316 overseas software (reverse charge), EC-0330 client dinner, EC-0430 two coffees:** pass. Box 7 now leaves out the dinner's blocked VAT (c4c75d9).
- **EC-0346, the £320 till receipt:** still fails. Its £53.33 VAT is reclaimed, and the full VAT invoice is never asked for. Waits on the user's VAT-invoice-wanted design (A-N13).
- **No AI review ran in any pack.** By design: the review starts only when the books raise something to look at, and these packs raise nothing (the same on 23 Nov).

The packs are one small company with one case each, so they say little about a different kind of client. That needs one of the planned clients built (the shop, café, builder, landlord or LLP).
