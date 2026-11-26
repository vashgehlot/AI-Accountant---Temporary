import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from testbooks_runner import score
from testbooks_runner.runs import RunDir, new_run
from testbooks_runner.tests import builders as b
from testbooks_runner.verdicts import Verdict, save

FIX = Path(__file__).parent / "fixtures" / "set"
NAME = "EC-0346-receipt-over-250"
START, END = "2024-06-01", "2024-06-30"
SALES = "inbox/2024-06-04/2024-06-03_fernbrook-consulting-ltd_fc-0412.pdf"
RECEIPT = "inbox/2024-06-11/2024-06-10_wharfside-office-interiors_0911-04.pdf"
VERDICTS = "verdicts.csv"


def entry(repeat=1):
    return {"slug": f"{NAME}-{END}-r{repeat}", "db": f"tbrun_{repeat}", "status": "done", "name": NAME,
            "kind": "pack", "period_start": START, "period_end": END, "repeat": repeat}


def write_raw(unit_dir: Path, which: str, snap) -> None:
    raw = unit_dir / "raw" / which
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"ledger-{START}.json").write_text(json.dumps(snap.ledgers[START]), encoding="utf-8")
    (raw / f"posted-{START}.json").write_text(json.dumps(snap.posted[START]), encoding="utf-8")
    for name in ("invoices", "questions", "decisions", "reviews", "accounts"):
        (raw / f"{name}.json").write_text("[]", encoding="utf-8")


def books_snapshot(booked_sales=True):
    rows = [b.row(1, 11, gross="3000.00", direction="in", document_type="invoice", date="2024-06-03"),
            b.row(2, 12, gross="320.00", document_type="receipt", date="2024-06-10")]
    if not booked_sales:
        rows = rows[1:]
    posted = [b.posted(r["id"], "4010" if r["id"] == 1 else "7504", credit="2500.00" if r["id"] == 1 else "0",
                       debit="0" if r["id"] == 1 else "266.67") for r in rows]
    return b.snapshot(rows=rows, posted_lines=posted, scored_year=START,
                      uploads=[{"id": 11, "name": Path(SALES).name}, {"id": 12, "name": Path(RECEIPT).name}])


