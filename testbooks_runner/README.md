# Test books runner

An outside program that puts made-up UK bookkeeping paperwork (the "test books") through Super Accountant, then
scores the books the app produced against an answer key. It finds where the app goes wrong and says which catalogue
case each fault belongs to.

**Read this first: the answer key has not been reviewed by an accountant yet.** Every report opens with "The key is
unreviewed: a difference may be the key's mistake." That line stays until the file
`<set>/review/signed-off.txt` exists (`<set>` is the folder of test books, `testbooks/out` by default). Until then,
a difference is a question, not a verdict.

## What it does

For each client or pack you pick, the runner:

1. starts its own copy of the app on its own throwaway database, with a relay between the app and the model that
   records every model call, its cost and its time;
2. sets the client up as a person would, then sends the papers in, batch by batch, in the order they arrived;
3. saves a snapshot of the books, passes the client's replies to the app's questions into the app's chat, and saves
   another snapshot;
4. scores both snapshots against the key and names the catalogue case behind each fault;
5. repeats the whole run `k` times if you ask, to see whether the app is right every time (Pass^k).

It does only what a person could do in the app. It never touches your real data: it uses databases named `tbrun_...`
and refuses the app's own database.

## Set-up

### 1. The runner's environment

From the repository root:

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt -r testbooks_runner/requirements.txt
```

This is also the app's environment: the runner starts the app with the same Python that runs the runner, so always
run it as `.venv/bin/python -m testbooks_runner`.

### 2. The test books

The generator pins pillow 13.0.0 and the app pins 12.3.0, so they cannot share one venv. Build the set with the
generator in its own venv:

```bash
python3.11 -m venv ~/testbooks-venv && ~/testbooks-venv/bin/pip install -r testbooks/requirements.txt
~/testbooks-venv/bin/python -m testbooks build --out testbooks/out --seed 7 --client agency --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430
```

The runner reads the set only as files, from `testbooks/out` unless you pass `--set <folder>`.

### 3. MongoDB

The runner uses `mongodb://localhost:27017` unless `--mongodb-uri` names another server. Nothing listens there by
default, so start a throwaway one:

```bash
mkdir -p ~/tbrun-mongo
mongod --dbpath ~/tbrun-mongo --bind_ip 127.0.0.1 --port 27017 --fork --logpath ~/tbrun-mongo/mongod.log
```

Stop it when you are done:

```bash
mongod --shutdown --dbpath ~/tbrun-mongo
```

The runner only creates, uses and drops databases whose names start `tbrun_`. A run's databases are named
`tbrun_<8 hex>_<n>`, short enough for MongoDB Atlas's 38-byte limit once the app adds `_checkpoints`. The run's
`run.json` records which database is which.

### 4. The app's `.env`

The app reads its model key from `.env` in the checkout it is started from. A git worktree has no `.env` (it is
ignored by git), so copy it from the main checkout or link it. From a worktree root:

```bash
ln -s ../../../.env .env
```

It must hold `OPENROUTER_API_KEY`. The runner reads only variable names from `.env`, plus three non-secret values:
`OPENROUTER_MODEL`, `OPENROUTER_CHAT_MODEL` and `OPENROUTER_BASE_URL` (the environment wins over `.env` for each). It
never writes the key down, and the relay records no `Authorization` header.

### 5. The measurements behind the estimates

`testbooks_runner/runs/measurements.json` holds the figures the estimates come from. Each finished run adds its own,
unless its model address is on this machine (127.0.0.1, localhost or ::1): that is a stand-in for the model, like the
end-to-end test's pretend one, and its zero cost and quick answers would make every estimate too low. The tests write
nothing under `testbooks_runner/runs/` and never touch `testbooks_runner/verdicts.csv`.

Earlier versions of the end-to-end test wrote pretend figures there (zero cost, about two seconds a file). If an
older checkout's file holds those, delete it before the first live run:

```bash
rm testbooks_runner/runs/measurements.json
```

## Commands

All commands start `.venv/bin/python -m testbooks_runner`. Costs are in US dollars (what OpenRouter charges). Money
in the books is in pounds.

### Choosing what to run

