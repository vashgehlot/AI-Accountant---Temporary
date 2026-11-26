# Northbridge demo: how the expected figures were worked out

The directors' demo client (the spec's "The demo, in order"):
- `existing/` holds September, already read, which the reset loads.
- `documents/` holds October, dropped into the chat.
- `answers/` holds the Brightline invoice, uploaded in answer to the £240 question.

**The review sorts five things:**
- a duplicate (R2);
- an amount conflict (R4);
- a mixed-VAT split (R3);
- VAT from an invoice (R5);
- a date from the bank (R1).

**It asks two questions:** the undated taxi, and the £240 payment with no invoice.

**It posts a balanced trial balance with £240.00 in Suspense.** After the answers, the £240 leaves Suspense.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the rows (`checks.normalise`, `matching.match` with the opening unpaid invoices, `evidence_rules`,
`posting.summarise` with the opening balances), without MongoDB or a model:
- each resolution's own check (`_keep_one`, `_use_primary`, `_vat_from_document`, and R3's sums) passed;
- every evidence quote is in its document's text;
- both trial balances agreed to the penny;
- nothing was changed to fit.

## Client and year

| Setting | Value |
|---|---|
| Name | Northbridge Consulting Ltd |
| Business type | `limited_company`; director Jamie North (the "J NORTH" lines) |
| VAT registered | yes |
| First year | 1 Apr 2026 to 31 Mar 2027 (`first_year_end` 2027-03-31) |
| Bank | one Barclays current account, code 1200 |
| Contact | jamie.north@example.com (a reserved test domain) |

## Opening balances at 1 Apr 2026 (`opening_balances.json`)

| Account | Debit | Credit |
|---|---|---|
| 0030 Office Equipment | 3,200.00 | |
| 0031 Office Equipment Depreciation | | 1,100.00 |
| 1100 Debtors | 6,000.00 | |
| 1200 Bank Current Account | 12,450.00 | |
| 2250 Director's Loan Account | | 1,500.00 |
| 2320 Corporation Tax | | 2,850.00 |
| 3000 Ordinary Shares | | 100.00 |
| 3200 Retained Earnings | | 16,100.00 |
| **Total** | **21,650.00** | **21,650.00** |

Behind Debtors, two unpaid sales invoices (`unpaid`):
- NB-1031, Brightwell Ltd, £3,600.00;
- NB-1032, Harbour & Lane Ltd, £2,400.00.

They add up to 6,000.00, as `books.check_opening` requires. `books` dates them 31 Mar 2026, the day before the
year.

## Documents

### September, already read (`existing/`)

| Upload | Rows |
|---|---|
| `barclays-september.csv` (statement, 1200) | 01/09 HARBOUR & LANE LTD in 2,400.00; 04/09 BT GROUP PLC 42.00; 11/09 STAPLES UK 23.94; 15/09 PREMIER INN 96.00; 25/09 XERO UK 36.00; 30/09 BARCLAYS ACCOUNT FEE 8.50 |
| `staples-receipt-10-09.txt` | Staples UK, 10/09/2026, notebooks and pens £23.94 incl. VAT £3.99, VAT number |
| `premier-inn-receipt-15-09.txt` | Premier Inn Leeds City Centre, 15/09/2026, one night £96.00 incl. VAT £16.00, VAT number |

### October, dropped into the chat (`documents/`)

| File | What it is |
|---|---|
| `barclays-october.csv` | 9 lines, listed below. Barclays' export prints no balances |
| `parking-photo.png` | NCP ticket, Leeds Wellington Street, **no date**, £6.50 incl. VAT £1.08, VAT number |
| `costco-receipt-21-10.txt` | Costco Wholesale UK Ltd, 21/10/2026, **VAT number GB 999 4021 87**. Copier paper 24.00 A, box files 12.00 A, milk 1.65 Z, coffee 14.00 Z, tea 6.35 Z. TOTAL 58.00 by Visa debit. VAT analysis: "A 20.00% 30.00 6.00 36.00", "Z 0.00% 22.00 0.00 22.00" |
| `inkwell-invoice-INK-4471.pdf` | Inkwell Supplies Ltd, invoice INK-4471, 07/10/2026, VAT number. 2 × HP 305XL at 12.59 = 25.18. "Subtotal: £25.18", "VAT at 20%: £5.04", "Total due: £30.22" |
| `staff-expenses-october.xlsx` | Priya Shah's October sheet, no total row: 07/10 "Inkwell - printer ink" **27.50**; 16/10 "Mileage - client visit York, 50 miles at 45p" 22.50; 21/10 "Costco - office supplies and kitchen" 58.00 |
| `IMG_20261009_081502.png` | Leeds City Cabs, Leeds Station to Kirkstall, £18.00, paid cash, **no date**, no VAT |

