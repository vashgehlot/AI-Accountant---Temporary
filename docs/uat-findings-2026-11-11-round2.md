# UAT round 2, 11 Nov 2026: testing as a UK accountant

Second round, on new cases. Run on the throwaway test server (local MongoDB, database
`ledgersync_uat_haiku`); the real database was not touched. Documents read by Qwen 3.8, chat and
background review by Claude Haiku 5.5. Nothing below is fixed yet.

## Status of the critical issues (fixed 11 Nov, not committed)

| # | Issue | What changed | Checked |
|---|---|---|---|
| 1 | CIS invoice crashes the books | The posting rule keeps the CIS amount when VAT stays in the cost. A row that still can't post now names itself on the page instead of "the API is not running". | Tests; the invoice re-read on the test server: cost £1,200, CIS payable £200, books balance |
| 2 | CIS taken off every line | One deduction per invoice: kept on the labour line, and taken off it when the lines were read before the deduction. | Tests |
| 3 | Till takings counted twice | With a till summary in the books, takings go into the till (Petty Cash), and a card processor's sales and cash paid in at the bank move money out of the till instead of adding to Sales. The reader is told not to make rows for "cash banked" or card totals. | Tests; Rosa's Cafe: Sales £6,666.67 (was £12,226.67), books balance |
| 4 | Overlapping statements booked twice | A bank line with the same account, day, amount and balance as an earlier one is a copy and is not booked. Overlapping statements are no longer reported as missing lines. Lines without a printed balance still go to the possible-duplicate check. | Tests; Marlow: bank agrees with the statement to the penny |
| 5 | Dividend matched to a mileage claim | A line coded to tax, wages, a loan or the owner only pays a document of exactly its amount; otherwise it is suggested, not matched. | Tests; Marlow: £8,000 in Dividends |
| 6 | Receipts booked to the bank | A receipt its account's statement doesn't show (lines either side of its day, no payment of it) is kept off the bank in Suspense with a note. Edit has a new "Paid from" choice: a bank account, the owner's own money, or staff to repay. With no statement around its day nothing changes. | Tests; in the app on the Currys receipt |
| 7 | Revised invoice booked on top of the original | An invoice under a number already used by that supplier, for another total, is flagged on the later one. That starts an AI review and lets "keep one" drop the original. It is not removed without a person or the AI deciding. | Tests; Marlow: the review now picks it up and asks for confirmation |

