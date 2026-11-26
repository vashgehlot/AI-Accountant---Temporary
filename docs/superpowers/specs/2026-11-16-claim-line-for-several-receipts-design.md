# One claim line for several receipts on one document

Approved approach and choices by the user on 2026-11-16; the written design awaits their approval.

## Why

Jenny's October expense claim has one line, "31/10/2026, Transport for London, Train, £55.40". Her TfL contactless
"Payment Statement" (upload 199) lists eight daily charges, 5 to 27 Oct, £61.50 in all, and the reader rightly makes
each charge a receipt of its own (rule 2 in `ledgersync/extractor.py`, committed as 4f71949).

Matching pairs a claim line with one receipt only, of the same amount and dated within three days of it
(`_with_claims`, `ledgersync/matching.py`). No single charge is £55.40 and none is near 31 Oct, so nothing pairs:
the claim line is booked to Travel as owed to Jenny, and the eight charges are booked to Travel again as paid from the
business bank, though her own MasterCard paid them. Her October TfL travel counts twice.

Seven of the eight charges (all but 5 Oct, £6.10) add up to £55.40, and no other set of them does.

## Goals

- A claim line that names a supplier is booked from the set of that supplier's receipts, on one upload, that adds up
  to it exactly, when only one such set does. Each receipt in the set is owed to the claimant on the claim, as a
  single paired receipt is today; the claim line is not booked.
- A charge on that upload that the claim leaves out is not booked, and asks whether it was a business expense missed
  from the claim. Ticking Include books it, owed to the claimant.
- When no set adds up, or more than one does, nothing pairs, and the line and the upload's receipts say so and point
  at each other.
- From either side a person sees the other: the claim line names its receipts, each receipt names its claim line.
- Jenny's saved rows put right with no re-upload: matching is worked out afresh from the saved rows each time
  (`books.py`, `match_documents`), so a restart of the API is enough.

## Non-goals

- Pairing across uploads (three separate Trainline PDFs under one claim line). Sets of receipts from many uploads
  add up to the same amount too easily; the app would be guessing.
- Near amounts. Only an exact total, to the penny.
- A manual Link on claim lines to pick receipts by hand. Considered and left for later, if ambiguous cases turn up.
- Any change to the reader.

## Anti-goals

- A claim line paired with a set of receipts that only happens to add up: a Trainline line taking TfL charges, or a
  line taking a set when another set of the same receipts fits as well.
- Breaking today's one-receipt pairing, or any pairing a person made or kept apart ("Not the same").
- The leftover charge silently vanishing: it stays in the table, unbooked, saying why.

## Approaches

- **Pair in matching, within one upload (picked).** After today's one-to-one passes, a claim line still open looks at
  the open receipts of one upload whose supplier it names, for the one set that adds up to it. Automatic, re-worked
  every time matching runs, undone if a row changes.