`answers/brightline-invoice-BP-2210.pdf`: Brightline Print Ltd, invoice BP-2210, 19/10/2026, VAT number. Business
cards 80.00 + A5 brochures 120.00. "Subtotal: £200.00", "VAT at 20%: £40.00", "Total: £240.00", "Paid by bank
transfer".

The figures inside the documents:
- **Costco:** A 24.00 + 12.00 = 36.00, and VAT 36.00 × 1/6 = 6.00 exactly. Z 1.65 + 14.00 + 6.35 = 22.00. Total
  36.00 + 22.00 = 58.00.
- **Inkwell:** 25.18 × 20% = 5.036, which is 5.04. Then 25.18 + 5.04 = 30.22, and 30.22 × 1/6 = 5.0367, which is
  5.04.
- **Mileage:** 50 × £0.45 = £22.50.

## As read

Each document's `.rows.json` holds its reading.
- **Costco:** read as **one row**, £58.00, VAT £6.00, on 7504, with `mixed_items`. `normalise` words it "VAT £6.00
  is on £36.00; £22.00 has none".
- **Inkwell:** read as one row, £30.22 on 7504, with **`vat: null`** (the reading missed the VAT line). It has
  `document_net` 25.18 and `document_total` 30.22. This is the demo's "VAT from an invoice".
  - **With a model reading** (`run_agent_eval.py --read model`, or the app reading the PDF itself), the model reads
    the VAT line: 5.04 in 16 of 16 reads, over 4 realistic layouts of this invoice (tried 2026-11-04). So R5 does
    not come up there, and the eval scores the expected R5 as `already_in_reading`, not as a failure. R5 still runs
    live with `--read rows` and in the scripted demo, which both use this `.rows.json`. The user chose to keep it
    this way (2026-11-06) rather than restage it.
- **The sheet's lines:** each is an `expense_claim` row with counterparty Priya Shah, owed on 2110.

## What the books show before the agent acts

`matching`, with no decision yet:
- **Costco:** the sheet line and the receipt have the same £58.00, the same day and the same shop. So the receipt
  becomes the claim's, owed to Priya on 2110. The Barclays COSTCO WHOLESALE £58.00 line is then left unpaired
  (a `possible_payment` towards the sheet line), and is **held in Suspense** as a bank line of £50 or more. It
  warns `booked_twice`: "Also booked from the expenses sheet's receipt (Costco Wholesale UK Ltd, £58.00, 21 Oct
  2026). If this line paid it, drop the expenses sheet line: this line then pays the receipt."
- **Inkwell:** the sheet line (£27.50) and the invoice (£30.22) are from the same shop on the same day. Both get
  `amount_conflict`. The invoice is held, and the sheet line is booked. INKWELL SUPPLIES £30.22 on 12/10 then has
  no invoice to pay, so it is booked as a cost (under £50). The invoice also warns `vat_not_booked`: "The invoice
  shows £5.04 VAT; none is booked."
- **Parking:** the undated ticket and NCP LEEDS £6.50 match only each other, so the ticket is dated 14/10 from the
  bank (`date_from_bank`).
- **Taxi:** no date and no £18.00 line, so it gets `date_missing`. Its file name also gives a `file_date`
  `date_found` of 9 Oct (see "Needs a check").

The trial balance at that point (checked with the services):
- 9998 is 298.00 (Costco 58.00 + Brightline 240.00);
- 7504 is 129.67;
- 2110 is −108.00;
- 2201 is 27.07.

## The decisions, in order

**1. R2 keep_one** ("R2 Duplicate: kept the receipt"):
- keep "Costco: copier paper, box files, milk, coffee and tea" (receipt);
- drop the sheet line "Costco - office supplies and kitchen".

