from dataclasses import replace
from datetime import datetime

import openpyxl
import pytest

from testbooks_runner import verdicts as V
from testbooks_runner.checks import Outcome

HEADERS = ["ID", "Identity", "Cases", "Case title", "Stakes", "Check", "Where", "Key expects", "App did", "Cause",
           "Failed in runs", "Verdict", "What's right", "Who", "Date"]


def out(identity="aaa", ref="ag:entry:1", status="fail", got="10.00", phase="after"):
    return Outcome(check="entry", ref=ref, status=status, cases=("C1",), stakes="tax", phase=phase,
                   expected="12.00", got=got, identity=identity)


def vd(identity="aaa", verdict="app wrong", got="10.00", ref="ag:entry:1"):
    return V.Verdict(identity=identity, ref=ref, verdict=verdict, whats_right="r", who="sj", date="2026-11-20",
                     got=got)


def sheet(tmp_path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Differences"
    ws.append(HEADERS)
    for r in rows:
        row = dict.fromkeys(HEADERS, "")
        row.update(r)
        ws.append([row[h] for h in HEADERS])
    path = tmp_path / "differences.xlsx"
    wb.save(path)
    return path


def test_each_kind_applies():
    v = {"a": vd("a", "app wrong"), "k": vd("k", "key wrong"), "r": vd("r", "runner wrong"),
         "b": vd("b", "both acceptable", got="10.00"), "l": vd("l", "both acceptable", got="old")}
    outs = [out(i, ref=i) for i in "akrbl"]
    a, k, r, b, l = V.apply(outs, v)
    assert (a.status, a.data["known"]) == ("fail", True)
    assert k.status == "excluded" and r.status == "excluded"
    assert (b.status, b.data["accepted"]) == ("pass", True)
    assert (l.status, l.data["verdict_lapsed"]) == ("fail", True)
    for o in (a, k, r, b, l):
        assert o.data["verdict"].keys() == {"verdict", "whats_right", "who", "date"}
    assert a.data["verdict"] == {"verdict": "app wrong", "whats_right": "r", "who": "sj", "date": "2026-11-20"}


def test_shared_identity_marked_on_every_outcome_and_original_untouched():
    original = [out("a", phase="before"), out("a", phase="after"), out("z")]
    res = V.apply(original, {"a": vd("a", "key wrong")})
    assert [o.status for o in res] == ["excluded", "excluded", "fail"]
    assert "verdict" not in res[2].data
    assert original[0].status == "fail" and original[0].data == {}


def test_verdict_lapses_when_key_row_changes():
    v = {"contentA": vd("contentA", "key wrong")}
    outs = [out("contentB")]
    res = V.apply(outs, v)
    assert res[0].status == "fail" and res[0].data == {}
    assert V.orphans(v, outs) == [v["contentA"]]
    assert V.orphans(v, [out("contentA")]) == []


def test_save_load_round_trip_sorted_by_ref(tmp_path):
    p = tmp_path / "v.csv"
    V.save({"2": vd("2", ref="b"), "1": vd("1", ref="a")}, p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "identity,ref,verdict,whats_right,who,date,got"
    assert [ln.split(",")[1] for ln in lines[1:]] == ["a", "b"]
    assert V.load(p) == {"1": vd("1", ref="a"), "2": vd("2", ref="b")}
    assert not list(tmp_path.glob("*.tmp"))


def test_load_missing_file_is_empty(tmp_path):
    assert V.load(tmp_path / "none.csv") == {}


def test_import_from_a_filled_spreadsheet(tmp_path):
    x = sheet(tmp_path, [
        {"ID": "r1", "Identity": "i1", "App did": "5.00", "Verdict": "app wrong", "What's right": "x", "Who": "ann",
         "Date": "2026-11-18"},
        {"ID": "r2", "Identity": "i2", "App did": "6.00", "Verdict": "key wrong", "What's right": "y", "Who": "bob",
         "Date": "2026-11-19"},
        {"ID": "r3", "Identity": "i3", "App did": "7.00"},
    ])
    p = tmp_path / "v.csv"
    assert V.import_xlsx(x, p) == 2
    got = V.load(p)
    assert set(got) == {"i1", "i2"}
    assert got["i2"] == V.Verdict("i2", "r2", "key wrong", "y", "bob", "2026-11-19", "6.00")


def test_import_ignores_case_and_spaces_and_stores_iso_date(tmp_path):
    x = sheet(tmp_path, [{"ID": "r1", "Identity": "i1", "Verdict": "  Both Acceptable ",
                          "Date": datetime(2026, 11, 20, 0, 0)}])
    p = tmp_path / "v.csv"
    assert V.import_xlsx(x, p) == 1
    v = V.load(p)["i1"]
    assert (v.verdict, v.date) == ("both acceptable", "2026-11-20")


def test_import_upserts_by_identity(tmp_path):
    p = tmp_path / "v.csv"
    V.save({"i1": vd("i1", "app wrong"), "i9": vd("i9", ref="z")}, p)
    x = sheet(tmp_path, [{"ID": "r1", "Identity": "i1", "Verdict": "key wrong"}])
    assert V.import_xlsx(x, p) == 1
    got = V.load(p)
    assert got["i1"].verdict == "key wrong" and "i9" in got


def test_import_refuses_an_unknown_verdict(tmp_path):
    x = sheet(tmp_path, [{"Identity": "i1", "Verdict": "app wrong"}, {"Identity": "i2", "Verdict": "maybe"}])
    p = tmp_path / "v.csv"
    with pytest.raises(ValueError, match="row 3"):
        V.import_xlsx(x, p)
    assert not p.exists()


def test_key_corrections_for_key_wrong():
    v = {"k": vd("k", "key wrong"), "a": vd("a", "app wrong")}
    res = V.apply([out("k", ref="r-k"), out("a", ref="r-a"), out("n", ref="r-n")], v)
    assert V.key_corrections(res) == [
        {"ref": "r-k", "expected": "12.00", "got": "10.00", "whats_right": "r", "who": "sj"}]


def test_key_corrections_one_entry_per_identity_preferring_after():
    v = {"k": vd("k", "key wrong")}
    res = V.apply([out("k", ref="r1", phase="before", got="1.00"), out("k", ref="r1", phase="after", got="2.00"),
                   out("k", ref="r1", phase="before", got="3.00")], v)
    assert [c["got"] for c in V.key_corrections(res)] == ["2.00"]
    res = V.apply([out("k", phase="before", got="1.00"), out("k", phase="before", got="3.00")], v)
    assert [c["got"] for c in V.key_corrections(res)] == ["1.00"]


def test_load_reads_a_file_with_a_byte_order_mark(tmp_path):
    p = tmp_path / "v.csv"
    p.write_bytes(b"\xef\xbb\xbf" + b"identity,ref,verdict,whats_right,who,date,got\ni1,r1,app wrong,x,ann,2026-11-20,5\n")
    assert V.load(p) == {"i1": V.Verdict("i1", "r1", "app wrong", "x", "ann", "2026-11-20", "5")}
    V.save(V.load(p), p)
    assert not p.read_bytes().startswith(b"\xef\xbb\xbf")
