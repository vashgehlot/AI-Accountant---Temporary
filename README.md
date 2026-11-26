# Super Accountant (prototype)

A bookkeeping site for one accountant's clients. It turns UK financial inputs (receipt photos, bank statement
CSV/Excel/PDF exports, invoices, payroll reports, pasted text or manual entries) into categorised transactions and a
double-entry trial balance, kept **by client and by accounting year**. Documents are
read by a hosted Qwen vision model (`qwen/qwen3.8-27b`), through OpenRouter when `OPENROUTER_API_KEY` is
set and otherwise through Groq: **uploaded documents are sent to that provider.** The code keeps its working name, LedgerSync: the `ledgersync` package, the `LEDGERSYNC_*`
settings and the `X-LedgerSync` header.

- `server.py` — FastAPI routes (port 8085, localhost only)
- `ledgersync/` — settings, typed errors, background jobs, the model client, upload checks, the
  extractor (prompt, schema, per-row validation), pipeline, chart of accounts, money and VAT,
  transaction checks, matching, double-entry posting, and the books (years, opening balances, closing a year)
  kept in MongoDB
- `frontend/` — Next.js UI (port 3000); calls the API through its `/api` rewrite
- `eval/` — the accuracy measures (see Measuring accuracy)

The design is in [the accounting site design](docs/superpowers/specs/2026-10-23-accounting-site-design.md). An agent
that runs the site is a separate project, designed in
[the chat agent design](docs/superpowers/specs/2026-10-23-chat-agent-design.md); this site works without it.

## Prerequisites

