# AI Accountant: interaction and storage design plan

2026-10-21 · 

## Summary

People use a job workspace, not a free-form chatbot. An accountant opens a client, uploads the year's documents and starts the job. The agent works alone until the filing pack is ready, and people come back only to sign off. A chat panel inside each job answers questions about that job and nothing else.

Everything is stored in two places, both in a UK region in the final version (the MVP can use any region):

- Files (uploads, PDFs, iXBRL, filing submissions and receipts, Excel exports) go in object storage. They are written once and never overwritten.
- Figures and records (transactions, ledger, trial balances, accounts, CT600, exceptions, approvals, audit log) go in MongoDB . They are versioned per job and every figure links back to its source document.

What you asked for:

- A way for people to interact with the agent, including chat.
- Where every file and result is stored, including the trial balance and accounts.
- No human involvement until sign-off, with the agent doing the filing.

What I've assumed (please correct me):

- For now, one person uses it: the client's accountant, acting as preparer, reviewer and admin . The client's responsible person does the final review .
- The existing React/TypeScript front end ( `page.tsx` , `ledger.ts` ) and Python back end ( `server.py` , `jobs.py` ) stay.
- Version one covers small UK private limited companies, as set by the triage rules.

Decided for the MVP (version one):

- The MVP runs on test data only, so any model with enough capability will do.
- One accountant runs each client's job from start to sign-off.
- When the agent needs another document, it asks the client and flags the assumption it made.
- Final review by the client's responsible person comes after the MVP. Until then, the reviewer's approval alone locks the pack.
- MongoDB Atlas can run in any region for the MVP. The final version moves all storage to a UK region.
- Upload links don't expire in the MVP. Expiry is added in the final version.

This is a design spec for review. Once you approve it, the next step is a detailed implementation plan.

## Who interacts and when

Five roles use the system, but only two moments need a person: starting the job and signing it off. In between, people can watch progress and ask questions in chat. They can't change the work.

| Role | Who | When they act | What they can do |
|---|---|---|---|
| Preparer | Accountant at your firm | Start of the job | Create clients, upload documents, start, pause or cancel a job, watch progress, ask chat questions |
| Reviewer | Accountant at your firm (can be the preparer) | Sign-off | Review the pack, acknowledge each exception, approve, or send back with notes |
| Responsible person | The client's responsible person (for a limited company, a director) | After the MVP: sign-off, after the reviewer | Approve the accounts and CT600 through a secure link, or raise a query |
| Client contact | The client's bookkeeper or responsible person | When the agent asks for a document | Upload requested documents through a secure link |
| Firm admin | Practice manager or partner | Setup | Manage users and roles, HMRC agent credentials, the Companies House presenter account and the scope rules |

Sign-off has two parts in a fixed order: the reviewer approves first, then the responsible person does the final review. Filing starts only when both approvals match the same pack hash. In the MVP, the reviewer's approval alone locks the pack.

Pause and cancel are the only controls during a run. They stop the work but never steer it, so the no-intervention rule holds.

In the MVP, the client's accountant holds the preparer, reviewer and admin roles, and there's no final review yet. The roles stay separate in the data model, so a second person can be added later without a redesign.

## The interface

I recommend a job workspace with a chat panel built into each job. The screens hold the work, and the chat answers questions about it. I compared three approaches:

| Approach | How it works | Verdict |
|---|---|---|
| Workspace with scoped chat | Structured screens for upload, progress, exceptions and review, plus a chat panel bound to one job | Recommended. Figures and approvals need structured screens, and chat stays narrow |
| Chat-first | Everything happens through conversation, including uploads and approval | Rejected. Hard to review numbers, hard to audit, and easy to drift out of scope |
| Headless | Documents arrive by email or portal, and review happens in a PDF | Rejected for version one. The reviewer can't drill from a figure to its source |

The workspace has eight screens, including the client's upload page. Each one lists its empty, loading and error behaviour, so the developers don't have to guess.