def make_run(root: Path, label="packs", repeats=(1,), booked_sales=True, selection="packs", finished=None,
             with_after=False, after_booked=None, after_done=True) -> RunDir:
    run = new_run(label, root, today=date(2026, 11, 20))
    info = {"selection": selection, "app": {"commit": "abc"}, "set": {"build": "b1"},
            "units": [entry(r) for r in repeats]}
    if finished:
        info["finished"] = finished
    run.write_json("run.json", info)
    for r in repeats:
        unit_dir = run.path / "units" / entry(r)["slug"]
        write_raw(unit_dir, "before", books_snapshot(booked_sales))
        if with_after:
            write_raw(unit_dir, "after", books_snapshot(booked_sales if after_booked is None else after_booked))
        progress = {"client_id": 1, "app_year_start": START, "bank_codes": {"hsbc": "1200"},
                    "after_done": with_after and after_done,
                    "uploads": b.uploads_progress({SALES: 11, RECEIPT: 12})}
        (unit_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    return run


@pytest.fixture
def vfile(tmp_path):
    return tmp_path / VERDICTS


def test_scoring_needs_no_app_or_network(tmp_path, monkeypatch, vfile):
    def refuse(*a, **k):
        raise AssertionError("scoring went to the network")

    monkeypatch.setattr(httpx.Client, "__init__", refuse)
    monkeypatch.setattr(httpx, "get", refuse)
    run = make_run(tmp_path / "runs")
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert (run.path / "report.md").exists()
    right, total = s.headline["documents_right"]
    assert total > 0 and right > 0
    assert run.read_json("run.json")["scored"]
    assert s.signed_off is False and s.set["signed_off"] is False
    assert s.units[0]["slug"] == entry()["slug"] and s.units[0]["app_year"] == START


def test_rescoring_after_the_key_changes_lists_orphans(tmp_path, vfile):
    ref = f"{NAME}:{END}:document:PK-D9999"
    save({"gone": Verdict("gone", ref, "app wrong"),
          "other": Verdict("other", "another-pack:2024-06-30:document:X", "app wrong")}, vfile)
    s = score.score_run(make_run(tmp_path / "runs"), FIX, verdicts_path=vfile)
    assert [o.identity for o in s.orphans] == ["gone"]  # the other pack's verdict isn't this run's business
    assert "Verdicts that no longer match" in (tmp_path / "runs" / s.run_name / "report.md").read_text()


def test_repeats_give_pass_k(tmp_path, vfile):
    s = score.score_run(make_run(tmp_path / "runs", repeats=(1, 2)), FIX, verdicts_path=vfile)
    assert s.pass_k is not None and s.pass_k
    assert {o.data["repeat"] for o in s.outcomes} == {1, 2}
    assert score.score_run(make_run(tmp_path / "runs2"), FIX, verdicts_path=vfile).pass_k is None


def test_results_json_loads_back(tmp_path, vfile):
    run = make_run(tmp_path / "runs", with_after=True)
    unit_dir = run.path / "units" / entry()["slug"]
    s = score.score_run(run, FIX, verdicts_path=vfile)
    outcomes, extra = score.load_results(unit_dir)
    assert {o.phase for o in outcomes} == {"before", "after"}
    assert len(outcomes) == len(s.outcomes) and extra == []
    mine = {(o.check, o.ref, o.phase): o for o in s.outcomes}
    for o in outcomes:
        same = mine[(o.check, o.ref, o.phase)]
        assert (o.status, o.cases, o.identity, o.amount) == (same.status, same.cases, same.identity, same.amount)
        assert isinstance(o.amount, Decimal) and isinstance(o.cases, tuple)
    raw = json.loads((unit_dir / "results.json").read_text())
    assert isinstance(raw["outcomes"][0]["amount"], str) and isinstance(raw["outcomes"][0]["cases"], list)


def test_a_comparison_with_an_earlier_run(tmp_path, vfile):
    root = tmp_path / "runs"
    earlier = make_run(root, label="a", finished="2026-11-19T10:00:00")
    score.score_run(earlier, FIX, verdicts_path=vfile)
    worse = make_run(root, label="b", booked_sales=False)
    s = score.score_run(worse, FIX, verdicts_path=vfile)  # the earlier run is found by selection
    assert s.previous == earlier.name
    assert any(o.check == "document" for o in s.changes["flipped"])
    explicit = make_run(tmp_path / "other", label="c", selection="agency", booked_sales=False)
    s2 = score.score_run(explicit, FIX, verdicts_path=vfile, against=earlier)
    assert s2.previous == earlier.name and s2.changes["flipped"]
    assert "Changes since" in (explicit.path / "report.md").read_text()


def test_the_first_run_has_nothing_to_compare_with(tmp_path, vfile):
    s = score.score_run(make_run(tmp_path / "runs"), FIX, verdicts_path=vfile)
    assert s.previous is None and s.changes is None


def test_rescoring_with_the_set_at_another_path(tmp_path, vfile):
    elsewhere = tmp_path / "a copy of the set"
    shutil.copytree(FIX, elsewhere)
    run = make_run(tmp_path / "runs")
    first = score.score_run(run, FIX, verdicts_path=vfile)
    again = score.score_run(run, elsewhere, verdicts_path=vfile)
    assert again.headline == first.headline
    (elsewhere / "review").mkdir()
    (elsewhere / "review" / "signed-off.txt").write_text("ok")
    assert score.score_run(run, elsewhere, verdicts_path=vfile).signed_off is True


def test_a_unit_without_a_before_snapshot_is_listed_not_scored(tmp_path, vfile):
    run = make_run(tmp_path / "runs", repeats=(1, 2))
    shutil.rmtree(run.path / "units" / entry(2)["slug"] / "raw")
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert {o.data["repeat"] for o in s.outcomes} == {1}
    assert [u["slug"] for u in s.units] == [entry(1)["slug"], entry(2)["slug"]]


def test_cost_from_the_relay_files_or_the_totals(tmp_path, vfile):
    run = make_run(tmp_path / "runs")
    relay = run.path / "relay"
    relay.mkdir()
    calls = [{"seq": 1, "part": "reader", "replayed": False}, {"seq": 2, "part": "chat", "replayed": True},
             {"seq": 3, "part": "reader", "replayed": False}]
    costs = [{"seq": 1, "cost": "0.10"}, {"seq": 2, "cost": "0.25"}, {"seq": 3, "cost": None, "error": "x"}]
    (relay / "calls.jsonl").write_text("\n".join(json.dumps(c) for c in calls) + "\n")
    (relay / "costs.jsonl").write_text("\n".join(json.dumps(c) for c in costs) + "\n")
    info = run.read_json("run.json")
    info.update(started="2026-11-20T10:00:00", finished="2026-11-20T10:01:30")
    run.write_json("run.json", info)
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert (s.cost, s.calls, s.replayed, s.seconds) == (Decimal("0.35"), 3, 1, 90.0)
    assert s.cost_by_part == {"reader": Decimal("0.10"), "chat": Decimal("0.25")}
    t = score.score_run(run, FIX, verdicts_path=vfile,
                        relay_totals={"cost": Decimal("2"), "calls": 9, "replayed": 0, "by_part": {"reader": "2"}})
    assert (t.cost, t.calls, t.cost_by_part) == (Decimal("2"), 9, {"reader": Decimal("2")})


def test_calls_with_no_cost_are_counted_and_the_cost_called_a_lower_bound(tmp_path, vfile):
    run = make_run(tmp_path / "runs")
    relay = run.path / "relay"
    relay.mkdir()
    calls = [{"seq": 1, "part": "reader", "generation_id": "g1"},  # priced
             {"seq": 2, "part": "reader", "generation_id": "g2"},  # its lookup failed
             {"seq": 3, "part": "review", "generation_id": "g3"},  # its lookup never finished
             {"seq": 4, "part": "reader", "generation_id": "g4", "replayed": True},  # replayed: cost nothing
             {"seq": 5, "part": "health", "generation_id": None}]  # nothing to price
    costs = [{"seq": 1, "cost": "0.10"}, {"seq": 2, "cost": None, "error": "404"}]
    (relay / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))
    (relay / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs))
    assert score.unpriced_calls(run) == 2
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert (s.cost, s.unpriced) == (Decimal("0.10"), 2)
    section = (run.path / "report.md").read_text().split("## Cost and time")[1].split("## ")[0]
    assert "- 2 calls had no cost from the provider, so the cost shown is a lower bound" in section
    t = score.score_run(run, FIX, verdicts_path=vfile, relay_totals={"cost": "1", "calls": 2, "unpriced": 1})
    assert t.unpriced == 1


