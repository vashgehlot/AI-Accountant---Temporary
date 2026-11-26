# Removed lines and document problems: design

## Why

A person removed the £457.20 Innside line from Mark's October expense claim. The books then:

- warned "Total doesn't add up … £457.20 missing: add the line", as if the reading had missed a line;
- put that warning on the claim's first line (the Booking.com hotel), which has nothing to do with it;
- listed it on the AI review page under "Recorded twice";
- had the background review ask the person whether the line they removed should be booked again.

The cause is that Remove deletes the row, so nothing remembers the line was there, and that a problem with a whole
document has nowhere to live except on one of its rows.

## Goals

1. Removing a line on purpose raises no warning, no problem and no AI question, and can be taken back.
2. A problem that is about a whole document is shown once, against the document, never on a line that doesn't
   explain it.
3. A person who has looked at a total that doesn't add up, and means it, can say so and the problem goes.

## Not in this change

- The AI review page as one to-do list (problem, question and run log merged). That is its own piece.
- The agent's issue families (`FAMILIES` in `ledgersync/agent/tools.py`), its prompts and its tools.
- Bringing back the Innside line on Mark's claim: it is already deleted and can't be recovered from the change log.
  Its warning is cleared with "Leave it as it is" (part 3).

## Must not happen

- The AI putting back, booking or asking about a row a person removed.
- A removed row counted in any total, trial balance, VAT figure, export sheet of booked rows or "to review" count.
- A warning that a person's own removal caused with no way to clear it.

## Approaches considered

- **A. Set the row aside instead of deleting it (chosen).** The total check already treats a document's left-out
  rows as accounted for (`left_out` in `matching._checked_totals`), and the table already shows left-out rows
  crossed out. Removal becomes reversible for free.
- **B. Keep deleting, and let the person answer "It's fine" on the warning.** Smaller, but the warning still appears
  first, on the wrong line, the AI still asks, and the line can't be brought back.
- **C. Keep deleting, and lower the document's expected total by what was removed.** Hides the row's history and
  makes the printed total no longer the printed total.

## Design

### 1. Remove sets a read row aside

- A row read from a file (a document or a statement) that a person removes stays in the store, marked removed by a
  person. It behaves everywhere as a row left out of the books does today (`excluded`), so every existing check of
  `excluded` keeps working, and carries one more mark saying a person did it.
- A row added by hand (a manual entry, a journal, a line added with Add line) is deleted outright, as now.
- The row stays listed, crossed out, with "Removed by you" and a **Put back** link. Put back clears both marks and
  the books are worked out again.
- The confirm before removing says it can be put back, for a read row; for a hand-added row it still says it can't
  be undone.
- The AI never changes a removed row: a decision that names one is refused, as for a row a split replaced. The
  agent's tools skip it, as they skip any left-out row.
- The change log keeps recording `row_removed`; Put back records `row_included`.

What the person sees:

```
15 Sep 2026   ~~Mark McNee — Innside by Meliá Liverpool, room 1209~~      Money out   £457.20
              Removed by you · Put back
              Mark october expenses.xlsx · Expense claim
```

The claim's other lines show no warning: £1,148.43 booked + £457.20 set aside = £1,605.63 printed.

### 2. A document's problem is shown against the document

- An issue says what it is about: a row (as now) or its document. The total check marks its issue as about the
  document whenever no single row explains the difference (today's fall-back to the first row, and an agent's
  statement that doesn't net to what it paid over). The issue still travels on the document's first row, so counts,
  filters and the agent see what they see today.
- **Transactions page.** A document problem is not drawn inside that first row, and the row is not marked ⚠ for it.
  It is drawn in a strip above the table, one line per document:

  ```
  ⚠ Mark october expenses.xlsx · Expense claim
    Lines total £1,148.43; the claim's total is £1,605.63. £457.20 missing: add the line.
    Show its lines · Add line · Ask the AI
  ```

  Show its lines puts all the document's lines side by side. The "Total doesn't add up" chip does the same. The
  "to review" count still counts it once.
- **AI review page.** A document problem is listed under a new heading, "Document totals", titled by the file and
  kind of document ("Mark october expenses.xlsx, expense claim"), with Show its lines. A total problem that one row
  does explain (a line read twice, an amount a person changed) stays where it is, on that row.

### 3. "Leave it as it is" on a total that doesn't add up

Part 1 stops the warning for a line removed from now on. A difference can still be there on purpose: a line deleted
before this change (Mark's claim), a hand-added line deleted, or a total the document prints wrongly.

- Every total problem, on a document or on a row, has **Leave it as it is**, beside Show its lines and Add line, on
  the Transactions page and on the AI review page.
- It records, on the document, the difference the person accepted (£457.20 short). The problem goes from the row,
  the strip, the AI review list and the "to review" count, and the AI is not shown it, so it does not ask.
- The document's lines then carry one quiet note, not a warning: "Total differs from the claim's by £457.20: left as
  it is by you", with **Undo**.
- It holds for that difference only. If the lines change again and the difference is no longer £457.20, the
  acceptance is dropped and the problem is raised afresh.

## Left to the builder

- The name of the mark for a person's removal, and of the field saying what an issue is about.
- How the strip is styled, using the page's existing notice and issue styles.
- Tests: a claim with a removed line raises no total issue; Put back restores it; a hand-added row is still
  deleted; a decision on a removed row is refused; a document-level issue is grouped under "Document totals" and
  kept off its first row in the table's helpers; an accepted difference raises no issue, shows its note, comes back
  when the difference changes, and Undo raises it again.
- Where the accepted difference is kept (it belongs to the document, not to one row, and must survive a row of the
  document being removed).
