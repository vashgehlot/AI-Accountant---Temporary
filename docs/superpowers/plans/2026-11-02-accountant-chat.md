# Accountant Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A chat, one client per thread, where the agent reviews a client's documents like an accountant. It sorts what the evidence supports, asks the user for what it can't (dates, receipts, invoices), posts to an append-only ledger, and shows one summary with the posted trial balance.

**Architecture:**
- **Deterministic services do all the accounting:**
  - the document rules (the £50 and £250 limits, Suspense, VAT reclaim);
  - resolutions R0–R5, each with a decision record;
  - working out the questions;
  - posting with reversals.
- **The LangChain `create_agent` loop only investigates and picks actions.** It cannot set a date (no tool for it), cannot post (the server posts at the end of every turn), and cannot write the summary cards (the server builds them from the records).
- **Answers to questions are applied deterministically**, without a model call. They are then noted in the thread's memory.

**Tech Stack:**
- Python 3.11, FastAPI, pymongo (Decimal128), pytest.
- `langchain==1.4.6`, `langgraph==1.2.16`, `langgraph-checkpoint-mongodb==0.5.1`, plus `langchain-openrouter==0.2.9`.
- Next.js 16 and React 18, no UI libraries, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-02-accountant-chat-design.md`. Technical reference: `docs/2026-11-02-ai-accountant-demo-plan.md`. Where the two differ, the spec wins.

## Global Constraints

- **Money:**
  - `Decimal` in Python, exact decimal strings in `clients.rows`.
  - `Decimal128(str(d))` in the new `ledger_entries` and `posting_batches`, converted back to `Decimal` on read.
  - Strings in JSON (`"12.50"`).
- **The document rules** apply only to an **outgoing** row coded to an **expense or asset** account that is not one of the client's bank codes. Liability and equity accounts, transfers and money in are exempt.
- **Under £50** (`gross < Decimal("50.00")`): no document is needed. **£50.00 to £250.00**: a receipt or an invoice. **Over £250.00**: a full VAT invoice.
- **VAT is reclaimed:**
  - on an invoice that shows VAT, unless it says it is not a VAT invoice;
  - on a receipt only when it shows VAT **and** the supplier's VAT number, and its gross is ≤ £250.00;
  - otherwise the whole gross goes to the cost, with no VAT leg.
- **Held items** are posted as a debit to `9998` Suspense (`accounts.SUSPENSE`) against the row's contra, with no VAT leg, and get a "Documentation required" question.
- **No date is ever taken from a file name.** The agent has no tool that sets a date. Dates come only from a matching bank line (matching does this already) or from the user's answer.
- **Client and thread** IDs come from the server (`ToolRuntime.context`), never from model arguments.
- **Append-only:**
  - `decisions`, `ledger_entries` and `posting_batches` are never updated or deleted, except by the demo reset;
  - a correction is a reversal.
- **Rows' trial balance unchanged.** The existing `books.trial_balance`, year close and Trial balance section keep working from the rows, unchanged. The chat shows the posted ledger.
- **Writes** need the `X-LedgerSync: 1` header, as the existing routes do.
- **Model:**
  - `LEDGERSYNC_AGENT_MODEL` (default `openai/gpt-oss-120b`) through OpenRouter, with `openrouter_provider={"require_parameters": True, "data_collection": "deny"}`.
  - Images are transcribed by the existing Qwen vision model (`model_client`).
- **Real-model tests** are marked `llm` and need `OPENROUTER_API_KEY`. **Ask the user before running any of them**, because they spend credit.
- **Out of scope:** login, a chat side panel on other pages, emailing clients, and a sign-off step before posting.
- **Copy:**
  - plain sentences;
  - "Documentation required" and "Needs you" exactly as written;
  - £ amounts with two decimals;
  - dates as `14 Oct 2026` (`checks.long_date`).
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **MongoDB connections stay within Atlas M0** (500 connections across the cluster). One `MongoClient` per process (`MongoStore.client`). Every new collection, the LangGraph `MongoDBSaver` and the agent records reuse it, and never construct their own `MongoClient`. The tests share one session-wide client. Task 0 sets this up.
- **Running the tests:** `.venv/bin/python -m pytest`. MongoDB tests need network access to the test cluster.

## Review Focus

1. **The same answer sent twice** (a double click, or a retry after a timeout) records one decision and posts once. Test in Task 7: `test_answer_twice_is_one_decision`.
2. **A server restart between the agent asking and the user answering** keeps the questions, and the answer still applies. Test in Task 10: `test_questions_survive_restart`.
3. **An uploaded invoice that doesn't fit the held payment** (a different amount or payee) leaves the item open and says why. Test in Task 7: `test_invoice_that_does_not_fit_stays_open`.
4. **A person edits a row in Transactions after posting.** The Overview shows the change as not posted, and the next post reverses it and re-posts it once. Test in Task 6: `test_edit_after_post_reverses_once`.
5. **The model cites a quote that isn't in the document, or targets a row of another client or a closed year.** The service refuses, records `refused`, and the chat carries on. Test in Task 4: `test_quote_not_in_document_refused` and `test_closed_year_refused`.

---

### Task 0: Keep MongoDB connections within M0

**Files:**
- Modify: `ledgersync/store_mongo.py` (`MongoStore.__init__`, `close`), `ledgersync/config.py` and `.env.example` (`LEDGERSYNC_MONGO_MAX_POOL`, default 10), `server.py` (close the store on shutdown, if it doesn't already), `tests/conftest.py`
- Test: `tests/test_store_mongo.py`

**Interfaces:**
- Produces `MongoStore(uri=..., db_name=..., *, client: Optional[MongoClient] = None, max_pool: int = 10)`:
  - Given a `client`, it uses that client and never closes it. Otherwise it creates one with `maxPoolSize=max_pool`, `minPoolSize=0` and `maxIdleTimeMS=60000`, plus the existing timeouts.
  - `close()` closes only a client it created.
- Produces in `tests/conftest.py`:
  - one session-scoped `mongo_client` fixture: `MongoClient(uri, maxPoolSize=5, minPoolSize=0)`, closed at the end of the session;
  - `mongo_db` and `mongo_store` use it (`MongoStore(..., client=mongo_client)`).
  - A test that needs a second store "after a restart" builds it with the same shared client.

- [ ] **Step 1: Write the failing tests**

```python
def test_store_uses_given_client_and_does_not_close_it(mongo_client, mongo_db):
    store = MongoStore("unused", mongo_db.name, client=mongo_client); store.close()
    assert store.client is mongo_client and mongo_client.admin.command("ping")["ok"] == 1
