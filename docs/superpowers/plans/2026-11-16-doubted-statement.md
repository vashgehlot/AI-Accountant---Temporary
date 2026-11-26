# A statement that doesn't look like a bank's Implementation Plan

> **Shelved on 2026-11-16: do not build from this plan unless the user asks.** Nothing in it has been built. The note at the top of the design (`docs/superpowers/specs/2026-11-16-doubted-statement-design.md`) says why.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A statement whose lines all pay one payee and which prints no balance stops moving receipts to Suspense, and carries one warning with a one-click fix that reads its lines as receipts.

**Architecture:** One pure function judges an upload's bank lines (`statements.py`). The books work it out per upload before matching and hand matching a per-row flag, as they do `name_days`; `_off_statement` leaves flagged lines out of its days. `check_statement` puts one warning on the statement, and the rules record one suggestion (a new resolution, applied and undone by the existing machinery). The page gets a label, a tag, one summary line and "It's fine" on a document card.

**Tech Stack:** Python 3.11, pydantic, pymongo, pytest (`.venv/bin/python -m pytest`); Next.js and TypeScript, `node --test` (`npm test` in `frontend/`).

**Spec:** `docs/superpowers/specs/2026-11-16-doubted-statement-design.md`

## Global Constraints

- The issue code is `one_payee_statement`: severity `warning`, `about="document"`.
- The warning's text: `Every line pays {payee} and the statement prints no balance, so it may be {payee}'s own list of charges, not a bank statement. Until you say, it isn't used to check which receipts the bank paid.`
- The page's title for it: `May not be a bank statement`. Its tag: `Documents`. Its answer: `It's fine`.
- The resolution's action is `read_as_receipts`; its rule name is `R7 Not a bank statement`.
- Its refusals: `Nothing says this isn't a bank statement.` and `The statement's lines have changed.`
- The suggestion's one line on a card: `Its 8 lines: Bank statement line → Receipt` (the number is the statement's).
- A statement with any printed balance, lines to more than one payee, a line naming no payee, or a single line behaves exactly as today. `test_a_receipt_its_banks_statement_does_not_show_is_kept_off_the_bank` (`tests/test_matching.py`) is not edited and passes.
- A doubted statement's lines stay bank lines: still booked, still coded as read, still pairing with a receipt.
- Only a person applies the fix: `read_as_receipts` is in `Resolution`, never in `AgentResolution`.
- The working tree already holds uncommitted work that is not this plan's (`ledgersync/extractor.py`, `tests/test_extractor.py`, `tests/test_live_llm.py`, `HANDOFF.md`). `git add` only the files a task names.
- The whole Python suite takes about 55 minutes: run each task's files as its steps say, and the whole suite once, in the background, after Task 5.

## Review Focus

1. **A row left out of the books sits before the statement's lines.** Matching drops such rows and renumbers; the flags must follow their rows. Test in Task 2.
2. **A real statement and a doubted one cover the same days on one account.** The real one must still say what the bank did not pay. Test in Task 2.
3. **The statement's first stored line is out of the books.** The warning goes on the first line that counts, once. Test in Task 3.
4. **A person edited one line before pressing Apply.** The fix still applies to every line. Test in Task 4.
5. **A line was deleted after the suggestion was made.** Apply is refused and changes nothing. Test in Task 4.

---

### Task 1: The doubt, judged on one upload's rows

**Files:**
- Modify: `ledgersync/statements.py`
- Test: `tests/test_statements.py`

**Interfaces:**
- Consumes: `names_match(a, b) -> bool` from `ledgersync/matching.py` (no cycle: `matching` imports neither `statements` nor `books`).
- Produces:
  - `ONE_PAYEE = "one_payee_statement"`
  - `bank_lines(rows: list[Transaction]) -> list[int]`: the positions of the rows whose `document_type` is `statement` and which are not `excluded`, `removed` or `superseded_by`.
  - `doubted_payee(rows: list[Transaction]) -> Optional[str]`: the first line's `counterparty` when the upload is doubted, else `None`.

- [ ] **Step 1: Write the failing tests** (add `import pytest`; import `bank_lines`, `doubted_payee`)

```python
def charge(who="TfL", day=5, **kw):
    return Transaction(direction="out", gross="6.10", account_code="7400", date=dt.date(2026, 10, day),
                       description="travel", document_type="statement", counterparty=who, **kw)


def test_a_statement_all_to_one_payee_with_no_balance_is_doubted():
    assert doubted_payee([charge(day=5), charge(day=6)]) == "TfL"


