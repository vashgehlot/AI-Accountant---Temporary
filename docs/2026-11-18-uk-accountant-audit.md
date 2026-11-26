# Super Accountant for UK accountants: where it fails today

**Date:** 18 November 2026 · **Based on:** the code on `robust-ledger` at 4a9dac6, plus the uncommitted work in the
tree (another session's hotel VAT rule among it); the live database, read for counts only; and the earlier audits
(the [7 October gap analysis](2026-10-07-accountant-gap-analysis.md), the
[4 November test](2026-11-04-accountant-test-findings.md), and the UAT rounds of
[10 November](uat-findings-2026-11-10.md) and [11 November](uat-findings-2026-11-11-round2.md)).

**Not done for this review:** no documents were read by the model, and the pages were not clicked through. Each
finding below comes from the code, with the line that shows it. Issues the UAT rounds fixed are not repeated.

---

## 1. How it is being used now

From the live database, as counts:

- **Clients:** 3 clients. All are limited companies, and all are VAT registered.
- **Uploads:** 68, all in November 2026: 35 photos, 29 PDFs and 3 spreadsheets.
- **Rows:** 134 in all: 68 receipts, 61 expense-claim lines and 5 invoices. **No bank statements have been uploaded.**
  So far the site is used for expense claims and their receipts. Bank matching, reconciliation, payroll and closing
  a year have been tried only in tests and UAT.
- **Receipt sizes:** most are small. 43 are under £25, 11 are £25 to £50, 9 are £50 to £250, and 5 are over £250.

The workflow is:

1. Add a client and its first year.
2. Upload its files.
3. The reader (Qwen through OpenRouter) turns each file into rows.
4. The rules book the rows: VAT, the document rules, and matching.
5. The AI review and the to-do list ask about what is left.
6. The trial balance, profit and loss, balance sheet, VAT figures and Excel export are worked from the rows.
7. The year is closed.

## 2. Receipts without a proper VAT invoice, today

This is the case the requested change is about. Today the app gives a different answer depending on how the
receipt came in:

| The receipt | What happens today | Live count |
|---|---|---|
| Prints its VAT, £250 or less | Reclaimed, with or without the supplier's VAT number (the accountant's ruling, `evidence_rules.py:168`) | 24 |
| Prints a VAT number or "VAT included", but no amount, £250 or less | VAT worked out at the account's rate (`checks.vat_implied`) | 4 |
| Says "not a VAT invoice" | VAT kept in the cost (`evidence_rules.py:161`). It asks for the VAT invoice only when a claim line shows VAT (`matching.py:1125`) | 6 |
| Shows no VAT at all | Booked gross; **nothing asks** (`evidence_rules.py:163`) | 35 |
| Prints its VAT, over £250 | **The whole cost is held in Suspense** until a full VAT invoice is uploaded (`evidence_rules.py:158`) | 0 |
| A UK hotel stay (in progress in another session, not committed) | 20% VAT booked and reclaimed, and the receipt asks for the property's VAT invoice (`checks.hotel_vat`) | 2 |
| An expense-claim line with no receipt | Booked as claimed, VAT reclaimed, "Get a VAT invoice for this" (`document_wanted`) | — |

**The biggest group is not what it seems.** 35 receipts show no VAT. 31 of them are on accounts that usually carry
standard-rated VAT. But 28 of those 31 are **Travel**, and most travel carries no VAT:

- rail, bus, Tube and air fares are zero-rated;
- on-street parking is outside the scope of VAT;
- many taxi drivers aren't VAT registered.

So "add 20% when the VAT is missing" would be wrong for most of the receipts it would touch. The VAT a receipt
"should have" has to come from what was bought and who sold it, not from the account.

## 3. Findings, worst first

**Severity:**
- **High:** wrong figures, or a legal or compliance problem.
- **Medium:** an accountant would be misled or slowed down.
- **Low:** an edge case.

**Status:**
- **New:** found in this review.
- **Known:** raised in an earlier audit and still open.

