# Who was at a meal, decided like an accountant (design, 2026-11-17)

## Why

The meal check asked "who was there?" on every food or drink row without a claim note, at any amount, including
groceries from a food shop on an employee's travel claim (Jenny's £3.99 and £8.19 Victoria Food receipts). Nobody
entertains a client with groceries. The user: "I want it to decide on its own, think like an accountant". This
replaces the earlier decision "who was there always gets asked when a meal has no note".

## How an accountant reads it

1. The claim note (already: `account_by_note`).
2. What was bought and where: groceries or provisions from a food shop are the claimant's own food while working.
3. The rest of the claim and the receipts: the AI review reads these (the day's travel, an event, team drinks).
4. Whether it matters: when the evidence can't settle it and nothing points to guests, a row under the client's
   trivial level is left as coded, saying so.

## Decided

- **Rules (checks).** On Subsistence, groceries from a food shop (the row's words or the seller name a grocer,
  supermarket, food shop or provisions) raise no meal question and get an info note (`meal_decided`) saying why;
  so does a receipt the reader says is one person's. Words naming guests or staff still ask, as before.
- **By materiality (materiality.decide).** A meal question with nothing pointing to guests (the claim doesn't say,
  or the receipt is for several) carries its amount as the stake: under the trivial level it is left on its account
  as coded (`left_small`, saying nothing points to guests); with no levels, or at or above it, it is asked. The stake
  is the amount that would be misstated, as materiality measures (ISA 450); a tax figure would need a rate the books
  can't know before the year's profit is in. A question naming guests is always asked.
- **The AI review (resolutions).** A new resolution, `who_was_there` (R7), lets the agent settle a meal question
  from the documents: `present` is `claimant` (Subsistence), `staff` (Staff Welfare) or `guests` (Entertainment),
  with quotes from the row's receipt or its claim, like every resolution (R0). It moves the row to that account and
  marks the meal question answered on it; it is shown and can be undone. A background review in suggest mode
  suggests it. The prompt tells the agent to reason as above and ask the person only when the documents point both
  ways.

## Done when

- Unit tests for each rule; the agent test for R7 (applied, refused without quotes or on a non-meal row).
- Jenny replayed: the two grocery receipts ask nothing and say why; the £9.20 coffees still ask while her
  materiality is unset, and are left with a note once a firm figure is set.
- The affected suites, `npm test` and `tsc` pass.

## Generalised (same day)

- **The reader says what was bought** (`bought`: groceries, food_to_go, meal_out, drinks_out, catering), from the
  items, not the shop: a Tesco meal deal is food to go, Sainsbury's milk and bread are groceries (live tests on the
  public fixtures). The shop-name list is kept only for rows read before the reader said.
- **Accountant cases** (`eval/accountant_cases`, `tests/test_accountant_cases.py`): a builder, a cafe, a landlord, a
  consultancy and a partnership, with an accountant's expectations written before the rules ran. They found one
  rule that didn't generalise: an asset was questioned only under the trivial level (a £12.99 mouse stayed on Office
  Equipment for a client whose trivial level was £12.60). An asset is now questioned under the working level, the
  same line equipment kept as a cost is asked from.
