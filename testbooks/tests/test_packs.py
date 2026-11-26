import csv
from datetime import date

from testbooks.build import build
from testbooks.checks import run_checks

FIVE = ["EC-0301", "EC-0316", "EC-0330", "EC-0346", "EC-0430"]


def entries(folder, case):
    with open(folder / "key" / "2024-06-30" / "entries.csv", newline="") as f:
        return [r for r in csv.DictReader(f) if case in r["cases"].split(";")]


def test_packs_build_and_pass(tmp_path):
    folders = build(tmp_path, seed=7, clients=[], packs=FIVE)
    assert [f.name for f in folders] == ["EC-0301-laptop-bought", "EC-0316-overseas-software", "EC-0330-client-dinner",
                                         "EC-0346-receipt-over-250", "EC-0430-two-coffees"]
    for f in folders:
        assert (f / "case.txt").read_text().startswith(f.name[:7])
        results = run_checks(f, date(2024, 6, 30))
        assert all(r.ok for r in results), (f.name, [r for r in results if not r.ok])


def test_pack_client_identifiers_check():
    from testbooks.ids import vat_number_valid
    from testbooks.packs.definitions import PACKS
    assert all(vat_number_valid(define().vat_number) for define, _ in PACKS.values())


def test_client_dinner_pack_blocks_the_vat(tmp_path):
    f = build(tmp_path, seed=7, clients=[], packs=["EC-0330"])[0]
    rows = entries(f, "EC-0330")
    assert {(r["account"], r["debit"]) for r in rows if r["debit"] != "0.00"} == {("7403", "186.00")}
    assert not any(r["account"] == "2201" for r in rows)


def test_the_other_packs_show_their_treatment(tmp_path):
    folders = dict(zip(FIVE, build(tmp_path, seed=7, clients=[], packs=FIVE)))
    debits = lambda case, phase="books": {(r["account"], r["debit"]) for r in entries(folders[case], case)
                                           if r["debit"] != "0.00" and r["phase"] == phase}
    assert debits("EC-0301") >= {("0030", "1082.50"), ("2201", "216.50")}
    assert {("7550", "250.00"), ("2201", "50.00")} <= debits("EC-0316")
    assert any(r["account"] == "2200" and r["credit"] == "50.00" for r in entries(folders["EC-0316"], "EC-0316"))
    assert debits("EC-0346") == {("7504", "266.67"), ("9998", "53.33")}       # booked until the invoice comes
    assert debits("EC-0346", "answers") == {("2201", "53.33")}                 # the answer reclaims the VAT
    coffees = [r for r in entries(folders["EC-0430"], "EC-0430") if r["account"] == "7406" and r["phase"] == "books"]
    assert len(coffees) == 2
    with open(folders["EC-0316"] / "key" / "2024-06-30" / "vat-returns.csv", newline="") as f:
        june = next(csv.DictReader(f))
    assert june["period_end"] == "2024-06-30"
