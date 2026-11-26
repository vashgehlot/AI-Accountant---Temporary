# clean-month: how the expected figures were worked out

A month with nothing to sort and nothing to ask: every payment has the document its amount needs, or is under
£50, or is exempt. The real-model smoke test (Task 10, Step 5) uploads this case and expects no questions and a
balanced trial balance.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit. No row
has any issue at all, not even an info note.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 5 lines, no balances |
| `documents/ardent-rent-invoice-AP-10-2026.pdf` | Ardent Property Ltd, invoice AP-10-2026, 01/10/2026: office rent for October 750.00. "No VAT is charged on this rent." "Total due: £750.00" |
| `documents/pret-receipt.txt` | Pret A Manger, Leeds Station, 13/10/2026, eat in, VAT number printed: baguette 5.95 + flat white 2.50 = TOTAL 8.45, VAT 20% 1.41, Visa debit |

## Conventions

- **Invoices and receipts:**
  - An invoice is owed on 2100 until a bank line pays it, and the paying line posts Dr 2100, Cr 1200.
  - A receipt paired with its card payment is booked from the receipt, against 1200, and the line is not booked.
- **Exempt lines:** money in, and the director's loan account, are exempt from the document rules.

## Rows and their double entry

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 01/10/2026 | Barclays | J NORTH LOAN TO COMPANY (in) | 1000.00 | none | money in, 2250: exempt | 1200 1000.00 | 2250 1000.00 |
| I1 | 01/10/2026 | Invoice AP-10-2026 | Ardent Property: office rent, Suite 3, 14 Wharf Street, October 2026 | 750.00 | none shown | invoice: book (no VAT to reclaim) | 7100 750.00 | 2100 750.00 |
| B2 | 02/10/2026 | Barclays | ARDENT PROPERTY | 750.00 | — | pays I1 exactly | 2100 750.00 | 1200 750.00 |
| B3 | 03/10/2026 | Barclays | BT GROUP PLC | 42.00 | none | under £50 | 7502 42.00 | 1200 42.00 |
| B4 | 13/10/2026 | Barclays | PRET A MANGER | 8.45 | — | recorded by R1, **not booked** | — | — |
| R1 | 13/10/2026 | Pret receipt | Pret A Manger: chicken caesar baguette and flat white | 8.45 | 1.41 | receipt with VAT number and VAT shown: reclaim | 7406 7.04; 2201 1.41 | 1200 8.45 |
| B5 | 30/10/2026 | Barclays | BARCLAYS ACCOUNT FEE | 8.50 | none | under £50 | 7901 8.50 | 1200 8.50 |

- **R1's VAT:** eat-in food is standard-rated. £8.45 × 1/6 = £1.4083, which is £1.41, as printed. Net 8.45 −
  1.41 = 7.04.
- **I1:** rent is exempt unless the landlord opted to tax, and the invoice says no VAT is charged. So there is no
  VAT to reclaim.

## Decisions and questions

None, and none.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | 1000.00 | 750.00 + 42.00 + 8.45 + 8.50 = 808.95 | **191.05** |
| 2100 Creditors | 750.00 | 750.00 | 0.00 (no line) |
| 2201 Purchase VAT | 1.41 | | **1.41** |
| 2250 Director's Loan Account | | 1000.00 | **-1000.00** |
| 7100 Rent | 750.00 | | **750.00** |
| 7406 Subsistence | 7.04 | | **7.04** |
| 7502 Telephone and Internet | 42.00 | | **42.00** |
| 7901 Bank Charges | 8.50 | | **8.50** |

Check: the debits are 191.05 + 1.41 + 750.00 + 7.04 + 42.00 + 8.50 = 1000.00, against credits of 1000.00. It
balances.

## Answers

None.

```json
[]
```

## Needs a check

Nothing.

## Judgement calls

1. **The director's £1,000 goes to 2250 Director's Loan Account.** It is money the director lent the company, not
   a sale.
2. **The rent invoice, over £250, needs nothing more.** It is an invoice. The over-£250 rule asks for a full VAT
   invoice only where the document is a receipt.
