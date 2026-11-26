import csv
import filecmp
import json
from datetime import date
from pathlib import Path

from testbooks.build import build

ENTRY_COLUMNS = ["entry_id", "journal_id", "date", "account", "account_name", "debit", "credit", "vat_code", "vat",
                 "counterparty", "deal_id", "doc_ids", "line_ids", "stakes", "also_ok", "phase", "cases"]


def built(tmp_path, name):
    return build(tmp_path / name, seed=7, clients=["agency"], until=date(2024, 6, 30))[0]


def header(path):
    with open(path, newline="") as f:
        return next(csv.reader(f))


def test_key_files_and_every_file_accounted_for(tmp_path):
    client = built(tmp_path, "a")
    key = client / "key" / "2024-03-31"
    assert header(key / "entries.csv") == ENTRY_COLUMNS
    assert header(key / "trial-balance.csv") == ["account", "name", "heading", "opening", "books", "before_answers",
                                                 "year_end", "final"]
    for name in ("documents", "statement-lines", "bank-recs", "vat-returns", "debtors", "creditors", "payroll",
                 "opening-balances", "fixed-assets", "owners", "year-end", "queries", "ct-working", "mess"):
        assert (key / f"{name}.csv").exists(), name
    assert (key / "key.xlsx").exists() and (key / "accounts.xlsx").exists()
    assert json.loads((client / "profile.json").read_text())["name"] == "Kestrel & Finch Digital Ltd"
    with open(key / "documents.csv", newline="") as f:
        listed = {r["file"] for r in csv.DictReader(f)}
    on_disk = {str(p.relative_to(client)) for folder in ("inbox", "answers")
               for p in (client / folder).rglob("*") if p.is_file()}
    assert listed <= on_disk
    assert {f for f in on_disk if f.startswith("inbox") and Path(f).name[:10] <= "2024-03-31"} <= listed


def test_the_april_bill_behind_an_accrual_is_listed(tmp_path):
    key = built(tmp_path, "a") / "key" / "2024-03-31"
    with open(key / "documents.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert any("EC-0505" in r["cases"] and r["date"] == "2024-04-09" for r in rows)
    assert any("EC-0501" in r["cases"] and r["kind"] == "bank_statement" for r in rows)


def test_same_seed_same_bytes(tmp_path):
    a, b = built(tmp_path, "a"), built(tmp_path, "b")
    for p in sorted(a.rglob("*")):
        if p.suffix in {".csv", ".json", ".txt"}:
            assert filecmp.cmp(p, b / p.relative_to(a), shallow=False), p