@pytest.mark.parametrize("rows", [
    [charge()],                                                    # one line
    [charge(), charge("Uber", 6)],                                 # two payees
    [charge(), charge(None, 6)],                                   # a line that names no payee
    [charge(), charge(day=6, balance="93.90")],                    # a running balance
    [charge(opening_balance="100.00"), charge(day=6, opening_balance="100.00")],
    [charge(closing_balance="87.80"), charge(day=6, closing_balance="87.80")],
    [charge(accepted=["one_payee_statement"]), charge(day=6)],     # a person said it is a bank statement
])
def test_a_statement_that_looks_like_a_banks_or_was_accepted_is_not_doubted(rows):
    assert doubted_payee(rows) is None


def test_the_same_payee_in_other_words_is_one_payee():
    assert doubted_payee([charge("TfL"), charge("Transport for London", 6)]) == "TfL"


def test_rows_out_of_the_books_and_other_documents_are_not_its_lines():
    receipt = charge("Uber", 7).model_copy(update={"document_type": "receipt"})
    gone = [charge("Uber", 8, excluded=True), charge("Uber", 9, removed=True), charge("Uber", 10, superseded_by="D1")]
    assert bank_lines([receipt, charge(), *gone, charge(day=6)]) == [1, 5]
    assert doubted_payee([receipt, charge(), *gone, charge(day=6)]) == "TfL"
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_statements.py -q`
Expected: an ImportError for `bank_lines`.

- [ ] **Step 3: Add `ONE_PAYEE`, `bank_lines` and `doubted_payee` to `ledgersync/statements.py`**

Doubted when there are two or more lines, every line's `counterparty` matches the first line's by `names_match`, no line has `balance`, `opening_balance` or `closing_balance`, and no line has `ONE_PAYEE` in `accepted`.

- [ ] **Step 4: Run them and see them pass**

Run: `.venv/bin/python -m pytest tests/test_statements.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/statements.py tests/test_statements.py
git commit -m "feat: a statement all to one payee with no balance is told from a bank's"
```

---

### Task 2: Matching leaves a doubted statement's days out

**Files:**
- Modify: `ledgersync/matching.py` (`match`, `match_documents`, `_without_left_out`, `_off_statement`)
- Modify: `ledgersync/posting.py` (`matched_rows`)
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes: nothing from Task 1; it takes flags.
- Produces: a keyword `doubted: Optional[list[bool]] = None` on `match`, `match_documents` and `posting.matched_rows`, beside `name_days`. `doubted[n]` is true when row `n` is a line of a doubted statement; `None` means no row is.

- [ ] **Step 1: Write the failing tests** (after the two `_fuel` tests, near line 1356)

```python
def matched_doubting(rows, doubted):
    return match([normalise(t, SETTINGS) for t in rows], SETTINGS, doubted=doubted)


def _tfl(gross, date, ref):
    return bank(gross, date, "TFL", ref, account="7400")


def test_a_doubted_statements_lines_do_not_say_what_the_bank_did_not_pay():
    # The Currys receipt again, between two lines of a statement that is doubted: nothing shows either way.
    receipt, *lines = matched_doubting([_fuel(), _tfl("6.10", "2026-05-11", "a"), _tfl("6.20", "2026-05-22", "b")],
                                       [False, True, True])
    assert receipt.contra_account_code == "1200" and codes(receipt) == []
    assert [(t.document_type, t.contra_account_code) for t in lines] == [("statement", "1200")] * 2


def test_a_real_statement_beside_a_doubted_one_still_says_what_the_bank_did_not_pay():
    real = [bank("14.50", "2026-05-11", "NATWEST CHARGES", "a", account="7901"),
            bank("86.99", "2026-05-22", "SCREWFIX", "b", account="5000")]
    rows = [_fuel(), *real, _tfl("6.10", "2026-05-12", "c"), _tfl("6.20", "2026-05-21", "d")]
    receipt = matched_doubting(rows, [False, False, False, True, True])[0]
    assert receipt.contra_account_code == "9998" and codes(receipt) == [("not_on_statement", "warning")]


def test_doubt_changes_nothing_but_the_days_a_statement_covers():
    # A receipt for the same charge as a doubted line still pairs with it, exactly as with no doubt.
    rows = [row("receipt", "out", "6.10", "2026-05-12", "TfL", "r", account="7400"),
            _tfl("6.10", "2026-05-12", "c"), _tfl("6.20", "2026-05-21", "d")]
    assert matched_doubting(rows, [False, True, True]) == matched(*rows)