| Screen | Used by | What it shows | Empty, loading and error states |
|---|---|---|---|
| Client list | Preparer, reviewer | Every client with its year end, the current job's status and the next deadline (accounts, CT600 or tax payment) | Empty: "No clients yet. Add a client to start their first year-end job." A client with no year end shows a "Year end not set" flag |
| Client profile | Preparer, admin | Company number, UTR, year end, accounting framework, HMRC agent authorisation, Companies House authentication code, prior-year figures | Missing authorisation blocks new jobs: "HMRC agent authorisation is missing for this client. Add it before you start a job." |
| New job | Preparer | The period, a checklist of expected documents, drag-and-drop upload with a check on each file, then the triage result | Unreadable file: "This file can't be read. It may be password-protected. Upload an unlocked copy." A triage failure shows its reason before any work starts |
| Job workspace | Preparer, reviewer | A stage tracker, a plain-English activity feed, and tabs for documents, requests, ledger, exceptions and chat. The ledger tab is the existing review screen, read-only during the run | Updates live as each stage finishes. A failed stage names the stage and the error. Retry appears only for system errors |
| Sign-off review | Reviewer | The pack (accounts, computation, CT600), each figure drillable to its journals and then its source document, gate results, changes against last year, and every exception and judgement call | "Approve" stays disabled until every exception is acknowledged. "Send back" needs a note and the stage to return to |
| Final review | Responsible person, after the MVP | A plain summary (turnover, profit, tax due and its payment date), the full accounts and CT600, and the declarations they're making | Expired link: "This link has expired. Ask your accountant to send a new one." |
| Filing status | Preparer, reviewer | Each submission's status, the HMRC and Companies House references, acceptance or rejection, and receipts to download | A rejection shows the gateway's error and whether the job went back to sign-off |
| Document request page | Client contact | Each requested document with the reason it's needed, and an upload area. Nothing else from the job is visible | A document already received shows as received. Expired link: "This link has expired. Ask your accountant to send a new one." |

The document checklist asks for a statement for every bank account covering the whole period, sales and purchase invoices, last year's accounts, and fixed asset and loan details.

Use the same words everywhere: job, pack, exception, sign-off. The activity feed announces each new stage to screen readers, and status never relies on colour alone.

## The chat panel

The chat panel answers questions about one job and turns change requests into review notes. It never edits the books itself. Every message first goes to a scope router: a small model with structured output that sorts it into one of seven intents. Anything the router isn't confident about is treated as out of scope.

| Intent | Example | What answers it | When it's allowed |
|---|---|---|---|
| Explain a figure | "Why is rent higher than last year?" | Read-only ledger tools: the journals behind an account and their source documents | Any time |
| Find a document | "Show me the March bank statement" | A document lookup by type, date and account | Any time |
| Job status | "What's left before review?" | The job's state and activity feed | Any time |
| Exceptions | "Which assumptions did you make?" | The exceptions log | Any time |
| Deadlines | "When is the tax payment due?" | The client profile's deadline dates | Any time |
| Change request | "Move the laptop purchase to fixed assets" | A review note card, which the reviewer confirms | Acted on at sign-off. Before that, it's saved and shown at sign-off |
| Out of scope | General questions, or anything about another client | A fixed reply. The chat agent is never called | Never |

The rules behind the panel:

- The chat agent has read-only tools only. Its job ID and client ID come from the user's session, never from the model.
- Each figure in an answer links to its journal and source document, so the person can check it.
- A confirmed change request becomes a "send back" note. The agent applies it, re-runs from the affected stage, and returns the pack to sign-off.
- Chat history is saved with the job and forms part of its audit trail.

The out-of-scope reply says what the panel can do and how to use it: "I can only help with this job: its figures, documents, exceptions, deadlines and filing status. Try asking why a figure is what it is."

## Missing documents and assumptions

When the agent needs a document it doesn't have, it does two things at once: it asks the client for it, and it flags the assumption it made so the work carries on. The accountant is never asked mid-run.

