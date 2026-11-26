# ltd-matched-payments: how the expected trial balance was worked out

**These three documents are authored test documents, not copies of `eval/fixtures/`.** No public fixture pairs a
document with the bank line that pays it, so this case was written to exercise two kinds of matching:

- a receipt recorded by its card payment;
- a bank line clearing an open invoice through 2100 Creditors.

The expected trial balance was worked out by hand from the documents. Before writing the documents, I read
`ledgersync/matching.py`, `ledgersync/checks.py` and `ledgersync/posting.py` for the matching windows and the posting
conventions. The app, the API, the ledger, the matching and posting code, and the extractor were not run to produce
or check any figure.

All names, addresses, VAT numbers and the invoice number are made up for the test.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Ashdown Analytics Ltd | The invoice is billed to it, so the invoice reads as a purchase. The name shares no word with any counterparty. |
| Business type | `limited_company` | The case is a limited company. |
| VAT registered | yes | The case is a VAT-registered company, so the VAT shown on the receipt and the invoice is reclaimed. |
| Contact email | ashdown-matched-payments@example.com | Reserved test domain. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027, and every document, dated 01/10/2026 to 31/10/2026, is in it. |

## Documents (authored)

| File | What it is |
|---|---|
| `documents/harbour-street-receipt.txt` | Harbour Street Stationers till receipt, 08/10/2026: paper 13.50, pens 6.00, sticky notes 4.50; total 24.00 including VAT 4.00; paid by VISA ending 4417 |
| `documents/pemberton-hale-invoice.txt` | Pemberton & Hale (chartered accountants) invoice PH-2026-114, 05/10/2026, billed to Ashdown Analytics Ltd: bookkeeping net 180.00, VAT 36.00, total 216.00, due 19/10/2026 |
| `documents/business-account-october.csv` | Bank CSV in the Starling fixture's column layout (`csv-starling`). Opening balance 5,000.00, three lines with running balances, closing balance 4,753.50. The format also adds a "Closing Balance" row, printed the same way as the "Opening Balance" row. |

## The matching rules read from `ledgersync/matching.py`

**A bank line pays an open invoice** (`match`, `_could_pay`, `_exact`, `_pay`):

- The line and the invoice go the same way.
- The invoice is dated on or before the line, at most 31 days before it (`WINDOW = 31 days`).
- Lines that pay exactly what one document owes, to a counterparty whose name matches (`names_match`), are paid
  first and automatically, whatever their date.
- A paid line posts against the account holding what was owed (`paid_against` = 2100 Creditors for a purchase
  invoice), with no VAT, because the VAT was booked with the invoice.

**A receipt is recorded by its card payment** (`_pair_receipts`):