def test_store_default_pool_is_small():
    store = MongoStore("mongodb://localhost:1", "x", max_pool=7)   # never connects: no server selection on init?
    assert store.client.options.pool_options.max_pool_size == 7 and store.client.options.pool_options.min_pool_size == 0
```

  If `__init__` creates indexes (which connects), the second test passes `client=` a `MongoClient("mongodb://localhost:1", maxPoolSize=7, minPoolSize=0, connect=False)` built by the same helper the store uses (`_new_client(uri, max_pool)`), and asserts on that helper instead.
- [ ] **Step 2: Run the tests.** Run `.venv/bin/python -m pytest tests/test_store_mongo.py -k "client or pool" -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Grep the tests for any other `MongoClient(` or `MongoStore(` that builds its own client, and switch it to the shared one.
- [ ] **Step 4: Run the tests.** Run `.venv/bin/python -m pytest -q`, including the MongoDB tests. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `fix: share one small MongoDB pool so tests and the app stay within Atlas M0's connection limit`.

### Task 1: Row fields, the supplier's VAT number, and the feature branch

**Files:**
- Modify: `ledgersync/models.py` (`Transaction`), `ledgersync/checks.py:50-58` (`booked`), `ledgersync/extractor.py` (`AccountingTransaction`, prompt), `ledgersync/adapter.py`
- Test: `tests/test_checks.py`, `tests/test_adapter.py`, `tests/test_extractor.py`

**Interfaces:**
- Produces these `Transaction` fields:
  - `excluded: bool = False`, an input set only by decisions;
  - `superseded_by: Optional[str] = None`, a decision id;
  - `decision_ids: list[str] = []`;
  - `supplier_vat_number: Optional[str] = None`.
- Produces `checks.booked(tx)`, which returns False when `tx.excluded or tx.superseded_by`, before every other rule.

- [ ] **Step 1: Create the branch.** Run `git switch -c ai-accountant-demo` from `accounting-site`.
- [ ] **Step 2: Write the failing tests**

```python
def test_excluded_row_is_not_booked():
    assert booked(tx(excluded=True, include=True)) is False

def test_superseded_row_is_not_booked():
    assert booked(tx(superseded_by="d1")) is False

def test_adapter_keeps_supplier_vat_number():   # tests/test_adapter.py
    rows = to_transactions(model_rows(supplier_vat_number="GB 123 4567 89"), ...)
    assert rows[0].supplier_vat_number == "GB123456789"   # spaces removed, upper case

def test_schema_asks_for_supplier_vat_number():  # tests/test_extractor.py
    assert "supplier_vat_number" in AccountingTransaction.model_json_schema()["properties"]
```

- [ ] **Step 3: Run the tests.** Run `pytest tests/test_checks.py tests/test_adapter.py tests/test_extractor.py -k "excluded or superseded or vat_number" -v`. Expected: FAIL.
- [ ] **Step 4: Implement the fields and the schema field.**
  - In `AccountingTransaction`, add `supplier_vat_number: Optional[str] = Field(None, description="The supplier's VAT registration number printed on the receipt or invoice, the same on every transaction from that document; null when none is printed")`.
  - `adapter.to_transactions` copies it, with whitespace removed and in upper case.
  - Add `"excluded", "superseded_by", "decision_ids"` to neither `EDITABLE` nor `RowPatch`.
- [ ] **Step 5: Run the tests.** Run `pytest -q`. Expected: all pass, including the existing ones.
- [ ] **Step 6: Commit.** Message: `feat: rows can be excluded or superseded by a decision; read the supplier's VAT number`.

### Task 2: Document rules

**Files:**
- Create: `ledgersync/evidence_rules.py`
- Test: `tests/test_evidence_rules.py`

**Interfaces:**
- Consumes `Transaction` from Task 1, `posting.journal_for`, and `accounts.BY_CODE`, `SUSPENSE` and `ALL_BANK_CODES`.
- Produces:

```python
NO_DOCUMENT_LIMIT = Decimal("50.00"); SIMPLIFIED_LIMIT = Decimal("250.00")
class DocumentRule(BaseModel):
    action: Literal["book", "hold"]
    reclaim_vat: bool
    needs: Optional[Literal["receipt_or_invoice", "vat_invoice"]] = None
    reason: str          # one plain sentence, shown on the question card and the decision
def document_rule(tx: Transaction, settings: BusinessSettings) -> DocumentRule
def journal_with_rule(tx: Transaction, index: int, rule: DocumentRule) -> list[JournalLine]
```

`document_rule` takes a row **after** `normalise` and `match`:
- A row is **covered** when `direction == OUT`, its account type is EXPENSE or ASSET, `account_code not in ALL_BANK_CODES`, and `paid_against is None`. A row that is not covered → `book`, with `reclaim_vat=True` (normalise has already decided its VAT).
- A covered `statement` or `expense_claim` row (a bank line or a sheet line with no document behind it) → `book` with no VAT when `gross < 50.00`. Otherwise → `hold`, needs `receipt_or_invoice`.
- A covered `receipt` with `gross > 250.00` → `hold`, needs `vat_invoice`. Otherwise → `book`, with `reclaim_vat = vat_posted > 0 and supplier_vat_number is not None and not not_vat_invoice`.
- A covered `invoice` → `book`, with `reclaim_vat = not not_vat_invoice`.

`journal_with_rule` works like this:
- `book` with reclaim → `journal_for` unchanged.
- `book` without reclaim → the account leg is the whole gross, with no VAT leg.
- `hold` → debit `SUSPENSE` with the gross and credit the contra.
- Debits must equal credits, asserted as `journal_for` does.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("kind,gross,vat_no,expected", [
    ("statement", "49.99", None, ("book", False, None)),
    ("statement", "50.00", None, ("hold", False, "receipt_or_invoice")),
    ("expense_claim", "84.20", None, ("hold", False, "receipt_or_invoice")),
    ("receipt", "120.00", "GB123456789", ("book", True, None)),
    ("receipt", "120.00", None, ("book", False, None)),
    ("receipt", "250.00", "GB123456789", ("book", True, None)),
    ("receipt", "250.01", "GB123456789", ("hold", False, "vat_invoice")),
    ("invoice", "300.00", None, ("book", True, None)),
])
def test_document_rule(kind, gross, vat_no, expected): ...