1. The agent spots a gap, such as a missing month of bank statements or no invoice behind a large payment.
2. It makes the most reasonable assumption, records it as an exception with its confidence, and carries on.
3. It calls a new tool, `request_client_document` , with the document type, the period and the reason. The request is linked to the exception.
4. The system emails the client contact a secure upload link. All requests from one run go in a single email, and reminders follow after 3 and 7 days if nothing arrives .
5. If the client uploads before filing, the agent checks the file, re-runs from the affected stage and marks the exception resolved. Any approval already given is cleared, and the updated pack goes back to sign-off.
6. If the document still hasn't arrived at sign-off, the reviewer sees the exception, the assumption, and the request's date and status, then decides whether to approve or wait.

Guardrails:

- The agent never writes the email. It supplies only the document type, period and reason, and the system sends a fixed template, so text inside a document can't steer what the client receives.
- Each upload link shows the client only the documents requested, nothing else from the job.
- A document that arrives after filing is stored and flagged for the accountant. It never changes a filed pack, because an amendment is a separate job.

In the MVP, the client contact is a test email address, and upload links don't expire. Expiry is added in the final version.

## Final review (after the MVP)

This is built after the MVP, and planned in the Final review tab of the phase plans. The client's responsible person approves in a browser without needing an account, using a single-use link plus a one-time code. For a limited company they must confirm they're a director, because the law requires the board to approve the accounts. The link expires after 14 days.

1. After the reviewer approves, the system emails the responsible person a link and texts them a one-time code.
2. The responsible person opens the link and enters the code. They need both to see the pack.
3. They see a plain summary first: turnover, profit, tax due and the payment date. The full accounts and CT600 sit underneath.
4. They tick each declaration they're making, such as approving the accounts as presented and confirming that the CT600 is correct and complete.
5. They choose "Approve and sign" or "Ask a question". A question goes to the reviewer and holds the job at sign-off.

Each approval records the responsible person's name, the time, the IP address, the code check, every declaration ticked, and the pack hash they saw. That record goes in the append-only audit log. A signed PDF certificate is stored with the pack.

An e-signature provider could run steps 2 to 5 and supply the audit certificate. Building it yourself is simpler for version one, but then you own the identity checks. The plan builds it behind an interface, so a provider can replace it later.

## Notifications

Notifications tell people when something is ready or has gone wrong. None of them asks for input while the agent is running.

| Event | Sent to | Channel |
|---|---|---|
| Triage passed, job started | Preparer | In-app |
| Job outside version one's scope | Preparer | In-app and email |
| A stage failed with a system error | Preparer, admin | In-app and email |
| Pack ready for review | Reviewer | In-app and email |
| Final review requested | Responsible person | Email, plus a text with the code |
| Final review approved, or a question asked | Reviewer | In-app and email |
| Filing accepted | Preparer, reviewer, responsible person | Email with receipts attached |
| Filing rejected | Reviewer | In-app and email |
| Deadline approaching with no job started | Preparer | Email 60, 30 and 14 days before |
| Tax payment due | Responsible person | Email before the payment date |
| Agent requests documents | Client contact | One email per run with a secure upload link |
| Requested document still missing | Client contact | Reminder email after 3 and 7 days |
| Requested document received | Preparer | In-app |

Notifications to the responsible person start when final review is built. In the MVP, they go to the accountant.

## Where everything is stored

MongoDB holds every figure, plus the key and hash of every file. Object storage holds the files themselves.

_[Diagram: storage map · 2 stores of record, 3 supporting — see the doc]_

The trial balance lives in MongoDB as a snapshot document at each stage, and its Excel export sits in object storage. The accounts and CT600 live in MongoDB as versioned documents, and their PDF and iXBRL files sit in object storage.

File paths follow firm, client and job, for example `firm/{firm_id}/client/{client_id}/job/{job_id}/uploads/{document_id}.pdf`. The hash stored in MongoDB proves that a file hasn't changed since it was uploaded or filed.

LangGraph keeps its checkpoints in the same MongoDB cluster, in a separate database, through `MongoDBSaver` from the `langgraph-checkpoint-mongodb` package. The existing `store.py` moves from SQLite to MongoDB in phase 1.

