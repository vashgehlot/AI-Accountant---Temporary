# Test Books Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A command-line runner in `testbooks_runner/` that puts the test books' clients and packs through Super
Accountant on its own databases, records every model call through a relay, and scores the books against the answer
key by catalogue case, with verdicts, run-to-run comparison and Pass^k.

**Architecture:** The runner is an outside program. It starts copies of the app (`server.py`) as subprocesses, each on
its own MongoDB database, with `OPENROUTER_BASE_URL` pointed at a local recording relay (Starlette on uvicorn, in a
thread). It drives the app only through its HTTP API (httpx). It saves raw snapshots, then scores them offline against
the key's CSVs. Scoring is pure functions over saved files, so `score` works without the app or the model.

**Tech Stack:** Python 3.11, httpx 0.28.1, Starlette (from fastapi 0.141.1), uvicorn 0.54.0, openpyxl 3.1.5, pymongo
4.6+, pytest 9.1.1. All of these are already in the app's environment.

**Spec:** `docs/superpowers/specs/2026-11-19-test-books-runner-design.md`. Read it first. Every task argues from it.

## Global Constraints

- **Environment:** the worktree's `.venv`, with the app's and the runner's requirements installed:
  `.venv/bin/pip install -r requirements-dev.txt -r testbooks_runner/requirements.txt`.
- **Independence:** nothing under `testbooks_runner/` (tests included) imports `ledgersync` or `testbooks`. It talks to
  the app only over HTTP, and reads the test books only as files.
- **The header:** every request to the app carries `X-LedgerSync: testbooks-runner`.
- **Databases:** run databases are named `tbrun_…`. MongoDB is `mongodb://localhost:27017` unless `--mongodb-uri` is
  given. The runner never reads `MONGODB_URI` from the app's `.env`.
- **The key:** never write the `Authorization` header or any key value to disk or to a log. `.env` is read for
  variable names only.
- **The banner:** every report and terminal summary opens with "The key is unreviewed: a difference may be the key's
  mistake." unless `<set>/review/signed-off.txt` exists.
- **Money:** `decimal.Decimal` everywhere, with the key's and the API's strings parsed as given. Costs are in US
  dollars, as OpenRouter charges.
- **Run folders:** under `testbooks_runner/runs/`, git-ignored.
- **Testing:** only `.venv/bin/python -m pytest testbooks_runner/tests -q`. Never run the app's own suite for these
  tasks (it takes about 55 minutes). Tests that need MongoDB carry `@pytest.mark.mongo` and skip without
  `LEDGERSYNC_TEST_MONGODB_URI`.
- **Tests spend nothing:** no test calls a real model or `openrouter.ai`.
- **Commits:** `feat(runner): …`, `test(runner): …` or `docs(runner): …`. Every message ends with the line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Paths with spaces.** The repo lives under `ACTING OFFICE- WORK/`. Selection, uploads, run folders and the app's
   subprocess must all work there, with arguments passed as lists, never shell strings.
   - Tests: Task 2 (`test_set_under_a_path_with_spaces`) and Task 8 (`test_start_copy_from_a_path_with_spaces`).
2. **An app copy that won't start** (no OpenRouter key in its `.env`, a crash on start). The runner must stop with a
   message naming the cause and the end of the app's log, never hang.
   - Tests: Task 8 (`test_preflight_names_the_missing_key`, `test_start_failure_shows_the_log`).
3. **A run interrupted mid-batch.** `resume` carries on without reading saved files again, and the app's 409
   `same_file` counts as "already saved".
   - Test: Task 10 (`test_resume_skips_done_batches_and_counts_same_file_as_saved`).
4. **The provider answers 429 or 5xx.** The relay passes it through unchanged and keeps serving. The driver tries the
   file once more.
   - Tests: Task 6 (`test_upstream_error_passes_through`) and Task 10 (`test_provider_failure_retried_once`).
5. **The key changed between a run and `score`** (corrected or rebuilt). Scoring still runs: files no longer in the
   key are listed, and verdicts whose key rows changed lapse and are listed as orphans.
   - Tests: Task 12 (`test_unknown_file_is_listed_not_fatal`) and Task 18 (`test_verdict_lapses_when_key_row_changes`).

---

### Task 1: Package skeleton and independence

**Files:**
- Create: `testbooks_runner/__init__.py` (`__version__ = "0.1.0"`), `testbooks_runner/requirements.txt`,
  `testbooks_runner/verdicts.csv`, `testbooks_runner/tests/__init__.py`, `testbooks_runner/tests/test_independence.py`
- Modify: `.gitignore` (append `testbooks_runner/runs/`)

**Interfaces:**
- Produces: the package `testbooks_runner`, and `verdicts.csv` with the header
  `identity,ref,verdict,whats_right,who,date,got`.

- [ ] **Step 1: Install the environment**

Run: `.venv/bin/pip install -r requirements-dev.txt`. Expected: exits 0.

- [ ] **Step 2: Write the failing tests**

```python
# testbooks_runner/tests/test_independence.py
import re, subprocess
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(ledgersync|testbooks)(\.|\s|$)", re.M)

def test_runner_imports_neither_app_nor_generator():
    offenders = [p for p in PKG.rglob("*.py") if FORBIDDEN.search(p.read_text())]
    assert offenders == []

def test_runs_folder_is_ignored():
    assert subprocess.run(["git", "check-ignore", "-q", str(PKG / "runs" / "x")], cwd=PKG.parent).returncode == 0

def test_verdicts_file_has_its_header():
    assert (PKG / "verdicts.csv").read_text().splitlines()[0] == "identity,ref,verdict,whats_right,who,date,got"
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_independence.py -q`. Expected: FAIL (no package, no
ignore rule).

- [ ] **Step 4: Create the files**

`requirements.txt` lists `httpx==0.28.1`, `fastapi==0.141.1` (for Starlette), `uvicorn==0.54.0`, `openpyxl==3.1.5`,
`pymongo>=4.6.0` and `pytest==9.1.1`. Then run
`.venv/bin/pip install -r testbooks_runner/requirements.txt`.

- [ ] **Step 5: Run them to see them pass**

Same command. Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore testbooks_runner && git commit -m "feat(runner): package skeleton, kept apart from the app and the generator" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Reading the set and choosing what to run

**Files:**
- Create: `testbooks_runner/model.py`, `testbooks_runner/books.py`, `testbooks_runner/selection.py`
- Create: `testbooks_runner/tests/fixtures/set/`, a frozen copy of a built set's `README.txt`, `catalogue.csv` and
  `packs/EC-0346-receipt-over-250/`:
  ```bash
  mkdir -p testbooks_runner/tests/fixtures/set/packs && cp testbooks/out/README.txt testbooks/out/catalogue.csv testbooks_runner/tests/fixtures/set/ && cp -R testbooks/out/packs/EC-0346-receipt-over-250 testbooks_runner/tests/fixtures/set/packs/
  ```
  If `testbooks/out` is missing, build it first with the command in `testbooks/README.md`.
- Create: `testbooks_runner/tests/helpers.py` with `write_mini_client(set_dir: Path) -> Path`. It writes
  `clients/mini/` (below) and returns its folder.
- Test: `testbooks_runner/tests/test_books.py`, `testbooks_runner/tests/test_selection.py`

The mini client, written by `write_mini_client`. Every CSV uses the same columns as the built set's.

| Path | Content |
|---|---|
| `profile.json` | `name` "Mini Widgets Ltd"; `kind` "ltd"; `vat_number` "123456782"; `company_number` "01234567". `owners`: Ann Mini, share "1", loan account 2250. `accounts`: hsbc 1200 "Business current"; amex 1240 "Business card"; stripe 1250 "Card payments". `periods`: 2023-04-01–2024-03-31, then 2024-04-01–2025-03-31. `vat_quarters_end` [2, 5, 8, 11] |
| `chart.csv` | copy of the fixture pack's `chart.csv` |
| `inbox/2023-05-09/` | `2023-04-01_hsbc-statement_2023-04-30.csv`, `2023-04-15_cabot_62874.pdf` (any bytes) |
| `inbox/2023-04-12/` | `2023-03-31_prior_tb.xlsx` (any bytes) |
| `inbox/2024-05-08/` | `2024-04-01_cabot_99999.pdf`, which is not in the key |
| `answers/2023-05-16/` | `2023-05-16_reply_mn-q0001.txt`: `Re: Is the Streamflix charge personal?\n\nYes, mine.` |
| `answers/2024-03-12/` | `2024-03-12_reply_mn-q0002.txt` and `2024-02-08_wharf_woi-1.pdf` |
| `key/2024-03-31/documents.csv` | the three in-year inbox files, plus the answer PDF. Doc IDs: `hsbc-statement-20230401-20230430`, `MN-D0001` (prior TB, `evidence`), `MN-D0002` (Cabot invoice 62874, gross 120.00, `book`), `MN-D0003` (answer PDF, `book`) |
| `key/2024-03-31/opening-balances.csv` | 1100 debit 1000.00; 1200 debit 500.00; 2100 credit 300.00; 3260 debit 0.00 credit 0.00; 3200 credit 1200.00 |
| `key/2024-03-31/debtors.csv` | as_at 2023-04-30: Calder, `OPENING-INV-1`, number INV-1, date 2023-03-20, gross/owed 400.00 |
| `key/2024-03-31/entries.csv` | books, 2023-04-12: Dr 1200 / Cr 1100, 600.00, counterparty Brightwater, no doc, line `hsbc-2023-04-0001`. Books, 2023-04-20: Dr 2100 / Cr 1200, 300.00, counterparty Cabot, no doc, line `hsbc-2023-04-0002` |
| `key/2024-03-31/queries.csv` | `MN-Q0001` about `MN-0009`, answer `answers/2023-05-16/2023-05-16_reply_mn-q0001.txt`. `MN-Q0002` about `MN-0010;MN-D0003`, answer `answers/2024-03-12/2024-03-12_reply_mn-q0002.txt` |
| `key/2024-03-31/statement-lines.csv`, `vat-returns.csv`, `trial-balance.csv`, `creditors.csv` | header plus the two lines and one row each, as above, consistent with the entries. `vat-returns.csv` holds 2023-03-01–2023-05-31 and 2023-06-01–2023-08-31 |

**Interfaces:**
- Produces:
  - `model.Period(start: date, end: date)`, frozen.
  - `model.Unit(name: str, kind: str, folder: Path, period: Period, repeat: int = 1)`, frozen, with:
    - `.key_dir -> Path`: `folder/"key"/period.end.isoformat()`
    - `.slug -> str`: `f"{name}-{period.end}-r{repeat}"`
    - `.ref -> str`: `f"{name}:{period.end}"`

    `kind` is `"client"` or `"pack"`.
  - `model.Key`, a dataclass of `list[dict[str, str]]` fields: `documents`, `entries`, `lines`, `queries`,
    `vat_returns`, `trial_balance`, `opening`, `debtors`, `creditors`.
  - `model.money(text: str) -> Decimal`, where `""` gives `Decimal("0")`.
  - `books.load_key(key_dir: Path) -> Key`. A missing CSV gives `[]`.
  - `books.load_profile(folder: Path) -> dict`
  - `books.load_catalogue(set_dir: Path) -> dict[str, dict]`, keyed by `id`.
  - `books.batches(folder: Path) -> list[tuple[date, list[Path]]]`, over `inbox/<date>/`.
  - `books.answer_folders(folder: Path) -> list[tuple[date, list[Path]]]`, over `answers/<date>/`.
  - `books.signed_off(set_dir: Path) -> bool`
  - `books.key_hash(unit: Unit) -> str`: the sha256 of the key CSVs in name order. The set's README carries no seed,
    so this hash identifies the build.
  - `selection.SelectionError(Exception)`
  - `selection.select_units(set_dir: Path, *, client: str | None = None, period: date | None = None,
    packs: list[str] | None = None, smoke: bool = False, all_packs: bool = False, repeat: int = 1) -> list[Unit]`
  - `selection.files_to_send(unit: Unit, key: Key, with_next_year: bool) -> list[tuple[date, list[Path]]]`

