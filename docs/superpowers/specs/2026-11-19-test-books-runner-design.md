# Test books runner: putting the test books through the app and scoring it against the key (design, 2026-11-19)

## Why

The test books (`2026-11-18-test-books-design.md`) are made-up UK clients' paperwork with an accountant's answer key,
built to find where Super Accountant fails. Their design left one piece for later: the program that puts a client-year
or a pack through the app, reads the books back, scores them against the key, and repeats runs to measure
consistency. This is that design.

What exists to run today: the agency's year to 31 March 2024 (710 files in 31 dated batches, 578 documents in its
key, 769 statement lines, 2,550 expected entries, 3 questions with the client's replies) and five packs (28 files).
The key is waiting for an accountant's review. The runner doesn't depend on that review, but it must say so.

The research (`research_notes/test-corpus/existing-datasets-and-benchmarks.md`) says how AI bookkeeping is scored:

- **Per transaction:** account, VAT treatment, VAT amount, the document behind it (Toot Books).
- **Per period:** the VAT boxes and the trial balance, judged on the end state of the books rather than the steps.
- **Made-up or reused transactions** count as hard failures (AccountingBench).
- **Repeat runs:** right in every one of k runs (Pass^k; APEX, DualEntry), because the same model gives different
  answers on different runs.

## What it is

A command-line program in `testbooks_runner/`. For each client or pack chosen, it:

1. starts its own copies of the app, each on its own database, with a **relay** between them and the model that
   records every model call with its cost and time;
2. sets the client up as a person would, and sends its papers in batch by batch, in the order they arrived;
3. saves a snapshot of the books, passes to the app's chat the client's replies to the questions the app asked, and
   saves another;
4. scores both snapshots against the key and names the catalogue case behind each fault;
5. repeats the whole thing k times when asked, for Pass^k.

Before a run it shows what will be read and the expected cost and time. After it, it reports what the run cost.
People's verdicts on the differences it finds (the app's fault, the key's, or both acceptable) are kept from run to
run.

## Goals

- **Fair to the app.** A fault is the app's, not the runner's. The runner does only what a person would do in the
  app: set the client up, pick each statement's bank account, and paste a client's reply to the app's own question
  into the chat. It adds nothing the app could learn from.
- **Points at the cause.** Each fault names:
  - its catalogue case and stakes
  - the document or statement line
  - what the key expects and what the app did
  - where the runner can tell, whether the app misread the paper, booked it wrong, or changed it in its review or chat
- **Spends knowingly.** The cost and time come before a run and the measured cost after it. A rerun after a change
  to the booking rules can reuse earlier reads for free.
- **Never touches live data.**
- **Honest about the key.** Every report says the key is unreviewed until it is signed off. Verdicts separate the
  key's mistakes from the app's.
- **Repeatable.** Every run is saved as it came back, so it can be scored again later (a corrected key, new verdicts,
  a fix to the runner) without the app or the model.
- **Usable in pieces:** chosen packs, the smoke list, or one client-year.

## Non-goals

- **Fixing the app.** Gaps the runner finds go in its reports. The ones found while designing are listed below.
- **Changing the test books.** What the runner needs from them is listed as requests.
- **Year-end work in the app.** The runner doesn't post the key's year-end adjustments or close years. When the set
  has later years, carrying a year forward gets its own design.
- **Testing the web pages.** The runner uses the API the pages use.
- **A results page or dashboard.** Reports are files.

## Anti-goals (failure even if it "works")

- **A runner that helps the app.** That means hints in a chat message, a bank account guessed for a file the app
  refused, an answer to a question the client never answered, or retries until the app gets it right.
- **A score that hides its faults.** A number with no list of what failed and why.
- **Live data touched**, or a run that spends money without saying how much first.
- **A replayed run passed off as a live one.**

## Constraints

- **Its own folder:** `testbooks_runner/`.
  - It imports neither the app's code (`ledgersync`) nor the generator's (`testbooks`), and a test checks both.
  - It talks to the app only through its HTTP API, and reads the test books only as files, so it works on any build of
    the set and any version of the app.