The sheet line is `recorded_by` the receipt, and the receipt ranks 3 to the sheet's 1. The evidence is "TOTAL
58.00" (receipt) and "Costco - office supplies and kitchen" (sheet). With the sheet line `excluded`, the Barclays
COSTCO WHOLESALE £58.00 (21/10) pairs with the receipt: the same amount and day, and "COSTCO" matches "Costco
Wholesale UK Ltd". So the line is not booked.

**2. R3 split_vat** ("R3 Mixed VAT: split by rate") on the same receipt:
- "Copier paper and box files": 7504, 36.00, standard, VAT 6.00;
- "Milk, coffee and tea for the office": 8205, 22.00, zero, VAT 0.00.

The parts are 36.00 + 22.00 = 58.00, the row's gross. Their VAT is 6.00 + 0.00 = 6.00, the row's VAT. The
evidence is "A 20.00% 30.00 6.00 36.00" and "Z 0.00% 22.00 0.00 22.00". The parts keep the receipt's
`document_ref`, so they still pair with the bank line.

**3. R4 use_primary** ("R4 Conflict: used the invoice"):
- primary "Inkwell: HP 305XL black ink cartridges x2" (invoice);
- other the sheet line "Inkwell - printer ink".

The `amount_conflict` issue links them, and the invoice ranks 3 to 1. The evidence is "Total due: £30.22"
(invoice) and "Inkwell - printer ink" (sheet). The sheet line is `excluded`. INKWELL SUPPLIES £30.22 on 12/10 (on
or after 07/10, "INKWELL SUPPLIES" matches "Inkwell Supplies Ltd") then pays the invoice exactly.

**4. R5 set_vat_from_document** ("R5 VAT from the document") on the invoice, `vat` 5.04:
- 5.04 is at most `vat_in_gross(30.22)` = 5.04;
- 7504 is an expense account;
- "5.04" is printed in the invoice.

The evidence is "VAT at 20%: £5.04".

**5. R1 Date from the bank** (automatic, `record_automatic`, actor `rules`): the parking ticket is dated
2026-10-14 from NCP LEEDS £6.50, with "NCP LEEDS" as the evidence.

R2 must come before R3. After R3, the receipt row is superseded, and `keep_one` would have to name a part. R4 and
R5 can come in either order.

## Rows and their double entry, before the answers

| # | Date | Description | Gross | Rule | Debit | Credit |
|---|---|---|---|---|---|---|
| S1 | 01/09 | HARBOUR & LANE LTD (in) | 2,400.00 | pays opening invoice NB-1032 exactly; money in, exempt | 1200 2,400.00 | 1100 2,400.00 |
| S2 | 04/09 | BT GROUP PLC | 42.00 | under £50 | 7502 42.00 | 1200 42.00 |
| S3 | 10/09 | Staples: A4 notebooks and pens (receipt; STAPLES UK 11/09 records it, not booked) | 23.94 | receipt, VAT number: reclaim 3.99 | 7504 19.95; 2201 3.99 | 1200 23.94 |
| S4 | 15/09 | Premier Inn Leeds City Centre (receipt; PREMIER INN 15/09 records it, not booked) | 96.00 | receipt, VAT number: reclaim 16.00 | 7402 80.00; 2201 16.00 | 1200 96.00 |
| S5 | 25/09 | XERO UK | 36.00 | under £50 | 8201 36.00 | 1200 36.00 |
| S6 | 30/09 | BARCLAYS ACCOUNT FEE | 8.50 | under £50 | 7901 8.50 | 1200 8.50 |
| O1 | 02/10 | BRIGHTWELL LTD (in) | 3,600.00 | pays opening invoice NB-1031 exactly; exempt | 1200 3,600.00 | 1100 3,600.00 |
| O2 | 05/10 | BT GROUP PLC | 42.00 | under £50 | 7502 42.00 | 1200 42.00 |
| O3 | 07/10 | Inkwell invoice INK-4471 (after R4, R5) | 30.22 | invoice: reclaim | 7504 25.18; 2201 5.04 | 2100 30.22 |
| O4 | 12/10 | INKWELL SUPPLIES | 30.22 | pays O3; exempt | 2100 30.22 | 1200 30.22 |
| O5 | 14/10 (R1, from the bank) | NCP parking ticket (NCP LEEDS 14/10 records it, not booked) | 6.50 | receipt, VAT number: reclaim 1.08 | 7400 5.42; 2201 1.08 | 1200 6.50 |
| O6 | 15/10 | J NORTH DIRECTOR LOAN | 400.00 | 2250, exempt | 2250 400.00 | 1200 400.00 |
| O7a | 21/10 | Costco part: copier paper and box files | 36.00 | receipt part, VAT number: reclaim 6.00 | 7504 30.00; 2201 6.00 | 1200 36.00 |
| O7b | 21/10 | Costco part: milk, coffee and tea | 22.00 | no VAT on this part | 8205 22.00 | 1200 22.00 |
| O8 | 22/10 | BRIGHTLINE PRINT | 240.00 | **£50–£250, no document: hold** | 9998 240.00 | 1200 240.00 |
| O9 | 26/10 | XERO UK | 36.00 | under £50 | 8201 36.00 | 1200 36.00 |
| O10 | 30/10 | BARCLAYS ACCOUNT FEE | 8.50 | under £50 | 7901 8.50 | 1200 8.50 |
| O11 | 16/10 | Mileage - client visit York (sheet) | 22.50 | sheet line under £50: book, no VAT | 7400 22.50 | 2110 22.50 |
| O12 | none | Leeds City Cabs taxi (receipt, cash) | 18.00 | under £50, no VAT shown | 7400 18.00 | 1200 18.00 (9998 once it is dated: the bank did not pay it) |