- [ ] **Step 1: Write the failing tests**

```python
# test_books.py  (FIX = Path(__file__).parent / "fixtures" / "set"; PACK = FIX / "packs" / "EC-0346-receipt-over-250")
def test_load_key_reads_every_table():
    key = books.load_key(PACK / "key" / "2024-06-30")
    assert len(key.documents) == 6 and key.vat_returns is not None and len(key.queries) == 1

def test_batches_are_in_date_order():
    assert [d.isoformat() for d, _ in books.batches(PACK)] == ["2024-06-04", "2024-06-11", "2024-06-12", "2024-06-20", "2024-07-01"]

def test_answer_folders_list_their_files():
    [(day, files)] = books.answer_folders(PACK)
    assert day.isoformat() == "2024-06-14" and len(files) == 2

def test_signed_off_only_with_the_file(tmp_path):
    assert books.signed_off(FIX) is False
    (tmp_path / "review").mkdir(); (tmp_path / "review" / "signed-off.txt").write_text("x")
    assert books.signed_off(tmp_path) is True

# test_selection.py
def test_select_pack_by_case_id():
    [u] = selection.select_units(FIX, packs=["EC-0346"])
    assert (u.name, u.kind, u.period.start.isoformat(), u.period.end.isoformat()) == ("EC-0346-receipt-over-250", "pack", "2024-06-01", "2024-06-30")

def test_select_client_defaults_to_its_first_period(tmp_path):
    shutil.copytree(FIX, tmp_path / "set"); write_mini_client(tmp_path / "set")
    [u] = selection.select_units(tmp_path / "set", client="mini")
    assert u.period.end.isoformat() == "2024-03-31" and u.kind == "client"

def test_later_period_is_refused(tmp_path):  # same set-up
    with pytest.raises(SelectionError, match="earlier years"):
        selection.select_units(tmp_path / "set", client="mini", period=date(2025, 3, 31))

def test_unknown_pack_and_missing_smoke_list_are_refused():
    with pytest.raises(SelectionError, match="EC-9999"): selection.select_units(FIX, packs=["EC-9999"])
    with pytest.raises(SelectionError, match="smoke.txt"): selection.select_units(FIX, smoke=True)

def test_repeat_numbers_the_units():
    assert [u.slug for u in selection.select_units(FIX, packs=["EC-0346"], repeat=2)] == [
        "EC-0346-receipt-over-250-2024-06-30-r1", "EC-0346-receipt-over-250-2024-06-30-r2"]

def test_next_year_files_left_out_unless_asked(tmp_path):  # mini client
    u = ...; key = books.load_key(u.key_dir)
    sent = [p.name for _, fs in selection.files_to_send(u, key, False) for p in fs]
    assert "2024-04-01_cabot_99999.pdf" not in sent and "2023-04-15_cabot_62874.pdf" in sent
    assert "2024-04-01_cabot_99999.pdf" in [p.name for _, fs in selection.files_to_send(u, key, True) for p in fs]

def test_set_under_a_path_with_spaces(tmp_path):
    root = tmp_path / "ACTING OFFICE- WORK" / "set"; shutil.copytree(FIX, root)
    [u] = selection.select_units(root, packs=["EC-0346"])
    assert len(books.batches(u.folder)) == 5
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_books.py testbooks_runner/tests/test_selection.py -q`.
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `model.py`, `books.py` and `selection.py`**

- **Packs** are found by `packs/<case id>-*`. Their period is `profile["periods"][0]`.
- **Clients** are `clients/<name>`. Only their first period runs. Any other `period` raises
  `SelectionError("later periods need the earlier years carried forward, which the runner doesn't do yet")`.
- **The smoke list** is `packs/smoke.txt`, one case ID per line.
- **`files_to_send`** keeps a file only if its path relative to the unit folder is in `documents.csv`'s `file` column,
  unless `with_next_year` is set. It never sends `answers/` files.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): read the test books and choose clients or packs to run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The chart and VAT tables

**Files:**
- Create: `testbooks_runner/tables/chart.csv`, `testbooks_runner/tables/vat.csv`, `testbooks_runner/mapping.py`. The
  module isn't called `tables.py`, because the data folder already has that name.
- Test: `testbooks_runner/tests/test_mapping.py`

`chart.csv` has the columns `key_code,key_name,app_code,also,note`. It has one row for each of the 54 codes in the
generator's chart (`testbooks/books/chart.csv`).
- Where the code means the same in both charts, `app_code` is that code.
- Where it differs, the rows are pinned:

| key | app | also | note |
|---|---|---|---|
| 1290 Transfers in transit | 9998 | 1200;1210 | the app has no in-transit account; it books a transfer straight to the other account |
| 2125 Deferred income | 2105 | | |
| 3260 Dividends | 3250 | | the app's 3260 is Drawings |
| 4010 Sales - projects | 4000 | | the app has one sales account |
| 4906 Bank interest received | 4902 | | the app's 4906 is Grants Received |
| 5100 Freelancers | 5002 | 7602 | |
| 7410 Car lease | 7304 | | |
| 7550 Software and subscriptions | 8201 | | |
| 7905 Card processing fees | 7901 | | the app's 7905 is Exchange Differences |
| 8205 Staff welfare and entertainment | 8206 | 8205 | the app's 8205 is Refreshments |
| 8250 Sundry and corrections | 8207 | | the app's 8250 is Fines and Penalties |
| 9100 Corporation tax charge | 8800 | | |

`vat.csv` has the columns `key_code,label,reverse_charge`:

| key_code | label | reverse_charge |
|---|---|---|
| standard | VAT at 20% | N |
| reduced | VAT at 5% | N |
| zero | zero-rated | N |
| exempt | exempt | N |
| outside | outside the scope of VAT | N |
| none | no VAT reclaimed | N |
| reverse_charge | reverse charge | Y |
| blocked | VAT blocked | N |
| blocked_half | half the VAT blocked | N |
| flat_rate | flat rate scheme | N |

**Interfaces:**
- Produces:
  - `mapping.ChartRow(key_code, key_name, app_code, also: tuple[str, ...], note)`
  - `mapping.VatRow(key_code, label, reverse_charge: bool)`
  - `mapping.Unmapped(KeyError)`
  - `mapping.load_chart(path: Path = TABLES / "chart.csv") -> dict[str, ChartRow]`
  - `mapping.load_vat(path: Path = TABLES / "vat.csv") -> dict[str, VatRow]`
  - `mapping.app_code(chart, key_code) -> str`
  - `mapping.choices(chart, key_code, also_ok: str = "") -> tuple[str, ...]`: the primary code, then the table's
    `also`, then each `also_ok` code mapped. No duplicates.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_generator_account_is_mapped():
    chart = mapping.load_chart()
    for row in csv.DictReader(open(PACK / "chart.csv")):
        assert mapping.app_code(chart, row["code"])

@pytest.mark.parametrize("key,app", [("4906","4902"),("3260","3250"),("7550","8201"),("7905","7901"),("8205","8206"),
    ("8250","8207"),("9100","8800"),("2125","2105"),("7410","7304"),("5100","5002"),("4010","4000"),("7504","7504")])
def test_codes_whose_meaning_differs(key, app):
    assert mapping.app_code(mapping.load_chart(), key) == app

def test_choices_add_also_ok():
    assert mapping.choices(mapping.load_chart(), "9998", also_ok="7504") == ("9998", "7504")

def test_unmapped_code_raises():
    with pytest.raises(mapping.Unmapped): mapping.app_code(mapping.load_chart(), "1234")

def test_vat_table():
    vat = mapping.load_vat()
    assert vat["reverse_charge"].reverse_charge and vat["standard"].label == "VAT at 20%"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_mapping.py -q`. Expected: FAIL.

- [ ] **Step 3: Write the two CSVs and `mapping.py`**

`TABLES = Path(__file__).parent / "tables"`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): the runner's chart and VAT tables" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Setting a client up

**Files:**
- Create: `testbooks_runner/setup.py`
- Test: `testbooks_runner/tests/test_setup.py`

**Interfaces:**
- Consumes: `Key`, `Period`, `money` (Task 2); `mapping.load_chart` and `mapping.app_code` (Task 3).
- Produces:
  - `setup.SetupError(Exception)`
  - `setup.bank_kind(code: str) -> str | None`: `"current"` for 1200–1209, `"savings"` for 1210–1219,
    `"petty_cash"` for 1230–1239, `"credit_card"` for 1240–1249, else `None`.
  - `setup.business_type(profile: dict) -> str`: `ltd` gives `limited_company`; `sole_trader`, `partnership` and `llp`
    keep their names. For `"pack"`, the name decides: ending "Ltd" or "Limited" gives `limited_company`, "LLP" gives
    `llp`. Anything else raises `SetupError`.
  - `setup.client_fields(profile: dict, period: Period, review: str) -> dict`, with the keys:
    - `name`, `business_type`
    - `contact_name`: the first owner's name, else the client's name
    - `first_year_end`: `period.end` in ISO form
    - `vat_registered`: `bool(vat_number)`
    - `vat_number`, `company_number`
    - `bank_accounts`: `[{"code": "", "name", "kind"}]` for accounts whose `bank_kind` isn't `None`, in profile order
    - `owners`: `[{"name", "share"}]`, with the share as a percent string (`"0.5"` becomes `"50"`)
    - `ai_review`: the `review` argument
  - `setup.bank_codes(profile: dict, client: dict) -> dict[str, str]`: profile account ID to the app's code, matched
    by account name against the created client's `bank_accounts`.
  - `setup.statement_account(doc_id: str, profile: dict) -> str | None`: the profile account ID equal to the first
    `-`-separated word of `doc_id`.
  - `setup.opening_balances(key: Key, chart) -> tuple[dict, list[str]]`: `({"lines": [...], "unpaid": [...]},
    warnings)`. The lines are mapped to app codes and netted per code. Each line is `{"code", "debit", "credit"}`, with
    money as strings.
  - `setup.opening_items(key: Key) -> tuple[list[dict], list[str]]`: OpenItem dicts `{"id": "open-<n>", "direction",
    "counterparty", "amount", "number", "date"}`, and warnings. The direction is `"in"` for debtors and `"out"` for
    creditors.

- [ ] **Step 1: Write the failing tests** (`mini = write_mini_client(...)`, with `profile` and `key` loaded from it)

```python
def test_client_fields_for_a_limited_company():
    f = setup.client_fields(profile, Period(date(2023,4,1), date(2024,3,31)), "automatic")
    assert f["business_type"] == "limited_company" and f["first_year_end"] == "2024-03-31" and f["vat_registered"]
    assert [(a["name"], a["kind"]) for a in f["bank_accounts"]] == [("Business current","current"),("Business card","credit_card")]
    assert f["owners"] == [{"name": "Ann Mini", "share": "100"}] and f["ai_review"] == "automatic"

def test_pack_business_type_from_its_name():
    assert setup.business_type({"kind": "pack", "name": "Fernbrook Consulting Ltd"}) == "limited_company"
    assert setup.business_type({"kind": "pack", "name": "Ashgrove Studio LLP"}) == "llp"
    with pytest.raises(setup.SetupError): setup.business_type({"kind": "pack", "name": "Grace Adeyemi"})

def test_statement_account_from_the_document_id():
    assert setup.statement_account("amex-statement-20230304-20230403", profile) == "amex"
    assert setup.statement_account("MN-D0002", profile) is None