- **It owns the chart table.**
  - The key uses Sage 50 numbering with FRS 105 headings (54 accounts). The app has its own Sage 50-style chart of
    129 accounts.
  - Of the key's accounts, 24 have the same code and name in the app. 23 have the same code under another name, some
    with another meaning: 4906 is bank interest in the key but grants in the app; 3260 is dividends in the key but
    drawings in the app. 7 aren't in the app's chart at all: 1290, 2125, 4010, 5100, 7410, 7550 and 9100.
- **Every document is a paid model read**, and so is each step of the app's review and chat. Hence the choice of what
  to run, the preview and the relay.
- **Its own MongoDB database**, never the live one.
- **Python 3.11.** It runs in the repo's `.venv`, the app's environment, because it starts the app with it.
- **The app's own limits**, which the runner works within and doesn't change:
  - the `X-LedgerSync` header on every change
  - five reads at once
  - files up to 20 MB and 30 pages (bigger planted files are the app's to refuse, and the runner records the refusal)
  - the review starts 20 seconds after the last change

## Approaches

All three ways considered treat the app as it is, without changing its code.

1. **Through the API, with a recording relay (picked).**
   - **How it works:** the runner starts the app with its model address (`OPENROUTER_BASE_URL`, an existing setting)
     pointed at a relay on this Mac. The relay passes every call on to OpenRouter unchanged and records it.
   - **Gains:**
     - exact cost and time for every document read, review and chat turn, so the estimate before a run is built from
       measurements
     - a rerun can answer from the recordings instead of paying again, which makes checking a fix to the booking
       rules cheap
     - no change to the app; the reader and the chat both send their calls to that address
   - **Costs:**
     - one more part to build and test, which must pass the chat's streamed answers through
     - recordings take disk space
2. **Through the API, with nothing in between.**
   - **Gains:** the least to build.
   - **Costs:**
     - Only a whole-run cost, read from the key's total spend before and after. It is wrong if anything else uses the
       key meanwhile.
     - No cost per document, so the estimate is rough.
     - Every rerun pays for every read: checking a rules fix on the agency's year costs as much as the first run, about
       577 reads.
3. **Inside the app's process, as its tests do (dropped).**
   - **Gains:** fastest, and it sees everything.
   - **Why dropped:** the runner would import the app, break when the app is reorganised, and skip the API the pages
     use.

The user picked 1.

## Decided with the user

- **The client's replies go in through the app's chat**, as the accountant would pass them on. The files that came
  with a reply are attached to its message.
- **A reply is sent only when the app asked the question it answers.** It goes under the app's own question, never
  the key's. Each reply file opens with the key's question, which states the key's treatment ("so we've put it to
  Hannah's director's loan account"), so pasting it would hand the app the answer. When the app never asked, nothing
  is sent: a client answers only what they're asked.
- **Verdicts are kept from run to run.**
- **The scoring** as played back and agreed: lining up, the checks, causes, cases, stakes, repeats and the report
  (below).
- **The relay** (approach 1).

From the brief that started this work (the session that built the test books):

- the runner's own folder, and its own chart mapping
- a choice of packs, the smoke list or one client-year, with the expected cost and time shown before a run
- its own database
- "the key is unreviewed" on every report until it is signed off
- repeat runs and Pass^k
- what to compare: `documents.csv`, `entries.csv` (honouring `also_ok` and `stakes`), `vat-returns.csv`,
  `trial-balance.csv` (with `before_answers`) and `queries.csv`, each fault reported against its catalogue case

## How a run goes

### 1. Its own app

- **The server.** The runner starts the app's server (`server.py`) from a checkout (this one by default, or another
  with `--app`, to compare a fix branch with main). It uses a free port on 127.0.0.1, so a copy of the app you already
  have running is left alone.
- **The settings it overrides**, as environment variables, which win over the app's `.env`:
  - `MONGODB_URI`: a local MongoDB (`mongodb://localhost:27017`) unless `--mongodb-uri` names another
  - `MONGODB_DB_NAME`: a database of the run's own for each copy of the app, named `tbrun_<run id>_<n>` (see the
    pool, below)
  - `LEDGERSYNC_PORT`
  - `OPENROUTER_BASE_URL`: the relay
  - `LEDGERSYNC_REVIEW_DAILY_LIMIT`: lifted (my call). A run squeezes a year of batches into an hour or two, and the
    limit of 20 reviews per client per day would cut the reviews off half-way. That would be a fault of the test,
    not of the app.
