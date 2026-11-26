import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from testbooks_runner import books, estimate, selection
from testbooks_runner.estimate import Workload
from testbooks_runner.model import Period, Unit

FIX = Path(__file__).parent / "fixtures" / "set"
PRICE = {"in": Decimal("1e-7"), "out": Decimal("4e-7")}


def _unit(name="u1"):
    return Unit(name, "pack", Path("/nowhere") / name, Period(date(2024, 6, 1), date(2024, 6, 30)))


def _wl(files, name="u1", replies=0):
    return Workload(_unit(name), dict(files), [dict(files)], replies)


def _one_file_units(n, kind="pdf"):
    return [_wl({kind: 1}, f"u{i}") for i in range(n)]


MEASURED = {"model": "m", "kinds": {"pdf": {"cost": "0.02", "seconds": 600, "n": 3}},
            "review": {"cost": "0.5", "seconds": 100, "n": 1}, "chat": {"cost": "0.4", "seconds": 50, "n": 1}}


def test_file_kinds():
    expect = {"a.pdf": "pdf", "A.PDF": "pdf", "a.jpg": "image", "a.jpeg": "image", "a.png": "image",
              "a.heic": "image", "a.heif": "image", "a.webp": "image", "a.gif": "image", "a.tif": "image",
              "a.tiff": "image", "a.csv": "sheet", "a.tsv": "sheet", "a.xlsx": "sheet", "a.xls": "sheet",
              "a.ofx": "sheet", "a.qif": "sheet", "a.txt": "text", "a.eml": "text", "a.docx": "text",
              "a.zip": "other", "noext": "other"}
    for name, kind in expect.items():
        assert estimate.file_kind(Path(name)) == kind, name


def test_rough_estimate_from_the_listed_price():
    est = estimate.estimate([_wl({"pdf": 2})], measurements=None, price=PRICE, pool=1, review="off")
    assert est.cost == 2 * (7000 * Decimal("1e-7") + 3000 * Decimal("4e-7"))
    assert est.rough is True


def test_no_price_means_cost_unknown():
    wls = [_wl({"pdf": 2})]
    est = estimate.estimate(wls, measurements=None, price=None, pool=1, review="off")
    assert est.cost is None and est.rough is True
    assert "cost unknown" in estimate.format_plan(wls, est, 1)


def test_measured_estimate_and_pool_time():
    wls = _one_file_units(4)
    four = estimate.estimate(wls, measurements=MEASURED, price=None, pool=4, review="off")
    one = estimate.estimate(wls, measurements=MEASURED, price=None, pool=1, review="off")
    assert four.seconds == 600 and one.seconds == 2400
    assert four.cost == Decimal("0.08") and four.rough is False


def test_review_off_drops_review_cost_and_time():
    wls = [_wl({"pdf": 1}, replies=1)]
    on = estimate.estimate(wls, measurements=MEASURED, price=None, pool=1, review="auto")
    off = estimate.estimate(wls, measurements=MEASURED, price=None, pool=1, review="off")
    assert on.cost == Decimal("0.02") + Decimal("0.5") + Decimal("0.4")
    assert on.seconds == 600 + 100 + 50
    assert off.cost == Decimal("0.02") + Decimal("0.4") and off.seconds == 600 + 50


def test_review_and_chat_priced_at_their_own_model():
    wls = [_wl({"pdf": 1}, replies=1)]
    agent = {"in": Decimal("1e-6"), "out": Decimal("2e-6")}
    pdf = 7000 * Decimal("1e-7") + 3000 * Decimal("4e-7")
    turn = 40000 * Decimal("1e-6") + 5000 * Decimal("2e-6")
    est = estimate.estimate(wls, measurements=None, price=PRICE, agent_price=agent, pool=1, review="automatic")
    assert est.cost == pdf + 2 * turn  # one review and one chat turn at the agent's price
    same = estimate.estimate(wls, measurements=None, price=PRICE, pool=1, review="automatic")
    assert same.cost == pdf + 2 * (40000 * Decimal("1e-7") + 5000 * Decimal("4e-7"))
    assert estimate.estimate(wls, measurements=None, price=PRICE, agent_price=None, pool=1,
                             review="automatic").cost is None  # the chat model's price isn't known
    measured = {"review": {"cost": "0.5", "seconds": 1, "n": 1}, "chat": {"cost": "0.4", "seconds": 1, "n": 1}}
    assert estimate.estimate(wls, measurements=measured, price=PRICE, agent_price=None, pool=1,
                             review="automatic").cost == pdf + Decimal("0.9")


def test_time_uses_parallel_reads_per_batch_by_the_slowest_kind():
    m = {"kinds": {"pdf": {"cost": "0", "seconds": 10, "n": 1}, "sheet": {"cost": "0", "seconds": 30, "n": 1}}}
    wl = Workload(_unit(), {"pdf": 11, "sheet": 1}, [{"pdf": 11, "sheet": 1}, {"pdf": 1}], 0)
    est = estimate.estimate([wl], measurements=m, price=None, pool=1, review="off", parallel=5)
    assert est.seconds == 3 * 30 + 1 * 10