def test_bank_codes_from_the_created_client():
    client = {"bank_accounts": [{"code": "1200", "name": "Business current"}, {"code": "1240", "name": "Business card"}]}
    assert setup.bank_codes(profile, client) == {"hsbc": "1200", "amex": "1240"}

def test_opening_lines_go_to_app_codes():
    opening, _ = setup.opening_balances(key, mapping.load_chart())
    assert {l["code"] for l in opening["lines"]} >= {"1100", "1200", "2100", "3200"}

def test_opening_items_named_first_then_from_first_payments():
    items, warnings = setup.opening_items(key)
    assert [(i["counterparty"], i["amount"], i["number"]) for i in items] == [
        ("Calder", "400.00", "INV-1"), ("Brightwater", "600.00", None), ("Cabot", "300.00", None)]
    assert warnings == []

def test_opening_items_warn_when_payments_dont_reach_the_total():
    key.opening[0]["debit"] = "1500.00"   # 1100 now 1500, payments only reach 1000
    items, warnings = setup.opening_items(key)
    assert any("1100" in w for w in warnings) and [i["counterparty"] for i in items if i["direction"] == "in"] == ["Calder"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_setup.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `setup.py`**

`opening_items` works in this order:
1. Rows of `debtors.csv` and `creditors.csv` whose `doc_id` starts `OPENING-`, from the earliest `as_at`.
2. Then entries in phase `books` with empty `doc_ids` that credit 1100 (for debtors) or debit 2100 (for creditors),
   in date order, while the listed total stays at or under the opening balance on that account.

If the total isn't reached exactly, it keeps only the step-1 items for that side and adds a warning naming the
account.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): set a client up from its profile and opening balances" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The app's API client

**Files:**
- Create: `testbooks_runner/api.py`
- Test: `testbooks_runner/tests/test_api.py`, using `httpx.MockTransport`

**Interfaces:**
- Produces:
  - `api.HEADER = {"X-LedgerSync": "testbooks-runner"}`
  - `api.AppError(Exception)`, with `.status: int`, `.code: str` and `.message: str`, taken from
    `{"detail": {"code", "message"}}`.
  - `api.Api(base_url: str, *, timeout: float = 120.0, transport: httpx.BaseTransport | None = None)`, with methods
    that each return the parsed JSON:

| Method | Route |
|---|---|
| `health()` | `GET /api/health` |
| `accounts(client_id)` | `GET /api/accounts?client_id=` |
| `create_client(fields)` | `POST /api/clients` |
| `client(client_id)` | `GET /api/clients/{id}` |
| `years(client_id)` | `GET /api/clients/{id}/years` |
| `put_opening(client_id, opening)` | `PUT /api/clients/{id}/opening-balances` |
| `analyze(client_id, year_start: date, path: Path, bank_account: str \| None) -> str` | `POST /api/analyze` (multipart: `file`, `client_id`, `year_start`, and `bank_account` only when given); returns the `job_id` |
| `job(job_id)` | `GET /api/jobs/{id}` |
| `ledger / posted_tb / tb_shown / invoices / bank / summary / suggestions(client_id, year_start)` | `GET /api/clients/{id}/years/{start}/ledger`, `/posted-trial-balance`, `/trial-balance?shown=true`, `/invoices`, `/bank`, `/summary`, `/suggestions` |
| `vat(client_id, year_start, start: date, end: date)` | `GET …/vat?period_start=&period_end=` |
| `export_xlsx(client_id, year_start) -> bytes` | `GET …/export.xlsx` |
| `questions / decisions / reviews(client_id)` | `GET /api/clients/{id}/questions`, `/decisions`, `/reviews` |
| `new_thread(client_id)` | `POST /api/chat/threads` with `{"client_id"}` |
| `thread(thread_id)` | `GET /api/chat/threads/{id}` |
| `send_message(thread_id, text, files: list[Path]) -> list[tuple[str, dict]]` | `POST /api/chat/threads/{id}/messages` (multipart: `text`, then each file as `files`). It reads the SSE stream until the `done` event |

- [ ] **Step 1: Write the failing tests**

```python
def test_every_request_carries_the_header(): ...  # handler asserts request.headers["X-LedgerSync"] == "testbooks-runner"
def test_errors_become_app_error():
    # handler returns 409 {"detail": {"code": "same_file", "message": "Skipped a.pdf"}}
    with pytest.raises(api.AppError) as e: client.analyze(1, date(2023,4,1), f, None)
    assert (e.value.status, e.value.code) == (409, "same_file")
def test_analyze_sends_the_file_and_fields():  # body contains b'filename="a b.pdf"', b'name="year_start"', no b'name="bank_account"'
def test_sse_events_until_done():
    # body: 'event: status\ndata: {"text": "Reading"}\n\nevent: token\ndata: {"text": "Hi"}\n\nevent: done\ndata: {}\n\n'
    assert client.send_message("t1", "hello", []) == [("status", {"text": "Reading"}), ("token", {"text": "Hi"}), ("done", {})]
def test_vat_passes_the_period():  # handler asserts params period_start=2023-06-01, period_end=2023-08-31
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_api.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `api.py`**

Use one `httpx.Client(base_url=…, headers=HEADER, timeout=…, transport=…)`. A non-2xx answer raises `AppError`. When
the body has no `detail`, `code` is `"http_<status>"`. `send_message` uses `client.stream`. Events are split on blank
lines, each `data:` line is JSON, and reading stops after `done`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): an HTTP client for the app's API" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The relay: passing calls through and recording them

**Files:**
- Create: `testbooks_runner/relay.py`
- Create: `testbooks_runner/tests/servers.py`, with `serve(app) -> tuple[int, Callable[[], None]]`: it starts any ASGI
  app on a free port in a thread and returns the port and a stop function.
- Create: `testbooks_runner/tests/fake_upstream.py`, with `make_upstream(calls: list) -> Starlette`. Each request it
  receives is appended to `calls`. Its routes:

| Route | Answer |
|---|---|
| `POST /api/v1/chat/completions` | With `"stream": true`: three SSE `data:` chunks with `"id": "gen-1"`, then `data: [DONE]`. Otherwise `{"id": "gen-1", "choices": [...], "usage": {"prompt_tokens": 100, "completion_tokens": 50}}` |
| `GET /api/v1/key`, `GET /api/v1/models/user` | small JSON |
| `GET /api/v1/generation?id=` | `{"data": {"total_cost": 0.0012, "tokens_prompt": 100, "tokens_completion": 50}}` |
| `POST /api/v1/fail` | 429 with `{"error": {"message": "slow down"}}` |

- Test: `testbooks_runner/tests/test_relay.py`

**Interfaces:**
- Produces:
  - `relay.Relay(upstream: str, record_dir: Path, *, replay_from: Path | None = None, strict: bool = False,
    cost_lookup: bool = True)`, with:
    - `.start() -> int`: the port
    - `.stop() -> None`
    - `.base_url(unit: str) -> str`: `f"http://127.0.0.1:{port}/c/{unit}"`
    - `.set_part(unit: str, part: str | None)`
    - `.totals() -> dict`: `{"cost": Decimal, "calls": int, "replayed": int, "by_part": {part: Decimal}}`
  - `relay.fingerprint(method: str, path: str, body: bytes) -> str`: sha256 over `method`, `path` and canonical JSON
    (sorted keys, compact separators), or the raw bytes when the body isn't JSON.
  - `relay.part_of(method: str, body: bytes, chat: bool) -> str`, which picks the first that applies:
    1. `"health"` for GET
    2. `"chat"` when `chat` is set and the body has `tools`
    3. `"review"` when the body has `tools`
    4. otherwise `"reader"`
  - Records go to `record_dir/calls.jsonl`, one JSON object per call, with these fields: `seq`, `unit`, `part`,
    `method`, `path` (with the `/c/<unit>` prefix removed), `fingerprint`, `status`, `started` (epoch seconds),
    `seconds`, `streamed`, `request` (parsed JSON or text), `response` (JSON or text, or null when streamed), `events`
    (the list of `data:` strings, or null), `generation_id`, `usage`, `replayed`.

- [ ] **Step 1: Write the failing tests**

```python
def test_json_call_passes_through_unchanged(): ...  # bytes from relay == bytes from upstream; status 200
def test_streamed_call_arrives_chunk_by_chunk():   # client sees the 3 data lines then [DONE]; record["events"] has 4 entries
def test_record_never_holds_the_key(tmp_path):
    # send Authorization: Bearer sk-or-secret-123 through the relay
    assert all("sk-or-secret-123" not in p.read_text() for p in tmp_path.rglob("*") if p.is_file())
def test_unit_prefix_is_stripped():  # upstream sees /api/v1/chat/completions; record unit == "u1", path == "/chat/completions"
def test_parts():
    assert relay.part_of("GET", b"", False) == "health"
    assert relay.part_of("POST", b'{"messages": []}', False) == "reader"
    assert relay.part_of("POST", b'{"tools": []}', False) == "review"
    assert relay.part_of("POST", b'{"tools": []}', True) == "chat"
def test_upstream_error_passes_through():  # POST /c/u1/fail -> 429, same body; a call after it still succeeds
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_relay.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement pass-through and recording in `relay.py`**

- **The app:** a Starlette app with one catch-all route, `/c/{unit}/{path:path}`. Forward with an
  `httpx.AsyncClient` to `upstream + "/" + path`, keeping the method, query and body. Copy the headers except `host`
  and `content-length`.
- **Streamed answers:** when the upstream's content type is `text/event-stream`, answer with a `StreamingResponse`
  that yields each chunk as it comes and collects the `data:` lines for the record.
- **The server:** uvicorn `Server` in a daemon thread, with `start()` waiting for `server.started`.
- **Recording:** a `threading.Lock` guards `seq`, and the file is appended under it.
- **The chat flag:** `set_part(unit, "chat")` marks the unit's agent calls as chat, and `None` clears it.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): a relay that passes model calls through and records them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The relay: replay, strict mode and cost

**Files:**
- Modify: `testbooks_runner/relay.py`
- Test: `testbooks_runner/tests/test_relay_replay.py`

**Interfaces:**
- Consumes: `Relay`, `fingerprint` (Task 6).
- Produces:
  - Replay from `replay_from/calls.jsonl`. Each fingerprint keeps a first-in, first-out list of records. A replayed
    call is recorded with `replayed: true` and costs nothing.
  - `strict=True`: a call with no recording gets 502 `{"error": {"message": "no recording for this call"}}`, and
    upstream is not called.
  - Cost lookups go to `record_dir/costs.jsonl`, one `{"seq", "cost", "tokens_in", "tokens_out"}` per line, with the
    cost as a decimal string. `totals()` adds them up.

- [ ] **Step 1: Write the failing tests**

