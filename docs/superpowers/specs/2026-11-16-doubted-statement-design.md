# A statement that doesn't look like a bank's: one question on it, not a warning on every receipt: design

> **Shelved on 2026-11-16, before anything was built.** The reader's instructions were changed the same day, and the
> document that prompted this is now read as eight receipts (4 reads of 4). Decided with the user: build this only if
> another supplier's list is read as a bank statement. A smaller idea raised then, and not sized: have each
> `not_on_statement` warning name the file it relied on.

## Why

On 2026-11-16 a client's Transport for London "Payment Statement" (a card, a date range, one charge for each of eight
days, every line to TfL, no balance) was read as her bank statement. Matching trusts a bank statement completely:
`_off_statement` took its lines as proof of what the bank did not pay, moved the 21 receipts dated inside it
(£622.17) to Suspense, and put a warning on each. Nothing pointed at the statement, so the page made no sense to the
person reading it.

The reader's instructions now say what such a document is (same day). They are instructions to a model, though, and
another supplier's list can be misread again. One misread document should give one question about that document,
with one click to put it right.

## Goals

1. A statement that doesn't look like a bank's (section 1) is not used to say what the bank did not pay.
2. It carries one warning, on the statement itself, that says why and what happens meanwhile.
3. One suggestion beside the warning turns its lines into receipts in one click, with Undo.
4. A person can say it is a bank statement after all, and it is then trusted like any other.

Statements already saved are covered like new ones: the client's saved TfL lines get the warning and the suggestion
as soon as this is in.

## Not in this change

- Doubting a statement that looks like a bank's (several payees, or a printed balance) because it pays none of the
  receipts dated inside it. That case stays as it is: a warning on each receipt, answered with Paid from. (Decided
  with the user: "Narrow".)
- Asking anything while a file is being uploaded.
- What the Bank page says about an account.
- The reader, and the stateless analysis (`/api/analyze`, `/api/transactions/validate`), where nothing is doubted.
- The accountant agent's actions: it is not offered the new one. It sees the warning as it sees any other, filed
  under Documents; what it says about it is not part of this change.

## Must not happen

- A real bank statement losing its say. A statement with any printed balance, with lines to more than one payee, with
  a line that names no payee, or with a single line behaves exactly as today. `tests/test_matching.py` has the
  director's-own-card case (a £499 receipt, statement lines either side of 16 May): it stays as it is and passes
  unchanged.
- A doubted statement's lines being left out of the books, re-coded, or kept from pairing with a receipt for the same
  charge. Only its use as proof of what the bank did not pay changes.
- The fix applied by anything but a person: not the background review, not the chat.
- The warning repeated on every line, or raised again after a person said it is fine.
- Apply changing some of the statement's lines and not others.

## Approaches considered

Scope, decided first:

- **Narrow (chosen).** Doubt only a statement that doesn't look like a bank's. It covers what happened and cannot
  disturb real statements.
- **Broad.** Doubt any statement that pays none of the receipts dated inside it. It also fires on the genuine case
  (the owner paid for everything personally), needs a stored answer, and changes the review list for real statements.

How the person answers, decided second:

- **A. One warning with a one-click fix (chosen).** The warning on the statement, and a suggestion from the rules
  that turns its lines into receipts, applied and undone through the machinery account-change suggestions already
  use. One question, one click, where the person was looking when the 21 warnings appeared.
- **B. One warning, fixed by hand.** Smallest, but the fix is an edit per line (eight here) or deleting the upload
  and adding it again, which only helps if the reader gets it right the second time.
- **C. Ask at upload time.** Nothing doubtful reaches the books, but it interrupts a batch upload (this one was 27
  files), needs new upload screens, and does nothing for statements already saved.

## Design

### 1. What is doubted

One upload's bank lines, when all of these hold. Its bank lines are its rows whose `document_type` is `statement`,
leaving out rows a decision left out of the books (`excluded`, `superseded_by`) and removed rows; "line" below always
means one of these.

- there are two or more of them;
- every one names a payee (`counterparty`), and the names all match one another, compared as matching compares names
  (`names_match` in `ledgersync/matching.py`);
