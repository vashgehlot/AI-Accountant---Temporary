# The accounting site, by client and year: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Super Accountant as a site where each client's work is split into years and sections. Along the way, fix the accounting errors found on 2026-10-23: invoices paid late booked twice, payroll, no years, a single bank account, and accounts missing from the chart.

**Architecture:**
- **Rows:** a client's rows stay in one MongoDB document per client, as now.
- **Matching:** runs over all of a client's rows, whatever their year, so a payment in one year can clear an invoice from another.
- **Years:** a year's views take that year's rows. Its trial balance is its opening balances plus that year's journal. The opening balances are worked out from earlier years, or taken from the closing balances saved when the previous year was closed.
- **Website:** the Next.js site is rebuilt as a layout with a side menu and a year picker, over year-scoped API routes.
- **Agent:** the Phase 1 agent job comes out until the agent project.

**Tech Stack:**
- Backend: Python 3.11, FastAPI, Pydantic v2, pymongo (MongoDB and GridFS).
- Frontend: Next.js 16 with React 18 and TypeScript, unit tests on `node --test`.

**Spec:** `docs/superpowers/specs/2026-10-23-accounting-site-design.md`. Read it before starting: this plan argues from it.

## Global Constraints

- **Money:** `Decimal` in Python, an exact decimal string in MongoDB and in JSON (`"12.50"`). Never use floats for money.
- **Documents:** never change an amount, date or VAT that a document shows. Only a person's edit does that, and the store keeps the original, as today.
- **No silent mistakes:** every case the site can't decide puts a warning or an error on the row (an `Issue`). It must never balance by booking something twice or leaving it out without saying so.
- **Closed years:** a closed year never changes unless it is reopened first.
- **MongoDB only.** With `MONGODB_URI` unset, the API refuses to start with: `Set MONGODB_URI in .env: Super Accountant keeps its data in MongoDB.`
- **Account codes are Sage 50-style.** Use the codes fixed in Task 3, exactly.
- **Tests:** they use the fake model (`tests/fakes.py`) and need no key. MongoDB tests run against a local MongoDB.
  - Start it with `brew services start mongodb-community`.
  - Run the suite as `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`.
  - Frontend tests: `cd frontend && npm test`.
- **Model credit:** never run `eval/run_eval.py` or `eval/run_job_eval.py`, or anything else that calls the real model, without the accountant's OK. These runs spend credit.
- **Wording on screen and in errors:** plain English sentences, matching the existing tone. Money is written `£1,200.00`. Dates are written `31 Mar 2026`.
- **Stack:** stays as it is: FastAPI, Next.js and MongoDB. Don't add frontend dependencies. The agent project will use LangChain, so leave the pinned `langchain`, `langgraph` and `langchain-openai` lines in `requirements.txt`.
- **Simplicity:** an MVP on test data for one accountant. Where there are two ways, pick the simpler one.

## Review Focus

These are the inputs most likely to break the site in use that no task's main tests cover. Each has a test added to the task that owns the code.

1. **A bank statement that crosses the year end.** Its rows are split between the two years, and its balance check still runs over the whole statement, not each year's part. Test: Task 7, `test_a_statement_across_the_year_end_is_split_but_checked_whole`.
2. **A payment in an open year for an invoice from a closed year.** The closed year's figures don't move, and the invoice shows as paid. Test: Task 8, `test_paying_a_closed_years_invoice_leaves_that_year_alone`.
3. **A credit card statement**, whose balance rises as money is spent. It must not be flagged as "doesn't add up". Test: Task 6, `test_a_credit_card_statement_adds_up_when_spending_raises_the_balance`.
4. **Reopening the latest closed year, editing it and closing it again.** The next year opens from the new closing balances. Test: Task 8, `test_reopen_edit_and_close_again_moves_the_next_years_opening`.
5. **Importing from a folder that holds a file already uploaded under another name**, plus files that can't be read (`.DS_Store`, `.zip`). The duplicate is skipped and the unreadable files are listed, never read. Test: Task 10, `test_import_skips_known_contents_and_lists_unreadable_files`.

---

## Before you start

- [ ] Create the branch from `accounting-agent`, keeping today's uncommitted TrialBalancePanel styling fix as its own commit:

```bash
git switch accounting-agent
git add frontend/src/components/TrialBalancePanel.tsx frontend/src/app/globals.css
git commit -m "fix: show the trial balance's summary cards in the page's theme"
git switch -c accounting-site
```

