import csv
from dataclasses import replace
from decimal import Decimal

import openpyxl

from testbooks_runner import report, verdicts
from testbooks_runner.cases import CaseResult
from testbooks_runner.checks import Outcome
from testbooks_runner.verdicts import Verdict


def out(ref="E1", status="fail", cases=("C1",), stakes="tax", identity=None, **kw):
    return Outcome(check=kw.pop("check", "entry"), ref=ref, status=status, cases=cases, stakes=stakes,
                   phase=kw.pop("phase", "after"), expected=kw.pop("expected", "100.00 to 4000"),
                   got=kw.pop("got", "100.00 to 5000"), cause=kw.pop("cause", "booked wrong"),
                   where=kw.pop("where", "a/file.pdf"), identity=identity or "id-" + ref, **kw)


def case(code="C1", stakes="tax", status="fail", title="Title one"):
    return CaseResult(code, title, "cat", stakes, status, 0, 1, [])


def summary(outcomes=None, cases=None, signed_off=False, **kw):
    base = dict(run_name="2026-11-20-test", selection="agency", app={"commit": "abc"}, set={"build": "b1"},
                review="off", calls=3, replayed=0, cost=Decimal("1.5"), cost_by_part={"reading": Decimal("1.0")},
                estimate=Decimal("2"), seconds=65.0, units=[], outcomes=outcomes if outcomes is not None else [],
                cases=cases if cases is not None else [], headline={}, signed_off=signed_off)
    base.update(kw)
    return report.RunSummary(**base)


def read_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def text(tmp_path):
    return (tmp_path / "report.md").read_text()


def verdict(o, kind, **info):
    return replace(o, data={**o.data, "verdict": {"verdict": kind, "whats_right": "x", "who": "AB", "date": "d",
                                                  **info}})


def test_banner_unless_signed_off(tmp_path):
    report.write_all(tmp_path, summary(signed_off=False))
    lines = text(tmp_path).splitlines()
    assert lines[0] == "# 2026-11-20-test" and report.UNREVIEWED in lines[2]
    report.write_all(tmp_path, summary(signed_off=True))
    assert report.UNREVIEWED not in text(tmp_path)


def test_sections_in_order(tmp_path):
    fail = out()
    s = summary(
        outcomes=[fail, out("P1", status="pass", data={"presentation": "uses 4000 for 4001"}),
                  replace(out("L1", status="pass"), data={"verdict_lapsed": True})],
        cases=[case(), case("C2", status="not_attempted"), case("C3", status="cant_compare")],
        headline={"by_stakes": {"tax": {"pass": 0, "fail": 1}}, "entries_right": [1, 2], "documents_right": [0, 0],
                  "queries_asked": [0, 1], "tb_difference": {"before": "1.00", "after": "0.50"},
                  "vat_difference": "0.00", "files_not_read": 2},
        pass_k={"C1": "flaky"}, changes={"new": [fail], "fixed": [], "still": [], "flipped": []},
        previous="2026-11-19-x", extra_questions=[{"text": "Why?"}],
        units=[{"slug": "agency", "status": "done", "chat_year": "2024", "app_year": "2023", "refusals": ["no"],
                "not_read": ["f.pdf"], "replies_not_sent": ["Q1"], "asked_back": ["Which year?"],
                "offers_confirmed": ["vat: 8250 £312.00"]}],
        orphans=[Verdict("i", "E9", "app wrong")])
    report.write_all(tmp_path, s)
    heads = [ln[3:] for ln in text(tmp_path).splitlines() if ln.startswith("## ")]
    assert heads == ["What was run", "Cost and time", "Headline", "Pass^k", "Changes since 2026-11-19-x",
                     "Faults by case", "Not attempted", "Can't be compared", "Presentation notes",
                     "Questions the app asked that the key doesn't", "Replies not sent", "Offers confirmed",
                     "Files not read and refusals", "The chat", "Verdicts that no longer match"]
    body = text(tmp_path)
    assert "$1.50" in body and "£0.50" in body and "100.00 to 5000" in body


def test_cost_and_time_says_when_the_cost_is_a_lower_bound(tmp_path):
    report.write_all(tmp_path, summary(unpriced=1))
    assert "- Cost: $1.50 (estimate $2.00)\n- 1 call had no cost from the provider, so the cost shown is a lower " \
           "bound\n" in text(tmp_path)
    report.write_all(tmp_path, summary())
    assert "lower bound" not in text(tmp_path)


def test_empty_sections_left_out(tmp_path):
    report.write_all(tmp_path, summary())
    heads = [ln[3:] for ln in text(tmp_path).splitlines() if ln.startswith("## ")]
    assert heads == ["What was run", "Cost and time"]


def test_faults_in_stakes_order_with_no_case_last(tmp_path):
    s = summary(outcomes=[out("A", cases=("C2",), stakes="accounts"), out("B", cases=(), stakes="tax"),
                          out("C", cases=("C1",), stakes="tax")],
                cases=[case("C1", "tax"), case("C2", "accounts", title="Two")])
    report.write_all(tmp_path, s)
    body = text(tmp_path)
    assert body.index("#### C1: Title one") < body.index(f"#### {report.NO_CASE}") < body.index("#### C2: Two")
    assert body.index("### Tax") < body.index("### Accounts")


