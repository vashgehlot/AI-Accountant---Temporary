# Bank and Payment Exports Read in Code: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read any bank's, card's or payment processor's CSV or spreadsheet export in code, and ask the model only
for each bank line's account and payee.

**Architecture:** A new `ledgersync/tables.py` finds the heading row and column roles, reads dates and amounts
exactly, settles each line's direction (by columns, the account's kind and the balance chain) and builds processor
exports' rows outright. A new `TransactionExtractor.code_statement` asks the model, 50 lines a request at low
thinking, for account, payee and alternatives only. `pipeline.analyze` tries this path for table intakes and falls
back to today's full read when the table isn't recognised. The output is today's `TransactionExtractionResult`.

**Tech Stack:** Python 3.11, `csv`, `decimal`, pydantic models already in `ledgersync/extractor.py`; pytest.

**Spec:** `docs/superpowers/specs/2026-11-23-csv-statements-in-code-design.md`

## Global Constraints

- No new dependencies.
- `TransactionExtractionResult` and `ledgersync/adapter.py` do not change.
- A file that can't be read with certainty returns None from `tables` and goes to the model as today; never a guess.
- Every payment row of a recognised file becomes exactly one row (processor lines: one row, plus one fee row when
  the fee isn't nil); none dropped or added.
- Coding requests: at most 50 lines each, `reasoning_effort` "low".
- Processor charges: "in" on 4000; refunds "out" on 4000; fees "out" on 7901; payouts not rows; other categories on
  9998 with a warning. Agents named: Stripe, PayPal, Square, SumUp, Zettle, Shopify, GoCardless, else
  "Payment processor".
- Tests: `.venv/bin/python -m pytest <the task's files> -q` from the main checkout, with
  `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017` for Mongo tests. Never the full `tests/` suite (about 55
  minutes). Not with `-W error`: pymupdf crashes Python on import under it.
- Commits: one per task, each only after the user's yes, message ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Spending: Task 6's live check needs the user's yes first.

## Review Focus

1. A heading block above the header row and a totals row below the lines (no date, "Total" with amounts): the
   heading is kept as text, the totals row is not a transaction. Test in Task 1.
2. A newest-first export: the balance chain holds in reverse, opening and closing balances come out right. Test in
   Task 2.
3. Amounts written "£1,234.56", "(12.00)", "12.00 CR", "12.00 DR": read exactly, sign as written. Test in Task 1.
4. A US month-first date column (04/13/2023) or a column mixing formats: not recognised, so the model reads it.
   Test in Task 1.
5. The model's coding answer leaves a line out or numbers one it wasn't sent: that line is on 9998 with a warning,
   nothing dropped or doubled. Test in Task 4.

---

### Task 1: Recognising a table

**Files:**
- Create: `ledgersync/tables.py`
- Test: `tests/test_tables.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Table: heading: list[str]; header: list[str]; roles: dict[str, list[int]];
    rows: list[list[str]]` (roles: "date", "description" (several allowed, in file order), "amount", "paid_in",
    "paid_out", "balance", "type", "currency", "gross", "fee", "net", "category", "id")
  - `parse(text: str) -> Optional[Table]`: cells split by tab when the text has tabs, else by `csv` with commas.
  - `parse_date(column: list[str]) -> Optional[list[dt.date]]`: one format for the whole column, or None.
  - `parse_amount(cell: str) -> Optional[Decimal]`: signed; None for a blank cell and for anything not an amount;
    never raises. A non-blank amount cell that gives None makes `parse` return None.

- [ ] **Step 1: Write the failing tests** in `tests/test_tables.py`:
  - `test_the_test_books_hsbc_export`: text `"Date,Type,Description,Amount,Balance\n28 Apr 2023,BP,LEAH MORGAN
    SALARY,-3149.87,8263.46\n"` → `roles == {"date": [0], "type": [1], "description": [2], "amount": [3],
    "balance": [4]}`, one row.
  - `test_a_heading_block_and_a_totals_row`: three lines ("Account: Business current", "Sort code 40-11-22",
    "") then `Date,Details,Paid out,Paid in,Balance`, two lines, then `,Total,120.00,500.00,` →
    `heading == ["Account: Business current", "Sort code 40-11-22"]`, `len(rows) == 2`.
  - `test_amounts_as_banks_write_them`: `parse_amount` of "£1,234.56", "(12.00)", "12.00 CR", "12.00 DR", "-5",
    "abc" → `1234.56, -12.00, 12.00, -12.00, -5, None`.
  - `test_dates_are_read_day_first_with_one_format_a_column`: `["09/04/2023", "11/04/2023"]` → 9 and 11 April;
    `["2023-04-04 12:00:00"]` → 4 April; `["28 Apr 2023"]` and `["3 April 2023"]` read; `["04/13/2023"]` → None;
    `["09/04/2023", "2023-04-11"]` → None.
  - `test_a_table_without_dates_or_amounts_is_not_recognised`: `"Name,Notes\nA,B\n"` → None; a row whose date
    cell isn't a date → None.
  - `test_the_amex_and_stripe_headings`: the Amex header (`Date,Description,Amount,Extended Details,Appears On Your
    Statement As,Address,Town/City,Postcode,Country,Reference,Category`) gives `description == [1, 9]` (Description,
    Reference) and `amount == [2]`; the Stripe header gives date `[3]` (created_utc), gross `[5]`, fee `[6]`,
    net `[7]`, category `[8]` (reporting_category), description `[9]` and id `[2]` (balance_transaction_id).

- [ ] **Step 2: Run them to see them fail**
  Run: `.venv/bin/python -m pytest tests/test_tables.py -q` — Expected: FAIL, `ledgersync.tables` not found.

- [ ] **Step 3: Implement `parse`, `parse_date`, `parse_amount` in `ledgersync/tables.py`**
  Headings are matched after lowercasing and dropping punctuation, by the spec's synonym lists (section 1), first
  match wins; the header row is the first of the first 15 that has a date role and an amount role or both paid
  in/out (or gross/fee/net). A data row with a blank date cell is not a transaction when its text has "total" or
  "balance", else `parse` returns None. A blank row is skipped.

- [ ] **Step 4: Run the tests to see them pass** — same command, Expected: PASS.

- [ ] **Step 5: Commit** (after the user's yes): `feat: tables recognises a bank export by its column headings`.

### Task 2: Direction and balances

**Files:**
- Modify: `ledgersync/tables.py`
- Test: `tests/test_tables.py`

**Interfaces:**
- Consumes: `Table`, `parse_date`, `parse_amount` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Line: date: dt.date; text: str; amount: Decimal (positive);
    direction: Literal["in", "out"]; balance: Optional[Decimal]; currency: str; kind: Optional[str] (the type
    column)`
  - `@dataclass(frozen=True) class Statement: lines: list[Line]; opening_balance: Optional[Decimal];
    closing_balance: Optional[Decimal]; heading: str`
  - `statement(table: Table, account_kind: Optional[str]) -> Optional[Statement]`, account_kind one of
    `models.BankAccountKind` or None.
  - `account_kind(code: Optional[str]) -> Optional[str]`: the kind whose `accounts.BANK_SLOTS` holds the code.

- [ ] **Step 1: Write the failing tests**
  - `test_paid_in_and_paid_out_columns_say_the_direction`.
  - `test_one_amount_column_is_money_in_when_positive_on_a_bank_account`.
  - `test_a_card_export_takes_positive_as_spending` (Amex rows 10.99 and -250.00 on "credit_card" → out 10.99,
    in 250.00).
  - `test_the_balance_chain_settles_the_sign_when_the_account_is_unknown` (account_kind None, balance column) and
    `test_without_a_balance_an_unknown_account_is_not_recognised` (→ None).
  - `test_a_newest_first_export_has_its_balances_the_right_way_round`: lines dated 28, 21, 14 Apr with balances
    1000, 1200, 1500 and amounts -200, -300, +100 → opening 1400, closing 1000, lines in file order.
  - `test_a_chain_that_holds_neither_way_is_not_recognised`.
  - `test_a_line_in_another_currency_keeps_it` (currency column "USD").

- [ ] **Step 2: Run them to see them fail** — `.venv/bin/python -m pytest tests/test_tables.py -q`, Expected: FAIL.

- [ ] **Step 3: Implement `statement` and `account_kind`**
  Sign rule as the spec's section 2; the chain is checked in file order and in reverse, exact to the penny; flip all
  signs only when the chain fails as read and holds flipped. Opening and closing balances as the spec's section 3.

- [ ] **Step 4: Run the tests to see them pass**, Expected: PASS.

- [ ] **Step 5: Commit** (after the user's yes): `feat: tables settles each line's direction and the balances`.

### Task 3: Payment processor exports, in code

**Files:**
- Modify: `ledgersync/tables.py`
- Test: `tests/test_tables.py`

**Interfaces:**
- Consumes: `Table`, `parse_date`, `parse_amount` (Task 1).
- Produces: `processor(table: Table, file_name: str) -> Optional[TransactionExtractionResult]` (None when the table
  has no gross, fee and net roles), imported from `ledgersync.extractor`.

- [ ] **Step 1: Write the failing tests**
  - `test_stripes_export_books_each_charge_and_fee_on_its_own_day`: the April 2023 test-books Stripe export (the
    seven lines in `testbooks/out/clients/agency/inbox/2023-05-09/2023-04-01_stripe-statement_2023-04-30.csv`,
    copied into the test as text) → 8 rows: four "in" on 4000 (720.00, 1080.00, 540.00, 900.00) dated 4, 5, 6,
    7 April, four "out" on 7901 (11.00, 16.40, 8.30, 13.70); every row `document_type == "agent_statement"`;
    each charge and its fee share `document_number` (the txn id) and `document_total` (the net: 709.00, ...);
    `agent == "Stripe"`; no row for the two payouts.
  - `test_the_january_export_keeps_each_charge_on_its_own_day`: the January 2024 export (charges on 5, 5, 7, 10
    January; payouts 9 and 16 January) → charges dated 5, 5, 7, 10 January, never 9 or 16.
  - `test_a_refund_and_an_unknown_category`: a refund line → "out" on 4000; "adjustment" → 9998 and a warning.
  - `test_the_processor_is_named_from_the_file_or_the_heading_else_generically`.

- [ ] **Step 2: Run them to see them fail**, Expected: FAIL.

- [ ] **Step 3: Implement `processor`** as the spec's section 5; descriptions from the description columns, the
  fee row's description `"<agent> fee: <line text>"`; `counterparty` the customer name column when present, else
  the agent.

- [ ] **Step 4: Run the tests to see them pass**, Expected: PASS.

- [ ] **Step 5: Commit** (after the user's yes): `feat: a payment processor's export is booked in code`.

### Task 4: The model codes the lines

**Files:**
- Modify: `ledgersync/model_client.py` (`chat_json`), `ledgersync/extractor.py`
- Test: `tests/test_extractor.py`, `tests/test_model_client.py`

**Interfaces:**
- Consumes: `Statement`, `Line` (Task 2).
- Produces:
  - `ModelClient.chat_json(messages, schema, images=None, reasoning_effort: Optional[str] = None)`: the
    argument, when given, replaces the setting for that call.
  - `TransactionExtractor.code_statement(statement: Statement, account_kind: Optional[str]) ->
    TransactionExtractionResult`: rows with date, amount, direction, balance and currency from the statement;
    account, counterparty, alternatives, bought and people from the model; `document_type` "statement";
    opening/closing balances from the statement.
  - `CODING_BATCH = 50`.

- [ ] **Step 1: Write the failing tests** (with the existing `FakeModel` from `tests/fakes.py`):
  - `test_chat_json_can_ask_for_less_thinking` in `tests/test_model_client.py`: payload's `reasoning_effort` is
    "low" when passed, the setting otherwise.
  - `test_coding_a_statement_asks_only_for_accounts_and_keeps_the_figures`: a 3-line statement, the fake answers
    `{"lines": [{"n": 1, "account": "2220", "counterparty": "Leah Morgan", ...}, ...]}` → rows keep the
    statement's dates, amounts and directions even if the fake's answer carries others; the request's user message
    lists `1 | 2023-04-28 | out | 3149.87 | BP LEAH MORGAN SALARY`; the call used `reasoning_effort="low"`.
  - `test_a_long_statement_is_coded_fifty_lines_a_request` (120 lines → 3 calls of 50, 50, 20).
  - `test_a_line_the_answer_leaves_out_goes_to_suspense` (Review Focus 5): answer missing n=2 and adding n=9 →
    3 rows, row 2 on 9998, one warning naming line 2, nothing for 9.

- [ ] **Step 2: Run them to see them fail**:
  `.venv/bin/python -m pytest tests/test_extractor.py tests/test_model_client.py -q`, Expected: FAIL.

- [ ] **Step 3: Implement** `chat_json`'s argument, and `code_statement`: its instructions are the reader's own
  (`_instructions()`) with a short preface that the figures are given and only the coding is asked; the answer
  schema is a new pydantic model `CodedLines` (`lines: list[CodedLine]`, `CodedLine`: `n: int`, `account` (the
  chart enum, as `AccountingTransaction.account`), `counterparty: Optional[str]`, `alternatives: list[str]`,
  `bought`, `people` as on `AccountingTransaction`).

- [ ] **Step 4: Run the tests to see them pass**, Expected: PASS.

- [ ] **Step 5: Commit** (after the user's yes): `feat: a statement read in code is coded by the model, fifty lines a request`.

### Task 5: Reading a table takes the new path

**Files:**
- Modify: `ledgersync/pipeline.py` (`analyze`), `server.py` (`run_analysis`, the `pipeline.analyze` call)
- Test: `tests/test_pipeline.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `tables.parse`, `tables.statement`, `tables.processor`, `tables.account_kind`,
  `TransactionExtractor.code_statement`.
- Produces: `analyze(intake: Intake, extractor, ctx: JobContext, name: str = "", account: Optional[str] = None)`.

- [ ] **Step 1: Write the failing tests**
  - `test_a_recognised_csv_is_read_in_code_and_coded` in `tests/test_pipeline.py`: the HSBC text → the fake model
    gets one coding request, never the full reader's; the result warns `"Read in code: 2 lines"`.
  - `test_a_processor_export_needs_no_model`: the Stripe text → no request at all.
  - `test_an_unrecognised_table_is_read_as_today`: a table without dates → the full reader's request, warning
    `"Columns not recognised: read by the model"`.
  - `test_a_statement_upload_passes_its_account_to_the_reader` in `tests/test_api.py`: an Amex-style upload for a
    card account books 10.99 as money out.

- [ ] **Step 2: Run them to see them fail**:
  `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest tests/test_pipeline.py tests/test_api.py -q`,
  Expected: FAIL.

- [ ] **Step 3: Implement** the branch in `analyze` for `intake.kind == "table"`, and pass `name` and `own` from
  `run_analysis`.

- [ ] **Step 4: Run the tests to see them pass**, then the neighbours:
  `LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest tests/test_tables.py tests/test_pipeline.py tests/test_api.py tests/test_extractor.py tests/test_model_client.py tests/test_adapter.py tests/test_jobs.py tests/test_documents.py -q`,
  Expected: all pass.

- [ ] **Step 5: Commit** (after the user's yes): `feat: bank and payment exports are read in code`.

### Task 6: Check on the test books (needs the user's yes to spend)

- [ ] **Step 1:** Show the user the cost: the agency year's 42 statement files through the coding step (about 600
  lines, 13 or so requests at low thinking), from `testbooks_runner plan`; wait for a clear yes.
- [ ] **Step 2:** Run the agency year with the runner from its worktree, label `agency-csv`, `--yes`, its app
  directory set to the main checkout (the runner's README gives the exact flags), and compare with `runs/2026-11-23-agency-first`: statement read time, cost, blocking errors (expect none
  from Stripe), entries right.
- [ ] **Step 3:** Report to the user, and update `HANDOFF.md` in the runner's worktree.
