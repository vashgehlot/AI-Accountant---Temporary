# AI accountant demo for Super Accountant: plan (2 Nov, original)

Kept for reference. Its agent behaviour (resolve or flag) is replaced by `docs/superpowers/specs/2026-11-02-accountant-chat-design.md` (decide or ask the user). Its data model, ledger, tools, threads, API, testing and milestones carry over unless that design says otherwise.

## Decisions made while planning

1. **Posted ledger.** Rows stay the working papers. A new append-only `ledger_entries` collection (Decimal128) is the posted ledger, and corrections are made by reversal.
2. **Live documents.** Files are uploaded in the chat, stored with the client's files, and read by the existing pipeline. The agent uses the new and existing data together. It can open a source document again to check a date or an amount, and it decides which of two records to keep.
3. **Threads.** A new chat starts by asking which client. A thread belongs to one client, and a client can have many threads. A thread never sees another thread's context.

## Refactors needed first

1. **Row exclusion.** Add `excluded: bool` to the row data, honoured by `checks.booked`. Set only by agent decisions, not exposed in `RowPatch`.
2. **Splitting a row.** Add `resolutions.split_row`. It keeps the original (marked `superseded_by`) and adds the parts as a new "split" upload, so nothing is overwritten.
3. **Posting is read-only today.** Add `ledgersync/ledger_book.py` (the posted ledger), which reuses `posting.trial_balance(...).journal`.
4. **Server-side, not model-side.** The `client_id` and the actor come from the server, never from model arguments. Each change also needs an evidence and decision record (new `decisions` collection).
5. **Document text.** Expose `pipeline._pdf_text` and the intake text conversion as one `documents.text_of(upload)` service, with its result cached.

Prior art to port selectively: the `accounting-agent` branch (947ae1b) has a hash-chained audit log (`records/audit.py`), a per-client tool lock, `StopWhenCancelled` middleware, and a `create_agent` factory with call-limit middleware. Port those patterns; don't merge the branch.

## Agent

- `create_agent` with `ChatOpenRouter` (`langchain-openrouter==0.2.9`), `model=OPENROUTER_MODEL` (default `qwen/qwen3.8-27b`: one model reads the files and runs the agent), `reasoning={"effort": "medium"}`, `openrouter_provider={"require_parameters": True, "data_collection": "deny"}`, timeout 60 s, `max_retries=2`.
- `context_schema=ChatContext(client_id, thread_id)`, `checkpointer=MongoDBSaver(client, db_name=f"{db}_checkpoints")`.
- Middleware: `ModelCallLimitMiddleware(run_limit=30, exit_behavior="end")`, `ToolCallLimitMiddleware(run_limit=80, exit_behavior="end")` plus `read_document` ≤ 20, `ModelRetryMiddleware(max_retries=2)`, a `wrap_tool_call` middleware turning validation errors and `LedgerSyncError` into error `ToolMessage`s, `StopWhenCancelled`, `recursion_limit=120`.
- Images and scanned PDFs: `read_document` asks the existing Qwen vision model for a transcript, cached by SHA-256.

## Tools

`client_id` and `thread_id` come from `ToolRuntime.context`. Every argument is a Pydantic schema.

| Tool | Inputs | Output | Side effects |
|---|---|---|---|
| `get_overview` | — | Client, years, open year's summary, open issue counts by family | none |
| `list_issues` | `year_start?`, `family?`, `after_row_id=0`, `limit≤20` | Rows with issues, codes, related row ids | none |
| `get_row` | `row_id` | Full row, related rows, source upload, original values, earlier decisions | none |
| `list_documents` | `year_start?` | Uploads with name, kind, rows, statement check | none |
| `read_document` | `upload_id`, `page?` | Document text by page (≤12k chars a page) | caches transcript in `document_texts` |
| `resolve_issue` | `row_id`, `resolution`, `evidence[1–3]`, `reason≤400` | `{decision_id, status: applied, rule, before, after}` or `{status: refused, why}` | decision + row patch or split; idempotent |
| `flag_issue` | `row_ids`, `question`, `missing` | `{decision_id, status: flagged}` | decision only; idempotent (becomes "ask the user" in the new design) |
| `post_ledger` | `year_start` | batch, entries, reversals, totals, or blocking problems | appends `ledger_entries`, `posting_batches`; idempotent |
| `get_trial_balance` | `year_start` | Posted trial balance, totals, `is_balanced`, agreement with the rows' trial balance | none |
| `list_decisions` | `year_start?`, `status?` | Decisions so far | none |

### Resolution rules (the service checks; the model only chooses and cites)

| Action | Rule | Service check |
|---|---|---|
| `set_date{date}` | R1 | The date appears in the row's document text or is a matched bank or claim line's date, and is within the client's books. **A file name no longer counts (new design).** |
| `keep_one{keep, drop[]}` | R2 | Rows linked by a duplicate issue, or same amount, counterparty and dates within 3 days; the kept row ranks at least as high. |
| `split_vat{parts[]}` | R3 | Parts add up exactly to gross; VAT per part via `vat_in_gross` equals printed VAT within 1p per part; accounts exist and are allowed. |
| `use_primary{primary}` | R4 | The rows conflict and the primary ranks higher; secondary `excluded`, bank line linked. |
| `set_vat_from_document{vat}` | R5 | VAT appears verbatim in the document; ≤ gross/6; valid for the account. |
| all | R0 | Row belongs to the client, open year, unchanged since read, no new error-level issue afterwards; otherwise rolled back and recorded `refused`. |