@pytest.mark.parametrize("account", ["2210", "2202", "2250", "2300", "1240"])   # PAYE, VAT, DLA, loan, card pay-off
def test_exempt_accounts_need_no_document(account):
    assert document_rule(statement_line("500.00", account), SETTINGS).action == "book"

def test_money_in_needs_no_document():
    assert document_rule(statement_line("500.00", "4000", direction="in"), SETTINGS).action == "book"

def test_held_row_posts_gross_to_suspense():
    lines = journal_with_rule(statement_line("240.00", "7500"), 0, DocumentRule(action="hold", reclaim_vat=False,
                                                                                    needs="receipt_or_invoice", reason="x"))
    assert [(l.code, l.debit, l.credit) for l in lines] == [("9998", D("240.00"), 0), ("1200", 0, D("240.00"))]

def test_no_reclaim_puts_vat_in_cost():
    lines = journal_with_rule(receipt("60.00", vat="10.00", vat_no=None), 0, document_rule(...))
    assert {l.code for l in lines} == {"7400", "1200"} and sum(l.debit for l in lines) == D("60.00")
```

- [ ] **Step 2: Run the tests.** Run `pytest tests/test_evidence_rules.py -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement `evidence_rules.py`** with the signatures and rules above.
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_evidence_rules.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: document rules for the £50 and £250 limits, Suspense and VAT reclaim`.

### Task 3: Agent records — decisions, questions, threads, document texts

**Files:**
- Create: `ledgersync/records.py`
- Modify: `ledgersync/models.py` (add the models below), `ledgersync/store_mongo.py` (`_init_indexes` for the new collections; `add_split`)
- Test: `tests/test_records.py` (marker `mongo`)

**Interfaces:**
- Produces these models in `models.py`:

```python
class Evidence(BaseModel): upload_id: int; upload_name: str = ""; quote: str
class Decision(BaseModel):
    id: str; client_id: int; thread_id: Optional[str]; year_start: dt.date
    action: str; rule: str                       # e.g. "R2 Duplicate: kept the receipt"
    status: Literal["applied", "refused"]
    row_ids: list[int]; evidence: list[Evidence]; reason: str
    before: dict[str, dict]; after: dict[str, dict]   # keyed by str(row_id)
    actor: str                                   # "agent:<model>", "user", "rules"
    created_at: str; reverses: Optional[str] = None; prev_hash: str; hash: str
class Question(BaseModel):
    id: str; client_id: int; year_start: dt.date; row_ids: list[int]
    kind: Literal["date", "receipt_or_invoice", "vat_invoice", "other"]
    text: str; why: str                          # "When was this taxi?" / "Over £50, so I need …"
    status: Literal["open", "waiting", "resolved"]   # waiting: "I don't have it" / "Not sure"
    answer: Optional[str] = None; source: Literal["rules", "agent"]; created_at: str; resolved_at: Optional[str] = None
class ChatThread(BaseModel): id: str; client_id: int; year_start: dt.date; title: str; created_at: str; updated_at: str
```

- Produces `class AgentRecords(db)` in `records.py`. It exposes `.db`, which `ledger_book` uses for `ledger_entries` and `posting_batches`:
  - `append_decision(d: DecisionDraft, idempotency_key: str) -> tuple[Decision, bool]`. The bool is "new". This method fills in `id`, `created_at` and the hash chain per client. A repeated key returns the stored decision with `False`.
  - `decisions(client_id, year_start=None, since: Optional[str]=None) -> list[Decision]`
  - `upsert_question(q: QuestionDraft, key: str) -> Question`. The key is unique per client.
  - `questions(client_id, year_start, statuses=("open","waiting")) -> list[Question]`
  - `set_question(id, status, answer=None) -> Question`
  - `create_thread(client_id, year_start, title) -> ChatThread`, `threads(client_id=None)`, `thread(id)`, `touch_thread(id, title=None)`, `delete_thread(id)`
  - `document_text(sha256) -> Optional[list[str]]`, `save_document_text(sha256, pages, method, model)`
- Produces `MongoStore.add_split(client_id, row_id, parts: list[Transaction], decision_id) -> list[int]`. In one revision-checked write, it marks the row `superseded_by=decision_id` and adds the parts as a new upload `kind="split"` named `"<original upload name> (split)"`. It returns the new row ids.
- `DecisionDraft` and `QuestionDraft` are the same models without the server-filled fields.

- [ ] **Step 1: Write the failing tests**

```python
def test_decision_is_idempotent(records): d1, new1 = records.append_decision(draft(), "k"); d2, new2 = records.append_decision(draft(), "k")
    assert (new1, new2) == (True, False) and d1.id == d2.id and len(records.decisions(1)) == 1
def test_decisions_are_hash_chained(records): a, _ = records.append_decision(draft(), "a"); b, _ = records.append_decision(draft(), "b")
    assert b.prev_hash == a.hash