def test_verdicts_are_applied_and_lapse_by_identity(tmp_path, vfile):
    run = make_run(tmp_path / "runs", booked_sales=False)
    first = score.score_run(run, FIX, verdicts_path=vfile)
    fault = next(o for o in first.outcomes if o.status == "fail" and o.check == "document")
    save({fault.identity: Verdict(fault.identity, fault.ref, "key wrong", "the key", "AB", "2026-11-20")}, vfile)
    again = score.score_run(run, FIX, verdicts_path=vfile)
    judged = next(o for o in again.outcomes if o.identity == fault.identity)
    assert judged.status == "excluded" and judged.data["verdict"]["verdict"] == "key wrong"


def test_each_check_reads_its_own_snapshot(tmp_path, vfile):
    run = make_run(tmp_path / "runs", with_after=True, booked_sales=False, after_booked=True)
    s = score.score_run(run, FIX, verdicts_path=vfile)

    def phases(check):
        return {o.phase for o in s.outcomes if o.check == check}

    for check in ("document", "entry"):
        assert phases(check) == {"before", "after"}, check
    for check in ("line", "opening"):
        assert phases(check) <= {"before"}, check
    for check in ("vat", "unpaid", "query"):
        assert phases(check) <= {"after"}, check
    assert phases("vat") == {"after"} and phases("query") == {"after"}
    sales = [o for o in s.outcomes if o.check == "document" and o.ref.endswith("PK-D0001")]
    assert {(o.phase, o.status) for o in sales} == {("before", "fail"), ("after", "pass")}