These rows are not booked:
- the Costco receipt row (superseded by R3);
- the sheet's Costco and Inkwell lines (excluded by R2 and R4);
- the bank lines STAPLES UK, PREMIER INN, NCP LEEDS and COSTCO WHOLESALE (each recorded by its receipt).

The VAT on the September receipts:
- Staples: 23.94 × 1/6 = 3.99, as printed; net 19.95.
- Premier Inn: 96.00 × 1/6 = 16.00, as printed; net 80.00.

The undated taxi is booked, and waits in the year it was added to.

## Questions after the review

| Row | Kind | Why |
|---|---|---|
| Leeds City Cabs taxi, Leeds Station to Kirkstall | `date` | "£18.00, no date on it and no matching bank line." |
| BRIGHTLINE PRINT | `receipt_or_invoice` | "£240.00 to Brightline Print on 22 Oct 2026. £50 or more, so I need it. Held in Suspense as Documentation required until then." |

Nothing else is asked.
- **Parking:** dated from the bank.
- **Costco and Inkwell:** settled by documents.
- **The mileage, BT, Xero and the fees:** under £50.
- **The director's loan and the money in:** exempt.

## Trial balance before the answers (`expected_trial_balance_before_answers.json`)

| Account | Opening | Movements | Net |
|---|---|---|---|
| 0030 Office Equipment | 3,200.00 | | **3,200.00** |
| 0031 Office Equipment Depreciation | −1,100.00 | | **−1,100.00** |
| 1100 Debtors | 6,000.00 | −2,400.00 − 3,600.00 | 0.00 (no line) |
| 1200 Bank Current Account | 12,450.00 | +6,000.00 − 206.44 − 839.22 | **17,404.34** |
| 2100 Creditors | | −30.22 + 30.22 | 0.00 (no line) |
| 2110 Expenses Owed to Staff | | −22.50 | **−22.50** |
| 2201 Purchase VAT | | 3.99 + 16.00 + 5.04 + 1.08 + 6.00 | **32.11** |
| 2250 Director's Loan Account | −1,500.00 | +400.00 | **−1,100.00** |
| 2320 Corporation Tax | −2,850.00 | | **−2,850.00** |
| 3000 Ordinary Shares | −100.00 | | **−100.00** |
| 3200 Retained Earnings | −16,100.00 | | **−16,100.00** |
| 7400 Travel | | 5.42 + 22.50 + 18.00 | **45.92** |
| 7402 Hotels | | 80.00 | **80.00** |
| 7502 Telephone and Internet | | 42.00 + 42.00 | **84.00** |
| 7504 Office Stationery | | 19.95 + 25.18 + 30.00 | **75.13** |
| 7901 Bank Charges | | 8.50 + 8.50 | **17.00** |
| 8201 Subscriptions and Software | | 36.00 + 36.00 | **72.00** |
| 8205 Refreshments | | 22.00 | **22.00** |
| 9998 Suspense | | 240.00 | **240.00** |