- [ ] Start a local MongoDB and run the suite once, to know the baseline.
  - Run: `brew services start mongodb-community && LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: every test passes (on 2026-10-23, 14 failed against the remote cluster, all on dropped connections).

## File map

| File | What it's for |
|---|---|
| `ledgersync/rows.py` (new) | What `store.py` shared with `store_mongo.py`: `INPUTS`, `EDITABLE`, `WHOLE_DOCUMENT`, `StoredRow`, `saved_form`, `now_iso`, `OLD_TOTAL` |
| `ledgersync/store_mongo.py` | The only store. Gains bank accounts, years, opening balances, closed years and the client's folder |
| `ledgersync/accounts.py` | The chart, with the new accounts and the bank account slots |
| `ledgersync/matching.py` | Matching, with the late-payment rule, transfers, payroll exclusion and brought-forward items |
| `ledgersync/checks.py` | Row checks: payroll warnings, a sale on a bank line with no VAT |
| `ledgersync/statements.py` | Statement balance check, signed for credit cards |
| `ledgersync/years.py` (new) | Year arithmetic: bounds, the year a date falls in, labels |
| `ledgersync/books.py` (new) | A client's year: its ledger, trial balance, opening balances, invoices, bank checks, summary, close and reopen |
| `ledgersync/ledger.py` | Client and row actions, now refusing changes in a closed year |
| `ledgersync/posting.py` | Journal and trial balance, over the rows a year keeps, with opening balances |
| `ledgersync/folder.py` (new) | Finds the new files in a client's folder |
| `ledgersync/extractor.py`, `ledgersync/adapter.py` | The payroll summary and the client's bank accounts in the prompt |
| `server.py` | Year-scoped routes. The agent, requests and SQLite paths are gone |
| `frontend/src/app/clients/[id]/[year]/layout.tsx` and `.../[section]/page.tsx` (new) | The client space: header, year picker, side menu, the sections |
| `frontend/src/lib/years.ts` (new) | Sections, routes and year labels for the pages |
| `frontend/src/components/*` | Reused sections, plus `BankSection`, `InvoicesSection`, `OverviewSection`, `OpeningBalancesForm` |
| `eval/run_job_eval.py`, `eval/jobs/*` | Score a client's year trial balance, with no agent |

---

### Task 1: Take out the agent job, its records, client emails and the client's upload page

**Files:**
- Delete:
  - `ledgersync/agent/` (all), `ledgersync/records/` (all), `ledgersync/notify.py`, `ledgersync/gate.py`
  - `frontend/src/components/JobPanel.tsx`, `frontend/src/components/JobPanel.css`
  - `frontend/src/lib/agentJobs.ts`, `frontend/src/lib/agentJobs.test.ts`
  - `frontend/src/app/requests/` (all), `frontend/src/lib/requests.ts`, `frontend/src/lib/requests.test.ts`
  - `tests/test_agent_graph.py`, `tests/test_agent_jobs_api.py`, `tests/test_agent_nodes.py`, `tests/test_agent_tools.py`, `tests/test_audit.py`, `tests/test_exceptions.py`, `tests/test_job_records.py`, `tests/test_snapshots.py`, `tests/test_notify.py`, `tests/test_requests_api.py`, `tests/test_gate.py` (keep `tests/test_live_llm.py`: it tests document reading)
- Modify:
  - `server.py`: remove every agent, request, reminder, snapshot and `Busy` path, and `JobPeriod`.
  - `ledgersync/config.py`: remove `agent_model`, `agent_max_fix_rounds`, `public_url`, the SMTP settings and `MAX_FIX_ROUNDS`.
  - `ledgersync/errors.py`: remove `AgentNotConfigured`, `JobRunning` and `EmailNotSent` if nothing else uses them.
  - `frontend/src/app/clients/[id]/page.tsx`: remove JobPanel, the row lock and the "Add to account" button.
- Test: `tests/test_api.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `create_app(settings=None, *, model_client=None, store=None, blobs=None) -> FastAPI` (the `agent_nodes` and `notifier` keywords are gone).

- [ ] **Step 1: Write the failing test** in `tests/test_api.py`:

```python
def test_the_agent_and_request_routes_are_gone(app_client):
    paths = {route.path for route in app_client.app.routes}
    assert not any(p.startswith(("/api/agent-jobs", "/api/requests")) or "agent-jobs" in p for p in paths)
```

  Use the module's existing app fixture, or add `app_client` built the way the module already builds its client.

- [ ] **Step 2: Run it to make sure it fails.**
  - Run: `.venv/bin/python -m pytest tests/test_api.py::test_the_agent_and_request_routes_are_gone -q`
  - Expected: FAIL.
- [ ] **Step 3:** Delete the files listed and strip `server.py`, `config.py` and the client page as listed. `grep -rn "agent\|notify\|records\|gate\|JobPanel\|agentJobs" ledgersync server.py frontend/src tests` should then find only the `agent` field of an agent's statement and its uses in `models`, `adapter`, `matching`, `extractor` and the eval cases.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q && (cd frontend && npm test && npx tsc --noEmit)`
  - Expected: all pass, no type errors.
- [ ] **Step 5: Commit.** `git commit -am "refactor: take out the agent job, its records, client emails and upload page until the agent project"` (use `git add -A` for the deletions).

### Task 2: MongoDB is the only store

**Files:**
- Create: `ledgersync/rows.py`
- Delete: `ledgersync/store.py`, `tests/test_store.py` (port any case it has that `tests/test_store_mongo.py` lacks)
- Modify:
  - `ledgersync/store_mongo.py` (import from `rows`), `ledgersync/ledger.py`, `server.py`
  - `ledgersync/config.py`: remove `db_path`.
  - `.env.example`: list every setting `Settings.from_env` reads, with its default.
  - `tests/test_ledger.py`, `tests/test_clients_api.py`, `tests/test_export.py`, `tests/test_jobs.py`, `tests/test_blobs.py`: use the `mongo_store` fixture.
  - `README.md`: the Clients section's database paragraph.
- Test: `tests/test_config.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `ledgersync.rows` with `INPUTS: set[str]`, `EDITABLE: tuple[str, ...]`, `WHOLE_DOCUMENT: set[str]`, `class StoredRow(NamedTuple): id, upload_id, tx, original`, `saved_form(tx) -> dict`, `now_iso() -> str` and `OLD_TOTAL: re.Pattern`.
- Produces: `MongoStore` is the store type everywhere. `ledgersync.store_mongo.Store = MongoStore` is not kept: rename the imports.
- Produces: `create_app` raises `StorageError("Set MONGODB_URI in .env: Super Accountant keeps its data in MongoDB.")` when `settings.mongodb_uri` is empty and no store is passed.

- [ ] **Step 1: Write the failing tests:**

```python
def test_without_mongodb_the_api_refuses_to_start():
    with pytest.raises(StorageError, match="Set MONGODB_URI in .env"):
        create_app(Settings(mongodb_uri=""), model_client=FakeModel())

def test_env_example_lists_every_setting():
    listed = {line.split("=")[0].lstrip("# ").strip() for line in Path(".env.example").read_text().splitlines() if "=" in line}
    assert set(ENV_NAMES) <= listed   # ENV_NAMES: a tuple in config.py of every variable from_env reads
```

  A blank number setting (`LEDGERSYNC_PORT=`) falls back to its default: add `test_a_blank_number_setting_uses_its_default`.

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_api.py -q`
  - Expected: the three new tests fail.
- [ ] **Step 3:** Move the shared helpers into `ledgersync/rows.py`, delete `store.py`, and point every importer at `rows` or `store_mongo`. Add `ENV_NAMES` to `config.py` and use it in `from_env`. Rewrite `.env.example`. Move the store-based tests to `mongo_store`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git add -A && git commit -m "refactor: keep everything in MongoDB and remove the SQLite store"`

### Task 3: The chart gains the accounts a company needs, and bank account slots

**Files:**
- Modify: `ledgersync/accounts.py`, `ledgersync/extractor.py` (the chart in the prompt), `eval/eval_cases.py` and regenerated `eval/fixtures/*/expected.json` (only where an expected row used 3000)
- Test: `tests/test_accounts.py`

**Interfaces:**
- **Produces these new accounts** (code, name, type, usual VAT, `reclaim_vat`):

| Code | Name | Type | VAT | Notes |
|---|---|---|---|---|
| 0031 | Office Equipment Depreciation | asset | outside | accumulated; ledger-only for now |
| 0041 | Furniture and Fixtures Depreciation | asset | outside | ledger-only |
| 0051 | Cars Depreciation | asset | outside | ledger-only |
| 0056 | Vans Depreciation | asset | outside | ledger-only |
| 1103 | Prepayments | asset | outside | ledger-only |
| 1201 | Bank Current Account 2 | asset | outside | bank slot |
| 1202 | Bank Current Account 3 | asset | outside | bank slot |
| 1211 | Bank Deposit Account 2 | asset | outside | bank slot |
| 1240 | Company Credit Card | liability | outside | bank slot |
| 1241 | Company Credit Card 2 | liability | outside | bank slot |
| 2109 | Accruals | liability | outside | ledger-only |
| 2220 | Net Wages | liability | outside | net pay owed to staff from a payroll report, cleared by the bank payments |
| 2230 | Pension Fund | liability | outside | pension owed to the provider |
| 2320 | Corporation Tax | liability | outside | limited companies only |
| 3000 | Ordinary Shares | equity | outside | limited companies only (renamed from Capital Introduced) |
| 3010 | Capital Introduced | equity | outside | not limited companies (moved from 3000) |
| 3100 | Owner's Capital Account | equity | outside | ledger-only: where a non-company's profit closes |
| 3200 | Retained Earnings | equity | outside | ledger-only: where a company's or LLP's profit closes |
| 3250 | Dividends | equity | outside | limited companies only |
| 6201 | Advertising and Marketing | expense | standard | |
| 7001 | Directors' Salaries | expense | outside | limited companies only |
| 7006 | Employer's National Insurance | expense | outside | |
| 7007 | Employer's Pension Contributions | expense | outside | |
| 8000 | Depreciation | expense | outside | ledger-only for now |
| 8250 | Fines and Penalties | expense | outside | "not tax-deductible" in its definition |
| 8800 | Corporation Tax Charge | expense | outside | limited companies only, ledger-only for now |

- Produces: constants
  - `CAPITAL = "3010"`, `SHARES = "3000"`, `DIVIDENDS = "3250"`, `RETAINED = "3200"`, `OWNERS_CAPITAL = "3100"`;
  - `NET_WAGES = "2220"`, `PAYE = "2210"`, `PENSION = "2230"`;
  - `BANK_SLOTS: dict[str, tuple[str, ...]] = {"current": ("1200","1201","1202"), "savings": ("1210","1211"), "credit_card": ("1240","1241"), "petty_cash": ("1230",)}`;
  - `ALL_BANK_CODES: frozenset[str]` (every slot).
- Produces: `reserve_for(business_type: str) -> str`, which returns `"3200"` for `limited_company` and `llp` and `"3100"` otherwise.
- Produces: `choosable(business_type: Optional[str] = None, bank_codes: tuple[str, ...] = ()) -> tuple[Account, ...]`.
  - It leaves out the ledger-only accounts and every bank slot except those in `bank_codes`.
  - With no client (`bank_codes == ()`), 1210 stays offered as today, and 1230 is always offered.
  - Limited-company-only accounts are hidden from other business types. 3010 and 3260 are hidden from limited companies.
  - `model_accounts()` keeps its meaning: what `choosable(None)` offers, before the business-type filter.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_company_is_offered_shares_dividends_and_directors_salaries():
    codes = {a.code for a in choosable("limited_company")}
    assert {"3000", "3250", "7001", "2250", "2320"} <= codes and not {"3010", "3260", "3100", "3200"} & codes

def test_a_sole_trader_is_offered_capital_and_drawings_only():
    codes = {a.code for a in choosable("sole_trader")}
    assert {"3010", "3260"} <= codes and not {"3000", "3250", "7001", "2250", "2320"} & codes

def test_only_the_clients_own_bank_accounts_are_offered():
    codes = {a.code for a in choosable("limited_company", bank_codes=("1200", "1240"))}
    assert {"1240"} <= codes and not {"1201", "1211", "1241"} & codes

def test_profit_closes_to_retained_earnings_or_the_owners_capital():
    assert reserve_for("limited_company") == reserve_for("llp") == "3200"
    assert reserve_for("sole_trader") == reserve_for("partnership") == "3100"
```

  Update `test_accounts.py` lines that expect `"3000"` for non-companies to `"3010"`.

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `.venv/bin/python -m pytest tests/test_accounts.py -q`
  - Expected: FAIL.
