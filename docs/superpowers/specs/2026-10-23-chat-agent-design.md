# AI Accountant: chat agent design

2026-10-23 · replaces the "Start job" interface in `2026-10-21-interaction-and-storage-design.md`

## Why

The accountant wants to work through a chat, as they would with Claude or ChatGPT, rather than pressing "Start job" and watching a panel. They ask the agent to do accounting work or to answer questions about a client. The agent does the work, and the client's own pages (documents, transactions, trial balance) show the result.

This reverses one decision in the 21 Oct spec. That spec rejected a chat-first design because numbers are hard to check in a conversation. This design keeps the client's pages for checking numbers, and the chat is how work gets asked for and explained. So that concern doesn't apply.

**Keep it simple.** This is an MVP on test data. When there are two ways to build something, pick the simpler one.

## What the accountant sees

### Login
- The accountant logs in with an email and a password, and everything else sits behind the login.
- There is one account for now; other staff come later.
- The client's upload page for requested documents (`/requests/[token]`) stays outside the login. It shows only the documents asked for.

### Main menu
The menu has two items:
- **Clients**
- **Chat**

### Clients
- The list of clients, as today.
- Opening a client shows that client's own space. It has a side menu of the client's sections:
  - **Overview:** the client's details and year, plus a short status. The status gives rows to review, open requests, whether the trial balance is ready, and anything the checks flagged.
  - **Documents:** uploads, adding documents, and the documents being read. This is today's `AddDocuments` and `UploadsList`.
  - **Transactions:** today's `TransactionsTable`. A person can still edit rows here.
  - **Requests to client:** every document request for this client and its status. The statuses are "waiting for your OK", "sent", "received" and "replaced".
  - **Trial balance:** today's `TrialBalancePanel`, with its Excel export.
- Each client has **one year**, stored on the client: a period start and end, entered when the client is created and editable. There is no year picker in this version.

### Chat
- **A Chat button on every page** opens the chat in a panel beside the page. The panel knows which client and section is open, so a chat opened inside Acme starts on Acme.
- **Chat in the main menu** opens the same chat full page, like Claude:
  - a list of past chats down the side;
  - a "New chat" button;
  - the conversation in the middle.
- **Replies appear as they're written.**
- **Big tasks show progress as they run**, for example "Reading 12 documents…", "Coding 84 lines…", "Running the checks…". A **Stop** button stops the work.
- **Each answer is labelled** with the client it is about, for example "Acme Ltd · year to 31 Mar 2026". It also links to the section where its changes can be seen.
- **The page beside the chat refreshes** when the agent changes something. Rows changed by the latest answer are highlighted.
- **Documents can be dropped into the chat.** They go into the current client's Documents and are read as usual.

## What the chat can do

### Switch clients
- The chat can work on any client.
- The accountant names the client ("open Acme", "now Bright Cafe"), and the chat switches. The label on each answer shows which client is current.
- One conversation can move between clients.

### Answer questions about the client
These are answered straight away, with nothing changed:
- its figures, rows and trial balance;
- why a figure is what it is;
- its documents and its requests and their status;
- what the checks flagged and what assumptions the agent made.

### Do the accounting work
This version covers the tasks the branch already has:
- coding and correcting rows (account, document type, Include, Link, Not the same);
- linking payments to what they pay;
- recording exceptions and assumptions;
- asking the client for missing documents;
- building the trial balance, running the quality checks and fixing what they flag;
- saving trial balance snapshots with their Excel workbook.

"Prepare Acme's books" runs the whole preparation that "Start job" runs today:
1. read the documents;
2. code the rows;
3. run the checks;
4. fix what they flag (up to 3 rounds);
5. record exceptions;
6. draft requests to the client;
7. save the snapshot.

## When it acts and when it asks first

The accountant decided these three rules:

1. **New work: it does the work first, then asks the accountant to check.**
   - This applies when the accountant asks it to do something new. Examples: "code the March bank lines", "prepare Acme's books for the year".
   - It does the work and saves as it goes, with no approval along the way.
   - Then it says what it did and asks: "Please check, and let me know if you'd like to change anything."
2. **A change to something already done: it asks first.**
   - This applies when the accountant asks it to change existing work. Example: "BT should be Telephone".
   - It shows the exact change and waits for an OK before saving: "Change BT Business, £58.80 on 5 Mar, from 7500 Office costs to 7502 Telephone?" with **Change it** and **Leave it** buttons.
   - The accountant can also reply in words to adjust the change.
3. **Sending to anyone, or filing: it always asks first.**
   - Document requests are drafted as "waiting for your OK".
   - The chat shows them in one card: who the email goes to, the documents and periods, and the reasons. It has **Send** and **Don't send** buttons.
   - All requests from one task go in one email, as today.
   - Nothing is emailed without the OK.
   - Filing is in a later project, and the same rule applies to it.

Two further rules for new work are my calls:

- **It never overwrites a person's own choice without asking.** During new work, the agent may want to change a row a person set by hand, such as an account the accountant picked in the Transactions table. That counts as a change to something already done, so it is listed in the "please check" message as a proposed change with buttons, not saved.
- **The "please check" message names anything that moved rows on or off the books.** That covers rows taken off the trial balance (by a document type change or Include) and rows added to it. The final review of the previous branch found that the agent could pass the checks this way without anyone seeing it.

## What carries over and what goes

The build starts from branch `accounting-agent` at `947ae1b` (Phase 1).

