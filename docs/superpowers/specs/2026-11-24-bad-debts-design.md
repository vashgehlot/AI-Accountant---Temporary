# Bad debts: writing off a customer's unpaid invoice, and recovering part of it (design, 2026-11-24)

## Why

The test books' agency year (EC-0363, EC-0705): Lowther Interiors Ltd never paid its £4,800 invoice (£4,000 + £800
VAT, 5 June 2023) and went into administration. The key writes it off on 31 January 2024 (Dr 8100 Bad debts
£4,000, Dr 2201 VAT £800 bad debt relief, Cr 1100 Debtors £4,800) and books the administrator's £1,200 dividend
of 20 March 2024 as a recovery (Cr 8100 £1,000, Cr 2200 £200). The app has no bad debt handling, so:
- December to February's box 4 is £800 short (no bad debt relief);
- Debtors is £3,000 too high and bad debts £3,000 too low;
- the £1,200 dividend was booked as a sale with no VAT (sales £1,200 too high).

## Goals

- The app notices a sales invoice that is long overdue and asks whether to write it off.
- A write-off settles the invoice, books the bad debt and claims VAT bad debt relief in the quarter of the
  write-off.
- A later payment from that customer is a recovery, not a sale.
- One decision, undone in one step.

## Non-goals

- Reading insolvency letters (the administrators' notice) to ask earlier: a later step.
- Part write-offs, and writing off what a supplier is owed.
- Bad debt relief checks beyond the six months (the claim's records, notifying the customer).

## Anti-goals

- VAT relief claimed on an invoice whose VAT was never paid to HMRC (not a VAT-registered client, or no VAT on the
  invoice).
- An invoice still shown as owed after it is written off, or a recovery taken as a part payment of it.

## Approaches

A (chosen): the write-off is a decision about the invoice, made by answering a question; matching treats the
invoice as settled and a later payment from the customer as a recovery. B: journals that point at the invoice,
with matching taught to let a journal settle a document. C: the question only, the person entering the journals by
hand. The user picked A. Refinement: the VAT return places each row in a quarter by its own date, so the write-off
is its own row, dated the day of the write-off and tied to the invoice (not a field on the invoice row, which
would put the relief in the invoice's quarter). Undoing it is removing that row.

## Design

1. **The question.** For each booked sales invoice (direction in, on Debtors) still owed, more than six months
   past its due date (no due date is recorded: the invoice date plus 30 days), the year's questions ask "Write off
   the £4,800.00 Lowther Interiors Ltd owes as a bad debt?", why: the invoice (number, date), unpaid since, and
   that VAT bad debt relief can be claimed once it is written off. Kind `bad_debt`, about the invoice's row.
2. **The answer.** `write_off` with a date (on or after the six months, inside the year; default the day of the
   answer) adds the write-off row; "Not sure" leaves the question waiting, as today.
3. **The write-off row.** A new document type `write_off`: dated the write-off date, gross = what is still owed,
   account 8100 Bad Debts, contra 1100 Debtors, counterparty the customer, `writes_off` = the invoice's
   document_ref. VAT: the invoice's VAT share of what is owed (owed × VAT ÷ gross), booked to 2201 Purchase VAT as
   relief when the client is VAT registered and the invoice charged VAT; otherwise none.
   Posting: Dr 8100 the net, Dr 2201 the relief, Cr 1100 the gross. The VAT return takes the relief in box 4 of
   the write-off's quarter, and not the net in box 7.
4. **Matching.** A write-off row settles its invoice exactly (a Settlement of kind `write_off` on the invoice), so
   it is no longer owed and no question asks again.
5. **A recovery.** A bank line in from the customer, with no other open document of theirs, after a write-off of
   theirs: posted against the write-off, not as a sale. Cr 8100 the net share and Cr 2200 Sales VAT the VAT share
   (the same fraction as the write-off's), with a note. Up to the amount written off; more than that is left to
   matching as today.
6. **Undo.** Removing the write-off row (as any row is removed) reopens the invoice, and its question.

## Constraints

- No model calls; targeted tests only (the full suite takes about 55 minutes).
- The question form on the page: a date and "Write it off", beside "Not sure".

## Left to the builder

- Where the overdue rule lives (questions, beside the opening balances question).
- The exact wording of notes and warnings.
- How the write-off row is added (ledger.add_manual or a small service of its own).

## Calls I made (to check)

- Due date taken as the invoice date plus 30 days.
- The recovery's VAT goes to 2200 Sales VAT (box 1), as the key does, not back off box 4.