def test_question_upsert_keeps_one_per_key(records): ...   # second upsert with the same key updates text, keeps id and status
def test_add_split_supersedes_and_adds_parts(mongo_store, acme): ...   # booked() False on the original; parts sum to its gross
```

- [ ] **Step 2: Run the tests.** Run `pytest tests/test_records.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 3: Implement the models, `AgentRecords`, the indexes and `add_split`.** The indexes are:
  - `decisions` (client_id, year_start), and `idempotency_key` unique;
  - `questions` (client_id, key) unique;
  - `chat_threads` (client_id, updated_at).

  The hash is `sha256(prev_hash + canonical JSON of the decision without hash)`.
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_records.py -m mongo -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: append-only decisions, questions, chat threads and document texts`.

### Task 4: Resolutions (R0–R5)

**Files:**
- Create: `ledgersync/resolutions.py`
- Test: `tests/test_resolutions.py` (marker `mongo`)

**Interfaces:**
- Consumes `AgentRecords` and `MongoStore.add_split` (Task 3), `documents.text_of` (Task 5; stub it in tests by passing `texts=`), `books.ledger`, `ledger.ensure_open`, and `store.patch_row`.
- Produces:

```python
class KeepOne(BaseModel): action: Literal["keep_one"]; keep_row_id: int; drop_row_ids: list[int]
class UsePrimary(BaseModel): action: Literal["use_primary"]; primary_row_id: int; other_row_id: int
class SplitPart(BaseModel): description: str; account_code: str; gross: Decimal; rate: VatTreatment
class SplitVat(BaseModel): action: Literal["split_vat"]; parts: list[SplitPart]
class VatFromDocument(BaseModel): action: Literal["set_vat_from_document"]; vat: Decimal
Resolution = Annotated[Union[KeepOne, UsePrimary, SplitVat, VatFromDocument], Field(discriminator="action")]
def resolve(store, records, *, client_id: int, thread_id: Optional[str], actor: str, row_id: int,
            resolution: Resolution, evidence: list[Evidence], reason: str) -> Decision
def set_date(store, records, *, client_id, thread_id, row_id: int, date: dt.date, question_id: str) -> Decision
def record_automatic(store, records, *, client_id: int, year_start: dt.date, thread_id: Optional[str]) -> list[Decision]
RANK = {"invoice": 3, "receipt": 3, "payroll": 3, "statement": 2, "expense_claim": 1}   # anything else 1
```

**The rule each action applies.** Copy the R1–R5 table in `docs/2026-11-02-ai-accountant-demo-plan.md`. These are the differences:

- **R0, applied to every action.** The service checks all of the following:
  - every row belongs to `client_id`;
  - the row's year is open (`ensure_open`);
  - every evidence quote appears, whitespace-normalised and case-insensitive, in `text_of` for its upload;
  - every evidence upload is that client's;
  - after the change, `books.ledger` shows no **new** error-level issue on the touched rows.

  If any check fails, the change is reverted with a compensating patch, and a `refused` decision is stored with `why` in `reason`.
- **keep_one** sets `excluded=True` on the dropped rows. **use_primary** sets `excluded=True` on the other row. If the other row is a bank line, it sets `link` instead, so the bank line pays the primary.
- **split_vat** uses `add_split`. The parts' gross must sum exactly to the row's gross. `vat_in_gross(part.gross, part.rate)` summed must equal the row's `vat` within `0.01 × len(parts)`.
- **set_date** is called only from an answer, never by the model, and the evidence is "user". The date must be within the client's books (`settings.books_start` ≤ date ≤ the end of the open year). Otherwise it raises `InvalidValue` ("That date is outside the books, which run from … to …").
- **record_automatic** turns the year's rows carrying `date_from_bank` into decisions, rule `"R1 Date from the bank"`, actor `"rules"`, with the bank line as evidence. It is idempotent, keyed on (row id, date).
- **Idempotency key:** `sha256(client_id, sorted row ids, resolution.model_dump_json())`.

- [ ] **Step 1: Write the failing tests** (Northbridge-like rows built with `tests/helpers.py`)

```python
def test_keep_one_excludes_lower_ranked_copy(...)            # receipt kept, sheet line excluded, status applied
def test_keep_one_refuses_dropping_higher_rank(...)          # status refused, rows unchanged
def test_use_primary_invoice_beats_sheet(...)                # £30.22 booked, £27.50 excluded
def test_split_vat_parts_must_sum(...)                       # 0.01 short → refused
def test_split_vat_supersedes_original(...)                  # original superseded_by == decision.id; parts booked
def test_vat_from_document_must_appear_in_text(...)
def test_quote_not_in_document_refused(...)                  # Review Focus 5
def test_closed_year_refused(...)                            # Review Focus 5
def test_other_clients_row_refused(...)
def test_resolve_twice_is_one_decision(...)
def test_set_date_outside_books_refused(...)
def test_record_automatic_turns_bank_dating_into_decision(...)   # rule startswith "R1", actor "rules"; twice → one
```

- [ ] **Step 2: Run the tests.** Run `pytest tests/test_resolutions.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 3: Implement `resolutions.py`.**
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_resolutions.py -m mongo -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: resolutions R0–R5, each checked against its evidence and recorded`.

### Task 5: Document text

**Files:**
- Create: `ledgersync/documents.py`
- Modify: `ledgersync/pipeline.py` (make `_pdf_text` public as `pdf_text`, keeping a private alias for callers), `ledgersync/intake.py` (expose the existing spreadsheet/CSV-to-text conversion as `text_of_bytes(name, data) -> Optional[str]`)
- Test: `tests/test_documents.py`

**Interfaces:**
- Produces `documents.text_of(upload: dict, blobs, records: AgentRecords, vision=None) -> list[str]`:
  - pages of at most 12,000 characters;
  - CSV and TXT as they are, XLSX as tab-separated sheets, a text PDF as its text;
  - an image or scanned PDF → `vision.transcribe(image_b64) -> str` (add `ModelClient.transcribe`, a plain chat call asking for a faithful transcript).
  - It caches by `upload["sha256"]` in `records`, and calls the vision model at most once per file.

- [ ] **Step 1: Write the failing tests.**
  - `test_csv_comes_back_as_is`.
  - `test_xlsx_as_tab_separated`.
  - `test_long_text_split_into_12k_pages`.
  - `test_image_uses_vision_once`: a fake `vision` counts calls, and two `text_of` calls → 1.
- [ ] **Step 2: Run the tests.** Run `pytest tests/test_documents.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_documents.py tests/test_pipeline.py tests/test_intake.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: one service returns a document's text, transcribing images once`.

### Task 6: Posted ledger

**Files:**
- Create: `ledgersync/ledger_book.py`
- Modify: `ledgersync/books.py` (add `booked_rows`), `ledgersync/models.py` (`PostResult`, `PostedTrialBalance`)
- Test: `tests/test_ledger_book.py` (marker `mongo`)

**Interfaces:**
- Consumes `evidence_rules.document_rule` and `journal_with_rule` (Task 2), and `books.opening`.
- Produces:

