# Super Accountant: an accountant's test, 4 November 2026

**Date:** 4 November 2026 · **Branch:** `ai-accountant-demo` (d93ae44) · **Tested as:** a UK practice accountant
doing a limited company's books part-way through its first year.

**How it was run:**
- A separate copy of the site, with its own local MongoDB (`ledgersync_accountant_test` on port 27027), so no
  real data was touched.
- The documents went in two ways, as an accountant would use the site:
  - through the **Documents** route (`POST /api/analyze`), outside the chat;
  - then through **two chat reviews**.
- Cost: 7 document reads and 2 chat runs on `qwen/qwen3.8-27b` through OpenRouter.

This follows [the 7 October gap analysis](2026-10-07-accountant-gap-analysis.md). That one measured the product
against an accountant's whole job. This one looks at what goes wrong today when you use it.

---

## 1. The test client

**Ashdown Joinery Ltd:**
- limited company, VAT registered;
- a joinery subcontractor under CIS;
- director Priya Ashdown;
- first year 1 Apr 2026 to 31 Mar 2027;
- Starling current account (1200) and Starling savings (1210).

**Opening balances at 1 Apr 2026:**
- Bank £5,000.00 Dr;
- shares £100.00 Cr;
- retained earnings £4,900.00 Cr.

**Documents** (all made up; the files were kept in the session's scratchpad, not in the repo):

| File | What it holds | The trap in it |
|---|---|---|
| `starling-current-oct-2026.csv` | 15 lines, 1–30 Oct 2026, opening balance £8,200.00, closing £1,605.10 | April to September statements missing (the books start at £5,000.00); Stripe payout net of fees; Netflix on the business card; PAYE paid with no payroll report; £86.40 Screwfix with no receipt; transfer to savings |
| `currys-invoice-CB-55120.pdf` | Laptop £1,208.33 + VAT £241.67 = £1,450.00 | A capital item |
| `hiscox-policy-schedule-HX-778120.pdf` | Premium £1,125.00 + Insurance Premium Tax £135.00 = £1,260.00, cover 7 Oct 2026 to 6 Oct 2027 | IPT isn't VAT; the cover runs past the year end, so there's a prepayment |
| `jewson-invoice-JW-88812.pdf` | Timber £285.00 + VAT £57.00 = £342.00, dated 28 Sep, paid 30 Oct | A bill paid later |
| `sales-invoice-AJ-2041.pdf` | Labour £3,000 + materials £1,000 = £4,000; domestic reverse charge; CIS 20% on labour (£600); £3,400 due | CIS deduction and reverse charge |
| `ivy-receipt-12-10.txt` | Client dinner, £184.00 incl. £30.67 VAT | Entertainment (VAT blocked; disallowed for corporation tax) |
| `screwfix-receipt-03-10.txt` | Uploaded **after** the first chat review, outside the chat. By accident it stops at "VAT 20" (no VAT amount, no total) | A missing receipt arriving late; a cut-off document |

---

## 2. What worked

- **Matching:** the Currys, Hiscox and Jewson documents were matched to their bank lines and booked once.
- **Capital and VAT:** the laptop went to 0030 Office Equipment, and VAT on the client dinner was blocked.
- **Coding:**
  - the transfer to savings went to 1210;
  - the HMRC VAT payment went to 2202;
  - the director's withdrawal went to 2250.
- **Payroll:** "No payroll report for October 2026" was raised, and the chat asked for the report.
- **IPT:** the chat recognised that the £135.00 was Insurance Premium Tax, quoted the schedule ("Insurance is
  exempt from VAT"), and didn't reclaim it.
- **The cut-off receipt:** the chat noticed that its VAT amount isn't printed, and asked before booking £14.40.
- **Manual edits:** the chat left alone a row that the accountant had changed by hand.
- **The £50 rule in the chat:** the Screwfix payment was held in Suspense, with a clear question.

---

## 3. Flaws, worst first

**Severity:**
- **High:** it gives wrong numbers or says something untrue.
- **Medium:** it's slow, noisy, or gets the accountant's routine wrong.
- **Low:** a polish issue.

### F1. It says the bank agrees when it doesn't. (High)
- **What happened:**
  - The books show the Starling account at **-£1,594.90**; the statement says **£1,605.10**.
  - The Overview says "£3,200.00 less in the books than the statement", with no reason, and the summary's
    `problems` list is empty.
  - The first chat said the October statement "agrees to its printed balances", and the second said "nothing was
    wrongly booked".
- **Why it's wrong:** the statement opens at £8,200.00, but the books carry £5,000.00 at 1 April. Six months of
  statements are missing.
- **What it should do:**
  - Name the gap: "No Starling current statements for April to September 2026. The October statement opens at
    £8,200.00 but the books have £5,000.00."
  - Never call a bank account reconciled while there is a difference.

### F2. CIS deductions are left as money the customer owes, and the chat defends it. (High)
- **What happened:**
  - Sales invoice AJ-2041 (£4,000, CIS £600 on labour) and a payment of £3,400 leave **£600 in Debtors**, flagged
    `part_payment`.
  - The second chat said the £600 is "already accounted for in Debtors until the CIT credit arrives".
- **Why it's wrong:**
  - Fenwick will never pay the £600. It has gone to HMRC as CIS deducted.
  - A limited company sets CIS deducted against its own PAYE and NI (on its EPS), and claims any excess back from
    HMRC.
  - The £600 belongs on a "CIS deducted" asset, not on Debtors.
- **What makes it worse:** the explanation sounded right. A reviewer would believe it.

### F3. The same data gets two different answers. (High)
- **What happened:**
  - Through Documents, the £86.40 Screwfix payment with no receipt was booked to **5000 Purchases**, with no
    issue.
  - Through the chat, the same row went to **9998 Suspense**, with "Can you upload the receipt or invoice?".
- **Why:** the document rules (£50 and £250) and the questions run only when a chat turn runs
  (`questions.rule_questions` and `refresh`). The plain checks (`checks.py`) know nothing about them.

### F4. Changes made outside the chat don't reach the chat's books. (High)
- **What happened:**
  - The Screwfix receipt was uploaded through Documents. It was read and matched to the bank line (row 29 paid
    by row 16).
  - The question "Can you upload the receipt or invoice?" **stayed open**, the posted ledger **kept £86.40 in
    Suspense**, and the Overview showed **"Posted ledger: 2 changes not posted"**. Nothing happened until a new
    chat was opened.
  - Meanwhile the Trial balance page (rows) and the chat's trial balance (posted ledger) **disagreed**.
- **Why it matters:** an accountant uploads most files outside a chat. Today the AI's work goes stale the moment
  they do. This is the gap the background review fixes.

### F5. Warnings can't be dismissed, by the accountant or the AI. (Medium)
- **What happened:**
  - Row 11 (Hiscox) keeps "The invoice shows £135.00 VAT; none is booked." The £135 is IPT, so the warning is
    false.
  - The second chat "refused both my attempts to force the flag shut"; there is no action for it.
- **Why it matters:**
  - Warnings that can't be cleared become noise, and the accountant stops reading them.
  - This one also invites someone to "fix" it by reclaiming IPT as VAT.

### F6. The reader reports figures the document doesn't print. (Medium–High)
- **What happened:**
  - The Screwfix receipt ends at "Subtotal 72.00 / VAT 20". The reader booked it at **£86.40**, with the issue
    "The receipt shows **£14.40** VAT; none is booked".
  - Neither £86.40 nor £14.40 is on the receipt; they were worked out (or taken from the bank line).
- **Why it matters:**
  - It breaks the chat design's anti-goal, "Guessing a date or an amount", one layer below the agent.
  - The chat caught it; the Documents path didn't.
- **What it should do:** figures that are read and figures that are worked out must be told apart, and an issue
  must never say "the receipt shows" a figure it doesn't show.

### F7. Stripe payouts are treated as one sale. (Medium)
- **What happened:**
  - The £1,163.10 Stripe payout was booked as a sale of £1,163.10, with "A sale with no VAT shown".
  - The chat asked for "the invoice (or tell me the net amount and the VAT rate)".
- **Why it's wrong:**
  - A payout is gross sales less Stripe's fees (here £1,200.00 less £36.90) and refunds.
  - The document to ask for is the **Stripe payout report** for that date.
  - Booking VAT on the net payout understates both sales and VAT, and leaves the fees out.
- **Same pattern:** PayPal, Square, SumUp, Amazon, eBay and Shopify payouts.

### F8. It doesn't notice what an accountant would. (Medium)
Nothing was said about any of these:
- **Netflix £12.99** on the business card, which is probably personal (DLA, or a benefit in kind).
- **Hiscox cover to 6 Oct 2027**, past the 31 Mar 2027 year end: about £652 is a prepayment at the year end.
  Nothing has to happen in October, but the row should carry "runs past the year end".
- **The director's loan account** went **overdrawn by £2,000** (a debit balance). If it's still overdrawn nine
  months after the year end, s455 tax applies.
- **No savings statement** for 1210, although money was moved into it. The Overview does show "No statement this
  year", but it isn't one of the things the AI asks for.

### F9. The AI can't say what has changed. (Medium)
- **What happened:** the second chat was asked "What has changed since the last review?". It re-read the year,
  but didn't say "you uploaded the Screwfix receipt" or "you recoded Netflix to the director's loan account".
- **Why it matters:**
  - There is no record of changes (who changed what, and when) for it to read.
  - A background review needs that record to know what to look at, and to tell the accountant what it did.

### F10. Chat replies show their working and contradict the numbers. (Low–Medium)
- **Working on show:** the first reply began "Let me look at the documents and the full list of rows." and
  included "The zero-VAT resolution was refused, and rightly so". That is the agent's working, not an
  accountant's summary.
- **Contradiction:** the second reply said the £86.40 was "still held until that confirmation", while the posted
  trial balance it had just returned had nothing in Suspense.

### F11. A statement without its bank account fails after it has been read. (Low)
- **What happened:** a statement sent with no bank account was read in full (paid for), then refused with "Choose
  which bank account this statement is for." The read was thrown away.
- **Caveat:** this went through the API; the site's upload form may already force the choice.
- **What it should do:** keep the read, and ask which account it is.

---

## 4. What an accountant would want next

These come from the test and from the 7 October gaps that are still open.

| # | Feature | Why | From |
|---|---|---|---|
| N1 | **Background AI review**: every change that can move the numbers is reviewed without a chat, and what it did is shown with Undo | F3, F4 and F9; the accountant's normal way of working is uploading, not chatting | User's idea |
| N2 | **Missing paperwork**: gaps in the statement chain, months with no statement, accounts with no statement, bank lines over £50 with no document, payroll months missing | F1, F8; most of an accountant's time is chasing | Gap A4 |
| N3 | **Accept a warning with a reason**: for the accountant and the AI, recorded, reversible | F5 | New |
| N4 | **Queries for the client**: open questions gathered into a list the accountant can send, with answers coming back onto the rows | Most open questions (Stripe report, payroll, receipts) are the client's to answer | Gap H1 |
| N5 | **Remembered corrections**: "Netflix goes to the director's loan" applied next month without asking | Repeat work | Gap E1 |
| N6 | **UK rules the AI must know**: CIS (sales and purchases), payment processors' payouts, IPT, the domestic reverse charge, capital items, personal spending | F2, F6, F7, F8 | Gap K |
| N7 | **Year-end pointers**: prepayments and accruals from the periods printed on documents; DLA overdrawn | F8 | Gaps B2, B4 |
| N8 | **One set of books**: the posted ledger and the rows' trial balance kept in step automatically | F4 | Chat design's "later project" |
| N9 | **Change history**: who (a person or the AI) changed what and when, readable by the AI and the accountant | F9 | Gap C3 |

---

## 5. Reproducing the test

1. Start a MongoDB on port 27027. Add `api-accountant-test-8095` and `web-accountant-test-3007` to
   `.claude/launch.json`: they point the API at `mongodb://127.0.0.1:27027`, database
   `ledgersync_accountant_test`, `LEDGERSYNC_DEMO=1`.
2. Create the client and its opening balances as in section 1, then upload the six documents to year 2026-04-01
   (the statement with `bank_account=1200`).
3. Open a chat on the client: "Review Ashdown Joinery's books for the year so far and get them right."
4. Upload the Screwfix receipt through Documents. Change row 25 (Netflix) to 2250 by hand. Open a new chat: "What
   has changed since the last review? Bring the books up to date."

The documents should become a test case under `eval/agent_cases/ashdown/`, with hand-worked expected figures, as
part of the fixes (see the design).