- none prints a balance: `balance`, `opening_balance` and `closing_balance` are all empty on every line;
- no line has the warning's code in `accepted` (section 3).

It is a pure function over one upload's rows, beside `check_statement` in `ledgersync/statements.py`, which already
judges one upload's bank lines whole. It gives the payee's name when the statement is doubted, and nothing otherwise.
Importing `names_match` there makes no cycle: `matching` imports neither `statements` nor `books`.

### 2. Matching

`match_documents` takes one more per-row input, threaded exactly as `name_days` is (worked out in `books.py` from the
uploads, one entry per row, `None` when not given): whether the row is a line of a doubted statement.

`check_statement` runs after matching, so this input is worked out before it, from `b.stored`, as `_name_days` is.
`books.py` passes `name_days` in three places (the `_Books` method near line 151, `_matched`, and `booked_rows`);
each of them passes this input too, so the pages, the trial balance and the booked rows agree.

`_off_statement` leaves the days of those lines out of the days it collects for each account. Nothing else in
matching changes: the lines are still bank lines, still booked, and still pair with a receipt for the same charge.

With no doubted line among them, the days are what they are today, so every existing test of `_off_statement` passes
unchanged.

### 3. The warning

One issue on the first of the statement's lines, in the order the rows are stored:

- code `one_payee_statement`, severity `warning`, `about="document"`, so the AI review page lists it as one document
  card named by the file;
- text, in this meaning: "Every line pays {payee} and the statement prints no balance, so it may be {payee}'s own
  list of charges, not a bank statement. Until you say, it isn't used to check which receipts the bank paid."

It is derived like the other statement issues: registered in `checks.STATEMENT_ISSUES`, so checking again replaces
it, and added where `check_statement`'s issues are added.

It is also a matter of judgement: the code joins `checks.ACCEPTABLE` and its mirror in `frontend/src/lib/ledger.ts`.
A person who answers "It's fine" puts the code in that line's `accepted`; by section 1 the statement is then not
doubted, so the warning goes and the statement is used again to say what the bank did not pay. The card must offer
"It's fine"; if a document card does not offer it today, making it do so is part of this change.

The answer lives on that one line. If the line is later removed or left out of the books, the statement is asked
about again.

### 4. The suggestion

A new resolution, `read_as_receipts`, with the rule name "R7 Not a bank statement". It is in `Resolution` and not in
`AgentResolution`, as `change_account` is.

- **What it holds.** The ids of the statement's lines, as `keep_one` holds the rows it drops, because `_named` sees
  only the resolution: the line asked about (the one carrying the warning) first, then the rest.
- **What it does.** It sets `document_type` to `receipt` and `bank_account` to empty on each of those lines. Every
  line already has its own `document_ref`, so each becomes a receipt of its own; its payee, date, amount and account
  stay as they are, and it is booked as paid from the client's default bank, like any receipt. `patch_row` stores an
  empty value as given, and a row's first change keeps what it held as `original`, as with any decision.
