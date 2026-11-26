# sole-trader-expense-claim: how the expected trial balance was worked out

Worked by hand from the documents themselves, cross-checked against each fixture's `expected.json`. The app, the
API, the ledger, the posting code and the extractor were not run to produce or check any figure.
`ledgersync/accounts.py`, `ledgersync/posting.py`, `ledgersync/checks.py` and `ledgersync/matching.py` were read
only for the chart and the posting conventions.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Sam Rivers | Neither document names the business. This is a test name for a sole trader trading under their own name. It shares no word with any counterparty, so the client's own name can't make the ledger pair two rows by name. |
| Business type | `sole_trader` | The case is a sole trader. The owner's personal spending goes through 3260 Drawings, not 2250 Director's Loan Account. |
| VAT registered | no | Neither document shows a VAT number, a VAT amount or a payment to HMRC. No document here shows VAT, so this changes no figure either way. |
| Contact email | sam.rivers@example.com | Reserved test domain. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027. The expense claim is dated 12/09/2026 and the bank lines run 01/10 to 28/10/2026. |

## Documents

| File | Copied from | What it is |
|---|---|---|
| `documents/expense-note.txt` | `eval/fixtures/text-expense-note-mixed/input.txt` | Expense claim, 12/09/2026: Breakfast £18.00, Taxi to client £32.00, Total £50.00 |
| `documents/bank-october.csv` | `eval/fixtures/csv-unseen-mixed/input.csv` | Bank CSV: 20 lines with running balances, 01/10 to 28/10/2026 |

## Conventions used (from accounts.py, posting.py, checks.py and matching.py)

- An expense claim's lines are owed to the claimant until paid. Their other side is 2110 Expenses Owed to Staff.
- A bank line posts to its account against 1200 Bank, with no VAT.
- Not VAT registered: no VAT is booked on anything.
- A bank line pays a claim only if it is the same way, dated on or after the claim within 31 days, and for its open
  amount (or names the claimant). No line here is for £50.00.

## Rows and their double entry

### The expense claim (other side 2110)

| # | Date | Description | Way | Gross | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|
| C1 | 12/09/2026 | Breakfast | out | 18.00 | 7406 Subsistence | 7406 18.00 | 2110 18.00 |
| C2 | 12/09/2026 | Taxi to client | out | 32.00 | 7400 Travel | 7400 32.00 | 2110 32.00 |

The lines total 18.00 + 32.00 = 50.00, which agrees with the printed "Total £50.00".

### The bank lines (other side 1200)

| # | Date | Description | Way | Gross | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|
| B1 | 01/10/2026 | ONBUY.COM - A4 COPIER PAPER | out | 32.40 | 7504 Office Stationery | 7504 32.40 | 1200 32.40 |
| B2 | 01/10/2026 | BRIGHTWATER DESIGN LTD INV 3107 | in | 3150.00 | 4000 Sales | 1200 3150.00 | 4000 3150.00 |
| B3 | 02/10/2026 | TRAVIS PERKINS | out | 86.30 | 7800 Repairs and Renewals | 7800 86.30 | 1200 86.30 |
| B4 | 03/10/2026 | GREGGS | out | 5.60 | 7406 Subsistence | 7406 5.60 | 1200 5.60 |
| B5 | 05/10/2026 | GUMTREE - SECOND-HAND OFFICE DESK | out | 120.00 | 0040 Furniture and Fixtures | 0040 120.00 | 1200 120.00 |
| B6 | 06/10/2026 | PLUSNET | out | 30.00 | 7502 Telephone and Internet | 7502 30.00 | 1200 30.00 |
| B7 | 07/10/2026 | ETSY | out | 24.50 | 3260 Drawings (judgement 4) | 3260 24.50 | 1200 24.50 |
| B8 | 08/10/2026 | ARGOS - LAPTOP FOR NEW STARTER | out | 549.00 | 0030 Office Equipment | 0030 549.00 | 1200 549.00 |
| B9 | 09/10/2026 | IBIS LONDON | out | 94.00 | 7402 Hotels | 7402 94.00 | 1200 94.00 |
| B10 | 12/10/2026 | LINKEDIN ADS | out | 200.00 | 8201 Subscriptions and Software (judgement 5) | 8201 200.00 | 1200 200.00 |
| B11 | 13/10/2026 | MORRISONS | out | 21.75 | 8205 Refreshments | 8205 21.75 | 1200 21.75 |
| B12 | 14/10/2026 | MARKS & SPENCER - SANDWICHES FOR CLIENT MEETING | out | 38.20 | 7403 Entertainment | 7403 38.20 | 1200 38.20 |
| B13 | 15/10/2026 | CANVA | out | 10.99 | 8201 Subscriptions and Software | 8201 10.99 | 1200 10.99 |
| B14 | 16/10/2026 | NCP CAR PARKS | out | 18.00 | 7400 Travel | 7400 18.00 | 1200 18.00 |
| B15 | 19/10/2026 | SELFRIDGES | out | 210.00 | 3260 Drawings (judgement 4) | 3260 210.00 | 1200 210.00 |
| B16 | 20/10/2026 | DPD UK | out | 12.49 | 7501 Postage and Carriage | 7501 12.49 | 1200 12.49 |
| B17 | 21/10/2026 | COSTCO - MILK AND COFFEE FOR THE OFFICE | out | 46.80 | 8205 Refreshments | 8205 46.80 | 1200 46.80 |
| B18 | 22/10/2026 | BP CONNECT | out | 61.05 | 7300 Fuel and Oil | 7300 61.05 | 1200 61.05 |
| B19 | 26/10/2026 | CAMDEN COUNCIL PENALTY CHARGE | out | 65.00 | 3260 Drawings (judgement 4) | 3260 65.00 | 1200 65.00 |
| B20 | 28/10/2026 | OFFICE DEPOT | out | 27.99 | 7504 Office Stationery | 7504 27.99 | 1200 27.99 |

