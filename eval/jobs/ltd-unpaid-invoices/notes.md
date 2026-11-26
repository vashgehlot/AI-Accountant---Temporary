# ltd-unpaid-invoices: how the expected trial balance was worked out

Worked by hand from the documents themselves, cross-checked against each fixture's `expected.json`. The app, the
API, the ledger, the posting code and the extractor were not run to produce or check any figure.
`ledgersync/accounts.py`, `ledgersync/posting.py` and `ledgersync/matching.py` were read only for the chart and the
posting and matching conventions.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Northbridge Consulting Ltd | The invoice is billed to "Northbridge Consulting Ltd", so it is a purchase. The Starling statement receives "INV NB-0112", Northbridge's own invoice numbering. |
| Business type | `limited_company` | "Ltd". |
| VAT registered | yes | Northbridge pays HMRC VAT elsewhere in the fixture set (`csv-barclays-export`, `text-hmrc-vat-payment`). Here that means the invoice's VAT is reclaimed. |
| Contact email | northbridge-invoices@example.com | Reserved test domain. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027. The statement runs 01/09 to 23/09/2026 and the invoice is dated 08/09/2026. |

## Documents

| File | Copied from | What it is |
|---|---|---|
| `documents/clearway-invoice.pdf` | `eval/fixtures/pdf-purchase-invoice/input.pdf` | Clearway Office Supplies Ltd invoice CW-20931, 08/09/2026: net 250.00, VAT 50.00, total 300.00 |
| `documents/starling-september.csv` | `eval/fixtures/csv-starling/input.csv` | Starling CSV: opening balance 3,200.00 and 4 lines with running balances |

## Conventions used (from accounts.py, posting.py and matching.py)

- An invoice is owed until a bank line pays it. A purchase invoice's other side is 2100 Creditors, and its VAT goes
  to 2201 when shown.
- A bank line pays an invoice only if it is the same way and dated on or after the invoice, within 31 days. Then it
  posts against 2100 with no VAT, clearing the creditor.
- A bank line that pays no document posts to its own account against 1200 Bank, with no VAT, because a bank line
  shows none.
- The trial balance holds transactions only. A statement's opening balance is used to check the statement, not
  booked.

## Rows and their double entry

| # | Date | Source | Description | Way | Gross | VAT shown | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 08/09/2026 | Clearway invoice | Clearway Office Supplies Ltd, CW-20931: paper 45.00, toner 165.00, desk organisers 40.00 | out | 300.00 | 50.00 | 7504 Office Stationery | 7504 250.00; 2201 50.00 | 2100 300.00 |
| 2 | 03/09/2026 | Starling | WeWork, desk rental September | out | 295.00 | none | 7100 Rent | 7100 295.00 | 1200 295.00 |
| 3 | 07/09/2026 | Starling | Hartley & Co, Invoice 2026-288 | out | 360.00 | none | 7601 Accountancy Fees | 7601 360.00 | 1200 360.00 |
| 4 | 15/09/2026 | Starling | Brightwell Ltd, INV NB-0112 | in | 2100.00 | none | 4000 Sales | 1200 2100.00 | 4000 2100.00 |
| 5 | 23/09/2026 | Starling | Avanti West Coast, rail | out | 64.30 | none | 7400 Travel | 7400 64.30 | 1200 64.30 |

The Starling "Opening Balance" line (01/09/2026, amount 0.00, balance 3,200.00) is not a transaction.

Row 1's VAT: 45.00 + 165.00 + 40.00 = 250.00 net. VAT at 20% on that is 50.00, and the total is 300.00, all as
printed. Also, 300.00 × 20/120 = 50.00.

Every row balances: row 1 is 250.00 + 50.00 = 300.00 against 300.00, and rows 2 to 5 have one debit and one credit of
the same amount.

**Does any bank line pay the invoice?** No.