**1200, step by step:**
- Money in: 2,400.00 + 3,600.00 = 6,000.00.
- September's money out (booked): 42.00 + 23.94 + 96.00 + 36.00 + 8.50 = 206.44.
- October's money out (booked): 42.00 (BT) + 30.22 (Inkwell) + 6.50 (NCP ticket) + 400.00 (J North) + 36.00 +
  22.00 (Costco parts) + 240.00 (Brightline) + 36.00 (Xero) + 8.50 (fee) + 18.00 (taxi) = 839.22. Added up: 42.00,
  then 72.22, 78.72, 478.72, 514.72, 536.72, 776.72, 812.72, 821.22 and 839.22.
- 12,450.00 + 6,000.00 − 206.44 − 839.22 = **17,404.34**.

**Against the statements:**
- September moves +2,400.00 − 206.44 = +2,193.56.
- October moves +3,600.00 − (42.00 + 30.22 + 6.50 + 400.00 + 58.00 + 240.00 + 36.00 + 8.50) = +3,600.00 − 821.22 =
  +2,778.78.
- From 12,450.00, the bank's own figure is 17,422.34. Before the answers the books are £18.00 lower: the cash
  taxi has no date yet and is booked against 1200. Once it is dated, the books agree (judgement 2).

**Check:**
- The debit nets are 3,200.00 + 17,404.34 + 32.11 + 45.92 + 80.00 + 84.00 + 75.13 + 17.00 + 72.00 + 22.00 + 240.00
  = **21,272.50**. Added up: 20,604.34, then 20,636.45, 20,682.37, 20,762.37, 20,846.37, 20,921.50, 20,938.50,
  21,010.50, 21,032.50 and 21,272.50.
- The credit nets are 1,100.00 + 22.50 + 1,100.00 + 2,850.00 + 100.00 + 16,100.00 = **21,272.50**.
- It balances.

The posted trial balance's `suspense` list holds one item: BRIGHTLINE PRINT, £240.00, needs `receipt_or_invoice`.

## Answers

1. **The taxi date: 8 Oct 2026** ("R1 Date from the person", actor `user`). It changes no figure. The photo's
   name says 9 Oct, the morning after, and is not used.
2. **The Brightline invoice is uploaded** (`answers/brightline-invoice-BP-2210.pdf`):
   - Invoice BP-2210, 19/10/2026, Brightline Print Ltd, £240.00 incl. VAT £40.00, VAT number. It goes to 7500
     Printing, against 2100.
   - BRIGHTLINE PRINT £240.00 on 22/10 is on or after the invoice, for exactly what it owes, and "BRIGHTLINE
     PRINT" matches "Brightline Print Ltd". So the line pays the invoice and is no longer covered by the rules.
   - At the next post, the line's Suspense entries are reversed and its new lines posted:
     - the reversal: Dr 1200 240.00, Cr 9998 240.00;
     - the payment: Dr 2100 240.00, Cr 1200 240.00;
     - the invoice: Dr 7500 200.00, Dr 2201 40.00, Cr 2100 240.00.
   - The question resolves.

```json
[
  {"question": {"kind": "date", "row": {"file": "IMG_20261009_081502.png",
                                        "description": "Leeds City Cabs taxi, Leeds Station to Kirkstall"}},
   "answer": {"kind": "date", "date": "2026-10-08"}},
  {"question": {"kind": "receipt_or_invoice", "row": {"file": "barclays-october.csv", "description": "BRIGHTLINE PRINT"}},
   "answer": {"kind": "upload", "file": "answers/brightline-invoice-BP-2210.pdf"}}
]
```

## Trial balance after the answers (`expected_trial_balance_after_answers.json`)

These accounts change from the table above:

| Account | Before | Change | After |
|---|---|---|---|
| 2100 Creditors | 0.00 | −240.00 (invoice) + 240.00 (payment) | 0.00 (no line) |
| 2201 Purchase VAT | 32.11 | +40.00 | **72.11** |
| 7500 Printing | — | +200.00 | **200.00** |
| 9998 Suspense | 240.00 | −240.00 | 0.00 (no line) |

