# Bank and payment exports read in code (design, 2026-11-23)

## Why

The test books' agency year (runs/2026-11-23-agency-first) showed the reader is slow and can misread structured files:

- Every bank, card and Stripe CSV went to the model as text, at thinking "high", to be copied out row by row. A
  30-line statement took 13,000-18,000 output tokens and 5-17 minutes; one hit the 32,768-token cap after 15 minutes
  and was cut short. At the 60-second default every one of them timed out.
- January 2024's Stripe export was misread: its charges were dated by their payout and grouped wrongly, which left
  the 12 March payout unmatched (the year's last blocking error after the five matching fixes of 2026-11-23).

A CSV states its dates, amounts and balances exactly. Reading them in code makes them always right, and leaves the
model only the judgement: which account and which payee each line is.

## Goals

- Any bank's or card's CSV or spreadsheet export is recognised by its column headings, not by a list of named banks.
- Dates, amounts, directions and balances come from code, exactly as the file states them.
- The model is asked only for each line's account, payee and alternatives, in small requests at low thinking, so a
  statement is coded in seconds and costs a small fraction of today.
- Payment processor exports (gross, fee and net on each line: Stripe, PayPal, SumUp and the like) are built entirely
  in code, with no model call.
- What comes out is the same `TransactionExtractionResult` the reader returns today, so the adapter, checks,
  matching and everything after them are unchanged.

## Non-goals

- PDF statements (with a text layer or scanned) stay with the model as today.
- OFX, QIF and other non-table formats.
- Coding lines by rules (the client's usual account for a payee, keywords): the model still codes every line.
- Re-reading files already saved; new uploads and re-reads take the new path.

## Anti-goals (a failure even if it runs)

- A wrong sign, date or amount saved silently. When the file can't be read with certainty, it goes to the model as
  today, never a guess.
- A row of the file dropped or added. Every payment row of the file becomes exactly one row.
- A file that reads well today reading worse.

## Approaches considered

- **A. Code reads the rows, the model codes them (chosen).** Exact figures, fast, and the model keeps the judgement.
  The largest of the three changes.
- B. Code reads and codes by rules, the model only for lines rules can't code. Cheapest, but coding is weak for a new
  client and the rules are a lot to write and keep; mistakes move from reading to coding.
- C. The model keeps reading, in chunks of about 15 rows at low thinking, in parallel. Smallest change, but still
  paid and slow-ish, and it can still misread a row (as it did January's Stripe export).

The user picked A.

## Design

### 1. Recognising a table (new module `ledgersync/tables.py`)

Input: the text `intake` already makes of a CSV, TSV or spreadsheet (cells comma- or tab-separated). Output: a
`Table` with its layout and rows, or None (not recognised: the model reads it as today).

- **Header row:** the first row, among the first 15, whose cells name a date column and either an amount column or a
  paid in / paid out pair. Lines before it (a bank's account name, number, period) are kept as the statement's
  heading text for the model's context.
- **Column roles, by heading** (case and punctuation ignored, first match wins):
  - date: Date, Transaction Date, Posted Date, Posting Date, Value Date, Completed Date, Created, created_utc
  - description: Description, Details, Narrative, Transaction Description, Payee, Name, Merchant, Memo, Reference
    (several may be present: all of them are joined, in file order, as the line's text)
  - amount: Amount, Value, Amount (GBP), Transaction Amount
  - paid in: Paid In, Money In, Credit, Credit Amount, In
  - paid out: Paid Out, Money Out, Debit, Debit Amount, Out
  - balance: Balance, Running Balance
  - type: Type, Transaction Type
  - currency: Currency
  - processor columns: Gross, Fee, Net (all three present), and a category column (reporting_category, Type)
- **Dates:** UK day first (dd/mm/yyyy, dd-mm-yy, dd Mon yyyy, d Month yyyy) and ISO (yyyy-mm-dd, with or without a
  time). A whole column is read with one format; if any value would need a different one, or a value isn't a date,
  the table is not recognised.
- **Amounts:** "£1,234.56", "1234.56", "-12.00", "(12.00)", "12.00 CR", "12.00 DR", blank (none on that side).
  Anything else in an amount cell: not recognised.
- **Rows that aren't payments:** blank rows and rows with no amount (a "Balance brought forward" line, a total) are
  not transactions. A brought-forward line's balance is the opening balance.

### 2. Direction

- **Paid in / paid out columns:** the column says it.
- **One amount column:** for a bank account, positive is money in. For a credit card (the upload's account is a
  card), positive is money spent and negative is a payment or refund: Amex exports this way. When the account isn't
  known yet (a client with several accounts who hasn't said which), only the balance check below can settle it;
  with no balance column the table is not recognised, the model reads it, and the app asks which account as today.
- **Check by the balance:** when there is a balance column, each line's signed amount must take the previous
  balance to its own, in the file's order or in reverse (exports run newest first as often as oldest first). If the
  chain fails with the rule above and holds with every sign flipped, flip them. If it holds neither way, the table is
  not recognised.
- **Currency:** a currency column other than GBP on a line: that line keeps its currency, as the reader gives it
  today.

### 3. Balances

From the balance chain: the opening balance is the earliest line's balance less its signed amount (or a
brought-forward line), the closing balance is the latest line's balance. With no balance column, both are None, as
when a statement prints none.

### 4. Coding by the model (new method on `TransactionExtractor`)

One request per 50 lines, at `reasoning_effort` "low", with:

- the same instructions the reader has today for bank lines (rules 2-6: whose books, document types, accounts, the
  chart, the client's bank accounts and owners), cut to what applies to a bank line;
- the statement's heading text and the account it is for (current, savings, card);
- a numbered list: `n | date | in/out | amount | text`.

The answer schema: `{"lines": [{"n", "account", "counterparty", "alternatives", "bought", "people"}]}`. Each answer is
joined to its line by `n`; the date, amount and direction always come from code. A line the answer leaves out, or a
number it doesn't know, is coded 9998 Suspense with a warning, never dropped. The rows are then built as
`AccountingTransaction`s with document_type "statement", so the adapter treats them as it treats a statement read
today.

### 5. Payment processor exports (no model)

A table with Gross, Fee and Net columns and a category column:

- a charge or sale line: an `agent_statement` row "in" on 4000 Sales for its gross, and, when its fee isn't nil, a
  row "out" on 7901 Bank Charges for the fee, both with the line's id (or its row number) as document_number and its
  net as document_total;
- a refund line: "out" on 4000 for its gross, with its fee as above;
- a payout line: not a transaction (the net paid over, as the reader's rule says today);
- any other category (an adjustment, a dispute): coded 9998 Suspense with a warning, for a person.
- The agent: the processor named in the file name or the heading text (Stripe, PayPal, Square, SumUp, Zettle,
  Shopify, GoCardless), else "Payment processor".
- Each line is dated by its own date (created), never by its payout.

### 6. Where it plugs in

`pipeline.analyze` gains the upload's account (`server.run_analysis` already works it out as `own` before reading:
the account the person chose, or the client's only one; None otherwise). For an intake of kind "table", try
`tables.read(text, account_kind)`, where the kind (current, savings, credit card) comes from that account. Recognised: a processor
table is built in code; a statement is coded by the new method. Not recognised: today's path, unchanged. A warning
on the result says which path read the file ("Read in code: 31 lines" / "Columns not recognised: read by the model").

## Constraints

- No new dependencies: Python's `csv` module and the `intake` text the app already makes.
- The reader's output shape (`TransactionExtractionResult`) and the adapter don't change.
- Tests: targeted files only (the app's full suite takes about 55 minutes). Each HSBC, savings, Amex and Stripe
  layout in the test books gets a test, plus headings from other UK banks (Barclays, NatWest, Lloyds, Monzo,
  Starling, Tide).
- Spending: checking on the test books' agency year means re-reading its 42 statement files through the model's
  coding step, a few cents; it needs the user's yes before it runs.

## Left to the builder

- The exact heading synonyms beyond those listed, and the date formats' edge cases.
- How the coding prompt is cut from the reader's instructions, as long as the bank-line rules are kept word for word.
- Whether the 50-line batches run one after another or in parallel within a job.
- The wording of warnings.

## Calls I made (to check)

- A file that can't be read with certainty goes to the model, not to a person.
- Processor charges go to 4000 Sales and fees to 7901 Bank Charges, as the reader's rule codes them today.
- A card's export with one amount column takes positive as spending.
- 50 lines per coding request.
