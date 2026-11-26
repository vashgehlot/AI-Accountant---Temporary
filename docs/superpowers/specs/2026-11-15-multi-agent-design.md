# Specialist agents for the accountant chat and the background review

Design of 15 Nov 2026. Status: built the same day, following `docs/superpowers/plans/2026-11-15-multi-agent.md`,
which lists the changes made while planning.

**Changed later that day, at the user's request:** there is no setting and no second mode. Specialists are always
on, with the lead accountant for what none of them takes, and every agent runs on the one chat model at one
reasoning effort. Where this document says otherwise (the `LEDGERSYNC_AGENTS` setting, low effort for the reporter
and the bookkeeper) it is out of date.

**The eval on the real model** ran once each way before that change (documents pre-read): 8 of 10 cases passed
both ways, with the same two failing; median model calls per case 6 with one agent, 3 with specialists.

## Why

Today one agent does everything the chat and the background review ask of the AI: it reviews documents, makes the
changes a person tells it to, answers tax questions and reports on the books. It carries 15 tools and one prompt of
about 3,300 tokens on every model call. Two things follow:

- **It is slow.** A chat turn took 30 seconds to 2 minutes in the 11 Nov test round. Most of that is model round
  trips: the agent spends its first calls fetching the overview and the issues before it does anything.
- **It slips.** The same test round found it quoting figures the pages don't show and saying it had asked a
  question when none was created. A long prompt with rules for four different jobs gives the model more to get wrong.

The request (15 Nov): make the AI a multi-agent system in which each agent is specialised in particular tasks, with
low latency.

## Goals

1. Each turn is handled by one specialist with a short prompt, only the tools its job needs, and the state of the
   books already in front of it.
2. Fewer model calls per turn than today, on the same model.
3. No loss of accuracy on the agent eval cases (`eval/agent_cases`, the Northbridge demo).
4. A person can see which specialist handled a turn, and the logs say how long it took.

## Not in this design

- The rules and services (`resolutions`, `questions`, `evidence_rules`, posting) do not change. Every change the AI
  makes still goes through them, is checked against the evidence, and is recorded as a decision that can be undone.
- No new powers: the AI still can't post a journal, remove a row or add one.
- The document reader stays one agent in this phase (see Later phases).
- No change to how the chat stores its memory or to the events the chat page reads, beyond the text of `status`.

## What would make it a failure

- A specialist that can change the books when its job is only to read them.
- A turn that goes to the wrong specialist and quietly does the wrong thing, or refuses work the old agent did.
- More model calls per turn than today (a supervisor that only passes messages on).
- A reply that reads as if several people were talking. The person is talking to their accountant.

## Approaches considered

1. **Router in code, one specialist per turn (chosen).** Code picks the specialist from the message and the books;
   no model call is spent on routing. Fewest model calls; a wrong pick is handled by handing the turn over.
2. **A supervisor agent that calls specialists as tools.** Handles mixed requests naturally, but every turn pays one
   or two extra model calls for the supervisor to delegate and to sum up. Slower, which works against the request.
3. **Keep one agent and trim its prompt.** Cheapest and safest, but not a multi-agent system, and the four jobs
   still share one prompt.

Chosen by the user on 15 Nov ("Yes, write the design" to the router-plus-specialists recommendation).

## The agents

