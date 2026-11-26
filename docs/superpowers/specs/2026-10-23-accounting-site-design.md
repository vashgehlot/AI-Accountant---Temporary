# Super Accountant: the accounting site, by client and year

2026-10-23 · comes before the agent. The agent design in `2026-10-23-chat-agent-design.md` waits until this is built.

## Why

The accountant wants an agent that runs the whole site, but first wants the accounting underneath to be right and the site laid out the way they work: open a client, pick a year, and find that year's documents, bank lines, invoices, transactions and trial balance, each in its own place.

The existing code already does the accounting: it reads uploaded files with an AI model, matches receipts, invoices and payments, and builds a double-entry trial balance. A check of that code on 2026-10-23 found that the figures are wrong in some common cases, and that it has no idea of a year or of more than one bank account. This project fixes the accounting and rebuilds the site around it. The agent is added afterwards, in its own project, on top of a site that already works without it.

The accountant said starting from scratch is fine. The plan keeps the accounting engine, which has detailed rules and over a thousand passing tests, and fixes it. It rebuilds the website.

## What the accountant sees

### The layout (the accountant chose this from two mockups)
- A top bar on every page: the product name, **Clients**, and space on the right for the **Agent** button, which this project leaves out.
- **Clients:** the list of clients, as today, with each client's current year and whether that year is open or closed.
- **A client's space:**
  - a header with the client's name and a **year picker** beside it, for example "Year to 31 Mar 2026 ▾";
  - a **side menu** of the client's sections on the left;
  - the chosen section in the middle.
- Everything shown is for the year picked. Changing the year changes every section.

### The client's sections
1. **Overview.**
   - The client's details, which can be edited here.
   - The year's status: open or closed.
   - A short summary of the year:
     - rows to review;
     - unpaid sales invoices and supplier bills;
     - whether each bank account agrees with its statements;
     - whether the trial balance balances.
2. **Documents.**
   - Upload files, or import from the client's folder (below).
   - Every file of the year, with its status: reading, read, failed, or "doesn't add up" for a statement whose lines don't reach its printed balances.
   - Each file's original can be downloaded.
   - Today's `AddDocuments` and `UploadsList` do most of this.
3. **Bank.**
   - One tab for each of the client's bank accounts and credit cards, with that account's lines for the year.
   - Its balance in the books beside the balance its statements print. When they differ, it says by how much.
4. **Invoices.**
   - Two lists: **Sales** (invoices the client sent to customers) and **Purchases** (bills from suppliers).
   - Each invoice shows its counterparty, number, date, total, what has been paid and what is still owed, and which bank lines paid it.
   - An invoice paid in a later year shows as paid there.
   - The site doesn't create invoices. They come from the client's files.
5. **Transactions.**
   - Every row of the year, as today's `TransactionsTable`.
   - A person can still edit, link, include, unlink, mark "Not the same", add and remove rows.
6. **Trial balance.**
   - The year's trial balance with its summary figures and the Excel export.
   - **Close year** and **Reopen year** (see Years).

### Importing from a folder
- Each client can have a folder on the computer the site runs on. "Import from folder" takes in every file that is new since the last import.
- A file already taken in is skipped, judged by its contents and not by its name.
- Each file is copied into MongoDB first, then read into the client's books like an upload.
- This works only because the site runs on the accountant's own computer. It is one way in, and so is uploading.

## Years