def test_with_repeats_each_fault_says_which_runs_it_failed_in(tmp_path):
    both = [out("E1", identity="same", data={"repeat": r}) for r in (1, 2)]
    flaky = [out("E2", identity="flaky", data={"repeat": 2}), out("E2", identity="flaky", status="pass",
                                                                  data={"repeat": 1})]
    report.write_all(tmp_path, summary(outcomes=both + flaky, cases=[case()], pass_k={"C1": "flaky"}))
    faults = text(tmp_path).split("## Faults by case")[1]
    assert faults.count("- `E1`") == 1 and "  - Failed in runs: 1, 2" in faults.split("- `E1`")[1].split("- `E2`")[0]
    assert "  - Failed in runs: 2\n" in faults.split("- `E2`")[1]
    report.write_all(tmp_path, summary(outcomes=[out("E1")], cases=[case()]))  # one run: nothing to say
    assert "Failed in runs" not in text(tmp_path)


def test_excluded_and_accepted_listed_apart_after_faults(tmp_path):
    s = summary(outcomes=[out("F"), verdict(out("K", status="excluded"), "key wrong", whats_right="net 80"),
                          replace(verdict(out("A", status="pass"), "both acceptable"),
                                  data={"accepted": True, "verdict": {"verdict": "both acceptable",
                                                                       "whats_right": "either", "who": "CD",
                                                                       "date": "d"}})],
                cases=[case()])
    report.write_all(tmp_path, s)
    body = text(tmp_path)
    assert body.index("`F`") < body.index("### Left out by a verdict") < body.index("`K`")
    assert body.index("`K`") < body.index("### Accepted by a verdict") < body.index("`A`")
    assert "net 80" in body and "either" in body and "CD" in body


def test_faults_csv(tmp_path):
    f = verdict(out("E1", cases=("C1", "C2"), amount=Decimal("5.00")), "app wrong")
    report.write_all(tmp_path, summary(outcomes=[f, out("P", status="pass")]))
    rows = read_csv(tmp_path / "faults.csv")
    assert list(rows[0]) == ["identity", "ref", "check", "phase", "status", "cases", "stakes", "cause", "where",
                             "expected", "got", "amount", "verdict"]
    assert len(rows) == 1
    assert rows[0]["cases"] == "C1;C2" and rows[0]["amount"] == "5.00" and rows[0]["verdict"] == "app wrong"


def sheet(tmp_path):
    wb = openpyxl.load_workbook(tmp_path / "differences.xlsx")
    assert wb.sheetnames[0] == "Differences"
    return wb["Differences"]


def test_differences_xlsx_columns_and_rows(tmp_path):
    a1 = out("E1", identity="same", data={"repeat": 1})
    a2 = out("E1", identity="same", data={"repeat": 2})
    other = out("E2", cases=(), status="fail")
    ex = verdict(out("E3", status="excluded"), "key wrong", whats_right="net")
    report.write_all(tmp_path, summary(outcomes=[a1, a2, other, ex, out("P", status="pass")], cases=[case()]))
    ws = sheet(tmp_path)
    assert [c.value for c in ws[1]] == report.XLSX_COLUMNS
    assert ws.column_dimensions["B"].hidden
    rows = {r[0].value: [c.value for c in r] for r in ws.iter_rows(min_row=2)}
    assert set(rows) == {"E1", "E2", "E3"}
    assert rows["E1"][1] == "same" and rows["E1"][3] == "Title one" and rows["E1"][10] == "1, 2"
    assert rows["E3"][11] == "key wrong" and rows["E3"][12] == "net" and rows["E3"][13] == "AB"


def test_the_spreadsheet_carries_the_banner_on_a_read_me_sheet_until_signed_off(tmp_path):
    report.write_all(tmp_path, summary(outcomes=[out("E1", identity="abc")]))
    wb = openpyxl.load_workbook(tmp_path / "differences.xlsx")
    assert wb.sheetnames == ["Differences", "Read me"] and wb["Read me"]["A1"].value == report.UNREVIEWED
    report.write_all(tmp_path, summary(outcomes=[out("E1", identity="abc")], signed_off=True))
    assert openpyxl.load_workbook(tmp_path / "differences.xlsx").sheetnames == ["Differences"]


def test_xlsx_round_trips_through_import(tmp_path):
    report.write_all(tmp_path, summary(outcomes=[out("E1", identity="abc"), out("E2", identity="def")]))
    path = tmp_path / "differences.xlsx"
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Differences", "Read me"]  # the verdicts are read from the first, by its name
    ws = wb["Differences"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "E2":
            row[11].value = "key wrong"
            row[12].value = "net 80"
    wb.save(path)
    store = tmp_path / "verdicts.csv"
    assert verdicts.import_xlsx(path, store) == 1
    v = verdicts.load(store)["def"]
    assert (v.ref, v.verdict, v.whats_right, v.got) == ("E2", "key wrong", "net 80", "100.00 to 5000")


def test_key_corrections_written(tmp_path):
    k = verdict(out("E1", status="excluded"), "key wrong", whats_right="80.00")
    report.write_all(tmp_path, summary(outcomes=[k, out("E2")]))
    rows = read_csv(tmp_path / "key-corrections.csv")
    assert rows == [{"ref": "E1", "expected": "100.00 to 4000", "got": "100.00 to 5000", "whats_right": "80.00",
                     "who": "AB"}]


def test_no_temp_files_left(tmp_path):
    report.write_all(tmp_path, summary())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["differences.xlsx", "faults.csv", "key-corrections.csv",
                                                          "report.md"]


def test_every_unit_is_listed_with_its_status(tmp_path):
    units = [{"slug": "a-r1", "status": "done"}, {"slug": "b-r1", "status": "failed: no key"},
             {"slug": "c-r1", "status": "not scored: FileNotFoundError: profile.json"}]
    report.write_all(tmp_path, summary(units=units))
    body = text(tmp_path)
    for line in ("- Unit a-r1: done", "- Unit b-r1: failed: no key",
                 "- Unit c-r1: not scored: FileNotFoundError: profile.json"):
        assert line in body