- **Change the reader** to read a supplier's statement as one receipt of many lines. Ruled out: the reader can't see
  the claim, it undoes the rule that each charge is a receipt (so a business card's bank lines can pay them), and
  Jenny's claim is £6.10 short of the statement, so even one receipt wouldn't pair.
- **Matching plus a manual Link on claim lines.** Covers the ambiguous cases, but is a new control and more work. Not
  now.

## What gets built

1. **The pass.** In `_with_claims`, after the existing one-to-one passes (by name, by amount and date, undated by file
   name, settled) and before the "differs" pass. For each claim line still open (not paired, not kept apart, with a
   date), and each upload:
   - the candidates are that upload's receipts that are booked, not yet claimed or paired, not kept apart from the
     line, the same direction as the line, and whose supplier the line names (below);
   - dated no later than three days after the line and no earlier than 35 days before it (my call: a claim line is
     usually dated the end of the month or the statement's date; `COVERED` and `CARD_DAYS` are the existing spans);
   - there are at least two of them (one is today's pairing);
   - the sets of them that add up exactly to the line's gross are counted, stopping at two.
   Exactly one set across all uploads: pair it. Two or more sets, on one upload or across several, or a set on more
   than one upload: nothing pairs and both sides warn (item 4). None: nothing happens, as today.
   One claim line takes one set; a receipt goes in one set at most. When two open claim lines each have a set that
   fits and the sets could share a receipt, neither pairs and both warn (item 4): which line claims which charge
   would be a guess. Lines are taken in date order, then row order, so the result does not depend on the order rows
   arrived in. An undated receipt is never a candidate.
2. **What pairing does.** Each receipt in the set gets `claimed_in` for the line and `contra_account_code` 2110, as
   `pair` does for one receipt, with the claim line's VAT checks (`_claim_vat`) run against the set as one document
   (a TfL fare is zero-rated, so Jenny's has none). The claim line gets `recorded_by` for the set, so it is not
   booked, and the new list of the set's refs (item 5). A claim line a person ticked Include on is booked as well and
   warns `booked_twice`, as today.
3. **The leftover.** Once a set on an upload pairs, each other candidate on that upload (same supplier, same
   direction, inside the date span; for Jenny, the 5 Oct charge) is not booked and gets a warning `not_claimed`:
   "On {supplier}'s statement with {n} charges on {claimant}'s claim, but not claimed itself. Not booked: the claimant
   paid it and hasn't asked for it back. If it was a business expense missed from the claim, tick Include." Its
   `contra_account_code` becomes 2110, so Include books it owed to the claimant, not paid from the bank. Receipts of
   the upload outside the date span or from another supplier are untouched. If a business bank line later in matching
   pays a leftover charge (the business card paid it after all), it is booked as an ordinary receipt paid by that
   line, and `not_claimed` goes: the builder orders the passes, or clears the mark, so this holds.
4. **When it can't tell.** When two or more sets fit, the claim line warns `claim_receipts_unclear`: "{n} sets of
   {supplier}'s charges on {upload} add up to {amount}; can't tell which this line claims." with `related` on all the
   candidates, and the upload's first candidate warns the same, `related` on the line. Both stay booked as today
   until a person acts (edit a row, or remove one of them, or say Not the same). The warnings are worked out afresh,
   so they go when the books change.
5. **The records.** `Transaction` gets `recorded_by_refs: list[str]` (default empty): on a claim line booked from a
   set, every receipt's `document_ref`. `recorded_by` on that line is one Settlement for the set: `ref` the first
   receipt's ref (in date order), `amount` the set's total, `date` the latest receipt's, `kind` "receipt",
   `description` naming the supplier and the count ("TfL Customer Services, 7 charges, 6 to 27 Oct 2026"). A receipt
   left off a claim gets `left_off_claim: Optional[Settlement]` naming the claim line; `booked()` in `checks.py`
   treats it as it treats `recorded_by` (booked only when included). Both are cleared in `_cleared` and are matching
   outputs, like the others.
6. **Names.** The line names the supplier when `names_match` or `_named_in` agree, as today, and also when it is
   initials the other way round. Jenny's must pass: "TfL Customer Services" (the reader's counterparty) against
   "Jenny Hogg — Transport for London, Train". Today `names_match` says False: "Customer Services" and the claim's
   category ("Train") get in the way. The builder fixes this in the name rules for every caller, not only this pass,
   with tests that other names still don't match.
7. **The table and the card.**
   - The claim line's status says "Booked from {n} receipts: {supplier}, {total}" and lists them; its document card
     (`cardDocuments` in `frontend/src/lib/suggestions.ts`) opens the upload.
   - A receipt finds its claim line by `recorded_by_refs` as well as `recorded_by.ref` (`frontend/src/lib/ledger.ts`,
     the lookup by `claimed_in`), so its status reads "On Jenny Hogg's expense claim: owed to the claimant".
   - A `left_off_claim` row shows "not booked" with the `not_claimed` warning and Include.
   - `not_claimed` and `claim_receipts_unclear` get labels, and go under Documents on the to-do list
     (`frontend/src/lib/todo.ts`).
8. **Everyone else who reads the links.** `duplicates.py`, `questions.py`, `resolutions.py` (`_PARTNERS`,
   `_uploads_of`), `agent/tools.py` (`_MATCHES`) and the agent's prompt read `recorded_by` and `claimed_in`; each
   treats a set as it treats one receipt, so no duplicate or question is raised between a claim line and its own
   receipts, and the AI review sees a `not_claimed` row as a question for the person, not something to fix.

## Tests

- Jenny's case, in `tests/test_matching.py`, built from rows (no file): a claim line of £55.40 dated 31 Oct and eight
  TfL receipts on one upload. Seven are claimed and owed on 2110; the claim line is not booked; 5 Oct is not booked,
  warns `not_claimed`, sits on 2110, and is booked when included. Travel totals £55.40.
- The whole statement claimed (£61.50): all eight pair, no leftover.
- Two sets add up: nothing pairs, both warn `claim_receipts_unclear`, Travel as today.
- A set on two uploads adds up: the same.
- No set adds up: nothing changes from today.
- The line names another supplier (Trainline): no pairing.
- One receipt of the line's amount on the upload: today's one-receipt pairing, not the set.
- A receipt kept apart from the line (Not the same) is never in its set.
- A line ticked Include: booked as well, warns `booked_twice`.
- The order of rows makes no difference.
- Name tests: "TfL Customer Services" against "Jenny Hogg — Transport for London, Train"; and that names which
  should not match still don't.
- Frontend: the claim line's status and the receipt's status, in `frontend/src/lib/ledger.test.ts`.
- A live check, not a test: Jenny's books after an API restart (client 3) show the seven paired, the 5 Oct row asking,
  and the £55.40 line not booked.

## Left to the builder

- How to count the sets fast. A day-a-charge statement has about 30 receipts; count by the pennies, stopping at two,
  rather than trying every set. Above a limit (my call: 60 candidates) skip the upload, as if no set fitted.
- The exact wording of the statuses and warnings, in the app's plain voice.
- Where `recorded_by_refs` and `left_off_claim` go in `ledgersync/models.py` and `frontend/src/lib/api.ts`, with
  comments like their neighbours.
- Whether a statement read before 4f71949 needs anything: no, it is matched afresh like any other.