def test_doubt_follows_its_rows_when_a_row_is_left_out_of_the_books():
    gone = row("receipt", "out", "5.00", "2026-05-13", "Cafe", "x", excluded=True)
    rows = [gone, _fuel(), _tfl("6.10", "2026-05-11", "a"), _tfl("6.20", "2026-05-22", "b")]
    assert matched_doubting(rows, [False, False, True, True])[1].contra_account_code == "1200"
```

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -q -k "doubt"`
Expected: `TypeError: match() got an unexpected keyword argument 'doubted'`.

- [ ] **Step 3: Thread `doubted` through matching**

`match` and `match_documents` take it and default it to all false; `_without_left_out` filters it with the rows it keeps, as it filters `name_days`; `_off_statement(rows, changes, settings, doubted)` skips a row whose flag is true when it collects each account's days. `posting.matched_rows` takes it and passes it on. Add a sentence for it to `match_documents`'s docstring.

- [ ] **Step 4: Run matching's tests**

Run: `.venv/bin/python -m pytest tests/test_matching.py tests/test_posting.py -q`
Expected: all pass, the two `_fuel` tests among them, unedited.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/matching.py ledgersync/posting.py tests/test_matching.py
git commit -m "feat: a doubted statement's lines are not proof of what the bank did not pay"
```

---

### Task 3: The books pass the doubt on, and the statement carries one warning

**Files:**
- Modify: `ledgersync/books.py` (new `_doubted` beside `_name_days`; `_Books.post`, `_matched`, `booked_rows`)
- Modify: `ledgersync/statements.py` (`check_statement`)
- Modify: `ledgersync/checks.py` (`STATEMENT_ISSUES`, `ACCEPTABLE`)
- Modify: `ledgersync/agent/tools.py` (`FAMILIES`: `"one_payee_statement": "documents"`)
- Test: `tests/test_statements.py`, `tests/test_books.py`

**Interfaces:**
- Consumes: `ONE_PAYEE`, `bank_lines`, `doubted_payee` (Task 1); `doubted=` (Task 2).
- Produces:
  - `books._doubted(b: _Books) -> list[bool]`: for each stored row, whether it is a bank line of an upload `doubted_payee` doubts. Passed as `doubted=` in the three places `name_days=_name_days(...)` is passed.
  - `check_statement` adds the issue to the row at `bank_lines(rows)[0]` when `doubted_payee(rows)` gives a payee, with the text in Global Constraints. Its `StatementCheck` is unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/test_statements.py`:

```python
def test_a_doubted_statement_is_warned_about_once_on_its_first_line_in_the_books():
    checked, summary = check_statement([charge(day=5, excluded=True), charge(day=6), charge(day=7)])
    assert [[i.code for i in tx.issues] for tx in checked] == [[], ["one_payee_statement"], []]
    said = checked[1].issues[0]
    assert (said.severity, said.about) == ("warning", "document")
    assert said.message == ("Every line pays TfL and the statement prints no balance, so it may be TfL's own list of "
                            "charges, not a bank statement. Until you say, it isn't used to check which receipts the "
                            "bank paid.")
    assert summary.status == "none"
```

`tests/test_books.py` (fixtures `store`, `acme`; `add_rows` and `row` from `helpers`; dates in the October the tests near `_october_statement` use):

```python
def _receipt_inside_a_one_payee_statement(store, acme):
    """A £39.94 taxi receipt of 12 October, and three TfL bank lines either side of it with no balances."""
    add_rows(store, acme.id, row(document_type="receipt", direction="out", gross="39.94", date=dt.date(2026, 10, 12),
                                 counterparty="Uber", description="Uber taxi", account_code="7400"))
    return add_rows(store, acme.id, *[row(document_type="statement", direction="out", gross=gross, counterparty="TfL",
                                          date=dt.date(2026, 10, day), description="TfL travel", account_code="7400")
                                      for day, gross in ((5, "6.10"), (20, "6.60"), (27, "6.20"))], bank_account="1200")


def test_a_doubted_statement_moves_no_receipt_and_is_asked_about_once(store, acme):
    _receipt_inside_a_one_payee_statement(store, acme)
    rows = books.ledger(store, acme.id, YEAR).transactions
    receipt = next(r for r in rows if r.document_type == "receipt")
    lines = sorted((r for r in rows if r.document_type == "statement"), key=lambda r: r.id)
    assert receipt.contra_account_code == "1200"
    assert not any(i.code == "not_on_statement" for r in rows for i in r.issues)
    assert [[i.code for i in r.issues if i.severity != "info"] for r in lines] == [["one_payee_statement"], [], []]
    assert net(books.trial_balance(store, acme.id, YEAR), "9998") == 0


def test_a_statement_a_person_accepts_is_trusted_again(store, acme):
    _receipt_inside_a_one_payee_statement(store, acme)
    first = min((r for r in books.ledger(store, acme.id, YEAR).transactions if r.document_type == "statement"),
                key=lambda r: r.id)
    store.patch_row(acme.id, first.id, {"accepted": ["one_payee_statement"]})
    rows = books.ledger(store, acme.id, YEAR).transactions
    receipt = next(r for r in rows if r.document_type == "receipt")
    assert [i.code for i in receipt.issues if i.severity != "info"] == ["not_on_statement"]
    assert receipt.contra_account_code == "9998"
    assert not any(i.code == "one_payee_statement" for r in rows for i in r.issues)
```

