# AI review as one to-do list: design

## Why

The AI review page is shaped around what the review did, run by run, not around what the person has to do. The same
item can appear three times (in "Problems found", in a run's summary, and as that run's question card), suggestions
and questions sit inside whichever run produced them, and five failed runs each take a red row with a "New" badge.
The person has to read the whole page to learn what is still waiting for them.

The mockup the person approved on 2026-11-15 turns the page into one list of what needs them, with history below.

## Goals

1. One card per thing that needs the person, holding what is wrong, what the AI says about it, and every control
   that settles it.
2. Nothing that needs the person is shown twice, and nothing waiting (a suggestion, a question) is lost.
3. Failed runs are one notice, with a way to try again.
4. History (what the AI changed, what each run did) stays available, below the list and collapsed.

## Not in this change

- What the AI reviews, changes, suggests or asks, and when it runs (apart from Try again).
- "Add the line back" filled in from what the AI found: a question is free text, so there is nothing structured to
  fill a line from. The card offers the ordinary Add line.
- Filter chips. The list is short for one year; they can be added if lists grow.
- The Transactions page, the chat, and the counts on the Overview and Clients pages.

## Must not happen

- An open question, a waiting suggestion or an Undo that the page shows today having nowhere to appear.
- A control on a card that does something different from the same control on the Transactions page.
- Opening the page no longer marking the runs as seen.

## Approaches considered

- **A. Build the list on the page from what the API already returns (chosen).** The year's rows and their issues, the
  waiting suggestions, the client's questions and the runs are already loaded here. One rule in `frontend/src/lib`
  turns them into cards, tested without the network; the components stay thin. One small route is added for Try again.
- **B. A new API route that returns ready-made items.** Repeats, on the server, grouping the page already does, and
  touches the review code that has other uncommitted work in it.
- **C. Keep the three sections and hide the repeats.** Cheaper, but the page stays shaped around runs.

## Design

### The list

A card is about one row, one document, or one question that names no row.

- **A row's card**: every warning and error on a row that is in the books, as the Transactions page lists them, each
  with the same controls it has there (the fix, Show both, Not the same, It's fine, Leave it as it is, Ask the AI).
  This is the issue list of the Transactions page, shared, so the two can't drift apart.
- **A document's card**: a problem with a whole document (today, a total that doesn't add up), named by its file, with
  Show its lines, Add line and Leave it as it is.
- **The AI's part of a card**: a waiting suggestion for the row, with what it would do and Apply; and an open
  question about the row, with its answer control. Each goes on the card of the first of its rows that has one.
- **A card of its own**: a suggestion or a question whose rows have no card gets one, named by its first row; a
  question that names no row gets one titled by its text.
- Each card is headed by a small tag for its kind ("Account", "Recorded twice", "Document total", "Question", …),
  what it is (the row as a person knows it, or the file), and a Show link to it on Transactions.

Order: cards with an error first, then cards with a question, then cards with a suggestion, then the rest; within
each, by the row's date. Questions the person answered "I don't have it" or "Not sure" come last, marked as waiting,
and can still be answered.

Above the list: "N things need you", and, when more than one suggestion is waiting, "Apply all N suggestions".
With nothing waiting: "Nothing needs you." and when the books were last reviewed.

### One notice for failed runs

When the latest run failed, one notice at the top: "The review hasn't finished since Fri 13 Nov 16:33: API key
expired (5 tries)." with **Try again**. The count and the time are of the unbroken run of failures at the top of the
history. Try again asks for a review now (a new route that makes the client's review due at once); while one is
running the notice is replaced by "Reviewing…". "Paused for today: limit reached" and "AI review is off for this
client" are notices of the same kind, without a button.

### History, below the list

- **Changed by the AI** (collapsed; says how many are new since the person last looked): every change a review made
  that hasn't been undone, newest first, each as it reads today with **Undo**; and the changes the person applied on
  this visit.
- **Activity** (collapsed): one line per run, newest first: when, what set it off, and what it did ("changed 2,
  suggested 1, asked 1"; "3 other changes were stopped by the checks"). Runs that failed one after another with the
  same error fold into one line: "Fri 13 Nov, 16:33 to 17:13 · 5 runs didn't finish: API key expired".

### What goes

"Problems found" and the per-run bodies (summary, decisions, question cards) are replaced by the above. The "New"
badge per run goes; "new since you last looked" is said once, on Changed by the AI.

## Constraints

- Another session is changing the chat pages on this checkout and may edit `frontend/src/components/chat/` and
  `frontend/src/app/globals.css`. This change uses `QuestionCard` and `DecisionLine` as they are, and keeps its
  styles in one new block of the stylesheet.
- `ledgersync/reviews.py` has other uncommitted work: the Try again route should need no edit there beyond what
  making a review due requires, kept small and separate.
- A closed year or an archived client shows the list with no control that changes anything, as today.

## My calls, to check

- One card per row, not per issue: a row with two warnings is one thing to open and settle.
- The order above, and waiting questions last.
- Try again is in; filling Add line from the AI's finding is out.

## Left to the builder

- Names and file layout of the rule and the components, following `src/lib` (rules, tested) and `src/components`
  (thin).
- The exact wording of an Activity line from a run's counts.
- Tests: a row with two issues is one card; a document problem is a card named by its file; a suggestion and a
  question land on their row's card, and get their own when the row has none; a question with no rows gets a card;
  the order; five failures with one error fold into one line and one notice; a success between failures breaks the
  fold; Try again makes a review due and is refused for an archived client.