```python
def test_replay_answers_without_upstream(tmp_path):
    # record one JSON and one streamed call with relay A; stop upstream; relay B(upstream=dead port, replay_from=A dir)
    # gives identical bodies; B's records have replayed True; B.totals()["cost"] == 0
def test_replay_miss_goes_live():   # different body -> upstream called once
def test_strict_miss_is_refused():  # status 502; upstream calls unchanged
def test_cost_is_looked_up(tmp_path):
    # after a live call, wait until costs.jsonl has 1 line (poll up to 10 s)
    assert relay_a.totals()["cost"] == Decimal("0.0012")
def test_lookup_uses_the_callers_key():  # upstream /generation sees Authorization equal to the one the app sent
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_relay_replay.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement replay, strict mode and the lookup**

- **Which calls:** a lookup runs for every live call whose answer carries an `id`. For a JSON answer that's its
  top-level `id`; for a streamed one, the first chunk's.
- **When and how:** after 1 second, send
  `GET {upstream}/generation?id=<id>` with the caller's `Authorization` header, which is held only in a local variable.
  Retry 5 times, 2 seconds apart.
- **Where it runs:** lookups run in a background thread, and `stop()` waits up to 15 seconds for them to finish.
- **A replayed stream** emits the recorded `data:` lines as SSE.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): relay replay, strict mode and cost per call" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Starting a copy of the app

**Files:**
- Create: `testbooks_runner/appserver.py`
- Test: `testbooks_runner/tests/test_appserver.py`

**Interfaces:**
- Consumes: `api.Api` (Task 5).
- Produces:
  - `appserver.StartError(Exception)`
  - `appserver.free_port() -> int`
  - `appserver.env_names(app_dir: Path) -> set[str]`: the variable names in `app_dir/.env`. Values are never returned.
  - `appserver.live_db_name(app_dir: Path, environ: Mapping[str, str]) -> str`: from `environ["MONGODB_DB_NAME"]`, else
    `.env`'s `MONGODB_DB_NAME` line, else `"ledgersync"`. This is the one value read from `.env`, and it isn't a
    secret.
  - `appserver.preflight(app_dir: Path, environ) -> None`: raises `StartError` when `server.py` is missing, or when
    `OPENROUTER_API_KEY` is in neither `environ` nor `env_names`. The message says
    `"No OpenRouter key: the app reads it from <app_dir>/.env; copy .env from the main checkout"`.
  - `appserver.check_database(mongodb_uri: str, db: str, live: str, *, resume: bool,
    client_factory=pymongo.MongoClient) -> None`: raises `StartError` when `db` doesn't start with `tbrun_`, when
    `db == live`, or, without `resume`, when the database already has collections.
  - `appserver.app_env(environ, *, mongodb_uri: str, db: str, port: int, relay_url: str) -> dict`: sets
    `MONGODB_URI`, `MONGODB_DB_NAME`, `LEDGERSYNC_HOST=127.0.0.1`, `LEDGERSYNC_PORT`,
    `OPENROUTER_BASE_URL=relay_url`, `LEDGERSYNC_REVIEW_DAILY_LIMIT=100000` and `LEDGERSYNC_RELOAD=0`.
  - `appserver.app_commit(app_dir: Path) -> dict`: `{"commit": <HEAD sha>, "dirty": <changes under server.py or
    ledgersync/>}`
  - `appserver.AppCopy(port: int, db: str, process: subprocess.Popen, log: Path, api: Api)`
  - `appserver.start_copy(app_dir, *, python: str, env: dict, port: int, db: str, log: Path,
    timeout: float = 90.0) -> AppCopy`
  - `appserver.stop_copy(copy: AppCopy) -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_app_env_points_the_app_at_its_database_and_the_relay():
    e = appserver.app_env({"PATH": "/bin"}, mongodb_uri="mongodb://localhost:27017", db="tbrun_x_1", port=9001, relay_url="http://127.0.0.1:9002/c/u")
    assert (e["MONGODB_DB_NAME"], e["LEDGERSYNC_PORT"], e["OPENROUTER_BASE_URL"], e["LEDGERSYNC_REVIEW_DAILY_LIMIT"]) == ("tbrun_x_1", "9001", "http://127.0.0.1:9002/c/u", "100000")
def test_databases_refused():
    # fake factory: client[db].list_collection_names() returns ["clients"] for "tbrun_full"
    for db, live in [("ledgersync", "ledgersync"), ("mine", "ledgersync"), ("tbrun_full", "ledgersync")]:
        with pytest.raises(appserver.StartError): appserver.check_database("mongodb://x", db, live, resume=False, client_factory=fake)
    appserver.check_database("mongodb://x", "tbrun_full", "ledgersync", resume=True, client_factory=fake)  # allowed
def test_preflight_names_the_missing_key(tmp_path):
    (tmp_path / "server.py").write_text(""); (tmp_path / ".env").write_text("MONGODB_URI=x\n")
    with pytest.raises(appserver.StartError, match=r"\.env"): appserver.preflight(tmp_path, {})
def test_start_failure_shows_the_log(tmp_path):
    (tmp_path / "server.py").write_text("print('boom'); raise SystemExit(1)")
    with pytest.raises(appserver.StartError, match="boom"):
        appserver.start_copy(tmp_path, python=sys.executable, env=dict(os.environ), port=appserver.free_port(), db="tbrun_t_1", log=tmp_path / "app.log", timeout=10)
def test_start_copy_from_a_path_with_spaces(tmp_path):
    app = tmp_path / "ACTING OFFICE- WORK"; app.mkdir()
    (app / "server.py").write_text(HEALTH_SERVER)  # stdlib http.server answering GET /api/health on LEDGERSYNC_PORT
    copy = appserver.start_copy(app, python=sys.executable, env={**os.environ, "LEDGERSYNC_PORT": str(port)}, port=port, db="tbrun_t_1", log=app / "app.log", timeout=20)
    assert copy.api.health()["status"] == "online"; appserver.stop_copy(copy); assert copy.process.poll() is not None
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_appserver.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `appserver.py`**

- **Start:** `subprocess.Popen([python, "server.py"], cwd=app_dir, env=env, stdout=log_file,
  stderr=subprocess.STDOUT)`.
- **Wait:** poll `Api.health()` every 0.5 seconds until it answers. If the process exits or the timeout passes, raise
  `StartError` with the last 20 lines of the log.
- **Stop:** `terminate`, wait 10 seconds, then `kill`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): start and stop copies of the app on their own databases" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Run folders and progress

**Files:**
- Create: `testbooks_runner/runs.py`
- Test: `testbooks_runner/tests/test_runs.py`

**Interfaces:**
- Consumes: `Unit` (Task 2).
- Produces:
  - `runs.RUNS = Path(__file__).parent / "runs"`
  - `runs.RunDir(path: Path)`, with:
    - `.name`
    - `.unit_dir(unit) -> Path`: `path/"units"/unit.slug`, created on demand
    - `.write_json(rel: str, data) -> None`: atomic, written to `.tmp` then replaced
    - `.read_json(rel: str, default=None)`
  - `runs.new_run(label: str, root: Path = RUNS, today: date | None = None) -> RunDir`: `<root>/<YYYY-MM-DD>-<label>`,
    with `-2`, `-3` and so on when the name is taken.
  - `runs.open_run(name: str, root: Path = RUNS) -> RunDir`: a folder name or a path.
  - `runs.previous_run(current: RunDir, selection: str, root: Path = RUNS) -> RunDir | None`: the latest other run
    whose `run.json` has the same `selection` and a `finished` value.
  - `runs.Progress` dataclass, with defaults:
    - `client_id: int | None = None`, `app_year_start: str | None = None`
    - `bank_codes: dict = {}`, `batches_done: list[str] = []`
    - `uploads: dict[str, dict] = {}`, keyed by file path relative to the unit folder
    - `before_done: bool = False`, `replies: dict[str, dict] = {}`
    - `thread_id: str | None = None`, `chat_year: str | None = None`, `after_done: bool = False`
  - `runs.load_progress(unit_dir: Path) -> Progress` and `runs.save_progress(unit_dir: Path, p: Progress) -> None`,
    using `progress.json`.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_run_names_and_collisions(tmp_path):
    a = runs.new_run("packs", tmp_path, today=date(2026,11,19)); b = runs.new_run("packs", tmp_path, today=date(2026,11,19))
    assert (a.name, b.name) == ("2026-11-19-packs", "2026-11-19-packs-2")
def test_previous_run_same_selection_finished_only(tmp_path):
    # runs A (selection "packs", finished), B ("packs", not finished), C ("agency", finished), D current ("packs")
    assert runs.previous_run(D, "packs", tmp_path).name == A.name
def test_progress_round_trip(tmp_path):
    p = runs.Progress(client_id=3, batches_done=["2023-04-12"], uploads={"inbox/2023-04-12/a.pdf": {"status": "saved"}})
    runs.save_progress(tmp_path, p); assert runs.load_progress(tmp_path) == p
def test_write_json_is_atomic(tmp_path):  # no *.tmp left behind after write_json
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_runs.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `runs.py`**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): run folders and per-unit progress" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Driving a unit: set-up and batches

**Files:**
- Create: `testbooks_runner/driver.py`
- Create: `testbooks_runner/tests/fake_api.py`, with a `FakeApi` exposing the `Api` methods. Each test sets:
  - `years`, `clients`
  - `job_script: dict[str, list[dict]]`: file name to the job dicts returned on successive polls
  - `raise_on: dict[str, AppError]`
  - `review_script: list[list[dict]]`

  It records `calls: list[tuple[str, tuple]]` and `max_in_flight: int`.
- Test: `testbooks_runner/tests/test_driver.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5 and 9.
- Produces:
  - `driver.Options(review: str = "automatic", with_next_year: bool = False, job_timeout: float = 900.0,
    review_timeout: float = 900.0, review_grace: float = 25.0, poll: float = 2.0)`
  - `driver.Stopped(Exception)`
  - `driver.set_up(api, unit, key, profile, chart, progress, options) -> list[str]`, which:
    1. creates the client
    2. sets `progress.client_id`
    3. sets `progress.app_year_start` to the year whose `end == unit.period.end`
    4. sets `progress.bank_codes`
    5. puts the opening balances

    It returns the warnings and does nothing when `client_id` is already set.
  - `driver.send_batches(api, unit, key, profile, progress, options, *, unit_dir: Path, clock=time.monotonic,
    now=lambda: datetime.now(timezone.utc), sleep=time.sleep, after_batch: Callable[[], bool] | None = None) -> None`
  - `driver.wait_jobs(api, job_ids: list[str], *, timeout, poll, clock, sleep) -> dict[str, dict]`
  - `driver.wait_review(api, client_id: int, since: datetime, *, timeout, grace, poll, clock, sleep) -> str`, which
    returns one of:
    - `"done"`: a review run started at or after `since` and isn't `running`
    - `"none"`: no such run within `grace` and none running
    - `"timeout"`
  - Each entry of `progress.uploads[rel]` is `{"status": "saved" | "no rows" | "refused" | "failed" | "same file",
    "job_id", "upload_id", "error", "submitted", "finished", "tries"}`, with the times in epoch seconds.

- [ ] **Step 1: Write the failing tests**

```python
def test_set_up_creates_the_client_and_its_opening(): ...  # calls include create_client and put_opening; progress.app_year_start == "2023-04-01"
def test_batches_in_date_order_never_more_than_five_reading(): ...  # 7 files in one batch -> fake.max_in_flight <= 5
def test_statement_gets_its_bank_account():  # hsbc statement -> analyze(..., bank_account="1200"); stripe file -> None
def test_refusal_recorded_and_the_batch_goes_on():  # raise_on {"a.pdf": AppError(413,"file_too_large","too big")}
    assert progress.uploads[a]["status"] == "refused" and progress.uploads[b]["status"] == "saved"
def test_provider_failure_retried_once():
    # job fails with error code "ai_rate_limited", second submission succeeds -> "saved", tries == 2
    # fails twice -> "failed", tries == 2
def test_waits_for_the_review_after_a_batch():  # review_script: [[{"status":"running",...}], [{"status":"done","started_at": later}]] -> "done"
def test_no_review_wait_when_review_is_off():   # reviews() never called
def test_resume_skips_done_batches_and_counts_same_file_as_saved():
    # progress.batches_done == ["2023-04-12"]; raise_on {second batch file: AppError(409,"same_file","Skipped")}
    # -> first batch not sent again; that file's status "same file"; batch marked done