- **When it is refused.** When the line asked about no longer carries `one_payee_statement` ("Nothing says this isn't
  a bank statement."), when the lines it holds are no longer exactly that upload's lines ("The statement's lines have
  changed."), and in every case R0 already refuses (a closed year, an archived client, a change a person undid).
- **Who makes it.** Like R6, in each of the three places `resolve` treats `change_account` apart: it needs no
  evidence, because the books themselves show it; it is only ever suggested unless a person makes it; and the
  background review's refusal of rows a person changed does not apply to it. Applying already reads the stored
  resolution through `Resolution` (`undo.apply_suggestion`). The agent cannot ask for it: what it may ask for is
  `AgentResolution`.
- **When it is suggested.** Wherever `suggest_account_changes` runs (`upkeep.py`), the rules also record one
  suggestion for each line of the year that carries `one_payee_statement` and has none yet. The reason is the
  warning's first sentence. A change a person undid is not suggested again. None is recorded when any of the
  statement's lines is in a closed year, since it would be refused: the warning stays, and the person can reopen the
  year or answer "It's fine".
- **Where it shows.** On the statement's card: `todo.ts` puts a suggestion on the card of the first of its rows that
  has one, and the line carrying the warning is first.
- **When it stops waiting.** `waiting_suggestions` lists it only while its line still carries the warning, as
  `_still_holds` does for an account change: after "It's fine", an edit by hand or the upload's removal it is gone.
- **Undo.** The existing undo puts both fields back on every line. The statement is then doubted again and warns
  again, with no new suggestion; the person has "It's fine" and Edit.

### 5. The page

- `frontend/src/lib/ledger.ts`: the code's label, "May not be a bank statement", and the code in `ACCEPTABLE`.
- `frontend/src/lib/todo.ts` and `FAMILIES` in `ledgersync/agent/tools.py`: the code joins the Documents family.
- The card shows the suggestion as one line, not one per line of the statement:
  "Its 8 lines: Bank statement line → Receipt". The grouped-fix rule (`sameFixGroups`) leaves it alone: it is one
  suggestion.

What the person sees, for the statement that prompted this:

```
AI review · 1 thing needs you

  Transport_for_London-2026-10-31_00_00_00.pdf
  ⚠ May not be a bank statement. Every line pays TfL and the statement prints no balance, so it
    may be TfL's own list of charges, not a bank statement. Until you say, it isn't used to check
    which receipts the bank paid.
    Suggested · R7 Not a bank statement
    Its 8 lines: Bank statement line → Receipt                     [Apply]   [It's fine]
```

### 6. The case to hold it to

Client 3's year from 2 May 2026, as saved on 2026-11-16: 26 receipts, and upload 117 with eight bank lines to "TfL"
from 5 to 27 October, no balances.

| | Today | With this change | After Apply |
|---|---|---|---|
| `not_on_statement` warnings | 21 | 0 | 0 |
| In 9998 Suspense | £622.17 | £0.00 | £0.00 |
| On 1200 Bank | £225.29 | £847.46 | £847.46 |
| Cards on the AI review page from this | 21 | 1, on the statement | 0 |
| Upload 117's rows | 8 bank lines | 8 bank lines | 8 receipts |

After "It's fine" in place of Apply, the year is as it is today, by the person's own word.

The table was worked out in memory from the saved year on 2026-11-16, through `books._saved_rows` and the trial
balance, with the days of upload 117's lines left out of `_off_statement` (middle column) and with those lines as
receipts (last column). As bank lines the eight rows carry only the `vat_unclaimed` note; as receipts they carry no
issue at all. Both columns are tests, not hopes.

## Calls made in writing this

Not decided with the user; each can be changed.

- The line that carries the warning is the statement's first line in the books, and "It's fine" is kept on that line.
- The doubt is judged in `statements.py`, with `names_match` imported from `matching.py`.
- The resolution holds its lines' ids, and is refused when they are no longer the upload's lines.
- No suggestion is recorded for a statement with a line in a closed year.
- The warning is tagged with the Documents family, on the page and for the agent.

## What the tests must show

- **Section 1:** doubted with two lines to one payee and no balance; not doubted with one line, with two payees, with
  a line that names no payee, with any one balance printed, or once accepted.
- **Section 2:** a receipt inside a doubted statement stays on the bank with no `not_on_statement`; the same receipt
  inside the same statement, accepted, is moved to Suspense as today.
- **Section 3:** the warning is on the first line only, and once.
- **Section 4:** suggested once and not again after an undo; Apply changes every line or none; refused when the
  warning has gone; not in `AgentResolution`.
- **Section 5:** one document card with the suggestion on it and both answers offered.
- **Section 6:** the table's middle column, from rows shaped like that year's.

## Left to the builder

- The names of the new functions and of the per-row input, and where in `books.py` it is worked out.
- The wording of the warning and of the card's one line, within the meanings given.
- Whether doubt is worked out once and shared between matching and the warning, or worked out in both places from the
  same function.
- The year a warning shows in when a statement's lines fall in two years: the year of the line that carries it.

## Accepted risk

A real statement can be short, all to one payee and without a balance (two bank lines to HMRC, pasted). It is asked
about once, and "It's fine" restores it. Meanwhile it only fails to move receipts to Suspense; it books nothing wrong.
