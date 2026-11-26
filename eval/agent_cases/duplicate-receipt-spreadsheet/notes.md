# duplicate-receipt-spreadsheet: how the expected figures were worked out

One Staples purchase appears three times: the till receipt, the Barclays card payment, and a line on the office
expenses sheet. The card paid it, so the sheet line is the duplicate. The agent keeps the receipt (R2) and the
sheet line leaves the books. Then the receipt pairs with its card payment, and the purchase is booked once,
against the bank.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 2 lines |
| `documents/staples-receipt.txt` | Staples till receipt, 13/10/2026, paper £29.99 + toner £34.81 = **£64.80**, "of which VAT @ 20% 10.80", VAT number printed, paid by card |
| `documents/staff-expenses-october.xlsx` | Priya Shah's October sheet: "Staples - printer paper and toner" 13/10 £64.80; "Train to Manchester, client meeting" 20/10 £34.60. No total row |

## Conventions

- **Lines:**
  - A bank line posts against 1200.
  - An expenses sheet line is owed to the employee (2110).
  - A receipt paired with its card payment is booked from the receipt, against 1200, and the line is not booked.
- **Document rules:**
  - A sheet line or bank line under £50 is booked with no document.
  - A receipt of £50–£250 with the VAT number and the VAT shown reclaims the VAT.

## What the books show before the agent acts

`matching` pairs the sheet line with the receipt, because they have the same amount, the same day and the same
shop. The receipt becomes the claim's, owed to Priya on 2110. That leaves the Barclays line unpaired, so it is
booked as well: £64.80, a bank line of £50 or more, so it goes to Suspense. The purchase counts twice:
- the receipt: 7504 54.00 and 2201 10.80, against 2110 64.80;
- the bank line: 9998 64.80, against 1200 64.80.

The bank line raises `possible_payment`: "may pay" the sheet line. That is the wrong reading, because the card paid
Staples, not Priya. It also raises `booked_twice`: "Also booked from the expenses sheet's receipt (Staples, £64.80,
13 Oct 2026). If this line paid it, drop the expenses sheet line: this line then pays the receipt."

## The decision

**R2 keep_one** on the receipt:
- **keep** "Staples: A4 printer paper and toner" (receipt, rank 3);
- **drop** the sheet line "Staples - printer paper and toner" (expenses sheet, rank 1).

R2's checks:
- The rows are one transaction: the sheet line is `recorded_by` the receipt (`_paired`), and they have the same
  £64.80, the same day and the same shop.
- The kept row ranks above the dropped one.

The evidence is two quotes:
- "TOTAL 64.80" from `staples-receipt.txt`;
- "Staples - printer paper and toner" from `staff-expenses-october.xlsx`.

The expected rule is "R2 Duplicate: kept the receipt".

What it does:
- The sheet line becomes `excluded`.
- `match` runs again without it. The receipt is no longer the claim's, so the Barclays line pairs with it: the
  same £64.80, the same day, and "STAPLES" matches "Staples". The line becomes `recorded_by` the receipt and is
  not booked.

## Rows and their double entry, after the decision

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 03/10/2026 | Barclays | BT GROUP PLC | 42.00 | none | under £50 | 7502 42.00 | 1200 42.00 |
| B2 | 13/10/2026 | Barclays | STAPLES | 64.80 | — | recorded by R1, **not booked** | — | — |
| R1 | 13/10/2026 | Staples receipt | Staples: A4 printer paper and toner | 64.80 | 10.80 | receipt ≤ £250, VAT number and VAT shown: reclaim | 7504 54.00; 2201 10.80 | 1200 64.80 |
| S1 | 13/10/2026 | Expenses sheet | Staples - printer paper and toner | 64.80 | — | **excluded by R2** | — | — |
| S2 | 20/10/2026 | Expenses sheet | Train to Manchester, client meeting | 34.60 | none | sheet line under £50: book, no VAT | 7400 34.60 | 2110 34.60 |

**R1's VAT:** £64.80 × 1/6 = £10.80 exactly, as printed. Net £54.00.

## Questions

None. The receipt backs R1, and S2 is under £50.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 42.00 + 64.80 = 106.80 | **-106.80** |
| 2110 Expenses Owed to Staff | | 34.60 | **-34.60** |
| 2201 Purchase VAT | 10.80 | | **10.80** |
| 7400 Travel | 34.60 | | **34.60** |
| 7502 Telephone and Internet | 42.00 | | **42.00** |
| 7504 Office Stationery | 54.00 | | **54.00** |

Check: the debits are 10.80 + 34.60 + 42.00 + 54.00 = 141.40. The credits are 106.80 + 34.60 = 141.40. It
balances.

## Answers

None.

```json
[]
```

## Needs a check

1. **No issue said the purchase is booked twice.** Done in Task 8: `matching` warns `booked_twice` on a bank line
   left unpaired whose amount, shop and day equal a receipt that a claim line records, pointing at the receipt and
   the claim line.
   - Before, `booked_twice` fired only when a person ticked Include on the claim line, and the agent had only
     `possible_payment` on the bank line to go on.
   - Without R2, `questions.refresh` asks for a receipt for "STAPLES £64.80", which is held in Suspense.
2. **R2 is only right here because the card paid.**
   - Had Priya paid (no Barclays line), `matching` already books the purchase once, owed to her on 2110. There
     is nothing to resolve.
   - Dropping the sheet line there would move the receipt's other side from 2110 to 1200, a bank payment that
     never happened. Checked with the services: 1200 goes from −42.00 to −106.80, and 2110 from −99.40 to
     −34.60.
   - R2 doesn't refuse it today. `_keep_one` could refuse to drop a claim line that a receipt records when no
     bank line would pay the receipt instead. Or the prompt could say so.

## Judgement calls

1. **The sheet is a log of office spending, not only a claim.** `staff-expenses-october.xlsx` is read as an
   expense claim, so each line is owed to Priya until paid. A line for something the company card already paid is
   then a duplicate, not money owed to her.
2. **Paper and toner go to 7504 Office Stationery** ("paper, pens, ink and other small office supplies").
3. **The train fare goes to 7400 Travel.** Rail fares are zero-rated, and with no ticket none is reclaimed anyway.