The MVP uses MongoDB Atlas in any region. The final version moves MongoDB and object storage to a UK region.

Until an object storage provider is picked, the MVP keeps files in GridFS in the same Atlas cluster, behind a blob-store interface that S3 can replace later.

## Data model

Every figure traces back to a file. A journal line belongs to a journal, the journal points to its source document, and the document points to its file in object storage. Trial balances, statements and packs are snapshots: each change creates a new version, and nothing is updated in place.

MongoDB needs a few rules so the books stay correct to the penny:

- Store every amount as an exact decimal string ( `"12.50"` ), as `MongoStore` already does , never as a float, so totals always tie.
- Keep each client's rows inside its client document, as MongoStore already does. A row change is then a single-document write, which MongoDB makes atomic, and posting.py derives the journals from the rows .
- Use multi-document transactions where one step writes to several collections, such as a year-end adjustment and its journal. Transactions need a replica set, which MongoDB Atlas provides by default.
- Give each collection a JSON Schema validator for required fields and types. The posting tool also checks that debits equal credits before it writes.
- The app's database user can only insert into and read `audit_log` , never update or delete. Each entry carries the hash of the entry before it, so any tampering shows.

| Collection | What it holds | References |
|---|---|---|
| `firms`, `users` | Your firm, its staff and their roles | — |
| `clients` | Company number, UTR, year end, accounting framework, authorisation status | `firms` |
| `jobs` | Period, status, current stage, LangGraph thread ID | `clients` |
| `documents` | Storage key, SHA-256 hash, document type, period covered, validation result | `jobs` |
| `extracted_transactions` | Date, amount, description, extraction confidence | `documents` |
| `chart_of_accounts` | Account codes, names and types (the existing `accounts.py`) | `firms` |
| `journals` | Not stored in phase 1: posting.py derives each journal from the rows, and the agent's decisions are row edits with audit entries | `jobs`, `documents`, `chart_of_accounts` |
| `trial_balances` | A versioned snapshot, lines embedded, labelled by stage: after posting, after the gate, after year end, final | `jobs` |
| `year_end_adjustments` | Accruals, prepayments, depreciation, stock, director's loan, tax provision, each with its working | `jobs`, `journals` |
| `statements` | Accounts, tax computation and CT600 as versioned documents, with keys for the PDF and iXBRL files and a hash | `jobs` |
| `exceptions` | What couldn't be resolved, the assumption made, the confidence, open or acknowledged | `jobs` |
| `review_notes` | Send-back notes and confirmed chat change requests, each with a target stage | `jobs` |
| `filing_packs` | A manifest of every artefact's hash, plus the pack hash | `jobs`, `statements` |
| `approvals` | Reviewer and final review approvals: person, time, declarations, IP, certificate key | `filing_packs` |
| `filings` | HMRC or Companies House, submission and response keys, references, status, receipt key | `filing_packs` |
| `job_events` | The plain-English activity feed | `jobs` |
| `chat_messages` | Each message, its author, its intent | `jobs` |
| `audit_log` | Append-only: actor, action, object, hashes before and after, time | Everything |
| `document_requests` | Document type, period, reason, link expiry, status (sent, reminded, received, expired) | `jobs`, `exceptions`, `documents` |

## Job lifecycle

A job moves through seven main states. Every path to filing passes through both approvals.

_[Diagram: job lifecycle · 9 states — see the doc]_

If a rejection only needs a technical fix that leaves every figure unchanged, the job stays in Filing and resubmits. The preparer can cancel a job from any state before Filing. A cancelled job keeps its files and audit trail until its retention date.

A document the client uploads after a request sends the job back to Preparing from the affected stage, unless the job is already filed. Any approval given is cleared, and the pack goes through sign-off again.

The MVP has no final review, so the reviewer's approval moves the job straight from Awaiting review to Filing.

## Security, access and retention

In the final version, client data stays in a UK region and is encrypted. The MVP runs on test data, so MongoDB Atlas can use any region. It's kept for at least 6 years after the period it relates to, and only the filing service can read the filing credentials.

Access:

