# Test books: six made-up UK clients' paperwork, years of it, to find where the app fails (design, 2026-11-18)

## Why

The user: "create a database to test my accounting software, it should have invoices, receipts, bank statements and
make it as real as possible, cover all the edge cases you can possibly think of, create database for multiple
years, don't make it to fit my application right now, it should help me find all the faults in the application and
where it is lacking."

What exists today is narrow. `eval/fixtures` has 33 single documents, `eval/jobs` has 7 small scenarios,
`demo/northbridge` has one month, and `eval/accountant_cases` has 5 clients given as reader rows (so the reader is
skipped). None of them spans more than one year. The 18 November audit found that no bank statement has been uploaded
live. So bank reconciliation, opening balances, closing and carrying a year forward, payroll and VAT quarters have
only been tried in unit tests and UAT.

The research (`research_notes/test-corpus/existing-datasets-and-benchmarks.md`) found:

- **No public set to reuse.** No public dataset or demo company has a UK business's books over several years with an
  answer key.
- **Failure modes the set must expose.** Benchmarks of AI bookkeeping found these:
  - errors that compound month by month
  - transactions invented or reused to force a reconciliation through
  - different answers on repeat runs
  - zero-rated vs exempt VAT confusion
  - the payment processor booked instead of what was bought
  - chains (receipt to bill to payment) that break
  - acting where it should stop and ask

## What it is

A generated set of the paperwork six made-up UK clients send their accountant, from 2023 to October 2026. It comes
with four things:

- **The answer key:** the books an accountant would produce from that paperwork, up to the final accounts.
- **The catalogue:** every edge case planted in the set, with the files and lines that hold it.
- **Standalone packs:** one for every edge case that doesn't need a client's history, about 330 of them. Together they
  are the quick set. A smoke list of about 60 of them checks a fix in minutes.
- **The generator:** a program that simulates each business first and prints the paperwork from the simulation, so
  the key and the papers always agree.

It is called the **test books** and lives in `testbooks/`.

## Goals

- **Real.** The paperwork looks and behaves like a real client's: real layouts and export formats, photos that look
  like phone photos, and clients who lose, repeat and delay things.
- **Finds faults and gaps.** It covers every edge case in the catalogue, including things the app doesn't attempt
  today: VAT schemes, year end, foreign currency, payroll, CIS and so on.
- **A key you can trust.** It is right to the penny and agrees with itself. Every figure traces to the papers.
- **Any software can use it.** Plain files: CSV, Excel, PDF, images. No dependence on this app.
- **Reproducible.** The same seed rebuilds the same set. Routine volume is a setting.
- **Usable in pieces.** One client-year at a time; the quick set (every pack); or the smoke list to check a fix.
- **Reviewed.** An accountant at the firm has checked the expected treatments before the set is trusted.

## Non-goals

- **Tax returns.** No CT600, SA100/103/105, SA800 or CIS300. The corporation tax charge that goes into a company's
  accounts is in. The CIS figures in the books are in.
- **The script that runs the set through this app and scores it.** That is a separate design, later, and it includes
  repeat runs and Pass^k scores. The key is shaped so it can be written.
- **Fixing the app.**
- **Real client data.** `eval/private` and `Test -realdocs` are not copied in.
- **Out of scope:** non-UK businesses, charities, groups and consolidation, partial exemption, audit work.

## Anti-goals (failure even if it "works")

- **A key that agrees with the app because it came from it.** The generator never imports `ledgersync` or follows
  the app's rules. Its rules come from HMRC guidance and accounting practice.
- **Paperwork too tidy to fail anything.**
- **Edge cases no real client would produce.**
- **A set that quietly changes between builds.**
- **Anything in it that could pass for a real bank's statement or a real shop's receipt.** See Names and identities.
- **Real people's details.**

## Constraints

- **Language:** Python 3.11, like the rest of the repo. The generator's dependencies go in
  `testbooks/requirements.txt`, open-licence only.
- **Runs locally:** on this Mac, with no network and no model calls at build time.
- **Where it lives:** the generator, client definitions and catalogue source are committed. The generated set goes to
  `testbooks/out/` and is git-ignored, since it will be roughly 1 GB of photos and PDFs.