- [ ] **Step 3:** Add the accounts, constants and `reserve_for`, and extend `choosable`. In `checks.normalise`, the director's-loan rule now names 3010 and 3260 (and 3000 and 3250 for non-companies). `TransactionExtractor.__init__` takes `bank_codes: tuple[str, ...] = ()` and lists `choosable(self.business_type, self.bank_codes)` in the prompt. Regenerate fixtures with `.venv/bin/python eval/make_fixtures.py` after updating `eval_cases.py`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: add the accounts a company needs, and slots for more bank accounts and cards"`

### Task 4: A payment clears an invoice however late, and never silently doubles it

**Files:**
- Create: `tests/helpers.py`
- Modify: `ledgersync/matching.py`, `ledgersync/checks.py` (`MATCHING_ISSUES`), `frontend/src/lib/ledger.ts` (title for the new issue)
- Test: `tests/test_matching.py`, `tests/test_posting.py`

**Interfaces:**
- Produces: `tests/helpers.py: row(**overrides) -> Transaction`, a receipt for £0.00 on 7600 dated 1 Jan 2026, out, GBP, with whatever is overridden. `SETTINGS = BusinessSettings(business_name="Acme Ltd", vat_registered=True, business_type="limited_company")`. Later tasks use both.
- Produces: in `matching.py`, `PART_WINDOW = dt.timedelta(days=120)`. The issue code is `"open_document"`, severity `"warning"`, with the message `May pay {label}: not matched because {why}. Link it if so.` and `candidates` set.

- [ ] **Step 1: Write the failing tests:**

```python
def test_an_exact_payment_clears_an_invoice_paid_45_days_later():
    invoice = row(date=date(2026,1,10), counterparty="Smith Solicitors Ltd", gross=D("1200.00"), vat=D("200.00"),
                  document_type="invoice", document_ref="d1")
    paid = row(date=date(2026,2,24), counterparty="Smith Solicitors", gross=D("1200.00"),
               document_type="statement", document_ref="b1")
    tb = trial_balance([invoice, paid], SETTINGS)
    assert net(tb, "7600") == D("1000.00") and net(tb, "2100") == 0   # net(): debit minus credit, 0 if absent

def test_a_part_payment_matches_only_within_120_days():
    invoice = row(date=date(2026,1,10), counterparty="Smith Solicitors Ltd", gross=D("1200.00"),
                  document_type="invoice", document_ref="d1")
    part = row(date=date(2026,4,1), counterparty="Smith Solicitors", gross=D("600.00"), document_type="statement")
    late = part.model_copy(update={"date": date(2026,6,1)})
    assert match_one(invoice, part).pays          # match_one: matched bank line of [invoice, line]
    assert not match_one(invoice, late).pays

def test_an_unmatched_line_to_someone_with_an_open_invoice_is_never_silent():
    invoice = row(date=date(2026,1,10), counterparty="Smith Solicitors Ltd", gross=D("1200.00"),
                  document_type="invoice", document_ref="d1")
    line = row(date=date(2026,8,1), counterparty="Smith Solicitors", gross=D("450.00"), document_type="statement")
    issue = only_issue(match_one(invoice, line), "open_document")
    assert issue.severity == "warning" and "Smith" in issue.message
```

  Write the small helpers `net`, `match_one` and `only_issue` in `tests/helpers.py`.

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `.venv/bin/python -m pytest tests/test_matching.py tests/test_posting.py -q`
  - Expected: the three new tests fail.
- [ ] **Step 3:** In `matching.py`:
  - `_could_pay` keeps `doc.date <= line.date` and drops the upper bound for an exact amount. `_exact`'s callers in `match` and `_decide` take documents dated on or before the line, at any age.
  - Sets, part payments and overpayments use documents within `PART_WINDOW`.
  - `WINDOW` stays as the bound for `_paid_before` suggestions.
  - In `_settle`, when the result is `"none"` and documents from the same counterparty are open (any date, either side), add the `open_document` warning with those documents as candidates.
  - Add `"open_document"` to `MATCHING_ISSUES` and a title "May pay an open invoice" to `ISSUE_TITLES` in `frontend/src/lib/ledger.ts`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q && (cd frontend && npm test)`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "fix: clear an invoice paid late instead of booking it twice, and flag unmatched payments to open accounts"`

### Task 5: Wages are booked from the payroll report

**Files:**
- Modify:
  - `ledgersync/models.py`: `DocumentType` gains `"payroll"`, placed before `"quote"` so `NOT_TRANSACTIONS = DOCUMENT_TYPES[6:]`.
  - `ledgersync/extractor.py`: the field `owed_to`, and prompt rule 2.
  - `ledgersync/adapter.py`, `ledgersync/checks.py`, `ledgersync/matching.py` (`_documents` excludes payroll).
  - `frontend/src/lib/clientRules.ts`: `DOCUMENT_TYPES` label "Payroll report".
  - `frontend/src/lib/ledger.ts`: issue titles.
- Test: `tests/test_adapter.py`, `tests/test_checks.py`, `tests/test_posting.py`, `tests/test_extractor.py`

**Interfaces:**
- Produces: `AccountingTransaction.owed_to: Optional[Literal["net_pay", "paye_ni", "pension"]]` (null except on a payroll report).
- **Prompt rule for `"payroll"`:**
  - A payroll report or payroll summary from payroll software.
  - It gives, as separate transactions, all "out" and dated the pay date:
    - net pay (account 7000, or 7001 for directors), `owed_to` `"net_pay"`;
    - employees' tax and NI (7000 or 7001), `owed_to` `"paye_ni"`;
    - employees' pension (7000 or 7001), `owed_to` `"pension"`;
    - employer's NI (7006), `owed_to` `"paye_ni"`;
    - employer's pension (7007), `owed_to` `"pension"`.
  - On a bank statement, net pay to staff is coded 2220 Net Wages, payments to HMRC for PAYE and NI 2210, and payments to the pension provider 2230.
- Produces: the adapter sets `contra_account_code` from `owed_to`: `net_pay` → `"2220"`, `paye_ni` → `"2210"`, `pension` → `"2230"`.
- **Issue codes** (`warning`):
  - `"no_payroll"`: on a bank line on 2220, 2210 or 2230 with no payroll report dated in the same calendar month or the one before. Message: `No payroll report for {Month YYYY}: add it so wages are booked in full.`
  - `"wages_from_bank"`: on a bank line coded 7000 or 7001. Message: `Book wages from the payroll report: code net pay to 2220 Net Wages.`

- [ ] **Step 1: Write the failing tests:**

```python
def test_net_pay_and_paye_from_the_report_and_the_bank_book_wages_in_full():
    pay = dict(date=date(2026,3,28), document_type="payroll", document_ref="p1")
    report = [row(**pay, gross=D("3000.00"), account_code="7000", contra_account_code="2220"),
              row(**pay, gross=D("1000.00"), account_code="7000", contra_account_code="2210"),
              row(**pay, gross=D("100.00"), account_code="7006", contra_account_code="2210")]
    bank = [row(date=date(2026,3,28), gross=D("3000.00"), account_code="2220", document_type="statement"),
            row(date=date(2026,4,19), gross=D("1100.00"), account_code="2210", document_type="statement")]
    tb = trial_balance(report + bank, SETTINGS)
    assert net(tb, "7000") == D("4000.00") and net(tb, "7006") == D("100.00")
    assert net(tb, "2220") == net(tb, "2210") == 0 and net(tb, "1200") == D("-4100.00")

def test_a_wages_payment_with_no_payroll_report_is_flagged():
    line = row(date=date(2026,3,28), gross=D("3000.00"), account_code="2220", document_type="statement")
    assert "March 2026" in only_issue(normalise_and_match([line])[0], "no_payroll").message

def test_a_bank_line_coded_to_wages_is_told_to_use_the_report():
    line = row(gross=D("3000.00"), account_code="7000", document_type="statement")
    assert only_issue(normalise_and_match([line])[0], "wages_from_bank")

def test_owed_to_sets_the_payroll_rows_other_account():
    rows = to_transactions([payroll_row(owed_to="net_pay"), payroll_row(owed_to="pension", account="7007")], "text", SETTINGS)
    assert [r.contra_account_code for r in rows] == ["2220", "2230"]
```

  `normalise_and_match(rows, settings=SETTINGS) -> list[Transaction]` (normalise each row, then `match`) and `payroll_row(**overrides) -> dict` (one model answer row of a payroll report) go in `tests/helpers.py`. `only_issue(tx, code) -> Issue` is the one issue of that code on a row, and fails the test when there isn't exactly one.

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `.venv/bin/python -m pytest tests/test_posting.py tests/test_checks.py tests/test_adapter.py -q`
  - Expected: FAIL.
