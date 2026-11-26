# ltd-late-paid-invoice: how the expected trial balance was worked out

**These two documents are authored test documents, not copies of `eval/fixtures/`.** They test one rule: a bank
payment for exactly what a supplier's bill owes clears that bill, **however late it is paid**. The bill is dated
04/08/2026 and paid on 22/09/2026, 49 days later. Before the rule was added, a payment more than 31 days after its
bill was not tied to it, so the bill stayed owed and the payment was booked as a second cost.

The expected trial balance was worked out by hand from the documents and the booking rules: an invoice posts to
2100 Creditors with its VAT on 2201, and a bank line that pays it clears 2100 with no VAT of its own. It is
checked by `tests/test_eval_cases.py`, which feeds the rows a good reading gives through the real API, with a fake
model. All names, addresses, VAT numbers and the invoice number are made up for the test.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Fernhill Studio Ltd | The bill is made out to it. The name shares no word with any counterparty. |
| Business type | `limited_company` | A limited company. |
| VAT registered | yes | So the VAT on the bill is reclaimed. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027, and both documents are in it. |
| Bank accounts | one current account (1200) | Both documents go to it. |

## Documents (authored)

| File | What it is |
|---|---|
| `documents/calder-rowe-invoice.txt` | Calder & Rowe Print Ltd invoice CR-5521, 04/08/2026, due 03/09/2026, to Fernhill Studio Ltd: printed brochures, net 400.00, VAT 80.00, total 480.00 |
| `documents/current-account-september.csv` | Bank CSV in the layout of the `csv-starling` fixture. Opening balance 6,000.00, three lines with running balances, closing balance 5,425.60 |

## Rows and their double entry

| # | Date | Source | Description | Way | Gross | VAT shown | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|---|---|
| I1 | 04/08/2026 | Invoice | Calder & Rowe Print Ltd, CR-5521: printed brochures | out | 480.00 | 80.00 | 7500 Printing | 7500 400.00; 2201 80.00 | 2100 480.00 |
| S1 | 03/09/2026 | Bank | Northern Electric, electricity September | out | 86.40 | none | 7200 Electricity | 7200 86.40 | 1200 86.40 |
| S2 | 22/09/2026 | Bank | Calder & Rowe Print Ltd, CR-5521 (pays I1) | out | 480.00 | none | paid against 2100 Creditors | 2100 480.00 | 1200 480.00 |
| S3 | 30/09/2026 | Bank | Bank charges, monthly account fee | out | 8.00 | none | 7901 Bank Charges | 7901 8.00 | 1200 8.00 |

The "Opening Balance" and "Closing Balance" rows have an amount of 0.00: they are balances, not transactions.

**VAT:** I1's VAT is as printed: 400.00 × 20% = 80.00, and 400.00 + 80.00 = 480.00 (also 480.00 × 20/120 = 80.00).
Bank lines show no VAT and book none. S2 books none in particular, because the VAT was booked with I1: booking it
again would claim it twice.

**Why S2 pays I1:** the line is for 480.00, exactly what I1 owes, it goes the same way, it names the same payee and
quotes the invoice number CR-5521, and it is dated after the invoice. It is the only line that could. Its being 49
days after the invoice does not matter for an exact payment.

Every row balances: I1 is 400.00 + 80.00 = 480.00 against 480.00, and S1 to S3 each have one debit and one credit
of the same amount.

**Statement check:**

| From | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 6,000.00 | |
| S1 | −86.40 | 5,913.60 | ✓ |
| S2 | −480.00 | 5,433.60 | ✓ |
| S3 | −8.00 | 5,425.60 | ✓ |

The statement reconciles. Its movement is 5,425.60 − 6,000.00 = −574.40, which is 1200's net below.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | | 86.40 (S1) + 480.00 (S2) + 8.00 (S3) = 574.40 | **-574.40** |
| 2100 Creditors | 480.00 (S2) | 480.00 (I1) | 0.00, so it is left out |
| 2201 Purchase VAT | 80.00 (I1) | | **80.00** |
| 7200 Electricity | 86.40 (S1) | | **86.40** |
| 7500 Printing | 400.00 (I1) | | **400.00** |
| 7901 Bank Charges | 8.00 (S3) | | **8.00** |

Check: the debit nets are 80.00 + 86.40 + 400.00 + 8.00 = 574.40, and the credit net is 574.40. The expected trial
balance sums to zero.

## What a wrong result looks like

- **The payment not tied to the bill** (2100 left at −480.00): 2100 would show −480.00 and the payment would be a
  cost of its own, so the books would hold the bill twice. 7500 would be 880.00 or the payee's account would rise by
  480.00.
- **VAT booked on the payment as well**: 2201 would be more than 80.00.

## Judgement calls

1. **I1 goes to 7500 Printing.** Printed brochures are "printing and copying done by others".
2. **S1 goes to 7200 Electricity** and **S3 to 7901 Bank Charges** (a fee, so no VAT).
3. **No opening balance is entered**, so 1200 shows the year's movement, −574.40, not the closing balance.

## Document rules (4 Nov 2026)

From 4 Nov 2026 the site's trial balance applies the document rules (`ledgersync/evidence_rules.py`).

| Account | Old | New | Rule |
|---|---|---|---|
| 7200 Electricity | 86.40 | 0.00 (left out) | S1, Northern Electric: a bank line of £50 or more with no document is held in 9998 Suspense. |
| 9998 Suspense | none | 86.40 | The same row, held. |

The invoice (I1) is a document, so it books and reclaims its VAT as before; S2 pays it, so it is not a purchase of its
own; S3 (£8.00 bank charges) is under £50 and is booked.