- **Rates, thresholds and bank export layouts** come from `research_notes/test-corpus/uk-banks-and-tax-facts.md`. Each
  one keeps its source link in the generator's rates table.
  - **Rates by date.** Every rate is applied from its own date, including the ones that change part-way through a
    period. Examples:
    - employee NI on 6 January 2024
    - the VAT threshold on 1 April 2024
    - fuel scale charges from the first VAT period starting on or after 1 May
    - the temporary 5% VAT rate from 25 June to 1 September 2026
    - mileage at 55p, backdated to 6 April 2026
    - s455 following the dividend upper rate from 6 April 2026

    The 5% rate and the 55p mileage were checked on GOV.UK on 18 November 2026.
  - **Unconfirmed layouts.** Several banks publish no CSV specification, so their layouts come from forums and
    open-source importers: Barclays, HSBC, NatWest, Nationwide, Starling, Tide, Amex and Barclaycard. The catalogue
    marks those formats "layout unconfirmed", so a failure on one may be the layout's fault. A real export confirms a
    layout: its header and a few lines with the figures changed.
- **Build time:** a full build in under an hour; the quick set in under 10 minutes.

## Approaches

1. **Simulate the books, then print the paperwork (picked).** Each client's business is simulated day by day. An
   independent double-entry ledger writes the key from the simulation, and renderers print every document from it.
   A last pass adds the mess and logs it.
   - **Gains:**
     - the key always agrees with the papers to the penny
     - any size, and reproducible
     - each edge case lands exactly where the catalogue says
   - **Costs:** the most work up front. Variety is limited to the layouts written, so the plan has several per kind
     of document and checks the photos against real ones.
   - `eval/make_fixtures.py` already works this way on a small scale.
2. **An AI model writes the documents and the key.**
   - **Gains:** more natural variety.
   - **Costs:**
     - over thousands of documents the key drifts from the papers, so a failure might be the key's
     - it can't be resized or rebuilt
     - a model-written key shares blind spots with the model the app reads with
