# missing-date-must-ask: how the expected figures were worked out

A taxi receipt has no date, and no bank line matches it. Only the photo's file name carries a date, and a file
name is not evidence. So the agent asks, and the person answers.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 2 lines, no balances. No £18.00 line |
| `documents/IMG_20261009_081502.png` | Leeds City Cabs receipt, Leeds Station to Kirkstall, £18.00, paid cash. **No date**, no VAT, no VAT number |

**The file name says 9 Oct 2026 at 08:15.** That is when the photo was taken, the morning after the journey. The
person's answer is **8 Oct 2026**, so a run that took the name's date would show the wrong date as well as
asking nothing.

## Conventions

- A bank line posts against 1200 with no VAT.
- A receipt is booked as paid from 1200 when it is issued. Once it has a date and the statement has lines either
  side of that day with no payment of it, the bank did not pay it (it was cash): it is kept off the bank, in 9998
  Suspense, with a note, until a person says what paid it.
- Under £50 no document is needed. With no VAT shown, none is reclaimed.

## Rows and their double entry

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 03/10/2026 | Barclays | BT GROUP PLC | 42.00 | none | under £50, no document needed | 7502 42.00 | 1200 42.00 |
| B2 | 30/10/2026 | Barclays | BARCLAYS ACCOUNT FEE | 8.50 | none | under £50 | 7901 8.50 | 1200 8.50 |
| T1 | **none**, then 08/10/2026 from the answer | Taxi receipt | Leeds City Cabs taxi, Leeds Station to Kirkstall | 18.00 | none | receipt under £50 with no VAT: book the gross | 7400 18.00 | 9998 18.00 |

T1 is booked while undated. It waits in the year it was added to (1 Apr 2026), so the trial balance is the same
before and after the answer. Only its date changes.

## Decisions

The agent resolves nothing, and nothing is dated automatically. There is no £18.00 line, so `date_from_bank`
can't apply. The answer makes one decision:

| Rule | Row | Date | Actor |
|---|---|---|---|
| R1 Date from the person | Leeds City Cabs taxi | 2026-10-08 | user |

## Questions

| Before answers | After answers |
|---|---|
| `date`: "When was this Leeds City Cabs taxi, Leeds Station to Kirkstall?" (open) | none |

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 42.00 + 8.50 = 50.50 | **-50.50** |
| 9998 Suspense | | 18.00 (the cash taxi, until someone says what paid it) | **-18.00** |
| 7400 Travel | 18.00 | | **18.00** |
| 7502 Telephone and Internet | 42.00 | | **42.00** |
| 7901 Bank Charges | 8.50 | | **8.50** |

Check: the debits are 18.00 + 42.00 + 8.50 = 68.50, against credits of 68.50. It balances.

## Answers

```json
[
  {"question": {"kind": "date", "row": {"file": "IMG_20261009_081502.png",
                                        "description": "Leeds City Cabs taxi, Leeds Station to Kirkstall"}},
   "answer": {"kind": "date", "date": "2026-10-08"}}
]
```

## Needs a check

1. **The file name's date lands in `date_found`.**
   - `books._saved_rows` runs `file_dates.check_file_date` on each upload. For this undated receipt it sets
     `date_found = 2026-10-09` and adds a `file_date` warning ("No date; the file name says 9 Oct 2026").
   - Task 7's date rule is "no date and no `date_found` from a bank line". So `questions.refresh` must not treat
     this `date_found` as one, or the question is never asked.
   - The two can be told apart: a bank line's `date_found` comes with a `date_conflict` issue, a file name's with
     `file_date`.
   - `posting.matched_rows` (and so `booked_rows`) never runs `check_file_date`. The risk is only where the
     questions read `books.ledger`'s rows.
2. **The `file_date` warning's "Use" offers the name's date.** The page's "Use" button on that warning would
   date the row 9 Oct from the name. That is the existing page's behaviour, outside the chat. Worth knowing
   before the demo.

## Judgement calls

1. **Taxi goes to 7400 Travel.** It is a fare for work travel.
2. **The cash taxi is booked against 1200, as the app books any receipt.** A person might move it to 1230 Petty
   Cash, or to 2250 Director's Loan Account if a director paid. The receipt doesn't say, so neither is expected.