| Agent | Its job | Tools | Can change the books |
|---|---|---|---|
| **Reviewer** | Settles what the evidence settles: dates, duplicates, records that disagree, mixed-VAT rows, VAT a document prints. Asks only what the evidence can't settle. Runs every background review. | `list_issues`, `list_rows`, `get_row`, `list_documents`, `read_document`, `resolve_issue`, `ask_user`, `close_question`, `list_questions`, `list_changes`, `list_decisions` | Yes, through `resolve_issue` (evidence checked) |
| **Bookkeeper** | Does what the person tells it: an account, VAT, a date, an amount, a warning that is fine, booking without a receipt; an answer to a question. | `list_issues`, `list_rows`, `get_row`, `list_questions`, `edit_row` | Yes, through `edit_row` (chat only, as now) |
| **Tax and VAT adviser** | Answers tax questions from the books and the fixed facts in the prompt: VAT boxes, dividends, director's loans, reverse charge, what a journal should be. | `get_trial_balance`, `get_vat_figures`, `list_rows`, `get_row` | No |
| **Reporter** | Says where the books stand: what changed, what needs the person, balances, the trial balance. | `get_overview`, `list_questions`, `list_changes`, `list_decisions`, `get_trial_balance`, `list_issues`, `list_rows`, `get_row`, `list_documents` | No |
| **Lead accountant** | Today's agent, unchanged: every tool and the whole prompt. Takes a request the router can't place, a mixed request, and any turn a specialist hands over. | all 15 | Yes, as now |
| **Reader** | Reads uploaded documents into rows (`extractor.py`). Unchanged. | none | Saves the rows it reads |

Every specialist also has `hand_over` (below). The tool lists are the starting point; the eval may move a tool.

### Prompts

Each specialist's prompt is cut from today's `SYSTEM_PROMPT` (`agent/prompt.py`), not rewritten: every line in it is
there because a test round found a slip. All get "How you work" (less the line that says to start with
`get_overview` and `list_issues`) and "Finishing".

| Agent | Also gets these sections |
|---|---|
| Reviewer | Evidence; Resolving; What the rules already do; Background reviews |
| Bookkeeper | Doing what the person tells you; the lines of "What the rules already do" about questions, Suspense and VAT on a person's word |
| Tax and VAT adviser | Tax questions; the lines of "What the rules already do" about VAT, bank lines and statements |
| Reporter | The lines about `list_questions`, `list_changes`, bank balances against statements, and totals from the trial balance |

One line is added to each: what it is for, and to call `hand_over` rather than attempt work outside it.

## The router

Code, in a new module `agent/router.py`: `route(trigger, text, has_files) -> name`. The first rule that fits wins.

1. A background review: **Reviewer**.
2. The message is an answer to a question card (it starts `Answer to "`): **Bookkeeper**.
3. Files came with the message: **Reviewer**.
4. One of the chat's suggested prompts: "What needs my attention?" and "Show the trial balance" go to the
   **Reporter**; "Review the documents I'm adding" to the **Reviewer**.
5. An instruction about a row (it opens with put, move, change, set, code, book, reclaim, mark, accept, use):
   **Bookkeeper**. This is tested before the tax words, so "reclaim the VAT on the hotel" is the Bookkeeper's.
6. A question with a tax word (VAT return, box, dividend, corporation tax, director's loan, s455, reverse charge,
   depreciation, accrual, prepayment, journal): **Tax and VAT adviser**.
7. A question about the state of the books (what changed, summary, balance, trial balance, how much, outstanding):
   **Reporter**.
8. A request to review (review, check, go through, sort out, duplicates): **Reviewer**.
9. Anything else: **Lead accountant**.

A rule that misses costs speed, never correctness: the turn falls to the Lead, which does what the agent does today.

### Handing over

`hand_over(why)` is the one new tool. A specialist calls it when the request is outside its job. The rest of that
turn runs as the Lead accountant, in the same chat, with what has been read so far. It costs one model call, only on
a wrong pick. The Lead has no `hand_over`.

A tool outside a specialist's list is refused in code ("that isn't one of your tools; call hand_over"), so the
Reporter and the Tax adviser cannot change the books whatever the model tries.

## The briefing

Before the specialist's first model call, code fetches what the agent today spends its first calls on, and puts it
at the end of the system prompt for that turn only, under "The books now". It is not kept in the chat's memory, so
it never goes stale there.