3. **Build on real documents** (the user's own and public ones such as the CORD receipt photos).
   - **Gains:** the most realistic look.
   - **Costs:**
     - far too few
     - none is a UK business's run of years
     - none has a key
     - real ones carry personal data
   - Used only to judge how real the generated photos look.

The user picked 1. From the research it takes these:

- plant an early error and see whether it is caught or carried
- include gaps that can only be "closed" by inventing a row
- give each client its own conventions and a prior-year history
- concentrate volume in a few frequent suppliers
- run statements through the known statement quirks (Bankstatemently's list)

## Decided with the user

- **Shape: both.** Whole client books with the edge cases inside ordinary months, plus a catalogue that points each
  case to its files, plus standalone packs for cases no client fits.
- **Six clients:** a web agency (Ltd), a builder (sole trader, CIS), a café (partnership), an online shop (new Ltd), a
  landlord (individual) and a design practice (LLP).
- **The key goes to final accounts.** It covers year-end adjustments and accounts. Tax returns are out.
- **The edge-case categories:**
  1. reading the paper
  2. what is it and should it be booked
  3. coding and VAT
  4. bank and matching
  5. periods and years
  6. owners
  7. year end
  8. suspicious
  9. the client's own mess

  The full list, 353 cases, is in `2026-11-18-test-books-edge-cases.md`.
- **The approach:** simulate first.
- **Packs:** every case that doesn't need a run of years gets a standalone pack, plus a smoke list. Decided after the
  builder review.
- **Review:** an accountant at the firm reviews the catalogue and the first client-year's key after build step 1, and
  the build waits for it. Decided after the builder review.

## The clients

Names are working names, all made up. The mix was agreed; the details below are my calls.

| Client | Type | Periods in the set | VAT | Staff | Accounts |
|---|---|---|---|---|---|
| Kestrel & Finch Digital Ltd, web agency, Bristol | Ltd, 2 director-shareholders 50/50 | Years to 31 Mar 2024, 2025, 2026; 1 Apr to 31 Oct 2026 | Standard, quarters to Feb/May/Aug/Nov | 2 directors and 5 staff, monthly | FRS 105 micro-entity |
| Daniel Mensah, DM Build & Renovate, Leeds | Sole trader, CIS subcontractor | Year to 30 Apr 2024; **11 months** to 31 Mar 2025 (moves to the tax year); year to 31 Mar 2026; 1 Apr to 31 Oct 2026 | Registers in 2024 on passing £90,000; construction reverse charge; quarters to Jan/Apr/Jul/Oct | None; from 2025 a CIS labourer, so also a contractor | Sole trader accounts, accruals (opted out of the cash basis) |
| Steep & Crumb, café, York | Partnership, 60/40, then 50/50 from 1 Jul 2025 | Years to 31 Dec 2023, 2024, 2025; 1 Jan to 31 Oct 2026 | Flat rate scheme 12.5%; leaves it in 2025 on passing £230,000 income, then standard with the hot/cold food split; quarters to Mar/Jun/Sep/Dec | 4 to 6 part-timers, 4-weekly, tips through payroll | Partnership accounts, accruals |
| Lumen & Loom Ltd, online homeware shop | New Ltd, 1 director, incorporated 1 Aug 2023 | **17 months** to 31 Dec 2024 (two CT periods); year to 31 Dec 2025; 1 Jan to 31 Oct 2026 | Registers voluntarily from 1 Oct 2023 (claims VAT on costs from before registration); monthly; postponed import VAT; exports zero-rated | Director from 2024; a part-time packer from 2025 | FRS 105 micro-entity |
| Grace Adeyemi, landlord, Nottingham | Individual, 4 homes: 2 through a letting agent, 1 self-managed, 1 owned 50/50 with her husband; one a furnished holiday let until April 2025 | Tax years to 5 Apr 2024, 2025, 2026; 6 Apr to 31 Oct 2026 | Not registered | None | Property income and expenses, **cash basis** (the default), per property and in total, her share of the joint one |
| Ashgrove Studio LLP, architecture, Manchester | LLP, 2 members, a third joins 1 Jan 2025 | Years to 30 Jun 2024, 2025, 2026; 1 Jul to 31 Oct 2026 | **Cash accounting scheme**, quarters to Jan/Apr/Jul/Oct | 2 staff, monthly | FRS 105 micro-entity |

Each client's first year opens from its previous accountant's last accounts and trial balance, which are part of its
paperwork. The exception is the shop, which is new. Each client also has the following.

**Banks and cards.** Between them the clients use every format in the research notes:

- Banks and cards: Barclays, HSBC, Lloyds, NatWest, Santander, Nationwide, Monzo, Starling, Revolut, Tide, Metro,
  Amex, Barclaycard.
- Platforms: Stripe, SumUp, PayPal, Wise, Shopify, Amazon, and the delivery and holiday-let platforms.

| Client | Accounts and platforms (suggested) |
|---|---|
| Agency | HSBC current, a savings account, Amex, Stripe |
| Builder | A personal Lloyds account used for everything; a Tide account opened in year 2 |
| Café | NatWest; SumUp; petty cash |
| Shop | Starling; Wise in GBP, USD and EUR; PayPal; Barclaycard; Shopify and Amazon reports |
| Landlord | Personal Santander account; Nationwide mortgages; agent statements |
| LLP | Metro; Revolut for euro and dollar spend |

Each export follows its bank's real layout (see Names and identities).

**Behaviour.** How tidy the client is:

- **Agency:** tidy. Monthly batches from an expense app; about 5% of receipts never arrive.
- **Builder:** messy. Crumpled photos, a yearly shoebox plus quarterly VAT batches once registered, about 25% of
  receipts lost.
- **Café:** paper-heavy. Weekly photos of invoices, some till Z-reads, a monthly takings spreadsheet.
- **Shop:** digital. Platform reports, emailed and foreign-language supplier invoices.
- **Landlord:** sporadic. Agent statements monthly by email, everything else in one batch in December.
- **LLP:** middling.

**Policies**, recorded in each client's profile so the key's choices can be checked:

- the basis (accruals or cash)
- depreciation by asset class: straight line, a full year in the year bought, none in the year sold
- capitalise from £500
- accrue and prepay items from £250
- stock at cost by first in, first out
- bad debts written off specifically
- the accounts standard

## The paperwork

**Kinds of document.** Every kind a client sends:

- **Invoices and related:**
  - sales invoices, in the client's own layout: software-style, Word-style, or a carbon invoice book for the builder
  - purchase invoices, with each supplier keeping its layout across the years
  - credit notes, statements of account, remittances, quotes, pro formas, order confirmations
- **Receipts:** thermal till receipts, card slips, e-receipts, app screenshots, tickets.
- **Bank:** bank and card statements; Stripe, SumUp, Shopify, Amazon, PayPal, delivery-platform and holiday-let
  platform reports.
- **Payroll and CIS:** payroll bureau summaries, payslips, employer payment records, pension schedules, CIS payment
  and deduction statements.
- **Property and loans:**
  - letting agent statements
  - mortgage, loan and hire purchase statements and agreements
  - tenancy and lease extracts
- **Company and partnership papers:**
  - board minutes for dividends
  - partnership and LLP agreement extracts for profit shares
  - incorporation papers
- **Tax and history:**
  - HMRC paperwork (return receipts, statements, penalties, postponed VAT statements), as the plain text a client
    copies from their online account
  - the previous accountant's accounts and trial balance
- **The client's own:** takings sheets, a mileage log, a cashbook, notes and emails.

**Formats:**

- PDFs, with and without a text layer
- JPEG, PNG and HEIC photos
- CSV, TSV and XLSX
- OFX and QIF
- EML emails
- DOCX
- ZIP

Some files are deliberately over 20 MB or 30 pages. Real clients send them, and they are catalogued as such.

**Realism.** Documents are rendered, then aged to a set quality level with Augraphy: fading, folds, shadows, lighting
and JPEG. Phone photos get a phone's angle and background. Several layouts are written for each kind of document that
comes from many issuers. Receipts use real till conventions: VAT summary codes, masked card numbers and authorisation
codes. Statements hit the statement quirks in the research notes:

- carried-forward balances
- descriptions over several lines
- rows split across pages
- trailing signs
- pending lines

**Names and identities:**

- Every person, client, supplier, customer, shop and bank that issues a printed document is made up. The layouts
  copy real ones, so nothing in the set can pass for a real bank's statement or a real shop's receipt.
- Bank exports keep each real bank's file layout, under a made-up bank's name. CSV, XLSX, OFX and QIF files carry no
  branding anyway; the layout is what is being tested.
- Real names appear only as the other side of a transaction line: HMRC, Stripe, Amazon, PayPal, TfL, DVLA, a
  streaming service. Platform exports follow those platforms' real column layouts.
- Identifiers:
  - **VAT numbers and UTRs** have valid check digits, except the ones planted to fail.
  - **NI numbers** use the QQ prefix, which HMRC never issues.
  - **Email addresses** use example.com.
- There is no visible watermark, because that could change how a reader treats a document. Each file's metadata,
  and the set's README, say it is synthetic test data.

## The mess

- **Background mess** follows each client's behaviour: receipts lost, photographed twice, sent late or misnamed. It is
  random but seeded, and every instance is logged in `mess.csv`.
- **Planted cases** are placed by the catalogue, inside ordinary months.
- **Deliveries.** Files arrive in dated batches (`inbox/<arrival date>/`), as they would by email. A batch can hold
  papers from two years, or papers for a year that is already closed.
- **The client's answers.** Each question the key says an accountant would ask has a dated reply in
  `answers/<date>/`. Some are helpful, some unhelpful ("no idea, ask Dave"), and some contradict the papers. The key
  says what the accountant does with each.

## The answer key

Each client-year has a `key/` folder of CSVs, plus `key.xlsx` with the same tables for people.

- **`documents.csv`:** one line per document. A photo of two receipts is two documents. Each line gives:
  - the file and arrival date
  - kind, issuer, number, date and currency
  - net, VAT and gross as printed
  - what to do with it: book, don't book, evidence only, a copy of another, belongs to another client, or wait for
    something else
  - why, and the catalogue IDs
- **`statement-lines.csv`:** every bank, card and platform line, with a stable ID and what it matches.
- **`entries.csv`:** every expected double-entry line. Each gives:
  - date, account, debit and credit
  - VAT treatment: standard, reduced, zero, exempt, outside scope, reverse charge, blocked or flat rate; plus the VAT
    amount
  - counterparty, and the source documents and statement lines
  - stakes, and any other account an accountant could fairly use
  - phase: books, year end or after answers
- **Per period:**
  - `bank-recs.csv`: each account each month, statement balance against book balance, with reconciling items
  - `vat-returns.csv`: boxes 1 to 9 for each return, under the client's scheme
  - `debtors.csv` and `creditors.csv`: open items at each month end
  - `payroll.csv`: each pay run, and what is owed at each month end
  - `mtd-updates.csv`: for the builder and the landlord, who come under Making Tax Digital for income tax from
    6 April 2026, the totals by HMRC category for the first two quarterly updates of 2026/27. These are bookkeeping
    summaries, not a tax return.
- **Per year:**
  - `opening-balances.csv`
  - `fixed-assets.csv`: the asset register, depreciation and disposals
  - `owners.csv`: director's loan, capital and current accounts
  - `year-end.csv`: the adjustments, each with its reason. These cover accruals, prepayments, depreciation, stock,
    bad debts, the corporation tax charge (with its working), dividends, and the profit share
  - `trial-balance.csv`: each account's opening balance, the books before year end, the adjustments and the final
    figure, plus a "before answers" column with Suspense
  - `accounts.xlsx`: the P&L and balance sheet in the entity's statutory headings, with comparatives
  - `queries.csv`: what an accountant would ask the client. For each: what it is about, why, the stakes, the answer
    file, and the effect on the books
- **Stakes:** each entry and query is one of
  - changes the tax (capital or revenue, VAT reclaimable or not, business or personal)
  - changes the accounts
  - presentation only
  - process only (asks the right question, no figures change)
- **Before and after answers.** Before answers, a queried item is where an accountant puts it: in Suspense, or on a
  best guess with the question. The key lists the acceptable places. After answers, there is one right treatment.
- **The chart.** A standard UK chart in Sage 50 numbering, which most UK accountants know, with each account's
  statement heading and tax treatment. Another chart can be compared through the headings.
- **The rules.** VAT, payroll, CIS, CT and accounts rules are coded from the research notes and HMRC guidance, with
  dated rates. Each rule has worked examples as tests. The corporation tax charge is worked out only as far as the
  accounts need: adjusted profit, capital allowances, and rates with marginal relief scaled for short periods.

Each client also has:

- `profile.json` and a one-page client information sheet
- `policies.json`
- `chart.csv`

## The catalogue and the packs

**The catalogue** is `catalogue.csv` and `catalogue.xlsx`. Each planted case has an ID, a title, a category, where it
is (client and year, or pack), its files and lines, what an accountant expects, its stakes, whether it needs a run of
years, and its source (a research link or accounting practice). The 18 November audit's open findings are planted as
cases too, so each one can be seen failing and, later, passing.

**Packs (decided with the user after the review).** Every case that doesn't need a run of years gets a pack in
`packs/<id>-<slug>/`. That is about 330 packs and roughly 800 to 1,000 files.

- **What a pack is.** A tiny client, generated by the same engine as the six: a profile, an opening position if the
  case needs one, the case's documents with just enough ordinary ones around it to be realistic, and its own key. So
  the engine treats "a client" and "a pack" alike from the first build step.
- **Planted twice.** A case is planted in its client's books as well as in its pack, wherever a client fits it. Cases
  marked PK are only in packs.
- **Not in packs.** A case that needs a run of years, such as carry-forward, a late paper after a close, or an early
  error carried, exists only in the client books. The catalogue says so.
- **The quick set** is all the packs: about an hour to read through the app.
- **The smoke list** is `packs/smoke.txt`, about 60 packs (around 150 files, about 10 minutes). It covers every
  category and every audit finding, for checking a fix quickly.

## How it is built

1. **Client definitions** in `testbooks/clients/`: profile, policies, accounts, counterparties and their habits,
   routine patterns and seasonality, and the planted cases by catalogue ID.
2. **Simulator.** Turns each definition into the events that happened: sales, purchases, pay runs, loans, transfers,
   VAT and FX, day by day, seeded.
3. **Ledger.** Independent double entry. It posts the events under each year's rules and the client's policies, runs
   the VAT returns, payroll, CIS, year ends and carry-forward, and writes the key.
4. **Renderers.** Print each document from its events, in its issuer's layout and format.
5. **Ageing.** Photo and scan effects, at the quality the client's behaviour and the case call for.
6. **Mess and delivery.** Background mess, arrival batches, the client's answers, and `mess.csv`.
7. **Checks** (below), then the README, the catalogue, the packs and a view by year (links, not copies).

## Checks: how we know the key is right

- Every trial balance balances. Every year's closing balance sheet is the next year's opening.
- Each bank account's book balance equals its statement balance at every month end, after the listed reconciling
  items.
- The VAT control account equals the returns, period by period.
- Debtors and creditors equal the open documents. Payroll, CIS and processor clearing accounts clear when paid.
- Every figure printed on a document equals its event. Text files and text-layer PDFs are read back to check;
  images are checked on the text before ageing.
- Every catalogue entry points to files and lines that exist and say what the entry says.
- The same seed rebuilds byte-identical CSV, JSON and text.
- The rules' worked examples pass.
- A test fails if the generator imports the app's code.
- **An accountant's review is required (decided with the user).** These checks prove the key agrees with itself, not
  that each treatment is right. The key's rules are written by an AI model from HMRC guidance, and the first review
  found three wrong entries in the edge-case list. So the build stops after step 1 until an accountant at the firm
  has checked two things:
  - the catalogue's expected treatments: 353 one-line entries, roughly 2 hours
  - the agency's year to 31 Mar 2024: its key against its paperwork, roughly half a day

  Their corrections are made before the rules are copied to the other clients. Until the review is done, the README
  and any results mark the key as unreviewed.

## Done when

- All six clients are built for all their periods, with their keys.
- Every catalogue category appears in the client books.
- Every case that doesn't need a run of years has a pack, and the smoke list covers every category and every audit
  finding.
- The accountant's review is done and its corrections are in.
- All the checks pass.
- The full build runs in under an hour and the quick set in under 10 minutes.
- `testbooks/README.md` says how to build it, what is in it and how to use the key.
- The user has looked at a mix of generated and real receipt photos and finds the generated ones believable.

## Build order

1. The engine and one client-year end to end: the agency's year to 31 Mar 2024, with plain text PDFs and CSVs, its
   key and the checks. Also a first handful of packs, to prove a pack is just a small client.
2. **The accountant's review** of the catalogue and that year's key. Their corrections are made before going on.
3. Paper realism: every document kind, the photo ageing, the statement layouts.
4. All six clients over all their periods: year ends, VAT schemes, payroll, CIS, platforms, FX.
5. The mess, deliveries, answers and catalogue.
6. All the packs, the smoke list, the quick set and the README.

Later, as its own design: running the set through the app and scoring it.

## Left to the builder

- **Code:** its structure and the internal formats between stages.
- **Look:** the templates and fonts (open licence), and the ageing settings, within the realism check.
- **Content:**
  - the names of suppliers, customers, shops and staff
  - amounts and seasonality
  - each planted case's details, as long as it matches its catalogue entry
- **Layouts:** how many per kind of document. At least three for kinds that come from many issuers.
- **Banks:** which bank goes to which account, as long as every researched format appears.
- **Key files:** exact column names, as long as the fields above are there.
- **Volume:** routine volume, aiming at roughly 4,000 to 5,000 files in the client books.
- **The smoke list:** which packs go in it, as long as it covers every category and every audit finding.

## My calls, for checking

- The periods and VAT schemes per client, including:
  - the builder's 11-month year
  - the café starting in January 2023
  - the shop's 17-month first period
  - cash accounting at the LLP
  - the flat rate scheme at the café
- Made-up issuers and banks on everything printed, with real export layouts.
- The Sage 50 numbering for the key's chart; FRS 105 for the companies and the LLP; the accounting policies above.
- The landlord on the cash basis, and the builder opted out of it.
- The corporation tax charge worked out for the accounts only.
- `testbooks/` in this repo, with the output git-ignored.
- No model calls at build time.
- After the review, three entries in the edge-case list were corrected:
  - **EC-0317:** the reverse charge still applies when an overseas supplier shows a UK VAT number (Notice 741A,
    5.17).
  - **EC-0154:** a UTC timestamp moves a payment made just after midnight in summer back a day, not forward.
  - **EC-0809:** UK company numbers have no check digit.
