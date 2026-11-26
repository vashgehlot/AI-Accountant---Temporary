# no-invoice-over-50-suspense: how the expected figures were worked out

Bank payments with no receipt or invoice behind them:
- One of £49.99 is booked from the bank line.
- One of exactly £50.00 and one of £240.00 are held in Suspense (9998) as Documentation required, each with a
  question.
- A £500.00 payment to HMRC is exempt from the rules.

The person says they don't have the Brightline invoice, so it stays in Suspense and its question waits. The
Amazon question is left unanswered.

The figures were worked by hand from the documents. Afterwards they were cross-checked with the pure services on
the `.rows.json` files, without MongoDB or a model. Every figure agreed, and nothing was changed to fit.

## Client and year

Northbridge Consulting Ltd: a limited company, VAT registered. The first year runs 1 Apr 2026 to 31 Mar 2027.
There is one current account (1200) and no opening balances.

## Documents

| File | What it is |
|---|---|
| `documents/barclays-october.csv` | Barclays export, 4 lines, no balances. No other document |

## Conventions

- **Document rules (gross):**
  - under £50.00, a bank line is booked with no document and no VAT;
  - from £50.00, it needs a receipt or invoice;
  - until one arrives, it is posted Dr 9998 Suspense, Cr 1200, with no VAT leg.
- HMRC payments are exempt. The rules cover only expense and fixed-asset accounts, and 2320 is a liability.

## Rows and their double entry

| # | Date | Description | Gross | Account read | Rule | Debit | Credit |
|---|---|---|---|---|---|---|---|
| B1 | 06/10/2026 | OFFICE DEPOT | 49.99 | 7504 | **£49.99 < £50.00**: book from the line, no VAT | 7504 49.99 | 1200 49.99 |
| B2 | 09/10/2026 | AMAZON MKTPLACE | 50.00 | 7504 | **£50.00 needs a document**: hold, needs `receipt_or_invoice` | 9998 50.00 | 1200 50.00 |
| B3 | 20/10/2026 | HMRC CORPORATION TAX | 500.00 | 2320 | liability, exempt: book | 2320 500.00 | 1200 500.00 |
| B4 | 22/10/2026 | BRIGHTLINE PRINT | 240.00 | 7500 | £50–£250, no document: hold, needs `receipt_or_invoice` | 9998 240.00 | 1200 240.00 |

## Decisions

None. Holding is the document rule's, applied at posting. It needs no decision.

## Questions

| Row | Kind | Before answers | After answers |
|---|---|---|---|
| AMAZON MKTPLACE £50.00 | `receipt_or_invoice` | open | open (not answered) |
| BRIGHTLINE PRINT £240.00 | `receipt_or_invoice` | open | **waiting**, answer "I don't have it" |

The Brightline question's why, per Task 7: "£240.00 to Brightline Print on 22 Oct 2026. £50 or more, so I need it.
Held in Suspense as Documentation required until then."

"I don't have it" changes no figure. The payment stays in Suspense, as the spec says.

## Per-account sums

| Account | Debits | Credits | Net |
|---|---|---|---|
| 1200 Bank Current Account | | 49.99 + 50.00 + 500.00 + 240.00 = 839.99 | **-839.99** |
| 2320 Corporation Tax | 500.00 | | **500.00** |
| 7504 Office Stationery | 49.99 | | **49.99** |
| 9998 Suspense | 50.00 + 240.00 = 290.00 | | **290.00** |

Check: the debits are 500.00 + 49.99 + 290.00 = 839.99, against credits of 839.99. It balances.

The posted trial balance's `suspense` list holds two items:
- AMAZON MKTPLACE, £50.00, needs `receipt_or_invoice`;
- BRIGHTLINE PRINT, £240.00, needs `receipt_or_invoice`.

## Answers

```json
[
  {"question": {"kind": "receipt_or_invoice", "row": {"file": "barclays-october.csv", "description": "BRIGHTLINE PRINT"}},
   "answer": {"kind": "no_document"}}
]
```

## Needs a check

1. **The question wording for an under-£250 hold.** Task 7's why read "Over £50, so I need it", which at exactly
   £50.00 was not quite true: the rule is "£50.00 or more". It now reads "£50 or more, so I need it" for the
   `receipt_or_invoice` case.

## Judgement calls

1. **The HMRC payment is posted to 2320 Corporation Tax as read.** There are no opening balances here, so it shows
   as a debit, a payment on account. This case only needs it to be exempt.
2. **The Amazon line is held although it might be several small items.** The rule goes by the line's gross, and
   the line is all there is.
