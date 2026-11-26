# Ashdown Joinery: the books worked by hand

Worked on 6 November 2026, before comparing with what the site produced. The site was used as an accountant uses
it: files added through Documents (`POST /api/analyze`), no chat, with the background AI review on.

## The client

| Setting | Value |
|---|---|
| Name | Ashdown Joinery Ltd: limited company, VAT registered, a joinery subcontractor under CIS |
| Director | Priya Ashdown (the "P ASHDOWN" line) |
| First year | 1 Apr 2026 to 31 Mar 2027 |
| Banks | Starling current (1200), Starling savings (1210) |
| Opening balances at 1 Apr 2026 | 1200 Bank £5,000.00 Dr; 3000 Shares £100.00 Cr; 3200 Retained earnings £4,900.00 Cr |

## The documents, booked line by line

`documents/` goes in first; `answers/screwfix-receipt-03-10.txt` follows later, on its own.

| # | Line or document | Booking | Why |
|---|---|---|---|
| 1 | 01/10 HMRC VAT £2,140.00 out | Dr 2202 VAT Liability | Payment of the VAT return |
| 2 | Sales invoice AJ-2041, 20/09: labour £3,000 + materials £1,000, reverse charge, CIS 20% on labour £600, £3,400 due | Cr 4000 Sales £4,000.00; Dr 1100 Debtors £3,400.00; Dr CIS Deducted £600.00 | The sale is £4,000. The £600 went to HMRC as CIS: the customer will never pay it, and the company sets it against its PAYE. No output VAT (domestic reverse charge) |
| 3 | 02/10 Fenwick Builders £3,400.00 in | Dr 1200 / Cr 1100 £3,400.00 | Pays AJ-2041 in full |
| 4 | 03/10 Screwfix £86.40 out, no receipt | Dr 9998 Suspense £86.40 | Over £50 with no document; ask for the receipt |
| 4a | Screwfix receipt (later): subtotal £72.00, cut off at "VAT 20" | Dr 5000 Purchases £86.40, no VAT | The receipt doesn't print the VAT or the total, so the £14.40 can't be reclaimed yet. Ask for a complete copy |
| 5 | Currys CB-55120, laptop £1,208.33 + VAT £241.67, paid by card 05/10 | Dr 0030 £1,208.33; Dr 2201 £241.67 | A capital item, with a full VAT invoice |
| 6 | Hiscox HX-778120, £1,125.00 + IPT £135.00, DD 07/10 | Dr 8204 Insurance £1,260.00, no VAT | IPT is not VAT; insurance is exempt. Cover runs to 6 Oct 2027: about £652 is prepaid at the year end (a pointer only) |
| 7 | 09/10 P ASHDOWN £2,000.00 out | Dr 2250 Director's Loan Account | A director's withdrawal with no payroll behind it |
| 8 | 10/10 Shell £38.50 | Dr 7300 Fuel, no VAT | Under £50; no receipt, so no VAT |
| 9 | Ivy receipt, £184.00 incl. VAT £30.67, dinner with the customer's site team | Dr 7403 Entertainment £184.00 | Business entertainment: VAT blocked |
| 10 | 15/10 Stripe payout £1,163.10 in | Cr payment processor clearing £1,163.10 | A payout is sales less Stripe's fees and refunds. Ask for the Stripe payout report |
| 11 | 18/10 Adobe £24.71 | Dr 8201 Subscriptions and Software, no VAT | Under £50 |
| 12 | 20/10 To savings £3,000.00 | Dr 1210 | Own transfer |
| 13 | 22/10 Netflix £12.99 | Dr 2250 Director's Loan Account | A streaming service on a joinery company's account is personal |
| 14 | 25/10 HMRC PAYE £612.40 | Dr 2210 PAYE and NI | Ask for the payroll reports |
| 15 | 28/10 Starling fee £7.00 | Dr 7901 Bank Charges | Exempt |
| 16 | Jewson JW-88812, 28/09: £285.00 + VAT £57.00; paid 30/10 £342.00 | Dr 5000 £285.00; Dr 2201 £57.00; Cr 2100 £342.00; then Dr 2100 / Cr 1200 £342.00 | A bill paid later |

## The bank

- October's statement opens at £8,200.00 (£6,060.00 after the first line's £2,140.00) and closes at £1,605.10.
- The books hold £5,000.00 at 1 April and -£1,594.90 at 30 October: £3,200.00 less than the statement.
- The difference is the April to September statements, which are missing. No savings statement either.