Four older test cases expected a cash receipt to sit on the bank (the demo's £18 taxi among them); their expected
figures and notes now show it in Suspense with the bank agreeing. Backend 1,541 tests pass, frontend 115.
The backend runs used the local throwaway MongoDB: the remote test cluster did not answer.

Issues 12 and 8, left open by these fixes, are covered by the high-priority fixes below.

## Status of the high issues (fixed 12 Nov, not committed)

| # | Issue | What changed | Checked |
|---|---|---|---|
| 8 | Finance agreements read as invoices | New document type "finance or loan agreement": listed, never booked, with a note to book the asset and interest by journal. | Tests; both Marlow agreements re-read: not booked, Vans £18,000 |
| 9 | Deposit held in Suspense | A payment whose own words say deposit, part payment or instalment pays its invoice. Any other part payment still waits, and now says which document it was matched to and to Link it. | Tests; Marlow: Creditors £18,295.20 equals the unpaid list |
| 10 | VAT reclaimed with no VAT number | Warning on an invoice that charges VAT with no VAT registration number read. | Tests; Dave's Skips flagged |
| 11 | Reverse charge | A row can be marked reverse charge (the reader sets it, or a non-UK VAT number does; Edit has a tick box). The VAT goes to boxes 1 and 4 and the value to box 6. A currency row now mentions import VAT. | Tests; Google invoice re-read: £11.04 in boxes 1 and 4 |
| 12 | Overpayment refund coded to Sales | A line going the other way for exactly the amount overpaid, to the same person, clears the credit. | Tests; Marlow: Sales £21,750, nothing owed to Hartwell |
| 13 | Personal receipt booked to the business | The reader gives who a document is addressed to; a company's purchase addressed to someone else is a warning. | Tests; Currys receipt re-read and flagged |
| 14 | Documents read wrong | VAT charged before a voucher is booked with a warning instead of blocking the books. An asset under £100 and a meal of £50 or more on Subsistence are warnings. The reader is told: the supplier is not the waiter, describe items as printed, under £100 is a cost, promotional goods are advertising. | Tests; Acting Office: books no longer blocked, 2 small assets and 1 meal flagged |
| 15 | One problem row blocks Bank and Overview | Both show, worked out without the problem rows, and say how many are left out. Closing a year names the row in the way. | Tests; Bad Refs Ltd |
| 16 | VAT registration has no date | "VAT registered from" on the client: rows before that day book no VAT and are left out of the VAT figures. | Tests |
| 18 | Chat slips | New tool gives the VAT boxes as the VAT card shows them. The trial balance tool gives the books as they stand when rows changed since the last posting. A part payment since paid in full is a note, not a warning. The prompt covers dividends, and saying a question was asked. | Three questions re-asked live: all three answers agree with the pages |
| 19 | Suggest-only review says it made the changes | The review is told it only suggests. "Apply all" button on a run with more than one suggestion. | Live: summary reads "I suggest dropping..."; Apply all applied 3 |

The five new judgement warnings (no VAT number, VAT above 20%, small asset, meal, addressed to someone else) each
have an "It's fine" button, so a person who has looked can clear one.

Not done, because each is a feature and not a fix:

- Issue 17, partner accounts and profit share for partnerships.
- From issue 16: VAT schemes (flat rate, cash accounting) and VAT quarter settings.
- From issue 8: splitting interest out of finance repayments.
- From issue 14: an invoice that says it was paid by a card the client has is still unpaid until that card's
  statement is added; the invoice number the reader missed can't be fixed by a rule.

Backend 1,556 tests pass, frontend 116, on the local throwaway MongoDB.

## Status of the medium and low issues (fixed 12 Nov, not committed)

| # | Issue | What changed | Checked |
|---|---|---|---|
| 20 | Journals with no checks | A journal on a bank account, a VAT account, Debtors or Creditors carries a note saying what it leaves out of step. A row typed in more than a year ahead, or for a billion pounds or more, is refused. | Tests; test server refuses both |
| 21 | Invoice dated in a later year | A document dated after the year today is in gets a warning, with "It's fine". | Tests; the HSS invoice of 2 Apr 2027 flagged |
| 22 | Mileage claim held for a receipt | A mileage claim line is booked as its own record. Wages to one person are no longer offered another person's claim (an initial was matching the surname). | Tests; Marlow: Travel £144, no suggestion on S Marlow's wages |
| 23 | Rates asked for a VAT invoice | A cost that carries no VAT (rates, insurance, rent) asks for "its receipt or invoice". A cheque in Suspense is unchanged: what it bought isn't known. | Tests; Rushmoor BC |
| 24 | Like names not matched | A payment of an invoice's exact amount within a week, from a name sharing a real name word (not a trade word), pays it. | Tests; Google £55.20 now paid |
| 25 | Returned direct debit | A payment and the same amount back within two weeks cancel: no receipt needed, cost nil. | Tests; Marlow: Gas nil, one payment left waiting |
| 26 | "Tip or service charge" on zero-rated goods | The note now says zero-rated or exempt items first. | Tests |
| 27 | Invoice number read as a date | A reference like PE-2026-0619 in a file name is not a date. When the AI confirms the date a document prints, the file-name question closes. | Tests; Marlow: no file-date question left |
| 28 | First year end unchecked | Must be within 10 years back and 2 ahead, and can't move so that booked rows drop out. | Tests; 1990 refused |
| 29 | References not validated | Company number, UTR, VAT number and PAYE reference are checked for shape. | Tests; "ABC" refused |
| 30 | No prompt for prepayments | A note on an insurance bill of £300 or more, or a bill worded annual, 12 months or in advance. | Tests; the Aviva invoice |
| 32 | No-op decision in the audit trail | Setting a date a row already has is refused unless it settles a file-name question. The prompt forbids test calls. | Tests |
| 33 | Data error shown as "API is not running" | Any server fault now answers with a plain message, and the "could not be reached" text no longer mentions `python server.py`. | Tests pass; not triggered live |

Not done:

- Issue 31 (speed): five documents are read at once, set by `LEDGERSYNC_MAX_PARALLEL_JOBS`. Raising it depends on
  the model provider's rate limits, so it was left as it is.
- From issue 30: accruals are not prompted for; only costs paid ahead.
- From issue 32: the chat can still say "row 33" if the model ignores its instruction; nothing strips it.

Backend 1,574 tests pass, frontend 116, on the local throwaway MongoDB.

## What was tested

| Client | Set-up | Documents |
|---|---|---|
| Marlow Builders Ltd | Ltd, VAT registered, YE 31 Mar 2027, one bank account | 28 files written for this test: two NatWest statements that overlap by a month, 5 sales invoices (part payments, one receipt for two invoices, overpayment, domestic reverse charge, retention), CIS subcontractor invoice, van on hire purchase, loan agreement, mixed-rate invoice, revised invoice, copy invoice and reminder letter, supplier statement, remittance advice, quote, personal receipt, invoice with no VAT number, mileage claim, insurance, reverse-charge software, next-year invoice |
| Rosa's Cafe | Partnership, VAT registered, YE 31 Mar 2027, bank + till cash | 9 files: two weekly till Z-readings, SumUp payout report, Co-op statement, mixed-rate food invoices, energy bill with CCL, rent, staff dinner |
| Acting Office Limited | Ltd, VAT registered, YE 31 Dec 2026, bank + Amex | The 11 real files in `Test -realdocs` (2 photos, 1 scanned PDF, 8 PDFs) |
| Bad Refs Ltd | Empty client | Paste text, journals, close, reopen, archive, restore |

Flows covered this time that round 1 did not: Paste text, Suggest-only review, reopen year,
archive and restore, overlapping statements, real scanned documents, journal edge cases.

## What worked well

- Part payments, one receipt paying two invoices and an overpayment were all matched correctly.
- Quote, remittance advice and supplier statement were recognised and not booked.
- Copy invoice + reminder letter: the rules first kept the reminder (no VAT), then the AI review
  swapped to the real invoice, so rent and its £600 VAT ended up right.
- Mixed-rate documents (till readings, Bidfood, Booker) were split into zero and standard rated by
  the AI review, with quotes from the document.
- Overlapping statements: the AI review found all 11 repeated lines in 51 seconds and kept the line
  each receipt was matched to.
- Real documents: totals, dates and VAT were right on 10 of 11 (US-format date, crumpled till
  receipts, a photographed parking receipt, an expenses invoice split into travel and subsistence).
- Paste text: one paste holding a euro invoice (German number format) and a sales credit note was
  split into two rows, the euro one held for a sterling amount, the credit note taken off Sales.
- Capital purchases went to fixed assets (van, table saw, firewall). Insurance, bank interest,
  corporation tax, VAT repayment, director's loan, HMRC Self Assessment (to Drawings) all coded right.
- Closed-year locks, archive locks and reopen all held.
- Chat on Haiku answered in 30 seconds to 2 minutes and quoted the books accurately most of the time.

## Critical: wrong figures, or the books stop working

1. **A CIS subcontractor invoice crashes the client's books.** Trial balance, Bank and Overview
   return an error for the whole year, the page says "The Super Accountant API is not running or
   failed. Check that `python server.py` is running", and the AI's overview tool fails too.
   Excluding the rows does not help; only deleting the upload does. Cause: for an invoice that is
   not a VAT invoice, `evidence_rules.journal_with_rule` sets net = gross, which drops the CIS
   amount, so `posting.journal_for` raises "does not balance: 800.00 != 1000.00".
2. **The CIS deduction is applied to every line of the invoice.** £200 was taken off both the labour
   row and the materials row: cost £1,400 instead of £1,200, CIS payable £400 instead of £200.
3. **Takings are counted twice for a till business.** The weekly Z-readings (all takings) and the
   SumUp payout report (card sales) both post to Sales: £12,226.67 against a true £6,666.67. The
   SumUp sales carry no VAT. The Z-reading posts the whole week's takings straight into the bank
   account, including cash not banked and card money still with SumUp. "Cash banked" posts bank to
   bank and blocks the trial balance. The background review missed the double count; the chat found
   it only when asked.
4. **Overlapping bank statements are booked twice** until each line is approved: the bank was
   £8,629.60 out. The page says "lines are missing before it", which is the wrong diagnosis, and that
   message stays after the duplicates are removed.
5. **An £8,000 dividend to the director was matched to his £144 mileage claim.** It posts to
   Expenses Owed to Staff with "The employee owes you £7,856.00"; Dividends is untouched.
6. **A receipt with no bank line is booked as paid from the main bank account.** The Currys receipt
   put the bank £499 out against its statement, and the Bank page gives no pointer (it lists
   statement lines only). On the real documents, five receipts paid on personal and credit cards put
   the current account £220.33 overdrawn. Nothing asks who paid.
7. **A revised invoice is booked on top of the original.** Ashdown A-551 (£360) and "A-551 REVISED,
   replaces the invoice" (£240) are both in: purchases £380 instead of £200, VAT £100 instead of £40,
   £240 shown as owed. The review did not flag it. The chat could not remove the original even after
   two explicit confirmations ("the invoice doesn't rank above the invoice").

## High: an accountant would be misled

8. **Finance agreements are read as invoices.** The hire purchase agreement became a £3,600 invoice
   on Vans (van £21,600 instead of £18,000) and the monthly HP payments were matched to it as part
   payments. The financed £18,000 stays in trade creditors as an unpaid purchase. The loan agreement
   shows in Invoices as a £20,000 credit note. Interest is never split, though both agreements print
   it. The AI asked a good question about the van, but after the answer it still could not remove
   the row and asked again.
9. **A deposit linked to its invoice is still held in Suspense**, asking for "the full VAT invoice"
   that is already uploaded and linked. Creditors is £3,600 away from the unpaid list.
10. **VAT is reclaimed on an invoice with no VAT registration number** (Dave's Skips, £50) with no
    warning. Asked directly, the AI said it could not rely on memory for this rule.
11. **Reverse charge on services from abroad is not accounted for** (Google Ireland £55.20, LinkedIn
    Ireland £264.98): boxes 1 and 4 both miss the VAT and no note says so. The euro goods invoice got
    no import VAT note either.
12. **A refund of a customer's overpayment is coded to Sales** instead of clearing the £100 credit:
    Sales £100 low, the customer still shown £100 in credit.
13. **A personal receipt is booked to the business.** Addressed to the director at home (the file is
    even named "personal"), it went to Office Equipment with VAT; the only question was for a fuller
    invoice.
14. **Real documents, what was read wrong:**
    - The restaurant's name was taken from the waiter's name on the receipt ("Maisei").
    - A Logitech ERGO M575S (a mouse) was described as a "chair" and capitalised in Furniture.
    - A £9.67 cable and a £20.99 item were capitalised: there is no capitalisation threshold.
    - 400 promotional charging cables (£1,499.84) went to Office Stationery.
    - An Amazon invoice with a marketplace-funded promotion (VAT £1.70 on £8.48, £9.67 paid) was
      flagged "VAT impossible", its VAT dropped, and it blocked Bank and Overview for the client.
    - The LinkedIn invoice says "paid by AMEX ****1006"; the client has an Amex account, but it was
      left as an unpaid creditor.
    - Invoice number 0095 was not read on the expenses invoice.
    - A restaurant meal with wine went to Subsistence with VAT reclaimed and no question about
      entertaining.
15. **One problem row blocks Bank and Overview** while the trial balance page shows with a "left
    out" note. Closing the year is refused with "The trial balance must balance" when it does balance.
16. **VAT registration is yes or no, with no date.** A client who registers mid-year cannot be kept;
    switching it rebooks the whole open year. There is no VAT scheme (flat rate, cash accounting) and
    no VAT quarter setting.
17. **Partnerships have no partner accounts.** Both partners' drawings and capital share one
    account each, and there is no profit share.
18. **Chat slips (Haiku):** said invoice 1001 was "still £4,200.00 short" (it is paid; the part-payment
    warning stays on the first receipt); quoted VAT boxes 6 and 7 as £21,750.00 and £23,577.53 when
    the VAT card shows £21,753.12 and £28,520.53; said the trial balance showed £530.00 Sales VAT
    (it shows £1,113.33); left £1,900 out of drawings; said "I've asked you two things" when no
    question was created; would not say whether a dividend could be paid.
19. **Suggest-only review says it made the changes.** The summary reads "I dropped the later copy
    each time... Nothing is left for you to answer" while all 11 wait for Apply. There is no "Apply
    all": 11 separate clicks.

## Medium and low

20. Journals are accepted straight to a bank account, to VAT control and to Debtors with no warning
    (the VAT figures leave journals out, so the return and the VAT account can disagree). A journal
    dated 2031 silently opened five future years. £99,999,999,999.99 was accepted.
21. An invoice dated 2 Apr 2027 (in the future) opened next year with no flag.
22. A mileage claim was held in Suspense asking for "the receipt or invoice"; the claim is the
    document. A wage payment to S Marlow was suggested as paying M Marlow's mileage.
23. Business rates and a cheque over £250 ask for "a full VAT invoice"; rates carry no VAT.
24. "Google Workspace Ireland" (bank) was not matched to "Google Cloud EMEA Limited" (invoice):
    same £55.20, three days apart.
25. A returned direct debit is credited to Gas while both payments wait in Suspense: Gas shows -£210.
26. The mixed-rate warning says "a tip or service charge" for zero-rated goods.
27. An invoice number in a file name ("PE-2026-0619") was read as a date (19 Jun) and raised as a
    date conflict, in the review and again in chat.
28. The first year end can be changed with rows booked, and set to 1990, with no check at the API.
29. Reference numbers are not validated (company number "ABC", VAT number "GB 12" accepted).
30. No prompt for prepayments or accruals (12-month insurance paid in May, rent paid a quarter ahead).
31. Speed: 47 documents took about 12 minutes to read, five at a time.
32. The agent logged a no-op decision ("Placeholder check only") in the audit trail, and the chat
    showed a row id ("row 33").
33. A data error is shown to the accountant as "the API is not running... check `python server.py`".

## Tests

The full backend run from the last fixing round finished: 1,511 passed, 6 failed, 1 error. Five were
tests that add two clients with the same name, which the new duplicate-name check now refuses; those
tests now use different names. The other two passed when re-run on their own. The four affected
test files were re-run after the change and all 145 tests in them pass; the whole suite was not
run again.