def test_spend_guard_stops_after_saving():  # after_batch returns False -> Stopped raised; progress.json has the batch done
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_driver.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement set-up and batches in `driver.py`**

- **Which files:** the batches come from `selection.files_to_send(unit, key, options.with_next_year)`.
- **Within a batch:** keep at most 5 jobs unfinished. As each finishes, submit the next file.
- **A statement's bank account:** look up the file's `documents.csv` row by `file`. If
  `setup.statement_account(doc_id, profile)` names an account, use its code from `bank_codes`.
- **Retries:** a failed job whose `error.code` is `ai_rate_limited`, `ai_timeout`, `ai_offline` or `ai_error` is
  resubmitted once.
- **What a finished job means:** a `succeeded` job with `result.upload_id` is "saved", and one without it is "no rows".
- **After each batch:**
  1. If anything was saved and the review isn't `off`, call `wait_review(since=<time the last job finished>)`.
  2. Append the batch date to `batches_done`.
  3. `save_progress`.
  4. If `after_batch` returns `False`, raise `Stopped`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): set a unit up and send its batches in arrival order" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Snapshots

**Files:**
- Modify: `testbooks_runner/driver.py`
- Test: `testbooks_runner/tests/test_snapshot.py`

**Interfaces:**
- Consumes: Tasks 5, 9 and 10.
- Produces:
  - `driver.vat_periods(key: Key, period: Period) -> list[tuple[date, date]]`: the key's VAT return periods that lie
    wholly inside `period`.
  - `driver.take_snapshot(api, progress, unit_dir: Path, which: str, vat_periods) -> None`, where `which` is
    `"before"` or `"after"`. It writes `unit_dir/raw/<which>/`:
    - `client.json`, `years.json`, `accounts.json`
    - for every year listed, `ledger-<start>.json`, plus `posted-<start>.json` for each year whose ledger has rows
      (always the scored year)
    - `tb-shown.json`
    - `vat-<start>-<end>.json` for each VAT period
    - `invoices.json`, `bank.json`, `summary.json`, `suggestions.json`, `questions.json`, `decisions.json`,
      `reviews.json`
    - `export.xlsx`
    - `chat.json`, only in `after`, and only when `progress.thread_id` is set

    A call that raises `AppError` writes `<name>.error.json` with `{status, code, message}` instead, and the snapshot
    goes on. It then sets `progress.before_done` or `progress.after_done` and saves.

- [ ] **Step 1: Write the failing tests**

```python
def test_vat_periods_inside_only():  # mini key: [(2023-06-01, 2023-08-31)]; the Mar-May 2023 quarter is left out
def test_snapshot_writes_every_file(tmp_path): ...  # expected names present under raw/before
def test_snapshot_survives_a_failing_call(tmp_path):  # FakeApi.tb_shown raises AppError(422, "transactions_need_fixing", "x")
    assert (tmp_path / "raw/before/tb-shown.error.json").exists() and (tmp_path / "raw/before/questions.json").exists()
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_snapshot.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `vat_periods` and `take_snapshot`**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): snapshots of the books, saved as the API returned them" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Lining up the app's rows with the key

**Files:**
- Create: `testbooks_runner/align.py`
- Create: `testbooks_runner/tests/builders.py`, with:
  - `key(**tables) -> Key`
  - `row(id, upload_id, **fields) -> dict`, with defaults: `direction` "out", `gross` "0.00", `document_type`
    "receipt", `decision_ids` []
  - `posted(row_id, code, debit="0", credit="0") -> dict`
  - `snapshot(rows=(), posted_lines=(), uploads=(), questions=(), decisions=(), reviews=(), vat=None, invoices=(),
    tb_lines=(), opening=(), accounts=(), scored_year="2023-04-01", chat=None) -> Snapshot`
  - `uploads_progress(mapping: dict[str, int]) -> dict`
- Test: `testbooks_runner/tests/test_align.py`

**Interfaces:**
- Consumes: Tasks 2, 4 and 11.
- Produces:
  - `align.Snapshot` dataclass:
    - `which: str`, `scored_year: str`
    - `ledgers: dict[str, dict]` and `posted: dict[str, dict]`, both keyed by year start
    - `vat: dict[tuple[str, str], dict]`
    - `invoices: list`, `questions: list`, `decisions: list`, `reviews: list`, `accounts: list`
    - `chat: dict | None`, `errors: dict[str, dict]`
  - `align.load_snapshot(unit_dir: Path, which: str) -> Snapshot`
  - `align.Group` (frozen): `journals: tuple[str, ...]`, `docs: frozenset[str]`, `lines: frozenset[str]`,
    `deals: frozenset[str]`, `phases: frozenset[str]`, `paperless: bool`
  - `align.Alignment` dataclass:
    - `rows_by_doc: dict[str, list[dict]]`
    - `line_rows: dict[str, dict]` and `line_how: dict[str, str]`, where `how` is `"exact"`, `"date"` or `"amount"`
    - `unpaired: list[dict]`
    - `posted_by_row: dict[int, list[dict]]`
    - `groups: list[Group]`
    - `not_read: set[str]`: the doc IDs whose file was never saved or was refused
    - `unknown_files: list[str]`
  - `align.align(key, snap, uploads: dict[str, dict], profile: dict, bank_codes: dict[str, str]) -> Alignment`
  - `align.pair_lines(key_lines, rows, account_codes: dict[str, str]) -> tuple[dict, dict, list]`
  - `align.groups_of(entries: list[dict]) -> list[Group]`
  - `align.subjects(row_ids: list[int], al: Alignment, key: Key) -> set[str]`: doc IDs, deal IDs, and `"cp:" +` each
    lower-cased counterparty behind those rows.
  - `align.query_for(question: dict, key: Key, al: Alignment) -> str | None`

- [ ] **Step 1: Write the failing tests**

```python
def test_rows_tie_to_their_documents():  # upload of file X has id 7 -> rows with upload_id 7 in rows_by_doc[doc of X]
def test_rows_in_another_year_still_tie(): # the doc's rows sit in ledgers["2024-04-01"]
def test_statement_lines_pair_exact_then_by_date_then_by_amount():
    # key lines L1 (-504.00, 2023-04-03), L2 (-16.20, 2023-04-03), L3 (-50.00, 2023-04-05); app rows for 1200:
    # -504.00 on 04-03, -16.20 on 04-05, -55.00 on 04-05
    assert al.line_how == {"L1": "exact", "L2": "date", "L3": "amount"}
def test_unpaired_rows_are_listed():
def test_groups_join_journals_sharing_a_document_or_line():  # invoice journal + payment journal sharing doc D8 -> one group
def test_paperless_journal_is_its_own_group():               # VAT-2023-05-31 -> Group(paperless=True)
def test_query_matched_by_deal_and_by_counterparty():
    # MN-Q0001 about MN-0009 (Streamflix); the app's question is about a later month's Streamflix row -> "MN-Q0001"
def test_unknown_file_is_listed_not_fatal():  # an upload whose file isn't in documents.csv -> in al.unknown_files
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_align.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `align.py`**

- **Signs:** a key line's `amount` is signed, with negative meaning money out. An app row's signed amount is `gross`,
  negated when `direction == "out"`.
- **Pairing statement lines:** one to one, in three passes:
  1. same account, same amount, same date
  2. same account and amount, date within 3 days, nearest date first
  3. same account and date, another amount

  Only rows with `document_type == "statement"` take part.
- **Documents in a file:** a file holding several key documents gives each row to the document with the same gross,
  else to the nearest date.
- **Groups:** union-find over the journals that share any `doc_ids` or `line_ids` entry.
- **Matching a question to a query:** `query_for` matches when the query's `about` IDs, or `"cp:"` plus the
  counterparties of the entries for those deals, meet `subjects(question["row_ids"])`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): line the app's rows up with the key" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Replies through the chat

**Files:**
- Modify: `testbooks_runner/driver.py`
- Test: `testbooks_runner/tests/test_replies.py`