Idempotency key = sha256(client, row ids, action, arguments). `post_ledger`'s key is the hash of the journal it would post.

## MongoDB

| Collection or field | Shape |
|---|---|
| `chat_threads` | `{_id, client_id, title, created_at, updated_at, last_run: {status, error?}}` |
| `<db>_checkpoints` | LangGraph checkpoints |
| `decisions` (append-only, hash-chained) | `{_id, client_id, thread_id, year_start, action, rule, status, row_ids, evidence[{upload_id, upload_name, quote}], reason, before, after, idempotency_key (unique), created_at, actor, reverses?}` |
| `ledger_entries` (append-only) | `{_id, client_id, year_start, batch_id, row_id, account_code, debit: Decimal128, credit: Decimal128, description, reverses?, decision_ids[], posted_at}` |
| `posting_batches` | `{_id, client_id, year_start, key (unique per client/year), kind, totals, validated, created_at}` |
| `document_texts` | `{_id: sha256, pages[], method, model, created_at}` |
| Row `data` | `excluded`, `superseded_by`, `decision_ids[]`; `checks.booked` is False when `excluded` or `superseded_by` is set |

Post-time validation, all or nothing: debits equal credits per row and in total; every account in `BY_CODE` and allowed for the client; VAT legs only on 2200/2201, ≤ gross/6, none on a no-VAT account or a non-VAT-registered client, and `normalise` raises no `vat_*` error.

Reversals: `post_ledger` compares the wanted journal per row with what is already posted for that row. A changed row gets a reversal plus new lines; a removed or excluded row gets a reversal only.

## API (writes need the `X-LedgerSync` header)

- `GET/POST /api/chat/threads?client_id=`, `GET/PATCH/DELETE /api/chat/threads/{id}`
- `POST /api/chat/threads/{id}/messages` (multipart `text` + `files[]`, answered as SSE: `token | step | decision | flag | trial_balance | error | done`)
- `POST /api/chat/threads/{id}/stop`
- `GET /api/clients/{id}/decisions?year_start=`, `GET /api/clients/{id}/years/{start}/posted-trial-balance`
- `POST /api/demo/reset` and `python -m ledgersync.demo reset`

## UI

- Top bar: **Clients | Chat**. `/chat`: thread list on the left (grouped Today, Yesterday, Earlier), conversation on the right.
- New thread asks "Which client are we working on?" with client chips (no LLM call), then offers suggested prompts.
- Composer: text box, paperclip, drag and drop; attachment chips show Queued, Reading, Read (n rows), Failed. Statements on a client with several bank accounts get a bank account picker on the chip.
- During a run: status line at once, collapsible step list, streamed text, Stop.
- Cards: decision (rule, rows, before → after, evidence quotes with links, reason, View in Transactions), trial balance (totals, Balanced badge, agreement with the books).
- Errors: model unavailable (steps kept, Retry, new thread), loop limit ("Stopped after N steps", Continue), malformed tool call (invisible, retried), lost connection (reload from checkpoint).
- Client pages: "Agent" badge on rows with a popover; excluded and split rows struck through; Overview shows "Posted ledger: up to date / N changes not posted".
- "Reset demo" in the header behind a confirm, only when `LEDGERSYNC_DEMO=1`.

## Open decisions (recommendations, accepted)

1. When the posted ledger and the rows' trial balance disagree (a person edits a row after posting): the existing pages keep the rows' trial balance, and Overview shows "N changes not posted". The chat shows the posted one.
2. Images transcribed by Qwen vision inside `read_document`.
3. OpenRouter: `require_parameters` and `data_collection: deny`; pin a provider if tool calls are unreliable.
4. Statement bank account: a picker on the attachment chip, defaulting to the first current account.
5. Plain text with line breaks and lists, plus cards. No markdown library.
6. The model's reasoning text is not shown (one model, `OPENROUTER_MODEL`, reads the files and runs the agent).
7. Expected figures worked by hand in `notes.md` before any code runs on them.

## Demo data

Synthetic, in `demo/northbridge/`: Northbridge Consulting Ltd, limited company, VAT registered, year to 31 Mar 2027, one Barclays current account, opening balances. September's bank CSV and two receipts loaded by reset as already-read rows. October files dropped in live: `barclays-october.csv`, an undated parking photo, a mixed-VAT Costco receipt, the Inkwell invoice (£30.22 incl. £5.04 VAT), `staff-expenses-october.xlsx` (repeats Costco and Inkwell at £27.50, plus a clean mileage line), an undated taxi receipt. `expected_trial_balance.json` and `notes.md` worked by hand. None of this exists yet; it is written as part of the build.

## Tests

`eval/agent_cases/<case>/` with `client.json`, `documents/`, `expected_trial_balance.json`, `expected_decisions.json`, `notes.md`. Three levels: deterministic services (including a scripted resolver run per case to the penny), the agent with `FakeModel`, then the real model (`pytest -m llm`, `eval/run_agent_eval.py`, ask before spending credit) and the demo script ×3 in the browser.

## Milestones

M0 copy plan, branch `ai-accountant-demo`, add `langchain-openrouter==0.2.9` and `.env.example` settings → M1 deterministic core → M2 test set, demo data, reset → M3 agent and API → M4 chat UI → M5 end-to-end eval and demo ×3.