```python
# books.py
def booked_rows(store, client_id: int, year_start: dt.date) -> list[tuple[int, Transaction]]
    # (row id, matched tx) for the year's booked rows, matched exactly as _trial_balance matches them;
    # raises InvalidTransactions as _trial_balance does
# ledger_book.py
def wanted_journal(store, client_id, year_start) -> dict[int, list[JournalLine]]          # by row id, with document rules
def post(store, records, client_id, year_start, *, decision_ids: Sequence[str] = ()) -> PostResult
def posted_trial_balance(store, records, client_id, year_start) -> PostedTrialBalance
def unposted_changes(store, records, client_id, year_start) -> int                             # rows whose wanted ≠ posted
class PostResult(BaseModel): batch_id: Optional[str]; entries_added: int; reversals_added: int
                             total_debits: Decimal; total_credits: Decimal; problems: list[str] = []
class PostedTrialBalance(TrialBalance): suspense: list[SuspenseItem]   # row id, description, gross, needs
```

- **`post`:**
  1. For each row, it compares the wanted lines with the net of what is already posted for that row id. A changed row gets a reversal of its posted lines plus new lines. A row that is gone or not booked gets a reversal only.
  2. It validates the batch before writing anything. Debits must equal credits for every row and in total. Every code must be in `BY_CODE`. VAT legs are allowed only on 2200 and 2201, and are ≤ gross/6. There is no VAT leg when the client isn't VAT registered.
  3. If validation fails, it writes nothing and returns `problems`.
  4. The batch key is `sha256` of the canonical JSON of the new lines. A repeated key, or nothing to post, → `batch_id=None` and 0 entries.
- **`posted_trial_balance`** = `books.opening` + the sum of `ledger_entries`. It uses the same line shape and totals as `posting.trial_balance`.

- [ ] **Step 1: Write the failing tests**

```python
def test_post_writes_balanced_batch_as_decimal128(...)
def test_post_twice_posts_nothing_second_time(...)
def test_held_payment_posts_to_suspense(...)                 # 240.00 on 9998; suspense item needs "receipt_or_invoice"
def test_excluding_row_after_post_reverses_it(...)
def test_edit_after_post_reverses_once(...)                  # Review Focus 4: unposted_changes == 1, post → 0, re-post → no batch
def test_invalid_batch_writes_nothing(...)                   # monkeypatch wanted_journal to an unbalanced line → problems, 0 entries
def test_posted_trial_balance_includes_opening(...)
```

- [ ] **Step 2: Run the tests.** Run `pytest tests/test_ledger_book.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `pytest -q && pytest -m mongo -q`. Expected: PASS. The existing trial balance tests are unchanged.
- [ ] **Step 5: Commit.** Message: `feat: append-only posted ledger with validation, reversals and Suspense`.

### Task 7: Questions and answers

**Files:**
- Create: `ledgersync/questions.py`
- Test: `tests/test_questions.py` (marker `mongo`)

**Interfaces:**
- Consumes `records` (Task 3), `resolutions.set_date` (Task 4), `ledger_book.post` (Task 6), and `evidence_rules` (Task 2).
- Produces:

```python
def refresh(store, records, client_id: int, year_start: dt.date) -> list[Question]
def ask(records, *, client_id, year_start, row_ids: list[int], text: str, why: str) -> Question   # kind "other", source "agent"
class DateAnswer(BaseModel): kind: Literal["date"]; date: dt.date
class NoDocumentAnswer(BaseModel): kind: Literal["no_document"]
class NotSureAnswer(BaseModel): kind: Literal["not_sure"]
Answer = Annotated[Union[DateAnswer, NoDocumentAnswer, NotSureAnswer], Field(discriminator="kind")]
def answer(store, records, *, client_id, thread_id, question_id: str, answer: Answer) -> list[Question]
```

- **`refresh`** works out the rule questions from the books, upserting each with a stable key. It resolves rule questions whose condition no longer holds (`resolved_at` set). Agent questions are left alone.
  - **Date:** a booked row with no date and no `date_found` from a bank line → kind `date`. The text is `"When was this <description>?"`, and the why is `"£<gross>, no date on it and no matching bank line."`. Key: `date:<row id>`.
  - **Held row:** a row held by `document_rule` → kind `needs`. For `receipt_or_invoice` the text is `"Can you upload the receipt or invoice?"`; for `vat_invoice` it is `"Can you upload the full VAT invoice?"`. The why is `"£<gross> to <counterparty or description> on <date>. <Over £50|Over £250>, so I need it. Held in Suspense as Documentation required until then."`. Key: `doc:<row id>`.
  - **Questions in `waiting`** stay waiting until their condition clears.
- **`answer`:**
  - `date` → `set_date` with the date.
  - `no_document` → status `waiting`, answer `"I don't have it"`.
  - `not_sure` → status `waiting`, answer `"Not sure"`.
  - Then it calls `refresh` and `ledger_book.post`.
  - An answer to a resolved question does nothing.
  - A repeat of the same answer → the same single decision.
- **Upload answers** are not here. The API reads the file into the client's documents, then calls `refresh` (Task 10). If the question is still open after the read, the API attaches the reason to it (Task 10).

- [ ] **Step 1: Write the failing tests.**
  - `test_undated_receipt_without_bank_match_asks_for_date`.
  - `test_receipt_dated_from_bank_asks_nothing`.
  - `test_file_name_date_never_used`: `IMG_20261014.png` with no date → a `date` question, and the row's date stays None.
  - `test_240_payment_without_invoice_asks_for_document`.
  - `test_receipt_over_250_asks_for_vat_invoice`.
  - `test_answer_date_dates_row_and_resolves`.
  - `test_answer_twice_is_one_decision` (Review Focus 1).
  - `test_no_document_keeps_suspense_and_waits`.
  - `test_uploaded_invoice_resolves_held_payment`: add an upload whose invoice matches £240 → `refresh` → resolved, and the posted Suspense is reversed.
  - `test_invoice_that_does_not_fit_stays_open` (Review Focus 3).
- [ ] **Step 2: Run the tests.** Run `pytest tests/test_questions.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_questions.py -m mongo -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: questions worked out from the books, and answers applied without the model`.

### Task 8: Test cases, Northbridge demo data, scripted run, reset

**Files:**
- Create: `eval/agent_cases/<case>/{client.json, documents/, expected_trial_balance.json, expected_decisions.json, expected_questions.json, notes.md}` for:
  - `missing-date-from-bank`
  - `missing-date-must-ask`
  - `duplicate-receipt-spreadsheet`
  - `combined-vat`
  - `conflict-invoice-vs-expense-report`
  - `vat-on-invoice-missing-from-entry`
  - `no-invoice-over-50-suspense`
  - `receipt-over-250-needs-invoice`
  - `clean-month`
- Create: `demo/northbridge/`, laid out as in the reference plan. These differences apply:
  - the Costco receipt prints a supplier VAT number;
  - `barclays-october.csv` holds a £240.00 Brightline Print payment on 22 Oct with no invoice;
  - `brightline-invoice-BP-2210.pdf` (£240.00 incl. £40.00 VAT) is kept apart, for uploading as the answer;
  - the parking photo is matched by a £6.50 bank line;
  - the taxi receipt (£18.00) has no date and no matching line.
- Also create `demo/northbridge/expected_trial_balance_before_answers.json`, `expected_trial_balance_after_answers.json` and `notes.md`, all worked by hand.
- Create: `eval/run_scripted_resolutions.py`, `ledgersync/demo.py`
- Test: `tests/test_agent_cases.py` (marker `mongo`)

**Interfaces:**
- Consumes Tasks 3–7.
- Produces:
  - `demo.reset(store, records, db) -> int` (the Northbridge client id). It drops that client's rows, decisions, questions, threads, checkpoints, `ledger_entries` and `posting_batches`, then loads `demo/northbridge/existing/*.json` as already-read uploads.
  - The CLI `python -m ledgersync.demo reset`.
  - `run_scripted_resolutions.run(case_dir, store, records) -> CaseResult`: it loads the case, applies `expected_decisions.json` through `resolutions.resolve`, applies the answers in `notes.md`'s "Answers" section through `questions.answer`, posts, and returns the posted trial balance and questions.

- [ ] **Step 1: Work every case by hand in `notes.md` before any code runs on it.** Use the same format as `eval/jobs/*/notes.md`: each row, its rule, its journal, and the trial balance to the penny.
- [ ] **Step 2: Write the failing test.**
  - `test_scripted_case_matches_expected[case]`, parametrised over every case directory and `demo/northbridge`.
  - It checks that the posted trial balance equals `expected_trial_balance*.json` exactly, line by line.
  - It checks that the open questions equal `expected_questions.json` (kind and row description).
- [ ] **Step 3: Run the test.** Run `pytest tests/test_agent_cases.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 4: Implement the runner and `demo.py`.**
  - If a case shows a problem that the existing checks don't raise as an issue, add the deterministic check where it belongs (`checks.py` or `matching.py`), with its own unit test.
  - Never edit the expected figures to fit the code without re-working `notes.md` and saying why in the commit.
