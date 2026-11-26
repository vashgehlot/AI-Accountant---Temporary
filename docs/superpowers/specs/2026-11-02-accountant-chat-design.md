# Accountant chat: design

2026-11-02 · branch base `accounting-site` (c592bd4) · for the directors' demo of Super Accountant

This replaces the 2 Nov "AI accountant demo" plan's agent behaviour. Where it conflicts with `2026-10-23-chat-agent-design.md`, this document wins: a chat belongs to one client here, and the agent decides and asks by the rules below.

## Why

When someone leaves the directors' demo, they should remember that **the chat behaves like an accountant**. It knows what to do in each situation. Where it can't know, it asks the person in front of it, the way an accountant asks a client.

The earlier plan left anything unresolved as a flag card for someone to deal with later. That reads as a tool tidying rows. This design has the agent use judgement: it acts where a real document supports the answer, and asks where only a guess would.

## The rule behind every decision

**Where real evidence supports the answer, the agent acts and says why. Where only a guess would, it asks.**

- **Real evidence** means a document's own contents: an invoice, a receipt, payroll, a bank statement line, an expenses sheet line. The ranking stays as before: invoice, receipt or payroll first, then the bank line, then the expenses sheet, a spreadsheet or a hand entry.
- **Not evidence:** a file name (for example `IMG_20261014.png`), when a file was uploaded, or the model's own guess.

## What the agent does in each situation

| Situation | What the agent does | Asks you? |
|---|---|---|
| The same transaction entered more than once (receipt and expenses sheet, a receipt uploaded twice, receipt and bank line booked as two costs) | Keeps the entry from the best source, removes the rest from the books, and says which it kept and why | No |
| Two sources disagree on the amount (the invoice says £30.22, the sheet says £27.50) | Uses the better-ranked source | No |
| One receipt mixes VAT rates (20% and 0% items, one VAT total) | Splits it into parts so that VAT is claimed only on the standard-rated part. The parts must add up exactly to the receipt, and the VAT must match the printed VAT | No |
| VAT printed on the document but missing from the entry | Takes the VAT from the document | No |
| Date missing, and a bank line matches it (same amount, same payee) | Uses the bank line's date and says so: "dated 14 Oct from the Barclays payment of £6.50" | No |
| Date missing, and nothing matches it except the file name | Asks for the date | **Yes** |
| A purchase **under £50** with no receipt or invoice | Books it from the bank line. No VAT is reclaimed | No |
| A purchase of **£50 or more** with no receipt or invoice | Asks for the receipt or invoice. Until it arrives, the payment is posted to **Suspense (9998)** and marked **Documentation required** | **Yes** |
| A purchase **over £250** with only a receipt | Asks for the full VAT invoice. Until it arrives, the payment is held in Suspense as Documentation required | **Yes** |
| The evidence doesn't settle it (anything not covered above) | Asks a specific question and says what would settle it | **Yes** |

### The document rules, in one place (decided by you)

| Gross amount | Document needed to book it | VAT reclaimed when |
|---|---|---|
| Under £50 | None: the bank line is enough | A receipt with the supplier's VAT number and the VAT shown is held. Otherwise none |
| £50 to £250 | A receipt or an invoice | The receipt shows the supplier's VAT number and the VAT (a **simplified VAT invoice**), or there is a full VAT invoice |
| Over £250 | A **full VAT invoice** | The full VAT invoice shows it |