- Access is role-based within each firm, and staff see only the clients assigned to them.
- Every staff account uses multi-factor authentication.
- A fter the MVP, a final review link will be single-use, read-only and scoped to one pack.
- Filing credentials live in a secrets manager: HMRC agent credentials, the Companies House presenter ID and authentication code, and each client's company authentication code. They never appear in graph state, prompts or logs.

Data protection:

- Data is encrypted at rest with managed keys, and in transit with TLS.
- The MVP runs on test data, so any capable model will do. Before real client data goes in, the model provider must sign a data processing agreement with zero-data-retention terms, and receive only the pages each step needs.
- Agent traces are self-hosted, or redacted before they leave your systems.
- Uploaded documents are treated as untrusted input, so text inside an invoice can never act as an instruction.
- Complete a data protection impact assessment before launch, because the system processes client financial data automatically.

Retention: GOV.UK says companies must keep records for 6 years from the end of the last financial year they relate to. They must keep them longer if a transaction spans more than one accounting period, an asset is expected to last more than 6 years, the Company Tax Return was filed late, or HMRC has started a compliance check.

- Each job gets a retention date of its period end plus 6 years. It's pushed back automatically when any of those four conditions applies.
- Filed packs, receipts and the audit log sit under object lock, so nobody can change or delete them early.
- Deletion runs only as a scheduled job after the retention date. It needs admin approval and is logged.
- LangGraph checkpoints and traces aren't the record of the work, so they can be deleted sooner ( 90 days after the job is filed).

## System architecture

The existing repo becomes four layers: the browser apps, the API, the agent worker and the engine modules. Three new services sit beside them, and only the filing service ever talks to HMRC and Companies House.

_[Diagram: system architecture · existing and new components — see the doc]_

Dashed boxes are outside services. The API streams the worker's progress events to the browser, so the activity feed updates live. The worker and API share the stores, but only the filing service can read the secrets manager.

## Tools to build

The agents need 27 tools, shared across five agents. Eleven of them wrap modules you already have, and 16 are new. Each agent gets only its own tools. Every tool reads the job and client IDs from the graph state, never from the model. The Phase column matches the build plan below.

| Tool | What it does | Used by | Access | Built from | Phase |
|---|---|---|---|---|---|
| `list_``rows_to_review` | Returns the next batch of rows that need review | Classify and post | Read | `ledger.py` | 1 |
| `lookup_account` | Searches the chart of accounts by name or code | Classify and post, fix, year-end | Read | `accounts.py` | 1 |
| `get_row` | Returns a row with the documents it could pay or was paid by, and the rows its issues relate to | Classify and post, fix | Read | `matching.py` | 1 |
| `update_row` | Changes a row's account, document type, Include, Link or Not the same, with its reasoning and confidence. Never an amount, date or VAT | Classify and post, fix, year-end | Write | `ledger``.py` | 1 |
| `log_exception` | Records an unresolved issue, the assumption made and the confidence | Classify and post, fix, year-end | Write | New | 1 |
| `request_client_document` | Asks the client for a missing document, linked to an exception. The system sends the email | Classify and post, fix, year-end | Write | New | 1 |
| `get_trial_balance` | Returns the latest trial balance snapshot | Fix, year-end | Read | `ledger.py` | 1 |
| `get_gate_results` | Returns each failed check with its details | Fix | Read | `checks.py`, `statements.py` | 1 |
| `get_``statement_checks` | Returns each bank statement's balance check and the rows where it breaks | Fix | Read | `statements.py` | 1 |
| `list_``row``s` | Lists the rows for an account or an upload | Fix, year-end | Read | `ledger.py` | 1 |
| `rever``t_row` | Puts back what the model read, with a reason | Fix | Write | `ledger``.py` | 1 |
| `get_prior_year` | Returns last year's closing balances and accounts | Year-end | Read | New | 2 |
| `list_documents` | Lists the job's documents by type and period | Year-end | Read | New, over `documents` | 2 |
| `get_fixed_asset_register` | Returns the client's fixed assets | Year-end | Read | New | 2 |
| `add_fixed_asset` | Adds an asset from a purchase invoice | Year-end | Write | New | 2 |
| `calculate_depreciation` | Works out the year's depreciation from the register and returns the journal to post | Year-end | Read | New | 2 |
| `propose_accrual` | Records an accrual or prepayment with its working, and posts its journal | Year-end | Write | New | 2 |
| `get_directors_loan_account` | Returns the director's loan account movements and balance | Year-end | Read | `ledger.py` | 2 |
| `calculate_ct_provision` | Runs the tax engine on the current figures and returns the provision journal | Year-end | Read | New | 2 |
| `get_accounts_draft` | Returns the draft accounts and their notes | Notes | Read | New | 2 |
| `draft_note` | Saves the wording of one note to the accounts | Notes | Write | New | 2 |
| `explain_figure` | Returns the journals and documents behind an account or a line in the accounts | Chat | Read | `ledger.py` | 2 |
| `find_document` | Finds a document by type, date or account | Chat | Read | New | 2 |
| `get_job_status` | Returns the stage, recent events and open document requests | Chat | Read | New | 2 |
| `list_exceptions` | Returns the exceptions and their status | Chat | Read | New | 2 |
| `get_deadlines` | Returns the client's filing and payment dates | Chat | Read | New | 2 |
| `create_change_request` | Saves a change request as a review note for sign-off | Chat | Write | New | 3 |

