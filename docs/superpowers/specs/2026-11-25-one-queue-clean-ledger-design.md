# One queue, clean ledger: the client pages (design, 25 Nov 2026)

## Why

Checked on a copy of the agency books (1,355 rows), the client pages get in the way of the work:

- The same work is counted four ways: Overview "8 questions" and "110 of 1355 rows to review", AI review "113 things
  need you", Transactions "111 to review".
- Every issue is shown in full twice. On Transactions a flagged row is 3 to 10 lines tall, and six "Total doesn't add
  up" boxes sit above the table, a screen before the first row. One Stripe payout row lists 40+ "Link Stripe's
  statement" links.
- AI review is one flat list of 113 cards: no groups, no filter, no sense of progress, beige on everything.
- The filters wrap over two or three lines; 20 issue chips look like the filters.
- Overview opens on fixed client details; the year's state is plain text under them.

The person using it is an accountant working a client's year to the point where it posts and balances. Success: they
see one number for what is left, work it in one place, and read the ledger as a ledger.

## Goals

- AI review is the one place the work is done: one queue, grouped, filterable, with progress.
- Transactions is a compact ledger, one line a row; a row's detail and fixes open in a side panel.
- One "to do" number, defined once, on Overview and AI review.
- Overview leads with the year's state.

## Non-goals

- No backend change: the API, its issue codes and messages stay as they are.
- The date pickers keep the browser's own format (U9).
- The chat page is not touched.

## Anti-goals

- No way to accept many warnings with one click. "Another account? 30 rows" is worked one by one (decided 25 Nov).
  The existing "Apply all N suggestions" and "Apply to all N" for one suggested change stay: those are the AI's
  changes, each shown before it is applied.
- No fix that exists today is lost: every control on a row today (Link, Unlink, Include, Which date/amount, Reclaim it,
  Book without a receipt, Put back, Not the same, It's fine, account choice, Add line, Edit, Revert, Remove, Ask the
  AI, the Agent decisions) is reachable from the side panel.

## Approaches

1. **One queue, clean ledger** (chosen 25 Nov): AI review becomes the work queue; Transactions shows rows, with
   detail in a side panel. Bigger change, about a day of front end; the pages become short.
2. **Light touch**: today's layout, fixing only the faults (one count, cap the links, no date wrap, a "⋯" menu,
   fold the document problems, one-line filters). Quicker, lower risk, but the pages stay long and issues stay
   duplicated.

## Design

### The one number