- The bank line has nothing else matched to it.
- It is for the receipt's total, goes the same way, and is dated within 3 days of the receipt (`CARD_DAYS = 3
  days`).
- Names are tried first, then the amount and the date alone.
- The receipt is booked and the bank line is not (`checks.booked` is false once `recorded_by` is set). So the
  payment counts once, and its VAT is the receipt's.

## Why each pair matches

**Pair 1: the receipt and the 09/10 card line.**

| Test | Receipt | Bank line | Result |
|---|---|---|---|
| Amount | 24.00 | 24.00 | equal |
| Way | out | out | same |
| Date | 08/10/2026 | 09/10/2026 | 1 day apart, within 3 |
| Name | Harbour Street Stationers | Harbour Street Stationers | the same words, so `names_match` is true (the by-name pass) |

- The card line can't be taken by the invoice first. The invoice's counterparty (Pemberton & Hale) doesn't match
  its name, and 24.00 is not what the invoice owes (216.00), so `_decide` finds nothing to pay, suggest or offer.
- The invoice is dated 05/10, before the line, so the "paid before the document" suggestion doesn't apply either.
- The line therefore reaches `_pair_receipts` free, and the receipt records it.

**Pair 2: the invoice and the 16/10 Pemberton & Hale line.**

| Test | Invoice | Bank line | Result |
|---|---|---|---|
| Amount | 216.00 open | 216.00 | exact |
| Way | out | out | same |
| Date | 05/10/2026 | 16/10/2026 | 11 days later: on or after the invoice, within 31 days |
| Name | Pemberton & Hale | Pemberton & Hale | the same words, so `names_match` is true |

- The line also quotes the invoice number, PH-2026-114.
- It is the only line that names Pemberton & Hale for 216.00, so `_exact` finds exactly one document and `_pay`
  pays it automatically.
- `paid_against` = 2100 and the VAT is nil. The invoice's open amount goes to 0.00.

**The unrelated line: 31/10 bank charges, 6.50.**

- No document is for 6.50.
- By 31/10 the invoice is already paid, so it is not open, and its payee doesn't match anyway.
- No receipt is for 6.50.
- So the line is an ordinary bank line on its own account.

## Rows and their double entry

| # | Date | Source | Description | Way | Gross | VAT shown | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|---|---|
| R1 | 08/10/2026 | Receipt | Harbour Street Stationers: paper, pens, sticky notes | out | 24.00 | 4.00 | 7504 Office Stationery | 7504 20.00; 2201 4.00 | 1200 24.00 |
| I1 | 05/10/2026 | Invoice | Pemberton & Hale, PH-2026-114: bookkeeping, September 2026 | out | 216.00 | 36.00 | 7601 Accountancy Fees | 7601 180.00; 2201 36.00 | 2100 216.00 |
| S1 | 09/10/2026 | Bank | Harbour Street Stationers, VISA 4417 (recorded by R1) | out | 24.00 | none | not booked | none | none |
| S2 | 16/10/2026 | Bank | Pemberton & Hale, PH-2026-114 (pays I1) | out | 216.00 | none | paid against 2100 Creditors | 2100 216.00 | 1200 216.00 |
| S3 | 31/10/2026 | Bank | Bank charges, monthly account fee | out | 6.50 | none | 7901 Bank Charges | 7901 6.50 | 1200 6.50 |

The "Opening Balance" and "Closing Balance" rows have an amount of 0.00. They are balances, not transactions.

**VAT:**

- R1: 24.00 × 20/120 = 4.00, as printed. The net is 24.00 − 4.00 = 20.00, and the items add up to
  13.50 + 6.00 + 4.50 = 24.00.
- I1: 180.00 × 20% = 36.00, as printed, and 180.00 + 36.00 = 216.00. Also, 216.00 × 20/120 = 36.00.
- Bank lines show no VAT and book none. S2's VAT is nil because it was booked with I1.

Every booked row balances:

| Row | Debits | Credits |
|---|---|---|
| R1 | 20.00 + 4.00 = 24.00 | 24.00 |
| I1 | 180.00 + 36.00 = 216.00 | 216.00 |
| S2 | 216.00 | 216.00 |
| S3 | 6.50 | 6.50 |

S1 posts nothing.

**Statement check:**

| From | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 5,000.00 | |
| S1 | −24.00 | 4,976.00 | ✓ |
| S2 | −216.00 | 4,760.00 | ✓ |
| S3 | −6.50 | 4,753.50 | ✓ |
| Closing | | | 4,753.50 ✓ |

The statement reconciles. Its movement is 4,753.50 − 5,000.00 = −246.50. That is exactly 1200's net below: the card
payment is counted once, through the receipt.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | | 24.00 (R1) + 216.00 (S2) + 6.50 (S3) = 246.50 | **-246.50** |
| 2100 Creditors | 216.00 (S2) | 216.00 (I1) | 0.00, so it is left out |
| 2201 Purchase VAT | 4.00 (R1) + 36.00 (I1) = 40.00 | | **40.00** |
| 7504 Office Stationery | 20.00 (R1) | | **20.00** |
| 7601 Accountancy Fees | 180.00 (I1) | | **180.00** |
| 7901 Bank Charges | 6.50 (S3) | | **6.50** |

Check: the debit nets are 40.00 + 20.00 + 180.00 + 6.50 = 246.50, and the credit net is 246.50. The expected trial
balance sums to zero.

## What a wrong result looks like

- **The card line booked as well as the receipt** (the pairing undone, or the line ticked to Include): the £24.00
  counts twice. 1200 would be −270.50, and the line's own account would rise by 24.00.
- **The invoice not cleared** (the bank line unlinked, or posted to its own account): 2100 would show −216.00, and
  7601 would be 396.00, or the line's account would rise by 216.00.
- **The VAT doubled or lost**: 2201 would not be 40.00.

The year's checks are expected to pass for this case:

- the trial balance builds and balances;
- the statement reconciles;
- no row has an error;
- nothing is in 9998;
- every row is in the year.

## Judgement calls

1. **R1 goes to 7504 Office Stationery.** Paper, pens and sticky notes are "paper, pens, ink and other small office
   supplies".
2. **I1 goes to 7601 Accountancy Fees.** Bookkeeping by chartered accountants is "accountants, bookkeeping and
   audit".
3. **S3 goes to 7901 Bank Charges.** It is a bank account fee, so no VAT.
4. **The opening balance of 5,000.00 is not booked.** No opening balances are entered, so the trial balance holds the year's transactions only, so 1200
   shows the movement, −246.50.

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`). No figure moves:
both purchases have a document. The Harbour Street receipt prints "VAT Reg No 412 7730 58" and its VAT £4.00, so the VAT is
still reclaimed; the reading in `tests/test_eval_cases.py` now gives that number as `supplier_vat_number`, as a good
reading of the receipt does (without it a receipt's VAT is kept in the cost). The invoice reclaims its VAT as before.