Use the year constant and the import style `tests/test_books.py` already has, and `acme` as its other tests use it (the client, or its id).

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_statements.py tests/test_books.py -q -k "doubted or accepts"`
Expected: the statement test fails on the missing issue; the books tests fail on `not_on_statement`.

- [ ] **Step 3: Implement**

Add `"one_payee_statement"` to `STATEMENT_ISSUES` and to `ACCEPTABLE` in `checks.py`, and to `FAMILIES` as `"documents"`. Have `check_statement` add the warning. Add `books._doubted` and pass it at the three call sites.

- [ ] **Step 4: Run the files this touches**

Run: `.venv/bin/python -m pytest tests/test_statements.py tests/test_books.py tests/test_checks.py tests/test_ledger.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/books.py ledgersync/statements.py ledgersync/checks.py ledgersync/agent/tools.py tests/test_statements.py tests/test_books.py
git commit -m "feat: a statement that may not be a bank's is asked about once and moves no receipt meanwhile"
```

---

### Task 4: The rules suggest reading it as receipts, and a person applies or undoes it

**Files:**
- Modify: `ledgersync/resolutions.py` (`ReadAsReceipts`, `Resolution`, `_read_as_receipts`, `_ACTIONS`, `_RULES`, `_named`, `resolve`, `suggest_receipts`, `waiting_suggestions`)
- Modify: `ledgersync/upkeep.py` (`settle`)
- Test: `tests/test_resolutions.py`

**Interfaces:**
- Consumes: `ONE_PAYEE`, `bank_lines` (Task 1); the warning on the statement's first line (Task 3).
- Produces:
  - `class ReadAsReceipts(BaseModel)`: `action: Literal["read_as_receipts"]`, `line_row_ids: list[int]` (every line of the statement). In `Resolution`, not in `AgentResolution`.
  - `suggest_receipts(store, records, *, client_id: int, year_start: dt.date) -> list[Decision]`: one suggested decision for each row of the year that carries `one_payee_statement` and has none; none for an archived client, a closed year, a statement with a line in a closed year, or a change a person undid. Its reason is the warning's text up to and including `not a bank statement.`
  - `upkeep.settle` calls it straight after `suggest_account_changes`.

- [ ] **Step 1: Write the failing tests**

Follow the fixtures and helpers of the account-change tests at `tests/test_resolutions.py:1015-1080` (`mongo_store`, `records`, `pages`). Add a fixture `tfl` that saves the two uploads of Task 3's `_receipt_inside_a_one_payee_statement` to a new client and returns the client; `lines` below is the three bank lines' row ids in order, and `apply` and `undo` are `undo.apply_suggestion` and `undo.undo_decision` called as the neighbouring tests call them.

```python
def test_the_rules_suggest_reading_a_doubted_statement_as_receipts(mongo_store, records, tfl):
    made = suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR)
    assert [(d.status, d.action, d.rule, d.row_ids) for d in made] == [
        ("suggested", "read_as_receipts", "R7 Not a bank statement", lines)]
    assert made[0].after == {str(n): {"document_type": "receipt", "bank_account": None} for n in lines}
    assert made[0].reason == ("Every line pays TfL and the statement prints no balance, so it may be TfL's own list "
                              "of charges, not a bank statement.")
    assert [r.tx.document_type for r in mongo_store.rows(tfl.id)][1:] == ["statement"] * 3    # nothing changed
    assert suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR) == []     # and not twice