- [ ] **Step 3:** Add the document type, the field, the prompt rule, the adapter mapping and the two warnings. Each warning goes where it can see the whole client's rows: `no_payroll` in `matching.match`, because it needs the other rows (add it to `MATCHING_ISSUES`); `wages_from_bank` in `normalise` (add it to `_DERIVED`). `_documents` leaves out `document_type == "payroll"`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q && (cd frontend && npm test)`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "fix: book wages from the payroll report, and flag wages paid without one"`

### Task 6: A client has bank accounts and credit cards

**Files:**
- Modify:
  - `ledgersync/models.py`: `BankAccount`, and `ClientFields.bank_accounts`.
  - `Transaction.bank_account` (an input: add it to `rows.INPUTS`).
  - `Upload.bank_account`, `BusinessSettings.bank_accounts`.
  - `ledgersync/store_mongo.py`: client fields, `add_upload(bank_account=)`, and `set_upload_bank(client_id, upload_id, code)`, which also sets the bank account of that upload's rows.
  - `ledgersync/ledger.py`: `settings_for`, `check_client`, and assigning codes.
  - `ledgersync/checks.py`: `other_side` and `normalise` take a row's bank account.
  - `ledgersync/matching.py`: `_pair_transfers`.
  - `ledgersync/statements.py`: credit card signs.
  - `server.py`: `/api/analyze` takes the form field `bank_account`, and the new route `PATCH /api/clients/{id}/uploads/{upload_id}`.
- Test: `tests/test_ledger.py`, `tests/test_matching.py`, `tests/test_statements.py`, `tests/test_clients_api.py`

**Interfaces:**
- Produces: `BankAccountKind = Literal["current", "savings", "credit_card", "petty_cash"]` and `class BankAccount(BaseModel): code: str = ""; name: str; kind: BankAccountKind`.
  - `ClientFields.bank_accounts: list[BankAccount]` defaults to `[BankAccount(code="1200", name="Bank current account", kind="current")]`.
  - `ledger.check_client` refuses an empty list, a blank name, two accounts with one name, or more accounts of a kind than `BANK_SLOTS` has codes for: `You can add up to {n} {kind} accounts.`
  - `ledger.assign_codes(accounts: list[BankAccount], kept: list[BankAccount]) -> list[BankAccount]` gives each account without a code the next free slot of its kind. It keeps the code of an account whose code is sent, and refuses to drop an account that rows still use: `{name} has transactions: move them to another account first.`
- Produces: `BusinessSettings.bank_accounts: tuple[str, ...] = (BANK,)`, the client's codes. The first current account is the default bank, `settings.bank_account`.
  - `checks.other_side` returns `tx.bank_account or settings.bank_account` for a receipt or bank line.
  - `normalise`'s `worked_out` set includes every code in `settings.bank_accounts`.
- Produces: `/api/analyze` and `PATCH /api/clients/{id}/uploads/{upload_id}` (body `{"bank_account": "1240"}`, returns `Ledger`) set the bank account of an upload's rows.
  - With several accounts and no `bank_account` sent, a statement upload is refused with 422: `Choose which bank account this statement is for.` The page always sends it.
- Produces: a **transfer** between the client's own accounts.
  - The pair: a statement line A with bank X coded to Y, and a statement line B with bank Y coded to X. Both X and Y are client codes, A and B go in opposite directions with the same gross, and their dates are at most 3 days apart.
  - Booking: B gets `recorded_by` A's ref and isn't booked, so the transfer posts once. B gets an `info` issue `"transfer"`: `The other side of {A's description} on {A's date}: booked once, from that line.` Add it to `MATCHING_ISSUES`.
  - It reuses the `recorded_by` and `booked()` path receipts already use.
- Produces: `check_statement(rows, credit_card: bool = False)`. For a credit card, money out raises the balance owed, so the signs are reversed.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_transfer_between_the_clients_own_accounts_books_once():
    s = SETTINGS.model_copy(update={"bank_accounts": ("1200", "1210")})
    out = row(gross=D("5000.00"), account_code="1210", bank_account="1200", document_type="statement", document_ref="a")
    into = row(direction="in", gross=D("5000.00"), account_code="1200", bank_account="1210", document_type="statement", document_ref="b")
    tb = trial_balance([out, into], s)
    assert net(tb, "1200") == D("-5000.00") and net(tb, "1210") == D("5000.00")

def test_a_credit_card_statement_adds_up_when_spending_raises_the_balance():
    lines = [row(gross=D("40.00"), document_type="statement", balance=D("140.00"), opening_balance=D("100.00")),
             row(gross=D("10.00"), document_type="statement", balance=D("150.00"), closing_balance=D("150.00"))]
    _, check = check_statement(lines, credit_card=True)
    assert check.status == "ok"

def test_a_statement_for_a_client_with_two_accounts_must_say_which(api, client_with_two_accounts):
    # the fake model answers with one bank statement line
    job = api.post("/api/analyze", data={"client_id": client_with_two_accounts, "text": "Bank lines"},
                   headers={"X-LedgerSync": "1"}).json()
    failed = wait_for_job(api, job["job_id"])   # the module's existing helper for polling a job to its end
    assert failed["status"] == "failed" and "Choose which bank account" in failed["error"]["message"]
    assert api.get(f"/api/clients/{client_with_two_accounts}/ledger").json()["uploads"] == []   # Task 7 moves this to the year route

def test_new_accounts_get_the_next_free_code_of_their_kind():
    got = assign_codes([BankAccount(name="Main", kind="current", code="1200"), BankAccount(name="Second", kind="current"),
                        BankAccount(name="Amex", kind="credit_card")], kept=[])
    assert [a.code for a in got] == ["1200", "1201", "1240"]
```

  Whether an upload is a statement is only known after reading, so the refusal is the job's error (a 422 `InvalidInput` raised before the rows are saved), not the POST's answer. Match the job dict's shape to what `JobStore` returns today.

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL.
- [ ] **Step 3:** Implement as listed. `ledger.build` passes `credit_card=` for each upload by its bank account's kind. `TransactionExtractor` gets `bank_codes` = the client's codes other than the upload's own. `ledger.settings_for(client)` fills `bank_accounts` and `bank_account`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: keep each bank account and credit card apart, and book transfers between them once"`

### Task 7: Years, opening balances and a year's trial balance

**Files:**
- Create: `ledgersync/years.py`, `ledgersync/books.py`, `tests/test_years.py`, `tests/test_books.py`
- Modify:
  - `ledgersync/models.py`: `ClientFields.first_year_end`, plus `Year`, `OpeningLine`, `OpenItem`, `OpeningBalances`, `Upload.year_start`, `Ledger.year`, `Ledger.years`, `TrialBalance.opening`.
  - `ledgersync/store_mongo.py`: `first_year_end`, `opening` on the client document, `add_upload(year_start=)`, `set_opening(client_id, OpeningBalances)`.
  - `ledgersync/posting.py`: `keep` and `opening`.
  - `ledgersync/matching.py`: `open_items`.
  - `server.py`: the year routes; the undated routes `/ledger`, `/trial-balance` and `/export.xlsx` are removed.
  - `ledgersync/ledger.py`: its `build`, `trial_balance` and `export` move into `books.py`.
- Test: `tests/test_years.py`, `tests/test_books.py`, `tests/test_clients_api.py`

**Interfaces:**
- **`years.py`**
  - `year_bounds(first_year_end: date, n: int) -> tuple[date, date]`, for year n (0 is the first). Each year ends on the first year end's day and month; a 29 Feb end becomes 28 Feb in a year that has none. The start is the day after the previous end.
  - `year_index(first_year_end: date, day: date) -> Optional[int]`: None before the first year starts.
  - `label(end: date) -> str`: `"Year to 31 Mar 2026"`.
- Produces: `class Year(BaseModel): start: date; end: date; label: str; closed: bool = False`.
- Produces: `ClientFields.first_year_end: date` (required). `ledger.check_client` refuses a missing one with `Enter the client's first year end.`
- **Opening balances:**
  - `class OpeningLine(BaseModel): code: str; debit: Decimal = 0; credit: Decimal = 0`.
  - `class OpenItem(BaseModel): id: str; direction: Direction; counterparty: str; amount: Decimal; number: Optional[str] = None; date: Optional[date] = None`. Direction `in` means a customer owes the client; `out` means the client owes a supplier.
  - `class OpeningBalances(BaseModel): lines: list[OpeningLine] = []; unpaid: list[OpenItem] = []`.