### VAT

| # | Sev. | Status | Finding | Where |
|---|---|---|---|---|
| 1 | High | New | **Car lease VAT is reclaimed in full.** The Vehicle Leasing account says only half the VAT on a car lease can be reclaimed, but no code applies that rule. When a leased car is available for private use, 50% of its VAT is blocked, so box 4 is over-claimed. | `accounts.py:246` (the definition is the only mention) |
| 2 | High | Known | **No VAT schemes.** A flat-rate client is booked as if it used standard VAT accounting: its input VAT is reclaimed and its output VAT is charged at the full rate, so every box is wrong. A cash-accounting client's VAT counts by invoice date, not by payment date. | `books.py:448`, `books.py:475` |
| 3 | High | New | **A receipt over £250 that prints its VAT is held whole in Suspense** until a full VAT invoice arrives. The cost is missing from its account in the profit and loss, not just the VAT from box 4. | `evidence_rules.py:158` |
| 4 | Medium | New | **A receipt that shows no VAT is booked gross, and nothing asks for the VAT invoice.** A receipt that says it is "not a VAT invoice" is treated the same, unless a claim line shows VAT. VAT on standard-rated purchases from VAT-registered sellers, such as fuel card slips or a car park's card slip, is lost without anyone being told. | `evidence_rules.py:161`, `evidence_rules.py:163`, `matching.py:1125` |
| 5 | Medium | Known | **VAT quarters follow the accounting year,** not the client's VAT stagger. | `frontend/src/lib/sections.ts:287` |
| 6 | Medium | New | **The domestic reverse charge for construction isn't handled.** The reverse-charge flag is set only for suppliers outside the UK. When a subcontractor's invoice falls under the domestic reverse charge, the VAT that belongs in boxes 1 and 4 is missing. | `adapter.py:37`, extractor rule 7 |
| 7 | Medium | New | **Fuel used privately:** all the VAT on fuel is reclaimed. There is no fuel scale charge and no business-mileage share. | Account 7300 has only a tax "check" |
| 8 | Medium | New | **Partial exemption isn't checked.** A client with exempt income (rent, 4904) reclaims all its input VAT, and nothing tests the de minimis limits. | — |
| 9 | Medium | Known | **Supplier VAT numbers aren't checked,** either by their check digits or against HMRC's lookup. A misread number still counts as evidence for reclaiming VAT: one photo's number was read as 670 487 106 in 6 reads of 6. | `adapter.py:152`, HANDOFF |
| 10 | Medium | New | **Nothing warns that a client must register.** For a client that isn't VAT registered, nothing checks whether its taxable turnover has passed £90,000 in any 12 months in a row. | — |
| 11 | Low | New | **Water (7202) is set as standard-rated.** Most business water and sewerage is zero-rated; only industrial users pay VAT on it. This does no harm while VAT is booked only when printed. But a rule that adds the VAT a receipt "should have" from the account's rate would add 20% to water bills. | `accounts.py:240` |
| 12 | Low | New | **Pre-registration VAT can't reach box 4.** The app says to add it by journal, but journals carry no VAT, and the VAT figures leave journals out. | `checks.py` (before_vat_registration), `books.py:448` |
| 13 | To confirm | — | **VAT is reclaimed from a receipt that prints VAT but no supplier VAT number,** and from an order summary's "estimated VAT". This follows the accountant's ruling. A simplified VAT invoice has to show the seller's VAT number, and without it HMRC can refuse the claim unless it accepts other evidence. It is worth confirming that the firm is content to carry that risk. | `evidence_rules.py:168` |

### Income tax and corporation tax