def test_applying_it_turns_every_line_into_a_receipt_and_undo_puts_them_back(mongo_store, records, pages, tfl):
    suggested, = suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR)
    applied = apply(suggested)
    assert applied.status == "applied"
    assert [(r.tx.document_type, r.tx.bank_account) for r in mongo_store.rows(tfl.id)][1:] == [("receipt", None)] * 3
    assert waiting_suggestions(mongo_store, records, client_id=tfl.id, year_start=YEAR) == []
    after = books.ledger(mongo_store, tfl.id, YEAR).transactions       # the spec's last column: nothing left to ask
    assert not any(i.severity != "info" for r in after for i in r.issues)
    assert net(books.trial_balance(mongo_store, tfl.id, YEAR), "9998") == 0
    undo(applied)
    assert [(r.tx.document_type, r.tx.bank_account) for r in mongo_store.rows(tfl.id)][1:] == [("statement", "1200")] * 3
    assert suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR) == []     # a person undid it


def test_it_stops_waiting_and_is_refused_once_a_person_says_it_is_a_bank_statement(mongo_store, records, pages, tfl):
    suggested, = suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR)
    mongo_store.patch_row(tfl.id, lines[0], {"accepted": ["one_payee_statement"]})
    assert waiting_suggestions(mongo_store, records, client_id=tfl.id, year_start=YEAR) == []
    refused = apply(suggested)
    assert (refused.status, refused.reason) == ("refused", "Nothing says this isn't a bank statement.")


def test_it_is_refused_whole_when_a_line_has_gone(mongo_store, records, pages, tfl):
    suggested, = suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR)
    mongo_store.delete_row(tfl.id, lines[2])
    refused = apply(suggested)
    assert (refused.status, refused.reason) == ("refused", "The statement's lines have changed.")
    assert [r.tx.document_type for r in mongo_store.rows(tfl.id)][1:] == ["statement"] * 2


def test_a_line_a_person_edited_does_not_stop_the_fix(mongo_store, records, pages, tfl):
    suggested, = suggest_receipts(mongo_store, records, client_id=tfl.id, year_start=YEAR)
    records.add_change(ChangeDraft(client_id=tfl.id, year_start=YEAR, actor="user", kind="row_edited",
                                   row_ids=[lines[1]], summary=f"Row {lines[1]} changed: account_code"))
    assert apply(suggested).status == "applied"


def test_the_agent_is_not_offered_it():
    asked = {"action": "read_as_receipts", "line_row_ids": [1, 2]}
    assert TypeAdapter(Resolution).validate_python(asked).action == "read_as_receipts"
    with pytest.raises(ValidationError):
        TypeAdapter(AgentResolution).validate_python(asked)


def test_asked_by_anyone_but_a_person_it_is_only_suggested(mongo_store, records, pages, tfl):
    made = resolve(mongo_store, records, client_id=tfl.id, thread_id=None, actor="rules", row_id=lines[0],
                   resolution=ReadAsReceipts(action="read_as_receipts", line_row_ids=lines), evidence=[],
                   reason="why", texts=pages)
    assert made.status == "suggested"
    assert [r.tx.document_type for r in mongo_store.rows(tfl.id)][1:] == ["statement"] * 3
```

If `records.person_rows` is fed some other way than a user's change, feed it that way in
`test_a_line_a_person_edited_does_not_stop_the_fix`; pass `texts` as the neighbouring tests pass it.

Add one more beside `test_a_closed_year_gets_no_suggestion`, made the way that test closes its year: `test_a_statement_with_a_line_in_a_closed_year_gets_no_suggestion`, asserting `suggest_receipts(...) == []`.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest tests/test_resolutions.py -q -k "receipt or bank_statement or line_has_gone or person_edited or not_offered or line_in_a_closed"`
Expected: an ImportError for `suggest_receipts`.

- [ ] **Step 3: Implement**

- `_named`: `"read_as_receipts": lambda r: r.line_row_ids`.
- `_read_as_receipts(rows, row_id, r, **_) -> _Change`: refuse with the first message when `rows[row_id]` has no `one_payee_statement` issue; refuse with the second when `sorted(r.line_row_ids)` is not the ids of that row's upload's rows at `bank_lines`; else `_Change(rule=_RULES["read_as_receipts"], touched=<those ids>, patches={id: {"document_type": "receipt", "bank_account": None}})`.
- `resolve` treats `change_account` apart in three places (the background review's refusal of a person's rows, `No evidence was cited.`, and suggesting unless the actor is `user`). Make each test membership of `_A_PERSON_APPLIES = {"change_account", "read_as_receipts"}`.
- `waiting_suggestions`: a `read_as_receipts` suggestion is listed only while its first row is in the books and carries `one_payee_statement`.
- `suggest_receipts` follows `suggest_account_changes` line for line, with the conditions in Interfaces.