- **`books.py`:**
  - `years_of(store, client_id, today: date) -> list[Year]`: the first year through the latest year that holds a row, or holds today, whichever is later.
  - `year_of_row(client, row: StoredRow, uploads_by_id) -> Optional[int]`: by the row's date, or by its upload's `year_start` when it has no date.
  - `ledger(store, client_id, year_start: date) -> Ledger`: matched over all rows, with only that year's rows returned. It includes the uploads holding any of them, plus the uploads added to that year.
  - `opening(store, client_id, year_start: date) -> dict[str, Decimal]`, signed with debits positive: the first year's typed lines; or the previous year's saved closing (Task 8); or the balances of every row before the year plus the first year's lines. In the last case, income and cost accounts are summed into `reserve_for(business_type)`.
  - `trial_balance(store, client_id, year_start: date) -> TrialBalance`.
  - `set_opening(store, client_id, opening: OpeningBalances) -> Client`, which checks the opening balances (below).
- **Checks on opening balances:**
  - Lines may only use asset, liability and equity accounts, other than the reserves (3100 and 3200 are allowed).
  - Debits must equal credits: `Opening debits £{d} and credits £{c} must be the same.`
  - The unpaid `in` items must add up to the 1100 balance, and the unpaid `out` items to the 2100 balance: `The unpaid invoices from customers add up to £{x}; Debtors is £{y}.`
- Produces: `posting.trial_balance(transactions, settings, read=None, apart=None, *, keep: Optional[list[bool]] = None, opening: Optional[dict[str, Decimal]] = None, open_items: Sequence[OpenItem] = ()) -> TrialBalance`.
  - Only rows where `keep` is true are posted and checked for errors.
  - `opening` is added before the movements, and is also returned as `TrialBalance.opening: list[TrialBalanceLine]`.
- Produces: `matching.match(..., open_items: Sequence[OpenItem] = ())`. Each item is an open `_Document`: ref `f"ob-{id}"`, kind `"invoice"`, account `1100` for `in` and `2100` for `out`, dated the day before the first year starts, described as `f"Brought forward: {number or counterparty}"`.
  - Produces: `matching.match_documents(...) -> tuple[list[Transaction], dict[str, DocumentStatus]]`, where `DocumentStatus` has `open: Decimal` and `paid_by: list[Settlement]`, keyed by ref. `match` keeps returning the rows only. Task 9 uses the statuses.
- **Routes (all return JSON):**
  - `GET /api/clients/{id}/years` → `list[Year]`
  - `GET /api/clients/{id}/years/{start}/ledger` → `Ledger`
  - `GET /api/clients/{id}/years/{start}/trial-balance` → `TrialBalance`
  - `GET /api/clients/{id}/years/{start}/export.xlsx`
  - `GET` and `PUT /api/clients/{id}/opening-balances` → `OpeningBalances`
  - `/api/analyze` takes `year_start`, the year picked when the file was added.
  - An unknown `{start}` (not a year start of the client) is a 404: `That year was not found.`

- [ ] **Step 1: Write the failing tests:**

```python
def test_years_run_from_the_first_year_end():
    assert year_bounds(date(2026,3,31), 0) == (date(2025,4,1), date(2026,3,31))
    assert year_bounds(date(2026,3,31), 1) == (date(2026,4,1), date(2027,3,31))
    assert year_bounds(date(2024,2,29), 1) == (date(2024,3,1), date(2025,2,28))
    assert year_index(date(2026,3,31), date(2025,3,31)) is None

def test_the_second_year_opens_with_the_first_years_closing_and_its_profit_in_retained_earnings(store, acme):
    # acme: limited company, first year end 31 Mar 2026; one sale of £1,200 (VAT £200) paid into the bank in year 1,
    # one £60 stationery receipt in year 2
    tb = books.trial_balance(store, acme, date(2026,4,1))
    opening = {l.code: l.debit - l.credit for l in tb.opening}
    assert opening == {"1200": D("1200.00"), "2200": D("-200.00"), "3200": D("-1000.00")}
    assert net(tb, "7504") == D("60.00") and net(tb, "1200") == D("1140.00")

def test_a_payment_in_year_one_clears_an_unpaid_bill_brought_forward(store, acme):
    books.set_opening(store, acme, OpeningBalances(
        lines=[OpeningLine(code="1200", debit=D("500.00")), OpeningLine(code="2100", credit=D("500.00"))],
        unpaid=[OpenItem(id="1", direction="out", counterparty="Smith Solicitors Ltd", amount=D("500.00"))]))
    add_rows(store, acme, row(date=date(2025,5,2), counterparty="Smith Solicitors", gross=D("500.00"), document_type="statement"))
    tb = books.trial_balance(store, acme, date(2025,4,1))
    assert net(tb, "2100") == 0 and net(tb, "7600") == 0 and net(tb, "1200") == 0

def test_opening_balances_must_balance_and_agree_with_the_unpaid_invoices(store, acme):
    with pytest.raises(InvalidInput, match="must be the same"):
        books.set_opening(store, acme, OpeningBalances(lines=[OpeningLine(code="1200", debit=D("10.00"))]))
    with pytest.raises(InvalidInput, match="Debtors is £300.00"):
        books.set_opening(store, acme, OpeningBalances(
            lines=[OpeningLine(code="1100", debit=D("300.00")), OpeningLine(code="3000", credit=D("300.00"))],
            unpaid=[OpenItem(id="1", direction="in", counterparty="Bright Cafe", amount=D("200.00"))]))

def test_a_statement_across_the_year_end_is_split_but_checked_whole(store, acme):
    # one statement upload: a line on 30 Mar 2026 and a line on 2 Apr 2026, opening and closing balances that add up
    year1, year2 = books.ledger(store, acme, date(2025,4,1)), books.ledger(store, acme, date(2026,4,1))
    assert len(year1.transactions) == len(year2.transactions) == 1
    assert year1.uploads[0].statement.status == year2.uploads[0].statement.status == "ok"

def test_an_undated_row_belongs_to_the_year_it_was_added_to(store, acme):
    add_rows(store, acme, row(date=None, gross=D("9.00")), year_start=date(2026,4,1))
    assert not books.ledger(store, acme, date(2025,4,1)).transactions
    [undated] = books.ledger(store, acme, date(2026,4,1)).transactions
    assert any(i.code == "date_missing" for i in undated.issues)
```

  `store` is `mongo_store`. `acme` and `add_rows` go in `tests/helpers.py` as fixtures and helpers that use `store.create_client` and `store.add_upload`.

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL (module not found).
- [ ] **Step 3:** Implement `years.py`, `books.py`, the posting and matching parameters, and the routes.
  - Every year's view runs `match_documents` over all of the client's rows and the open items.
  - `check_statement` runs per upload over all of that upload's rows, before the year filter.
  - The earlier rows' balances for `opening` come from a `posting` pass with `keep` set to the rows before the year.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: split a client's work into years, carried forward, with opening balances for the first"`

### Task 8: Closing and reopening a year

**Files:**
- Modify:
  - `ledgersync/models.py`: `ClosedYear` and `Client.closed_years`.
  - `ledgersync/store_mongo.py`: `close_year` and `reopen_year`.
  - `ledgersync/books.py`: `close`, `reopen`, and the saved closing balances used in `opening`.
  - `ledgersync/ledger.py`: refuse writes in a closed year.
  - `server.py`: run_analysis refuses to save rows into a closed year.
  - `ledgersync/errors.py`: `YearClosed` (409, code `"year_closed"`).
- Test: `tests/test_books.py`, `tests/test_clients_api.py`

**Interfaces:**
- Produces: `class ClosedYear(BaseModel): start: date; end: date; closed_at: str; closing: dict[str, Decimal]`, the signed balances at the year's end by account. `Client.closed_years: list[ClosedYear] = []`.
- **`books.close(store, client_id, year_start) -> Client`** refuses when:
  - an earlier year is still open: `Close the year to {date} first.`
  - the trial balance can't be built, or doesn't balance: `The trial balance must balance before the year is closed.`
