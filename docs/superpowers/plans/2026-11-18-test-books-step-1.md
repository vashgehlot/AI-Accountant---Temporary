# Test books, build step 1: the engine, the agency's first year and five packs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the test-books generator far enough to produce one complete, checked client-year and five packs:

- the agency's year to 31 March 2024: paperwork, answer key, checks
- five standalone packs
- the folder an accountant at the firm reviews before any more is built

**Architecture:** A seeded simulator turns a client definition into deals: the economic truth, each with its lines,
payments and documents. An independent double-entry ledger posts the deals and works out the answer key:

- VAT returns, payroll and bank reconciliations
- year-end adjustments, the corporation tax charge and the accounts

Renderers print each document and statement from the same deals. Checks then read the written files back and prove
they agree. A pack is a tiny client run through the same pipeline.

**Tech stack:** Python 3.11 (the repo's `.venv`); reportlab (PDFs); openpyxl (Excel); pypdf (reading PDFs back for
the checks); pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-test-books-design.md`, its edge-case list
`docs/superpowers/specs/2026-11-18-test-books-edge-cases.md`, and the research notes in `research_notes/test-corpus/`.
This plan is build step 1 of the design's build order. Step 2 is the accountant's review. Steps 3 to 6 get their own
plans after the review, because the review may change the rules.

## Global Constraints

- Everything lives in `testbooks/`. Nothing in it imports `ledgersync`, `server` or `eval`, and nothing calls a
  network or a model. A test enforces this.
- Dependencies go in `testbooks/requirements.txt`, open-licence only, pinned to exact versions.
- The generated set goes to `testbooks/out/`, which is git-ignored.
- **Made-up issuers and people.** Every person, client, supplier, customer, shop and bank that issues a printed
  document is made up.
  - Bank exports keep the real bank's file layout under a made-up bank's name.
  - Real names appear only as the other side of a transaction line (HMRC, Stripe).
- **Identifiers:**
  - VAT numbers have valid check digits, except planted bad ones.
  - NI numbers use the QQ prefix.
  - Email addresses use example.com.
- **Marked as synthetic.** No visible watermark. Every PDF's metadata subject is
  `Synthetic test data, not a real document`, and `testbooks/out/README.txt` says the same.
- **Reproducible.** The same seed rebuilds byte-identical CSV, JSON and text files. Iterate sorted sequences, never
  sets or unordered dicts, when writing output.
- **Rates by date.** Every rate comes from `testbooks/rules/rates.py`, applied from its own date, with its source link.
- **Money.** `decimal.Decimal` throughout, rounded to the penny with ROUND_HALF_UP. Never use float.
- **Tests:** run with `.venv/bin/python -m pytest testbooks/tests -q`. The app's own suite is slow and is not needed
  for this work.
- **Commits:**
  - Stage only the files a task names. The working tree holds other people's uncommitted work in `ledgersync/`,
    `server.py` and `tests/`.
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Mark it unreviewed.** Until the accountant's review is done, `testbooks/out/README.txt` and every
  `key/*/checks.txt` say the key is unreviewed.

## Review Focus

The inputs and failure modes most likely to bite, each pinned by a test in the task that owns it:

1. **Penny drift.** A document's lines must add up to its printed total, and to its payment, to the penny. VAT boxes
   1–5 are to the penny; boxes 6–9 are whole pounds, truncated. Tests: Task 4 (boxes), Task 6 (every deal adds up).
2. **Boundary dates.** A deal dated 29 Feb 2024 must land in the December–February return. Payments due on a bank
   holiday move: the VAT direct debit due 7 Apr 2023 (Good Friday) is collected on 13 Apr 2023, and CT due on 1 Jan
   2024 is paid on 29 Dec 2023. Tests: Task 1 and Task 6.
3. **Newest-first statements.** HSBC-layout exports list the newest line first, but the running balances must still
   chain in date order. Test: Task 9.
4. **Determinism.** Two builds with one seed must give identical CSV, JSON and text files. Test: Task 10.
5. **Signs on liability accounts and credits.** The card account (1240) holds a credit balance. Card charges are
   positive and payments negative in the Amex layout. A sales credit note reverses sales and output VAT. Tests:
   Task 7 and Task 9.

## Files

```
testbooks/
  __init__.py, __main__.py        CLI: python -m testbooks build | check
  requirements.txt, README.md
  money.py, ids.py, dates.py      pennies and VAT maths; VAT and NI numbers; working days and due dates
  rules/rates.py, vat.py, payroll.py
  books/chart.csv, chart.py       the key's chart (Sage 50 numbering)
  books/ledger.py, bank.py, year_end.py, accounts.py
  engine/model.py, simulate.py
  clients/agency.py               the agency: definition, routines, planted cases
  packs/definitions.py            the first five packs
  render/pdf.py, documents.py, statements.py, sheets.py
  key.py, build.py, checks.py, review.py
  catalogue/cases.csv, catalogue/__init__.py
  tests/test_*.py
```

**Output layout:**

```
testbooks/out/
  README.txt  catalogue.csv  catalogue.xlsx  review/
  clients/agency/
    profile.json  policies.json  chart.csv
    inbox/<arrival date>/<file>
    answers/<date>/<file>
    key/2024-03-31/  (the CSVs listed in Task 10, key.xlsx, accounts.xlsx, checks.txt)
  packs/<case id>-<slug>/  (the same shape, plus case.txt)
```

---

### Task 1: Scaffold, the independence guard, money, identifiers and dates

**Files:**
- Create: `testbooks/__init__.py`, `testbooks/requirements.txt`, `testbooks/money.py`, `testbooks/ids.py`,
  `testbooks/dates.py`, `testbooks/tests/__init__.py`, `testbooks/tests/test_foundations.py`
- Modify: `.gitignore` (add `testbooks/out/`)

**Interfaces:**
- Produces:
  - `pennies(x: Decimal | str | int) -> Decimal`
  - `vat_on(net: Decimal, rate: Decimal) -> Decimal`
  - `vat_in(gross: Decimal, rate: Decimal) -> Decimal` (the VAT inside a gross amount)
  - `whole_pounds(x: Decimal) -> int` (truncates toward zero)
  - `vat_number(rng: random.Random) -> str`, `vat_number_valid(s: str) -> bool`, `ni_number(rng) -> str`
  - `BANK_HOLIDAYS: frozenset[date]`, `is_working_day(d) -> bool`
  - `next_working_day(d) -> date` and `previous_working_day(d) -> date`: each returns `d` itself when it is a working
    day
  - `add_working_days(d, n) -> date`
  - `vat_deadline(period_end) -> date`, `vat_dd_date(period_end) -> date`, `paye_due(pay_date) -> date`,
    `ct_due(period_end) -> date`

- [ ] **Step 1: Write the failing tests** in `testbooks/tests/test_foundations.py`

```python
import ast, pathlib, random
from datetime import date
from decimal import Decimal as D
from testbooks.money import pennies, vat_on, vat_in, whole_pounds
from testbooks.ids import vat_number, vat_number_valid, ni_number
from testbooks.dates import (next_working_day, previous_working_day, vat_deadline, vat_dd_date,
                             paye_due, ct_due)

BANNED = {"ledgersync", "server", "eval", "eval_cases", "eval_scoring", "openai", "langchain", "httpx", "requests"}

def test_nothing_imports_the_app_or_the_network():
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in BANNED, f"{path} imports {name}"

def test_money():
    assert pennies("2.345") == D("2.35") and pennies(D("2.344")) == D("2.34")
    assert vat_on(D("1082.50"), D("0.20")) == D("216.50")
    assert vat_in(D("320.00"), D("0.20")) == D("53.33")
    assert whole_pounds(D("1234.99")) == 1234 and whole_pounds(D("-1234.99")) == -1234

def test_identifiers():
    rng = random.Random(1)
    assert all(len(n) == 9 and n.isdigit() and vat_number_valid(n) for n in (vat_number(rng) for _ in range(50)))
    assert vat_number_valid("284619331")
    assert not vat_number_valid("123456789")
    n = ni_number(rng)
    assert n[:2] == "QQ" and n[2:8].isdigit() and n[8] in "ABCD"

def test_working_days_and_due_dates():
    assert next_working_day(date(2024, 3, 29)) == date(2024, 4, 2)        # Good Friday, then Easter Monday
    assert previous_working_day(date(2024, 1, 1)) == date(2023, 12, 29)
    assert vat_deadline(date(2023, 5, 31)) == date(2023, 7, 7)
    assert vat_deadline(date(2024, 2, 29)) == date(2024, 4, 7)
    assert vat_dd_date(date(2023, 2, 28)) == date(2023, 4, 13)            # deadline is Good Friday 2023
    assert vat_dd_date(date(2023, 5, 31)) == date(2023, 7, 12)
    assert vat_dd_date(date(2024, 2, 29)) == date(2024, 4, 10)
    assert paye_due(date(2023, 4, 28)) == date(2023, 5, 22)
    assert paye_due(date(2023, 6, 28)) == date(2023, 7, 21)               # 22 Jul 2023 is a Saturday
    assert ct_due(date(2023, 3, 31)) == date(2023, 12, 29)                # 1 Jan 2024 is a bank holiday
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest testbooks/tests/test_foundations.py -q`. Expected: FAIL (imports).

- [ ] **Step 3: Implement**

- **`money.py`:** the four functions. `vat_in(g, r) = pennies(g * r / (1 + r))`.
- **`ids.py`, VAT numbers.** Validity: weights 8, 7, …, 2 on the first 7 digits, then add the last two digits as a
  number. The number is valid when the total mod 97 is 0, or when (total + 55) mod 97 is 0. `vat_number` picks 7
  digits (the first non-zero) and appends `(-weighted_sum) % 97` as two digits.
- **`ids.py`, NI numbers.** `ni_number` is `"QQ"`, six digits and one of A–D.
- **`dates.py`, bank holidays.** `BANK_HOLIDAYS` holds exactly these England and Wales dates (source:
  gov.uk/bank-holidays):
  - 2023-01-02, 04-07, 04-10, 05-01, 05-08, 05-29, 08-28, 12-25, 12-26
  - 2024-01-01, 03-29, 04-01, 05-06, 05-27, 08-26, 12-25, 12-26
  - 2025-01-01, 04-18, 04-21, 05-05, 05-26, 08-25, 12-25, 12-26
  - 2026-01-01, 04-03, 04-06, 05-04, 05-25, 08-31, 12-25, 12-28
  - 2027-01-01
- **`dates.py`, due dates:**
  - `vat_deadline`: for a month-end period, the 7th of the second month after it.
  - `vat_dd_date`: `add_working_days(vat_deadline(end), 3)`.
  - `paye_due`: the 22nd of the next month for pay dates on the 6th or later (the 22nd of the same month for the 1st
    to the 5th), moved to the previous working day.
  - `ct_due`: period end plus 9 months plus 1 day, moved to the previous working day.
- **`requirements.txt`:** install `reportlab`, `openpyxl` and `pypdf` into `.venv`, then write their exact installed
  versions here.

- [ ] **Step 4: Run the tests.** Expected: PASS.

- [ ] **Step 5: Commit** `testbooks/__init__.py testbooks/requirements.txt testbooks/money.py testbooks/ids.py
  testbooks/dates.py testbooks/tests/__init__.py testbooks/tests/test_foundations.py .gitignore`, with the message
  `feat(testbooks): scaffold, independence guard, money, identifiers and dates`.

---

### Task 2: Dated rates and the key's chart

**Files:**
- Create: `testbooks/rules/__init__.py`, `testbooks/rules/rates.py`, `testbooks/books/__init__.py`,
  `testbooks/books/chart.csv`, `testbooks/books/chart.py`, `testbooks/tests/test_rates_chart.py`

**Interfaces:**
- Produces:
  - `rate(name: str, on: date) -> Decimal`
  - `RATE_SOURCES: dict[str, str]`
  - `Account(code, name, kind, heading, tax)`, a frozen dataclass whose fields are all `str`
  - `CHART: dict[str, Account]`
  - `HEADINGS: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.rules.rates import rate, RATE_SOURCES
from testbooks.books.chart import CHART, HEADINGS

def test_rates_change_on_their_own_dates():
    assert rate("ni_employee_main", date(2024, 1, 5)) == D("0.12")
    assert rate("ni_employee_main", date(2024, 1, 6)) == D("0.10")
    assert rate("ni_employee_main", date(2024, 4, 6)) == D("0.08")
    assert rate("ni_employer", date(2025, 4, 5)) == D("0.138")
    assert rate("ni_employer", date(2025, 4, 6)) == D("0.15")
    assert rate("ni_st_month", date(2023, 4, 6)) == D("758") and rate("ni_st_month", date(2025, 4, 6)) == D("417")
    assert rate("employment_allowance", date(2025, 4, 6)) == D("10500")
    assert rate("vat_threshold", date(2024, 3, 31)) == D("85000")
    assert rate("vat_threshold", date(2024, 4, 1)) == D("90000")
    assert rate("mileage_car_first", date(2026, 4, 5)) == D("0.45")
    assert rate("mileage_car_first", date(2026, 4, 6)) == D("0.55")
    assert all(src.startswith("https://") for src in RATE_SOURCES.values())

def test_chart():
    for code in ("1100", "1200", "1240", "1290", "2100", "2200", "2201", "2202", "2210", "2220", "2230",
                 "2250", "2320", "3200", "3260", "4000", "7000", "7403", "7410", "8000", "9100", "9998"):
        assert code in CHART
    assert all(a.heading in HEADINGS for a in CHART.values())
    assert CHART["1240"].kind == "liability" and CHART["7403"].tax == "disallowable"
```

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement `rates.py`.** The table is `name -> [(from_date, value)]`, ascending, and `rate` picks the
  latest entry on or before `on`. Values come from `research_notes/test-corpus/uk-banks-and-tax-facts.md` §3.1, §3.2
  and §2.2, each with its source URL.

| Name | Values |
|---|---|
| `vat_standard` | 0.20 |
| `vat_reduced` | 0.05 |
| `vat_threshold` | 85000; 90000 from 2024-04-01 |
| `ni_employee_main` | 0.12; 0.10 from 2024-01-06; 0.08 from 2024-04-06 |
| `ni_employee_upper` | 0.02 |
| `ni_employer` | 0.138; 0.15 from 2025-04-06 |
| `ni_pt_month` | 1048 |
| `ni_uel_month` | 4189 |
| `ni_st_month` | 758; 417 from 2025-04-06 |
| `ni_pt_year` | 12570 |
| `ni_st_year` | 9100; 5000 from 2025-04-06 |
| `employment_allowance` | 5000; 10500 from 2025-04-06 |
| `paye_free_pay_month` | 1048.25 (code 1257L) |
| `paye_basic_limit_month` | 3142 |
| `income_tax_basic` / `income_tax_higher` | 0.20 / 0.40 |
| `pension_qe_lower_month` / `pension_qe_upper_month` | 520 / 4189 |
| `ct_small` / `ct_main` | 0.19 / 0.25 |
| `ct_lower` / `ct_upper` | 50000 / 250000 |
| `ct_mr_fraction` | 0.015 |
| `mileage_car_first` | 0.45; 0.55 from 2026-04-06 |
| `mileage_car_after` | 0.25 |
| `s455` | 0.3375; 0.3575 from 2026-04-06 |

The earliest "from" date for every rate is 2023-01-01.

- [ ] **Step 4: Implement `chart.py` and `chart.csv`.**
  - **CSV columns:** `code,name,kind,heading,tax`.
  - **`kind`** is one of asset, liability, equity, income, expense.
  - **`tax`** is one of allowable, disallowable, capital, not_trading, n/a.
  - **`HEADINGS`** are the FRS 105 lines:
    - P&L: Turnover; Other income; Cost of raw materials and consumables; Staff costs; Depreciation and other amounts
      written off assets; Other charges; Tax
    - Balance sheet: Called up share capital not paid; Fixed assets; Current assets; Prepayments and accrued income;
      Creditors: amounts falling due within one year; Creditors: amounts falling due after more than one year;
      Provisions for liabilities; Accruals and deferred income; Capital and reserves

  The step-1 chart is exactly these rows:

```
0030,Office equipment (computers) - cost,asset,Fixed assets,capital
0031,Office equipment (computers) - depreciation,asset,Fixed assets,capital
0040,Furniture and fixtures - cost,asset,Fixed assets,capital
0041,Furniture and fixtures - depreciation,asset,Fixed assets,capital
1100,Debtors control,asset,Current assets,n/a
1103,Prepayments,asset,Prepayments and accrued income,n/a
1200,Bank current account,asset,Current assets,n/a
1210,Bank deposit account,asset,Current assets,n/a
1240,Company credit card,liability,Creditors: amounts falling due within one year,n/a
1250,Payment processor clearing,asset,Current assets,n/a
1290,Transfers in transit,asset,Current assets,n/a
2100,Creditors control,liability,Creditors: amounts falling due within one year,n/a
2109,Accruals,liability,Accruals and deferred income,n/a
2125,Deferred income,liability,Accruals and deferred income,n/a
2200,VAT on sales,liability,Creditors: amounts falling due within one year,n/a
2201,VAT on purchases,liability,Creditors: amounts falling due within one year,n/a
2202,VAT liability,liability,Creditors: amounts falling due within one year,n/a
2210,PAYE and NI,liability,Creditors: amounts falling due within one year,n/a
2220,Net wages,liability,Creditors: amounts falling due within one year,n/a
2230,Pension contributions,liability,Creditors: amounts falling due within one year,n/a
2250,Director's loan - Hannah Finch,liability,Creditors: amounts falling due within one year,n/a
2251,Director's loan - Omar Kestrel,liability,Creditors: amounts falling due within one year,n/a
2320,Corporation tax,liability,Creditors: amounts falling due within one year,n/a
3000,Ordinary shares,equity,Capital and reserves,n/a
3200,Profit and loss account,equity,Capital and reserves,n/a
3260,Dividends,equity,Capital and reserves,n/a
4000,Sales - retainers,income,Turnover,allowable
4010,Sales - projects,income,Turnover,allowable
4906,Bank interest received,income,Other income,not_trading
5100,Freelancers,expense,Other charges,allowable
7000,Gross wages,expense,Staff costs,allowable
7001,Directors' salaries,expense,Staff costs,allowable
7006,Employer's NI,expense,Staff costs,allowable
7007,Employer's pension,expense,Staff costs,allowable
7100,Rent,expense,Other charges,allowable
7200,Electricity,expense,Other charges,allowable
7400,Travel,expense,Other charges,allowable
7403,Client entertainment,expense,Other charges,disallowable
7406,Subsistence,expense,Other charges,allowable
7410,Car lease,expense,Other charges,allowable
7500,Printing,expense,Other charges,allowable
7502,Telephone and internet,expense,Other charges,allowable
7504,Office stationery and small equipment,expense,Other charges,allowable
7550,Software and subscriptions,expense,Other charges,allowable
7601,Accountancy fees,expense,Other charges,allowable
7901,Bank charges,expense,Other charges,allowable
7905,Card processing fees,expense,Other charges,allowable
8000,Depreciation,expense,Depreciation and other amounts written off assets,disallowable
8100,Bad debts,expense,Other charges,allowable
8204,Insurance,expense,Other charges,allowable
8205,Staff welfare and entertainment,expense,Other charges,allowable
8250,Sundry and corrections,expense,Other charges,allowable
9100,Corporation tax charge,expense,Tax,n/a
9998,Suspense,asset,Current assets,n/a
```

- [ ] **Step 5: Run the tests.** Expected: PASS.
- [ ] **Step 6: Commit** these files, with the message `feat(testbooks): dated rates and the key's chart`.

---

### Task 3: The model and the agency's definition

**Files:**
- Create: `testbooks/engine/__init__.py`, `testbooks/engine/model.py`, `testbooks/clients/__init__.py`,
  `testbooks/clients/agency.py`, `testbooks/tests/test_agency_definition.py`

**Interfaces:**
- Produces, in `engine/model.py` (frozen dataclasses; tuples, not lists):
  - `VAT_CODES = ("standard", "reduced", "zero", "exempt", "outside", "reverse_charge", "blocked", "blocked_half",
    "none")`
  - `Line(description: str, account: str, net: Decimal, vat_code: str, vat: Decimal = 0, also_ok: tuple[str, ...] =
    (), stakes: str = "accounts")`
    - `.gross` is `net + vat`, except for `reverse_charge`, where it is `net`
  - `Payment(id: str, account: str, date: date, amount: Decimal, descriptor: str, type_code: str = "", against: str =
    "")`
    - `amount` is signed from the client's side: positive means money into that account
  - `JournalLine(account: str, debit: Decimal, credit: Decimal, description: str = "")`
  - `Doc(id, kind, issuer, recipient, number, date, currency="GBP", treatment="book", reason="", printed:
    dict[str, Decimal] = {}, extra: dict = {})`
    - `kind` is one of sales_invoice, sales_credit_note, void_invoice, purchase_invoice, receipt,
      order_confirmation, payroll_summary, employer_payment_record, board_minutes, expense_claim, letter,
      prior_accounts, prior_tb, client_sheet, bank_statement
    - `treatment` is one of book, not_booked, evidence, `copy_of:<id>`, other_client, `wait_for:<id>`
  - `Query(id, question, why, stakes, answer_date: date, answer_text: str, before: tuple[Line, ...] | None = None,
    answer_doc: Doc | None = None)`
  - `Deal(id, kind, date, counterparty, settles_via, lines=(), journal=(), payments=(), docs=(), cases=(),
    query=None, vat_boxes: dict[int, Decimal] = {}, covers: tuple[date, date] | None = None)`
    - `settles_via` is one of debtor, creditor, bank, director_loan, journal, transfer
    - `.gross` is the sum of its lines' `.gross`
  - `MoneyAccount(id, name, bank, layout, code, statement_day: int = 0)`
  - `Employee(id, name, director: bool, salary: Decimal, pension: bool, ni_number: str)`
  - `Owner(id, name, share: Decimal, loan_code: str)`
  - `Policies(basis, capitalise_from, accrue_from, depreciation_years: dict[str, int], accounts_standard,
    pension_ee, pension_er, known_accruals: tuple[tuple[str, str, Decimal, date], ...])`
    - each known accrual is (description, account, net amount, period end)
  - `Asset(id, description, cls, bought: date, cost: Decimal)`
  - `OpenItem(kind, counterparty, number, date, gross)`, where `kind` is "debtor" or "creditor"
  - `VatTotals(output, input, net_sales, net_purchases)`
  - `Opening(as_at, balances: dict[str, Decimal], open_items, assets, vat_brought_in: VatTotals, true_differences:
    dict[str, Decimal], prior_pl: dict[str, Decimal], reversals: tuple[tuple[str, str, Decimal], ...])`
    - `balances` are as received, with a debit positive
    - each reversal is (balance sheet account, P&L account, amount): last year's prepayments and accruals, reversed
      on the first day of the period
  - `Period(start: date, end: date, partial: bool = False)`
  - `Client(id, name, kind, address, company_number, vat_number, periods, vat_stagger: tuple[int, ...], accounts,
    employees, owners, policies, opening)`
- Produces, in `clients/agency.py`:
  - `define() -> Client`
  - `STEP1_CASES: tuple[str, ...]`, the IDs in the Task 6 table

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.clients import agency
from testbooks.ids import vat_number_valid

def test_agency_definition():
    c = agency.define()
    assert c.name == "Kestrel & Finch Digital Ltd" and c.kind == "ltd" and vat_number_valid(c.vat_number)
    assert [p.end for p in c.periods] == [date(2024, 3, 31), date(2025, 3, 31), date(2026, 3, 31), date(2026, 10, 31)]
    assert c.periods[-1].partial and c.vat_stagger == (2, 5, 8, 11)
    assert {a.id: a.code for a in c.accounts} == {"hsbc": "1200", "savings": "1210", "amex": "1240", "stripe": "1250"}
    assert sum(c.opening.balances.values()) == 0
    assert c.opening.balances["2202"] == D("-27100.00") and c.opening.true_differences == {"2202": D("-312.00")}
    assert c.opening.balances["2320"] == D("-14210.00") and c.opening.balances["3200"] == D("-32240.96")
    assert c.policies.capitalise_from == D("500") and c.policies.accrue_from == D("250")
    assert c.policies.depreciation_years == {"computer": 3, "furniture": 5}
```

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement `model.py`**, the dataclasses as listed.

- [ ] **Step 4: Implement `agency.define()`** with these values.

**The company:**

| Field | Value |
|---|---|
| `id` | `agency` |
| Address | Unit 4, 22 Harbour Wharf, Bristol BS1 6XX |
| Company number | 11873402 |
| VAT number | 284619331 |

**Periods:** as in the test, the last one partial.

**Money accounts:**

| `id` | Name | Bank | Layout | Code |
|---|---|---|---|---|
| hsbc | Business current | Severn Bank | `hsbc_csv` | 1200 |
| savings | Business deposit | Severn Bank | `hsbc_csv` | 1210 |
| amex | Business card | Calder Express | `amex_csv` | 1240 (statement day 3) |
| stripe | Card payments | Stripe | `stripe_csv` | 1250 |

**Employees:**
- **Directors:** Hannah Finch and Omar Kestrel, each £12,570 a year, no pension.
- **Staff,** each in the pension scheme:

| Name | Salary |
|---|---|
| Priya Nair | £28,000 |
| Daniel Okoro | £32,000 |
| Megan Whitlow | £36,000 |
| Tom Ashby | £45,000 |
| Leah Morgan | £52,000 |

**Owners:** Finch 50% with loan account 2250; Kestrel 50% with loan account 2251.

**Policies:**
- accruals basis; capitalise from 500; accrue from 250; computers 3 years, furniture 5 years
- accounts standard "FRS 105"; pension 0.05 employee, 0.03 employer
- known accrual: `("Accountancy fee 2023/24", "7601", 3000.00, 2024-03-31)`

**Opening balances at 31 Mar 2023**, as received from the previous accountant (debit positive):

| Code | Balance | Code | Balance |
|---|---|---|---|
| 0030 | 9,600.00 | 2100 | −5,880.00 |
| 0031 | −6,400.00 | 2109 | −2,400.00 |
| 0040 | 4,850.00 | 2200 | −10,560.00 |
| 0041 | −2,910.00 | 2201 | 1,980.00 |
| 1100 | 26,400.00 | 2202 | −27,100.00 |
| 1103 | 6,558.46 | 2210 | −5,812.36 |
| 1200 | 41,236.18 | 2230 | −1,067.12 |
| 1210 | 20,000.00 | 2250 | −1,200.00 |
| 1240 | −1,384.20 | 2320 | −14,210.00 |
| 1250 | 640.00 | 3000 | −100.00 |
| | | 3200 | −32,240.96 |

The `true_differences` are `{"2202": -312.00}`: the true liability for the December to February quarter is
£27,412.00 (EC-0512).

**Open items:**
- **Debtors** (the 1,100 balance):

| Number | Customer | Date | Gross |
|---|---|---|---|
| KF-0981 | Brightwater Homes Ltd | 1 Mar 2023 | £7,200.00 |
| KF-0984 | Northgate Dental Group | 1 Mar 2023 | £4,800.00 |
| KF-0990 | Lowther Interiors Ltd | 15 Mar 2023 | £8,400.00 |
| KF-0993 | Calder Valley Cycles | 27 Mar 2023 | £6,000.00 |

- **Creditors** (the 2100 balance):

| Number | Supplier | Date | Gross |
|---|---|---|---|
| INV-207 | Wyvern Freelance Studio (not VAT registered) | 20 Mar 2023 | £2,400.00 |
| 4471 | Avonside Print Ltd | 24 Mar 2023 | £1,080.00 |
| 99812 | Cabot Office Supplies | 28 Mar 2023 | £600.00 |
| BE-55120 | Brunel Energy | 15 Mar 2023 | £1,800.00 |

**Assets:**

| Asset | Bought | Cost |
|---|---|---|
| 3 laptops at £1,200 each | 10 May 2021 | £3,600 |
| 4 laptops at £1,500 each | 18 Jan 2022 | £6,000 |
| Office furniture | 1 Sep 2020 | £4,850 |

**VAT brought in** (March 2023): output 10,560.00, input 1,980.00, net sales 52,800.00, net purchases 9,900.00.

**Prepayments:**
- insurance £1,020.00 (October 2022 to September 2023 cover)
- rent £5,538.46 (84 of 91 days)

**`reversals`:**
- `("1103", "8204", 1020.00)`
- `("1103", "7100", 5538.46)`
- `("2109", "7601", 2400.00)`

**`prior_pl`:** plausible 2022/23 figures by P&L heading. They must be consistent with a profit before tax of about
£74,800, which is what the £14,210 corporation tax at 19% implies.

**`STEP1_CASES`:** the IDs in Task 6's table.

- [ ] **Step 5: Run the tests.** Expected: PASS.
- [ ] **Step 6: Commit** these files, with the message `feat(testbooks): the model and the agency's definition`.

---

### Task 4: VAT returns

**Files:**
- Create: `testbooks/rules/vat.py`, `testbooks/tests/test_vat.py`

**Interfaces:**
- Consumes: `Deal`, `Line`, `VatTotals` (Task 3); `vat_deadline`, `vat_dd_date`, `whole_pounds` (Task 1).
- Produces:
  - `VatReturn(start, end, box1, box2, box3, box4, box5, box6: int, box7: int, box8: int, box9: int, due: date, dd:
    date)`
  - `quarter_ends(stagger, start, end) -> list[tuple[date, date]]`
  - `reclaimable(line: Line) -> Decimal`
  - `vat_return(deals, start, end, brought_in: VatTotals | None = None) -> VatReturn`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.engine.model import Deal, Line, VatTotals
from testbooks.rules.vat import vat_return, quarter_ends

def mk(i, kind, d, net, vat, code, account, via):
    return Deal(id=i, kind=kind, date=d, counterparty="X", settles_via=via,
                lines=(Line("x", account, D(net), code, D(vat)),))

def test_boxes_for_a_quarter():
    deals = [mk("s1", "sale", date(2023, 6, 1), "1000.00", "200.00", "standard", "4010", "debtor"),
             mk("c1", "sale_credit", date(2023, 6, 9), "600.00", "120.00", "standard", "4000", "debtor"),
             mk("p1", "purchase", date(2023, 6, 2), "500.00", "100.00", "standard", "7500", "creditor"),
             mk("p2", "purchase", date(2023, 6, 3), "250.00", "50.00", "reverse_charge", "7550", "bank"),
             mk("p3", "purchase", date(2023, 6, 4), "155.00", "31.00", "blocked", "7403", "bank"),
             mk("p4", "purchase", date(2023, 6, 5), "420.00", "84.00", "blocked_half", "7410", "creditor"),
             mk("p5", "purchase", date(2023, 6, 6), "1950.00", "0.00", "exempt", "8204", "creditor"),
             mk("p6", "purchase", date(2023, 6, 7), "999.00", "0.00", "outside", "7000", "journal"),
             mk("s2", "sale", date(2023, 9, 1), "5000.00", "1000.00", "standard", "4010", "debtor")]
    r = vat_return(deals, date(2023, 6, 1), date(2023, 8, 31))
    assert (r.box1, r.box2, r.box3) == (D("130.00"), D("0.00"), D("130.00"))   # 200 - 120 credit + 50 RC
    assert r.box4 == D("192.00")                                               # 100 + 50 RC + 0 + 42
    assert r.box5 == D("-62.00")
    assert (r.box6, r.box7, r.box8, r.box9) == (650, 3275, 0, 0)               # 1000 - 600 + 250 RC; 500+250+155+420+1950
    assert (r.due, r.dd) == (date(2023, 10, 7), date(2023, 10, 11))

def test_brought_in_and_bad_debt_relief():
    bdr = Deal(id="b1", kind="bad_debt_relief", date=date(2024, 1, 31), counterparty="Lowther",
               settles_via="journal", vat_boxes={4: D("800.00")})
    rec = Deal(id="b2", kind="bad_debt_recovery", date=date(2024, 3, 20), counterparty="Lowther",
               settles_via="journal", vat_boxes={1: D("200.00")})
    assert vat_return([bdr, rec], date(2023, 12, 1), date(2024, 2, 29)).box4 == D("800.00")
    assert vat_return([bdr, rec], date(2024, 3, 1), date(2024, 5, 31)).box1 == D("200.00")
    bi = VatTotals(D("10560.00"), D("1980.00"), D("52800.00"), D("9900.00"))
    r0 = vat_return([], date(2023, 3, 1), date(2023, 5, 31), brought_in=bi)
    assert (r0.box1, r0.box4, r0.box6, r0.box7) == (D("10560.00"), D("1980.00"), 52800, 9900)

def test_quarters_feb_may_aug_nov():
    q = quarter_ends((2, 5, 8, 11), date(2023, 3, 1), date(2024, 5, 31))
    assert q[0] == (date(2023, 3, 1), date(2023, 5, 31)) and q[-1] == (date(2024, 3, 1), date(2024, 5, 31))
    assert (date(2023, 12, 1), date(2024, 2, 29)) in q
```

- [ ] **Step 2: Run.** Expected: FAIL.

- [ ] **Step 3: Implement**
  - **Tax point.** The tax point is `deal.date` (the standard accrual scheme).
  - **Which deals.**
    - Output side: `sale` and `sale_credit`. A credit note subtracts its VAT and net.
    - Input side: purchase-type kinds (`purchase`, `card_spend`, `director_expense`, `expense_claim`).
    - Payroll, tax payments, transfers and dividends never enter a return.
    - Every deal's `vat_boxes` are added as given.
  - **Lines that are left out.** In box 6 and box 7, `outside` lines are left out.
  - **`reclaimable`:**
    - standard, reduced, reverse_charge: `vat`
    - blocked_half: `pennies(vat / 2)`
    - everything else: 0
  - **Reverse charge.** Adds its VAT to box 1 and box 4, and its net to box 6 and box 7 (Notice 741A, research notes
    §2.8).
  - **Whole-pound boxes.** Boxes 6–9 are `whole_pounds` of the sums.
  - **Quarters.** `quarter_ends` gives three-month quarters ending on the last day of each stagger month.

- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit**, with the message `feat(testbooks): VAT returns`.

---

### Task 5: Payroll

**Files:**
- Create: `testbooks/rules/payroll.py`, `testbooks/tests/test_payroll.py`

**Interfaces:**
- Consumes: `Employee` (Task 3); `rate` (Task 2); `previous_working_day` (Task 1).
- Produces:
  - `Payslip(employee_id, pay_date, gross, tax, ee_ni, er_ni, ee_pension, er_pension, net)`
  - `PayRun(pay_date, payslips: tuple[Payslip, ...], ea_used: Decimal)`, with properties `gross`, `net`, `paye`
    (tax + ee_ni + er_ni − ea_used) and `pension`
  - `pay_date_for(year, month) -> date`: the 28th, or the previous working day
  - `payslip(emp, pay_date, ee_rate, er_rate) -> Payslip`
  - `pay_year(employees, tax_year_start_year: int, ee_rate, er_rate) -> list[PayRun]`: 12 runs, April to March

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.engine.model import Employee
from testbooks.rules.payroll import payslip, pay_year, pay_date_for

MEGAN = Employee("e3", "Megan Whitlow", False, D("36000"), True, "QQ123456C")
HANNAH = Employee("d1", "Hannah Finch", True, D("12570"), False, "QQ654321A")

def test_staff_payslip_april_2023():
    p = payslip(MEGAN, date(2023, 4, 28), D("0.05"), D("0.03"))
    assert (p.gross, p.ee_pension, p.tax, p.ee_ni, p.er_ni, p.er_pension, p.net) == (
        D("3000.00"), D("124.00"), D("365.40"), D("234.24"), D("309.40"), D("74.40"), D("2276.36"))

def test_employee_ni_falls_to_10_percent_from_6_january_2024():
    assert payslip(MEGAN, date(2024, 1, 26), D("0.05"), D("0.03")).ee_ni == D("195.20")

def test_pay_dates():
    assert pay_date_for(2023, 5) == date(2023, 5, 26) and pay_date_for(2024, 3) == date(2024, 3, 28)

def test_director_and_employment_allowance_over_the_year():
    runs = pay_year([HANNAH, MEGAN], 2023, D("0.05"), D("0.03"))
    assert len(runs) == 12 and runs[0].pay_date == date(2023, 4, 28)
    director_er = sum(p.er_ni for r in runs for p in r.payslips if p.employee_id == "d1")
    assert director_er == D("478.86")
    total_er = sum(p.er_ni for r in runs for p in r.payslips)
    assert sum(r.ea_used for r in runs) == min(D("5000"), total_er)
```

- [ ] **Step 3: Implement.** This is a plausible bureau payroll, not HMRC's exact tables. The key books whatever the
  report says.
  - **Gross:** `pennies(salary / 12)`.
  - **Pension (staff only, net pay arrangement):**
    - employee: `pennies(ee_rate × qualifying)`
    - employer: `pennies(er_rate × qualifying)`
    - qualifying = min(gross, `pension_qe_upper_month`) − `pension_qe_lower_month`, floored at 0
  - **Tax:** taxable = gross − employee pension − `paye_free_pay_month`, rounded down to the pound. 20% up to
    `paye_basic_limit_month`, 40% above.
  - **Employee NI:** the main rate on the amount between `ni_pt_month` and `ni_uel_month`, plus 2% above the UEL.
  - **Employer NI:** the employer rate on the amount above `ni_st_month`, rounded to the penny.
  - **Directors:** the same monthly thresholds, except that month 12 is adjusted so the year's employer NI equals
    the employer rate × (annual pay − `ni_st_year`).
  - **Employment Allowance:** `ea_used` takes from each run's employer NI, in order, until
    `rate("employment_allowance")` is used up.
  - **Tax year:** the tax year of a pay date decides the rates; month 1 is April.

- [ ] **Steps 2 and 4: Run** (FAIL, then PASS).
- [ ] **Step 5: Commit**, with the message `feat(testbooks): payroll`.

---

### Task 6: The simulator and the agency's year

**Files:**
- Create: `testbooks/engine/simulate.py`, `testbooks/tests/test_simulate_agency.py`
- Modify: `testbooks/clients/agency.py` (add `deals`)

**Interfaces:**
- Consumes: Tasks 1 to 5.
- Produces:
  - `World(client, deals: tuple[Deal, ...], vat_returns: tuple[VatReturn, ...], pay_runs: tuple[PayRun, ...])`
  - `simulate(client, until: date, seed: int) -> World`
  - `agency.deals(client, until, rng) -> list[Deal]`: routine and planted trading deals, with no tax payments
  - `CLIENTS: dict[str, tuple[Callable[[], Client], Callable]]`, holding `{"agency": (agency.define, agency.deals)}`

`simulate` does the following:

1. Calls the client's `deals`.
2. Adds pay runs from `pay_year`, as `kind="payroll"` journal deals:
   - Dr 7000/7001 (gross), 7006 (employer NI) and 7007 (employer pension)
   - Cr 2220 (net), 2210 (tax + employee NI + employer NI) and 2230 (pension)
   - the Employment Allowance used: Dr 2210, Cr 7006
3. Adds the payments that clear them:
   - net wages by BACS on the pay date (one HSBC line per person)
   - PAYE on `paye_due`
   - pension by direct debit on the 15th of the next month (next working day)
4. Adds VAT returns from `vat_return` for each quarter. The first quarter brings in March 2023. Each return is paid
   by direct debit on its `dd` if that is on or before `until`. The return for December 2022 to February 2023 is paid
   on 13 Apr 2023 at £27,412.00.
5. Adds the opening liabilities' payments:
   - March 2023 PAYE on 21 Apr 2023
   - March pension on 17 Apr 2023
   - the open items on plausible dates
   - CT of £13,987.00 on `ct_due(2023-03-31)` = 29 Dec 2023
6. Adds an `engagement` deal dated 12 Apr 2023 (`settles_via="journal"`, no journal lines). Its docs are the
   previous accountant's accounts (`prior_accounts`, PDF), their trial balance (`prior_tb`, XLSX, with the as-received
   balances) and the client information sheet (`client_sheet`, PDF), all with treatment `evidence`.
7. Sorts the deals by (date, id). IDs are `AG-0001…`, with docs `AG-D0001…` and payments `<account>-<yyyy-mm>-<nnnn>`.

**Agency routines,** from 1 Apr 2023 to `until`. Amounts are drawn from `rng` within these ranges:

| Routine | Rule |
|---|---|
| Retainers | Invoiced on the 1st of each month: Brightwater £6,000 and Northgate £4,000 net + 20% VAT. 30-day terms, paid by BACS (type CR) 20–35 days later. From 25 Mar 2024, retainers are invoiced on the 25th for the next month |
| Card-paying clients | Hartley Yoga £450, Moss & Pine Florists £600, Quayside Physio £750, Redcliffe Bakehouse £900 net + VAT. Paid through Stripe 3–10 days after invoicing. Fee 1.5% + £0.20 per charge. Payouts each Tuesday of the charges made by the previous Friday |
| Projects | 1–3 invoices a month, £3,000–£15,000 net + VAT, to a pool of 8 clients (Lowther Interiors Ltd among them). Paid 15–60 days later |
| Rent | Harbourside Estates Ltd (opted to tax). £6,000 + VAT on each quarter day (25 Mar, 24 Jun, 29 Sep, 25 Dec), paid by standing order that day (next working day). Covers the quarter |
| Electricity | Brunel Energy. Quarterly bill dated the 9th of the month after each calendar quarter, £1,500–£2,100 net + 20%, paid by direct debit 14 days later. Covers the quarter |
| Phone and internet | Northcliffe Telecom, £180 + VAT monthly, direct debit on the 5th |
| Car lease | Avon Vehicle Leasing, £420 + VAT monthly, direct debit on the 1st. A plug-in hybrid, 32 g/km |
| Software | Lumenhaus Software Ltd £96 + VAT monthly on Amex. Corrib Cloud Ltd (Ireland) £250 reverse charge monthly on Amex. Tallgrass Metrics Inc. $49 monthly on the HSBC debit card with a non-sterling fee line |
| Freelancers | Wyvern Freelance Studio, 1–2 invoices a month, £800–£3,000, no VAT. Paid by BP after 30 days |
| Print and supplies | Avonside Print Ltd and Cabot Office Supplies, 0–2 invoices a month, £100–£1,200 + VAT. Paid by BP |
| Card spend | 15–25 receipts a month on Amex or HSBC (VIS): subsistence £6–£40, travel £20–£180, taxis £12–£45 (no VAT), stationery £10–£90. Each with a receipt doc |
| Savings | £5,000 from HSBC to savings on the 2nd working day each month (`transfer`, legs through 1290). Interest at 1.5% a year on the last working day of Jun, Sep, Dec and Mar |
| Bank charges | £8.50 + £0.35 per electronic payment in the month before, on the 1st working day |
| Amex | Statement on the 3rd. HSBC pays its balance by direct debit on the 25th (next working day), as a `transfer` |
| Insurance | Severnside Insurance Brokers, 1 Oct 2023: premium £1,950.00 + Insurance Premium Tax £234.00 = £2,184.00 (exempt), paid by BP. Covers 1 Oct 2023 to 30 Sep 2024 |
| Previous accountant | Redland & Co's final fee for 2022/23 on 12 May 2023: £2,400 + VAT to 7601. The opening accrual's reversal offsets it. Paid by BP 30 days later |

Every deal for a service period sets `covers=(start, end)`. Monthly bills and retainers cover the calendar month they
are for.

**Planted in the year to 31 Mar 2024** (`STEP1_CASES` are the IDs in this table):

| Case | What happens | Expected posting (the key's) |
|---|---|---|
| EC-0152 | All HSBC exports in the HSBC layout | (format) |
| EC-0137 | In the March 2024 HSBC export, two BP references print as `1.23457E+15` | Booked; the reference is not used |
| EC-0501 | An extra HSBC export from 15 Mar to 14 Apr 2024 | Its lines are not booked twice |
| EC-0208 | 12 Jun 2023 order confirmation for a monitor arm, £89.99, "This is not a VAT invoice". VAT invoice dated 19 Jun 2023 (net 74.99, VAT 15.00) | Confirmation `not_booked`. 7504 74.99, 2201 15.00 from the invoice |
| EC-0210 | 6 Oct 2023: credit note CN-0007 to Northgate, £600 + £120, against the September retainer | Dr 4000 600, Dr 2200 120, Cr 1100 720 |
| EC-0211 | Invoice KF-1146 printed "VOID" | `not_booked` |
| EC-0225 | 1 Feb 2024: Lumenhaus annual plan, £1,440 + VAT, covering 1 Feb 2024 to 31 Jan 2025 | Prepayment of 1,203.93 at year end |
| EC-0226 | Rail e-ticket: fare £142.60 (zero-rated) + booking fee £1.50 (VAT £0.25) | 7400. Lines zero 142.60 and standard 1.25/0.25 |
| EC-0230 | Board minutes and interim dividends of £8,000 on 30 Jun, 30 Sep and 29 Dec 2023 and 28 Mar 2024, paid £4,000 to each director | Dr 3260, Cr 1200 |
| EC-0244 | 12 payroll summaries and 12 employer payment records | As Task 5 |
| EC-0301 | 14 Sep 2023 laptop, £1,082.50 + £216.50 | 0030 1,082.50; 2201 216.50 |
| EC-0303 | Nov 2023: monitor £480 net and chair £520 net, + VAT | Monitor 7504; chair 0040 |
| EC-0316 | Corrib Cloud monthly £250, "reverse charge" | 7550 250; 2201 50 Dr; 2200 50 Cr |
| EC-0318 | Tallgrass $49: HSBC VIS £38.62 and a `NON-STG TRANS FEE` £1.06 line | 7550 38.62 (reverse charge); fee 7901 |
| EC-0330 | 17 Oct 2023 dinner, £186.00 incl. VAT £31.00. The receipt says "Client: Brightwater" | 7403 186.00, VAT blocked |
| EC-0331 | 15 Dec 2023 staff party for 9, £1,140.00 incl. £190.00 VAT | 8205 950.00; 2201 190.00 |
| EC-0334 | Car lease monthly | 7410 462.00; 2201 42.00; 2100 Cr 504.00 |
| EC-0346 | 8 Feb 2024 till receipt, £320.00 printing VAT £53.33, no customer details. Query; the answer on 20 Feb 2024 is the full VAT invoice | Before answers: 7504 320.00. After: 7504 266.67, 2201 53.33 |
| EC-0352 | Rent quarterly, opted to tax | 7100; VAT reclaimed; 25 Mar 2024 quarter prepaid 5,538.46 |
| EC-0314 | The 1 Oct 2023 insurance premium with Insurance Premium Tax (exempt) | 8204 2,184.00, no VAT; prepaid 1,092.00 |
| EC-0372, EC-0373, EC-0375, EC-0380 | The payroll above. Employment Allowance on the employer payment record only | As Task 5 |
| EC-0401, EC-0430 | Card receipts and their bank lines. On 6 Mar 2024, two £4.50 coffees at one café with two receipts | Each booked once; both coffees booked |
| EC-0418 | The monthly savings transfer | Nets to 0 through 1290 |
| EC-0420 | Amex paid from HSBC | Transfer 1200 to 1240 |
| EC-0422 | Stripe charges on 28 and 29 Mar 2024, paid out on 2 Apr 2024 | 1250 balance at year end |
| EC-0435, EC-0437 | Savings interest; bank charges | 4906; 7901 |
| EC-0438 | HMRC payments: VAT (`HMRC VAT`, VAT number as reference); PAYE and CT (`HMRC CUMBERNAULD`, 13- and 17-character references) | To 2202, 2210, 2320 |
| EC-0502, EC-0706 | Retainers for April 2024 invoiced on 25 Mar 2024 (£12,700 net) | Deferred: Dr 4000, Cr 2125, 12,700.00 |
| EC-0505 | Brunel Energy bill dated 9 Apr 2024, covering January to March 2024 | Accrual of its net |
| EC-0506 | The known accrual | Dr 7601, Cr 2109, 3,000.00 |
| EC-0512 | The 13 Apr 2023 VAT direct debit of £27,412.00 leaves 2202 £312.00 overdrawn. Correction journal that day; query to the client and the previous accountant | Dr 8250 312.00, Cr 2202 312.00 |
| EC-0513 | The stagger | VAT at year end includes March 2024 |
| EC-0518 | A card purchase on 29 Feb 2024 | In the December–February return |
| EC-0519 | Payday 28 Mar 2024; Stripe payout 2 Apr 2024 | As dated |
| EC-0521 | March 2024 PAYE (due 22 Apr) and pension (15 Apr) | Owed at year end |
| EC-0601 | Streaming subscription £10.99 monthly on Amex (Finch's card). Query; answer "personal" | Dr 2250 |
| EC-0602 | Kestrel's October 2023 expense claim (XLSX, 3 receipts, £212.40), repaid on 15 Nov 2023 | Costs; Cr 2251, then cleared |
| EC-0705, EC-0363 | KF-1078 to Lowther Interiors Ltd, 5 Jun 2023, £4,000 + £800, due 5 Jul 2023. Administrator's letter 16 Oct 2023 (`letter`, evidence). Write-off 31 Jan 2024. The administrator pays £1,200 on 20 Mar 2024 | Write-off: Dr 8100 4,000, Dr 2201 800 (`vat_boxes={4: 800}`), Cr 1100 4,800. Recovery: Dr 1200 1,200, Cr 8100 1,000, Cr 2200 200 (`vat_boxes={1: 200}`) |
| EC-0707, EC-0708 | The CT charge; CT paid £13,987 against £14,210 provided | Task 8 |

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.clients import agency
from testbooks.engine.simulate import simulate

UNTIL = date(2024, 6, 30)

def world(seed=7):
    return simulate(agency.define(), until=UNTIL, seed=seed)

def test_deterministic_and_planted():
    a, b = world(), world()
    assert a.deals == b.deals
    assert set(agency.STEP1_CASES) <= {c for d in a.deals for c in d.cases}

def test_every_deal_adds_up_and_ids_are_unique():
    w = world()
    for d in w.deals:
        if d.settles_via == "bank":
            assert abs(sum(p.amount for p in d.payments)) == d.gross, d.id
        for doc in d.docs:
            if d.lines and "gross" in doc.printed and doc.treatment == "book":
                assert doc.printed["gross"] == d.gross, doc.id
    for ids in ([d.id for d in w.deals], [x.id for d in w.deals for x in d.docs],
                [p.id for d in w.deals for p in d.payments]):
        assert len(ids) == len(set(ids))

def test_tax_payments():
    w = world()
    vat = {p.date: -p.amount for d in w.deals if d.kind == "vat_payment" for p in d.payments}
    assert vat[date(2023, 4, 13)] == D("27412.00")
    for r in w.vat_returns:
        if r.dd <= UNTIL:
            assert vat[r.dd] == r.box5
    ct = next(d for d in w.deals if d.kind == "ct_payment")
    assert (ct.payments[0].date, ct.payments[0].amount) == (date(2023, 12, 29), D("-13987.00"))
    assert next(r for r in w.pay_runs if r.pay_date.year == 2024 and r.pay_date.month == 3).pay_date == date(2024, 3, 28)
    assert any(d.date == date(2024, 2, 29) for d in w.deals)
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): the simulator and the agency's year`.

---

### Task 7: Posting, the trial balance and bank reconciliations

**Files:**
- Create: `testbooks/books/ledger.py`, `testbooks/books/bank.py`, `testbooks/tests/test_ledger.py`

**Interfaces:**
- Consumes: `World`, `Deal`, `Period` (Tasks 3 and 6); `reclaimable` (Task 4); `CHART` (Task 2).
- Produces:
  - `Entry(id, journal_id, date, account, debit, credit, deal_id, doc_ids: tuple, line_ids: tuple, vat_code,
    vat, counterparty, stakes, also_ok: tuple, phase, cases: tuple)`
    - `phase` is one of opening, books, before_answers, year_end
  - `Books(entries: tuple[Entry, ...])`, with
    - `balance(code, as_at: date, phases=("opening", "books")) -> Decimal`
    - `balances(as_at, phases) -> dict[str, Decimal]`
  - `post(world, period) -> Books`
  - `StatementLine(id, account, date, type_code, description, amount, balance)`
  - `statement_lines(world, account_id) -> list[StatementLine]`
  - `BankRec(account, month_end, statement_balance, book_balance, items: tuple[tuple[str, Decimal, str], ...])`
  - `bank_rec(world, books, account_id, month_end) -> BankRec`

**Posting rules.** Each deal posts one journal on `deal.date`:

- **debtor:** Dr 1100 gross; Cr each line's account (net); Cr 2200 (VAT on standard and reduced lines).
  `sale_credit` reverses this. Each payment: Dr the payment's account, Cr 1100.
- **creditor:**
  - Dr each line's account: net + (VAT − `reclaimable`) for blocked and blocked_half
  - Dr 2201: `reclaimable`
  - reverse charge: also Cr 2200 VAT
  - Cr 2100: gross
  - each payment: Dr 2100, Cr the payment's account
- **bank:** as creditor, but crediting the payment's money account (`MoneyAccount.code`) instead of 2100. For
  income, the signs flip. Its payments post nothing more.
- **director_loan:** as creditor, crediting the owner's `loan_code`.
- **journal:** posts `deal.journal`. Each payment posts Dr or Cr its money account against `payment.against`.
- **transfer:** each payment posts its money account against 1290.
- **Opening:** posts `opening.balances` as `phase="opening"` on the period start, then posts each of
  `opening.reversals` that day as `phase="books"`.
  - A prepayment (1103) reverses as Dr the P&L account, Cr 1103.
  - An accrual (2109) reverses as Dr 2109, Cr the P&L account.
- **VAT return journal:** on each return's end date, move the period's 2200 and 2201 into 2202.
- **Before answers:** a deal whose `query.before` is set also posts its before-lines as `phase="before_answers"`.
  Its normal lines count as "after". `Books.before_answers(as_at) -> dict[str, Decimal]` gives the balances with each
  queried deal's `books` entries replaced by its `before_answers` entries.

`statement_lines` lists the account's payments sorted by (date, id), with a running balance from the opening balance
of that account's code. `bank_rec` reconciles that statement balance against the book balance of the account's code.
The items are the payments whose deal date and payment date fall on different sides of the month end.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.clients import agency
from testbooks.engine.simulate import simulate
from testbooks.books.ledger import post
from testbooks.books.bank import bank_rec

W = simulate(agency.define(), until=date(2024, 6, 30), seed=7)
P = W.client.periods[0]
B = post(W, P)

def rows(case, on=None):
    return {(e.account, e.debit, e.credit) for e in B.entries
            if case in e.cases and (on is None or e.date == on) and e.phase == "books"}

def test_trial_balance_balances():
    assert sum(B.balances(P.end, ("opening", "books")).values()) == 0

def test_planted_postings():
    assert rows("EC-0334", date(2023, 5, 1)) == {("7410", D("462.00"), D("0")), ("2201", D("42.00"), D("0")),
                                                 ("2100", D("0"), D("504.00"))}
    assert rows("EC-0210") == {("4000", D("600.00"), D("0")), ("2200", D("120.00"), D("0")),
                               ("1100", D("0"), D("720.00"))}
    assert rows("EC-0512") == {("8250", D("312.00"), D("0")), ("2202", D("0"), D("312.00"))}

def test_signs_and_transit():
    assert B.balance("1240", P.end) < 0                  # the card is owed
    assert B.balance("1290", P.end) == 0                 # no transfer in transit at 31 Mar 2024
    assert B.balance("1250", P.end) > 0                  # Stripe charges awaiting the 2 Apr payout

def test_bank_recs_tie_every_month():
    import calendar
    months = [(2023, m) for m in range(4, 13)] + [(2024, m) for m in range(1, 4)]
    for acc in ("hsbc", "savings", "amex", "stripe"):
        for y, m in months:
            month_end = date(y, m, calendar.monthrange(y, m)[1])
            r = bank_rec(W, B, acc, month_end)
            assert r.statement_balance - r.book_balance == sum(a for _, a, _ in r.items), (acc, month_end)

def test_opening_reversals():
    rev = {(e.account, e.debit, e.credit) for e in B.entries if e.date == P.start and e.phase == "books"}
    assert ("7100", D("5538.46"), D("0")) in rev and ("2109", D("2400.00"), D("0")) in rev
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): posting, trial balance, bank reconciliations`.

---

### Task 8: Year end, the corporation tax charge and the accounts

**Files:**
- Create: `testbooks/books/year_end.py`, `testbooks/books/accounts.py`, `testbooks/tests/test_year_end.py`

**Interfaces:**
- Consumes: `Books`, `Entry` and `post` (Task 7); `rate` (Task 2).
- Produces:
  - `Adjustment(id, kind, entries: tuple[Entry, ...], reason, cases)`
    - `kind` is one of accrual, prepayment, deferred_income, depreciation, ct_prior_year, ct_charge
  - `year_end(world, books, period) -> tuple[Adjustment, ...]`: the entries have `phase="year_end"` and are dated
    `period.end`
  - `ct_tax(taxable: Decimal, months: int) -> Decimal`
  - `CtWorking(profit_before_tax, add_backs: dict[str, Decimal], capital_allowances, taxable, tax)`
  - `Accounts(pl: tuple[tuple[str, Decimal, Decimal], ...], bs: tuple[...], profit_after_tax: Decimal)`: each row is
    (heading, this year, last year)
  - `accounts(books_with_adjustments, period, prior_pl) -> Accounts`

**Rules:**
- **Prepayments, accruals and deferred income** are worked by days, for items of £250 or more net.
  - **Prepaid:** a booked deal whose `covers` runs past `period.end` prepays its net × days after the year end ÷
    days covered.
  - **Accrued:** a bill dated after `period.end` (up to `until`) whose `covers` lies before or across the year end
    accrues its net × days in the period ÷ days covered. Each known accrual is also accrued.
  - **Deferred:** a sales invoice whose `covers` starts after `period.end` is deferred (EC-0502).
- **Depreciation:** straight line by `depreciation_years`, a full year in the year bought (the opening register plus
  capital lines in the period).
- **CT for prior years:** opening 2320 minus the CT paid in the year. Here that is Dr 2320 223.00, Cr 9100 223.00.
- **The CT charge:**
  - profit before tax from the books after the other adjustments
  - add back depreciation (8000) and the disallowable accounts (7403)
  - less capital allowances: full expensing, 100% of capital additions in the period
  - `ct_tax(taxable, 12)`; Dr 9100, Cr 2320
- **`ct_tax`:**
  - Scale the limits by months ÷ 12.
  - At or under the lower limit: 19%. At or over the upper limit: 25%.
  - Between them: 25% × taxable − (upper − taxable) × 3/200.
  - Round to the penny.
- **Accounts:**
  - Sum the final balances by `Account.heading`.
  - A director's loan with a debit balance is shown under Current assets.
  - Figures are shown positive. A credit-balance heading has its sign flipped; contra items, such as depreciation
    within Fixed assets, net off.
  - Profit after tax = income − expenses (tax included).

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from testbooks.books.year_end import year_end, ct_tax
from testbooks.books.accounts import accounts
from testbooks.tests.test_ledger import W, P, B

ADJ = year_end(W, B, P)

def amount(case, kind):
    return sum(e.debit for a in ADJ if a.kind == kind and case in a.cases for e in a.entries)

def test_ct_tax():
    assert ct_tax(D("80000"), 12) == D("17450.00")
    assert ct_tax(D("40000"), 12) == D("7600.00")
    assert ct_tax(D("300000"), 12) == D("75000.00")
    assert ct_tax(D("40000"), 5) == D("9037.50")

def test_agency_adjustments():
    assert amount("EC-0225", "prepayment") == D("1203.93")
    assert amount("EC-0352", "prepayment") == D("5538.46")
    assert amount("EC-0314", "prepayment") == D("1092.00")
    assert amount("EC-0502", "deferred_income") == D("12700.00")
    assert amount("EC-0506", "accrual") == D("3000.00")
    dep = {e.account: e.credit for a in ADJ if a.kind == "depreciation" for e in a.entries if e.credit}
    assert dep["0031"] == D("3560.83") and dep["0041"] == D("1074.00")
    prior = next(a for a in ADJ if a.kind == "ct_prior_year")
    assert {(e.account, e.debit, e.credit) for e in prior.entries} == {("2320", D("223.00"), D("0")),
                                                                       ("9100", D("0"), D("223.00"))}

def test_accounts_balance_and_reserves_roll():
    from testbooks.books.ledger import Books
    final = Books(B.entries + tuple(e for a in ADJ for e in a.entries))
    acc = accounts(final, P, W.client.opening.prior_pl)
    bs = dict((h, v) for h, v, _ in acc.bs)
    assert sum(final.balances(P.end, ("opening", "books", "year_end")).values()) == 0
    closing_reserves = D("32240.96") + acc.profit_after_tax - D("32000.00")
    assert bs["Capital and reserves"] == closing_reserves + D("100.00")
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): year end, CT charge, accounts`.

---

### Task 9: Plain renderers

**Files:**
- Create: `testbooks/render/__init__.py`, `testbooks/render/pdf.py`, `testbooks/render/documents.py`,
  `testbooks/render/statements.py`, `testbooks/render/sheets.py`, `testbooks/tests/test_render.py`

**Interfaces:**
- Consumes: `Doc`, `Deal`, `Client`, `MoneyAccount` (Task 3); `StatementLine` (Task 7).
- Produces:
  - `render_doc(doc, deal, client, out_dir: Path) -> Path`
  - `render_statement(account, lines, start, end, out_dir) -> Path`: writes `<start>_<account id>-statement_<end>.csv`
  - `hsbc_amount(x: Decimal) -> str`
  - `money_text(x, currency="GBP") -> str`: `£1,234.56`, or `$49.00`

**Rules:**
- **PDFs** (reportlab):
  - `invariant=1`; metadata subject `Synthetic test data, not a real document`; Helvetica
  - every figure in `doc.printed` printed with `money_text`
  - a VAT invoice prints the full Notice 700 §16 fields; a till receipt prints a simplified invoice
  - a `void_invoice` prints "VOID" across it
- **HSBC layout:**
  - header `Date,Type,Description,Amount,Balance`; CRLF line endings; UTF-8 with no BOM
  - dates `%d %b %Y`
  - amounts via `hsbc_amount`: trailing zeros trimmed to at least one decimal place
  - newest line first (by date, then id, descending)
  - EC-0137's references printed as `1.23457E+15`
- **Amex layout:**
  - header `Date,Description,Amount,Extended Details,Appears On Your Statement As,Address,Town/City,Postcode,Country,Reference,Category`
  - dates `dd/mm/yyyy`; charges positive, credits and payments negative; oldest first
  - one file per statement period, the 4th to the 3rd
- **Stripe layout:**
  - header `automatic_payout_id,automatic_payout_effective_at,balance_transaction_id,created_utc,currency,gross,fee,net,reporting_category,description,customer_name`
  - `currency` is `gbp`; one file per calendar month
- **Unconfirmed layouts.** The HSBC, Amex and Stripe layouts are marked "layout unconfirmed" in the catalogue.
- **Sheets** (openpyxl): the previous accountant's trial balance (`prior_tb`) and the expense claim (EC-0602).
- **Answers:** each answer is a text file; EC-0346's answer also renders its full VAT invoice PDF.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from decimal import Decimal as D
from pypdf import PdfReader
from testbooks.books.bank import StatementLine
from testbooks.engine.model import MoneyAccount
from testbooks.render.statements import render_statement, hsbc_amount
from testbooks.render.documents import render_doc
from testbooks.tests.test_ledger import W

HSBC = MoneyAccount("hsbc", "Business current", "Severn Bank", "hsbc_csv", "1200")

def test_hsbc_amounts():
    assert [hsbc_amount(D(x)) for x in ("-70.00", "1010.00", "276.10", "-80.78")] == ["-70.0", "1010.0", "276.1", "-80.78"]

def test_hsbc_csv_newest_first_and_balances_chain(tmp_path):
    lines = [StatementLine("l1", "hsbc", date(2024, 3, 1), "DD", "NORTHCLIFFE TELECOM", D("-216.00"), D("9784.00")),
             StatementLine("l2", "hsbc", date(2024, 3, 15), "CR", "BRIGHTWATER HOMES", D("7200.00"), D("16984.00"))]
    text = render_statement(HSBC, lines, date(2024, 3, 1), date(2024, 3, 31), tmp_path).read_bytes().decode()
    rows = text.split("\r\n")
    assert rows[0] == "Date,Type,Description,Amount,Balance"
    assert rows[1] == "15 Mar 2024,CR,BRIGHTWATER HOMES,7200.0,16984.0"
    assert rows[2] == "01 Mar 2024,DD,NORTHCLIFFE TELECOM,-216.0,9784.0"

def test_amex_signs_and_dates(tmp_path):
    amex = MoneyAccount("amex", "Business card", "Calder Express", "amex_csv", "1240", statement_day=3)
    lines = [StatementLine("a1", "amex", date(2024, 3, 5), "", "CORRIB CLOUD LTD", D("-250.00"), D("-250.00")),
             StatementLine("a2", "amex", date(2024, 3, 25), "", "PAYMENT RECEIVED - THANK YOU", D("1384.20"), D("1134.20"))]
    rows = render_statement(amex, lines, date(2024, 3, 4), date(2024, 4, 3), tmp_path).read_text().splitlines()
    assert rows[1].startswith("05/03/2024,CORRIB CLOUD LTD,250.00,")              # a charge prints positive
    assert rows[2].startswith("25/03/2024,PAYMENT RECEIVED - THANK YOU,-1384.20,")  # a payment prints negative

def test_invoice_pdf_prints_its_figures(tmp_path):
    deal = next(d for d in W.deals if "EC-0301" in d.cases)
    doc = next(x for x in deal.docs if x.treatment == "book")
    reader = PdfReader(render_doc(doc, deal, W.client, tmp_path))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "£1,082.50" in text and "£216.50" in text and "£1,299.00" in text
    assert reader.metadata.subject == "Synthetic test data, not a real document"
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message `feat(testbooks): plain renderers`.

---

### Task 10: The key writer and the build

**Files:**
- Create: `testbooks/key.py`, `testbooks/build.py`, `testbooks/__main__.py`, `testbooks/tests/test_build.py`

**Interfaces:**
- Consumes: Tasks 3 to 9.
- Produces:
  - `build(out: Path, seed: int, clients: Sequence[str], packs: Sequence[str] = (), until: date | None = None) ->
    list[Path]`, returning the client and pack folders written
  - `write_key(world, books, adjustments, period, client_dir: Path, delivered: dict[str, str]) -> Path`
    - `delivered` maps a doc id to its file path relative to `client_dir`
  - CLI: `python -m testbooks build --out testbooks/out --seed 7 [--client agency] [--packs ...] [--until
    2024-06-30]`

**Delivery:**
- **Documents:** each document and statement arrives on the 5th working day after the end of its month. It is
  written as `inbox/<arrival>/<doc date>_<issuer-slug>_<number-slug>.<ext>`; statements are named
  `<start>_<account id>-statement_<end>.csv`. Every file name therefore starts with its ISO date.
- **What `documents.csv` lists:** every delivered file dated on or before the period end, plus any later one the key
  relies on (such as EC-0505's April bill).
- **The `before_answers` column** comes from `Books.before_answers(period.end)`.
- **Engagement papers:** the prior accounts, the previous accountant's trial balance and the client information sheet
  arrive on 12 Apr 2023.
- **Answers:** written to `answers/<answer date>/<query id>.txt`.

**Key files** in `key/<period end>/`, CSV with `\n` line endings and these exact columns:

| File | Columns |
|---|---|
| documents.csv | doc_id,file,arrived,kind,issuer,recipient,number,date,currency,net,vat,gross,treatment,reason,cases |
| statement-lines.csv | line_id,account,date,type,description,amount,balance,deal_id,cases |
| entries.csv | entry_id,journal_id,date,account,account_name,debit,credit,vat_code,vat,counterparty,deal_id,doc_ids,line_ids,stakes,also_ok,phase,cases |
| bank-recs.csv | account,month_end,statement_balance,book_balance,item,item_amount,item_note |
| vat-returns.csv | period_start,period_end,box1,box2,box3,box4,box5,box6,box7,box8,box9,due,dd |
| debtors.csv, creditors.csv | as_at,counterparty,doc_id,number,date,gross,paid,owed |
| payroll.csv | pay_date,employee,gross,tax,ee_ni,er_ni,ee_pension,er_pension,net,ea_used |
| opening-balances.csv | account,name,debit,credit,source |
| fixed-assets.csv | asset_id,description,class,bought,cost,depreciation,accumulated,net_book_value |
| owners.csv | account,person,opening,increases,decreases,closing |
| year-end.csv | adjustment_id,kind,account,debit,credit,reason,cases |
| trial-balance.csv | account,name,heading,opening,books,before_answers,year_end,final |
| queries.csv | query_id,about,question,why,stakes,answer_file,answer_date,effect |
| ct-working.csv | item,amount |
| mess.csv | file,kind,detail (header only in step 1) |

Also written:
- `key.xlsx`: one sheet per CSV
- `accounts.xlsx`: P&L and balance sheet with comparatives
- `profile.json` and `policies.json` (sorted keys)
- `chart.csv`

- [ ] **Step 1: Write the failing tests**

```python
import csv, filecmp
from datetime import date
from pathlib import Path
from testbooks.build import build

def built(tmp_path, name):
    return build(tmp_path / name, seed=7, clients=["agency"], until=date(2024, 6, 30))[0]

def test_key_files_and_every_file_accounted_for(tmp_path):
    client = built(tmp_path, "a")
    key = client / "key" / "2024-03-31"
    with open(key / "entries.csv") as f:
        assert next(csv.reader(f)) == ["entry_id", "journal_id", "date", "account", "account_name", "debit", "credit",
                                       "vat_code", "vat", "counterparty", "deal_id", "doc_ids", "line_ids", "stakes",
                                       "also_ok", "phase", "cases"]
    listed = {r["file"] for r in csv.DictReader(open(key / "documents.csv"))}
    on_disk = {str(p.relative_to(client)) for p in (client / "inbox").rglob("*") if p.is_file()}
    assert listed <= on_disk
    assert {f for f in on_disk if Path(f).name[:10] <= "2024-03-31"} <= listed

def test_same_seed_same_bytes(tmp_path):
    a, b = built(tmp_path, "a"), built(tmp_path, "b")
    for p in sorted(a.rglob("*")):
        if p.suffix in {".csv", ".json", ".txt"}:
            assert filecmp.cmp(p, b / p.relative_to(a), shallow=False), p
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): key writer and build`.

---

### Task 11: Checks on the written set

**Files:**
- Create: `testbooks/checks.py`, `testbooks/tests/test_checks.py`
- Modify: `testbooks/build.py`: run the checks after writing; write `key/<period end>/checks.txt`, with one line per
  check and a first line `Key unreviewed: an accountant has not yet checked these treatments`; a failed check makes
  the build exit non-zero. Modify `testbooks/__main__.py`: add `check <client dir>`.

**Interfaces:**
- Produces:
  - `CheckResult(name: str, ok: bool, detail: str)`
  - `run_checks(client_dir: Path, period_end: date) -> list[CheckResult]`

The checks read only the written files, never the in-memory objects, so they verify what a user receives:

| Check | Passes when |
|---|---|
| `tb_balances` | The trial balance's opening, books and final columns each sum to 0 |
| `bank_recs_tie` | Each month's statement balance, recomputed by parsing the rendered statement files, equals `bank-recs.csv`'s statement balance, and statement minus book equals the sum of its items |
| `vat_control_ties` | Each return's box 5 equals that period's movement into 2202 |
| `debtors_creditors_tie` | Owed in `debtors.csv` equals 1100's balance at each month end; the same for `creditors.csv` and 2100 |
| `printed_figures` | Every PDF in `documents.csv` whose net, VAT or gross is filled contains each figure as `money_text` (via pypdf) |
| `statements_parse` | Every statement line in `statement-lines.csv` is in its file |
| `payroll_controls_clear` | At each month end, 2220 is 0, 2210 equals that month's `payroll.csv` (tax + ee_ni + er_ni − ea_used), and 2230 equals that month's pension. Passes trivially when there is no payroll |
| `opening_matches_prior_tb` | `opening-balances.csv` equals the previous accountant's trial balance file. Skipped when there is none, as in a pack |
| `catalogue_refs` | Every case ID in `entries.csv` and `documents.csv` exists in `catalogue/cases.csv` (skipped until Task 12 adds it) |

- [ ] **Step 1: Write the failing tests**: every check passes on a fresh build, and each fails on a doctored copy:

```python
import csv
from datetime import date
from decimal import Decimal as D
from testbooks.checks import run_checks
from testbooks.tests.test_build import built

def results(client):
    return {r.name: r.ok for r in run_checks(client, date(2024, 3, 31))}

def edit_csv(path, row, column, change, newline="\n"):
    rows = list(csv.reader(open(path, newline="")))
    rows[row][column] = change(rows[row][column])
    with open(path, "w", newline="") as f:
        csv.writer(f, lineterminator=newline).writerows(rows)

def test_all_pass(tmp_path):
    assert all(results(built(tmp_path, "a")).values())

def test_tb_and_bank_faults_are_caught(tmp_path):
    client = built(tmp_path, "a")
    key = client / "key" / "2024-03-31"
    edit_csv(key / "trial-balance.csv", 1, 7, lambda v: str(D(v) + 1))
    assert results(client)["tb_balances"] is False
    statement = sorted((client / "inbox").rglob("*_hsbc-statement_*.csv"))[0]
    edit_csv(statement, 1, 3, lambda v: str(D(v) + 1), newline="\r\n")
    assert results(client)["bank_recs_tie"] is False
```

Then one test per remaining check, each on a fresh build, each asserting that its check turns `False`:

| Check | Doctoring |
|---|---|
| `vat_control_ties` | Add 1 to box 5 of `vat-returns.csv` row 1 |
| `debtors_creditors_tie` | Delete the last data row of `debtors.csv` |
| `printed_figures` | Overwrite the first booked PDF with the bytes of a different booked PDF |
| `statements_parse` | Delete data row 1 of the first statement file |
| `payroll_controls_clear` | Add 1 to `tax` in `payroll.csv` row 1 |
| `opening_matches_prior_tb` | Add 1 to `debit` in `opening-balances.csv` row 1 |
| `catalogue_refs` | Set `cases` to `EC-9999` in `entries.csv` row 1 |

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): checks on the written set`.

---

### Task 12: The catalogue, the review folder and the README

**Files:**
- Create: `testbooks/catalogue/__init__.py`, `testbooks/catalogue/cases.csv`, `testbooks/review.py`,
  `testbooks/README.md`, `testbooks/tests/test_catalogue.py`
- Modify: `testbooks/build.py` (write `out/catalogue.csv`, `out/catalogue.xlsx`, `out/README.txt`, and `out/review/`)

**Interfaces:**
- Produces:
  - `Case(id, category, title, where, expects, stakes, needs_years: bool, layout_unconfirmed: bool, step: int |
    None)`
  - `load_cases() -> list[Case]`
  - `write_review(out: Path) -> Path`

**The catalogue source.** Convert the 13 tables of the edge-case list into `cases.csv` once, with a throwaway script
kept in the scratchpad, not the repo.

- **Columns:** `id,category,title,where,expects,stakes,needs_years,layout_unconfirmed,step`.
- **`needs_years`:** Y for the IDs in the list's "Cases that need a run of years" table.
- **`layout_unconfirmed`:** Y for the cases that depend on an unconfirmed layout: EC-0150 to EC-0156, and EC-0134.
- **`step`:** 1 for `STEP1_CASES` and the five pack cases.

**The review folder** is `out/review/`:
- **`README.txt`, in plain words for an accountant,** saying:
  - what the set is (synthetic, unreviewed)
  - what to check, with times:
    - (a) `catalogue.xlsx`: is each "An accountant expects" right? Roughly 2 hours.
    - (b) the agency's year to 31 Mar 2024: `key.xlsx` and `accounts.xlsx` against the paperwork in
      `clients/agency/inbox`, roughly half a day.
  - how to record answers: the three reviewer columns, and notes against any key row by its `entry_id`
- **`catalogue.xlsx`:** the catalogue plus three empty reviewer columns: `Agree? (Y/N)`, `Correct treatment`,
  `Notes`.
- **The agency's key:** a copy of `key.xlsx` and `accounts.xlsx` for the year to 31 Mar 2024.

**`testbooks/README.md`:** how to build, what step 1 contains, and that the key is unreviewed until the accountant
signs off.

- [ ] **Step 1: Write the failing tests**

```python
import re
from pathlib import Path
from openpyxl import load_workbook
from testbooks.catalogue import load_cases
from testbooks.clients import agency

DOC = Path(__file__).resolve().parents[2] / "docs/superpowers/specs/2026-11-18-test-books-edge-cases.md"

def test_catalogue_matches_the_edge_case_list():
    ids_in_doc = re.findall(r"^\| (EC-\d{4}) \|", DOC.read_text(), flags=re.M)
    cases = load_cases()
    assert [c.id for c in cases] == ids_in_doc and len(cases) == 353
    assert all(c.category == c.id[3:5] for c in cases)
    assert set(agency.STEP1_CASES) <= {c.id for c in cases if c.step == 1}

def test_review_folder(tmp_path):
    from testbooks.tests.test_build import built
    built(tmp_path, "a")
    review = tmp_path / "a" / "review"
    ws = load_workbook(review / "catalogue.xlsx").active
    header = [c.value for c in ws[1]]
    assert header[-3:] == ["Agree? (Y/N)", "Correct treatment", "Notes"] and ws.max_row == 354
    text = (review / "README.txt").read_text()
    assert "unreviewed" in text and "clients/agency/inbox" in text
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message
  `feat(testbooks): catalogue, review folder, README`.

---

### Task 13: The first five packs

**Files:**
- Create: `testbooks/packs/__init__.py`, `testbooks/packs/definitions.py`, `testbooks/tests/test_packs.py`
- Modify: `testbooks/build.py` (`--packs` builds `out/packs/<id>-<slug>/`, with `case.txt` taken from the catalogue
  row); `testbooks/engine/simulate.py` (register the packs in `CLIENTS` as `pack:<id>`)

**Interfaces:**
- Produces: `PACKS: dict[str, tuple[Callable[[], Client], Callable]]`, keyed by case ID.

**What a pack is.** A pack is a `Client` with:
- `kind` = "pack"
- one period, 1 to 30 Jun 2024
- one money account (`hsbc_csv`)
- opening balances: 1200 £5,000.00 and 3200 −£5,000.00
- no payroll and no tax payments
- its VAT return for June 2024, shown with no payment

Its deals are two ordinary card lunches, one sales invoice paid in the month, and the case:

| Pack | The case | The key must show |
|---|---|---|
| EC-0301-laptop-bought | Laptop £1,299.00 incl. £216.50 VAT, invoice, paid by BP | 0030 1,082.50; 2201 216.50 |
| EC-0316-overseas-software | Irish software £250, "reverse charge", paid by card | 7550 250; 2201 50 Dr and 2200 50 Cr; box 1 and box 4 at 50 |
| EC-0330-client-dinner | Dinner £186.00 incl. £31.00 VAT, "Client: Brightwater" | 7403 186.00; nothing on 2201 |
| EC-0346-receipt-over-250 | Till receipt £320.00 printing £53.33 VAT, no customer details | Before answers 7504 320.00; after answers (full invoice) 7504 266.67 and 2201 53.33 |
| EC-0430-two-coffees | Two £4.50 coffees, same café, same day, two receipts, two bank lines | Two entries of 4.50, neither marked a copy |

- [ ] **Step 1: Write the failing tests**

```python
import csv
from datetime import date
from decimal import Decimal as D
from testbooks.build import build
from testbooks.checks import run_checks

def test_packs_build_and_pass(tmp_path):
    folders = build(tmp_path, seed=7, clients=[], packs=["EC-0301", "EC-0316", "EC-0330", "EC-0346", "EC-0430"])
    assert len(folders) == 5
    for f in folders:
        assert (f / "case.txt").exists()
        assert all(r.ok for r in run_checks(f, date(2024, 6, 30)))

def test_client_dinner_pack_blocks_the_vat(tmp_path):
    f = build(tmp_path, seed=7, clients=[], packs=["EC-0330"])[0]
    rows = [r for r in csv.DictReader(open(f / "key" / "2024-06-30" / "entries.csv")) if "EC-0330" in r["cases"]]
    assert {(r["account"], r["debit"]) for r in rows if r["debit"] != "0.00"} == {("7403", "186.00")}
    assert not any(r["account"] == "2201" for r in rows)
```

- [ ] **Steps 2 to 5:** run (FAIL), implement, run (PASS), commit with the message `feat(testbooks): first five packs`.

- [ ] **Step 6: The full step-1 build.**
  - **Build:** `.venv/bin/python -m testbooks build --out testbooks/out --seed 7 --client agency --packs
    EC-0301,EC-0316,EC-0330,EC-0346,EC-0430 --until 2024-06-30`.
  - **Expected:**
    - exit code 0
    - every `checks.txt` reads all-pass
    - `testbooks/out/review/` exists
    - it finishes in under 2 minutes
  - **Then run** `.venv/bin/python -m pytest testbooks/tests -q`. Expected: all pass.

**Then stop.** Build step 2 is the accountant's review of `testbooks/out/review/`. Steps 3 to 6 are planned after it.