| Line | Why it can't pay the invoice |
|---|---|
| WeWork (03/09) | Dated before the invoice, a different payee, and 295.00 ≠ 300.00. |
| Hartley & Co (07/09) | Dated before the invoice, a different payee, and 360.00 ≠ 300.00. |
| Brightwell (15/09) | Money in, so it is the wrong way. |
| Avanti (23/09) | A different payee, and 64.30 ≠ 300.00. |

So the invoice is still owed at 30/09: 2100 Creditors stays at −300.00.

**Statement check:**

| From | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 3,200.00 | |
| WeWork | −295.00 | 2,905.00 | ✓ |
| Hartley & Co | −360.00 | 2,545.00 | ✓ |
| Brightwell | +2,100.00 | 4,645.00 | ✓ |
| Avanti | −64.30 | 4,580.70 | ✓ |

The statement reconciles. Its movement is 4,580.70 − 3,200.00 = +1,380.70, which is 1200's net below.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | 2100.00 (row 4) | 295.00 + 360.00 + 64.30 = 719.30 | **1380.70** |
| 2100 Creditors | | 300.00 (row 1) | **-300.00** |
| 2201 Purchase VAT | 50.00 (row 1) | | **50.00** |
| 4000 Sales | | 2100.00 (row 4) | **-2100.00** |
| 7100 Rent | 295.00 (row 2) | | **295.00** |
| 7400 Travel | 64.30 (row 5) | | **64.30** |
| 7504 Office Stationery | 250.00 (row 1) | | **250.00** |
| 7601 Accountancy Fees | 360.00 (row 3) | | **360.00** |

Check: the debit nets are 1380.70 + 50.00 + 295.00 + 64.30 + 250.00 + 360.00 = 2400.00. The credit nets are
300.00 + 2100.00 = 2400.00. The expected trial balance sums to zero.

## Judgement calls

1. **No bank line clears the invoice, so it stays on 2100 Creditors.** The task brief describes this case as "a bank
   line clearing an open invoice through 2100 Creditors". The public fixtures can't show that, because no Starling
   line pays Clearway (see the table above). What the case tests is that an invoice unpaid at the year end stays
   in 2100 with its VAT reclaimed. A reading that links Hartley & Co's £360.00 (or any other line) to the Clearway
   invoice is wrong: that would move 2100 and 7601.
2. **Hartley & Co £360.00 goes to 7601 Accountancy Fees.** Hartley & Co are chartered accountants (see
   `pdf-scanned-invoice`), and the line names their invoice 2026-288. That invoice is not in the set; it may be one
   received before the period. No opening creditors are entered, so the payment is a cost when paid.
3. **Brightwell £2,100.00 in goes to 4000 Sales gross.** It pays Northbridge's own sales invoice NB-0112, which is
   not in the set. The bank line shows no VAT, so none is split out.
4. **The whole Clearway invoice goes to 7504 Office Stationery.** Paper, toner (ink) and desk organisers are all
   small office supplies. The invoice prints one VAT total, so it is one row.
5. **WeWork £295.00 goes to 7100 Rent with no VAT.** It is desk rental for premises. VAT may well be charged, but
   no VAT invoice is in the set, and a bank line books none.
6. **The opening balance of £3,200.00 is not booked.** No opening balances are entered, so the trial balance holds the year's transactions only, so
   1200 shows the movement (+1,380.70), not the closing balance (4,580.70).

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`).

| Account | Old | New | Rule |
|---|---|---|---|
| 7100 Rent | 295.00 | 0.00 (left out) | WeWork (row 2): £50 or more with no document, and over £250 so it needs a full VAT invoice: held in 9998. |
| 7601 Accountancy Fees | 360.00 | 0.00 (left out) | Hartley & Co (row 3): £50 or more with no document (over £250): held in 9998. |
| 7400 Travel | 64.30 | 0.00 (left out) | Avanti West Coast (row 5): £50 or more with no document: held in 9998. |
| 9998 Suspense | none | 719.30 | The three rows above, 295.00 + 360.00 + 64.30. |

The Clearway invoice is a document, so it books and reclaims its VAT as before (7504 250.00, 2201 50.00, 2100 -300.00).
The sale is money in.