- **`books.reopen(store, client_id, year_start) -> Client`** reopens only the latest closed year: `Reopen the year to {date} first.`
- **Write guard:** `ledger.ensure_open(client, days: Iterable[Optional[date]], year_start: Optional[date] = None) -> None` raises `YearClosed("The year to {end} is closed. Reopen it to change it.")`.
  - It is called by `change_row` (with the row's old and new date), `remove_row`, `remove_upload`, `add_manual`, the save in `run_analysis`, `set_upload_bank`, `set_opening` (when the first year is closed) and `change_client` when `first_year_end` changes.
  - Changing `first_year_end` is refused outright once any year is closed: `The year end can't change once a year is closed.`
- **Drift check:** `opening()` of the year after a closed year uses its saved `closing`. `books.ledger` of a closed year sets `Ledger.year.changed_since_closed: bool` (add the field to `Year`, default False) when the closing worked out now differs from the saved one.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_closed_year_refuses_changes(store, acme_with_year_one):
    books.close(store, acme_with_year_one, date(2025,4,1))
    with pytest.raises(YearClosed, match="Reopen it"):
        ledger.change_row(store, acme_with_year_one, first_row_id(store, acme_with_year_one), RowPatch(account_code="7502"))

def test_years_close_in_order_and_reopen_from_the_latest(store, acme_two_years):
    with pytest.raises(InvalidInput, match="Close the year to 31 Mar 2026 first"):
        books.close(store, acme_two_years, date(2026,4,1))
    books.close(store, acme_two_years, date(2025,4,1)); books.close(store, acme_two_years, date(2026,4,1))
    with pytest.raises(InvalidInput, match="Reopen the year to 31 Mar 2027 first"):
        books.reopen(store, acme_two_years, date(2025,4,1))

def test_paying_a_closed_years_invoice_leaves_that_year_alone(store, acme_with_unpaid_bill_in_year_one):
    before = books.trial_balance(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    books.close(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,5,10)))
    after = books.ledger(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1))
    assert books.trial_balance(store, acme_with_unpaid_bill_in_year_one, date(2025,4,1)).lines == before.lines
    assert not after.year.changed_since_closed and bill_row(after).owed == 0

def test_reopen_edit_and_close_again_moves_the_next_years_opening(store, acme_two_years):
    # acme_two_years: year 1 holds a £60.00 stationery receipt paid from the bank (no VAT shown); year 2 one row
    def bank_opening():
        tb = books.trial_balance(store, acme_two_years, date(2026,4,1))
        return {l.code: l.debit - l.credit for l in tb.opening}["1200"]
    books.close(store, acme_two_years, date(2025,4,1))
    before = bank_opening()
    books.reopen(store, acme_two_years, date(2025,4,1))
    change_stationery_receipt_to(store, acme_two_years, D("80.00"))
    books.close(store, acme_two_years, date(2025,4,1))
    assert bank_opening() == before - D("20.00")
```

  The fixtures and helpers named here go in `tests/helpers.py`, each a few lines over `store.add_upload` and `ledger.change_row`.

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL.
- [ ] **Step 3:** Implement as listed. Add routes `POST /api/clients/{id}/years/{start}/close` and `POST .../reopen`, both returning `Client`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: close a year to lock it and carry its closing balances forward"`

### Task 9: Invoices, bank checks and the year's summary

**Files:**
- Modify: `ledgersync/models.py` (`InvoiceSummary`, `BankCheck`, `YearSummary`), `ledgersync/books.py`, `server.py`
- Test: `tests/test_books.py`

**Interfaces:**
- **Invoices:** `class InvoiceSummary(BaseModel)` has `ref: str`, `kind: Literal["sale", "purchase"]`, `counterparty: Optional[str]`, `number: Optional[str]`, `date: Optional[date]`, `total: Decimal`, `paid: Decimal`, `owed: Decimal`, `paid_by: list[Settlement]` and `brought_forward: bool`.
  - `books.invoices(store, client_id, year_start) -> list[InvoiceSummary]` lists the booked invoices (`document_type == "invoice"`) dated in the year.
  - It also lists earlier invoices and open items that were still owed at the year's start, oldest first.
  - `kind` is `"sale"` when the document's account is 1100.
  - `owed` is the document's open amount after every payment in any year.
- **Bank checks:** `class BankCheck(BaseModel)` has `code: str`, `name: str`, `kind: BankAccountKind`, `books: Decimal`, `statement: Optional[Decimal]`, `statement_date: Optional[date]` and `difference: Optional[Decimal]`.
  - `books.bank_checks(store, client_id, year_start) -> list[BankCheck]` gives one per bank account.
  - `statement` is the closing balance of the latest-dated statement for that account in the year.
  - `books` is the account's balance in the books on that date, from the opening plus posted rows up to it, shown the way the statement prints it: positive for money held, and positive for what's owed on a card.
  - `difference = books - statement`.
- **Summary:** `class YearSummary(BaseModel)` has `year: Year`, `rows: int`, `to_review: int`, `unpaid_sales: Decimal`, `unpaid_purchases: Decimal`, `bank: list[BankCheck]`, `trial_balance: Literal["balanced", "blocked"]` and `problems: list[str]`.
  - `books.summary(store, client_id, year_start) -> YearSummary`.
  - `"blocked"` means `InvalidTransactions` was raised, and `problems` holds its problems.
- Routes: `GET .../years/{start}/invoices`, `.../bank` and `.../summary`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_an_invoice_paid_next_year_shows_as_owed_at_the_year_end_and_paid_now(store, acme_with_unpaid_bill_in_year_one):
    add_rows(store, acme_with_unpaid_bill_in_year_one, the_bills_payment_dated(date(2026,5,10)))
    [bill] = books.invoices(store, acme_with_unpaid_bill_in_year_one, date(2026,4,1))
    assert bill.kind == "purchase" and bill.owed == 0 and bill.paid_by[0].date == date(2026,5,10)

def test_the_bank_check_compares_the_books_with_the_statement(store, acme_with_statement_missing_a_line):
    [check] = books.bank_checks(store, acme_with_statement_missing_a_line, date(2025,4,1))
    assert check.difference == D("-25.00") and check.statement_date == date(2025,9,30)

def test_a_blocked_trial_balance_shows_in_the_summary(store, acme_with_a_non_gbp_row):
    s = books.summary(store, acme_with_a_non_gbp_row, date(2025,4,1))
    assert s.trial_balance == "blocked" and "Convert" in s.problems[0]
```

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL.
- [ ] **Step 3:** Implement on top of `match_documents` (Task 7) and `posting.trial_balance`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: list a year's invoices, compare each bank account with its statements, and summarise the year"`

### Task 10: Import a client's files from a folder

**Files:**
- Create: `ledgersync/folder.py`, `tests/test_folder.py`
- Modify: `ledgersync/models.py` (`ClientFields.folder: str = ""`), `ledgersync/store_mongo.py`, `ledgersync/ledger.py` (`check_client`: a folder that is set must be an existing directory: `That folder doesn't exist on this computer.`), `server.py`
- Test: `tests/test_folder.py`, `tests/test_clients_api.py`

**Interfaces:**
- Produces: `folder.new_files(root: Path, known: set[str]) -> FolderScan`, where `FolderScan(new: list[tuple[Path, bytes, str]], skipped: list[str], unreadable: list[str])`.
  - It walks `root` recursively, ignoring hidden files and folders.
  - `new` holds each unread file with its bytes and sha256, one per distinct contents.
  - `skipped` holds the names of files whose sha256 is in `known` or repeats one already found.
  - `unreadable` holds the names whose extension `intake` doesn't accept.
- Produces: `POST /api/clients/{id}/import-folder` with body `{"year_start": "2025-04-01", "bank_account": "1200"}`. It needs the `X-LedgerSync` header, as `/api/analyze` does.
  - For each new file: check it as `/api/analyze` does, keep it in the blob store, and submit the same analysis job.
  - It returns `{"jobs": [{"name": str, "job_id": str}], "skipped": [str], "unreadable": [str], "refused": [{"name": str, "message": str}]}`.
  - A client with no folder set gets 422: `Set this client's folder first.`

- [ ] **Step 1: Write the failing tests:**