Every row has one debit and one credit of the same amount, so every row balances.

**Money out, added line by line (B1 and B3 to B20):** 32.40, then 118.70, 124.30, 244.30, 274.30, 298.80, 847.80,
941.80, 1141.80, 1163.55, 1201.75, 1212.74, 1230.74, 1440.74, 1453.23, 1500.03, 1561.08, 1626.08 and 1654.07.

**Statement check.** The first line's printed balance is 8,967.60 after 32.40 out, so the opening balance is
9,000.00. Each printed balance follows from the one before:

| Line | Movement | Balance |
|---|---|---|
| B2 | +3,150.00 | 12,117.60 |
| B3 | −86.30 | 12,031.30 |
| B4 | −5.60 | 12,025.70 |
| B5 | −120.00 | 11,905.70 |
| B6 | −30.00 | 11,875.70 |
| B7 | −24.50 | 11,851.20 |
| B8 | −549.00 | 11,302.20 |
| B9 | −94.00 | 11,208.20 |
| B10 | −200.00 | 11,008.20 |
| B11 | −21.75 | 10,986.45 |
| B12 | −38.20 | 10,948.25 |
| B13 | −10.99 | 10,937.26 |
| B14 | −18.00 | 10,919.26 |
| B15 | −210.00 | 10,709.26 |
| B16 | −12.49 | 10,696.77 |
| B17 | −46.80 | 10,649.97 |
| B18 | −61.05 | 10,588.92 |
| B19 | −65.00 | 10,523.92 |
| B20 | −27.99 | 10,495.93 |

The statement reconciles. Its movement is 10,495.93 − 9,000.00 = +1,495.93, which agrees with 3,150.00 − 1,654.07.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 0030 Office Equipment | 549.00 (B8) | | **549.00** |
| 0040 Furniture and Fixtures | 120.00 (B5) | | **120.00** |
| 1200 Bank Current Account | 3150.00 (B2) | 1654.07 (B1, B3 to B20) | **1495.93** |
| 2110 Expenses Owed to Staff | | 18.00 (C1) + 32.00 (C2) = 50.00 | **-50.00** |
| 3260 Drawings | 24.50 (B7) + 210.00 (B15) + 65.00 (B19) = 299.50 | | **299.50** |
| 4000 Sales | | 3150.00 (B2) | **-3150.00** |
| 7300 Fuel and Oil | 61.05 (B18) | | **61.05** |
| 7400 Travel | 32.00 (C2) + 18.00 (B14) = 50.00 | | **50.00** |
| 7402 Hotels | 94.00 (B9) | | **94.00** |
| 7403 Entertainment | 38.20 (B12) | | **38.20** |
| 7406 Subsistence | 18.00 (C1) + 5.60 (B4) = 23.60 | | **23.60** |
| 7501 Postage and Carriage | 12.49 (B16) | | **12.49** |
| 7502 Telephone and Internet | 30.00 (B6) | | **30.00** |
| 7504 Office Stationery | 32.40 (B1) + 27.99 (B20) = 60.39 | | **60.39** |
| 7800 Repairs and Renewals | 86.30 (B3) | | **86.30** |
| 8201 Subscriptions and Software | 10.99 (B13) + 200.00 (B10) = 210.99 | | **210.99** |
| 8205 Refreshments | 21.75 (B11) + 46.80 (B17) = 68.55 | | **68.55** |

Nothing is left in 9998 Suspense, so it has no line.

Check, adding the debit nets in table order: 549.00, then 669.00, 2164.93, 2464.43, 2525.48, 2575.48, 2669.48,
2707.68, 2731.28, 2743.77, 2773.77, 2834.16, 2920.46, 3131.45 and 3200.00. The credit nets are
50.00 + 3150.00 = 3200.00. The expected trial balance sums to zero.

