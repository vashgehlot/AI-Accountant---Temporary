# missing-date-from-bank: how the expected figures were worked out

A parking ticket with no date is dated from the one bank line that matches it: same amount, same payee. The
agent asks nothing.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services
(`checks.normalise`, `matching.match`, `evidence_rules`, `posting.summarise`) on the `.rows.json` files, without
MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 3 lines, no balances |
| `documents/parking-photo.png` | NCP ticket, Leeds Wellington Street. **No date.** £6.50 incl. VAT £1.08, NCP's VAT number printed. Paid by Visa |

The file name has no date in it. Even if it had, the date would not be used.

## Conventions

- A bank line posts against 1200 with no VAT. A receipt paired with its card payment is booked from the receipt,
  against the line's bank account (1200), and the line itself is not booked.
- **Document rules:** under £50 no document is needed. A receipt reclaims VAT only when it shows the VAT and
  the supplier's VAT number, up to £250.

## Rows and their double entry

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 03/10/2026 | Barclays | BT GROUP PLC | 42.00 | none | under £50, no document needed; no VAT | 7502 42.00 | 1200 42.00 |
| B2 | 14/10/2026 | Barclays | NCP LEEDS | 6.50 | — | recorded by R1, **not booked** | — | — |
| B3 | 30/10/2026 | Barclays | BARCLAYS ACCOUNT FEE | 8.50 | none | under £50; 7901 is exempt anyway | 7901 8.50 | 1200 8.50 |
| R1 | **14/10/2026** (from B2) | NCP ticket | NCP parking, Leeds Wellington Street (up to 3 hours) | 6.50 | 1.08 | receipt ≤ £250 with VAT number and VAT shown: reclaim | 7400 5.42; 2201 1.08 | 1200 6.50 |

**R1's date and pairing:**
- B2 is the only line for £6.50. Its payee "NCP LEEDS" matches "NCP" on the ticket, and nothing else matches the
  ticket. So the ticket takes B2's date, 14 Oct 2026, and B2 becomes the card payment the ticket records.
- This is `matching`'s `date_from_bank`. `resolutions.record_automatic` records it as "R1 Date from the bank"
  (actor `rules`), with B2 as the evidence.

**R1's VAT:** £6.50 × 1/6 = £1.0833, which is £1.08 to the penny, as printed. Net £6.50 − £1.08 = £5.42.

## Decisions

The agent resolves nothing. One automatic decision is expected:

| Rule | Row | Date | Evidence |
|---|---|---|---|
| R1 Date from the bank (rules) | NCP parking ticket | 2026-10-14 | `barclays-october.csv`: "NCP LEEDS" |

## Questions

None. The date comes from a matching bank line, and every row has the document its amount needs.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 42.00 + 6.50 + 8.50 = 57.00 | **-57.00** |
| 2201 Purchase VAT | 1.08 | | **1.08** |
| 7400 Travel | 5.42 | | **5.42** |
| 7502 Telephone and Internet | 42.00 | | **42.00** |
| 7901 Bank Charges | 8.50 | | **8.50** |

Check: the debits are 1.08 + 5.42 + 42.00 + 8.50 = 57.00, against credits of 57.00. It balances.

## Answers

None.

```json
[]
```

## Needs a check

Nothing. `matching` already dates the ticket from the bank (`date_from_bank`), and `record_automatic` records it.

## Judgement calls

1. **Parking goes to 7400 Travel.** The chart defines Travel as "fares and parking for work travel".
2. **The VAT is reclaimed.** A car park ticket that prints the operator's VAT number and the VAT is a simplified
   VAT invoice.