```python
def test_import_skips_known_contents_and_lists_unreadable_files(tmp_path):
    (tmp_path / "statement.csv").write_bytes(b"Date,Amount\n01/09/2026,-12.00\n")
    (tmp_path / "statement copy.csv").write_bytes(b"Date,Amount\n01/09/2026,-12.00\n")
    (tmp_path / "old.csv").write_bytes(b"Date,Amount\n02/09/2026,-5.00\n")
    (tmp_path / ".DS_Store").write_bytes(b"x"); (tmp_path / "backup.zip").write_bytes(b"PK")
    scan = new_files(tmp_path, known={sha256(b"Date,Amount\n02/09/2026,-5.00\n")})
    assert [p.name for p, _, _ in scan.new] == ["statement copy.csv"]     # sorted path order: " " sorts before "."
    assert scan.skipped == ["old.csv", "statement.csv"]
    assert scan.unreadable == ["backup.zip"]

def test_import_without_a_folder_is_refused(api, acme_id):
    r = api.post(f"/api/clients/{acme_id}/import-folder", json={"year_start": "2025-04-01"}, headers={"X-LedgerSync": "1"})
    assert r.status_code == 422 and "Set this client's folder first" in r.text
```

  Walk files in sorted path order. `sha256` here is a hex-digest helper in the test module.

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL.
- [ ] **Step 3:** Implement `folder.py` and the route, reusing the analysis job function from `server.py`. Factor it out to `submit_analysis(item, client, name, sha256, content_type, data, year_start, bank_account) -> job`.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "feat: import a client's new files from its folder"`

### Task 11: The smaller VAT points

**Files:**
- Modify: `ledgersync/accounts.py` (the usual VAT), `ledgersync/checks.py`
- Test: `tests/test_checks.py`

**Interfaces:**
- **Usual VAT rates:**
  - 7400 Travel becomes `STANDARD`, with its definition noting that rail, bus and air fares are zero-rated. A zero VAT figure isn't flagged, as now.
  - 7501 Postage becomes `STANDARD`; Royal Mail stamps show no VAT.
  - 7100 Rent becomes `EXEMPT`, with its definition noting that VAT is charged only when the landlord has opted to tax.
  - These only change which VAT figures are flagged as a mismatch.
- **New issue** `"sale_without_vat"` (`warning`, add it to `_DERIVED`): on a VAT-registered client's bank line coded to an income account with a standard usual rate and no VAT shown. Message: `A sale with no VAT shown: book it from its invoice, or choose its VAT rate.`

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_vat_registered_sale_from_a_bank_line_without_vat_is_flagged():
    line = row(direction="in", gross=D("600.00"), account_code="4000", document_type="statement")
    assert only_issue(normalise(line, SETTINGS), "sale_without_vat").severity == "warning"
    assert not any(i.code == "sale_without_vat" for i in normalise(line, SETTINGS.model_copy(update={"vat_registered": False})).issues)

def test_a_bank_line_that_pays_a_sales_invoice_is_not_flagged():
    invoice = row(direction="in", gross=D("600.00"), vat=D("100.00"), account_code="4000", counterparty="Bright Cafe",
                  document_type="invoice", document_ref="s1")
    paid = row(direction="in", date=date(2026,1,5), gross=D("600.00"), account_code="4000", counterparty="Bright Cafe",
               document_type="statement")
    assert not any(i.code == "sale_without_vat" for i in normalise_and_match([invoice, paid])[1].issues)
```

  The second test means the warning belongs in `matching.match`, on a line left unpaired. So add `"sale_without_vat"` to `MATCHING_ISSUES`, not `_DERIVED`.

- [ ] **Step 2: Run them to make sure they fail.** Expected: FAIL.
- [ ] **Step 3:** Implement. Rerun `tests/test_checks.py` and `tests/test_eval_fixtures.py`, and update any assertion that relied on the old usual rates.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q`
  - Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -am "fix: flag a sale with no VAT shown, and correct the usual VAT on travel, postage and rent"`

### Task 12: The client space: routes, side menu, year picker and client details

**Files:**
- Create:
  - `frontend/src/lib/years.ts`, `frontend/src/lib/years.test.ts`
  - `frontend/src/app/clients/[id]/[year]/layout.tsx`, `frontend/src/app/clients/[id]/[year]/[section]/page.tsx`
  - `frontend/src/components/ClientYearContext.tsx`
- Modify:
  - `frontend/src/app/clients/[id]/page.tsx`: becomes a redirect to the latest year's Overview.
  - `frontend/src/lib/clients.ts`: the year-scoped calls and types from Tasks 6 to 10.
  - `frontend/src/components/ClientDialog.tsx`: first year end, bank accounts and folder.
  - `frontend/src/components/AppHeader.tsx`: Clients link; empty space on the right for the agent button.
  - `frontend/src/app/page.tsx`: each client's current year and Open/Closed.
  - `frontend/src/app/globals.css`: side menu and year picker.

**Interfaces:**
- Produces in `years.ts`:
  - `SECTIONS = [{slug: 'overview', title: 'Overview'}, {slug: 'documents', title: 'Documents'}, {slug: 'bank', title: 'Bank'}, {slug: 'invoices', title: 'Invoices'}, {slug: 'transactions', title: 'Transactions'}, {slug: 'trial-balance', title: 'Trial balance'}] as const`
  - `sectionHref(clientId: number, yearStart: string, slug: SectionSlug): string`, giving `/clients/7/2025-04-01/bank`
  - `latestYear(years: Year[]): Year`
  - `yearOption(year: Year): string`, giving `"Year to 31 Mar 2026"`, plus `" · closed"` when closed
- Produces in `clients.ts`:
  - `getYears(id)`, `getYearLedger(id, start)`, `getYearTrialBalance(id, start)`, `getInvoices(id, start)`, `getBankChecks(id, start)`, `getSummary(id, start)`, `closeYear(id, start)`, `reopenYear(id, start)`, `getOpening(id)`, `putOpening(id, opening)`, `importFolder(id, start, bankAccount)`, `setUploadBank(id, uploadId, code)`, `yearExportUrl(id, start)`
  - Types `Year`, `BankAccount`, `OpeningBalances`, `InvoiceSummary`, `BankCheck`, `YearSummary`, matching the Python models. Money is a `string`.
- Produces: `ClientYearContext` gives `{ client, year, years, ledger, reload(): Promise<void>, error }` to every section. The layout loads it, and an unknown section slug shows "Section not found" with a link to Overview.

- [ ] **Step 1: Write the failing tests** in `years.test.ts`:

```ts
test('section links carry the client and the year', () => {
  assert.equal(sectionHref(7, '2025-04-01', 'bank'), '/clients/7/2025-04-01/bank')
})
test('the year picker names the year end and says when it is closed', () => {
  assert.equal(yearOption({ start: '2025-04-01', end: '2026-03-31', label: 'Year to 31 Mar 2026', closed: true }), 'Year to 31 Mar 2026 · closed')
})
test('the latest year is the one that ends last', () => {
  assert.equal(latestYear([y('2025-04-01'), y('2026-04-01')]).start, '2026-04-01')
})
```

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `cd frontend && npm test`
  - Expected: FAIL.
- [ ] **Step 3:** Build `years.ts`, the context, the layout and the section page. The section page switches on the slug; until Tasks 13 to 15 fill them, each section shows its title.
  - **Layout:** header with the client's name and a `<select>` year picker that navigates to the same section in the chosen year; side menu with `<nav>` links, the current one marked `aria-current="page"`; the section in the middle.
  - **ClientDialog:** first year end (date input, required), bank accounts (a list of name and kind with Add and Remove; codes come back from the API), and folder (text input).
- [ ] **Step 4:** Run `cd frontend && npm test && npx tsc --noEmit`. Expected: pass. Then start the API and the UI (`preview_start` in the Claude app, or `npm run dev`). Add a client with a first year end and two bank accounts, open it, and check that the side menu and the year picker work. Take a screenshot.
- [ ] **Step 5: Commit.** `git commit -am "feat: the client space with a side menu of sections and a year picker"`

### Task 13: Documents and Transactions sections

