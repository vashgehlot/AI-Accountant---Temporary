# Super Accountant (prototype)

Turns UK financial inputs (receipt photos, bank statement CSV/Excel/PDF exports, pasted text
or manual entries) into categorised transactions and a double-entry trial balance. Documents are
read by a hosted Qwen vision model (`qwen/qwen3.8-27b`), through OpenRouter when `OPENROUTER_API_KEY` is
set and otherwise through Groq: **uploaded documents are sent to that provider.** The code keeps its working name, LedgerSync: the `ledgersync` package, the `LEDGERSYNC_*`
settings and the `X-LedgerSync` header.

- `server.py` — FastAPI routes (port 8085, localhost only)
- `ledgersync/` — settings, typed errors, background jobs, the model client, upload checks, the
  extractor (prompt, schema, per-row validation), pipeline, chart of accounts, money and VAT,
  transaction checks and double-entry posting
- `frontend/` — Next.js UI (port 3000); calls the API through its `/api` rewrite

This prototype is being hardened; see
[the design spec](docs/superpowers/specs/2026-09-28-ledgersync-robustness-design.md) and
[the Groq model design](docs/superpowers/specs/2026-09-29-groq-vision-model-design.md).

## Prerequisites

- Python 3.11
- Node.js 20.9+
- An OpenRouter API key ([openrouter.ai/keys](https://openrouter.ai/keys)) or a Groq API key
  ([console.groq.com/keys](https://console.groq.com/keys)); with both, OpenRouter is used

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                      # then paste your key after OPENROUTER_API_KEY= or GROQ_API_KEY=
(cd frontend && npm install)
```

`.env` is git-ignored; never commit it or paste the key anywhere else.

## Run

```bash
.venv/bin/python server.py                # API on http://127.0.0.1:8085
(cd frontend && npm run dev)              # UI on http://localhost:3000
```

Analyses run as background jobs: `POST /api/analyze` returns `{job_id}`, then
`GET /api/jobs/{job_id}` reports progress and the result; `DELETE` cancels. The API takes an analysis
only with an `X-LedgerSync` header, which the pages send and a form on another web site can't. Up to five
jobs run at once (`LEDGERSYNC_MAX_PARALLEL_JOBS`), and the UI sends that many files of an upload at a time; on
Groq's free plan they mostly wait on its per-minute limits, so the gain shows on a paid plan.

Each client's page keeps one table across its uploads and catches what was entered twice. A file already
uploaded for that client, on any day, or picked twice, is skipped without being read. A row with the same
amount and direction as a row from another upload, dated within three days of it (a receipt and its bank
line, say), is flagged "possible duplicate" and left for a person to decide; two receipts on one expense claim
are not, as the claim has a line for each. Show both puts the two side by side, and Not the same keeps them
apart for good (with Undo).
Without a key or an internet connection the API answers 503 with how to fix it; it never guesses.

The ledger endpoints use double entry: `GET /api/accounts` lists the chart (Sage 50-style
codes), `POST /api/transactions/validate` splits VAT and lists issues, and
`POST /api/trial-balance` takes `{"transactions": [...], "settings": {"vat_registered": true}}`
and always balances; rows with errors (unknown account, non-GBP, impossible VAT) get a 422.
Money is sent and returned as strings, e.g. `"12.50"`. Send `vat` only when the document shows
it; the API never changes it, and fills in `vat_posted` and `net` afresh on every call, so an
edited row can simply be sent back. `vat_posted` is the VAT booked: the amount shown; or, when a
person picked a rate in `vat_treatment`, the VAT inside the gross at that rate (flagged); otherwise
none, because VAT can only be reclaimed when it was charged.

### Unpaid bills, claims and payments

Documents are booked the way an accountant would (accruals):

- A till or card receipt, or a bank line, is money that moved: it posts against 1200 Bank Current Account.
  A receipt and the card payment for it on a bank statement (the same amount, within three days) are booked
  once, from the receipt, which shows the VAT; Unlink on the bank line books them apart. The amount and the date
  decide, since a bank names a shop its own way; the shop's name only chooses between payments that both fit.
- An invoice starts unpaid. A bill, or a supplier's credit note, posts against 2100 Creditors; a sales
  invoice, or a credit note to a customer, against 1100 Debtors; an expense claim against 2110 Expenses
  Owed to Staff.
- A bank line that pays an open invoice or claim clears it instead of being booked as a second expense:
  the same counterparty, dated on or after the document and at most 31 days later. Names match when they
  are the same once legal and bank words are set aside, however short ("HML PM Ltd"). A payment of exactly
  what one document owes is applied first, whatever its date, so a bigger payment to the same person is
  never taken as an overpayment of it. One payment can clear up to five documents from one counterparty.
  When several could be meant, the table asks you to choose (Link) and the trial balance waits. Part
  payments and overpayments are applied and flagged; a payment of the same amount under a different name is
  only suggested. Unlink undoes a match.
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

### Clients and saved work

The first page lists your clients. Add one with its company name, its business type (limited company,
sole trader, partnership or LLP), its responsible person (the client's own contact, with email and phone)
and whether it is VAT registered. Open a client to add its documents: each analysis is saved to that
client in a local database when it finishes, with the decisions you make (Link, Include, edits), so
closing the browser loses nothing. Archive hides a client and keeps everything; Restore brings it back.

- Edit corrects a row: date, description, counterparty, money in or out, amount, VAT shown, account and
  document type. The row shows "Edited", and Revert puts back what the model read. Remove deletes one row (and
  its upload once nothing of it is left); Add transaction adds a row of your own.
- What needs review shows under each row in words, and a bar above the table counts each kind of issue; click
  one to see only those rows.
- A bank statement is checked against the balances it prints. A line the model missed or misread shows
  where the balance breaks, and the upload says "Doesn't add up".
- Export to Excel downloads the client's trial balance and transactions as one workbook.
- VAT on client entertainment (7403) and on cars (0050 Cars) is not reclaimed; vans (0055 Vans) are. A
  limited company's owners use 2250 Director's Loan Account; other businesses use 3260 Drawings and
  3000 Capital Introduced. Rent from tenants goes to 4904 Rent Income, and cash from a cash machine to 1230
  Petty Cash. VAT at the 5% rate (a small business's energy) and £0.00 VAT are not flagged.

The database is one SQLite file, `data/ledgersync.db` (git-ignored), or wherever `LEDGERSYNC_DB_PATH`
points; deleting it removes every client. The endpoints are under `/api/clients`, and the design is in
`docs/superpowers/specs/2026-10-06-clients-and-local-database-design.md`.

## The AI model (OpenRouter or Groq)

The app asks OpenRouter when `OPENROUTER_API_KEY` is set, and Groq otherwise; both serve the same model
under the same name, and the other model settings (`GROQ_TIMEOUT` and the rest) apply to either, apart
from the longest answer: OpenRouter counts the model's thinking in it, so it has its own, larger limit.
OpenRouter passes each request to one of the companies hosting the model, and only to one that honours
the strict JSON schema below; the account's [privacy settings](https://openrouter.ai/settings/privacy)
decide whether a host that may keep the documents can be used. The startup log names the provider.
It asks a full-precision host first (DeepInfra), then any host running the model at 8-bit precision or
better, never a 4-bit one: left to choose, OpenRouter sent every read to a 4-bit host, which left a line
out of an expense claim every time (`OPENROUTER_PROVIDERS` and `OPENROUTER_QUANTIZATIONS` change this).
Each upload keeps the model and host that read it, e.g. `qwen/qwen3.8-27b via DeepInfra`.

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
| `GROQ_API_KEY` | — | Your Groq key; put it in `.env`. Used when there is no OpenRouter key |
| `GROQ_MODEL` | `qwen/qwen3.8-27b` | Groq model; it must read images |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq's OpenAI-compatible API |
| `GROQ_TIMEOUT` | `60` | Seconds to wait for one model call (on either provider, as are `GROQ_REASONING_EFFORT` and `GROQ_MAX_IMAGES`) |
| `GROQ_MAX_OUTPUT_TOKENS` | `8192` | Longest answer on Groq; a 60-row statement needs over 4,000 tokens |
| `GROQ_REASONING_EFFORT` | `high` | The model's "thinking" (`none`, `low`, `high`); thinking keeps it to the receipt rules, `none` is about 10x faster than `low` |
| `GROQ_MAX_IMAGES` | `3` | Scanned pages per request, Groq's most; on the free plan set `1`, as 3 overflow its 8K tokens a minute |
| `LEDGERSYNC_BUSINESS_NAME` | — | Whose books these are; tells sales invoices from purchases |
| `LEDGERSYNC_HOST` / `LEDGERSYNC_PORT` | `127.0.0.1` / `8085` | API bind address |
| `LEDGERSYNC_RELOAD` | `0` | Auto-reload on code changes (development) |
| `LEDGERSYNC_WARMUP` | `1` | Check the key and model at startup, so the header shows the problem early |
| `LEDGERSYNC_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Allowed browser origins |
| `LEDGERSYNC_MAX_UPLOAD_MB` | `20` | Largest accepted upload |
| `LEDGERSYNC_MAX_PDF_PAGES` | `30` | Most pages accepted in one PDF |
| `LEDGERSYNC_MAX_PARALLEL_JOBS` | `5` | Documents read at once; `1` reads them one at a time |
| `LEDGERSYNC_LOG_LEVEL` | `INFO` | Log level (document contents are never logged) |
| `LEDGERSYNC_DB_PATH` | `data/ledgersync.db` | The local database of clients and their saved rows |
| `API_URL` (frontend) | `http://127.0.0.1:8085` | Where the Next.js `/api` rewrite sends requests |

## Tests

```bash
.venv/bin/python -m pytest                # fast tests, no network
.venv/bin/python -m pytest -m llm         # live test against the model (needs OPENROUTER_API_KEY or GROQ_API_KEY)
```

## Measuring accuracy

`eval/` holds 31 synthetic UK documents (receipts including a mixed-VAT one and two with items of
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

To measure real documents, put anonymised copies in `eval/private/<case>/` (the input file plus an
`expected.json` in the same format) and add `--private`; that folder is never committed. After
editing `eval/eval_cases.py`, regenerate the fixtures with `.venv/bin/python eval/make_fixtures.py`.
