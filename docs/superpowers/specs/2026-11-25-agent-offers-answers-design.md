# The agent offers an answer to the books' own questions (design, 25 Nov 2026)

## Why

The books ask some questions that need a choice before anything can be booked:
- the opening VAT difference (`opening_vat`);
- which costs the opening prepayments or accruals are for (`opening_prepayments`, `opening_accruals`);
- whether to write off a long-unpaid invoice (`bad_debt`).

Clients often answer them in the chat in their own words. In the agency's paid run of 25 Nov 2026, the client
answered the £312 VAT question: "Redland & Co say a February invoice was left off their VAT figure. Fine to correct
it this year". The books' question stayed open, because the agent has no way to answer a rules question
(`close_question` closes only its own). So the agent asked for a new document instead. The client had to find the
card on the page and fill it in themselves.

Goal: when a client's words (and the documents) settle such a question, the agent fills in its answer card and the
client confirms it. Nothing is booked on the agent's reading alone.

## Goals

- From a chat, the agent can **offer** an answer to an open books question of the four kinds above. The offer holds:
  - the answer (the split lines with account and amount, or the write-off date);
  - where each figure came from: the client's words, quoted from this chat, and quotes from the client's documents;
  - one line of reasoning.
- The offer is checked by the same service that books the page's answers (`questions.answer`) before it is kept,
  without booking anything. An offer the service would refuse is never shown.
- The question's card opens filled in with the offer, wherever the card shows: in the chat and on the client page's
  queue (`QuestionCard`, used by both). The client can change any line or the date before confirming (user,
  25 Nov). **Confirm** sends the answer, as edited, through the existing answer routes.
- The agent may work out amounts the client didn't give, from documents it quotes. For example, last year's rent
  invoice gives £5,538.46 for 84 days, and the insurance £1,020.00. Every figure on the card shows its source (user,
  25 Nov).

## Non-goals

- No answer is booked without the client's Confirm: not in a chat, and never in a background review.
- Date and document questions (`date`, `receipt_or_invoice`, `vat_invoice`, `payout_report`, `payroll_report`) are
  not covered. They have their own answers (a date read from a document, an upload), and the agent already handles
  dates with `resolve_issue set_date`.
- No undo of a confirmed answer beyond what the page's answer has today. An answer posts journals, and taking them
  out is a separate piece of work.
- The agent's own questions are not covered: `close_question` stays as it is.

## Anti-goals

- **Figures moved on the agent's reading.** If an offer books without the press, it has failed.
- **An offer the client can't trace.** A figure with no quote beside it is not shown.
- **Two answers in flight.** Two cards or two offers for one question, or an offer that outlives the question being
  answered, would let one question be answered twice.

## Constraints

- In a chat, the person's word is the authority, as for `edit_row` (`resolutions.edit_as_told`). The new tool is
  refused outside a chat (`ctx.trigger != "chat"`).
- Quotes from documents are checked the way every resolution's are (`resolutions.check_quotes`, rule R0). A
  quote of the client's words must appear in a person's message in this chat's thread (the checkpointed messages).
- Answers keep going through `questions.answer` (the API routes `/api/chat/threads/{t}/questions/{q}/answer` and
  `/api/clients/{c}/questions/{q}/answer`). Nothing else books them.
- The question's year rules hold. The question is asked in the earliest open year it belongs to (25 Nov fix); the
  offer belongs to the question, not to a year of its own.
- The user's uncommitted work in ledger.py, records.py, reviews.py, server.py and tests/test_reviews_api.py stays
  as it is.

## Approaches

- **A. Keep the offer on the question (chosen, user, 25 Nov).** The question document gets an `offer` field. The
  card reads it wherever it shows, and Confirm posts the (edited) answer through the existing routes. The offer
  survives a reload and shows on the client page.
- **B. Keep the offer only in the chat reply.** Less to build, but it is lost on a reload and never reaches the
  page's card.
- **C. Record it as a suggested decision**, applied through the review's suggestion machinery. This would gain undo
  by taking the journals out, but it needs a new decision kind and journal reversal: far beyond the need.

## The design

### Storage