- **Safety checks.** The runner refuses to start if:
  - the database name is the one in the app's `.env`, or `ledgersync`
  - the database already holds data, unless the run is being resumed
  - the address isn't local and wasn't given with `--mongodb-uri`
- **The model key** stays in the app's `.env`, which the app reads as usual. The relay sees it only on the calls it
  passes on, and never writes it down.
- **What the run records:** the app's commit (and whether its files had uncommitted changes), the model and its
  route from `/api/health`, the set's build (its seed and generator commit, from the set's README), the runner's own
  version, and the settings.
- **A pool of copies** (my call). The runner can start several copies of the app at once: four by default, set with
  `--pool`. Each copy has its own port and its own database (`tbrun_<run id>_<n>`), and runs one client or pack at a
  time. This is needed for two reasons:
  - Every pack today is the same made-up company, and the app refuses two live clients with one name
    (`_check_name_free`). Renaming them isn't safe, because the reader is told the client's name to tell sales from
    purchases.
  - One copy reads only five files at once, and a pack waits for a review after each batch. One copy would take hours
    over the smoke list; a pool gets it near the ten minutes the test books aim for.

  One relay serves every copy. Each copy is given its own address on it, so every call is known by copy and client.

### 2. Setting up a client or pack

As a person would, from the set's `profile.json` and the key's `opening-balances.csv`:

- **The client:** `POST /api/clients` with:
  - the name and business type
  - the first year end: the end of the first period in the set, or the pack's period end
  - VAT registration and the VAT number
  - the directors, partners or members, with their shares
  - the company number
  - `ai_review` set as asked: automatic by default, as the app ships
- **Bank accounts and cards**, from the profile's accounts. A current account, savings account, card or petty cash
  becomes one of the client's bank accounts, of the kind its code says. A payment processor (Stripe, code 1250)
  isn't one: the app has no such kind, and reads a processor's report as an agent's statement.
- **Opening balances**, through `PUT /api/clients/{id}/opening-balances`:
  - the key's opening lines, put into the app's chart through the runner's chart table
  - the unpaid invoices behind Debtors and Creditors. The key doesn't list these yet (see the requests below), so
    until it does, the runner works them out from the key's first payments against Debtors and Creditors that carry
    no document. That gives names and amounts, with no invoice numbers.

A pack is set up the same way: the engine treats a pack as a small client. A pack's period can be a single month. Its
first year then ends with that month, and the opening balances are the pack's.

### 3. Sending the papers

- **The order.** Each `inbox/<arrival date>/` batch goes in date order. Within a batch, files go up to five at a time,
  through `POST /api/analyze` with the client, the year being scored, and, for a statement, its bank account.
- **Which bank account.** The runner takes the account from the key: today, from the first word of the statement's
  document ID; later, from a column the runner asks the generator to add.
- **Refusals.** If the app refuses a file (too big, unreadable, "choose which bank account", "same file"), the runner
  records the refusal and goes on. It never guesses an account the app asked a person to choose.
- **Waiting between batches.** After each batch the runner waits until every file has been read and the background
  review that follows has finished. The API doesn't report the review's state directly, so the runner watches
  `GET /api/clients/{id}/reviews` for a run that started after the batch's last read and is no longer running. If
  none appears within a time limit, it records the time-out and goes on.
- **Read failures.** A read that fails for the provider's reasons (a rate limit or a time-out) is tried once more,
  as a person would. If it fails again, the file is "not read", and the report's headline counts these.
- **Papers for another year.** Files the scored year's `documents.csv` doesn't list are left out unless
  `--with-next-year` is given (my call). The agency has 133 of them, about a fifth of the reads. When they are sent,
  the runner checks only that none of them lands in the scored year.

### 4. Snapshot before the replies

Taken once the last batch's review has finished. It holds everything the scoring needs, saved exactly as the API
returned it:

- the client and its years
- for the scored year:
  - `ledger`: rows and uploads
  - `trial-balance?shown=true` and `posted-trial-balance`, the latter with its Suspense items
  - `vat` for each VAT quarter that lies inside the year
  - `invoices`, `bank`, `summary` and `suggestions`
  - `export.xlsx`, kept for people to open
