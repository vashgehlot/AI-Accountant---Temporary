# ltd-two-accounts-transfer: how the expected trial balance was worked out

**These two documents are authored test documents, not copies of `eval/fixtures/`.** They test a transfer between
two of the client's own bank accounts. £5,000.00 leaves the current account and arrives in the savings account on
12/10/2026, so it is on both statements. It must be booked **once**: debit the savings account, credit the current
account. Booked from both statements it would move £10,000.00.

The expected trial balance was worked out by hand from the documents and the booking rules, and is checked by
`tests/test_eval_cases.py`, which feeds the rows a good reading gives through the real API, with a fake model. All
names and amounts are made up for the test.

## The rule

A line on one account's statement that is coded to another of the client's own accounts is a transfer. When the
other account's statement has the matching line (same amount, opposite way, within a few days), the second is the
other side of the first: it is shown as booked from that line and books nothing of its own.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Greywell Surveying Ltd | |
| Business type | `limited_company` | A limited company. |
| VAT registered | yes | No row shows VAT, so this changes no figure. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027, and both statements are in it. |
| Bank accounts | Business current account (current, 1200) and Business savings account (savings, 1210) | |
| Statements | `current-account-october.csv` is the current account's; `savings-account-october.csv` is the savings account's | `client.json`'s `statements` says so: the runner sends each file to its account. |

## Documents (authored)

| File | What it is |
|---|---|
| `documents/current-account-october.csv` | Bank CSV in the layout of the `csv-starling` fixture. Opening balance 8,000.00, three lines with running balances, closing balance 2,938.50 |
| `documents/savings-account-october.csv` | The same layout. Opening balance 1,000.00, two lines, closing balance 6,004.20 |

## Rows and their double entry

A line on the current account has 1200 as its other side, and a line on the savings account has 1210.

| # | Date | Statement | Description | Way | Amount | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| C1 | 06/10/2026 | Current | Pennine Telecom, broadband | out | 54.00 | 7502 Telephone and Internet | 7502 54.00 | 1200 54.00 |
| C2 | 12/10/2026 | Current | Transfer to savings | out | 5,000.00 | 1210 (the savings account) | 1210 5,000.00 | 1200 5,000.00 |
| C3 | 20/10/2026 | Current | Bank charges | out | 7.50 | 7901 Bank Charges | 7901 7.50 | 1200 7.50 |
| V1 | 12/10/2026 | Savings | Transfer from current | in | 5,000.00 | 1200 (the current account) | not booked: the other side of C2 | |
| V2 | 31/10/2026 | Savings | Interest | in | 4.20 | 4900 Other Income | 1210 4.20 | 4900 4.20 |

C2 and V1 are the same £5,000.00 seen from each side: the same amount, one out and one in, on the same day. C2 is
booked and V1 is not. VAT: none of the lines shows any, and a bank line books none.

**Statement checks:**

| Current | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 8,000.00 | |
| C1 | −54.00 | 7,946.00 | ✓ |
| C2 | −5,000.00 | 2,946.00 | ✓ |
| C3 | −7.50 | 2,938.50 | ✓ |

| Savings | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 1,000.00 | |
| V1 | +5,000.00 | 6,000.00 | ✓ |
| V2 | +4.20 | 6,004.20 | ✓ |

Both statements reconcile. The current account's movement, 2,938.50 − 8,000.00 = −5,061.50, is 1200's net below. The
savings account's movement, 6,004.20 − 1,000.00 = +5,004.20, is 1210's net.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | | 54.00 (C1) + 5,000.00 (C2) + 7.50 (C3) = 5,061.50 | **-5061.50** |
| 1210 Bank Deposit Account | 5,000.00 (C2) + 4.20 (V2) = 5,004.20 | | **5004.20** |
| 4900 Other Income | | 4.20 (V2) | **-4.20** |
| 7502 Telephone and Internet | 54.00 (C1) | | **54.00** |
| 7901 Bank Charges | 7.50 (C3) | | **7.50** |

Check: the debit nets are 5,004.20 + 54.00 + 7.50 = 5,065.70, and the credit nets are 5,061.50 + 4.20 = 5,065.70.
The expected trial balance sums to zero.

## What a wrong result looks like

- **The transfer booked from both statements**: 1200 would be −10,061.50 and 1210 would be 10,004.20, each with
  the £5,000.00 twice.
- **The transfer taken as a cost or income** (C2 in 9998 Suspense, or V1 in 4000 Sales): 1210 would be 4.20 or 1200
  would be −61.50 instead.
- **A statement sent to the wrong account**: 1200 and 1210 would swap what they hold.

## Judgement calls

1. **Both sides are coded to the other account**, not to an expense or income account. The reading is told the
   client's other accounts so it can do this.
2. **The interest, 4.20, goes to 4900 Other Income**: "bank interest received", with no VAT because the bank line
   shows none.
3. **No opening balances are entered**, so the accounts show the year's movements, not the statements' balances.

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`).

| Account | Old | New | Rule |
|---|---|---|---|
| 7502 Telephone and Internet | 54.00 | 0.00 (left out) | Pennine Telecom (6 Oct): a bank line of £50 or more with no document is held in 9998 Suspense. |
| 9998 Suspense | none | 54.00 | The same line, held. |

The transfer between the two accounts is not a purchase (1200 and 1210 are the client's own bank accounts), the interest
is money in, and the £7.50 bank charge is under £50: all booked as before.