def test_longest_units_go_first_onto_the_least_loaded_copy():
    wls = [_wl({"pdf": 1}, "a"), _wl({"pdf": 1}, "b"), _wl({"pdf": 1}, "c")]
    m = {"kinds": {"pdf": {"cost": "0", "seconds": 100, "n": 1}}}
    assert estimate.estimate(wls, measurements=m, price=None, pool=2, review="off").seconds == 200


def test_partial_measurements_stay_rough_and_use_the_price_for_the_rest():
    est = estimate.estimate([_wl({"pdf": 1, "sheet": 1})], measurements=MEASURED, price=PRICE, pool=1, review="off")
    sheet = 9000 * Decimal("1e-7") + 8000 * Decimal("4e-7")
    assert est.rough is True and est.cost == Decimal("0.02") + sheet
    # with no price the unmeasured sheet leaves the cost unknown
    assert estimate.estimate([_wl({"pdf": 1, "sheet": 1})], measurements=MEASURED, price=None, pool=1,
                             review="off").cost is None


def test_workload_of_the_fixture_pack_counts_the_attachment_but_not_as_a_batch():
    [u] = selection.select_units(FIX, packs=["EC-0346"])
    key = books.load_key(u.key_dir)
    wl = estimate.workload(u, key, True)
    assert wl.files == {"pdf": 5, "sheet": 1}  # four inbox pdfs and the statement, plus the answer pdf
    assert len(wl.batches) == 5 and sum(sum(b.values()) for b in wl.batches) == 5
    assert wl.replies == 1
    text = estimate.format_plan([wl], estimate.estimate([wl], measurements=None, price=PRICE, pool=2, review="auto"), 2)
    assert "Reads: 6; reviews: about 5; chat turns: up to 1" in text
    assert "Files: 6 (pdf 5, sheet 1)" in text
    assert "(rough: no runs measured yet)" in text and "with 2 copies" in text


def _call(seq, unit, part, started, replayed=False, seconds=1.0):
    return {"seq": seq, "unit": unit, "part": part, "started": started, "seconds": seconds, "replayed": replayed}


def _cost(seq, cost):
    return {"seq": seq, "cost": cost, "tokens_in": 1, "tokens_out": 1}


def _run(tmp_path, calls, costs, progress, reviews=None, app=None):
    run = tmp_path / "run"
    (run / "relay").mkdir(parents=True)
    (run / "relay" / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    (run / "relay" / "costs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in costs), encoding="utf-8")
    ud = run / "units" / "u1-2024-06-30-r1"
    ud.mkdir(parents=True)
    (ud / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
    for which, rows in (reviews or {}).items():
        (ud / "raw" / which).mkdir(parents=True)
        (ud / "raw" / which / "reviews.json").write_text(json.dumps(rows), encoding="utf-8")
    if app:
        (run / "run.json").write_text(json.dumps({"app": app}), encoding="utf-8")
    return run


SLUG = "u1-2024-06-30-r1"


def test_measurements_share_a_call_among_overlapping_reads(tmp_path):
    progress = {"uploads": {"a/x.pdf": {"submitted": 100, "finished": 160, "status": "done"},
                            "a/y.xlsx": {"submitted": 110, "finished": 200, "status": "done"}}}
    run = _run(tmp_path, [_call(1, SLUG, "reader", 120)], [_cost(1, "0.10")], progress, app={"model": "m/x"})
    path = tmp_path / "measurements.json"
    path.write_text(json.dumps({"model": "m/x", "kinds": {"pdf": {"cost": "0.01", "seconds": 20, "n": 1}}}))
    got = estimate.update_measurements(run, path)
    assert got["model"] == "m/x"
    assert got["kinds"]["sheet"] == {"cost": "0.05", "seconds": 90.0, "n": 1}
    # pdf: new 0.05 / 60 s over n=1, merged with 0.01 / 20 s over n=1
    assert Decimal(got["kinds"]["pdf"]["cost"]) == Decimal("0.03") and got["kinds"]["pdf"]["seconds"] == 40
    assert got["kinds"]["pdf"]["n"] == 2
    assert json.loads(path.read_text()) == got
    assert not list(tmp_path.glob("*.tmp"))


def test_replayed_and_unpriced_calls_are_left_out(tmp_path):
    progress = {"uploads": {"a/x.pdf": {"submitted": 100, "finished": 160, "status": "done"},
                            "a/z.pdf": {"submitted": 300, "finished": 310, "status": "done"}}}
    calls = [_call(1, SLUG, "reader", 120, replayed=True), _call(2, SLUG, "reader", 305), _call(3, SLUG, "reader", 306)]
    run = _run(tmp_path, calls, [_cost(1, "0"), _cost(2, "0.04"), _cost(3, None)], progress)
    got = estimate.update_measurements(run, tmp_path / "m.json")
    assert got["kinds"]["pdf"] == {"cost": "0.04", "seconds": 10.0, "n": 1}


def test_review_and_chat_figures(tmp_path):
    progress = {"uploads": {}, "replies": {"q1": {"sent": True}, "q2": {"sent": True}, "q3": {"sent": False}}}
    calls = [_call(1, SLUG, "review", 5, seconds=100), _call(2, SLUG, "review", 6, seconds=140),
             _call(3, SLUG, "chat", 7, seconds=30), _call(4, SLUG, "chat", 8, seconds=50),
             _call(5, SLUG, "chat", 9, replayed=True), _call(6, SLUG, "health", 9)]
    costs = [_cost(1, "0.30"), _cost(2, "0.50"), _cost(3, "0.10"), _cost(4, "0.20"), _cost(5, "0"), _cost(6, "9")]
    # one review seen in both snapshots counts once; a running one does not count
    reviews = {"before": [{"id": 1, "status": "done"}, {"id": 2, "status": "running"}],
               "after": [{"id": 1, "status": "done"}, {"id": 3, "status": "failed"}]}
    run = _run(tmp_path, calls, costs, progress, reviews)
    got = estimate.update_measurements(run, tmp_path / "m.json")
    assert got["review"] == {"cost": "0.4", "seconds": 120.0, "n": 2}
    assert got["chat"] == {"cost": "0.15", "seconds": 40.0, "n": 2}


def test_merge_is_weighted_by_n(tmp_path):
    progress = {"uploads": {"a/x.pdf": {"submitted": 0, "finished": 10, "status": "done"}}}
    run = _run(tmp_path, [_call(1, SLUG, "reader", 5)], [_cost(1, "0.10")], progress)
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"model": "m", "kinds": {"pdf": {"cost": "0.02", "seconds": 40, "n": 3}}}))
    got = estimate.update_measurements(run, path)
    assert got["kinds"]["pdf"]["n"] == 4
    assert Decimal(got["kinds"]["pdf"]["cost"]) == Decimal("0.04")  # (0.02*3 + 0.10) / 4
    assert got["kinds"]["pdf"]["seconds"] == 32.5


