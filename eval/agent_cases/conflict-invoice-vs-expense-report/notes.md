# conflict-invoice-vs-expense-report: how the expected figures were worked out

An invoice says £46.80 for a toner cartridge, and the office expenses sheet says £42.00 for the same toner.
Barclays paid the invoice. The invoice ranks above the sheet, so the agent uses the invoice (R4), and the sheet
line leaves the books. The bank payment then pays the invoice.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export: PAGECRAFT STATIONERS −46.80 on 09/10/2026 |
| `documents/pagecraft-invoice-PC-5512.pdf` | Pagecraft Stationers Ltd, invoice PC-5512, 06/10/2026, VAT number printed: toner 39.00. "Net: £39.00", "VAT 20%: £7.80", "Invoice total: £46.80" |
| `documents/staff-expenses-october.xlsx` | Priya Shah's sheet: "Pagecraft - toner cartridge" 06/10 £42.00; "Mileage - client visit Harrogate, 40 miles at 45p" 16/10 £18.00. No total row |

The mileage: 40 × £0.45 = £18.00.

## Conventions

- An invoice is owed to the supplier (2100 Creditors) until a bank line pays it. A paying line posts Dr 2100,
  Cr 1200, with no VAT.
- An expenses sheet line is owed to the employee (2110).
- An invoice reclaims the VAT it shows.
- A sheet line under £50 is booked without a document, with no VAT.

## What the books show before the agent acts

`matching` sees the invoice and the sheet line from the same shop, on the same day, for different amounts. It
raises `amount_conflict` on both ("Read as £46.80; the claim says £42.00. Not booked until you choose."), holds
the invoice (`recorded_by` the sheet line) and books the sheet line.

With the invoice held, nothing is open for the Barclays £46.80 to pay, so it is booked as a cost too. Before:
- 7504 88.80 (42.00 + 46.80);
- 2110 −60.00;
- 1200 −46.80.

## The decision

**R4 use_primary:**
- **primary** "Pagecraft: Brother TN-2420 toner cartridge" (invoice, rank 3);
- **other** the sheet line "Pagecraft - toner cartridge" (expenses sheet, rank 1).

R4's checks:
- An `amount_conflict` issue links the two rows.
- The invoice ranks above the sheet.
- The other row is a sheet line, not a bank line, so it is `excluded` rather than linked.

The evidence is two quotes:
- "Invoice total: £46.80" from the invoice PDF's text layer;
- "Pagecraft - toner cartridge" from the sheet.

The expected rule is "R4 Conflict: used the invoice".

What it does: with the sheet line out, the invoice is booked, and BARCLAYS PAGECRAFT STATIONERS £46.80 (09/10,
on or after the invoice) pays it exactly.

## Rows and their double entry, after the decision

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| I1 | 06/10/2026 | Invoice PC-5512 | Pagecraft: Brother TN-2420 toner cartridge | 46.80 | 7.80 | invoice: reclaim | 7504 39.00; 2201 7.80 | 2100 46.80 |
| B1 | 09/10/2026 | Barclays | PAGECRAFT STATIONERS | 46.80 | — | pays I1 (exempt: it pays a document) | 2100 46.80 | 1200 46.80 |
| S1 | 06/10/2026 | Expenses sheet | Pagecraft - toner cartridge | 42.00 | — | **excluded by R4** | — | — |
| S2 | 16/10/2026 | Expenses sheet | Mileage - client visit Harrogate, 40 miles at 45p | 18.00 | none | sheet line under £50: book, no VAT | 7400 18.00 | 2110 18.00 |

**I1's VAT:** £39.00 × 20% = £7.80. Then 39.00 + 7.80 = 46.80, and 46.80 × 1/6 = 7.80.

## Questions

None.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 46.80 | **-46.80** |
| 2100 Creditors | 46.80 | 46.80 | 0.00 (no line) |
| 2110 Expenses Owed to Staff | | 18.00 | **-18.00** |
| 2201 Purchase VAT | 7.80 | | **7.80** |
| 7400 Travel | 18.00 | | **18.00** |
| 7504 Office Stationery | 39.00 | | **39.00** |

Check: the debits are 7.80 + 18.00 + 39.00 = 64.80. The credits are 46.80 + 18.00 = 64.80. It balances.

## Answers

None.

```json
[]
```

## Needs a check

1. **R4 is only right here because Barclays paid the invoice.**
   - If Priya had paid Pagecraft herself, the sheet line would be the record of what she is owed.
   - Excluding it would leave the invoice owed to Pagecraft on 2100, and Priya with nothing on 2110.
   - The right booking would then be the invoice at £46.80, owed to her. `use_primary` can't express that today.
   - Worth a line in the prompt: use the invoice over the sheet when a bank line pays it. Otherwise ask.

## Judgement calls

1. **Toner goes to 7504 Office Stationery** ("paper, pens, ink and other small office supplies").
2. **Mileage goes to 7400 Travel, with no VAT.** A mileage allowance has no VAT invoice.