- [ ] **Step 4: Run the files this touches**

Run: `.venv/bin/python -m pytest tests/test_resolutions.py tests/test_undo.py tests/test_upkeep.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ledgersync/resolutions.py ledgersync/upkeep.py tests/test_resolutions.py
git commit -m "feat: the rules suggest reading a doubted statement's lines as receipts, for a person to apply"
```

---

### Task 5: The page

**Files:**
- Modify: `frontend/src/lib/ledger.ts` (`ISSUE_TITLES`, `ACCEPTABLE`)
- Modify: `frontend/src/lib/todo.ts` (the document card's tag)
- Modify: `frontend/src/lib/suggestions.ts` (`changeLines`)
- Modify: `frontend/src/components/TodoList.tsx` (the document card's `IssueList`)
- Test: `frontend/src/lib/ledger.test.ts`, `frontend/src/lib/todo.test.ts`, `frontend/src/lib/suggestions.test.ts`

**Interfaces:**
- Consumes: the issue (Task 3) and the suggested decision, whose `before` and `after` hold `document_type` and `bank_account` for each line (Task 4).
- Produces: nothing later tasks use.

- [ ] **Step 1: Write the failing tests**

`suggestions.test.ts`:

```ts
test('reading a statement as receipts is one line, however many lines it has', () => {
  const rows = [287, 288, 289, 290, 291, 292, 293, 294]
  const d = suggestion('D1', 'read_as_receipts',
    Object.fromEntries(rows.map(r => [r, { document_type: 'statement', bank_account: '1200' }])),
    Object.fromEntries(rows.map(r => [r, { document_type: 'receipt', bank_account: null }])))
  assert.deepEqual(changeLines(d), { lines: ['Its 8 lines: Bank statement line → Receipt'], more: 0 })
})
```

`ledger.test.ts`: `canBeAccepted('one_payee_statement')` is true, and the title the page gives the code is `'May not be a bank statement'` (asserted through whichever exported function the file's other title tests use).

`todo.test.ts`, with that file's own row and suggestion builders: three statement rows 1, 2, 3, row 1 carrying `{ code: 'one_payee_statement', severity: 'warning', about: 'document', message: 'm' }`, and one suggestion with `row_ids: [1, 2, 3]`, give exactly one card, with `kind: 'document'`, `tag: 'Documents'`, the file name as its title, one issue and one suggestion.

- [ ] **Step 2: Run them and see them fail**

Run: `cd frontend && npm test`
Expected: the three new tests fail; the rest pass.

- [ ] **Step 3: Implement**

- `ISSUE_TITLES`: `one_payee_statement: 'May not be a bank statement'`; the code joins `ACCEPTABLE`.
- `todo.ts`: a document card's tag is `'Documents'` for this code and `'Document total'` for any other.
- `changeLines`: for `d.action === 'read_as_receipts'`, one line, `Its ${rows} lines: Bank statement line → Receipt`, where `rows` is the number of rows in `d.after`, and `more: 0`.
- `TodoList.tsx`: the document card's `IssueList` gets the same `onAccept` the row card's has.

- [ ] **Step 4: Run the page's checks**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: all tests pass and no type errors.

- [ ] **Step 5: See it in the preview app**

In the preview pair `HANDOFF.md` names, on a seeded client shaped like the spec's section 6 (never on client 3's saved year): the AI review page shows one card for the statement with Apply and "It's fine"; Apply leaves no card and the Bank page says "No statement this year."; Undo brings the card back with no suggestion; "It's fine" brings the receipts' own warnings back.

- [ ] **Step 6: Commit, then run the whole suite once**

```bash
git add frontend/src/lib/ledger.ts frontend/src/lib/todo.ts frontend/src/lib/suggestions.ts frontend/src/components/TodoList.tsx frontend/src/lib/ledger.test.ts frontend/src/lib/todo.test.ts frontend/src/lib/suggestions.test.ts
git commit -m "feat: a statement that may not be a bank's is one card, with Apply and It's fine"
```

Run, in the background: `.venv/bin/python -m pytest -q`
Expected: all pass (1,759 passed on 2026-11-15, plus this plan's and the reader fix's tests).