- [ ] **Step 5: Run the test.** Run `pytest tests/test_agent_cases.py -m mongo -v`. Expected: PASS for every case.
- [ ] **Step 6: Commit.** Message: `test: agent cases and the Northbridge demo, worked by hand and run through the services`.

### Task 9: The agent

**Files:**
- Create: `ledgersync/agent/__init__.py`, `llm.py`, `tools.py`, `prompt.py`, `middleware.py`, `run.py`
- Modify: `requirements.txt` (`langchain-openrouter==0.2.9`), `ledgersync/config.py` and `.env.example`:
  - `LEDGERSYNC_AGENT_MODEL=openai/gpt-oss-120b`
  - `LEDGERSYNC_AGENT_TIMEOUT=60`
  - `LEDGERSYNC_DEMO=0`
- Test: `tests/test_agent.py`, and `tests/agent_fakes.py` (a scripted chat model)

**Interfaces:**
- Consumes `books`, `records`, `resolutions.resolve`, `questions.ask`, `documents.text_of`, and `ledger_book.posted_trial_balance`.
- Produces:

```python
@dataclass class ChatContext: client_id: int; thread_id: str; year_start: dt.date
def build_agent(settings: Settings, deps: AgentDeps, *, model=None, checkpointer=None)   # create_agent(...)
# Tools (all take runtime: ToolRuntime[ChatContext]; args are Pydantic):
get_overview() ; list_issues(family: Optional[Literal["date","duplicate","combined_vat","conflict","missing_vat","documents","other"]], after_row_id: int = 0, limit: int = 20)
get_row(row_id) ; list_documents() ; read_document(upload_id, page: int = 1)
resolve_issue(row_id, resolution: Resolution, evidence: list[Evidence] (1–3), reason: str (≤400))
ask_user(row_ids: list[int], question: str (≤200), why: str (≤300))
list_questions() ; list_decisions() ; get_trial_balance()
```

- **No tool sets a date or posts.**
- **`build_agent`** passes:
  - `ChatOpenRouter(model=settings.agent_model, reasoning={"effort": "medium"}, openrouter_provider={"require_parameters": True, "data_collection": "deny"}, timeout=60, max_retries=2)`;
  - `context_schema=ChatContext`;
  - `checkpointer=MongoDBSaver(client, db_name=f"{db}_checkpoints")`;
  - the middleware: `ModelCallLimitMiddleware(run_limit=30, exit_behavior="end")`, `ToolCallLimitMiddleware(run_limit=80, exit_behavior="end")`, `ToolCallLimitMiddleware(tool_name="read_document", run_limit=20)`, `ModelRetryMiddleware(max_retries=2)`, `ToolErrorsAsMessages` (a `wrap_tool_call` that turns `ValidationError`, `LedgerSyncError` and an unknown tool into an error `ToolMessage`), and `StopWhenCancelled(is_cancelled: Callable[[str], bool])`.
- **The prompt** (`prompt.py`, plain sentences) gives these rules:
  - act like the client's accountant;
  - work only through tools;
  - never state a figure no tool returned;
  - rank evidence: invoice, receipt or payroll, then bank line, then sheet;
  - open the document before resolving a conflict or a VAT question;
  - you cannot set dates — undated items with no bank match become questions automatically;
  - documents over the limits become questions automatically;
  - use `ask_user` only for what the evidence can't settle and the rules don't already ask;
  - at the start of a thread, call `list_questions` and mention anything still open from earlier chats;
  - finish with two or three sentences, because the summary cards are added by the system.