1200 is unchanged at 17,404.34: the £240 still left the bank once.

**Check:** the debit nets are 21,272.50 − 240.00 + 40.00 + 200.00 = **21,272.50**, and the credit nets are
unchanged at **21,272.50**. It balances. Nothing is left in Suspense, and no question is open.

## Needs a check

1. **The Costco purchase is booked twice.** Done in Task 8: `matching` warns `booked_twice` on an unpaired bank
   line whose amount, shop and day equal a receipt that a claim line records, pointing at the receipt and the
   claim line.
   - Before R2, the receipt is the sheet's (2110) and the COSTCO WHOLESALE line is booked too, into Suspense.
     Before the check, only a `possible_payment` hint linked them.
   - If the agent misses it, the review asks a **third** question: a receipt for COSTCO WHOLESALE £58.00, which
     is already uploaded. The demo would look like a junior.
   - See also `eval/agent_cases/duplicate-receipt-spreadsheet/notes.md`: R2 there is only right because the card
     paid.
2. **The Inkwell invoice has no VAT booked.** It is read with `vat: null` while its `document_total` (30.22) and
   `document_net` (25.18) differ by 5.04 = 30.22 × 1/6. Done in Task 8: `checks.normalise` warns `vat_not_booked`
   (see `vat-on-invoice-missing-from-entry/notes.md`).
3. **The taxi's file name date lands in `date_found`.**
   - `books._saved_rows` runs `file_dates.check_file_date`, which sets the taxi's `date_found` to 2026-10-09
     with a `file_date` warning.
   - `questions.refresh` must still ask for the date: only a bank line's `date_found` counts. Otherwise the demo
     loses its date question.
   - See `missing-date-must-ask/notes.md`.
4. **The order of decisions.** R2 must come before R3 on the Costco receipt, so the scripted run applies them in
   the listed order. A real model might split first and then try `keep_one` on the original row, which is
   superseded by then, so R2 is refused. The prompt or `keep_one` could accept a split's part as the kept row.
5. **Uploading the answer.** The runner's answers go through `questions.answer`, which has no upload answer.
   Here the upload means:
   - `add_upload` of the invoice's rows (with `year_start` 2026-04-01);
   - then `questions.refresh` and `ledger_book.post`.

   This is Task 10's document route without the HTTP.

## Judgement calls

1. **Costco and Inkwell were paid from Barclays, and the sheet repeats them.**
   - This is the reading in which the spec's "duplicate" and "amount conflict" are right to resolve with R2 and
     R4.
   - Had Priya paid them, the sheet lines would be what she is owed, and excluding them would be wrong.
   - The bank statement shows both payments, so the sheet is a log of office spending, not a claim for them.
   - The mileage line is a genuine claim: no bank line pays it, and it stays owed on 2110 (−22.50).
2. **The cash taxi is kept off the bank once it has a date.** The statement has lines either side of 8 Oct and no
   £18.00, so 1200 did not pay it: it waits in 9998 Suspense (−18.00) with a note, and 1200 agrees with the
   statements. A person then chooses Paid from on the row (the director, or petty cash). Not expected here.
3. **Money in pays the opening invoices.** BRIGHTWELL £3,600.00 and HARBOUR & LANE £2,400.00 each pay their
   brought-forward invoice exactly. So Debtors clears to nil, and no `sale_without_vat` warning is raised (a
   paying line has no sale of its own).
4. **No bank movements April to August.** The demo's books hold only September and October on top of the opening
   balances. The opening bank balance (12,450.00) is taken as the balance on 1 Sep, so that the books agree with
   the statements but for the taxi. The Barclays export prints no balances, so `check_statement` has nothing to
   compare (status "none").
5. **Accounts:**
   - Costco's stationery goes to 7504, and its milk, coffee and tea to 8205 (zero-rated);
   - the ink goes to 7504;
   - the parking, taxi and mileage go to 7400;
   - the hotel goes to 7402;
   - Xero goes to 8201;
   - the Brightline print goes to 7500 Printing;
   - the director's £400 goes to 2250.
6. **The taxi date answer is 8 Oct, not the file name's 9 Oct.** The two differ on purpose, so the run shows the
   date came from the person.