**Interfaces:**
- Consumes: Tasks 6, 10, 11 and 12. It uses `align.load_snapshot(unit_dir, "before")` and `align.align(…)`.
- Produces:
  - `driver.client_words(text: str) -> str`: drops a first line that starts with `Re:`, and the blank lines after it.
  - `driver.reply_files(answer_file: Path) -> list[Path]`: the other files in the same folder, apart from names
    matching `*_reply_*.txt`.
  - `driver.plan_replies(unit, key, snap, al) -> list[dict]`: in `answer_date` order, one
    `{"query_id", "answer_file", "question_id", "question_text", "send"}` per query with an `answer_file`. `send` is
    true when an app question with status `open` or `waiting` (from `snap.questions` or its reviews' questions)
    matches through `query_for`.
  - `driver.send_replies(api, unit, key, progress, unit_dir, *, relay=None, options) -> None`. It:
    1. opens one thread (`progress.thread_id`, and `progress.chat_year` from the thread's `year_start`)
    2. for each planned reply with `send`: sends the text `"> " + question_text + "\n\n" + client_words(reply)` with
       its files, while `relay.set_part(unit.slug, "chat")` is set
    3. appends each turn's events to `unit_dir/chat.jsonl`
    4. records `progress.replies[query_id] = {"sent", "question_id", "events", "asked_back"}`, where `asked_back` holds
       the questions found in `result` events
    5. waits for the review after the last turn
    6. saves

    A reply that is not sent is recorded with `sent: false`.

- [ ] **Step 1: Write the failing tests**

```python
def test_client_words_drop_the_key_question():
    assert driver.client_words("Re: Is that right?\n\nYes, that's my personal one.\n") == "Yes, that's my personal one."
def test_reply_files_exclude_other_replies(tmp_path): ...
def test_reply_sent_only_when_the_app_asked():
    # snap.questions has one open question matching MN-Q0002 ("Can you upload the full VAT invoice?"); none for MN-Q0001
    [m] = fake.messages_sent
    assert m.text.startswith("> Can you upload the full VAT invoice?") and "Re:" not in m.text
    assert [p.name for p in m.files] == ["2024-02-08_wharf_woi-1.pdf"]
    assert progress.replies["MN-Q0001"]["sent"] is False
def test_chat_year_recorded():  # FakeApi.new_thread returns year_start "2026-04-01" -> progress.chat_year == "2026-04-01"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_replies.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the four functions**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): send a client's reply only to a question the app asked" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Checks: documents, statement lines and extra rows

**Files:**
- Create: `testbooks_runner/checks.py`
- Test: `testbooks_runner/tests/test_checks_documents.py`

**Interfaces:**
- Consumes: Tasks 2 and 12.
- Produces:
  - `checks.Outcome` (frozen dataclass):
    - `check: str`, `ref: str`
    - `status: str`: `"pass"`, `"fail"`, `"not_attempted"`, `"cant_compare"`, `"not_read"`, `"explained"` or
      `"excluded"`
    - `cases: tuple[str, ...]`
    - `stakes: str`: `"tax"`, `"accounts"`, `"presentation"` or `"process"`
    - `phase: str`: `"before"` or `"after"`
    - `expected: str = ""`, `got: str = ""`, `cause: str = ""`, `where: str = ""`
    - `amount: Decimal = Decimal(0)`, `identity: str = ""`
    - `data: dict = field(default_factory=dict)`
  - `checks.STAKES_ORDER = ("tax", "accounts", "presentation", "process")`
  - `checks.CAUSES = ("misread", "booked wrong", "changed by the review", "changed by the chat", "not read",
    "the app never asked", "chat couldn't reach the year", "made up or read twice", "unexplained")`
  - `checks.identity(check: str, unit: Unit, *content) -> str`: the sha1 of `json.dumps([check, unit.name,
    str(unit.period.end), *content])`, first 16 hex characters. The content is what the key row says (Task 18 relies
    on this):
    - document: `file, kind, issuer, number, date, gross`
    - line: `account, date, description, amount`
    - entry group: the sorted `(date, account, debit, credit, counterparty)` of its key lines
    - extra row: `file, date, gross, description`
    - tb: `code, phase`; opening: `code`; vat: `start, end, box`
    - unpaid: `counterparty, number, gross`
    - query: `question`
  - `checks.booked(rows: list[dict], al) -> bool`: true when any row's posted lines aren't all zero.
  - `checks.check_documents(unit, key, snap, al, profile, phase, progress) -> list[Outcome]`: it reads
    `progress.replies` to tell an answer document that was never sent.
  - `checks.check_lines(unit, key, al) -> list[Outcome]`
  - `checks.check_extra_rows(unit, al) -> list[Outcome]`

- [ ] **Step 1: Write the failing tests**

```python
def test_document_to_book_that_was_booked_passes():
def test_evidence_that_was_booked_fails_as_booked_wrong():  # prior TB rows posted -> fail, cause "booked wrong", stakes "accounts"
def test_document_misread_when_gross_differs():             # key gross 120.00, app row 102.00 -> cause "misread"
def test_unread_file_is_not_read():                         # file refused -> status "not_read", cause "not read"
def test_answer_document_never_sent_says_never_asked():     # MN-D0003, reply not sent -> "not_read", cause "the app never asked"
def test_statements_are_judged_by_their_lines_not_as_documents():
def test_lines_pass_or_misread_or_missed():                 # exact -> pass; "date" -> fail misread; unpaired -> fail misread
def test_extra_row_is_made_up_or_read_twice():
def test_identity_ignores_the_key_numbering():
    # two outcomes for the same content under different doc IDs share the identity
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_checks_documents.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the outcome type and the three checks**

- **Which documents are statements:** a document whose ID's first word is a profile account ID is a statement, and is
  skipped by `check_documents`.
- **`ref`** is `f"{unit.ref}:{check}:{key id}"`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): check documents, statement lines and made-up rows" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Checks: entries and the journals with no paper

**Files:**
- Modify: `testbooks_runner/checks.py`
- Test: `testbooks_runner/tests/test_checks_entries.py`

**Interfaces:**
- Consumes: Tasks 3, 12 and 14.
- Produces:
  - `checks.paperless_journals(key) -> dict[str, list[dict]]`: journal ID to lines, for `books` and `answers`
    journals with no `doc_ids` and no `line_ids`.
  - `checks.is_vat_transfer(lines: list[dict]) -> bool`: true when every line is on 2200, 2201 or 2202.
  - `checks.app_nets(rows: list[dict], al) -> dict[str, Decimal]`: app code to debit less credit, over the rows' posted
    lines.
  - `checks.nets_match(key_lines: list[tuple[str, Decimal, tuple[str, ...]]], app: dict[str, Decimal],
    tolerance: Decimal) -> tuple[bool, dict[str, Decimal]]`. Each key line is `(primary app code, signed amount,
    choices)`. It tries the choices (up to 64 combinations, then greedily) and returns whether it matched and the best
    per-code deltas, app less key.
  - `checks.app_vat_label(row: dict) -> str`, one of:
    - `"reverse charge"` when `reverse_charge`
    - `f"VAT {vat_posted}"` when `vat_posted > 0`
    - `"VAT not reclaimed: " + why` when `vat_not_reclaimed > 0`
    - `"no VAT"`
  - `checks.check_entries(unit, key, snap, al, chart, vat_table, phase, progress) -> list[Outcome]`
  - `checks.not_attempted(unit, key) -> list[Outcome]`: one outcome per paperless journal and per `year_end` journal.

- [ ] **Step 1: Write the failing tests**

```python
def test_entry_passes_with_also_ok():   # key 7504 266.67 Dr, 9998 53.33 Dr (also_ok 7504), 1240 320.00 Cr; app 7504 320 Dr, 1240 320 Cr
def test_entry_fails_with_tax_stakes_when_vat_reclaimed_early():
    # app 7504 266.67, 2201 53.33, 1240 -320 -> fail; data["deltas"] == {"2201": "53.33", "9998": "-53.33"}; stakes "tax"
def test_chart_choices_count():         # key 4010 Cr 1200.00; app 4000 Cr 1200.00 -> pass
def test_tolerance_only_for_worked_out_vat():  # 1p off with row vat None, vat_posted 3.33 -> pass; with vat "3.33" printed -> fail
def test_causes():
    # gross differs from documents.csv -> "misread"; row decision_ids -> decision trigger "background" -> "changed by the review"
    # otherwise -> "booked wrong"
def test_after_phase_checks_only_groups_with_answers_journals_and_names_the_reason():
    # reply not sent -> cause "the app never asked"; sent, chat_year "2026-04-01" != app year -> "chat couldn't reach the year"
def test_paperless_and_year_end_are_not_attempted():  # VAT-2023-05-31, AG-0554, YE-01 -> status "not_attempted"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_checks_entries.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the entry checks**

- **Which journals:**
  - `before`: every non-paperless group, using its `books` journals.
  - `after`: only groups holding an `answers` journal, using their `books` and `answers` journals.
- **Key lines:** each becomes `(app_code(account), debit - credit, choices(account, also_ok))`.
- **App lines:** the rows from `rows_by_doc` for the group's docs, plus `line_rows` for its lines.
- **Tolerance:** `Decimal("0.01")` when any of those rows has `vat` null and a non-zero `vat_posted`, otherwise `0`.
- **Stakes:** the highest by `STAKES_ORDER` among the catalogue stakes of the group's cases. With no cases, `"tax"`
  when a delta falls on 2200 or 2201, else `"accounts"`.
- **Cause:** the first that applies:
  1. not read
  2. misread
  3. changed by the review or the chat, from `snap.decisions` (`trigger`)
  4. in `after` only: the app never asked, or the chat couldn't reach the year
  5. booked wrong
- **Expected and got:** each is a line like `"7504 266.67 Dr; 9998 53.33 Dr (or 7504); 1240 320.00 Cr"`, followed by
  the VAT labels.
- **Data:** keep `data["deltas"]` and `data["dates"]`, for Task 16.
- **Presentation notes:** when a group passes only because two of its key accounts map to the same app code (4000 and
  4010 both to 4000, say), add `data["presentation"]`: `"key 4000 and 4010 are one app account, 4000"`. Task 19 lists
  these notes.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): check every transaction's entries, and the journals the app can't make" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Checks: trial balance, VAT, unpaid invoices and queries

**Files:**
- Modify: `testbooks_runner/checks.py`
- Test: `testbooks_runner/tests/test_checks_totals.py`

**Interfaces:**
- Consumes: Tasks 12, 14 and 15.
- Produces:
  - `checks.check_trial_balance(unit, key, snap, chart, entry_outcomes, phase) -> list[Outcome]`
  - `checks.check_opening(unit, key, snap, chart) -> list[Outcome]`
  - `checks.check_vat(unit, key, snap, entry_outcomes) -> list[Outcome]`
  - `checks.check_unpaid(unit, key, snap, sent_next_year: bool) -> list[Outcome]`
  - `checks.check_queries(unit, key, snap, al, progress) -> list[Outcome]`
  - `checks.extra_questions(snap, al, key) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
def test_tb_pass_explained_fail():
    # key before_answers 7504 100.00; app 153.33 with an entry delta of 53.33 on 7504 -> "explained"; 200.00 -> "fail" amount 100.00
def test_tb_takes_out_paperless_journals():  # VAT-2023-05-31 moves 26495.32 from 2200 to 2202; app has none -> 2200 and 2202 pass
def test_tb_after_uses_final_less_year_end():
def test_opening_compared_once():           # phase "before" only
def test_vat_quarter_straddling_the_books_cannot_be_compared():
def test_vat_bad_debt_relief_taken_out_of_box_4():   # paperless AG-0554 with 2201 800.00 Dr in Dec-Feb -> key box 4 less 800
def test_vat_box_explained_by_entry_faults_in_the_quarter():
def test_unpaid_matched_by_number_then_counterparty():
def test_unpaid_write_off_taken_out():      # app still owes 4800 from that counterparty; paperless write-off 4800 -> not a fault
def test_unpaid_cannot_be_compared_after_next_year_papers():
def test_queries_asked_or_never_asked():    # never asked -> fail, cause "the app never asked", stakes from the query
def test_extra_questions_listed():
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_checks_totals.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement the five checks**

- **Trial balance:**
  - The key column is `before_answers` for `before`, and `final - year_end` for `after`. It is mapped to app codes,
    then reduced by the paperless journals' lines (`books` ones for `before`, `books` and `answers` for `after`).
  - The difference is the app's posted trial balance (`snap.posted[scored_year]["lines"]`, debit less credit) less
    that column.
  - Status: within 1p is `pass`. Within 1p after taking off the entry outcomes' deltas for that code is `explained`.
    Anything else is `fail`, with cause `unexplained` and `amount` set to the raw difference.
- **VAT:**
  - The quarter must lie inside the period, or the outcome is `cant_compare`.
  - Paperless non-transfer journals dated in the quarter adjust the key's boxes: a 2201 debit comes off box 4, and a
    2200 credit off box 1. Boxes 3 and 5 are then worked out again.
  - Boxes 1–5 are compared to 1p, and boxes 6–9 to £1.
  - A differing box is `explained` when any failing entry outcome has a date in the quarter, else `fail`.
- **Unpaid:**
  - The key side is the rows at the latest `as_at` on or before the period end. The app side is invoices with
    `owed > 0`.
  - Match by normalised number (upper-case, spaces removed), else by counterparty and total.
  - App invoices matching a paperless 1100 write-off by counterparty and amount are dropped.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): check the trial balance, VAT boxes, unpaid invoices and questions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: Cases, the headline and Pass^k

**Files:**
- Create: `testbooks_runner/cases.py`
- Test: `testbooks_runner/tests/test_cases.py`

**Interfaces:**
- Consumes: `Outcome` and `STAKES_ORDER` (Task 14), and `books.load_catalogue` (Task 2).
- Produces:
  - `cases.CaseResult` dataclass: `case`, `title`, `category`, `stakes`, `status`, `passed: int`, `total: int`,
    `outcomes: list[Outcome]`.
  - `cases.roll_up(outcomes, catalogue) -> list[CaseResult]`:
    - It ignores `explained` and `excluded` outcomes, and counts each `ref` once, at its worst status across phases.
    - The status is `fail` if any outcome failed; else `not_read` if any wasn't read; else `pass` if any passed; else
      `not_attempted` if all were not attempted; else `cant_compare`.
    - Results are sorted by stakes, then case.
  - `cases.headline(outcomes, case_results) -> dict`, with:
    - `by_stakes`: `{stakes: {status: count}}`
    - `entries_right`, `documents_right` and `queries_asked`: `[n, total]`
    - `tb_difference`: `{"before": str, "after": str}`, the sum of `amount` over trial balance outcomes that didn't
      pass
    - `vat_difference: str`
    - `files_not_read: int`
  - `cases.pass_k(results_by_repeat: list[list[CaseResult]]) -> dict[str, str]`: `"pass"` when every repeat passed,
    `"flaky"` when some passed and some failed, `"fail"` when every repeat failed, otherwise the shared status.

- [ ] **Step 1: Write the failing tests**