- **`run.py`** provides `stream_turn(agent, ctx, text) -> Iterator[ChatEvent]`. It uses `stream_mode=["messages","updates","custom"]` and maps the stream to `step` (tool name + one-line label, e.g. `read_document` → "Opened costco-receipt-21-10.txt"), `token` and `error` events. The recursion limit is 120.

- [ ] **Step 1: Write the failing tests** with the scripted model.
  - `test_malformed_tool_args_become_error_message_and_run_continues`.
  - `test_unknown_tool_reported_back`.
  - `test_model_exception_mid_run_emits_error_event_keeps_steps`.
  - `test_model_call_limit_stops_with_message`.
  - `test_resolve_retried_records_once`.
  - `test_tools_use_context_client_not_args`: the tool schemas have no `client_id`.
  - `test_two_threads_share_no_messages`.
  - `test_no_tool_can_set_a_date`: no tool schema accepts `date` except inside `SplitPart`, which has none.
- [ ] **Step 2: Run the tests.** Run `pytest tests/test_agent.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `pytest tests/test_agent.py -v`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: the accountant agent, its tools, prompt and limits`.

### Task 10: Chat API

**Files:**
- Create: `ledgersync/agent/chat.py` (the turn and the summary), `ledgersync/agent/locks.py` (the per-client lock, ported from `accounting-agent` 947ae1b)
- Modify: `server.py` (routes; build the agent in `create_app`, injectable for tests)
- Test: `tests/test_chat_api.py` (marker `mongo`)

**Interfaces:**
- Consumes everything above, plus the existing `submit_analysis` and the job registry.
- **The turn,** `chat.turn(thread, text, files) -> Iterator[ChatEvent]`. Its SSE events are `status | step | token | summary | error | done`:
  1. Save and read the files with the existing `submit_analysis`, for the thread's client. Statements go to the bank account given per file (default: the first current account). Each file emits a `step` ("Reading <name>…" → "Read <name> (n rows)" or "Couldn't read <name>: <reason>").
  2. `stream_turn`.
  3. `resolutions.record_automatic`.
  4. `questions.refresh`.
  5. `ledger_book.post`.
  6. Emit a `summary`, built by `chat.summary(...)` from the records:

```python
class ReviewSummary(BaseModel):
    sorted: list[Decision]          # applied decisions since the turn started
    questions: list[Question]       # every open or waiting question on the client's year
    trial_balance: PostedTrialBalance
    post: PostResult
```

- **Routes:**
  - `GET /api/chat/threads?client_id=`
  - `POST /api/chat/threads` `{client_id}` → a thread on the client's open year, with title "New chat"
  - `GET /api/chat/threads/{id}` → the thread, its messages (from `agent.get_state`), and its last summary
  - `PATCH` `{title}`, and `DELETE` (also deletes its checkpoints)
  - `POST /api/chat/threads/{id}/messages`: multipart `text`, `files[]`, `bank_accounts[]` → `text/event-stream`. The title is set from the first message (the first 60 characters).
  - `POST /api/chat/threads/{id}/questions/{qid}/answer`: JSON `Answer` → `ReviewSummary`. It also appends `HumanMessage("Answered: <question> → <answer>")` to the thread state with `agent.update_state`.
  - `POST /api/chat/threads/{id}/questions/{qid}/document`: multipart `file` → reads it and refreshes. If the question is still open, it sets `why` to "Read <name>, but it doesn't match: <the invoice's payee and total> against <the payment's payee and amount>." It returns a `ReviewSummary`.
  - `POST /api/chat/threads/{id}/stop`
  - `GET /api/clients/{id}/questions`, `GET /api/clients/{id}/decisions?year_start=`, `GET /api/clients/{id}/years/{start}/posted-trial-balance`
  - `POST /api/demo/reset`, only when `LEDGERSYNC_DEMO=1` (404 otherwise)
- **One run per thread.** A second message while a run is going → 409 "Still working on the last message."

- [ ] **Step 1: Write the failing tests** (scripted model; a fake model client for reading the files).
  - `test_new_thread_belongs_to_client`.
  - `test_message_streams_steps_then_summary_then_done`.
  - `test_summary_lists_held_payment_and_question`.
  - `test_answer_date_returns_updated_summary`.
  - `test_upload_answer_moves_out_of_suspense`.
  - `test_questions_survive_restart`: a new `create_app` on the same DB → the questions are listed, and the answer still applies (Review Focus 2).
  - `test_thread_history_survives_restart`.
  - `test_second_message_while_running_409`.
  - `test_writes_need_header`.
  - `test_demo_reset_hidden_unless_demo`.
- [ ] **Step 2: Run the tests.** Run `pytest tests/test_chat_api.py -m mongo -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `pytest -q && pytest -m mongo -q`. Expected: PASS.
- [ ] **Step 5: Real-model smoke test.** **Ask the user first.** Then run `pytest -m llm tests/test_live_agent.py::test_clean_month`, which uploads `eval/agent_cases/clean-month` and expects no questions and a balanced trial balance.
- [ ] **Step 6: Commit.** Message: `feat: chat threads, streamed review turns, and answers to questions`.

### Task 11: Chat client library

**Files:**
- Create: `frontend/src/lib/chat.ts`, `frontend/src/lib/chat.test.ts`

**Interfaces:**
- Produces TypeScript types mirroring `ChatThread`, `Decision`, `Question`, `ReviewSummary`, `PostedTrialBalance` and `ChatEvent`.
- Produces these functions:
  - `parseEvents(chunk: string, carry: string): { events: ChatEvent[]; carry: string }`, which parses SSE text across chunk boundaries;
  - `groupThreads(threads, now: Date): { label: 'Today' | 'Yesterday' | 'Earlier'; threads }[]`;
  - `questionControl(q: Question): 'date' | 'upload' | 'text'`;
  - `ruleBadge(d: Decision): string` (e.g. `"R2"`);
  - `formatMoney(s: string): string` (`"£1,412.68"`);
  - `streamMessage(threadId, text, files, bankAccounts, onEvent, signal): Promise<void>`, which uses `fetch` with the `X-LedgerSync` header and `parseEvents`;
  - `answerQuestion` and `uploadForQuestion`.

- [ ] **Step 1: Write the failing tests.**
  - `parseEvents` handles an event split across two chunks.
  - `groupThreads` works at midnight boundaries.
  - `questionControl` maps each kind.
  - `formatMoney` handles thousands and negatives.
- [ ] **Step 2: Run the tests.** Run `cd frontend && npm test`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Run `cd frontend && npm test`. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: chat client library`.

