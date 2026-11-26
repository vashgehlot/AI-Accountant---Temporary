# Background AI review, and the fixes from the accountant test: design

2026-11-04 · branch base `ai-accountant-demo` (d93ae44) · follows
[the accountant test findings](../../2026-11-04-accountant-test-findings.md) (F1–F11, N1–N9 below refer to it)

## Why

An accountant mostly works by **uploading files and editing rows**, not by chatting. Today the AI only works
inside a chat. The moment someone uploads a receipt or changes a row outside the chat, the AI's work goes stale:
- a question it asked stays open after the answer has arrived;
- Suspense keeps an item that is now documented;
- the site shows two trial balances that disagree.

The same £86.40 purchase is booked as a cost outside the chat and held in Suspense inside it. The 4 November
test also found places where the AI states something untrue (the bank "agrees" while it is £3,200 out) or applies
the wrong UK rule (CIS).

**The idea (the user's):** whenever something changes that could change the books, the AI checks it in the
background, fixes what it can, and shows the accountant what it decided, with the ability to undo it.

**Success:**
- Upload the Ashdown files through Documents, without opening a chat. A minute later the client shows what the AI
  sorted and what it needs, and the one trial balance is right.
- Upload the missing receipt the same way. The question closes and Suspense clears on its own.
- Nothing the AI says contradicts the numbers.

## The rule behind the background review

The chat's rule carries over: **where a document supports the answer, act and say why; where only a guess would,
ask.** Three rules are added for working unattended:

1. **A person's change wins.** The AI never changes a row a person has edited, linked, unlinked or accepted, and
   never redoes a change a person has undone. If it disagrees, it asks.
2. **Everything it does is visible and reversible.** Every change it makes is a decision in the existing log, with
   its evidence, shown in the client's AI review list with an Undo button.
3. **Closed is closed.** It never touches a closed year. (When VAT returns arrive, a filed VAT quarter is treated
   the same way.)

## The parts, in build order

Each phase can ship on its own. Phase 1 is the foundation the background review needs; phases 3 and 4 make the
AI's judgement right.

### Phase 1. One set of books, the same rules everywhere, and a record of changes (F3, F4, F9, N8, N9)

**One set of books (N8).**
- After **every** change that can move the numbers, the deterministic part of a review runs at once, without the
  model:
  - normalise and check the rows;
  - match;
  - refresh the rule questions (`questions.refresh`);
  - close questions the change has answered;
  - post the ledger (`ledger_book.post`, reversals plus new lines).
- So the posted ledger is always up to date, and "Posted ledger: N changes not posted" goes away.
- **My call:**
  - The Trial balance section, the Overview's summary, the Excel export and Close year all read the **posted**
    ledger.
  - The rows stay the working papers.
  - Where the rows' trial balance and the posted one would differ (Suspense, excluded rows), the posted one is
    the books.
  - If posting is blocked (an error-level row), the site says why, as the posted trial balance does now.

**The same rules everywhere (F3).**
- The document rules (`evidence_rules.document_rule`: £50 and £250) are shown as **row issues** in Transactions,
  as well as being applied when posting.
- A bank purchase of £50 or more with no document says "Held in Suspense: needs its receipt or invoice" wherever
  it is seen.

**A document that answers a question closes it (F4).** When a new document is matched to a row that has an open
`receipt_or_invoice` or `vat_invoice` question, the deterministic step:
- checks it the way the chat's "Upload invoice" answer does (amount, payee, date);
- closes the question with the document as its answer;
- reposts, so the amount leaves Suspense.

If the document doesn't fit, the question stays open and gains a note saying why.

**A record of changes (N9).**
- Add a `changes` collection, append-only. Each entry has:
  - client, year;
  - when;
  - who: `user`, `agent:<model>`, `rules` or `import`;
  - what kind: upload read, upload removed, row edited, row added, row removed, link, include, apart from,
    client setting changed, opening balances changed, question answered, decision undone, year reopened;
  - the rows and upload it touched;
  - before and after;
  - a one-line summary.
- Every route that changes a client's data writes one entry. Agent decisions keep their own log and also write a
  change.
- The agent gets a read-only tool, `list_changes(since)`, so it can answer "what has changed since the last
  review?".

### Phase 2. The background review (N1)

**When it runs.**
- These changes **trigger** a review:
  - an upload finishes reading;
  - an upload is removed or its bank account changed;
  - a row is edited, added, removed, linked or unlinked;
  - a client's VAT registration, business type or bank accounts change;
  - opening balances change;
  - a question is answered;
  - a decision is undone;
  - a year is reopened.
- A change to a description alone doesn't trigger one.
- **Phase 1's deterministic step runs at once** for every change.
- **The AI step waits** until the client is quiet: no file of the client still being read, and no new change for
  a short while (the builder picks the wait; about 20 seconds). Thirty files dropped at once therefore cause one
  review, not thirty.
- If a change arrives during a review, one more review runs after it.

**What it looks at.**
- It does not re-review the whole year. It looks at:
  - the changes since the last review (from `changes`);
  - the rows they touched and the rows linked to those;
  - any issue on the year that no review has looked at yet.
- The first review of a year looks at everything.
- **Changes the AI made itself** (in a chat or a background review) never trigger an AI review; they get only the
  deterministic step. **My call.**
- **Files read in a chat** count as reviewed by that chat turn. A person's change made outside the chat still
  triggers a background review.

**What it may do.**
- It uses the chat's tools and rules: R1–R5 with the service's evidence checks, plus `ask`, plus the new actions
  in phase 3.
- **The user's call:** it fixes things itself and shows what it decided. It doesn't wait for approval.
- **My call:** each client has a setting, **AI review: Automatic** (the default), **Suggest only** (it records
  what it would do, and a person applies it with one click) or **Off**.
- **Closing its own questions (my call).** The deterministic step closes rule questions (date, receipt, VAT
  invoice, statement, payout report). The AI's own questions (kind `other`, such as "Is Netflix personal?") get a
  new action, `close_question(question_id, evidence)`:
  - The service allows it only when a person's change since the question was asked touches the question's rows
    (for example, the row was recoded to the director's loan), or a document now supports the answer.
  - It records the change it relied on.
  - It shows in AI review with Undo, which reopens the question.

**How it runs.**
- A headless agent run: the same agent, prompt and tools as the chat, with no chat thread.
- Its decisions carry `actor: agent:<model>` and a new `trigger: background` (chat decisions get `trigger:
  chat`).
- **Locking (my call).** The same pattern as chats today:
  - the agent's thinking holds no lock, so a chat, an edit or an upload is never kept waiting behind a review;
  - only the writes take the client's lock (`ClientLocks`): each decision, and the deterministic step's refresh and
    post;
  - each decision is checked again when it is written (R0: the row is unchanged since it was read), so a person's
    edit made part-way through a review wins, and the decision is refused and recorded as such.
- At most **one background review per client** at a time. A chat turn may run alongside it, as two chats can now.
- It obeys the existing limits: 30 model calls and 80 tool calls per run.
- **My call:** a per-client daily limit of AI review runs (default 20). When it is reached, the deterministic
  step still runs and the client shows "AI review paused for today: limit reached".

**Undo.**
- Undo writes a reversing decision (the existing `reverses` field) and reposts.
- The undone decision's idempotency key is recorded as **rejected by a person**, so no review makes that same
  change again. A changed version of it can still be asked about.

**Where the accountant sees it.**
- **A new "AI review" section** in the client's side menu, for the year picked. It lists the runs, newest first,
  for example: "Today 10:42, after 3 files were added: sorted 2, asked 1".
  - Each run opens to show its decision cards (the chat's cards: rule, before and after, evidence quote with a
    link to the file, a link to the row) with **Undo**.
  - It also shows its questions, with the chat's answer controls.
  - A run that changed nothing says so in one line.
- **On the Overview:** "AI review: last run 10:42. 2 changes you haven't looked at" beside "N things need you".
- **On the client list:** a small count of AI changes not yet looked at. Opening the AI review section marks them
  seen.
- **In Transactions:** a row the AI changed already has the Agent badge. That badge now also says whether the
  change came from a chat or a background review.
- **In the chat:** a new chat on the client mentions what background reviews did since the last chat, as it now
  mentions open items.

### Phase 3. Getting the accounting right (F1, F2, F5, F6, F7, F8)

**F1. Missing paperwork (N2), and never claiming the bank agrees when it doesn't.**
- **A deterministic paperwork check** per year. For each bank account it finds:
  - **Gaps in the statement chain:** the first statement's opening balance against the books at that date, and
    each statement's opening against the previous closing.
  - **Months with no statement lines** between the start of the year and the latest statement.
  - **Accounts with no statement at all.**
- It also lists bank purchases of £50 or more with no document (from the document rules) and months with PAYE
  paid but no payroll report (from the existing `no_payroll` check).
- **The Overview** shows a **Missing paperwork** list, for example: "Starling current: no statements for April to
  September 2026. October opens at £8,200.00; the books have £5,000.00."
- **Each missing statement** also becomes a question (a new kind, `statement`), answered by uploading it.
- **A new agent tool, `bank_position`,** returns for each account:
  - the books' balance, the latest statement balance, and the difference;
  - the paperwork gaps;
  - two separate flags:
    - `statement_consistent`: the statement's lines reach its own printed balances; this is what was "agreeing" in
      F1;
    - `reconciled`: the books equal the statement, so the difference is £0.00.
- The prompt forbids saying a bank account agrees with, matches or is reconciled to the books unless `reconciled`
  is true. "The statement adds up" is allowed when `statement_consistent` is true.
- **A deterministic check on the final reply:** if the reply claims agreement for an account whose flag is
  false, the reply is replaced by the structured summary. (**My call:** a narrow check on those words, not a
  general fact-checker.)

**F2. CIS.**
- **Two new accounts** in the chart (the builder picks codes that fit the chart):
  - **CIS deducted** (asset): tax customers have taken off the client's sales invoices;
  - **CIS payable** (liability): tax the client has taken off its own subcontractors.
- **The reader:**
  - captures a CIS deduction printed on a sales invoice (labour, materials, rate and amount);
  - marks a domestic reverse charge (`vat_treatment` `reverse_charge`; no output VAT).
- **Posting:** when a payment against such an invoice is short by exactly its printed CIS deduction, the shortfall
  goes to CIS deducted, not Debtors. There is no `part_payment` issue, and the invoice shows as paid.
- **The purchases side:** a subcontractor's invoice with CIS taken off books the deduction to CIS payable.
- **The agent's prompt** gets a short, correct account of CIS:
  - a limited company sets CIS deducted against its PAYE and NI;
  - a sole trader or partnership claims it on the tax return.
- A "CIS deducted" balance at the year end is a pointer for the accountant, not something the AI clears.

**F5. Accept a warning with a reason (N3).**
- **The accountant:** a warning (never an error) on a row can be **accepted** with a short reason. It then shows
  greyed as "Accepted: \<reason\> (\<who\>, \<date\>)", and stops counting towards "rows to review" and the
  review bar. Accepting is a change (Phase 1) and can be undone.
- **The AI:** gets the same action, `accept_issue(row_id, code, reason, evidence)`, held to the evidence rule. It
  may accept a warning only by quoting the document text that shows the warning is wrong ("Insurance is exempt
  from VAT"). It appears in AI review with Undo.
- **Errors** can't be accepted by anyone. They're fixed.
- An accepted warning comes back if the row's amount, VAT or account changes.
- **Book without a receipt (decided by the user, 4 Nov).**
  - A purchase held in Suspense for a missing receipt or invoice can be booked by **the accountant only**, never
    the AI, with **Book without a receipt** and a reason ("receipt lost; client confirms it was hand tools").
  - The row is then posted to its account as a cost with **no VAT reclaimed**, and its question closes as
    "Booked without a receipt: \<reason\>".
  - It is a change (Phase 1), shown on the row, and Undo puts the row back in Suspense.
  - It is offered on the row in Transactions and on the question's card, next to "I don't have it".

**F6. Figures read against figures worked out.**
- **The reader's schema** marks each amount (gross, VAT, total) as **printed** or **worked out**.
- **For documents with a text layer** (PDF text, CSV, Excel, pasted text), a deterministic check overrides the
  model: an amount whose figure doesn't appear in the text is "worked out".
- **Consequences of "worked out":**
  - an issue says "worked out", never "shows";
  - VAT that was worked out can't be reclaimed (the simplified-invoice rule needs it shown);
  - a row whose gross was worked out gets a warning: "Total not printed on the receipt: £86.40 taken from \<the
    bank line or the sum\>".

**F7. Payment processor payouts.**
- **Recognise payouts** from Stripe, PayPal, Square, SumUp, Zettle, Shopify Payments, GoCardless, Amazon and eBay
  by counterparty (the builder keeps the list in one place). Book them to a new **payment processor clearing**
  account, not to Sales.
- **Ask for the payout report** for that payout (a question of kind `payout_report`).
- **When the report is uploaded,** the reader books:
  - the gross sales (with their VAT, from the report or the client's invoices);
  - the processor's fees (VAT-exempt for Stripe and PayPal);
  - the refunds.
- These go against the clearing account, which then clears to nil.
- **Charges that pay the client's own invoices (my call).** Each charge on the report is first matched to an
  unpaid sales invoice, with the existing matching (amount, customer, dates).
  - A matched charge clears Debtors, so the sale isn't counted twice.
  - Only unmatched charges are booked as sales.
- **VAT on unmatched sales (my call).** It comes from the report when the report shows it.
  - Otherwise the AI asks once for the rate the client charges on those sales, and remembers the answer as a
    coding rule (Phase 4) for later payouts.
  - It never assumes 20%.

**F8. Noticing what an accountant would.** Deterministic pointers, shown as warnings and visible to the agent:
- **Possibly personal:** spending with consumer subscriptions and streaming services (a short list kept in one
  place) on a company's account. The suggested home is the director's loan (or drawings for others). The agent
  asks; it doesn't move them itself.
- **Runs past the year end:** a document with a printed service period that ends after the year end. The warning
  says how much would be prepaid at the year end (by days). This is a pointer only: no journal is posted
  (journals are out of scope).
- **Director's loan overdrawn:** when 2250 has a debit balance, the Overview warns "Director's loan overdrawn by
  £X". It notes that s455 tax applies if it is still overdrawn nine months after the year end.

### Phase 4. Client queries and remembered corrections (N4, N5)

**Queries for the client (N4).**
- **A "Queries" view** on the client lists every open question and missing-paperwork item, worded for the client
  ("Please send the Stripe payout report for 15 October 2026").
- The accountant can tick which to include, and **copy them as text or download them as a PDF** to send however
  they send things now. **My call:** the site doesn't send email in this round.
- Answers are entered as now (the question's own controls), and each answer is a change.

**Remembered corrections (N5).**
- When a person changes a row's account, the site offers "Always code \<payee\> to \<account\> for this client?".
- **Yes** saves a **coding rule**: the normalised payee, the account and the VAT treatment. The site also offers
  to apply the rule to this year's other rows from that payee.
- **New rows** from that payee get the rule's account after reading, before posting. They show "Coded by your
  rule (set 4 Nov)".
- **The AI** treats a rule as a person's change: it never overrides it.
- **A "Coding rules"** list on the client (in Client details) lets the accountant edit or delete rules.

### Phase 5. Polish (F10, F11)

**F10. Chat replies.**
- Only the text after the agent's last tool call is shown as the reply. Text written between tool calls becomes
  step lines (or is dropped).
- The summary's numbers come from the structured result (Suspense, open questions), so they can't contradict it.

**F11. Statements without a bank account.**
- A statement read without its bank account is **kept**, with the status "Choose the bank account". Choosing one
  saves its rows without reading the file again.

## Goals

- The Ashdown test (findings, section 5) gives:
  - through Documents alone, the same books as through the chat;
  - the hand-worked expected figures;
  - CIS on CIS deducted;
  - Stripe in clearing;
  - Screwfix out of Suspense once its receipt is in;
  - a Missing paperwork list naming April to September.
- Every change the AI makes in the background is visible within a minute and can be undone.
- One trial balance on the site.

## Non-goals

- Logins, roles or several users (the `user` actor stays a single person).
- Sending emails to clients; a client portal.
- VAT returns, MTD, P&L and balance sheet, journals, depreciation, corporation tax.
- Bank feeds.
- Payroll journals beyond what exists.

## Anti-goals (a failure even if it works)

- The AI changes a row a person changed, or repeats a change a person undid.
- An AI change that isn't shown in AI review, or that can't be undone.
- A background review that spends without limit, or runs once per file in a batch.
- A flood of questions: one question per missing statement month **range**, not per month; the existing "asking
  about what the evidence settles" anti-goal still holds.
- Any reply or issue that states a figure the documents or tools don't support. That includes "agrees" for a bank
  account that doesn't, and "shows" for a figure that was worked out.
- Touching a closed year.

## Constraints

- **The stack:** FastAPI, Next.js, MongoDB, LangChain `create_agent` and the existing agent, tools, middleware
  and decisions log, at the pinned versions.
- **One model, `OPENROUTER_MODEL`** (`qwen/qwen3.8-27b`), reads files and runs the agent.
- **The services decide, not the model:** every new action (`accept_issue`, the CIS and payout bookings) is
  checked by a deterministic service, as R1–R5 are.
- **Ask before spending OpenRouter credit** on real-model tests.
- Plain English in the site and the docs, as now.

## Testing

- **The Ashdown case:** put the Ashdown documents into `eval/agent_cases/ashdown/`. Hand-work the expected
  figures in its `notes.md` before any code runs on them (as Northbridge did):
  - `expected_trial_balance_*.json`;
  - expected decisions;
  - expected questions;
  - the expected missing-paperwork list.
- **Deterministic tests** for each new rule:
  - the paperwork check;
  - CIS posting;
  - the payout clearing;
  - printed and worked-out figures;
  - accept with a reason;
  - coding rules;
  - questions closed by a document;
  - auto-posting after each kind of change;
  - the change record.
- **The background review with `FakeModel`:**
  - the trigger and the wait;
  - one run for a batch;
  - the lock with a chat;
  - a person's change wins;
  - an undone change isn't repeated;
  - the daily limit;
  - Suggest only and Off.
- **With the real model** (ask first): Northbridge and Ashdown ×3, through Documents only and through the chat.
  The trial balances must match to the penny.

## Left to the builder

- The wait before an AI review, and how the queue of reviews is kept (a restart mustn't lose a pending review).
- The shapes of `changes`, coding rules and accepted warnings.
- Codes for the new accounts, within the chart's conventions.
- The lists of payment processors and personal-looking payees.
- The AI review section's layout, within the description above.
- How the prompt is changed, within the rules above.

## Decided by you

- The background review fixes things itself and shows what it decided, with the ability to undo it.
- A lost receipt over £50 can be booked as a cost with no VAT by the accountant, with a reason. The AI can't do
  this.
- Everything else in the design, including the calls below, was approved on 4 Nov.

## My calls (please check)

- AI review defaults to **Automatic**, with Suggest only and Off per client, as the user described ("fix it, and
  show what it decided, with the ability to fix it").
- The posted ledger becomes the one set of books for every page and for Close year.
- A daily limit of 20 AI review runs per client.
- A person's change wins, and an undone AI change is never repeated.
- The AI may accept a warning only by quoting the document that shows it is wrong. Errors can't be accepted.
- Personal-looking spending is asked about, not moved.
- The prepayment pointer is a warning only; journals stay out of scope.
- Queries are copied or downloaded, not emailed.
- The build order is phases 1 to 5, as above.
- **Locking:**
  - the review's thinking takes no lock, and only its writes do;
  - each decision is re-checked when written, so a person's edit made part-way through a review wins;
  - there is one background review per client at a time.
- **What triggers an AI review:**
  - the AI's own changes never do;
  - files read in a chat count as reviewed by that chat.
- **Closing its own questions:** the AI can close a question it asked once a person's change or a document
  answers it, with Undo.
- **Payout reports:**
  - charges are matched to the client's unpaid sales invoices first, so sales aren't counted twice;
  - the VAT rate on unmatched sales is asked once, never assumed.

## Builder notes

- The Ashdown documents and the 4 November test run are kept in `eval/agent_cases/ashdown/` (`documents/`,
  `answers/`, `test-run-2026-11-04/`). The expected figures still have to be worked by hand.
- The "Held in Suspense: needs its receipt or invoice" issue must be a **warning**, not an error. An error-level
  row blocks posting for the whole year (`posting.matched_rows`).