def test_model_price_parses_the_listing():
    seen = []

    def get(url, **kw):
        seen.append((url, kw))

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": [{"id": "other/x", "pricing": {"prompt": "1", "completion": "1"}},
                                 {"id": "qwen/qwen3.8-27b", "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}}]}
        return R()

    assert estimate.model_price("qwen/qwen3.8-27b", get=get) == {"in": Decimal("0.0000001"), "out": Decimal("0.0000004")}
    assert seen[0][0] == "https://openrouter.ai/api/v1/models"
    assert estimate.model_price("nope/none", get=get) is None


def test_model_price_failure_is_none():
    def boom(url, **kw):
        raise OSError("down")
    assert estimate.model_price("m", get=boom) is None


def test_a_different_model_starts_the_figures_afresh(tmp_path):
    progress = {"uploads": {"a/x.pdf": {"submitted": 0, "finished": 10, "status": "done"}}}
    run = _run(tmp_path, [_call(1, SLUG, "reader", 5)], [_cost(1, "0.10")], progress, app={"model": "new/m"})
    path = tmp_path / "m.json"
    old = {"model": "old/m", "kinds": {"pdf": {"cost": "0.02", "seconds": 40, "n": 3}, "sheet": {"cost": "1", "seconds": 1, "n": 1}},
           "review": {"cost": "1", "seconds": 1, "n": 1}}
    path.write_text(json.dumps(old))
    got = estimate.update_measurements(run, path)
    assert got == {"model": "new/m", "kinds": {"pdf": {"cost": "0.1", "seconds": 10.0, "n": 1}}}
    assert json.loads(path.read_text()) == got


def test_load_measurements_checks_the_model(tmp_path):
    path = tmp_path / "m.json"
    assert estimate.load_measurements("m", path) is None
    path.write_text("not json")
    assert estimate.load_measurements("m", path) is None
    data = {"model": "m", "kinds": {}}
    path.write_text(json.dumps(data))
    assert estimate.load_measurements("m", path) == data
    assert estimate.load_measurements("other", path) is None
    assert estimate.load_measurements(None, path) == data
    path.write_text(json.dumps({"kinds": {}}))
    assert estimate.load_measurements("other", path) == {"kinds": {}}


def test_plan_wording_tells_none_measured_from_some_unmeasured():
    wls = [_wl({"pdf": 1, "sheet": 1})]
    none = estimate.estimate(wls, measurements=None, price=PRICE, pool=1, review="off")
    some = estimate.estimate(wls, measurements=MEASURED, price=PRICE, pool=1, review="off")
    assert "(rough: no runs measured yet)" in estimate.format_plan(wls, none, 1)
    text = estimate.format_plan(wls, some, 1)
    assert "(rough: some figures not measured yet)" in text and "no runs measured" not in text
    full = estimate.estimate([_wl({"pdf": 1})], measurements=MEASURED, price=PRICE, pool=1, review="off")
    assert "rough" not in estimate.format_plan([_wl({"pdf": 1})], full, 1)