- the client's `questions`, `decisions` and `reviews`

The runner also keeps which file became which upload (from each job's result), and every refusal and failure.

### 5. The replies, through the chat

- **Only questions the app asked.** For each query in `queries.csv` that has a reply, the runner looks for a question
  the app asked about the same rows, through the lining up (below). It searches the app's questions and its reviews'
  questions, and the question must still be open or waiting once the batches are all in.
  - If there is one, the reply is sent.
  - If there isn't, nothing is sent. The query counts as not asked, and the change the reply would have made shows
    with the cause "the app never asked".
- **The order.** The replies go in date order. The client's year gets one chat (`POST /api/chat/threads`).
- **The message.** Each reply becomes one message:
  - the app's own question, in its words
  - the client's words, which are the reply file without its opening "Re:" line (that line is the key's question)
  - the files that came with the reply, attached: the other files in the same `answers/<date>/` folder. Where a folder
    holds several replies and files, the key ties each file to its query (requests, below).
- **Nothing added.** The runner adds no words of its own, so the chat gets no hints.
- **Waiting.** The runner waits for each turn's `done` event and saves its stream, then for the review that follows.
- **Questions back.** If the chat asks the runner something, the runner records the question and doesn't answer it:
  the client said all they had to say.
- **Where the chat lands.** The app opens a chat on the client's open year that holds today, or else the latest open
  one, and its tools see only that year (see the gaps below). The runner records which year the chat was on, and the
  report says so.

### 6. Snapshot after the replies, then scoring

The same contents as before the replies, plus the chat's record.

## Scoring

### Lining up

- **Files.** The runner knows which file became which upload, so every row the app read from a document is tied to
  that document in `documents.csv`. A file holding two documents, such as a photo of two receipts, is split by
  matching amounts and dates.
- **Statement lines.** Rows from a statement are paired with the key's statement lines, one to one, nearest first:
  - first the same account, the same amount and a date within three days
  - then the same account and the same date with another amount, which is a misread amount
- **Rows with nothing to pair.** A row with no counterpart in the key was made up or read twice. That is a fault (the
  research's "invented transaction"), with Accounts stakes.
- **The key's journals.** Each journal in `entries.csv` names its documents and statement lines (`doc_ids`,
  `line_ids`). Through the pairs above it is matched to the app's rows, and through `posted-trial-balance`'s journal
  to the lines those rows posted.

### The checks

Each check is against one key table.

- **Documents** (`documents.csv`): each is booked or not.
  - `book` must be booked.
  - Everything else must not be: `evidence`, `not_booked`, a copy of another document, another client's paper, or a
    document waiting for something else (which may sit in Suspense).
  - A statement is judged by its lines, not as a document.
- **Statement lines** (`statement-lines.csv`): each is read, with the right date, amount and sign. The brief didn't
  list this check, but the lining up needs it anyway.
- **Entries** (`entries.csv`), journal by journal:
  - **Accounts:** the key's lines against the app's posted lines, compared through the chart table. Any `also_ok`
    account counts as right. Where the app's chart can't draw a line the key draws (two sales accounts in the key, one
    in the app), the app's account counts as right and the difference is noted as presentation.
  - **VAT treatment**, compared through the runner's VAT table: standard, reduced, zero, exempt, outside the scope,
    reverse charge, blocked, half blocked, or none reclaimed.
  - **Amounts:** net, VAT and gross to the penny. The one tolerance is 1p on VAT and net when the app worked the VAT
    out of a gross instead of reading it (my call).
