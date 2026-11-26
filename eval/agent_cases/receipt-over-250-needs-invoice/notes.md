# receipt-over-250-needs-invoice: how the expected figures were worked out

A £499.00 laptop has only a till receipt, which says to ask in store for a VAT invoice. Over £250, a receipt is
not enough. The whole gross is held in Suspense, no VAT is reclaimed, and the agent asks for the full VAT invoice.
A chair at exactly £250.00 on a receipt with the VAT number is fine: VAT is reclaimed on a simplified invoice up
to £250.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export: VOLT ELECTRICAL −499.00 on 22/10; SEATWISE OFFICE FURN −250.00 on 27/10 |
| `documents/volt-receipt.txt` | Volt Electrical Ltd till receipt 2210-0457, 22/10/2026, VAT number printed: Lenovo ThinkPad E14 laptop 499.00, "Includes VAT @ 20% 83.17". "This is a till receipt. Ask in store for a VAT invoice." |
| `documents/seatwise-receipt.txt` | Seatwise Office Furniture Ltd, sale 88120, 27/10/2026, VAT number printed: ergonomic office chair 250.00, "VAT @ 20% INCLUDED 41.67" |

## Conventions

- A receipt paired with its card payment is booked from the receipt, against 1200, and the line is not booked.
- **Document rules:**
  - a receipt over £250.00 is held: Dr 9998 for the gross, Cr 1200, with no VAT leg, needing `vat_invoice`;
  - a receipt of £250.00 or less, with the VAT and the VAT number, reclaims the VAT.
- Fixed assets (0030, 0040) are covered by the rules.

## Rows and their double entry

| # | Date | Source | Description | Gross | VAT shown | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| B1 | 22/10/2026 | Barclays | VOLT ELECTRICAL | 499.00 | — | recorded by R1, **not booked** | — | — |
| B2 | 27/10/2026 | Barclays | SEATWISE OFFICE FURN | 250.00 | — | recorded by R2, **not booked** | — | — |
| R1 | 22/10/2026 | Volt receipt | Lenovo ThinkPad E14 laptop | 499.00 | 83.17 | **receipt over £250: hold**, needs `vat_invoice`; no VAT reclaimed | 9998 499.00 | 1200 499.00 |
| R2 | 27/10/2026 | Seatwise receipt | Ergonomic office chair, black | 250.00 | 41.67 | **receipt of exactly £250.00** with VAT number: book and reclaim | 0040 208.33; 2201 41.67 | 1200 250.00 |

The VAT:
- R1: £499.00 × 1/6 = £83.1667, which is £83.17, as printed. Not reclaimed while held.
- R2: £250.00 × 1/6 = £41.6667, which is £41.67, as printed. Net 250.00 − 41.67 = 208.33.

## Decisions

None. Holding is the document rule's.

## Questions

| Row | Kind | Before answers | After answers |
|---|---|---|---|
| Lenovo ThinkPad E14 laptop (£499.00) | `vat_invoice` | open | open (not answered) |

The why, per Task 7: "£499.00 to Volt Electrical Ltd on 22 Oct 2026. Over £250, so I need it. Held in Suspense
as Documentation required until then."

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 0040 Furniture and Fixtures | 208.33 | | **208.33** |
| 1200 Bank Current Account | | 499.00 + 250.00 = 749.00 | **-749.00** |
| 2201 Purchase VAT | 41.67 | | **41.67** |
| 9998 Suspense | 499.00 | | **499.00** |

Check: the debits are 208.33 + 41.67 + 499.00 = 749.00, against credits of 749.00. It balances.

The posted trial balance's `suspense` list holds one item: Lenovo ThinkPad E14 laptop, £499.00, needs
`vat_invoice`.

## Answers

None. The question stays open.

```json
[]
```

## Needs a check

Nothing. `evidence_rules` holds the receipt over £250, and books and reclaims at exactly £250.00.

## Judgement calls

1. **The laptop goes to 0030 Office Equipment, and the chair to 0040 Furniture and Fixtures.** Both are kept for
   over a year.
2. **The whole £499.00 waits in Suspense, not the net.** The spec says no part of it is booked as a cost until the
   invoice arrives.