`todo.ts` keeps `todoCards` and `needCount` as the definition of "to do": a card for each row in the books with a
warning or error, each document problem, and each open question or waiting suggestion not on one of those. A hook,
`useTodo()`, loads what the cards need (review runs, waiting suggestions, the client's questions) and returns the
cards and the count. AI review and Overview both use it. Transactions shows no headline count of its own; its
"Needs review" filter counts rows, and says so.

### Transactions

- **Columns:** Date (`01 Apr 23`, fixed width, never wraps), Description, Amount (signed: `+4,800.00` in green for
  money in, `−504.00` for money out), Account, Check (✓ / ⚠ / ✖ / ℹ / —). The Description cell is two lines at most:
  the description (one line, cut with "…", full text on hover) and a sub-line. In/out, VAT and Net move to the panel.
- **Sub-line:** for a flagged row, the heading of its worst issue in that severity's colour, with "+N" for the rest
  (`May pay an open invoice · +1`); otherwise the document type and its first status, shortened (`invoice · paid
  24 Apr`). A left-out row is muted and struck through, with `left out · <why>`.
- **Flag edge:** a flagged row has a 3px left edge in its severity colour. The selected row is tinted.
- **Document problems:** no block above the table. The document's problem is shown on each of its lines' sub-line
  and in the panel of any of them, with its Add line and Show its lines.
- **Side panel:** clicking a row opens it on the right (sticky, about 380px wide; below 1000px wide it covers the
  table, with Close). It holds, in order: the row's header (description, date, signed amount, file · type, Close);
  its issues (the same `IssueList`, every fix, restyled as below); its statuses (`rowStatus`, `apartStatus`, Include,
  Documentation required with Book without a receipt, Put back); the figures (in/out, amount, VAT with its treatment
  and "not reclaimed · Reclaim it", net, account, Edited with what the model read, the Agent decisions); the
  document itself (the file, or the lines read from it with this row marked, as `DocumentPanel` shows it now); and
  Edit, Add line, Revert, Remove. Esc closes it; ↑ and ↓ move to the next row when no field has focus.
- **Many candidates:** a status with more than three actions of one kind (the payout's 45 "Link Stripe's statement")
  shows the first three as links and the rest in one "Link to another…" picker.
- **Filters:** one line: the search box, a "Filters" button (with the number set) opening a panel of account, type,
  in/out, state, from/to dates and £ from/to, and a "Needs review" picker (All rows; Needs review, N rows; then each
  issue kind with its rows, errors first: today's chips). Each filter set shows below as a chip with × ("Money out ×",
  "1 Apr 23 – 30 Jun 23 ×"), then "412 of 1,355 shown · Clear". Order and Add transaction stay at the top right.
- **Links in:** `?row=<id>` (from AI review's Show) opens the table at that row with its panel open. Show both
  narrows the table to those rows, as now, and opens the panel on the first.
- **Totals** stay at the foot, with VAT and net written out on each line.
- **Paging** stays at 200 rows.

### AI review

- **Head:** "113 to do", "· 4 waiting on you", "· 5 done since you opened this page" (the count when it loaded less
  the count now, never below 0), a thin progress bar of that, and Apply all suggestions. The materiality line moves
  under the head, muted.
- **Groups**, from the card's rank in `todoCards`: Must fix (an error: "stops the books being posted"), Questions
  (an open question), Suggestions (a change to apply), To check (warnings), and Waiting on you (answered "I don't have
  it" or "Not sure") last. Tabs above the list: All, then each group with its count; a group with none has no tab.
  A "Kind" picker narrows to one issue heading or card tag.
- **To check** is folded by the heading of each card's first issue: one line each, "Another account? · 30 rows",
  most rows first. Opening one shows its first card with "1 of 30", Previous and Next; when a card is settled it
  leaves the list and the next one shows. No accept-all.
- **Cards:** white, a 3px left edge in the group's colour (error red, question accent, suggestion green, warning amber,
  waiting grey). The row's title, Show row and View document on one line; the issues as lines, not tinted boxes; the
  question and its answer field; the suggestion with Apply.
- The documents panel beside a card, the same-change groups ("Apply to all N"), the history of AI changes with Undo,
  and the notices (reviewing, failed with Try again) stay as they are.

### IssueList (both pages)

An issue is a line: its mark and heading in the severity's colour, the message in body text, the actions under it as
small buttons, not a beige box. Errors first, as now.

### Overview

- The year's card comes first: the to-do count (from `useTodo`) linking to AI review; questions waiting in other
  years; missing paperwork; then tiles for each bank account (agrees, or the difference in the warn colour), the
  trial balance (Balances, or Blocked with its first problem), unpaid sales and unpaid purchases.
- Client details come second, folded to one line ("Limited company · Hannah Finch · VAT 284619331 · Edit details"),
  opening to today's grid.
- "Rows to review N of M" goes: the to-do count replaces it.

## Left to the builder

- Exact widths, spacing and colours, within the "Ledger" look in `globals.css` (its tokens, serif headings, mono
  figures) and in both themes.
- Component boundaries (a `RowPanel`, a `FilterBar`, a `QueueGroups`), and where pure helpers live.
- Pure logic (the sub-line, signed amounts, short dates, filter chips, capped candidates, card groups, progress) is in
  `src/lib/*.ts` with `node --test` tests written first; components are checked in the browser on the agency copy
  (ports 3030/8120), in light and dark and at 375px.