```python
def test_one_failure_fails_the_case_and_counts():  # 12 outcomes for EC-0334, one fail -> status "fail", passed 11, total 12
def test_not_attempted_only_when_all_are():       # [not_attempted, pass] -> "pass"; [not_attempted, not_attempted] -> "not_attempted"
def test_explained_and_excluded_ignored():        # [explained, excluded, pass] -> "pass", total 1
def test_worst_phase_counts_once():               # same ref: before pass, after fail -> one outcome counted, status "fail"
def test_ordered_by_stakes():                     # tax cases before accounts cases
def test_headline_figures():
    # 3 entry outcomes (2 pass) -> entries_right [2, 3]; tb fails 10.00 and 5.00 before -> tb_difference["before"] == "15.00"
def test_pass_k_and_flaky():                      # [[pass],[pass]] -> "pass"; [[pass],[fail]] -> "flaky"; [[fail],[fail]] -> "fail"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_cases.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `cases.py`**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): roll faults up to catalogue cases, with Pass^k" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: Verdicts and comparison with an earlier run

**Files:**
- Create: `testbooks_runner/verdicts.py`, `testbooks_runner/compare.py`
- Test: `testbooks_runner/tests/test_verdicts.py`, `testbooks_runner/tests/test_compare.py`

**Interfaces:**
- Consumes: `Outcome` (Task 14).
- Produces:
  - `verdicts.VERDICTS_CSV = Path(__file__).parent / "verdicts.csv"`
  - `verdicts.KINDS = ("app wrong", "key wrong", "both acceptable", "runner wrong")`
  - `verdicts.Verdict` dataclass: `identity`, `ref`, `verdict`, `whats_right`, `who`, `date`, `got`.
  - `verdicts.load(path=VERDICTS_CSV) -> dict[str, Verdict]` and `verdicts.save(v: dict[str, Verdict], path)`.
  - `verdicts.apply(outcomes, v) -> list[Outcome]`, matched by `identity`:
    - `app wrong`: unchanged, with `data["known"] = True`
    - `key wrong` and `runner wrong`: status `excluded`
    - `both acceptable` with the same `got`: status `pass`, with `data["accepted"] = True`
    - `both acceptable` with another `got`: unchanged, with `data["verdict_lapsed"] = True`

    Every matched outcome gets `data["verdict"]`.
  - `verdicts.orphans(v, outcomes) -> list[Verdict]`: the verdicts whose identity matches no outcome.
  - `verdicts.import_xlsx(xlsx: Path, path=VERDICTS_CSV) -> int`: reads the `differences.xlsx` columns (Task 19) and
    upserts the rows whose Verdict is one of `KINDS`, ignoring case. An unknown value raises `ValueError` naming the
    row number.
  - `verdicts.key_corrections(outcomes) -> list[dict]`: `{"ref", "expected", "got", "whats_right", "who"}` for
    `key wrong`.
  - `compare.compare(current, previous) -> dict[str, list[Outcome]]`, matched by `identity`:
    - `new`: fails now, and wasn't there before
    - `flipped`: fails now, and passed before
    - `fixed`: failed before, and passes now
    - `still`: failed both times

- [ ] **Step 1: Write the failing tests**

```python
def test_each_kind_applies(): ...
def test_verdict_lapses_when_key_row_changes():
    # verdict on identity of content A; key row now says B -> outcome unchanged; verdict listed by orphans()
def test_import_from_a_filled_spreadsheet(tmp_path):  # openpyxl writes the Task 19 columns; 2 filled rows -> 2 imported
def test_import_refuses_an_unknown_verdict(tmp_path):
def test_key_corrections_for_key_wrong():
def test_compare_new_fixed_still_flipped():
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_verdicts.py testbooks_runner/tests/test_compare.py -q`.
Expected: FAIL.

- [ ] **Step 3: Implement `verdicts.py` and `compare.py`**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): verdicts kept by what the key says, and run-to-run changes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: Reports

**Files:**
- Create: `testbooks_runner/report.py`
- Test: `testbooks_runner/tests/test_report.py`

**Interfaces:**
- Consumes: Tasks 14, 17 and 18.
- Produces:
  - `report.UNREVIEWED = "The key is unreviewed: a difference may be the key's mistake."`
  - `report.RunSummary` dataclass:
    - `run_name`, `selection: str`
    - `app: dict`, `set: dict`
    - `review: str`
    - `calls: int`, `replayed: int`
    - `cost: Decimal`, `cost_by_part: dict`, `estimate: Decimal | None`, `seconds: float`
    - `units: list[dict]`, each with `slug`, `status`, `chat_year`, `app_year`, `refusals`, `not_read`,
      `replies_not_sent` and `asked_back`
    - `outcomes: list[Outcome]`, `cases: list[CaseResult]`, `headline: dict`
    - `pass_k: dict | None`, `changes: dict | None`, `previous: str | None`
    - `extra_questions: list[dict]`, `orphans: list`, `signed_off: bool`
  - `report.write_all(run_dir: Path, s: RunSummary) -> None`, which writes four files:
    - **`report.md`:**
      - Line 1 is `# <run_name>`.
      - When `not s.signed_off`, line 3 is `> **<UNREVIEWED>**`.
      - The sections follow, in this order: What was run, Cost and time, Headline, Pass^k, Changes since
        `<previous>`, Faults by case, Not attempted, Can't be compared, Presentation notes, Questions the app asked
        that the key doesn't, Replies not sent, Files not read and refusals, The chat, Verdicts that no longer match.
      - Sections with nothing to say are left out.
    - **`faults.csv`**, with the columns `identity,ref,check,phase,status,cases,stakes,cause,where,expected,got,amount,
      verdict`.
    - **`differences.xlsx`:**
      - One sheet, `Differences`, with exactly these columns: ID, Identity, Cases, Case title, Stakes, Check, Where,
        Key expects, App did, Cause, Failed in runs, Verdict, What's right, Who, Date.
      - Identity is hidden.
      - There is one row per `fail` outcome, plus the `excluded` ones with their verdicts filled in.
    - **`key-corrections.csv`**

- [ ] **Step 1: Write the failing tests**

```python
def test_banner_unless_signed_off(tmp_path):
    report.write_all(tmp_path, summary(signed_off=False)); assert report.UNREVIEWED in (tmp_path / "report.md").read_text().splitlines()[2]
    report.write_all(tmp_path, summary(signed_off=True));  assert report.UNREVIEWED not in (tmp_path / "report.md").read_text()
def test_sections_in_order(tmp_path):
def test_differences_xlsx_columns_and_rows(tmp_path):
def test_faults_csv(tmp_path):
def test_key_corrections_written(tmp_path):
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_report.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `report.py`**

The faults section is grouped by case, in stakes order. Each fault gives its where, key expects, app did, cause and
verdict.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): the run report, the faults list and the verdicts spreadsheet" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 20: Estimates and measurements

**Files:**
- Create: `testbooks_runner/estimate.py`
- Test: `testbooks_runner/tests/test_estimate.py`

**Interfaces:**
- Consumes: Tasks 2, 6 and 9.
- Produces:
  - `estimate.MEASUREMENTS = runs.RUNS / "measurements.json"`
  - `estimate.file_kind(path: Path) -> str`:
    - `"pdf"`
    - `"image"`: jpg, jpeg, png, heic, heif, webp, gif, tif, tiff
    - `"sheet"`: csv, tsv, xlsx, xls, ofx, qif
    - `"text"`: txt, eml, docx
    - `"other"`
  - `estimate.ROUGH`, with tokens per call and seconds:

    | kind | in | out | seconds |
    |---|---|---|---|
    | pdf | 7000 | 3000 | 45 |
    | image | 5000 | 3000 | 45 |
    | sheet | 9000 | 8000 | 90 |
    | text | 4000 | 2000 | 30 |
    | other | 6000 | 3000 | 45 |
    | review | 40000 | 5000 | 120 |
    | chat | 40000 | 5000 | 120 |

  - `estimate.model_price(model: str, *, get=httpx.get) -> dict | None`:
    1. `GET https://openrouter.ai/api/v1/models`, with no key.
    2. Find the entry whose `id == model`.
    3. Return `{"in": Decimal(pricing.prompt), "out": Decimal(pricing.completion)}`, or `None` on any failure.
  - `estimate.Workload(unit, files: dict[str, int], batches: list[dict[str, int]], replies: int)`
  - `estimate.workload(unit, key, with_next_year: bool) -> Workload`
  - `estimate.Estimate(cost: Decimal | None, seconds: float, rough: bool, basis: str)`
  - `estimate.estimate(workloads, *, measurements: dict | None, price: dict | None, pool: int, review: str,
    parallel: int = 5) -> Estimate`
  - `estimate.update_measurements(run_dir: Path, path: Path = MEASUREMENTS) -> dict`, which yields
    `{"model", "kinds": {kind: {"cost", "seconds", "n"}}, "review": {...}, "chat": {...}}`.
  - `estimate.format_plan(workloads, est: Estimate, pool: int) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_file_kinds():
def test_rough_estimate_from_the_listed_price():  # 2 pdf files, price in=1e-7 out=4e-7 -> cost 2*(7000e-7+3000*4e-7); rough True
def test_no_price_means_cost_unknown():           # cost None; format_plan says "cost unknown"
def test_measured_estimate_and_pool_time():       # 4 units of 600 s each: pool 4 -> 600 s; pool 1 -> 2400 s
def test_review_off_drops_review_cost_and_time():
def test_measurements_share_a_call_among_overlapping_reads(tmp_path):
    # one reader call (cost 0.10) during two overlapping jobs (pdf, sheet) -> pdf 0.05 and sheet 0.05; merged with existing by n
def test_model_price_parses_the_listing():        # get returns {"data": [{"id": "qwen/qwen3.8-27b", "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}}]}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_estimate.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `estimate.py`**

- **Time for one unit:** for each batch, `ceil(files / parallel)` × the slowest kind's seconds in that batch. Add the
  review's seconds for each batch that has files, unless the review is `off`. Add `replies` × the chat seconds.
- **Time for the run:** assign the units longest first, each to the least-loaded of `pool` copies. The time is the
  largest load.
- **Cost:** with measurements, the measured costs per kind. Otherwise rough tokens × price, with `rough=True`.
- **Measurements:**
  - A reader call's cost is split equally among that unit's jobs whose `submitted`–`finished` span covers the call's
    `started`.
  - Review cost is the review total divided by the number of review runs, and the same for chat turns.
  - New figures merge with existing ones, weighted by `n`.
- **`format_plan`** prints these lines:
  - the units
  - `Files: N (pdf …, sheet …)`
  - `Reads: N; reviews: about N; chat turns: up to N`
  - `Expected cost: $X`, followed by `(rough: no runs measured yet)` when rough
  - `Expected time: about H h M min with N copies`

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): cost and time estimates from measured runs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 21: Scoring a saved run

**Files:**
- Create: `testbooks_runner/score.py`
- Test: `testbooks_runner/tests/test_score.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 9, 12, and 14–19.
- Produces:
  - `score.score_unit(unit, set_dir: Path, unit_dir: Path, chart, vat_table, catalogue,
    sent_next_year: bool) -> tuple[list[Outcome], list[dict]]`. It returns the outcomes of both phases and the extra
    questions, and writes `unit_dir/results.json`.
  - `score.score_run(run: RunDir, set_dir: Path, *, verdicts_path: Path = VERDICTS_CSV, against: RunDir | None = None,
    relay_totals: dict | None = None) -> RunSummary`. It:
    1. scores every unit that has a `raw/before`
    2. applies verdicts
    3. rolls the outcomes up
    4. groups repeats by `Unit.ref` for `pass_k`
    5. compares with `against`, or with `runs.previous_run`
    6. writes the report (Task 19)
    7. sets `run.json["scored"]`

    Without `relay_totals`, the cost comes from `relay/costs.jsonl`.

- [ ] **Step 1: Write the failing tests**

