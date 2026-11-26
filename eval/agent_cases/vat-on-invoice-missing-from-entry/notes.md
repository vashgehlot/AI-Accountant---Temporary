# vat-on-invoice-missing-from-entry: how the expected figures were worked out

A broadband invoice prints £12.00 VAT, but the reading left the VAT out. The agent takes the VAT from the
document (R5).

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export: NORTHERN FIBRE BROADBAND −72.00 on 15/10 (direct debit); BARCLAYS ACCOUNT FEE −8.50 on 30/10 |
| `documents/northern-fibre-invoice-NFB-88213.pdf` | Northern Fibre Broadband Ltd, tax invoice NFB-88213, 01/10/2026, VAT number printed. Business Fibre 500 for October 60.00. "Amount before VAT £60.00", "VAT @ 20% £12.00", "Total to pay £72.00" |

## As read

- The invoice row is £72.00 on 7502 with **`vat: null`**: the reading missed the VAT line.
- It did read the total before VAT (`document_net` 60.00) and the total (`document_total` 72.00).
- With no VAT shown on the row, `normalise` books none. The invoice posts 7502 72.00 against 2100 72.00, and
  £12.00 of reclaimable VAT is lost in the cost.

## The decision

**R5 set_vat_from_document** on "Northern Fibre: Business Fibre 500, October 2026", with `vat` 12.00.

R5's checks:
- £12.00 is above zero and at most `vat_in_gross(72.00, standard)` = 72.00 × 1/6 = 12.00.
- 7502 is an expense account, and the client is VAT registered.
- "12.00" is printed in the row's own document.

The evidence is "VAT @ 20% £12.00" from the invoice PDF's text layer. The expected rule is "R5 VAT from the
document".

## Rows and their double entry, after the decision

| # | Date | Source | Description | Gross | VAT | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|---|
| I1 | 01/10/2026 | Invoice NFB-88213 | Northern Fibre: Business Fibre 500, October 2026 | 72.00 | 12.00 | invoice: reclaim | 7502 60.00; 2201 12.00 | 2100 72.00 |
| B1 | 15/10/2026 | Barclays | NORTHERN FIBRE BROADBAND | 72.00 | — | pays I1 exactly (dated after it; "NORTHERN FIBRE" matches) | 2100 72.00 | 1200 72.00 |
| B2 | 30/10/2026 | Barclays | BARCLAYS ACCOUNT FEE | 8.50 | none | under £50 | 7901 8.50 | 1200 8.50 |

## Questions

None.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 72.00 + 8.50 = 80.50 | **-80.50** |
| 2100 Creditors | 72.00 | 72.00 | 0.00 (no line) |
| 2201 Purchase VAT | 12.00 | | **12.00** |
| 7502 Telephone and Internet | 60.00 | | **60.00** |
| 7901 Bank Charges | 8.50 | | **8.50** |

Check: the debits are 12.00 + 60.00 + 8.50 = 80.50, against credits of 80.50. It balances.

## Answers

None.

```json
[]
```

## Needs a check

1. **No check raised this.** Done in Task 8: `checks.normalise` warns `vat_not_booked`, "The invoice shows £12.00
   VAT; none is booked.", on a VAT-registered client's account VAT applies to, when `vat is None` and
   `document_total − document_net` is above zero and at most `most_vat(document_total)`.
   - Before, an invoice row with no VAT, whose own `document_net` (60.00) and `document_total` (72.00) differ by a
     plausible VAT (12.00 = 72.00 × 1/6), got no issue at all, and the agent found it only by opening the
     document.
   - `matching._claim_vat` does this sum only for a document on an expense claim.

## Judgement calls

1. **Broadband goes to 7502 Telephone and Internet.**