## Judgement calls

1. **The claim is owed on 2110 Expenses Owed to Staff.** That is the app's convention for an expense claim, and the
   case tests "claim lines owed to staff". The note doesn't say who claimed. If it was the owner's own spending, an
   accountant might credit 3010 Capital Introduced instead. The documents don't say, so that is not expected.
2. **No bank line repays the claim.** There is no £50.00 line, nor one for £18.00 or £32.00, so 2110 stays at
   −50.00. A bank line linked to the claim is wrong.
3. **Claim lines: Breakfast to 7406 Subsistence, Taxi to client to 7400 Travel.** This agrees with the fixture's
   `expected.json`.
4. **Drawings, which this case is meant to test.** All three are departures from the fixture's `expected.json`,
   which puts B7, B15, B19 and B10 in 9998. Those labels were made for reading one document with no client known,
   where Suspense means "for a person to review". Here the business is known to be a sole trader. The model reads each
   row knowing the business is a sole trader, and is told to use Suspense only when nothing fits. The three Drawings rows:
   - **B15 SELFRIDGES £210.00 → 3260 Drawings.** A department store with no business purpose shown: for a sole
     trader, personal spending.
   - **B7 ETSY £24.50 → 3260 Drawings.** A marketplace with no business purpose shown. It is treated the same way as
     Selfridges, because the fixture conventions class a marketplace and a department store together. This is the
     least certain call: 7504 Office Stationery is the main alternative if it were supplies.
   - **B19 CAMDEN COUNCIL PENALTY CHARGE £65.00 → 3260 Drawings.** A fine is not a business expense. A sole
     trader's own fine is a personal cost, so it goes to Drawings. The alternative, 7400 Travel added back for
     tax, is rejected.
5. **B10 LINKEDIN ADS £200.00 → 8201 Subscriptions and Software.** This departs from the fixture's
   `expected.json`, which has 9998. LinkedIn Ads is a known, allowable business cost (advertising), so a careful
   accountant wouldn't leave it in Suspense at the year end. A row left in 9998 is flagged for a person to check.
   - The chart has no advertising account. The nearest fit is 8201, whose definition covers "online services";
     LinkedIn Ads is a self-serve online advertising service.
   - The alternative is 7603 Professional Fees ("other professional services"), which fits less well: no
     professional is engaged.
   - A reading that picks 7603 will differ on 8201 (−200.00) and 7603 (+200.00): a judgement call, not
     necessarily a mistake.
6. **Accounts that follow the chart's own definitions and the fixture's labels:**
   - B4 GREGGS → 7406 Subsistence: a bakery or takeaway.
   - B11 MORRISONS → 8205 Refreshments: a supermarket with no item detail is workplace groceries.
   - B3 TRAVIS PERKINS → 7800 Repairs and Renewals: a builders' merchant, so tools, hardware and building supplies.
   - B18 BP CONNECT → 7300 Fuel and Oil.
   - B12 M&S sandwiches for a client meeting → 7403 Entertainment.
   - B5 GUMTREE office desk → 0040 Furniture and Fixtures.
   - B8 ARGOS laptop → 0030 Office Equipment.
7. **The opening balance (9,000.00) is not booked.** No opening balances are entered, so the trial balance holds the year's transactions only, so 1200
   shows the movement, +1,495.93.

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`). The document rules
cover money out on an expense account or a fixed asset; Drawings (3260) lines are not purchases. Each bank line of £50 or
more with no document is held in 9998 Suspense; a line under £50 is booked (a bank line shows no VAT, so none is reclaimed).

| Account | Old | New | Rule |
|---|---|---|---|
| 0030 Office Equipment | 549.00 | 0.00 (left out) | Argos laptop: £50 or more with no document (over £250): held in 9998. |
| 0040 Furniture and Fixtures | 120.00 | 0.00 (left out) | Gumtree desk: £50 or more with no document: held in 9998. |
| 7300 Fuel and Oil | 61.05 | 0.00 (left out) | BP Connect: £50 or more with no document: held in 9998. |
| 7402 Hotels | 94.00 | 0.00 (left out) | Ibis London: £50 or more with no document: held in 9998. |
| 7800 Repairs and Renewals | 86.30 | 0.00 (left out) | Travis Perkins: £50 or more with no document: held in 9998. |
| 8201 Subscriptions and Software | 210.99 | 10.99 | LinkedIn Ads (£200.00) held in 9998; Canva (£10.99) is under £50 and stays. |
| 9998 Suspense | none | 1110.35 | 549.00 + 120.00 + 61.05 + 94.00 + 86.30 + 200.00. |

Unchanged: 7400 (18.00 NCP + 32.00 taxi), 7406, 7403, 7501, 7502, 7504, 8205 (all lines under £50, or claim lines under
£50 each) and 3260 (Drawings: Etsy, Selfridges and the penalty charge are not covered by the rules).