- £50.00 needs a document. £250.00 can still use a simplified VAT invoice (HMRC's limit is "up to £250").
- A receipt without the supplier's VAT number supports the cost but not a VAT reclaim.
- The Costco demo receipt is a simplified VAT invoice, so the mixed-VAT split reclaims VAT on the standard-rated part.

### Which payments the document rules cover (my call)

They apply only to **purchases and expenses**. These are exempt, because other records back them up:
- payroll, HMRC payments (PAYE, VAT, corporation tax), loan repayments, transfers between the client's own accounts, director's loan and drawings, and card pay-offs;
- money coming in.

Without this, a real bank statement would flood Suspense with questions.

## What you see

The chosen layout is **"does what it can, then asks everything at once"** (option A in the mockups).

1. **Start.** You click New chat, pick a client, drop in documents and ask for a review. Chips on each file show it being read.
2. **While it works.** A status line appears at once. A collapsible list shows the steps ("Read costco-receipt.txt", "Checked the Barclays lines for a matching date"). A Stop button is shown.
3. **The summary**, all in one reply when it has finished:
   - **Sorted:** a line for each thing it fixed on its own, with why and the source it used. Each line opens a card with the before and after values, the evidence quote with a link to the original file, and a link to the row in Transactions.
   - **Needs you:** one card per question, each with its own answer control: a date picker, an Upload invoice button, a choice, or a free-text box. Each card says why it matters ("Over £50, so I need the invoice. Held in Suspense until then.").
   - **Posted:** the trial balance after posting, balanced or not, with Suspense items labelled ("needs invoice"), and a link to the full trial balance.
4. **Posting happens straight away**, with no sign-off step. Every entry can be reversed, so nothing it posts is final.

## Answering the questions

- You can answer in any order, all at once or one at a time.
- Each answer goes back to the agent. It finishes that item, re-posts only what changed (as reversals plus new entries), and replies with an updated short summary and trial balance.
- **Uploading the missing invoice:** the agent reads it and checks it against the payment (amount, payee, date). If it fits, the agent moves the amount out of Suspense into the right cost account with the invoice's VAT. If it doesn't fit, it says why and the item stays open.
- **"I don't have it"** on an invoice of £50 or more: the payment stays in Suspense as Documentation required, and the card closes as "waiting for the invoice".
- **"Not sure"** on a date: the item stays open, and the agent doesn't pick a date.
- A date you give must fall within the client's books. If not, the agent says so and asks again.

## Open items outlive the chat

- Unanswered questions and Documentation required items stay on the **client**, not on the chat.
- The client's Overview shows "N things need you", with a list.
- A new chat on that client opens by mentioning them. It has no memory of the earlier conversation, but it knows those items are open.
- An invoice uploaded in any chat on that client is matched against the open Documentation required items.

## Goals

- In the demo, the agent sorts duplicates, amount conflicts, mixed VAT, missing VAT and dates it can find in the bank lines without help, and explains each one.
- It asks for exactly the things it can't support with evidence (a date with no bank match, a missing receipt or invoice), and never guesses them.
- After the answers come in, the posted trial balance matches hand-worked figures to the penny.
- Every change the agent makes can be traced to its evidence and can be reversed.

## Non-goals

- A sign-off or approval step before posting ("for now, just do it").
- Emailing the client for documents. The agent asks the person in the chat.
- Memory across chats beyond the client's open items and the record of decisions.
- Year-end work, filing, or more than one user.

## Anti-goals (a failure even if it technically works)

- **Guessing a date or an amount.** That includes taking a date from a file name.
- Booking a purchase as a cost without the document its amount needs.
- Reclaiming VAT without a simplified or full VAT invoice.
- Stating a figure that no tool returned.
- Asking about things the evidence already settles. Too many questions makes it look like a junior, not an accountant.
- A summary that buries the questions. They must stand out.

## Decided by you

- The agent should act like an accountant: decide what it can, ask what it can't.
- A matching bank line counts as evidence for a date. A file name doesn't.
- Post straight away, with no sign-off step, for now.
- Under £50 no document is needed. From £50 a receipt or invoice is needed. Above £250 a full VAT invoice is needed. A transaction without what it needs isn't booked as a cost and is marked Documentation required.
- Follow the simplified VAT invoice rule: a receipt with the supplier's VAT number and the VAT shown is enough to reclaim VAT, up to £250.
- Documentation required payments go to a suspense account.
- Layout A: all the questions come together, after it has done what it can.
- Everything else in this playback was confirmed as right.

## Carried over from the 2 Nov plan (already decided)

The full plan is kept at `docs/2026-11-02-ai-accountant-demo-plan.md`: tools, collections, API, UI, demo data, tests and milestones. It is in scope unless this document changes it. Login, the chat side panel on every page, and emailing requests to the client (all from the 23 Oct spec) are **not** in scope for this demo. The Northbridge documents and hand-worked figures don't exist yet and are written as part of the build.

- **Rows stay the working papers.** A new append-only posted ledger (`ledger_entries`, Decimal128) is the books. Corrections are made by reversal, never by editing or deleting.
- **Two views of the books, for now.** The existing Trial balance section and year close keep working from the rows. The chat shows the posted ledger. If a person edits a row after posting, nothing is posted automatically: the Overview shows "N changes not posted", and the next review posts the reversals. Bringing the two views together is a later project.
- **Removing a duplicate** marks the row `excluded` (a row change, with its decision recorded). The next posting then reverses anything already posted for it.
- **The expected figures** are measured against the posted ledger's trial balance.
- **Documents are uploaded in the chat**, stored with the client's files, and read by the existing pipeline. The agent can open an original document again to check a date or an amount.
- **A chat belongs to one client.** A new chat starts by asking which client, and a client can have many chats. A chat never sees another chat's conversation.
- **The stack:** FastAPI, Next.js, MongoDB, LangChain `create_agent` with the LangGraph Mongo checkpointer, at the pinned versions. The chat model is `LEDGERSYNC_AGENT_MODEL` (default `openai/gpt-oss-120b`) through OpenRouter, with `data_collection: deny`. Images are transcribed by the existing Qwen vision model.
  - *Changed 3 Nov:* one model now does both jobs, `OPENROUTER_MODEL` (default `qwen/qwen3.8-27b`): it reads the files and runs the agent. `LEDGERSYNC_AGENT_MODEL` and `openai/gpt-oss-120b` are no longer used.
- **The services decide, not the model.** The model picks an action and points to evidence. A deterministic service checks the evidence and refuses if it doesn't support the action. The client and the user come from the server, never from model arguments.
- **Every agent change is recorded** in an append-only decisions log, with its evidence, reason, and before and after values, and is idempotent.
- Posting checks that debits equal credits, every account exists, and the VAT treatment is valid. Either everything is written or nothing is.
- A synthetic demo client (Northbridge Consulting Ltd) with a reset, and hand-worked expected trial balances.
- Testing at three levels: deterministic services, the agent with a fake model, then the real model. **Ask before spending OpenRouter credit.**

## My calls (please check)

- "Not sure" on a date leaves the item open rather than letting the agent pick a date.
- The document rules cover purchases and expenses only, with the exempt list above.
- The limits apply to the gross amount: £50.00 needs a document, and £250.00 can still use a simplified VAT invoice.
- Over £250 with only a receipt, the payment is held in Suspense until the full invoice arrives, and no part of it is booked as a cost.
- The Suspense account is the existing `9998 Suspense`.
- A date you give is checked against the client's books, and a date outside them is refused.
- When an uploaded invoice doesn't fit the payment, the agent explains why and leaves the item open.
- Open items show on the client's Overview and are mentioned when a new chat opens.
- **A review covers the client's whole open year**, not only the files just dropped in, because the matching bank line or the duplicate may have been uploaded earlier. Posting covers the whole year too. The summary leads with what the new files changed, then anything else still open.

## Left to the builder

- How the agent pauses for answers: a normal turn that ends with question cards, or LangGraph interrupts. Either works, as long as answers can come in any order, and a server restart doesn't lose the open questions.
- How open questions are stored (for example an `open_items` collection keyed by client and row).
- How the answer controls send their answers (for example a structured message the agent receives as "Answer to question Q: 3 Oct").
- How the summary is streamed: the narrative streams; cards and tables arrive whole.
- The exact rules for matching an uploaded invoice to an open Documentation required item.

## The demo, in order

1. Reset the demo, open Chat, click New chat and pick Northbridge.
2. Drop the October files and ask: "Review Northbridge's October documents and get the books right."
3. The summary shows four or five things sorted (a duplicate, an amount conflict, a mixed-VAT split, VAT from an invoice, a date from the bank), two questions (an undated taxi receipt with no bank match, and a £240 payment with no invoice), and a balanced trial balance with £240 in Suspense.
4. Answer the taxi date. Upload the invoice. The £240 leaves Suspense, and the trial balance updates and matches the expected figures.
5. Ask "Why did you use £30.22?" The answer comes from the chat's memory and the decision record.
6. Open Transactions to show the agent's badges and the removed duplicate.
7. Start a new chat on Northbridge: it mentions any items still open, but not the earlier conversation.