| Agent | The briefing holds |
|---|---|
| All | The client (name, kind of business, VAT registered), the year, how many rows need a look in each family, how many are held in Suspense, how many questions are open, each bank account against its statement, the background reviews since the last chat |
| Reviewer | Also the first 20 rows that need a look, as `list_issues` gives them |
| Bookkeeper | Also the open questions, and the accounts a row can be coded to |
| Reporter | Also the open questions and the latest 20 changes |
| Tax and VAT adviser | Also the trial balance as it stands |

It is built by the functions behind the tools, so it says exactly what the tools would. A list that is cut says
which tool gives the rest. With the change of 15 Nov (one read of the client per calculation) it costs a few database
calls.

## How it is built

The preferred way keeps one compiled agent, so `Chat` reads and writes a chat's memory as it does now:

- `ChatContext` gains `specialist` (set by the router for the turn).
- A new middleware, `Specialist`, on each model call swaps in the specialist's prompt plus the briefing and offers
  only its tools; on each tool call it refuses a tool outside the list; after `hand_over` it switches the run to the
  Lead.
- The Reporter and the Bookkeeper run at low reasoning effort, the others at medium (today's setting).

To check first: that the installed LangChain (1.4.6) lets a middleware replace the prompt and the tools of a model
request. If it doesn't, build one agent per specialist over the same checkpoints and chat id; they share the same
middleware, so the same graph steps.

Also:

- `TurnRecord` gains `specialist` and `handed_over`, so a reopened chat and the evals know who answered. Old records
  read without them.
- The `status` event names the work: "Reviewing the books…", "Making the change…", "Working out the tax…", "Looking
  it up…", and "Working on it…" for the Lead. The chat page needs no change.
- One log line per turn: specialist, handed over or not, model calls, tool calls, seconds.
- A setting, `LEDGERSYNC_AGENTS`: `single` (today's agent for everything) or `specialists`. It ships as `single` and
  is switched once the eval passes, and is the way back if something goes wrong.
- Background review: `reviews._review_year` runs the Reviewer. Its message already names the issues, so its briefing
  is the common part only.

## Tests and the eval gate

- Router: a table of messages and the specialist each goes to, including the near misses ("reclaim the VAT" against
  "can I reclaim VAT on a van?").
- Each specialist is offered its tools and no others; a tool outside the list is refused and nothing changes.
- `hand_over` gives the rest of the turn to the Lead with every tool.
- The briefing equals what the tools return for the same books.
- With `single`, every existing agent and chat test passes unchanged.
- **Gate, on the real model:** `eval/run_agent_eval.py` on every case and the demo, before and after. The pass rate
  must not drop, and the median number of model calls per case must. "What needs my attention?" and "Show the trial
  balance" should each finish in two model calls. These runs spend OpenRouter credit and have not been approved yet.

## Later phases, each with its own note

1. **Background review side by side:** split a large review into Reviewer runs over groups of rows that don't touch
   each other, a few at a time. Not by family: a duplicate must be settled before its VAT is split.
2. **Reader specialists** by kind of document (bank statement, invoice or receipt, expense claim, payroll and agent
   statements), gated by the reading evals.
3. **Smaller speed-ups found on 15 Nov:** look-ups asked for together in one step; prompt caching for the prompt and
   tools; saving the chat's memory once at the end of a turn instead of after every step.

## Calls made in writing this, for the user to check

1. **A Lead accountant stays**, as the catch-all, so nothing the agent does today is lost. Cost if wrong: turns that
   reach it are no faster than today.
2. **Routing is by rules, with no model call.** Cost if wrong: more turns fall to the Lead; a small, fast model
   could be added later for the ones the rules can't place.
3. **The person sees one accountant.** The specialist shows only in the status line and the logs, not as a name on
   each reply.
4. **The Reader and the side-by-side review are left for later**, to keep the first build small enough to check
   against the eval.
5. **It ships switched off** (`single`) until the eval on the real model passes.
