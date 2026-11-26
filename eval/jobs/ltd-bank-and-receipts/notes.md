# ltd-bank-and-receipts: how the expected trial balance was worked out

Worked by hand from the documents themselves, cross-checked against each fixture's `expected.json`. The app, the
API, the ledger, the posting code and the extractor were not run to produce or check any figure.
`ledgersync/accounts.py` and `ledgersync/posting.py` were read only for the chart and the posting conventions.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Northbridge Consulting Ltd | Every public fixture is written from Northbridge's point of view (`eval/eval_cases.py`). No document here names the business. |
| Business type | `limited_company` | The case is a limited company. |
| VAT registered | yes | The Barclays export pays HMRC VAT (27/09, £1,210.33), so the business makes VAT returns. |
| Contact email | northbridge-bank-receipts@example.com | Reserved test domain: a document request can't reach anyone. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027, and every document, dated 02/09/2026 to 27/09/2026, is in it. |

## Documents

| File | Copied from | What it is |
|---|---|---|
| `documents/barclays-september.csv` | `eval/fixtures/csv-barclays-export/input.csv` | Barclays CSV export: 6 lines, no balances |
| `documents/tesco-receipt.txt` | `eval/fixtures/text-tesco-receipt/input.txt` | Tesco Express till receipt, 03/09/2026, £12.50, paid in cash; VAT number printed, no VAT amount |
| `documents/cafe-receipt.png` | `eval/fixtures/img-cafe-receipt-vat/input.png` | The Daily Grind Cafe receipt, 12/09/2026, £7.50 incl. VAT £1.25, paid by card |

## Conventions used (from accounts.py and posting.py)

- A bank line posts against 1200 Bank Current Account. A receipt is paid when it is issued, so its other side is
  1200 Bank too, unless the statement has lines either side of its day and no payment of it: then the bank did
  not pay it, and it waits in 9998 Suspense until a person says what did (the two receipts here).
- VAT is booked only when the document shows it. It goes to 2201 Purchase VAT on a cost, and the net goes to the
  cost account. A bank line shows no VAT, so it books none.
- Liability accounts (2202) take no VAT.
- Net = debit minus credit, so a credit balance is negative.

## Rows and their double entry

| # | Date | Source | Description | Way | Gross | VAT shown | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 02/09/2026 | Barclays | VODAFONE LTD | out | 45.99 | none | 7502 Telephone and Internet | 7502 45.99 | 1200 45.99 |
| 2 | 10/09/2026 | Barclays | STAPLES UK | out | 32.40 | none | 7504 Office Stationery | 7504 32.40 | 1200 32.40 |
| 3 | 13/09/2026 | Barclays | BRIGHTWELL LTD | in | 950.00 | none | 4000 Sales | 1200 950.00 | 4000 950.00 |
| 4 | 18/09/2026 | Barclays | ROYAL MAIL | out | 15.60 | none | 7501 Postage and Carriage | 7501 15.60 | 1200 15.60 |
| 5 | 22/09/2026 | Barclays | PREMIER INN | out | 89.00 | none | 7402 Hotels | 7402 89.00 | 1200 89.00 |
| 6 | 27/09/2026 | Barclays | HMRC VAT | out | 1210.33 | none | 2202 VAT Liability | 2202 1210.33 | 1200 1210.33 |
| 7 | 03/09/2026 | Tesco receipt | Tesco Express (meal deal, coffee, sandwich) | out | 12.50 | none | 7406 Subsistence | 7406 12.50 | 9998 12.50 |
| 8 | 12/09/2026 | Cafe receipt | The Daily Grind Cafe (flat white, croissant, water) | out | 7.50 | 1.25 | 7406 Subsistence | 7406 6.25; 2201 1.25 | 9998 7.50 |

Row 8's VAT: £7.50 × 20/120 = £1.25, which is exactly what the receipt prints, so it is booked as shown. The net is
£7.50 − £1.25 = £6.25.