**Files:**
- Create: `frontend/src/components/DocumentsSection.tsx`, `frontend/src/components/TransactionsSection.tsx`
- Modify: `frontend/src/components/AddDocuments.tsx` (`yearStart`, `bankAccounts`, Import from folder), `frontend/src/components/UploadsList.tsx` (each statement's bank account, changeable), `frontend/src/lib/api.ts` (`analyze` sends `year_start` and `bank_account`), `frontend/src/lib/clientRules.ts` (`importText(result)`), `frontend/src/lib/clientRules.test.ts`

**Interfaces:**
- Consumes: Task 12's context and `clients.ts` calls.
- Produces: `importText(r: ImportResult): string`, for example `"Reading 3 new files. Skipped 2 already taken in. 1 can't be read: backup.zip."`. Each part is left out when its count is 0. When nothing is new: `"No new files in the folder."`

- [ ] **Step 1: Write the failing tests** in `clientRules.test.ts`:

```ts
test('the import says what it found', () => {
  assert.equal(importText({ jobs: [j(), j(), j()], skipped: ['a', 'b'], unreadable: ['backup.zip'], refused: [] }),
    "Reading 3 new files. Skipped 2 already taken in. 1 can't be read: backup.zip.")
  assert.equal(importText({ jobs: [], skipped: ['a'], unreadable: [], refused: [] }), 'No new files in the folder.')
})
```

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `cd frontend && npm test`
  - Expected: FAIL.
- [ ] **Step 3:** Build both sections from today's components.
  - **Documents:** an "Add to: [bank account ▾]" picker, shown when the client has more than one account and sent with every upload; "Import from folder" (disabled with a hint when no folder is set), whose result reads in `importText`; and the uploads list.
  - **Transactions:** today's `TransactionsTable`, `EditRowDialog` and Add transaction, over the year's ledger.
  - **Closed year:** both sections are read-only, with the notice "This year is closed. Reopen it from Trial balance to change it."
- [ ] **Step 4:** Run `cd frontend && npm test && npx tsc --noEmit`. Expected: pass. Then, in the running app:
  - Upload a CSV to one of two bank accounts.
  - Edit a row.
  - Import from a test folder holding one new file and one copy.
  - Screenshot the Documents section.
- [ ] **Step 5: Commit.** `git commit -am "feat: the Documents and Transactions sections, with import from the client's folder"`

### Task 14: Bank and Invoices sections

**Files:**
- Create: `frontend/src/components/BankSection.tsx`, `frontend/src/components/InvoicesSection.tsx`, `frontend/src/lib/sections.ts`, `frontend/src/lib/sections.test.ts`

**Interfaces:**
- Produces in `sections.ts`:
  - `bankCheckText(c: BankCheck): string`:
    - `"Agrees with the statement of 30 Sep 2025."`;
    - `"£25.00 less in the books than the statement of 30 Sep 2025."` (or "more");
    - `"No statement this year."`
  - `linesFor(ledger: Ledger, code: string): SavedRow[]`: the year's rows whose bank account is `code`, or that are coded to it (transfers in).
  - `splitInvoices(list: InvoiceSummary[]): { sales: InvoiceSummary[]; purchases: InvoiceSummary[] }`.

- [ ] **Step 1: Write the failing tests:**

```ts
test('the bank check says whether the books agree with the statement', () => {
  assert.equal(bankCheckText(check({ difference: '0.00', statement_date: '2025-09-30' })), 'Agrees with the statement of 30 Sep 2025.')
  assert.equal(bankCheckText(check({ difference: '-25.00', statement_date: '2025-09-30' })), '£25.00 less in the books than the statement of 30 Sep 2025.')
  assert.equal(bankCheckText(check({ statement: null, difference: null, statement_date: null })), 'No statement this year.')
})
test('invoices split into sales and purchases', () => {
  const { sales, purchases } = splitInvoices([inv('sale'), inv('purchase'), inv('sale')])
  assert.equal(sales.length, 2); assert.equal(purchases.length, 1)
})
```

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `cd frontend && npm test`
  - Expected: FAIL.
- [ ] **Step 3:** Build the two sections.
  - **Bank:** a tab for each bank account. Each tab shows `bankCheckText` above that account's lines (read-only here; editing happens in Transactions).
  - **Invoices:** Sales and Purchases lists with counterparty, number, date, total, paid, owed (highlighted when above £0.00), "Brought forward" for open items, and the dates of the payments that paid it.
- [ ] **Step 4:** Run `cd frontend && npm test && npx tsc --noEmit`. Expected: pass. Then, in the app, open a client with two accounts and an unpaid invoice, and screenshot both sections.
- [ ] **Step 5: Commit.** `git commit -am "feat: the Bank and Invoices sections"`

### Task 15: Overview, Trial balance with Close year, and opening balances

**Files:**
- Create: `frontend/src/components/OverviewSection.tsx`, `frontend/src/components/OpeningBalancesForm.tsx`
- Modify: `frontend/src/components/TrialBalancePanel.tsx` (year-scoped, opening column, Close and Reopen year), `frontend/src/lib/sections.ts` and its tests

**Interfaces:**
- Produces in `sections.ts`:
  - `openingErrors(o: OpeningBalances): string[]`, the same three rules as `books.set_opening`, checked before sending, in the same words.
  - `closeQuestion(year: Year): string`, giving `"Close the year to 31 Mar 2026? Its figures are locked and carried into the next year. You can reopen it later."`

- [ ] **Step 1: Write the failing tests:**

```ts
test('opening balances must balance', () => {
  assert.deepEqual(openingErrors({ lines: [{ code: '1200', debit: '10.00', credit: '0.00' }], unpaid: [] }),
    ['Opening debits £10.00 and credits £0.00 must be the same.'])
})
test('closing a year asks first', () => {
  assert.match(closeQuestion(year('2026-03-31')), /^Close the year to 31 Mar 2026\?/)
})
```

- [ ] **Step 2: Run them to make sure they fail.**
  - Run: `cd frontend && npm test`
  - Expected: FAIL.
- [ ] **Step 3:** Build the three pieces.
  - **Overview:** the client's details with Edit (the `ClientDialog`); the year's status; and the summary from `getSummary`: rows to review, unpaid sales and purchases, each bank check's text, and whether the trial balance balances or what blocks it. When `changed_since_closed`, show a warning: "This closed year's figures no longer match what was saved when it was closed."
  - **Trial balance:** opening, movement and closing columns; the export for the year; Close year (asks `closeQuestion`) or Reopen year. In the first year, an "Opening balances" form: account lines plus the list of unpaid invoices, read-only once the first year is closed.
- [ ] **Step 4:** Run `cd frontend && npm test && npx tsc --noEmit`. Expected: pass. Then, in the app:
  - Enter opening balances.
  - Upload the payment of a brought-forward bill and see it cleared in Invoices.
  - Close year 1, and check that year 2's opening matches year 1's closing.
  - Screenshot the trial balance.
- [ ] **Step 5: Commit.** `git commit -am "feat: the Overview and Trial balance sections, closing a year, and opening balances"`

### Task 16: The client-level test set scores a year's trial balance, and the README

**Files:**
- Modify: `eval/run_job_eval.py`, `eval/job_scoring.py`, `eval/jobs/*/client.json` (add `first_year_end` and `bank_accounts`), `tests/test_job_scoring.py`, `tests/test_eval_runner.py`, `README.md`
- Delete: `eval/jobs/*/period.json`
- Create: these cases, each with `notes.md`, its documents, and an `expected_trial_balance.json` worked out by hand:
  - `eval/jobs/ltd-late-paid-invoice/`: a bill paid after 45 days;
  - `eval/jobs/ltd-payroll/`: a payroll report plus net pay and HMRC on the bank;
  - `eval/jobs/ltd-two-accounts-transfer/`: a current account and a savings account with a transfer on both statements.

**Interfaces:**
- Consumes: `POST /api/clients`, `/api/analyze` with `year_start` and `bank_account`, and `GET /api/clients/{id}/years/{start}/trial-balance`.
- Produces: `run_case(client, case, ...)`. It adds the client, reads every document into the first year (a statement goes to the account named for it in `client.json`'s `"statements": {"file name": "bank account name"}`), and scores the year's trial balance with `net_by_account(trial_balance: dict)`.

- [ ] **Step 1: Write the failing test** in `tests/test_eval_runner.py`, against a fake HTTP client in the way the module already fakes it:

```python
def test_a_case_is_scored_from_the_years_trial_balance(fake_api):
    outcome = run_case(fake_api, JOBS_DIR / "ltd-bank-and-receipts", sleep=lambda s: None)
    assert fake_api.called("GET", "/api/clients/1/years/2026-04-01/trial-balance") and outcome["verdict"] == "match"
```

- [ ] **Step 2: Run it to make sure it fails.**
  - Run: `.venv/bin/python -m pytest tests/test_eval_runner.py -q`
  - Expected: FAIL.
- [ ] **Step 3:** Rewrite the runner without jobs or snapshots. Move each case's period into `client.json` as `first_year_end` (`2027-03-31` for the September and October 2026 cases). Add the three cases. Update the README:
  - the client's year and sections;
  - bank accounts;
  - opening balances and closing a year;
  - payroll reports;
  - import from a folder;
  - MongoDB only;
  - how to run the tests against a local MongoDB;
  - the routes.

  Remove the agent and SQLite paragraphs.
- [ ] **Step 4: Run the tests.**
  - Run: `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest -q && (cd frontend && npm test)`
  - Expected: all pass.
- [ ] **Step 5:** Ask the accountant before the live run: it reads 7 cases' documents with the real model and spends OpenRouter credit. With their OK, run `.venv/bin/python server.py` in one terminal and `.venv/bin/python eval/run_job_eval.py --label accounting-site` in another. Expected: every case `match`, written to `eval/results/<date>-jobs-accounting-site.json`.
- [ ] **Step 6: Commit.** `git add -A && git commit -m "test: score each client's year trial balance, with cases for late payments, payroll and transfers"`

## Order of work

- Tasks 1 to 11 are the backend and come first, in order. Each later task uses the helpers and fields of the one before it (Task 4 creates `tests/helpers.py`; Tasks 6 to 9 build on each other's models).
- Tasks 12 to 15 are the frontend, in order, after Task 10.
- Task 16 comes last.
