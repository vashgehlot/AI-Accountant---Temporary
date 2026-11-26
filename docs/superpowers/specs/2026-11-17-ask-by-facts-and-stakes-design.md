# Ask by facts and stakes, from the client's own materiality (design, 2026-11-17)

## Why

The checks ask from fixed amounts (£20 and £50 meals, £100 / £500 equipment, £300 insurance, every Sundry row). No
UK standard or firm works that way (research: `reports/Materiality and client queries.md`). Two separate things
decide what an accountant asks:

1. **Facts that change the tax**, at any amount: who was at a meal (VAT and Corporation Tax), personal or business,
   a director's cost, who got a gift, unexplained money in. HMRC's rules turn on these facts, not on size.
2. **Presentation**, by the client's own materiality: capitalise or write off, carry part of a bill forward,
   Sundry or a named account. Both answers are right accounts once the amount is immaterial (ISRS 4410, FRS 102 3.16B,
   BIM31045).

The user's rule: get it right rather than fast. A fact is asked whenever the evidence doesn't give it; nothing is
decided silently (every decision without a question says why on the row).

## Goals

- **Levels per client and year** (ISA (UK) 320 / 450 method, as firm policy): overall materiality from the client's
  figures, a working level (performance materiality) and a trivial level, each with its basis recorded. The firm can
  set the overall figure for a client; the other two follow from it.
- **Meals by evidence, not amount.** On Subsistence, Entertainment and Staff Welfare, who was there comes from the
  claim note (`claim_note`), the row's own words, or a receipt the reader says is for one person. Without that, the
  meal check asks, at any amount.
- **Any account choice, from the chart.** The reader names up to two other accounts it seriously considered. Where
  the chosen and another account differ in tax treatment, VAT reclaim (on a row showing VAT), or cost against the
  owner's own (Drawings, Director's Loan) or income against a loan, it is a fact: asked always. Where they differ
  only in name, or cost against asset with the same tax, it is presentation.
- **Presentation by levels.** Sundry, a name-only account choice, equipment (asset or cost) and a bill that may run
  past the year end are asked when the amount at stake is at or above the trivial level; below it the row stays as
  coded with a note saying so. Items left small on an account are added up: when they reach the working level, one
  question asks about them together.
- **Refreshments on an expense claim** is booked to Subsistence (a buy while working away), with a note; no question
  (a name-only difference: both allowable, groceries mostly zero-rated).

## Non-goals

- The client question list (batched questions sent to the client) and learning rules from answers: a later piece.
- A firm-wide settings level: the method's percentages are the app's; a firm sets a client's overall figure.
- Cash-basis clients (no such setting yet): the prepayment question stays for every client.
- Documents (receipt or VAT invoice wanted) and the existing nature checks (`personal`, `director_loan`,
  `possible_duplicate`, `unusual_account`): unchanged.

## Anti-goals

- Guessing a fact silently. A meal with no evidence of who was there is never coded on a default without asking.
- A new hard-coded pound limit in place of the old ones.

## Approaches

- **A. Everything in `checks.normalise`.** One place, but `normalise` sees one row and the client's settings only:
  levels need the year's figures, which need every row matched first (circular).
- **B. Facts in `normalise`, presentation in a pass after matching (picked).** Facts need only the row; the
  presentation pass runs where `books._saved_rows` already adds `unusual_account` and `possible_duplicate`, with the
  year's matched rows in hand to work out the figures, the levels and the running totals. Presentation questions
  don't change any figure, so the trial balance never waits on them.
- **C. Let the AI review judge presentation.** Flexible, but not repeatable or explainable at a quality review.

## Decided

- **The method** (`ledgersync/materiality.py`, the app's policy, quoted in each basis):
  - overall = 5% of profit before tax when profit is positive; otherwise 1% of total costs (ISA 320 A8);
  - working level = 50% of overall (the prudent end of 50–75%: right over fast);
  - trivial = 3% of overall (inside the 0–5% the FRC found every firm uses).
- **The figures**: the year before, when it has booked rows; otherwise this year so far scaled to twelve months
  (months from the year's start to its latest dated booked row, at least one). Profit = booked income less booked
  costs, net of VAT. No booked income or costs: no levels, and nothing is trivial (everything asks).
- **The firm's figure**: `Client.materiality` (overall, pounds), set in the client dialog; the basis then reads "set by
  the firm".
- **Shown**: `GET /api/clients/{id}/years/{start}/materiality` returns the levels and their basis; a line above the
  to-do list shows them.
- **Reader**: `people` ("one" / "several" / null, for food and drink) and `alternatives` (up to two chart codes) in
  the reader's JSON, kept as row inputs. Rows read before keep null / none: their meals ask.
- **Codes**: `meal_check` (fact, any amount), `account_fact` (fact), `sundry_check`, `account_choice`, `small_asset`,
  `asset_check`, `prepayment` (presentation, warnings when asked), `left_small` (info: why a row was left),
  `small_items_add_up` (warning). `claim_refreshments` goes. The constants `MEAL_CHECK`, `CLAIM_MEAL_CHECK`,
  `SMALL_ASSET`, `LARGE_COST`, `PREPAYMENT_FROM` go.
- **Prepayment stake**: the part of an annual bill after the year end, gross × months after the year end ÷ 12.
- **Builder check**: read by the author against the code (usage limits), not by a fresh agent.

## Left to the builder

- Wording of each question; how `account_fact` names what differs.
- The two receipts for the live reader tests (export Jenny's ExCeL group order and Bagel Factory receipt from the
  store into `eval/private/jenny/`).

## Done when

- Unit tests for each rule; live reader tests: ExCeL "fruit salad, pastries, tea, coffee" reads `several`, Bagel
  Factory reads `one`.
- Jenny's rows replayed: her meals without a note ask (none has `people` yet); her Victoria Food buys are on
  Subsistence with a note; totals unchanged at £849.34.
- `npm test`, `tsc` and the whole Python suite pass.

## Amended (2026-11-17, after Jenny's live books)

- **Figures need income.** A year's figures set the levels only when they hold booked income: Jenny's year held only
  her October expense claims, which gave 1% of £1,617.60 (trivial £0.49), and every name-only choice was asked.
  With no income booked (this year or last) and no firm figure, there are no levels.
- **No levels: presentation waits.** Each presentation question is left as coded with an info note (`left_unset`)
  saying what would be asked, and the line above the to-do list asks once for the client's figure. Facts are still
  asked at any amount. (This replaces "no levels: everything asks".)