Every row balances: rows 1 to 7 have one debit and one credit of the same amount, and row 8 has 6.25 + 1.25 = 7.50
against 7.50.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | 950.00 (row 3) | 45.99 + 32.40 + 15.60 + 89.00 + 1210.33 = 1393.32 | **-443.32** |
| 9998 Suspense | | 12.50 (row 7) + 7.50 (row 8) = 20.00, the receipts the bank did not pay | **-20.00** |
| 2201 Purchase VAT | 1.25 (row 8) | | **1.25** |
| 2202 VAT Liability | 1210.33 (row 6) | | **1210.33** |
| 4000 Sales | | 950.00 (row 3) | **-950.00** |
| 7402 Hotels | 89.00 (row 5) | | **89.00** |
| 7406 Subsistence | 12.50 (row 7) + 6.25 (row 8) = 18.75 | | **18.75** |
| 7501 Postage and Carriage | 15.60 (row 4) | | **15.60** |
| 7502 Telephone and Internet | 45.99 (row 1) | | **45.99** |
| 7504 Office Stationery | 32.40 (row 2) | | **32.40** |

The 1200 credits added step by step: 45.99, then 78.39, 93.99, 182.99 and 1393.32.

Check: the debit nets are 1.25 + 1210.33 + 89.00 + 18.75 + 15.60 + 45.99 + 32.40 = 1413.32. The credit nets are
443.32 + 20.00 + 950.00 = 1413.32. The expected trial balance sums to zero. (In the expected file 9998 is 69.00:
the hotel's 89.00, held there for its invoice, less this 20.00.)

## Judgement calls

1. **No receipt is matched to a card payment.** This case can't test that, because neither receipt has a bank
   line. The Tesco receipt was paid in cash (CASH 20.00, CHANGE 7.50). The cafe's £7.50 card payment is not in the
   Barclays export: there is no £7.50 line, and nothing for £12.50 either. The right result is that each receipt is
   booked on its own and no bank line is paired with it. A receipt linked to a bank line here is wrong.
2. **Neither receipt is booked against 1200 Bank.** The statement has lines either side of each receipt's day and
   no payment of it, so the bank did not pay it. Both wait in 9998 Suspense with a note, and 1200 agrees with the
   statement's own movement: 950.00 − 1393.32 = −443.32. A person reviewing chooses Paid from on each row: 1230
   Petty Cash for the cash receipt, or 2250 Director's Loan Account if the director paid.
   That is a person's call, so it is not expected here.
3. **Tesco: no VAT is booked.** The receipt prints a VAT number but no VAT amount, and VAT is reclaimable only when
   shown. Much of a meal deal is zero-rated anyway. VAT is never added to a document that shows none.
4. **Tesco and the cafe go to 7406 Subsistence.** Both are food and drink bought while working: one person's meal,
   not client hospitality, so not 7403 Entertainment. This agrees with both fixtures' `expected.json`.
5. **BRIGHTWELL LTD £950.00 in goes to 4000 Sales gross.** The sales invoice it pays is not in the set, and the
   bank line shows no VAT, so none is split out.
6. **HMRC VAT £1,210.33 goes to 2202 VAT Liability.** It is a VAT return payment, not a cost, and a liability
   account takes no VAT.
7. No opening balance: the Barclays export prints none, and no opening balances are entered, so the trial balance holds the year's transactions only.

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`), so the expected figures
below were reworked by hand from the rows above.

| Account | Old | New | Rule |
|---|---|---|---|
| 7402 Hotels | 89.00 | 0.00 (left out) | Premier Inn (row 5): a bank line of £50 or more with no document is held in 9998 Suspense. |
| 9998 Suspense | none | 89.00 | The same row, held. |

Nothing else moves. The cafe receipt prints "VAT Reg No 318 4471 92" and VAT £1.25, so the VAT is still reclaimed (2201
stays 1.25; 7406 stays 18.75). The reading in `tests/test_eval_cases.py` now gives that number as `supplier_vat_number`,
as a good reading of the receipt does: without it a receipt's VAT is kept in the cost. Tesco shows no VAT, so nothing
changes there. Rows 1, 2 and 4 are bank lines under £50: booked, and a bank line shows no VAT to reclaim anyway.