| # | Sev. | Status | Finding | Where |
|---|---|---|---|---|
| 14 | High | New | **There is no cash basis.** Since 2024-25 it has been the default for sole traders and partnerships, and it is the default for most landlords. The app books on accruals only, so a cash-basis client's SA103 figures include debtors and creditors they should leave out. | HANDOFF lists "a cash-basis setting" as not done |
| 15 | High | New | **Making Tax Digital for Income Tax.** Since 6 April 2026, sole traders and landlords with qualifying income over £50,000 must send HMRC quarterly updates on tax-year quarters. The app has neither tax-year quarters nor a way to submit. | — |
| 16 | High | Known | **Making Tax Digital for VAT.** The VAT figures are only a guide. Typing them into filing software breaks HMRC's digital-links rule. There is no export that bridging software can take, and no way to submit. | `books.py:448` |
| 17 | Medium | New | **Basis period reform isn't applied.** From 2024-25 a sole trader is taxed on the tax year, so a year end other than 31 March or 5 April needs its profit apportioned. The app doesn't split it. | — |
| 18 | Medium | Known | **Landlords are not covered.** There are no SA105 boxes, no section 24 restriction (finance costs give a 20% tax credit, not a deduction), and no property allowance. Only the SA103F boxes exist. | `accounts.py:56` |
| 19 | Medium | Known | **Companies have no tax computation.** There is no corporation tax computation (19% or 25%, with marginal relief), no capital allowances and no CT600. The 7 October question still stands: does the accountant finish the job here, or hand off? | — |
| 20 | Medium | New | **Subsistence is allowable by default.** For a sole trader, meals are allowable only when travelling away from the usual place of work. | `accounts.py:257` |
| 21 | Low | New | **Mileage isn't checked against the approved rates** (45p a mile, then 25p after 10,000 miles), and the VAT in the fuel part of mileage isn't reclaimed. | Account 7305 |
| 22 | Low | New | **The chat's s455 rate stops at loans made up to 5 April 2026,** and it rightly says a later loan's rate needs checking. Dividend tax rates rose by 2 points from 6 April 2026, so this year's loans are likely charged at 35.75%. Add it once confirmed. | `agent/prompt.py:135` |

### Data protection and handing off

| # | Sev. | Status | Finding | Where |
|---|---|---|---|---|
| 23 | High | New | **Document reads don't tell OpenRouter to avoid hosts that keep data.** The reader's route lacks the `data_collection: "deny"` setting that the chat sets. Receipts and statements hold personal data under UK GDPR. The fix is one line. | `model_client.py:157` against `agent/llm.py:36` |
| 24 | High | Known | **No logins or users.** It runs on localhost for one person, and needs logins before staff share it. | README |
| 25 | High | Known | **No processing agreement with the model provider,** and no choice of UK or EU routing. | 7 October gap I1 |
| 26 | High | Known | **The only export is Excel.** Nothing that IRIS, CCH, Taxfiler, Xero, QuickBooks, Sage or FreeAgent can import. | `export.py:39` |

### The hotel rule in progress (not committed)

| # | Sev. | Finding |
|---|---|---|
| 27 | Medium | **It books 20% VAT on any UK stay on Hotels.** Airbnb hosts and small guesthouses are often not VAT registered, so their stays carry no VAT to reclaim. The general rule for receipts without a VAT invoice should take its place rather than sit beside it. |

## 4. What the requested change has to get right

The change asked for: when a receipt should have had a VAT invoice and doesn't, book it as it should be, and ask
for the VAT invoice.

- **The VAT it should have comes from what was bought and who sold it,** not from the account. Most travel, cold
  food to take away, books, postage stamps and water carry none. A seller below the VAT threshold charges none.
- **One rule for every route.** Today a receipt on its own, a claim line and a hotel stay each answer the same
  question differently (section 2).
- **Box 4 should show how much of it is still waiting on a VAT invoice,** so the accountant decides before filing
  a return.
- **Asking needs somewhere to go.** There is no list of questions to send the client (HANDOFF: "Not done: the
  client question list").
- **When the VAT invoice arrives, it should take the receipt's place.** Today a receipt and an invoice for the
  same amount within three days are flagged as a possible duplicate (`duplicates.py`), and a person or the AI has
  to keep one.