| Option | Meaning |
|---|---|
| `--client agency` | The client's first period in the set. Add `--period 2024-03-31` to pick another |
| `--packs EC-0301,EC-0346` | Those packs |
| `--smoke` | The set's `packs/smoke.txt` list (when the set has one) |
| `--all-packs` | Every pack |
| `--set <folder>` | The test books (default `testbooks/out`) |
| `--app <folder>` | The app checkout to start (default this one). Use it to compare a fix branch with main |
| `--pool N` | Copies of the app running at once (default 4) |
| `--review automatic\|suggest\|off` | How the app's AI review is set (default `automatic`, as the app ships) |
| `--repeat K` | Run the selection `K` times for Pass^k |
| `--with-next-year` | Also send the files the key does not list (the next year's papers), and count them in the plan |

### plan: what would run and what it would cost (spends nothing)

```bash
.venv/bin/python -m testbooks_runner plan --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430
.venv/bin/python -m testbooks_runner plan --client agency
```

It shows the files by kind, the reads, the reviews to expect and the chat turns, then the expected cost and time. The
figures come from earlier measured runs. Until a run has been measured, the estimate is marked rough and is worked
from OpenRouter's listed prices and guesses by kind of file. Treat a rough figure as a guide, not a limit.

Reading is priced at `OPENROUTER_MODEL`. The app runs its review and chat on `OPENROUTER_CHAT_MODEL` when that is set,
so they are priced at that model, and at the reading model when it is not. The plan names the models it priced. The
measurements stay filed under the reading model.

### run: plan, ask, run, score, report

```bash
.venv/bin/python -m testbooks_runner run --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430 --label packs-first
```

It prints the plan and asks `Go ahead? [y/N]` before it spends anything. More options:

- `--label NAME`: names the run folder (`<date>-<label>`). The default comes from the selection.
- `--yes`: skips the question. It refuses to run if the cost cannot be estimated, because there would be no
  spending guard. Run without `--yes` and answer the question instead.
- `--mongodb-uri URI`: use another MongoDB server.
- `--replay <run>`: answer identical model calls from an earlier run's recordings, for free (see below).
- `--against <run>`: compare with that run instead of the previous run of the same selection.

The spending guard: if the measured spend passes the estimate by half, the run pauses and asks. Under `--yes` it
stops instead and tells you how to resume. The spend is what OpenRouter reports for each call, a few seconds after
it. If it gives no cost for some calls, the question says how many: the spend is then a lower bound.

After the run it prints the cost and time and the headline (both from `report.md`), then where the report is.

Press Ctrl-C to stop. No more units start, each running unit finishes its current batch, then the runner stops
its app copies and exits, and the run can be resumed. The copies run in their own sessions, so the Ctrl-C reaches
the runner alone and they keep serving until their batch is done. If the runner is killed outright (`kill -9`,
or its terminal window closed), its copies keep running: `pgrep -fl server.py` lists them, and `kill <pid>`
stops one.

### resume: carry on an interrupted run

```bash
.venv/bin/python -m testbooks_runner resume 2024-03-31-packs-first
```

It carries on from the first batch not finished and does not read saved files again (the app's "same file" refusal
is counted as already saved). It keeps the run's own recorded settings, the app checkout and the set included. It
takes `--yes` and `--mongodb-uri`. It tells you what is left and what has been spent, and asks before spending.

### score: score a saved run again (no app, no model, no cost)

```bash
.venv/bin/python -m testbooks_runner score 2024-03-31-packs-first
```

Use it after a corrected key, new verdicts, or a fix to the runner. `--set <folder>` points at another set, and
`--against <run>` compares with another run. If the key has changed, files no longer in it are listed, and verdicts
whose key rows changed lapse and are listed as orphaned.

### verdicts: keep people's judgements

```bash
.venv/bin/python -m testbooks_runner verdicts testbooks_runner/runs/2024-03-31-packs-first/differences.xlsx
```

See "Judging the differences" below.

### clean: drop the runner's databases

```bash
.venv/bin/python -m testbooks_runner clean
.venv/bin/python -m testbooks_runner clean --folders-older-than 30
```

It drops **every** database named `tbrun_...` on that MongoDB server, after listing them and asking (`--yes` skips
the question). Do not run it while a run is in progress. With `--folders-older-than DAYS` it also deletes run
folders older than that.

### Replay: rerun for free

```bash
.venv/bin/python -m testbooks_runner run --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430 --replay <first run> --review off --label packs-replay --yes
```

Calls identical to one recorded in the earlier run are answered from the recording, with no call and no cost. Reads
repeat exactly when the file, the prompt and the client's details are the same. So after a change to the booking
rules you pay only for the review and the chat (nothing, with `--review off`). A changed prompt is read for real.
`--replay` cannot be combined with `--repeat`, which exists to measure the model's variation.

## Where runs go

Each run gets a folder, `testbooks_runner/runs/<date>-<label>/`, kept out of git. In it:

- `report.md`: read this first
- `differences.xlsx`: one row per difference, for people's verdicts (until the key is signed off, a second sheet,
  "Read me", carries the unreviewed banner)
- `faults.csv`: one line per fault, for other tools
- `key-corrections.csv`: what people say the key should have said
- `raw/`: every snapshot as it came back
- `relay/`: the recorded model calls
- `run.json`: what was run, how far it got, and which database is which
- the log

`testbooks_runner/runs/measurements.json` holds the measured averages behind the estimates.

## Reading a report

`report.md` opens with the unreviewed banner, then:

- **What was run:** the selection, the app's commit, the model, the set's build, the review setting, and how many
  reads were replayed.
- **Cost and time:** measured against the estimate, split into reading, review and chat. If OpenRouter gave no cost
  for some calls, it says how many, and the cost shown is then a lower bound.
