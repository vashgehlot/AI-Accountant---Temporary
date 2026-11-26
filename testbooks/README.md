# Test books

Generated paperwork for made-up UK clients, with an accountant's answer key, for finding where bookkeeping software
gets the books wrong. The design is in `docs/superpowers/specs/2026-11-18-test-books-design.md`, and the 353 edge
cases in `docs/superpowers/specs/2026-11-18-test-books-edge-cases.md`.

**Everything is synthetic.** No real client, person or document is used, and nothing imports the app (a test checks
this). Every issuer of a printed document is made up; real names appear only as the other side of a transaction.

**The key is unreviewed.** An accountant at the firm checks the catalogue and the agency's first year before the set
is trusted or built further (build step 2). Until then, a difference between the key and the software may be the
key's fault.

## Build

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r testbooks/requirements.txt
.venv/bin/python -m testbooks build --out testbooks/out --seed 7 --client agency --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430
.venv/bin/python -m testbooks check testbooks/out/clients/agency
.venv/bin/python -m pytest testbooks/tests -q
```

The same seed rebuilds the same CSV, JSON and text files. `testbooks/out/` is git-ignored.

## What build step 1 contains

- **Kestrel & Finch Digital Ltd** (a web agency, limited company, VAT registered, 2 directors and 5 staff), year to
  31 March 2024: about 640 documents and the bank, card and Stripe exports, in the batches the client sends them, with
  47 planted edge cases.
- **Five packs:** one standalone case each (EC-0301, EC-0316, EC-0330, EC-0346, EC-0430).
- **The catalogue** (`catalogue.csv`, `catalogue.xlsx`) and **the review folder** (`review/`) for the accountant.

## The output

```
testbooks/out/
  README.txt  catalogue.csv  catalogue.xlsx  review/
  clients/agency/
    profile.json  policies.json  chart.csv
    inbox/<arrival date>/<file>       the paperwork, as the client sends it
    answers/<date>/<file>             the client's replies to the accountant's questions
    key/2024-03-31/                   the answer key (CSV, key.xlsx, accounts.xlsx, checks.txt)
  packs/<case>-<slug>/                the same shape, plus case.txt
```

The key's tables: `documents`, `statement-lines`, `entries`, `bank-recs`, `vat-returns`, `debtors`, `creditors`,
`payroll`, `opening-balances`, `fixed-assets`, `owners`, `year-end`, `trial-balance`, `queries`, `ct-working`,
`mess`. Every entry names its edge cases in `cases`. Money is in pounds to the penny; VAT boxes 6 to 9 are whole
pounds; box 5 is signed (negative is a repayment).

## How it works

A client module (`clients/agency.py`) describes the business: its opening position, routines and planted cases. The
simulator (`engine/simulate.py`) turns it into deals, adding payroll, VAT returns and the payments they make due. An
independent ledger (`books/`) posts the deals, reconciles the bank, makes the year-end adjustments and works out
the corporation tax and the accounts. Renderers (`render/`) print every document and statement from the same deals.
The checks (`checks.py`) then read the written files back and prove they agree.