- **Unpaid at the year end** (`debtors.csv` and `creditors.csv`, as at the period's last month end) against the app's
  `invoices`: which invoices are still owed, and how much. The brief didn't list this check either. It is my call,
  because a payment cleared against the wrong invoice posts the same lines and shows up only here.
- **VAT** (`vat-returns.csv`): each quarter that lies wholly inside the year, box by box, against `vat` for that
  quarter. A quarter that straddles the start or end of the books (the agency's March to May 2023) "can't be
  compared": the app has no rows before its books start, and gives boxes only for periods inside a year.
- **Trial balance** (`trial-balance.csv`), account by account through the chart table:
  - before the replies, against `before_answers`
  - after the replies, against `final` less `year_end`

  Both are taken less the effect of the journals with no paper behind them (below). A difference that a fault on an
  entry already explains isn't counted again. What's left over is a fault of its own.
- **Queries** (`queries.csv`): each is asked or not. An app question matches a query when it is about the same rows,
  through the lining up (the query's `about` names its deals and documents). A query counts as asked if the app asked
  a matching question at any point. Questions the app asks that the key doesn't list are kept for a verdict, not
  counted as faults.

`entries.csv`'s phases decide the snapshot:

- `books`: before the replies
- `answers`: after them
- `opening`: checked through the trial balance's opening column
- `year_end`: not attempted (see below)

### Journals with no paper behind them (my call)

Some of the key's `books` journals name no document and no statement line. They are the accountant's own adjustments.
In the agency's year there are nine:

- the reversal of last year's prepayments and accrual on 1 April
- the four VAT-return transfers into 2202
- the £312 VAT correction (EC-0512)
- the bad-debt write-off with its £800 of VAT relief (EC-0363, EC-0705)

Every pack has a VAT-return transfer too.

The app's AI can't post a journal: its prompt says only a person can, with Add journal. The runner posts none. So these
journals are "not attempted", like the year-end adjustments. Their effect is taken out of every comparison they touch:

- each account in the trial balance
- for VAT relief, the box 4 of its quarter (the transfers into 2202 change no box)
- what is unpaid at the year end, for a write-off

Without this, every run would show about £221,000 of difference on the three VAT accounts alone, and three cases
could never pass. A case that rests only on such journals shows "not attempted". A case that also has a question or
an entry the app could get right is scored on those: EC-0512 is scored on whether the app asks about the £312.

### Causes

Each fault gets one cause, where the runner can tell:

- **misread:** the row's date, amount or VAT differs from what the document prints (`documents.csv` gives the
  printed net, VAT and gross)
- **booked wrong:** read right, booked to the wrong account or with the wrong VAT
- **changed by the review** or **changed by the chat:** one of their decisions touched the row (`decisions` names the
  rows)
- **not read:** the app refused the file or the read failed
- **the app never asked:** a reply's effect is missing because the app didn't ask the question it answers, so the
  reply was never sent
- **chat couldn't reach the year:** a reply was sent but its effect is missing, and the chat was on another year
- **unexplained:** none of these fits

### Cases and statuses

A catalogue case passes in a run when every check on the key rows that name it (the `cases` column) passes. Some
cases are planted many times, such as the agency's twelve monthly lease invoices. Such a case fails if any one of
them fails, and shows the count, for example "11 of 12".

The other statuses:

- **not attempted:** the case rests only on something the app doesn't do. Today that means the year-end adjustments
  (accruals, prepayments, depreciation, deferred income and the corporation tax charge) and the journals with no
  paper behind them.
- **can't be compared:** the key and the app can't be set side by side, as for a straddling VAT quarter.
- **not read:** the case's files never got read.

The report takes each case's title, category and stakes from the set's `catalogue.csv`.

### Stakes and the headline

The report is ordered by stakes: changes the tax, then changes the accounts, then presentation, then process. Its
headline gives, for each stakes level, the cases passed, failed, not attempted and can't-compare, followed by:

- the share of entries right
- the share of documents right
- the trial balance difference in pounds, before and after the replies
- the VAT box differences in pounds
- the key's questions asked
- the files not read

### Repeats

With `--repeat k`, the same selection runs k times. Each repeat gets its own copy of the app and its own database, the
same client names and live model calls. Repeats run side by side when the pool has room. A case's **Pass^k** is
passed in all k runs. The report also lists the **flaky** cases, right in some runs and wrong in others, and gives
each run's own results.

## Verdicts

- **Difference IDs.** Every difference has an ID for people, built from the client, the period, the check and the key
  row: for example `agency:2024-03-31:entry:AG-0580` or `agency:2024-03-31:query:AG-Q0580`.
- **Recognised by what they say, not by their number** (my call). The key's numbers aren't stable: the generator
  numbers deals, documents and queries in date order, so one deal added or removed renumbers everything after it. So a
  verdict, and the comparison with an earlier run, recognise a difference by what its key row says, not by its
  number. For an entry or document, that is its date, counterparty, accounts and amounts; for a query, its subject and
  wording. A verdict whose key row is no longer there, or now says something else, lapses and is listed as orphaned.
- **The spreadsheet.** Each run writes `differences.xlsx`, laid out like the accountant's catalogue review. It has one
  row per difference: its ID, the case and its title, the stakes, the check, the file and line, what the key expects,
  what the app did, the cause, and the runs it has failed in. Any earlier verdict is filled in. Four columns are left
  to fill:
  - **Verdict**, one of:
    - **app wrong:** a fault to fix
    - **key wrong:** the key's mistake
    - **both acceptable:** the app's answer is also right, and the key should accept it
    - **runner wrong:** the runner's lining up or tables are at fault
  - **What's right**
  - **Who**
  - **Date**
- **Saving verdicts.** `verdicts <file>` adds the filled-in rows to `testbooks_runner/verdicts.csv`, which is
  committed and so shared.
- **How later runs apply them:**
  - **app wrong:** still a fault, marked "known"
  - **key wrong:** left out of the score and listed apart while the key row still says what was judged. A corrected
    key ends it, and the difference is judged afresh if it still differs.
  - **both acceptable:** counts as a pass while the key row and the app's answer are the ones judged. It is listed as
    something the key should accept too.
  - **runner wrong:** left out of the score and listed for fixing the runner while the key row is the one judged, or
    until the verdict is removed.
- **For the generator's session.** "Key wrong" verdicts are written to `key-corrections.csv` in each run, with what
  the accountant says is right.

## The report

Each run gets its own folder, `testbooks_runner/runs/<date>-<label>/`, kept out of git.

**`report.md`** opens with: "The key is unreviewed: a difference may be the key's mistake." This stays until the set
carries a sign-off (requests, below). After that it gives:

- **What was run:** the selection, the app's commit, the model and route, the set's build, the review setting, and
  whether any reads were replayed and how many.
- **Cost and time**, measured against the estimate, split into reading, review and chat.
- **The headline** (above), and Pass^k when there were repeats.
- **Changes since the previous run of the same selection**, or against the run given with `--against`: new faults,
  fixed, still failing, and flipped (passing before, failing now).
- **The faults, by case,** in stakes order, each with the document, what the key expects, what the app did, the cause
  and any verdict.
- **Lists:**
  - the extra questions the app asked
  - the replies not sent because the app never asked
  - the not-attempted and can't-compare cases
  - the files not read, and the app's refusals
  - where the chat landed, and what it asked back

**The other files in the folder:**

- `differences.xlsx`: for verdicts
- `faults.csv`: one line per fault, for other tools
- `key-corrections.csv`
- `raw/`: every snapshot as it came back
- `relay/`: the recorded model calls
- `run.json`: what was run, and how far it got
- the log

## Choosing a run, its cost and time

- **What can be run:**
  - `--client agency`: its first period in the set, or `--period 2024-03-31`
  - `--packs EC-0301,EC-0346`
  - `--smoke`: the set's `packs/smoke.txt`, once it exists
  - `--all-packs`

  Each client or pack runs on a copy of the app from the pool, one at a time per copy.
- **`plan` shows, spending nothing:**
  - the files to send, by kind
  - the reads, the reviews to expect (about one per batch) and the chat turns
  - the expected cost and time

  The figures come from the relay's measurements of earlier runs: averages by kind of file, for a review and for a
  chat turn, with five reads at once on each copy in the pool. Before any run has been measured, the estimate is
  marked rough. It is then worked from OpenRouter's listed price for the model and the files' sizes.
- **The first live run** should be the five packs, about 28 files, to get measurements (my call). The agency's year
  is about 577 reads, plus the reviews and three chat turns.
- **`run` repeats the plan and asks to go ahead** (`--yes` skips the question). If the measured spend passes the
  estimate by half, it pauses and asks. Under `--yes`, it stops instead. Either way it says so (my call).

## The relay

- **Where it listens.** The relay listens on 127.0.0.1 only, on a free port. It serves every copy of the app in the
  pool, and each copy has its own address on it. It passes each call to the address the app would have used
  (OpenRouter's, or the one in the app's `.env`), unchanged. That includes the streamed answers the chat's model
  sends.
- **What it records** for each call:
  - the request and the answer
  - when it was made, and its seconds
  - its tokens, from the answer's usage
  - its cost, as OpenRouter reports it for that call
  - which part of the app made it: reader, review or chat, told apart by the shape of the request
- **The key.** It never writes down the `Authorization` header. The recordings hold the synthetic documents' content
  and stay in the git-ignored run folder.
- **Accuracy of the costs.** Totals per run, per batch and per part of the app are exact. A document's own cost is
  shared out among the reads running at the same moment. The averages behind the estimates smooth that out.
- **Replay.** `--replay <run>` answers any call identical to one recorded in that run (the same path once the copy's
  own part of the address is set aside, and the same body) from the recording, with no call and no cost. Anything else goes to the model. The reader's calls repeat exactly when the
  file, the prompt and the client's details are the same. So a rerun after a change to the booking rules pays only
  for the review and the chat (nothing, with `--review off`), and a changed prompt is read for real. Replayed calls
  are counted in the report. `--replay` can't be combined with `--repeat`, which exists to measure the model's
  variation.

## Commands

| Command | What it does |
|---|---|
| `plan <selection>` | What would be sent, and the expected cost and time. Spends nothing |
| `run <selection>` | Plan, ask, run, score and report. Options: `--repeat k`, `--pool n`, `--review automatic\|suggest\|off`, `--replay <run>`, `--with-next-year`, `--label`, `--against <run>`, `--app <path>`, `--set <path>` (default `testbooks/out`), `--yes` |
| `resume <run>` | Carries on an interrupted run from the first batch not finished. The app's "same file" refusal guards against reading anything twice |
| `score <run>` | Scores a saved run again: a corrected key, new verdicts, a fix to the runner. No app, no model |
| `verdicts <file>` | Takes the verdicts from a filled-in `differences.xlsx` |
| `clean` | Drops the runner's own databases (only names starting `tbrun_`), and old run folders when asked |

## Where things go

- `testbooks_runner/`: the code, `README.md`, `requirements.txt` (what it uses; all of it is already in the app's
  environment) and the tests
- `testbooks_runner/tables/chart.csv`: each key account and the app account or accounts that count as right, with a
  note where the meaning differs
- `testbooks_runner/tables/vat.csv`: each key VAT code and what the app's row must show for it
- `testbooks_runner/verdicts.csv`: committed
- `testbooks_runner/runs/`: git-ignored; one folder per run, plus the measurements behind the estimates

## What the runner needs from the test books

These are requests to the generator's session. The runner works around each until it is met.

1. **The unpaid invoices behind the opening Debtors and Creditors**: customer or supplier, number, date and amount.
   The agency opens with £26,400 of debtors and £5,880 of creditors, eight invoices in all, and the key names one.
   Without them the app can clear the wrong invoice: Brightwater Homes pays £7,200 on 12 April 2023 for an old
   invoice, and its new invoice that month is also £7,200.
   - *Until then:* the runner works them out from the key's first payments, as above.
2. **A sign-off record** once the accountant has signed the key off (for example `review/signed-off.txt`, with who,
   when and the build it covers), so the reports can stop saying "unreviewed".
   - *Until then:* every report says it.
3. **For each statement or platform export, which of the client's accounts it is.** `documents.csv` gives this only
   through the first word of the document ID.
   - *Until then:* the runner reads that word.
4. **Each pack's business type.** A pack's `profile.json` says `"kind": "pack"`, so the runner can't tell a limited
   company from a sole trader.
   - *Until then:* the runner goes by the name ("Ltd" is a limited company, "LLP" an LLP). All five packs today are
     Ltd.
5. **For each file in `answers/`, the query it answers.** `queries.csv` names each reply's text file but not the files
   that came with it.
   - *Until then:* the runner attaches the other files in the reply's dated folder. In the set today, every folder that
     holds files holds one reply.

## Gaps in the app found while designing

These will show in the reports. The runner doesn't work around them.

1. **A chat can't be about a past year.**
   - The app opens a chat on the client's open year that holds today, or else the latest open one. The chat's tools
     see only that year.
   - In November 2026 the agency's chat lands on the year to 31 March 2027, so the replies about 2023-24 can't change
     that year's books. The same goes for every pack.
   - The runner still sends the replies to the questions the app asked. The after-reply checks then show "chat
     couldn't reach the year" as the cause.
   - Letting a person choose the chat's year would be a small change to the app, outside this design.
2. **No adjustments of the accountant's own.** The app's AI can't post a journal, so it makes none of these:
   - year-end adjustments (accruals, prepayments, depreciation, deferred income, the corporation tax charge)
   - the reversal of last year's prepayments and accruals
   - VAT-return transfers into the VAT liability account
   - corrections and bad-debt write-offs

   A person can still enter any of them with Add journal.
3. **VAT boxes only for periods inside one year,** with no VAT scheme applied (flat rate, cash accounting). Boxes 2, 8
   and 9 are not worked out.
4. **The API doesn't say when the review will run next or whether one is running.** The runner infers this from the
   list of review runs, with a time limit.
5. **A payment processor can't be one of the client's bank accounts.** If the app refuses a processor's export for
   want of one, the runner records the refusal.

## Tests

- **Small hand-made keys and snapshots**, for:
  - the lining up, each check and each cause
  - the statuses
  - verdicts: applied, and lapsing when the key changes
  - the comparison with an earlier run
  - the estimate
- **The relay, against a fake model**:
  - passes plain and streamed answers through unchanged
  - records them and replays them
  - never writes the key down
- **One end-to-end test** that starts the real app on a throwaway database with a fake model behind the relay and runs
  a tiny pack through it, spending nothing.
- **A check** that the runner imports neither `ledgersync` nor `testbooks`.
- **Separate from the app's suite.** The runner's tests run on their own, apart from the app's slow suite.

## Done when

- `plan` shows the five packs and the agency's year, with their contents and an estimate.
- The five packs have run live once, end to end, and been scored, with the cost measured and the report saying the key
  is unreviewed.
- A rerun of the five packs with `--replay` spends nothing on reads, and scores the same where nothing changed.
- `score` scores a saved run again without the app or the model.
- A filled-in `differences.xlsx` goes back in with `verdicts`, and the next report applies it.
- `--repeat 2` on one pack gives Pass^2.
- The runner's tests pass.
- The agency's year shows an estimate from the packs' measurements. Running it is the user's call, as it spends real
  money.

## Left to the builder

- **Code:** its structure, the formats inside the run folder, exact flag names, ports, time limits and the retry
  details.
- **The relay:** how it tells the reader's calls from the review's and the chat's, and how it shares a call's cost
  among the reads running at the time.
- **The tables:** the first contents of the chart and VAT tables. "Runner wrong" verdicts correct them, and the
  accountant can look over the chart table alongside the key's review.
- **The lining up:** the tolerances for pairing statement lines and for splitting a file holding two documents.
- **Layout:** the report's, and the spreadsheet's as long as it has the columns named here.

## My calls, for checking

- **Where it lives:** the folder name `testbooks_runner/`, and running in the repo's `.venv`.
- **The database:** a local MongoDB by default; run databases named `tbrun_…`; `clean` drops only those.
- **The review:** as the app ships it (automatic) by default. Its daily limit is lifted for runs.
- **Papers for another year** are left out by default.
- **Bank accounts:** each statement's account is read from the key. Stripe isn't set up as a bank account.
- **Batches:** a batch's files go in together, as the pages send them, so the order in which they are saved can vary
  between runs.
- **Amounts:** to the penny, with 1p allowed on VAT the app worked out of a gross.
- **Extra checks** the brief didn't list: statement lines, and what is unpaid at the year end.
- **Rows the key has no line for** are faults ("made up or read twice").
- **No double counting:** a trial balance or VAT difference that an entry fault explains isn't counted again.
- **Journals with no paper behind them** (reversals, VAT-return transfers, corrections, write-offs) are "not
  attempted", and their effect is taken out of the comparisons.
- **Verdicts:** four kinds, including "runner wrong". Verdicts and comparisons between runs recognise a difference by
  what its key row says, not by the key's numbering. A verdict lapses when its key row changes.
- **Spending:** a run pauses when the spend passes the estimate by half.
- **The pool:** four copies of the app by default, each on its own database, one client or pack per copy at a time.
- **Repeats:** side by side on the pool, each in its own database under the same client names.
- **The first live run:** the five packs, to measure.
- **Resuming:** a `resume` command, since runs take hours and cost money.