```python
def test_scoring_needs_no_app_or_network(tmp_path, monkeypatch):
    # a run folder with raw snapshots written by builders for the fixture pack; httpx.Client patched to raise
    s = score.score_run(run, FIX)
    assert (run.path / "report.md").exists() and s.headline["documents_right"][1] > 0
def test_rescoring_after_the_key_changes_lists_orphans(tmp_path):  # verdicts.csv with an identity no outcome has -> s.orphans
def test_repeats_give_pass_k(tmp_path):                            # two units r1 and r2 of the same pack -> s.pass_k not None
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_score.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `score.py`**

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): score a saved run without the app or the model" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 22: Running a selection: the pool, the spending guard and resume

**Files:**
- Create: `testbooks_runner/orchestrate.py`
- Test: `testbooks_runner/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: Tasks 2, 6–11, 13, 20 and 21.
- Produces:
  - `orchestrate.RunOptions` dataclass:
    - `set_dir: Path`, `app_dir: Path`, `python: str = sys.executable`
    - `mongodb_uri: str = "mongodb://localhost:27017"`
    - `pool: int = 4`, `review: str = "automatic"`
    - `replay: Path | None = None`, `with_next_year: bool = False`
    - `yes: bool = False`, `label: str | None = None`, `against: str | None = None`
    - `upstream: str = "https://openrouter.ai/api/v1"`
  - `orchestrate.SpendGuard(estimate: Decimal | None, *, yes: bool, ask=input)`, whose `.check(spent: Decimal) -> bool`
    behaves like this:
    - It always returns `True` when `estimate` is `None`.
    - Once `spent > 1.5 × threshold`, it returns `False` under `yes`. Otherwise it asks
      `"Spent $X against an estimate of $Y. Carry on? [y/N] "`. A `y` doubles the threshold and returns `True`.
  - `orchestrate.run_selection(units, options, *, runs_root: Path = RUNS, estimate: Decimal | None = None) -> RunDir`
  - `orchestrate.resume_run(run: RunDir, options) -> RunDir`

- [ ] **Step 1: Write the failing tests**

```python
def test_spend_guard():  # None -> True; yes & over -> False; ask "y" -> True then threshold doubled; ask "" -> False
def test_replay_with_repeat_is_refused():
def test_run_selection_with_fakes(tmp_path, monkeypatch):
    # monkeypatch start_copy/stop_copy/check_database/preflight to give FakeApi copies; relay against fake upstream
    run = orchestrate.run_selection([u1, u2], options(pool=2), runs_root=tmp_path)
    assert {x["status"] for x in run.read_json("run.json")["units"]} == {"done"} and (run.path / "report.md").exists()
def test_unit_failure_does_not_stop_the_others():  # one copy raises StartError -> that unit "failed: ...", the other "done"
def test_stop_by_spend_guard_marks_unit_stopped_and_resume_finishes_it():
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_orchestrate.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `orchestrate.py`**

`run_selection`:

1. Refuse `replay` together with repeats.
2. Run `preflight`.
3. Make `new_run(label or selection slug)`. Write `run.json` with:
   - `selection` (the CLI's selection string) and `options`
   - `app: app_commit(...)`, plus `model`, taken from the first copy's `api.health()["model"]` once it is up
   - `runner: testbooks_runner.__version__`
   - `set: {"path", "key_hashes": {slug: key_hash}}`
   - `estimate`, `started`
   - `units`: `[{slug, db, status: "pending"}]`, where each `db` is
     `f"tbrun_{run.name.replace('-', '_')}_{i}"`
4. Start one `Relay(options.upstream, run.path / "relay", replay_from=options.replay and options.replay / "relay")`.
5. Run the units on a `ThreadPoolExecutor(options.pool)`. For each unit:
   1. `check_database`, then `start_copy`, with `env = app_env(…, relay_url=relay.base_url(unit.slug))` and the log at
      `unit_dir/app.log`.
   2. `set_up`.
   3. `send_batches`, with `after_batch = lambda: guard.check(relay.totals()["cost"])`.
   4. `take_snapshot(before)`, then `send_replies`, then `take_snapshot(after)`.
   5. `stop_copy` in `finally`.
   6. Set the unit's status to `done`, `stopped` or `failed: <message>`.
6. Stop the relay, call `update_measurements`, then `score_run`. Set `finished`.

`resume_run` restarts the units that aren't `done`, with `check_database(resume=True)`.

Throughout, write one line to `run.path / "run.log"` for each unit start, batch done, snapshot, reply and unit end,
using the `logging` module. Never log a key or a document's contents.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): run a selection on a pool of app copies, with a spending guard and resume" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 23: The command line

**Files:**
- Create: `testbooks_runner/cli.py`, `testbooks_runner/__main__.py` (`raise SystemExit(cli.main())`)
- Test: `testbooks_runner/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2, 18 and 20–22.
- Produces: `cli.main(argv: list[str] | None = None) -> int`, with these subcommands:
  - `plan`: `--client NAME [--period YYYY-MM-DD] | --packs IDS | --smoke | --all-packs`, `--repeat k`, `--pool n`,
    `--review`, `--with-next-year`, `--set PATH`, `--app PATH`. It prints `format_plan`.
  - `run`: the same options, plus `--replay RUN`, `--label`, `--against RUN`, `--mongodb-uri URI` and `--yes`.
  - `resume RUN`
  - `score RUN [--against RUN]`
  - `verdicts XLSX`
  - `clean [--yes] [--folders-older-than DAYS]`

  The defaults are `--set testbooks/out`, `--app` the repo root, `--pool 4` and `--review automatic`.
- The model for the price comes from `OPENROUTER_MODEL` in the environment, else from the app's `.env` (that one line
  only), else `qwen/qwen3.8-27b`.

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_prints_the_estimate(capsys):  # --packs EC-0346 --set FIX, model_price patched -> "Reads: 6" in output
def test_run_asks_and_stops_on_no(monkeypatch, capsys):  # input "n" -> exit 0, run_selection not called
def test_run_prints_the_banner_with_the_summary():       # run_selection patched; output contains report.UNREVIEWED
def test_selection_error_exits_2_with_its_message(capsys):
def test_clean_only_drops_runner_databases():            # fake Mongo names ["ledgersync", "tbrun_a_1", "other"] -> drops ["tbrun_a_1"]
def test_verdicts_imports(tmp_path):
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m pytest testbooks_runner/tests/test_cli.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement `cli.py` with `argparse`**

- `run` prints the plan, then asks `Go ahead? [y/N] ` unless `--yes`.
- After a run, it prints the banner (unless signed off), the headline, and the path of `report.md`.
- `clean` lists what it will drop and asks unless `--yes`.

- [ ] **Step 4: Run them to see them pass**

Same command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add testbooks_runner && git commit -m "feat(runner): plan, run, resume, score, verdicts and clean commands" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 24: End to end against the real app, spending nothing

**Files:**
- Create: `testbooks_runner/tests/minimal.py`, with `minimal_instance(schema: dict) -> Any`. It builds the smallest
  JSON instance that fits a JSON schema:
  - an object gets its required properties
  - an array gets `minItems` items
  - a string is the first `enum` value, else `"1970-01-01"` for `format: date`, else `""`
  - numbers are 0, and booleans `False`
  - for `anyOf` and `oneOf`, it takes the first
  - `$ref` is resolved through `$defs`
- Modify: `testbooks_runner/tests/fake_upstream.py`. Add `make_minimal_upstream(calls)`, which answers
  `chat/completions` with `{"id": "gen-n", "choices": [{"message": {"role": "assistant",
  "content": json.dumps(minimal_instance(request.response_format.json_schema.schema))}, "finish_reason": "stop"}],
  "usage": {...}}`. `/generation` reports cost 0.
- Test: `testbooks_runner/tests/test_end_to_end.py`, marked `mongo`.

**Interfaces:**
- Consumes: Task 22's `run_selection`, and the frozen fixture pack (Task 2).

- [ ] **Step 1: Write the test**

```python
@pytest.mark.mongo
def test_fixture_pack_runs_through_the_real_app(tmp_path, monkeypatch):
    uri = os.environ["LEDGERSYNC_TEST_MONGODB_URI"]
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")   # env wins over .env; the fake upstream never checks it
    options = RunOptions(set_dir=FIX, app_dir=REPO, mongodb_uri=uri, pool=1, review="off", yes=True,
                         upstream=f"http://127.0.0.1:{up_port}/api/v1")
    run = orchestrate.run_selection(selection.select_units(FIX, packs=["EC-0346"]), options, runs_root=tmp_path)
    u = run.read_json("run.json")["units"][0]
    assert u["status"] == "done"
    progress = runs.load_progress(run.unit_dir(unit))
    assert set(progress.uploads) == {sent files}                    # every file has an outcome
    assert report.UNREVIEWED in (run.path / "report.md").read_text()
    assert any(json.loads(l)["part"] == "reader" for l in open(run.path / "relay/calls.jsonl"))
    # finally: drop u["db"] with pymongo
```

- [ ] **Step 2: Run it**

Run:
`LEDGERSYNC_TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest testbooks_runner/tests/test_end_to_end.py -q`.

Expected: PASS, in about a minute. If the app refuses a minimal reading, keep the assertions above. They are about the
plumbing, not about what the fake model read.

- [ ] **Step 3: Fix what the real app shows up**

Likely suspects:
- the paths the relay forwards for `/key` and `/models/user`
- how the multipart file field is named
- the review state when `ai_review` is `off`

Fix them in the module that owns each, with a unit test there, and run the whole runner suite:
`.venv/bin/python -m pytest testbooks_runner/tests -q`. Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add testbooks_runner && git commit -m "test(runner): a pack end to end through the real app with a fake model" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 25: README and the first live run

**Files:**
- Create: `testbooks_runner/README.md`. It covers:
  - what the runner does
  - set-up: the venv command, a local MongoDB, and the app's `.env` with `OPENROUTER_API_KEY` (a worktree needs its
    own copy)
  - the commands, with examples
  - where runs go
  - how to fill in and import verdicts
  - that the key is unreviewed
  - the app gaps from the spec, in its words

**Interfaces:**
- Consumes: everything.

- [ ] **Step 1: Write the README and commit it**

```bash
git add testbooks_runner/README.md && git commit -m "docs(runner): how to run the test books through the app" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Plan the five packs**

Run:
`.venv/bin/python -m testbooks_runner plan --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430`.

Expected: 28 files, about 5 batches each, and a rough cost marked as rough.

- [ ] **Step 3: Ask the user before spending**

This step reads about 28 documents with the paid model, and the Pass^2 check in Step 6 reads about 12 more. Show the
plan's cost and time for both, and wait for a clear yes.

- [ ] **Step 4: Run the five packs live**

Run: `.venv/bin/python -m testbooks_runner run --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430 --label packs-first`.

Expected: a report whose first lines carry the banner, a measured cost in "Cost and time", and
`runs/measurements.json` written.

- [ ] **Step 5: Rerun with replay and check it spent nothing on reads**

Run:
`.venv/bin/python -m testbooks_runner run --packs EC-0301,EC-0316,EC-0330,EC-0346,EC-0430 --replay <first run> --review off --label packs-replay --yes`.

Expected:
- "Cost and time" shows $0 for reading, and the replayed calls equal the reader calls.
- The headline matches the first run's on the checks that don't depend on the review.

- [ ] **Step 6: Run one pack twice for Pass^2**

Run: `.venv/bin/python -m testbooks_runner run --packs EC-0346 --repeat 2 --label pass2 --yes`.

Expected: the report has a Pass^k section giving EC-0346 as pass, fail or flaky, and each repeat's own results.

- [ ] **Step 7: Show the agency's estimate**

Run: `.venv/bin/python -m testbooks_runner plan --client agency`.

Expected: about 577 reads, with an estimate from the packs' measurements, no longer marked rough. Running it is the
user's call.