- **The headline:** for each stakes level (changes the tax, changes the accounts, presentation, process), the cases
  passed, failed, not attempted and can't-compare. Then the share of entries right, the share of documents right,
  the trial balance difference before and after the replies, the VAT box differences, the key's questions asked and
  the files not read.
- **Pass^k**, when there were repeats: a case passes only if it is right in all `k` runs. A case right in some runs
  and wrong in others is listed as flaky, and each fault below says which runs it failed in.
- **Changes since the previous run:** new faults, fixed, still failing, flipped.
- **The faults, by case,** in stakes order, each with the document, what the key expects, what the app did, the
  likely cause (the app misread the paper, booked it wrong, or changed it in its review or chat) and any verdict.
- **Lists:** extra questions the app asked, replies not sent because the app never asked, not-attempted cases, files
  not read, the app's refusals, and where the chat landed.

## Judging the differences

Open `differences.xlsx`. Each row has a difference ID such as `agency:2024-03-31:entry:AG-0580`, the case, the
stakes, the check, the file and line, what the key expects, what the app did and the cause. Fill in four columns:

| Column | What to put |
|---|---|
| Verdict | `app wrong` (a fault to fix), `key wrong` (the key's mistake), `both acceptable` (the app's answer is also right), or `runner wrong` (the runner's lining up or tables are at fault) |
| What's right | The correct answer, in words |
| Who | Your name |
| Date | The date |

Then import them:

```bash
.venv/bin/python -m testbooks_runner verdicts path/to/differences.xlsx
```

This adds the rows to `testbooks_runner/verdicts.csv`, which is committed, so verdicts are shared. Later runs apply
them:

- **app wrong:** still a fault, marked "known".
- **key wrong:** left out of the score and listed apart, while the key row still says what you judged. A corrected
  key ends it.
- **both acceptable:** counts as a pass, and is listed as something the key should accept.
- **runner wrong:** left out of the score and listed for fixing the runner.

A difference is recognised by what its key row says (date, counterparty, accounts, amounts, or a query's subject),
not by its number, because the generator renumbers rows when a deal is added or removed. A verdict whose key row has
gone or changed lapses and is listed as orphaned.

## Tests

```bash
.venv/bin/python -m pytest testbooks_runner/tests -q
```

The end-to-end test needs MongoDB and spends nothing (it uses a pretend model):

```bash
LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest testbooks_runner/tests -q
```

Without that variable, tests marked `mongo` are skipped. Never run the app's own test suite for the runner: it takes
about 55 minutes.

## What the runner cannot do yet

### Gaps in the app

These will show in the reports. The runner does not work around them.

1. **A chat can't be about a past year.**
   - The app opens a chat on the client's open year that holds today, or else the latest open one. The chat's tools
     see only that year.
   - In November 2026 the agency's chat lands on the year to 31 March 2027, so the replies about 2023-24 can't change
     that year's books. The same goes for every pack.
   - The runner still sends the replies to the questions the app asked. The after-reply checks then show "chat
     couldn't reach the year" as the cause.
   - The runner asks the app to open the chat on the scored year. Today's app ignores that. The unmerged app branch
     `claude/priceless-bartik-30e023` honours it.
2. **No adjustments of the accountant's own.** The app's AI can't post a journal, so it makes none of these:
   - year-end adjustments (accruals, prepayments, depreciation, deferred income, the corporation tax charge)
   - the reversal of last year's prepayments and accruals
   - VAT-return transfers into the VAT liability account
   - corrections and bad-debt write-offs

   A person can still enter any of them with Add journal.
3. **VAT boxes only for periods inside one year,** with no VAT scheme applied (flat rate, cash accounting). Boxes 2,
   8 and 9 are not worked out.
4. **The API doesn't say when the review will run next or whether one is running.** The runner infers this from the
   list of review runs, with a time limit.
5. **A payment processor can't be one of the client's bank accounts.** If the app refuses a processor's export for
   want of one, the runner records the refusal.

### Requests to the test books generator

The runner works around each of these until it is met.

1. **The unpaid invoices behind the opening Debtors and Creditors:** customer or supplier, number, date and amount.
   The agency opens with 26,400 pounds of debtors and 5,880 of creditors, eight invoices in all, and the key names
   one. Without them the app can clear the wrong invoice. Until then, the runner works them out from the key's first
   payments.
2. **A sign-off record** (for example `review/signed-off.txt`, with who, when and the build it covers) once an
   accountant has signed the key off. Until then, every report says the key is unreviewed.
3. **For each statement or platform export, which of the client's accounts it is.** `documents.csv` gives this only
   through the first word of the document ID, which is what the runner reads.
4. **Each pack's business type.** A pack's `profile.json` says `"kind": "pack"`, so the runner goes by the name
   ("Ltd" is a limited company, "LLP" an LLP). All five packs today are Ltd.
5. **For each file in `answers/`, the query it answers.** `queries.csv` names each reply's text file but not the files
   that came with it. The runner attaches the other files in the reply's dated folder. Today every folder that holds
   files holds one reply.
