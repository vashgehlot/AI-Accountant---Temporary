# A claim's note decides; without one, ask (design, 2026-11-17)

## Why

Jenny's October claim (client 3, year from 2 May 2026) came to the accountant's £849.34, but £46.89 sat in other
accounts, and nothing asked about it:

- ExCeL London Hospitality, 8 Oct, £24.90 + £3.25 VAT (fruit salad, pastries, tea, coffee): booked Subsistence; the
  accountant's is Staff Welfare ("Coffees for team at DAS"). The meal check asks only from £50.
- Victoria Food & Groceries, three buys (£3.99, £8.19, £3.99): booked Refreshments ("for the workplace, such as from a
  supermarket"); they were her own food while working away, Subsistence.
- Amazon hi-viz vest, £5.82: booked Sundry Expenses, the account for nothing else fitting; the accountant's is
  Printing & Stationery.
- The Gun, £56.45: booked Entertainment, asked about (meal check), recoded to Staff Welfare by hand.

The person who knows is the claimant. Usually the claim says (a note on the claim line, "Drinks for team after
DAS"); when it doesn't, the row should ask.

## Goals

- A claim line's own words reach the receipts it is booked from, and the who-was-there check reads them.
- A note that says staff or team books the meal or drink to Staff Welfare (VAT reclaimed); one that names clients or
  guests books it to Entertainment (VAT blocked). No question then.
- With no note, the row asks (a warning on the to-do list, which the person recodes or accepts):
  - food or drink on Subsistence from £20 (gross) on a claim;
  - Refreshments a person paid and claimed back: for the workplace, or food while working away (Subsistence)?
  - anything on Sundry Expenses: what was it for?

## Non-goals

- No change to the reader's instructions (no re-reading, no live tests).
- Rows not on a claim keep today's meal check (Subsistence from £50, Entertainment, Staff Welfare with guests).
- No new account (Printing & Stationery stays Office Stationery 7504 / Printing 7500).

## Anti-goals

- Asking about every small solo lunch or coffee on a claim (hence £20).
- A note recoding a row that is not food or drink.

## Approaches

- A. The reader says when food looks like it was for a group. Most accurate on the receipt alone; changes the
  reader, needs live tests, only for documents read from now on.
- B. A lower amount on a claim (£20), with the claim's note deciding first. Rules only, cheap and certain; may ask
  about a large solo meal. **Picked**, with the user's addition: the claim's note is the evidence, ask only without it.
- C. Clues in the receipt's words ("2 mocha", plurals). No reader change, but rests on how the reader words things.

## Decided

- Built on the uncommitted meal-check work in `ledgersync/checks.py` (`_who_was_there`, `_STAFF`, `_GUESTS`) and
  `ledgersync/accounts.py`.
- A note recodes rather than asks (Claude's call, agreed in the design message).
- £20 threshold (Claude's call).
- The question is an issue on the row, like `meal_check` ("Meal: who was there?").

## Left to the builder

- Where the claim words are carried (on `claimed_in`'s Settlement or a field of its own) and where the check runs
  so it sees them (after matching).
- Issue codes and to-do titles for the Refreshments and Sundry questions, and whether they are acceptable
  (`ACCEPTABLE` in `frontend/src/lib/ledger.ts`).
- How a note's recode keeps VAT right (Staff Welfare reclaims, Entertainment blocks).

## Done when

- Tests for each case pass.
- Jenny's saved rows replayed: asks about ExCeL £28.15, the three Victoria buys and Amazon; nothing else new.
