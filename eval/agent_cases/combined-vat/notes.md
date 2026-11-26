# combined-vat: how the expected figures were worked out

A cash-and-carry receipt mixes standard-rated cleaning supplies with zero-rated tea, coffee, milk and sugar, under
one VAT total. The agent splits it by rate (R3). The parts add up exactly to the receipt, and the VAT is claimed
only on the standard-rated part.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 2 lines |
| `documents/bulkbuy-receipt.txt` | Bulkbuy Cash & Carry Ltd, 19/10/2026, VAT number printed. TOTAL **£64.00** by debit card. VAT summary: "S 20% 38.00 7.60 45.60" and "Z 0% 18.40 0.00 18.40"; TOTAL VAT 7.60 |

The receipt's items:

| Item | Amount | Rate |
|---|---|---|
| Washing-up liquid 5L | 9.60 | S |
| Bin bags 200 | 14.40 | S |
| Kitchen roll 24 | 12.00 | S |
| Antibac spray ×6 | 9.60 | S |
| Semi-skimmed milk 6pt | 2.40 | Z |
| Tea bags 1100 | 9.50 | Z |
| Instant coffee 750g | 5.20 | Z |
| Granulated sugar 2kg | 1.30 | Z |

- S: 9.60 + 14.40 + 12.00 + 9.60 = **45.60**.
- Z: 2.40 + 9.50 + 5.20 + 1.30 = **18.40**.
- Total: 45.60 + 18.40 = 64.00, as printed.
- VAT on S: 45.60 × 1/6 = **7.60** exactly, as printed. Net 38.00.

## As read

- The receipt is read as **one row**: £64.00, VAT £7.60, on 7801 Cleaning (the biggest part), with the
  adapter's `mixed_items` warning.
- `normalise` words the warning: "VAT £7.60 is on £45.60; £18.40 has none."
- The Barclays line BULKBUY CASH AND CARRY £64.00 on 19/10 pairs with the receipt and is not booked.

Before the split, the receipt would post 7801 56.40 and 2201 7.60. The VAT is right, but £18.40 of groceries sits
in Cleaning.

## The decision

**R3 split_vat** on "Bulkbuy: cleaning supplies, tea, coffee, milk and sugar":

| Part | Account | Gross | Rate | VAT (`vat_in_gross`) |
|---|---|---|---|---|
| Cleaning supplies: washing-up liquid, bin bags, kitchen roll, antibac spray | 7801 Cleaning | 45.60 | standard | 7.60 |
| Tea, coffee, milk and sugar for the office | 8205 Refreshments | 18.40 | zero | 0.00 |

R3's checks:
- The parts' gross is 45.60 + 18.40 = 64.00, exactly the row's gross.
- The parts' VAT is 7.60 + 0.00 = 7.60, against the row's VAT of 7.60, within 0.01 × 2.
- Both accounts are choosable for a limited company.

The evidence is two quotes from `bulkbuy-receipt.txt`: "S 20% 38.00 7.60 45.60" and "Z 0% 18.40 0.00 18.40".
The expected rule is "R3 Mixed VAT: split by rate".

The original row becomes `superseded_by` the decision. The two parts keep its `document_ref`, so together
(£64.00) they still pair with the Barclays line.

## Rows and their double entry, after the decision

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 19/10/2026 | Barclays | BULKBUY CASH AND CARRY | 64.00 | — | recorded by the receipt, **not booked** | — | — |
| B2 | 30/10/2026 | Barclays | BARCLAYS ACCOUNT FEE | 8.50 | none | under £50 | 7901 8.50 | 1200 8.50 |
| R | 19/10/2026 | Bulkbuy receipt | (original) | 64.00 | 7.60 | **superseded by R3** | — | — |
| R.1 | 19/10/2026 | split | Cleaning supplies… | 45.60 | 7.60 | receipt ≤ £250, VAT number and VAT shown: reclaim | 7801 38.00; 2201 7.60 | 1200 45.60 |
| R.2 | 19/10/2026 | split | Tea, coffee, milk and sugar… | 18.40 | 0.00 | no VAT shown on this part: the gross | 8205 18.40 | 1200 18.40 |

The rule is applied to each part. R.1 is a receipt part of £45.60 that shows £7.60 VAT, and the document prints
the VAT number, so it reclaims. R.2 shows no VAT, so it books its gross.

## Questions

None.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 45.60 + 18.40 + 8.50 = 72.50 | **-72.50** |
| 2201 Purchase VAT | 7.60 | | **7.60** |
| 7801 Cleaning | 38.00 | | **38.00** |
| 7901 Bank Charges | 8.50 | | **8.50** |
| 8205 Refreshments | 18.40 | | **18.40** |

Check: the debits are 7.60 + 38.00 + 8.50 + 18.40 = 72.50, against credits of 72.50. It balances.

## Answers

None.

```json
[]
```

## Needs a check

Nothing. The `mixed_items` warning, with "VAT £7.60 is on £45.60; £18.40 has none", is the issue the agent
resolves.

## Judgement calls

1. **Two parts, not one per item.** Each part takes one rate and one account. Splitting further (sugar apart from
   tea) changes no figure.
2. **Cleaning supplies go to 7801 Cleaning** ("cleaning services and supplies"). **Tea, coffee, milk and sugar go
   to 8205 Refreshments** (workplace groceries, zero-rated).