### Task 12: Chat screen

**Files:**
- Create: `frontend/src/app/chat/page.tsx`, `frontend/src/app/chat/[threadId]/page.tsx`, and in `frontend/src/components/chat/`: `ThreadList.tsx`, `ClientPicker.tsx`, `Composer.tsx`, `RunSteps.tsx`, `ReviewSummary.tsx`, `QuestionCard.tsx`, `DecisionLine.tsx`, `PostedTrialBalance.tsx`
- Modify: `frontend/src/components/AppHeader.tsx` (Clients | Chat; Reset demo behind `ConfirmDialog` when the health response says demo)

**Interfaces:**
- Consumes `lib/chat.ts` (Task 11). The layout is option A from the brainstorm mockup (`.superpowers/brainstorm/*/content/chat-questions.html`).

**Behaviour:**
- **Threads.** The thread list is grouped Today, Yesterday and Earlier, with each thread's title and client. New chat shows "Which client are we working on?" with searchable client chips, and makes no model call.
- **After picking a client:** if the client has open or waiting questions (`GET /api/clients/{id}/questions`), a line says "N things still need you from earlier", and their cards are shown. The header shows the client and year, and the suggested prompts are "Review the documents I'm adding", "What needs my attention?" and "Show the trial balance".
- **Composer.** A text box, a paperclip and drag and drop. Each file chip shows Queued, Reading, Read (n rows) or Failed with its reason. A statement chip has a bank account picker when the client has more than one bank account.
- **During a run:** "Working on it…" at once, a collapsible step list with spinner → tick or cross, streamed text, and a Stop button.
- **Summary, in this order:**
  1. the narrative;
  2. **Sorted**: one line per decision. Clicking a line opens before → after, the evidence quotes with links to the original file (`/api/clients/{id}/uploads/{uid}/file`), the reason, and "View in Transactions";
  3. **Needs you**: one `QuestionCard` per question, in amber, showing the text and the why. The control comes from `questionControl`:
     - a date input + "Not sure";
     - "Upload" + "I don't have it";
     - a text box.
     A waiting question shows its answer and stays visible;
  4. **Posted**: Balanced or Not balanced, the Suspense rows labelled "needs receipt or invoice" or "needs VAT invoice", the first five accounts and a link to the full table.
- **Answering** replaces the summary with the returned one, in place.
- **Errors:**
  - Model unavailable → a banner keeping the steps, with Retry (which resends the last message) and New chat.
  - Loop limit → "Stopped after N steps", with Continue (which sends "Continue").
  - Lost connection → the thread is reloaded.
- **Empty states:** "Start a chat to review a client's books", and when there are no clients, a link to add one.
- **Narrow screens:** at phone width the thread list collapses behind a button.

- [ ] **Step 1: Build the components and pages.**
- [ ] **Step 2: Verify in the browser pane** against a server with `LEDGERSYNC_DEMO=1` and the scripted model. Run the demo flow, and check desktop and 375 px widths, the console free of errors, and that the answer cards update in place. Take screenshots.
- [ ] **Step 3: Run the tests.** Run `cd frontend && npm test && npx tsc --noEmit`. Expected: PASS.
- [ ] **Step 4: Commit.** Message: `feat: chat screen with review summary, question cards and posted trial balance`.

### Task 13: Client pages

**Files:**
- Modify: `frontend/src/components/TransactionsTable.tsx`, `frontend/src/components/OverviewSection.tsx`, `frontend/src/lib/api.ts`

**Behaviour:**
- **Transactions:**
  - A row with `decision_ids` gets an "Agent" badge, with a popover showing the rule, evidence and before/after (from `/api/clients/{id}/decisions`).
  - Excluded and superseded rows are struck through with the reason.
  - A held row shows "Documentation required".
- **Overview** shows:
  - "N things need you", linking to the client's latest thread;
  - "Posted ledger: up to date" or "N changes not posted" (from `unposted_changes`, exposed on `GET /api/clients/{id}/years/{start}/posted-trial-balance` as `unposted_changes`).

- [ ] **Step 1: Implement, and add the `unposted_changes` field** to the posted trial balance response, with a test in `tests/test_chat_api.py`: `test_posted_trial_balance_reports_unposted_changes`.
- [ ] **Step 2: Verify in the browser pane** after the demo flow. Check the badges, the strike-through and the Overview counts. Take screenshots.
- [ ] **Step 3: Commit.** Message: `feat: agent badges, held rows and posted-ledger status on the client pages`.

### Task 14: End-to-end evaluation

**Files:**
- Create: `eval/run_agent_eval.py`, `tests/test_live_agent.py` (marker `llm`), and `eval/results/<date>-agent.json`

- [ ] **Step 1: Ask the user before spending OpenRouter credit.**
- [ ] **Step 2: Run the real-model eval.** Run `python eval/run_agent_eval.py`. For each case, it resets, uploads the documents through the chat API, sends "Review these documents", applies the case's answers through the answer routes, and scores:
  - the posted trial balance against the expected one, to the penny;
  - the decisions (rule per row) against `expected_decisions.json`;
  - the questions against `expected_questions.json`.

  Expected: every case passes. Record the failures that remain.
- [ ] **Step 3: Run the demo script from the spec three times** in the browser pane, each time from `python -m ledgersync.demo reset`. Save screenshots and the summary JSON to `eval/results/`.
- [ ] **Step 4: Fix what fails, or report it as unverified.** One example is provider variance in gpt-oss tool calls; if tool calls are unreliable across 10 runs, pin the best provider in `openrouter_provider`.
- [ ] **Step 5: Commit.** Message: `test: real-model agent eval and three demo runs`.