- Python 3.11
- Node.js 20.9+
- MongoDB, running locally (`brew services start mongodb-community`) or an Atlas cluster
- An OpenRouter API key ([openrouter.ai/keys](https://openrouter.ai/keys)) or a Groq API key
  ([console.groq.com/keys](https://console.groq.com/keys)); with both, OpenRouter is used

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                      # then paste your key after OPENROUTER_API_KEY= or GROQ_API_KEY=, and set MONGODB_URI
(cd frontend && npm install)
```

`.env` is git-ignored; never commit it or paste the key anywhere else.

## Run

```bash
.venv/bin/python server.py                # API on http://127.0.0.1:8085
(cd frontend && npm run dev)              # UI on http://localhost:3000
```

Without a key or an internet connection the API answers 503 with how to fix it; it never guesses.

## The site

### Clients, years and sections

The first page, **Clients**, lists the clients with each one's latest year and whether it is open or closed. Add a
client with its company name, business type (limited company, sole trader, partnership or LLP), its responsible
person (the client's own contact, with email and phone), whether it is VAT registered, the end of its **first year**
(for example 31 March 2027), its bank accounts, its directors, partners or LLP members (up to four, each with a
profit share for a partnership or LLP; empty shares mean equal shares). Archive hides a client and
keeps everything; Restore brings it back.

Open a client to get its own space: a **year picker** beside its name (for example "Year to 31 Mar 2027"), and a side
menu of six sections, all for the year picked.

| Section | What it shows |
|---|---|
| Overview | The client's details (editable), whether the year is open or closed, and a summary: rows to review, what is unpaid on sales and purchases, whether each bank account agrees with its statements, whether the trial balance balances. |
| Documents | Upload files; every file of the year with its status (reading, read, failed, or "Doesn't add up" for a statement that doesn't reach its printed balances); download an original. |
| Bank | One tab for each bank account and card, with its lines for the year, its balance in the books beside the balance its statements print, and the difference. |
| Invoices | **Sales** (invoices the client sent) and **Purchases** (bills from suppliers): the total, what has been paid, what is still owed, and the bank lines that paid it. An invoice paid in a later year shows as paid there. The site doesn't create invoices; they come from the client's files. |
| Transactions | Every row of the year: edit, link, include, unlink, mark "Not the same", add and remove rows. |
| Trial balance | The year's trial balance with its summary figures, a profit and loss account and balance sheet worked from it, Add journal, the Excel export, and Close year / Reopen year. The first year's opening balances are entered here. |

Rows belong to the year of their **date**: a file whose rows fall in two years puts each row in its own year. A row
with no date waits in the year the file was added to and is flagged. A row dated before the first year starts is not
booked again, because the opening balances hold it.

### Books kept up to date

After any change, the questions and the posted ledger are brought up to date at once, and every change is recorded:
who made it (the person, the rules or the agent), what it touched and the values before and after. The
Overview says so only when the books are not up to date.

### Bank accounts and cards

A client has one or more bank accounts and credit cards, each with a name ("Barclays current") and a kind (current,
savings, credit card or petty cash). Each gets its own account in the chart: current accounts 1200 to 1202, deposit
accounts 1210 and 1211, petty cash 1230, credit cards 1240 and 1241. A statement belongs to one account: pick it when
you add the file. A transfer between two of the client's own accounts is coded to the other account, and when both
statements are in, the two lines are booked once. Paying a card off from the bank is a transfer, not spending.

### Opening balances

A client's first year has no year before it, so its opening balances are typed in once, from the client's last
accounts: an amount on each balance sheet account (debits must equal credits), and for Debtors and Creditors the
unpaid invoices that make them up (the customer or supplier, the amount, the invoice number if known). Payments in the
year clear those unpaid invoices as they clear an invoice uploaded that year.

### Closing a year

Close year, on the Trial balance section, locks a year: no row, opening balance or setting of it can change until it
is reopened. Closing carries the year forward: balance sheet accounts open the next year as they stand, the year's
profit or loss goes to retained earnings for a company, to each partner's capital account (3100 to 3103) by their
share for a partnership or sole trader, and to each member's current account (2260 to 2263, a liability, as the LLP
SORP's automatic division has it) for an LLP; the shares used are saved with the closed year. Income and cost
accounts start at zero. A year closes only after the ones before it and only when its trial balance balances; only the latest closed year can be reopened, and a change made after
reopening flows into the next year's opening balances. While any year is closed, the client's year end, VAT
registration and business type can't be changed.

### Payroll reports

A client with staff sends a monthly payroll report from its payroll software. It is read like an invoice and books
the wages as costs: gross pay (7000 Gross Wages, or 7001 for directors), employer's NI (7006) and employer's pension
(7007), against what is owed on 2220 Net Wages, 2210 PAYE and National Insurance and 2230 Pension Fund. The bank lines
that pay the staff, HMRC and the pension provider are coded to those liability accounts and clear them. A bank line
coded to wages with no payroll report for that month is flagged "Book wages from the payroll report". A payment to
HMRC for PAYE with no payroll report that month or the one before asks for the report.

### Missing paperwork

The Overview lists the statements the books need and don't have: an account or card with no statement in the year,
and a break in the chain, where a statement opens at another balance than the books held before it (or than the
statement before it closed at), with the months no statement covers. A statement that prints only a running balance
on each line (Starling, Monzo and most CSV exports) is checked against its last line's balance. The Overview also
points out a director's loan the director owes the company (s455).

### What the rules book on sight

- **CIS.** An invoice with a Construction Industry Scheme deduction is booked at its whole value: a sale's deduction
  to 1104 CIS Deducted, which the customer paid to HMRC for the business; a subcontractor's to 2215 CIS Payable. What
  is owed is the amount due after it, so the payment clears the invoice.
- **Payment processors.** A payout from Stripe, PayPal, Square, SumUp, Zettle, Shopify, GoCardless, Amazon, eBay or
  Etsy is sales less the processor's fees and refunds: it goes to 1250 Payment Processor Clearing and asks for the
  payout report, which is read like an agent's statement (sales in, fees out, the payout the net paid over) and
  clears it.
- **Personal spending.** A streaming or gaming subscription (Netflix, Spotify and the like) goes to the Director's
  Loan Account for a company, Drawings for anyone else, with a note; recode it if it was for the business.
- **Figures a document doesn't print.** For a file with a text layer, VAT the document doesn't print is dropped (it
  can't be reclaimed), and an amount it doesn't print is flagged "Total not printed". A receipt read at its total
  before VAT, whose card payment is exactly that plus 20% or 5%, documents the payment: the bank line books it, with no
  VAT, and the receipt asks for a complete copy. A receipt never replaces a bank line of another amount.
- **Insurance.** The gap between a premium and its total is Insurance Premium Tax, not VAT, and isn't flagged.

### MongoDB only

Everything is kept in MongoDB: the clients, their years, rows and opening balances, and the original files. Set
`MONGODB_URI` in `.env` (for example `mongodb://localhost:27017`) and, if you want another database than `ledgersync`,
`MONGODB_DB_NAME`. With no `MONGODB_URI` the API refuses to start: `Set MONGODB_URI in .env: Super Accountant keeps
its data in MongoDB.` Dropping the database removes every client. There is no other store.

### The API

Analyses run as background jobs: `POST /api/analyze` returns `{job_id}`, then `GET /api/jobs/{job_id}` reports
progress and the result; `DELETE` cancels. The API takes an analysis only with an `X-LedgerSync` header,
which the pages send and a form on another web site can't. Up to five jobs run at once
(`LEDGERSYNC_MAX_PARALLEL_JOBS`), and the UI sends that many files of an upload at a time; on Groq's free plan they
mostly wait on its per-minute limits, so the gain shows on a paid plan. Money is sent and returned as strings, e.g.
`"12.50"`. Send `vat` only when the document shows it; the API never changes it. Errors are
`{"detail": {"code", "message"}}`.

| Route | What it does |
|---|---|
| `GET /api/health` | The model and its availability |
| `POST /api/analyze` | Reads one file or pasted text; with `client_id`, `year_start` and `bank_account` it saves the rows to that client's year |
| `GET /api/jobs/{job_id}`, `DELETE /api/jobs/{job_id}` | A reading job's progress and result; cancel it |
| `GET /api/accounts` | The chart (Sage 50-style codes); `?client_id=` gives the accounts that client's rows can be coded to |
| `POST /api/transactions/validate`, `POST /api/trial-balance` | Check or post rows sent in the request, without saving anything (422 when a row can't be posted) |
| `GET /api/clients`, `POST /api/clients` | List (`?archived=true` for archived ones) or add a client |
| `GET /api/clients/{id}`, `PATCH /api/clients/{id}` | Read, change or archive a client |
| `GET /api/clients/{id}/years` | The client's years, the first through the latest |
| `GET /api/clients/{id}/years/{start}/ledger` | The year's rows and uploads |
| `GET /api/clients/{id}/years/{start}/trial-balance` | The year's trial balance (422 while a row has an error to fix) |
| `GET /api/clients/{id}/years/{start}/invoices` | The year's sales and purchase invoices |
| `GET /api/clients/{id}/years/{start}/bank` | Each bank account against its statements |
| `GET /api/clients/{id}/years/{start}/summary` | The Overview's figures |
| `GET /api/clients/{id}/years/{start}/export.xlsx` | The trial balance and transactions as an Excel workbook |
| `POST /api/clients/{id}/years/{start}/close`, `.../reopen` | Close a year, or reopen the latest closed one |
| `GET /api/clients/{id}/opening-balances`, `PUT` the same | Read or set the first year's opening balances |
| `PATCH` or `DELETE /api/clients/{id}/rows/{row_id}` | Edit a row (the original is kept; Revert puts it back) or remove it |
| `POST /api/clients/{id}/uploads` | Add rows by hand |
| `PATCH` or `DELETE /api/clients/{id}/uploads/{upload_id}` | Change a statement's bank account, or remove an upload |
| `GET /api/clients/{id}/uploads/{upload_id}/file` | Download the original file |

In the UI the sections are at `/clients/{id}/{year start}/{section}`, for example
`/clients/3/2026-04-01/trial-balance`; a client's address on its own opens its latest year's Overview.

A row's `vat_posted` is the VAT booked: the amount shown; or, when a person picked a rate in `vat_treatment`, the VAT
inside the gross at that rate (flagged); otherwise none, because VAT can only be reclaimed when it was charged. The
API fills in `vat_posted` and `net` afresh on every call, so an edited row can simply be sent back.

### Unpaid bills, claims and payments

Documents are booked the way an accountant would (accruals):

- A till or card receipt, or a bank line, is money that moved: it posts against the bank account or card it went through (1200 Bank Current Account when the client has one).
  A receipt and the card payment for it on a bank statement (the same amount, within three days) are booked
  once, from the receipt, which shows the VAT; Unlink on the bank line books them apart. The amount and the date
  decide, since a bank names a shop its own way; the shop's name only chooses between payments that both fit.
- An invoice starts unpaid. A bill, or a supplier's credit note, posts against 2100 Creditors; a sales
  invoice, or a credit note to a customer, against 1100 Debtors; an expense claim against 2110 Expenses
  Owed to Staff.
- A bank line that pays an open invoice or claim clears it instead of being booked as a second expense. A
  payment of exactly what one open document from the same counterparty owes clears it however late it is made, and
  across years. Any other payment (a part payment, an overpayment, or one for several documents) is applied
  automatically only when it is dated on or after the document and within 120 days of it. Names match when they
  are the same once legal and bank words are set aside, however short ("HML PM Ltd"). A payment of exactly what one
  document owes is applied first, whatever its date, so a bigger payment to the same person is never taken as an
  overpayment of it. One payment can clear up to five documents from one counterparty. When several could be
  meant, the table asks you to choose (Link) and the trial balance waits. Part payments and overpayments are
  applied and flagged; a payment of the same amount under a different name is only suggested, and a bank line to
  or from a counterparty that has an open document it didn't clear carries a warning naming that document. Unlink
  undoes a match.
- A document with the same number, counterparty, direction and total as an earlier one (a reminder of a
  bill; a receipt photographed twice, on the same day) is a copy: it is not booked unless you tick Include.
- The receipt or invoice for a line of an expense claim (the same amount, within three days) is booked instead
  of that line, owed to the claimant: the document shows the VAT that can be reclaimed. The amount and the date
  decide, so a mileage log or a booking that names no one pairs too; the shop's name (initials count: NCP for
  National Car Parks) only chooses between documents that both fit, nearest date first. The claim line is greyed
  out; tick it to book it as well, which warns Booked twice (only for a different purchase). A claim line showing
  more VAT than its document is flagged, unless the document's own prices show it: when a receipt on one account prints its total before VAT and that is its total less the
  claim's VAT, the VAT is booked. If the receipt says it is not a VAT invoice, the VAT is not booked but offered:
  get the VAT invoice, then click Book VAT on the receipt (an edit, which Revert undoes).
- When a receipt and its claim line or card payment agree on all but the date, or on the shop and the day but
  not the amount, nothing is guessed: they stay apart and ask which is right, with a Use button (an edit, which
  Revert undoes), Show both, and Not the same for two purchases. A claim line whose claim adds up to its total
  doesn't offer the receipt's amount: the total confirms it. A receipt with no date takes the date of its claim
  line or card payment. A receipt or invoice
  on its own is also checked against a date in its file name (an expense app's export names the day).
- Each document is checked against the total printed on it, once, with what is missing or too much, on the row
  that explains it when one does (a line someone changed by just that much, a line read twice, the one line of
  that much) and otherwise on its first row, with Show its lines. The check is worked out afresh, so it clears when you add the line that wasn't read (Add line on any row
  of the document) or remove a row read twice (Remove on the row).
- A letting or managing agent's statement books the rent it collected and the fees and bills it took off,
  each on its own account, against 1100 Debtors: the agent holds the money. The bank line of the net it
  paid over clears the statement, and a bill the agent paid for the business (a plumber's, say) is cleared
  by the statement's line for it, not by the bank.
- Quotes, pro formas, purchase orders, remittance advices and supplier statements are not booked unless
  you tick Include.

`POST /api/transactions/validate` and `POST /api/trial-balance` take `document_type`, `counterparty`,
`document_number`, `agent`, `document_ref`, `link` and `include` on each row, and return `paid_against`,
`pays`, `candidates`, `owed`, `document_direction`, `paid_by`, `copy_of` and `recorded_by`. Rows without a `document_type` are receipts, so older clients keep their postings. The
design is in `docs/superpowers/specs/2026-10-06-unpaid-documents-and-payment-matching-design.md`.

### Working on a client's rows

Each analysis is saved to the client's year in MongoDB when it finishes, with the decisions you make (Link,
Include, edits), so closing the browser loses nothing. Each client's page keeps one table across its uploads and
catches what was entered twice. A file already uploaded for that client, on any day, or picked twice, is skipped
without being read. A row with the same amount and direction as a row from another upload, dated within three days of it (a receipt and its bank
line, say), is flagged "possible duplicate" and left for a person to decide; two receipts on one expense claim
are not, as the claim has a line for each. Show both puts the two side by side, and Not the same keeps them
apart for good (with Undo).

- Edit corrects a row: date, description, counterparty, money in or out, amount, VAT shown, account and
  document type. The row shows "Edited", and Revert puts back what the model read. Remove deletes one row (and
  its upload once nothing of it is left); Add transaction adds a row of your own.
- What needs review shows under each row in words, and a bar above the table counts each kind of issue; click
  one to see only those rows.
- A bank statement is checked against the balances it prints. A line the model missed or misread shows
  where the balance breaks, and the upload says "Doesn't add up".
- Export to Excel downloads the year's trial balance and transactions as one workbook. The trial balance sheet
  gives each account's statement heading, its tax treatment (disallowable, check, not trading income) and its
  SA103F box; the profit and loss and balance sheet follow the Companies Act headings (tax after profit before tax,
  creditors due within and after one year apart), as the Trial balance page does.
- A sale in a VAT-registered business booked from a bank line that shows no VAT is flagged.
- VAT on client entertainment (7403) and on cars (0050 Cars) is not reclaimed; vans (0055 Vans) are. A
  limited company's directors each have a Director's Loan Account (2250 to 2253); partners have their own
  Capital Introduced (3010 to 3013) and Drawings (3260 to 3263); LLP members draw on their current account
  (2260 to 2263). With several owners, a row booked to the first one's account from a document asks whose it is. Rent from tenants goes to 4904 Rent Income, and cash from a cash machine to 1230
  Petty Cash. VAT at the 5% rate (a small business's energy) and £0.00 VAT are not flagged.

## The AI model (OpenRouter or Groq)

The app asks OpenRouter when `OPENROUTER_API_KEY` is set, and Groq otherwise; both serve the same model
under the same name, and the other model settings (`OPENROUTER_TIMEOUT` and the rest) apply to either, apart
from the longest answer: OpenRouter counts the model's thinking in it, so it has its own, larger limit.
OpenRouter passes each request to one of the companies hosting the model, and only to one that honours
the strict JSON schema below; the account's [privacy settings](https://openrouter.ai/settings/privacy)
decide whether a host that may keep the documents can be used. The startup log names the provider.
It asks a full-precision host first (DeepInfra), then any host running the model at 8-bit precision or
better, never a 4-bit one: left to choose, OpenRouter sent every read to a 4-bit host, which left a line
out of an expense claim every time (`OPENROUTER_PROVIDERS` and `OPENROUTER_QUANTIZATIONS` change this).
Each upload keeps the model and host that read it, e.g. `qwen/qwen3.8-27b via DeepInfra`. The accountant chat
runs on that same model over the same route (the same hosts first, the same precisions, so never a 4-bit one
either) and tells OpenRouter besides to use only hosts that keep none of the data.

Pasted text, spreadsheets and PDFs with a text layer go to the model as text; photos and scanned
pages go as images (turned upright, at most 1600 px, up to three pages per request). The model answers in a
strict JSON schema: the direction of the money, an account chosen from the chart, and the VAT
printed on the document. A receipt or invoice gives one transaction per account: one row when its
items are all of one kind, one row per kind otherwise (e.g. a meal and a taxi fare). It stays one
row, flagged "mixed items", when it shows a single VAT total that cannot be divided between the
kinds. Rows that do not add up to the document's printed total are flagged.

- On Groq, the free plan for this model allows about 30 requests and 8,000 tokens a minute and 200,000
  tokens a day (checked 2026-09-29); each image counts as 2,048 tokens. At the limit the app waits
  up to a minute, then reports a rate limit; `eval/run_eval.py --resume` runs those documents again.
- The daily allowance refills gradually, about 8,300 tokens an hour, so a full eval run leaves
  little for the rest of the day. Groq can also hold a request's expected output to 1,000 tokens a
  minute: on 2026-09-29 it refused a few small documents that way (its message suggests lowering
  `max_tokens`, i.e. `GROQ_MAX_OUTPUT_TOKENS`), yet let a 60-row statement's 3,500-token answer
  through minutes later. A refused document usually goes through when tried again later.
- `qwen/qwen3.8-27b` is a Groq *preview* model and may change; `GROQ_MODEL` (or `OPENROUTER_MODEL`)
  switches it.
- `.venv/bin/python -m pytest -m llm` checks the key and model with one receipt photo.

### The agents

The accountant chat and the background review run on one agent, on one model. Each turn is that agent playing one
part, picked from the message by rules in code (`ledgersync/agent/router.py`), with no model call spent on choosing:

| Part | What it does | Can change the books |
|---|---|---|
| Reviewer | Settles what the evidence settles: dates, duplicates, records that disagree, mixed-VAT rows, VAT a document prints. Runs every background review | Yes, through the checked resolutions |
| Bookkeeper | Makes the changes the person tells it to, and applies an answer typed on a question card | Yes, as the person said |
| Tax and VAT adviser | Answers tax questions from the books and the facts in its prompt | No |
| Reporter | Says where the books stand: what changed, what needs the person, the balances | No |
| Lead accountant | The whole agent, with every tool: takes what no rule places, and any turn a specialist hands over | Yes |

Each specialist has a shorter prompt (cut from the lead's when the API starts, so an edit to the lead's prompt
reaches them), only the tools its part needs, and a briefing: the state of the books as the turn began, fetched in
code so it doesn't spend its first model calls fetching it. A tool outside its part is refused in code, and
`hand_over` gives the rest of a turn to the lead. The log has one line for each turn: the part, its model and tool
calls, and the seconds it took.

## Configuration

Settings come from environment variables or `.env` (environment variables win).

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Your OpenRouter key; put it in `.env`. When set, OpenRouter is used instead of Groq |
| `OPENROUTER_MODEL` | `qwen/qwen3.8-27b` | OpenRouter model; it must read images |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter's OpenAI-compatible API |
| `OPENROUTER_MAX_OUTPUT_TOKENS` | `32768` | Longest answer on OpenRouter, thinking included: a 60-row statement thinks for about 4,000 tokens and answers in about 9,000 |
| `OPENROUTER_PROVIDERS` | `deepinfra/bf16` | Hosts asked first, in order, comma-separated; blank lets OpenRouter choose |
| `OPENROUTER_QUANTIZATIONS` | `bf16,fp16,fp32,fp8` | Precisions a host may run the model at; blank allows any, 4-bit (`fp4`) hosts included |
| `OPENROUTER_TIMEOUT` | `200` | Seconds a model call may send nothing, on either provider (as are the next three): a streamed read still arriving is never cut off. Was `GROQ_TIMEOUT`, still read when this isn't set |
| `OPENROUTER_TOTAL_TIMEOUT` | `600` | Seconds a streamed read may take in all, a backstop: a long bank or card statement can take several minutes, and an answer that trails off into whitespace is stopped long before |
| `OPENROUTER_REASONING_EFFORT` | `high` | The model's "thinking" (`none`, `low`, `high`); thinking keeps it to the receipt rules, `none` is about 10x faster than `low`. Was `GROQ_REASONING_EFFORT` |
| `OPENROUTER_MAX_IMAGES` | `3` | Scanned pages per request, Groq's most; on Groq's free plan set `1`, as 3 overflow its 8K tokens a minute. Was `GROQ_MAX_IMAGES` |
| `GROQ_API_KEY` | — | Your Groq key; put it in `.env`. Used when there is no OpenRouter key |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq model; it must read images |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq's OpenAI-compatible API |
| `GROQ_MAX_OUTPUT_TOKENS` | `8192` | Longest answer on Groq; a 60-row statement needs over 4,000 tokens |
| `LEDGERSYNC_BUSINESS_NAME` | — | Whose books these are; tells sales invoices from purchases |
| `LEDGERSYNC_HOST` / `LEDGERSYNC_PORT` | `127.0.0.1` / `8085` | API bind address |
| `LEDGERSYNC_RELOAD` | `0` | Auto-reload on code changes (development) |
| `LEDGERSYNC_WARMUP` | `1` | Check the key and model at startup, so the header shows the problem early |
| `LEDGERSYNC_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed browser origins |
| `LEDGERSYNC_MAX_UPLOAD_MB` | `20` | Largest accepted upload |
| `LEDGERSYNC_MAX_PDF_PAGES` | `30` | Most pages accepted in one PDF |
| `LEDGERSYNC_MAX_PARALLEL_JOBS` | `5` | Documents read at once; `1` reads them one at a time |
| `LEDGERSYNC_LOG_LEVEL` | `INFO` | Log level (document contents are never logged) |
| `MONGODB_URI` | — | Where everything is kept (required), e.g. `mongodb://localhost:27017` |
| `MONGODB_DB_NAME` | `ledgersync` | The MongoDB database holding clients, rows and original files |
| `API_URL` (frontend) | `http://127.0.0.1:8085` | Where the Next.js `/api` rewrite sends requests |

## Tests

The tests need a local MongoDB (`brew services start mongodb-community`); they use throwaway databases
there. Without `LEDGERSYNC_TEST_MONGODB_URI` the MongoDB tests are skipped.

```bash
LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest   # fast tests, no network
(cd frontend && npm test)                                                           # the frontend's tests
.venv/bin/python -m pytest -m llm         # live test against the model (needs OPENROUTER_API_KEY or GROQ_API_KEY)
```

The tests use a fake model (`tests/fakes.py`) and need no key; only `-m llm` calls the real one.

## Measuring accuracy

`eval/` holds 33 synthetic UK documents (receipts including a mixed-VAT one and two with items of
different kinds, invoices including one already paid, bank statements in several bank formats
including two of payees used nowhere else, spreadsheets and pasted text), each with the
transactions a bookkeeper would record
(`eval/fixtures/*/expected.json`), and a harness that runs them through a running API:

```bash
.venv/bin/python server.py                               # in one terminal
.venv/bin/python eval/run_eval.py --label my-change      # in another
```

The headline number is **correct rows**: the share of all expected transactions extracted with the
right amount, date and direction. The harness also reports row precision and recall, per-field
accuracy on the rows it found (amount, date, direction, account, VAT), how often the trial balance
balances, and latency. Results go to `eval/results/<date>-<label>.json` and are saved after every
document: `--resume` continues an interrupted run, `--resume --rerun --cases img-` runs selected
cases again, `--rescore` re-scores a saved report without the API, `--note` records the run
conditions, and `--pause 10` waits between documents to stay inside Groq's free-plan limits.

The committed `2026-09-28-baseline.json` and `2026-09-28-phase3.json` runs used the earlier local
model (`qwen2.5vl:3b` through Ollama on an 8 GB Mac), before the switch to Groq.

The runs on 2026-09-29 used Groq's `qwen/qwen3.8-27b` on the free plan (thinking off, photos sent
as images, `--pause 10`). The first, `groq-swap`, changed only the model and reached 95.1%
correct rows. The second, `groq-prompt`, added the new prompt and reached 100% correct rows with
90.2% account accuracy. Phase 3's local model had 41.5% and 33.9%.

The third, `accounts-general`, gave every account a plain definition and told the model to choose
by what was bought rather than by the shop. It sends a line that names only a payee who could be
selling anything, such as an online marketplace, to Suspense for a person to check. The fixtures
now label supermarkets as Refreshments and marketplaces as Suspense; on those labels `groq-prompt`
scores 83.7% on accounts (103 of 123). On the same 26 documents, account accuracy rose to 99.2%
(122 of 123), with correct rows and VAT still at 100%. The one miss is new: a refund from Amazon for
a returned printer went to Suspense, not Office Equipment. On a statement of 20 payees used nowhere
else (`csv-unseen-payees`), the model placed 18 accounts correctly before the change
(`unseen-before`) and all 20 after (`unseen-after`, and again in `accounts-general`).

Two rewordings of the account rule were then measured and dropped, so the rule stays as in
`accounts-general`, whose one miss at least lands in Suspense, where a person checks it:
- Letting a named item decide whoever the seller is (`accounts-precedence`) fixed the refund, but
  twice out of two it sent Waitrose to Subsistence and Google Ads, which has no account in the
  chart, to Subscriptions and Software instead of Suspense: 98.6% (141 of 143).
- Spelling out an order, what was bought and then the account that fits (`accounts-order`), sent
  eight Tesco lines, an accountant's invoice and the refund itself to Suspense.

A second held-out statement (`csv-unseen-mixed`) was written before that last attempt, since the
first had by then been used to choose between wordings. It names items bought from sellers of
almost anything and has costs no account fits. Every wording placed 18 or 19 of its 20 accounts,
with all five named items and both sellers of anything right. A council penalty charge went to
Travel every time, and LinkedIn Ads went to Subscriptions and Software in one of two runs of the
rule kept (`unseen-mixed`). The chart has no account for either cost (fines, advertising), which is
also why Google Ads goes astray.

`receipt-split-guard` (2026-10-01) measured one transaction per account on a receipt, with the guard
that keeps a single VAT total whole: correct rows 99.4%, VAT 100%, every trial balance balanced. The
expense note split into Subsistence and Travel, and the receipt with one VAT total stayed one row.
Accounts fell to 92.2% (154 of 167). The 60-row statement's eight Tesco lines went to Suspense, as
under the dropped `accounts-order` wording, and so did a customer's payment. The Sainsbury's photo
came back as its £4.20 of cleaning supplies alone; the totals check flags that in the app.

`thinking-low` (2026-10-02) ran the same code with the model's thinking on
(`GROQ_REASONING_EFFORT=low`). On the 27 documents every run finished, accounts were 97.9% (141 of
144), against 99.3% before the split and 92.3% after it with thinking off, and every row had the
right amount, both Sainsbury's rows included. The Tesco lines, the customer's payment and the Amazon
refund came back right. Costa Coffee, an accountant's invoice and Google Ads did not. A receipt or
invoice took a median 11.5 seconds instead of 1.1, partly waiting on the free plan's per-minute
limits.

### The client-level test set

`eval/jobs/` holds 7 cases, each a whole client: its `client.json` (the client as the API takes it, with its
`first_year_end` and `bank_accounts`, and `statements` saying which bank account each statement is for), its
`documents/`, a `notes.md` explaining what it tests and how the figures were worked out, and
`expected_trial_balance.json`, the first year's trial balance worked out by hand, account by account (debit less
credit, so a credit is negative). The cases are a bank statement with two receipts, receipts and invoices matched to their payments, an unpaid invoice, a sole trader's
expense claim, a bill paid 49 days late, a payroll report with the net pay, HMRC and pension payments, and a
transfer between a current and a savings account. The runner adds the client, reads every document into its first
year, and compares the year's trial balance with the expected one to the penny. No agent is involved, so it
measures the model's reading and the booking rules together:

```bash
.venv/bin/python server.py                                          # in one terminal
.venv/bin/python eval/run_job_eval.py --label my-change             # in another
.venv/bin/python eval/run_job_eval.py --label my-change --case ltd- # only some cases
```

It writes `eval/results/<date>-jobs-<label>.json` and exits 0 only when every case matches. Reading the documents
spends model credit. The expected figures themselves are checked without a model by `tests/test_eval_cases.py`,
which gives each case the rows a good reading would give and runs them through the real API.

To measure real documents, put anonymised copies in `eval/private/<case>/` (the input file plus an
`expected.json` in the same format) and add `--private`; that folder is never committed. After
editing `eval/eval_cases.py`, regenerate the fixtures with `.venv/bin/python eval/make_fixtures.py`.