- **Each client has an accounting year end,** for example 31 March, entered with the client. It can be changed only while none of the client's years is closed (my call).
- **The data is test data,** so the new database starts empty: nothing is migrated from today's clients (my call).
- **Years:** the client's years run from one year end to the next. The first year is the one the accountant starts the client in.
- **Rows belong to the year of their date.** A file whose rows fall in two years puts each row in its own year. A row with no date waits in the year the file was added to and is flagged, as today.
- **Opening balances.** A year's opening balances are the previous year's closing balances, carried forward:
  - balance sheet accounts (bank, debtors, creditors, VAT, loans, director's loan and the rest) carry forward as they stand;
  - the year's profit or loss goes to retained earnings, or to the owners' capital for a business that isn't a company;
  - income and cost accounts start the new year at zero.
- **A client's first year** has no year before it. The accountant enters its opening balances once, from the client's last accounts:
  - an amount on each balance sheet account, which must balance;
  - for Debtors and Creditors, the unpaid invoices that make up the total: the customer or supplier, the amount, and the invoice number if known.
  - Payments in the year match those unpaid invoices as they would match an invoice uploaded that year.
- **Invoices across years.** An invoice still unpaid at the year end carries forward as unpaid, and a payment in a later year matches it. The trial balance of each year shows what was owed at its own end.
- **Closing a year** locks it: no row, opening balance or setting of that year can be changed. Reopening a closed year is a deliberate action. A change made after reopening flows into the next year's opening balances.

## Bank accounts

- **A client has one or more bank accounts and credit cards,** each with a name ("Barclays current", "Amex card") and a kind (current, savings, credit card, petty cash). Each has its own account in the chart.
- **A statement belongs to one bank account.** When it is uploaded, the site asks which, or suggests one it can tell from the statement.
- **Transfers between the client's own accounts** are coded to the other account. When both statements are in, the two lines are one transfer, booked once (as a receipt and its card payment are today).
- **The statement check:** each bank account's balance in the books at a statement's closing date must equal the balance the statement prints. The Bank section and the Overview say whether it does.

## Fixes to the accounting

The check on 2026-10-23 confirmed these against the code with small test cases.

1. **An invoice paid more than 31 days after its date is booked twice, with no warning.**
   - Today a payment matches a document only within 31 days. A £1,200 legal bill paid after 45 days (normal 30-days-end-of-month terms) gave £2,200 of legal fees instead of £1,000, and £1,200 still owed to the supplier.
   - Fix:
     - A payment of exactly what one open document from the same counterparty owes matches it whatever the document's age, across years too.
     - A part payment or overpayment to a counterparty matches automatically only within a longer window of 120 days (my call); the builder may tune it with the eval set.
     - A bank line to or from a counterparty that has an open document it didn't match gets a warning naming that document, so it is never silent.
2. **Wages are understated, because nothing books the payroll.**
   - Today net pay is coded to Gross Wages and the payment to HMRC to PAYE and NI. With £3,000 of net pay and £1,100 paid to HMRC, wages showed £3,000 instead of £4,100, and the PAYE account showed £1,100 owed by HMRC.
   - Fix: a new document type, the **payroll summary** (the monthly report from payroll software), is read like an invoice. It books:
     - gross pay, employer's NI and employer's pension as costs;
     - net pay, PAYE and NI, and pension as owed, on liability accounts.
   - The bank lines for net pay, HMRC and the pension provider then clear those, as payments clear invoices.
   - A bank line coded to wages with no payroll summary for that month is flagged.
3. **There is no year** (see Years). Today every row a client has ever had goes in one trial balance, the period check never runs for a client, and the bank balance is only the sum of the movements.
4. **There is only one bank account** (see Bank accounts). Today a transfer between two of the client's accounts, with both statements uploaded, is refused as "posts to and from the same account".
5. **The chart lacks accounts a limited company needs.** Add:
   - share capital, dividends and retained earnings;
   - accruals and prepayments;
   - depreciation and accumulated depreciation;
   - corporation tax;
   - directors' salaries, employer's NI and employer's pension;
   - the payroll liabilities of fix 2;
   - advertising and marketing;
   - fines and penalties (not tax-deductible);
   - credit card and further bank accounts.

   Codes follow Sage 50 as the chart does now. The AI model's account list and the prompt are updated to match.

Smaller points the builder should check and settle while working in this code, measured with the eval set:
- **Typical VAT rates.** The usual rates set on some accounts (Travel as zero-rated, Postage as exempt, Rent as standard) are wrong for part of what goes there: taxis and parking, couriers, commercial rent that isn't opted to tax. They only decide which VAT figures are flagged, never what is booked.
- **Bank lines paid into Sales.** A VAT-registered business's sale booked from a bank line with no VAT shown books no VAT. Flag it.

## Files and storage

- **MongoDB holds everything:** clients, years, bank accounts, rows, opening balances and every original file (GridFS, as now).
- The SQLite store is removed. With no MongoDB address set, the site says so and doesn't start.
- Money stays `Decimal` in Python and an exact decimal string in MongoDB.

## What happens to the existing code

### Kept and fixed
The accounting engine:
- `models`, `accounts`, `money`, `checks`, `matching`, `posting`, `statements`, `file_dates` and `export`;
- the document reading: `intake`, `pipeline`, `extractor`, `adapter` and `model_client`, on OpenRouter or Groq as now;
- `blobs` and the MongoDB store, extended for years, bank accounts and opening balances;
- the eval set in `eval/fixtures/` and its runner.

### Rebuilt
The Next.js pages, as the layout above, reusing today's components where they fit.

### Taken out for now
They stay in git history, and the agent project brings back what it uses:
- the agent job (`ledgersync/agent/`), its records (`ledgersync/records/`), the emails to clients (`notify`) and the client's upload page (`/requests/[token]`), with their routes and tests;
- `JobPanel` and the "Start job" button;
- the "Add to account" button, which does nothing.

### The client-level test set
`eval/jobs/` and its runner change from scoring an agent job to scoring the year's trial balance, built from the documents with no agent, against the expected one. Its `period.json` becomes the client's year. This measures the accounting directly.

## Goals
- The accountant can add a client with its year end and bank accounts, and enter its opening balances once.
- They can upload or import the year's files and see them in the right sections.
- They can check and correct the rows, and get a trial balance for the year that is right to the penny on the eval set.
- The five fixes hold, each with tests that fail before the fix and pass after it.
- A year can be closed, and its closing balances open the next year.
- The site is ready for an agent to be added: every action a person takes goes through an API route, so a later agent can call the same routes.

## Non-goals
- The agent, chat, MCP and login: the next project.
- Year-end adjustments (depreciation, accruals, corporation tax, the director's loan review) and final accounts: later. This project adds their accounts to the chart only.
- VAT returns, sign-off and filing.
- Creating invoices.
- More than one user.

## Anti-goals
- **A trial balance that balances but books something twice or leaves it out without saying so.** Every case where the site can't decide shows a warning on the row.
- **Changing an amount, date or VAT a document shows,** except when a person edits it, which keeps the original as today.
- **A closed year changing without being reopened.**
- **Over-building.** It runs on test data for one accountant, so pick the simpler way when there are two.

## Constraints
- The stack stays: Python with FastAPI, Next.js, MongoDB, and the OpenRouter or Groq model for reading documents.
- The agent project uses LangChain; nothing here should make that harder.
- Tests use a fake model and need no key. MongoDB tests run against a test database. A local MongoDB is recommended: on 2026-10-23 a full run against the remote test database lost its connection in 14 tests.
- Ask the accountant before running anything that spends model credit, such as the eval runs.

## Decided by the accountant
- The client's space is a side menu of sections, with the agent opened from the top bar (layout A).
- Each client's work is split by year, with a year picker.
- Closing figures carry forward into the next year.
- The site doesn't create invoices. They come from the client's files, uploaded as now.
- Every file is stored in MongoDB.
- Clients with staff send a monthly payroll report from their payroll software, and wages are booked from it.
- Build the accounting site first, and fix what is wrong in the existing accounting. The agent comes after.
- Starting from scratch is acceptable.

## My calls (please check)
- **Keep the accounting engine and fix it,** rather than rewrite it; rebuild the website.
- **The sections:** Overview, Documents, Bank, Invoices, Transactions and Trial balance. Requests to the client come back with the agent.
- **Rows go into the year of their date.**
- **A first year's opening balances are typed in,** with the unpaid invoices behind Debtors and Creditors.
- **Close year locks the year;** reopening is deliberate.
- **Payments match an exact-amount open document whatever its age;** part payments and overpayments only within 120 days. Any unmatched counterparty with an open document gets a warning.
- **Import from a folder** on the site's own computer, next to upload.
- **Remove the SQLite store.**
- **Take the Phase 1 agent job, its records, client emails and client upload page out for now.** They are in git history.
- **No login in this project:** it runs on the accountant's own computer.

## Left to the builder
- The exact Sage-style codes for the new accounts, and how the chart moves its existing codes if one clashes. The data is test data, so renumbering is fine.
- How years, bank accounts and opening balances are stored in MongoDB.
- How a statement's bank account is suggested.
- How the side menu maps to routes, for example `/clients/[id]/[year]/bank`.
- How the year picker remembers the last year viewed.
- How Close year shows what will carry forward before it locks.