## Expected trial balance, after the Screwfix receipt

Debits positive, credits negative; opening balances included. In `expected_trial_balance.json`.

| Account | Dr | Cr |
|---|---:|---:|
| 0030 Office Equipment | 1,208.33 | |
| CIS Deducted | 600.00 | |
| 1200 Bank Current Account | | 1,594.90 |
| 1210 Bank Deposit Account | 3,000.00 | |
| Payment processor clearing | | 1,163.10 |
| 2201 Purchase VAT | 298.67 | |
| 2202 VAT Liability | 2,140.00 | |
| 2210 PAYE and National Insurance | 612.40 | |
| 2250 Director's Loan Account | 2,012.99 | |
| 3000 Ordinary Shares | | 100.00 |
| 3200 Retained Earnings | | 4,900.00 |
| 4000 Sales | | 4,000.00 |
| 5000 Purchases | 371.40 | |
| 7300 Fuel and Oil | 38.50 | |
| 7403 Entertainment | 184.00 | |
| 7901 Bank Charges | 7.00 | |
| 8201 Subscriptions and Software | 24.71 | |
| 8204 Insurance | 1,260.00 | |
| **Total** | **11,758.00** | **11,758.00** |

Before the receipt, the £86.40 sits in 9998 Suspense instead of 5000.

## What should still need the accountant: missing documents only

- Starling current statements for April to September 2026 (they explain the £3,200.00).
- A Starling savings statement.
- The October 2026 payroll report, for the £612.40 PAYE payment.
- The Stripe payout report for 15 October 2026.
- A complete Screwfix receipt, to reclaim the £14.40 VAT (before it arrives: the receipt itself).

Pointers, not questions: the director's loan is overdrawn by £2,012.99 (s455 if still overdrawn nine months after
the year end); the Hiscox cover runs past the year end.

## What the site did on 6 November, before the fixes

| Item | Worked by hand | The site | |
|---|---|---|---|
| AJ-2041 | Sales £4,000, CIS Deducted £600 | Sales £3,400; the £600 vanished | Wrong |
| Hiscox | £1,260 insurance, no VAT, no warning | Booked right, but "The invoice shows £135.00 VAT; none is booked". The AI tried to clear it and was refused | Untrue warning |
| Stripe | Clearing; ask for the payout report | Sales £1,163.10, "choose its VAT rate" (invites 20% on a net payout); the AI asked for an invoice or report | Wrong account, misleading warning |
| Netflix | Director's loan | Subscriptions and Software, no flag | Wrong |
| Starling current | Statement £1,605.10, books -£1,594.90, £3,200 missing | "No statement this year" | Untrue |
| Missing statements | Ask for April to September, and savings | Nothing | Missing |
| Screwfix receipt | £86.40, no VAT; ask for a complete copy | Booked right; "The receipt shows £14.40 VAT" (it doesn't); the AI asked, after four refused attempts | Untrue warning |
| Director's loan | Overdrawn £2,012.99 | Nothing | Missing pointer |
| Everything else | as above | as above | Right |

## Found while fixing, on the second and third runs

The reader read the cut-off Screwfix receipt three ways on three runs: £86.40 with no VAT, £72.00 (its subtotal),
and £86.40 with £14.40 VAT it had worked out. Two of those went wrong:

| Reading | What happened | |
|---|---|---|
| £72.00 | An amount conflict with the £86.40 bank line. The AI review then kept the receipt and dropped the bank line (R4), so £14.40 that left the bank vanished and the bank stopped agreeing with its statement | Wrong |
| £86.40 + £14.40 VAT | £14.40 VAT reclaimed that the receipt never prints | Wrong |

## After the fixes (third run, 6 November)

Through Documents alone, with the background AI review on, both trial balances (the rows' and the posted
ledger's) match the figures above to the penny, before and after the Screwfix receipt, whichever way it is read.
The AI review changed nothing on the first files ("Nothing to change"). What is left needs the accountant only
for missing documents:

- **Missing paperwork** on the Overview: no Starling current statements for April to September 2026 (October
  opens at £8,200.00, the books have £5,000.00); no Starling savings statement.
- **Questions:** the Stripe payout report; the October 2026 payroll report; a complete copy of the Screwfix
  receipt (asked by the AI review).
- **Pointer:** the director's loan is overdrawn by £2,012.99 (s455).
- The Starling current card says "£3,200.00 less in the books than the statement of 30 Oct 2026", not "No statement".