- `Question` gains `offer: Optional[Offer]`.
- `Offer` holds:
  - `answer`, a `SplitAnswer` or a `WriteOffAnswer`;
  - `sources`, a list of where each part came from: the client's words or a document quote;
  - `reason`, one line;
  - `thread_id`, `offered_at` and `offered_by` (the agent's actor).
- Each source is one of two kinds:
  - `{"kind": "said", "quote": <the client's words>}`;
  - `{"kind": "document", "upload_id", "quote", "for": <which line or the date>}`.
- `AgentRecords.set_offer(question_id, offer)` and `clear_offer(question_id)` set and clear it.
- When the question is answered or resolved (`set_question` to `resolved`, or `waiting` from "Not sure"), the offer
  is cleared in the same update, so it can't outlive the question.
- `upsert_question` leaves the offer alone. When the question's text changes (say the amount to release changed),
  the offer is cleared, because its figures no longer add up.

### The service

- `questions.check_answer(store, client_id, question, answer) -> Optional[str]` gives the refusal the answer
  would meet, or None. It runs the same checks as `_release`, `_release_vat` and `_write_off`: the kind matches,
  the lines add up to what is left, the accounts are allowed, and the date is inside the year and past the six
  months. It writes nothing.
- Today the checks sit inside the posting functions; they move into helpers that both call.
- `questions.offer(store, records, *, client_id, thread_id, question_id, answer, sources, reason, texts, said_in)`
  makes the offer. It refuses, with a reason the agent reads, when:
  - the question isn't a rules question of the four kinds;
  - the question isn't open or waiting;
  - `check_answer` refuses;
  - a document quote fails `check_quotes`;
  - a "said" quote isn't in the thread's person messages;
  - an amount on a split line, or the write-off date, has no source (see "What counts as a source" below);
  - there is no `said` source, quoting the client in this chat.

  Otherwise it sets the offer, records a change (`question_offered`, actor the agent) and returns the question.
  Offered again, the new offer replaces the old.
- `questions.answer` is unchanged apart from clearing the offer, as above.

### The agent

- A new tool, `offer_answer(question_id, answer, sources, reason)`, works in a chat only. Its docstring says:
  - use it when the person's words in this chat, with the documents, settle a books question of these kinds;
  - work out amounts from the documents, quoting each;
  - the person confirms on the card, so never say it is booked.
- `list_questions` returns a question's `offer`, if any, so the agent doesn't offer again.
- A line goes in the prompt's question rules. When the person answers a books question in the chat, offer the
  answer with `offer_answer`; don't ask for something new. Say you have filled in the card for them to confirm.
- The chat turn's result already carries the turn's questions, so the offered question shows as a card in the reply.

### The card (`frontend/src/components/chat/QuestionCard.tsx`, `frontend/src/lib/chat.ts`)

- When `question.offer` is set:
  - the split lines, or the write-off date, start filled in from it;
  - beneath them, "From what you said: “…”", each document quote beside its line, and the reason;
  - the primary button reads **Confirm** (not "Release" or "Write it off"), and stays disabled until the lines add up,
    as today.
- Editing a line keeps the quotes in view and marks that line "changed by you". Confirm sends what is on the form.
- With no offer, the card is as today.
- The offer reaches the front end on the `Question` type, as an optional `offer`.

### The test runner (`claude/nostalgic-ptolemy-28a206`, `testbooks_runner/driver.py`)

- After a reply, `send_replies` reads the client's open questions. For each one with an offer made in the runner's
  thread, it confirms the offer unchanged (the client's yes) through the chat's answer route.
- It records what it confirmed in `progress.replies`, and the report lists the offers it confirmed.

## Settled after the builder check (my calls, 25 Nov)

- **Documents an offer may quote:** any of the client's own uploads, in any year. This is wider than
  `check_quotes`, which allows only the named rows' documents, because the opening questions name no row and
  last year's invoices belong to no row of this year. Each quote is still checked to be in the upload it names
  (normalised as `check_quotes` does). For these questions, `list_documents` and `read_document` reach the
  client's other years.
- **What counts as a source for a figure:** every split line and the write-off date carries a source. A source is
  one of:
  - the client's words in this chat (`said`);
  - a document quote (`document`, with `for` naming the line or the date);
  - the question itself (`question`): the amount it asks to be released or explained, or the default write-off
    date.

  A figure worked out from a document carries its working on its line ("£24,000 a year, 84 of 364 days"), shown on
  the card beside it. The service checks that each line has a source and that the lines pass `check_answer`. It
  does not look for the figure in the quoted text. The £312 VAT case is a line sourced from the question, with the
  client's words saying where it goes.
- **Questions in other years:** the tool and `list_questions` cover the books questions of every open year of the
  client, each answered in its own year. The turn's result carries any question offered in the turn, whatever its
  year.
- **Where it is built:** in the main checkout, on top of today's uncommitted work (the 25 Nov fixes this relies on).
  The user's own hunks in records.py and server.py are edited around, never discarded or committed with this work.
  The runner's part is a separate change on its own branch.

- **An offer needs the client's words (user, 25 Nov):** an offer is made only once the client has said something
  in this chat about that question, and it carries at least one `said` source quoting it. Documents alone never make
  an offer: the agent can't pre-fill a card the client hasn't spoken to. The service refuses an offer with no `said`
  source.

## Left to the builder

- The exact names, and where the shared check helpers live.
- How a "said" quote is matched (normalised as `check_quotes` does).
- The card's text and layout within the existing styles. The "changed by you" mark may be a small muted label.
- The tests: the service refusing each case above; an offer cleared when the question is answered or its text
  changes; the tool refused outside a chat; the card filled in, edited and confirmed (`chat.test.ts` for the pure
  logic); the runner confirming.