def test_a_key_question_the_reply_resolved_counts_as_asked(tmp_path, vfile):
    # PK-Q0002: the app asks for the receipt's full VAT invoice; the reply attaches it, which resolves the question,
    # and the app lists only open and waiting questions, so the after snapshot no longer has it
    run = make_run(tmp_path / "runs", with_after=True)
    unit_dir = run.path / "units" / entry()["slug"]
    asked = {"id": "q1", "status": "open", "row_ids": [2], "text": "Can you send the full VAT invoice?",
             "source": "rules", "kind": "vat_invoice"}
    (unit_dir / "raw" / "before" / "questions.json").write_text(json.dumps([asked]), encoding="utf-8")
    progress = json.loads((unit_dir / "progress.json").read_text())
    for replies in ({"PK-Q0002": {"sent": True, "question_id": "q1", "events": [], "asked_back": []}}, {}):
        progress["replies"] = replies
        (unit_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        s = score.score_run(run, FIX, verdicts_path=vfile)
        (q,) = [o for o in s.outcomes if o.check == "query"]
        assert (q.status, q.phase, q.ref) == ("pass", "after", f"{NAME}:{END}:query:PK-Q0002"), replies
        assert s.headline["queries_asked"] == [1, 1] and s.extra_questions == []


def test_an_unfinished_after_snapshot_is_ignored(tmp_path, vfile):
    run = make_run(tmp_path / "runs", with_after=True, after_done=False)
    s = score.score_run(run, FIX, verdicts_path=vfile)
    # not_attempted entries are labelled "after" by their journal, whatever was read
    assert {o.phase for o in s.outcomes if o.status != "not_attempted"} == {"before"}


def test_one_unit_that_cannot_be_scored_does_not_stop_the_run(tmp_path, vfile):
    run = make_run(tmp_path / "runs", repeats=(1, 2))
    info = run.read_json("run.json")
    info["units"][0]["name"] = "a-pack-that-was-removed"
    info["units"][0]["slug"] = "gone-slug"
    run.write_json("run.json", info)
    shutil.move(run.path / "units" / entry(1)["slug"], run.path / "units" / "gone-slug")
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert s.units[0]["status"].startswith("not scored: ") and s.units[0]["run_status"] == "done"
    assert s.units[1]["status"] == "done"
    assert {o.data["repeat"] for o in s.outcomes} == {2}
    assert (run.path / "report.md").exists()


def test_an_earlier_run_that_was_never_scored_gives_no_comparison(tmp_path, vfile):
    root = tmp_path / "runs"
    earlier = make_run(root, label="a", finished="2026-11-19T10:00:00")  # no score_run, so no results.json
    s = score.score_run(make_run(root, label="b"), FIX, verdicts_path=vfile)
    assert s.previous is None and s.changes is None
    s2 = score.score_run(make_run(tmp_path / "o", label="c"), FIX, verdicts_path=vfile, against=earlier)
    assert s2.previous is None and s2.changes is None


def test_the_report_names_a_unit_that_was_not_scored(tmp_path, vfile):
    run = make_run(tmp_path / "runs", repeats=(1, 2))
    info = run.read_json("run.json")
    info["units"][0]["name"] = "a-pack-that-was-removed"
    run.write_json("run.json", info)
    score.score_run(run, FIX, verdicts_path=vfile)
    body = (run.path / "report.md").read_text()
    line = next(ln for ln in body.splitlines() if ln.startswith(f"- Unit {entry(1)['slug']}: "))
    assert "not scored: " in line and "a-pack-that-was-removed" in line
    assert f"- Unit {entry(2)['slug']}: done" in body


def test_an_unreadable_progress_file_does_not_stop_the_run(tmp_path, vfile):
    run = make_run(tmp_path / "runs", repeats=(1, 2))
    (run.path / "units" / entry(1)["slug"] / "progress.json").write_text("{not json", encoding="utf-8")
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert s.units[0]["slug"] == entry(1)["slug"] and s.units[0]["status"].startswith("not scored: ")
    assert s.units[1]["status"] == "done" and {o.data["repeat"] for o in s.outcomes} == {2}


def test_a_malformed_unit_entry_does_not_stop_the_run(tmp_path, vfile):
    run = make_run(tmp_path / "runs")
    info = run.read_json("run.json")
    info["units"].insert(0, {"slug": "broken-r1", "status": "done"})  # no name, kind or period
    run.write_json("run.json", info)
    s = score.score_run(run, FIX, verdicts_path=vfile)
    assert s.units[0]["slug"] == "broken-r1" and s.units[0]["status"].startswith("not scored: ")
    assert s.units[1]["status"] == "done" and s.outcomes
