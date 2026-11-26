# UAT findings, 10 Nov 2026: testing as a UK accountant

Tested through the UI at `localhost:3013` (API `8100`) on a throwaway local MongoDB
(`ledgersync_uat_nov10`), model `qwen/qwen3.8-27b`. Nothing touched the real database.

## Status of the critical issues (fixed the same day, not committed)

| # | Fix |
|---|---|
| 1 | Folder import puts each file on the account its name points at (`folder.account_for`), else the one chosen. A credit on a card worded as a payment is a transfer from the bank (`adapter._recoded`); moving a statement onto a card recodes such lines (`ledger.set_upload_bank`); any other credit on a card still coded to income is flagged "Money in on a card". |
| 2 | Edit row converts an amount to pounds: the dialog says what was read and saving sends `currency: GBP`. The document's printed foreign totals are set aside and come back on Revert. |
| 3 | A document not in pounds is paid by nothing until it is converted (`matching._documents`). |
| 4 | Foreign legal forms (SARL, GmbH, Inc…) are no longer part of a payee's name, and an abbreviation must start the word or end as it ends, so "sarl" no longer matches "Starling". |
| 5 | Close year first lists what is unsettled: rows to review, rows with no date, Suspense, a bank away from its statement, missing statements. The button reads "Close anyway". It does not block. |
| 6 | Add by hand has a required Date and a Paid from / Paid into choice: one of the client's accounts, or the owner's own money (Director's Loan Account for a company, Capital Introduced otherwise), which leaves the bank agreeing with its statement. |
| 7 | The chat prompt carries the nine VAT boxes and the s455 facts, and is told never to give a rate, threshold or deadline from memory. Not re-tested against the live model. |
| new | Found while fixing: the AI review dropped the two salary bank payments as "duplicates" of the payroll lines, leaving the bank £4,750.00 off its statement. A payroll line and the bank line that pays it are no longer flagged as possible duplicates, and the keep-one resolution refuses the pair. |

## Status of the high issues (fixed the same day, not committed)

| # | Fix |
|---|---|
| 8 | A document read as a receipt that prints "VAT invoice" or "tax invoice" is booked as an invoice (`adapter._invoices_as_printed`), and the reader's prompt says so. The "over £250 needs a full VAT invoice" rule is unchanged. Applies to files read from now on. |
| 9 | A bank line under £50 on a VAT-bearing cost, for a VAT-registered client, carries a note: "No VAT reclaimed… add its receipt or invoice to reclaim up to £x". |
| 10 | Self Assessment payments go to the owner (Director's Loan Account or Drawings). For a business that is not a company, so do a mortgage, council tax and a TV licence, even when read as a loan repayment. Applies to files read from now on. |
| 11 | Invoices lists a credit note as one, with minus amounts; its row says "A supplier's credit note… check that is the account its invoice is on". It is still coded as the model read it. |
| 12 | A problem that stops the trial balance names its row (description, date, amount) instead of "#4". An error row still blocks the trial balance. |
| 13 | Missing paperwork lists the months with no statement lines before a statement that prints no balance. The Bank tab says its statements print no balance, not "No statement this year". Months after the last statement are not reported. |
| 14 | An overdrawn balance reads "£2,887.11 overdrawn"; a card's reads "owed" or "in credit". |
| 15 | The tile reads "Net loss (£209.60)". |
| 16 | A debit Suspense balance is counted with the assets, not taken off liabilities. |
| 17 | Edit row has a VAT treatment (standard, reduced, zero-rated, exempt, outside the scope), shown under the row's VAT. Reverse charge is recorded as outside the scope; there is still no VAT return. |
| 18 | The Account column reads "Suspense, then Rent" for a held row and "Booked from its document" for a line its receipt books. |
| 19 | A change the checks refused is counted, not quoted. The chat is told never to cite row ids to the person. Summaries saved before this still say "row 13". |
| 20 | A review still running no longer says "Nothing to change". |
| 21 | Not fixed: the time is the model's. |

## Status of the coverage gaps (11 Nov, not committed)

| # | Status |
|---|---|
| 22 | Done. "Add journal" on the Trial balance page: a date, a description, an account to debit, one to credit, an amount. No VAT, no document asked for, listed in Transactions as a Journal. Only its date, description and amount can be edited; remove and re-enter to change accounts. The chat still can't post one. |
| 24 | Done. A profit and loss account and a balance sheet under the trial balance, worked from it. Not in the Excel export. No drill-down from a line to its rows. |
| 26 | Not an issue: the opening balances list does offer every account and card the client has. The finding was wrong. |
| 29 | Partly. The Overview points out Loans in debit. Repayments are still not split between capital and interest. |
| 23, 25, 27, 28, 30, 31, 32, 33 | Not started: each needs a decision on scope first (VAT return and periods, an editable chart, opening debtors without itemising, due dates and ageing, payments on account, payroll per person, more client fields, login). |

## Features built on the recommended scope (11 Nov, not committed)

| # | What was built | What it does not do |
|---|---|---|
| 12 | The Trial balance page still shows while rows need fixing, without those rows, and names each one left out. | The year still can't be closed, and the bank still can't be checked, until they are fixed. Other callers of the route get the 422 as before (`?shown=true` is the page's mode). |
| 23 | "VAT return figures" on the Trial balance page for a VAT-registered client: the nine boxes for the whole year or one of its four quarters, from the rows booked in the period. | A guide, not a return. No schemes, no filing, boxes 2, 8 and 9 are nil, and the quarters follow the accounting year, not the client's VAT stagger. Rows held in Suspense are not in it (it says how many). |
| 25 | Sixteen standard accounts added: plant and machinery, stock, deferred income, hire purchase, bank interest received, subcontractor costs, water, vehicle repairs, vehicle insurance, exchange differences, bad debts, staff welfare, sundry expenses. | The chart is still fixed: a client can't add or rename accounts. |
| 27 | Opening Debtors and Creditors can be more than the invoices listed, or have none listed. The rest is brought forward as one "Not itemised" balance, shown in Invoices, and offered on unmatched bank lines in the first 120 days to link. | Nothing is matched to it automatically. |
| 28 | Invoices shows how many days each unpaid invoice has been owed, and totals by age (up to 30, 31 to 60, 61 to 90, over 90 days). | By invoice date. Due dates are not read. |
| 30 | A bank receipt worded as a payment on account, a deposit or an advance is held on Debtors as a credit, not booked as a sale, with a note to link it to its invoice. | Recognised by wording only, on files read from now on. |
| 31 | A payroll report read from text: each person's pay, tax and pension must add up to a gross the report prints, or their first line is flagged. | Needs the lines to name two people or more; not checked on a scanned image. |
| 32 | Company number, UTR, VAT number and PAYE reference on the client, in the form and on Overview. | Stored and shown only. |
| 33 | Login: left as it is, as recommended. | |

## Status of the low items (11 Nov, not committed)

Fixed: 34 (phone number checked), 35 (a name another client has is refused in the form; the API still allows it),
36 (table dates read "14 Oct 2026"; date inputs still follow the browser), 37 (rows listed by date, with a switch
back to the order read; no search yet), 39, 40, 41, 44 (wording only; sidecar files are still listed as unreadable),
45, 47 (the export's title names the year; the file name is unchanged), 48, 51, 53.

Fixed later: 24 (the Excel export has a Profit and loss sheet and a Balance sheet sheet), 35 (the API also refuses a
name another active client has), 42 (a payment coded to tax, a loan or the owner is no longer offered as the payment
of a supplier's later invoice), 43, 46 (the Overview count now says it is questions waiting for an answer).

Not fixed: 38 (the table scrolls sideways at 1024px, as designed), 49, 50, 52, 54, 55.

## What was tested

| Client | Set-up | Documents |
|---|---|---|
| 1. Northbridge Consulting Ltd | Ltd, VAT registered, YE 31 Mar 2027, one bank account | The repo's demo set (`demo/northbridge/documents`), opening balances from the demo |
| 2. Kestrel Design Ltd | Ltd, VAT registered, YE 31 Dec 2026, current + savings + Amex card | 15 files written for this test: Q1 Starling statement (35 lines), Amex statement, sales invoices (20% and EU reverse charge), purchase invoice, credit note, wrong-VAT invoice, pro forma, USD invoice, prior-year invoice, payroll summary, dividend voucher, entertaining and fuel receipts |
| 3. Hollis Plumbing | Sole trader, not VAT registered, YE 5 Apr 2026 | CIS sales invoice, supplier invoice with VAT, Lloyds statement spanning the year end, plus an empty CSV, a corrupt PDF and a .docx |

Flows covered: add/edit client, opening balances, folder import, Add by hand, transactions edit,
AI review, chat, bank, invoices, trial balance, Excel export, close year and carry forward,
dark mode and phone width.

Not tested: drag-and-drop upload and Paste text (folder import was used instead), reopen year,
archive/restore, the "Suggest only" review mode end to end, real scanned photos beyond the demo's.
The AI review of client 2 was still running after 4+ minutes when testing stopped, so its
decisions on that client were not seen.

## What works well

- Bank line coding was right on almost every line of a hard statement: HMRC VAT, PAYE and
  corporation tax to their liability accounts, director's personal Self Assessment and Netflix to
  the DLA, dividend, transfer to savings, card pay-off, Stripe payout to clearing, parking fine to
  Fines and Penalties.
- Entertaining VAT blocked and kept in cost. CIS deduction booked correctly. Pro forma not booked.
  Invoice dated before the first year not booked again. Impossible VAT (£250 on £1,250) caught.
- A non-VAT-registered client's purchase booked gross.
- Payroll summary booked to wages, PAYE, net wages and pension control accounts; all four cleared
  to nil against the bank payments.
- Rows split across 5/6 April into the right years. Year close carried profit to Owner's Capital.
- Bad files refused with clear messages. Re-importing a folder skips files already read.
- Opening balance validation (balanced, balance sheet accounts only, debtors itemised).
- Closed-year locking holds on rows and on VAT registration.
- The AI review on the demo set made the four expected changes, each with quoted evidence and Undo.

## Critical: wrong figures in the books

1. **Card statement imported into the current account, card payment booked as a sale.**
   Folder import puts every statement on the account selected in "Add to" (the first account).
   The Amex statement landed on Starling current, and "PAYMENT RECEIVED - THANK YOU £850" was
   coded to 4000 Sales. Moving the upload to the Amex account afterwards (Documents, "On") changed
   the account but not the coding: Sales stays overstated by £850 and the card shows £850 instead
   of nil, because the pay-off is now counted from both sides.
2. **A foreign-currency invoice can't be fixed and blocks the whole trial balance.**
   The USD invoice is flagged "Not in pounds. Convert USD to GBP." The Edit dialog has no currency
   or rate field. Editing the amount to the sterling figure leaves the flag, adds a "total
   mismatch" flag, and the trial balance still refuses to show. The only way out is to remove the row.
3. **USD invoice matched against sterling as if same currency.** The £396.42 card payment was
   treated as a part payment of "£500.00", leaving "£103.58 still owed".
4. **An unrelated bank fee was linked to that invoice.** The £7.00 Starling monthly fee was
   matched as a further part payment of the AWS invoice ("Paid £7.00 of £103.58").
5. **Year can be closed with unresolved items, with no warning.** Client 3 closed with £1,624.20
   in Suspense, 5 rows flagged, one row with no date, and the bank no longer agreeing with its
   statement. The confirm dialog mentions none of it. Suspense carried into the next year.
6. **Manual "cash" entry posts to the bank account, with no date.** Add by hand has no date,
   account, VAT or paid-from field. "Van MOT paid in cash … 28 March 2026" was booked with no date
   (the date in the text was ignored), credited to the bank account, and included in the year;
   the bank balance in the books moved away from the statement by £54.85.
7. **Chat gives wrong tax facts.**
   - VAT return: it invented the box meanings (called Box 2 "output VAT on standard-rated sales",
     Box 5 "VAT due on imports", Box 6 "total VAT due", Box 7 "total VAT to reclaim"). The real
     boxes are 1 VAT on sales, 2 VAT on acquisitions, 3 total due, 4 VAT reclaimed, 5 net,
     6 sales ex VAT, 7 purchases ex VAT, 8/9 EU goods.
   - s455: it quoted a £10,000 threshold (there is none; that is the beneficial-loan benefit in
     kind limit), a 32.5% rate (33.75% since April 2022), and repayment "within 30 days of the
     year end" (relief is 9 months and 1 day). Its conclusion that the DLA was in credit was right.

## High: an accountant would be misled or blocked

8. **The uploaded invoice asks for itself.** The Apple "Receipt / VAT Invoice" (VAT number, buyer
   named, VAT shown) was read as a receipt, held in Suspense, and raised "Can you upload the full
   VAT invoice?" £2,400 of equipment and £400 VAT sit in Suspense.
9. **Input VAT silently lost under £50.** Bank lines under £50 (BT £42, Xero £36, Adobe £49.94)
   are booked gross with no VAT and no request for the invoice. For a VAT-registered client that
   is unclaimed VAT with nothing on screen to say so.
10. **Sole trader personal items miscoded.** Nationwide mortgage went to 2300 Loans (leaving Loans
    in debit) instead of Drawings. HMRC Self Assessment went to Suspense asking for "a full VAT
    invoice". The limited company equivalent was handled correctly.
11. **Credit note treated as money-in on a different account.** Printworks CN-12 was coded to
    Advertising and Marketing (the invoice is on Printing), flagged "Money in… a refund?", and is
    listed under Purchases as a positive £120.00 bill marked paid.
12. **One problem row hides the entire trial balance.** "2 problem(s) must be fixed before the
    trial balance: #1 … #4 …". The numbers are list positions with no link to the rows.
13. **Missing statements not noticed.** Client 1's year starts in April; only October's statement
    is in. Nothing flags April to September, and the chat said "No bank statement is missing".
    The Bank tab says "No statement this year" while showing nine lines from that statement.
14. **Overdrawn balance shown as positive.** Bank tab: "In the books £2,887.11; on the statement
    £2,887.11" for an account that is £2,887.11 overdrawn.
15. **Loss shown as a positive figure.** Trial balance tile "Net profit / loss £209.60" with nil
    income and £209.60 expenses. No brackets, sign or word "loss".
16. **"Assets / liabilities" tile is misleading.** Suspense is typed as a liability, so a debit
    Suspense balance reduces liabilities (client 2 API total: −£4,590.80) or is shown as a
    positive liability (client 3).
17. **No VAT treatment on a row.** Zero-rated, exempt, outside scope and reverse charge all read
    as "VAT £0.00". The EU reverse-charge sale and the AWS reverse-charge purchase are
    indistinguishable from zero-rated, so a VAT return can't be built from the data.
18. **Account column disagrees with the posting.** Brightline shows "Printing" while held in
    Suspense; the Costco bank line shows "Suspense" after it was released. The Excel export
    repeats this (Apple row: account 0030, other side 1200, though it is in Suspense).
19. **Internal agent text shown to the user.** A refused decision in AI review reads "Send the
    call with the receipt as row_id, and drop only the expenses-sheet line". Review and chat refer
    to "Row 13", "Row 14"; rows have no visible numbers.
20. **Review status contradicts itself while running.** The entry reads "Nothing to change" with a
    "Reviewing…" spinner under it.
21. **Slow.** A three-part chat question took over four minutes. Reading 15 small text files took
    about six minutes. Every Add by hand row is a model call.

## Missing for an "AI accountant" (coverage gaps)

22. **No journals.** The chat worked out depreciation (£525) and then said it cannot post it.
    No way to post depreciation, accruals, prepayments, the corporation tax charge, stock, or any
    year-end adjustment.
23. **No VAT return or VAT period.** No VAT number, scheme (standard, cash, flat rate), stagger,
    box figures, or VAT control transfer to 2202.
24. **No profit and loss or balance sheet**, only a trial balance. No nominal ledger drill-down
    from a trial balance line to its rows.
25. **Fixed chart of 80 accounts, not editable.** No stock or WIP, plant and machinery, computer
    equipment, motor expenses, bank interest received, bad debts, staff welfare, hire purchase,
    deferred income, share premium, sundry, use of home, exchange differences.
26. **Opening balances cover only the first current account.** A client with a savings account,
    card or petty cash at takeover has no line for them (list shows 1200 only).
27. **Debtors and Creditors must be fully itemised** to save opening balances. At takeover an
    accountant often has only the total.
28. **Invoices section has no due dates, ageing or overdue markers.** Short payments (£20 on the
    EU invoice, likely bank charges) have no "write off the difference" action.
29. **Loan repayments not split** between capital and interest, and no warning when a liability
    account goes into debit.
30. **Payment on account** (£1,000 from Orbit with no invoice) goes straight to Sales; no
    customer-credit or deferred income treatment.
31. **Payroll per-employee split can be wrong while totals agree.** A messy footnote led to
    director's salary £3,035 and wages £2,965 (each should be £3,000). It was flagged "worked out".
32. **Client record lacks** company number, UTR, VAT number, PAYE reference, accounting period
    other than 12 months.
33. **No login or users.** Any folder path on the machine can be set as a client folder (`/etc`
    was accepted), and its files would be sent to the model provider.

## Low: polish and consistency

34. Phone number accepts anything ("abc").
35. Two clients can have the same name with no warning.
36. Dates: the transactions table shows `2026-10-14`, the Bank tab "14 Oct 2026", date inputs
    `mm/dd/yyyy` (browser locale). An accountant in the UK expects dd/mm/yyyy everywhere.
37. Transactions are not in date order (documents first, then bank, splits appended last) and
    can't be sorted or searched.
38. At 1024px the transactions table overflows: Net is cut off and Account, Check and the
    Edit/Remove actions are off screen.
39. "No date. No date. Add one." repeats itself.
40. "Paid by card: bank line on 10 Feb" on the dividend voucher; it was a bank transfer.
41. Bank salary payments are flagged "Possible duplicate" of the payroll rows they pay.
42. HMRC Self Assessment £1,250 offered as a possible payment of the Halden furniture invoice.
43. "Booked from the receipt: NCP … (£6.50, no date)" stays after the receipt was dated.
44. After folder import the banner keeps saying "Reading 6 new files" when reading has finished.
    Sidecar `.rows.json` files are listed as "can't be read".
45. "Import from folder" also appears under the Add by hand tab.
46. Overview says "11 things need you" beside "20 of 58 transactions" to review.
47. Excel export is titled and named with today's date, not the accounting year; it has two
    sheets only (trial balance, transactions).
48. Message amounts lack thousands separators ("£1250.00").
49. CIS sale row shows Amount £1,000.00 and Net £1,200.00.
50. Chat header stays "New chat" after the thread is named; choosing a client creates an empty
    thread before anything is sent.
51. Non-VAT-registered client is asked for "a full VAT invoice".
52. ATM withdrawal goes to Petty Cash though the client has no petty cash account set up.
53. README says opening balances are on Overview; they are on Trial balance.
54. No saving indicator: after Save in Edit row the old values show for about two seconds.
55. The agent dated an undated cash taxi receipt from the photo's file name and applied it
    automatically. A file name is the capture date, not necessarily the receipt date; worth a
    question rather than an automatic change.