Some steps are deliberately plain code rather than tools, because no model should decide them. The graph calls these directly:

| Code step | Why it isn't a tool | Built from | Phase |
|---|---|---|---|
| `validate_upload` | Runs on every upload, with nothing to decide | `intake.py` | 1 |
| `extract_transactions` | Runs the vision model with no tools, and checks its output against a schema | `pipeline.py`, `extractor.py`, `model_client.py` | 1 |
| `run_quality_gate` | Pass or fail must be the same every time | `checks.py`, `statements.py` | 1 |
| `snapshot_trial_balance` | Runs at every stage boundary and writes the Excel export | `ledger.py`, `export.py` | 1 |
| `send_notification` | Sends fixed email templates, so a model never writes to clients | New | 1 |
| `check_scope` | Triage is a fixed rule list | New | 2 |
| `build_accounts`, `compute_corporation_tax`, `build_ct600` | Every number comes from tested code | New | 2 |
| `tag_ixbrl`, `validate_ixbrl` | Tagging and schema checks are deterministic | New | 2 |
| `build_pack` | Creates the manifest and the pack hash on approval | New | 3 |
| `submit_hmrc`, `poll_hmrc`, `submit_companies_house`, `poll_companies_house` | Reachable only after approval, and never given to a model | New | 4 |

## Build plan

Build in four phases, reusing the repo's stage-one code first. Each phase must pass its gate before the next one starts.

_[Diagram: build plan · 4 phases, 3 gates — see the doc]_

The test set is a group of past client jobs with known correct figures. In shadow mode, the agent prepares real jobs alongside your accountants, and nothing is filed. Live filing starts only after test submissions to HMRC and Companies House are accepted. Once you approve this spec, the next document is a task-by-task implementation plan for phase 1.

## Open decisions

All seven are decided or deferred for the MVP, so the implementation plan can be written next.

- [x] Exceptions: decided. The agent asks the client for missing documents and also flags the assumption it made.
- [x] Final review: planned in its own tab. It builds the link and code, behind an interface an e-signature provider could replace lat er.
- [x] Segregation of duties: decided for the MVP. One accountant is both preparer and reviewer.
- [x] Client uploads: decided. The MVP includes a secure upload link for requested documents.
- [x] Hosting: MongoDB Atlas in any region for the MVP, moving to a UK region for the final version. The object storage provider is still to pick.
- [x] Model provider: decided for the MVP. Any capable model on test data, with zero-data-retention terms required before real data.
- [x] Defaults: confirm ed. Deadline reminders at 60, 30 and 14 days, document reminders after 3 and 7 day s, and 90-day checkpoint retention.

## Sources

- Running a limited company: company and accounting records , GOV.UK