### Carries over
- **The agent's tools:** row tools, account lookup, exceptions, document requests, trial balance and check results.
- **The records:** the hash-chained audit log, the exceptions and document request records, and the trial balance snapshots.
- **The preparation run:** the LangGraph run with its checkpoints, quality gate, fix loop and limits.
- **The client upload page** and its reminders after 3 and 7 days.
- **The eval set** in `eval/jobs/` and the Gate 1 runner.

### Changes
- **The preparation run is started from the chat.** It is no longer started by a button. Its progress shows in the chat.
- **The run's request step drafts requests instead of sending them.** They are sent when the accountant approves them in the chat. Reminders count from when the email is actually sent.
- **Exceptions and requests are shown per client, not per job.** The Requests to client section and the chat show all of a client's open items, whichever run made them. This fixes the previous review's finding I1, where a new run hid the earlier run's open items.

### Goes
- The "Start job" button, `JobPanel` and the job panel's polling.
- The code the previous branch's final review listed as unused. That review is in the transcript and is summarised in the plan.

### Fixes the previous branch's final review asked for, still relevant to code that carries over
- **Shutdown** stops running work rather than waiting for it to finish (finding I3).
- **Importing `server.py`** no longer connects to the database (I4).
- **`.env.example`** lists every setting. A blank number setting falls back to its default (I5).
- **The model call has a timeout** (M3).
- **Every write route** checks the `X-LedgerSync` header as well as the login (M4).
- **Two findings are settled by this design.** The login closes the open-site finding (I6). The accountant now sees every email before it is sent, which handles the finding about document text steering emails (I7). The existing filter on links, emails and domains stays.

## Goals
- The accountant can do the whole Phase 1 job through the chat, from any page:
  - pick a client;
  - prepare the books;
  - check and correct the work;
  - approve the document requests;
  - see the trial balance.
- They can switch clients in one conversation.
- The three "acts or asks" rules hold every time.
- Every change the agent makes, and every approval, goes in the audit log, with who approved.

## Non-goals for this version
- A year picker, or more than one year per client.
- More than one user, roles, or permissions. The records note who did what, so these can be added later.
- The year-end tasks: last year's figures, fixed assets, depreciation, accruals, the director's loan account, corporation tax, and accounts and notes.
- Sign-off and filing.
- A separate chat inside each job.
- Emails to the accountant.

## Anti-goals
- **Over-building.** This is an MVP. The accountant asked to keep it simple, so no extra features, settings or abstractions.
- **The agent emailing a client, or filing anything, without an explicit OK.**
- **The agent changing an amount, a date, or VAT that a document shows.**

## Constraints
These are kept from Phase 1:
- Money is `Decimal` in Python and an exact decimal string in MongoDB.
- The agent can change only a row's account, document type, Include, Link and Not the same.
- **The agent never writes to the client.** It supplies the document type, period and reason, and the system fills a fixed email template.
- **Every model call runs with the model-call and tool-call limit middlewares.** The fix loop runs at most 3 rounds.
- **Every agent write and every approval is appended to the hash-chained audit log.**
- **A tool acts on the conversation's current client.** It gets the client ID from the conversation, not from the model's tool arguments. The current client changes only through the switch step, and every answer shows which client is current.
- **The models are the existing OpenRouter set-up.** The agent's model is `LEDGERSYNC_AGENT_MODEL`. Any OpenRouter model that supports tool calling will do.
- **The stack stays the same:** FastAPI, Next.js, MongoDB Atlas and LangGraph/LangChain at the versions pinned on the branch.

## Testing and keys
- **Automated tests use a fake model** and the throwaway test database. They need no key.
- **One real-model check runs at the end** with a real model on the eval set. It needs `LEDGERSYNC_AGENT_MODEL` set and spends OpenRouter credit, so **ask the accountant before running it**. They asked to be told whenever a key is needed for testing.

## Decided by the accountant
- A chat agent like Claude or ChatGPT, in the main menu under Clients, that can be opened from any page.
- Each client keeps its own sections.
- The chat can pick up any client and switch between clients.
- It answers questions about the client and does all the planned accounting tasks, added over time.
- **The three rules:**
  - new work is done first, then checked;
  - a change to something already done is verified first;
  - sending or filing is always verified first.
- One login for now, by email and password, with other staff later.
- Keep it simple. Ask before using a key for testing.

## My calls (please check)
- **No year picker for now.** Each client has one year, stored on the client.
- **The sections:** Overview, Documents, Transactions, Requests to client, Trial balance.
- **The chat panel sits beside the page.** The full-page chat is the same conversation.
- **Past chats are saved and listed**, like Claude's.
- **During new work, the agent asks before overwriting a person's own choice.**
- **The "please check" message names rows moved on or off the books.**
- **Big tasks show live progress and a Stop button.**
- **Documents can be dropped into the chat.**
- **The preparation run is reused as the engine behind "prepare the books".**
- **Requests show per client, not per job.**

## Left to the builder
- How replies stream to the browser, for example server-sent events or polling.
- How chats are stored, for example a `chats` collection or the LangGraph checkpointer.
- How the agent tells new work from a change to existing work. It might use two kinds of write tool, apply-now and propose, or a single proposal step. Whatever is chosen, the three rules above must hold, and they must be tested.
- How the login is set up: for example, one account from `.env` with a hashed password and a signed session cookie.
- How the page beside the chat learns what changed.
- How to split today's client page into the section routes.

## Later projects, in order
1. **This design:** the chat, over the tasks the branch already has.
2. **Year-end tasks through the chat:** last year's figures, fixed assets and depreciation, accruals and prepayments, the director's loan account, the corporation tax provision, and draft accounts and notes. These are Phase 2 of the 21 Oct spec.
3. **Sign-off, then filing** with HMRC and Companies House. Filing always asks first.
