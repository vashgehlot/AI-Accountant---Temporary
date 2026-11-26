import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from testbooks_runner import runs
from testbooks_runner.model import Period, Unit


def _unit(tmp_path):
    return Unit("acme", "client", tmp_path, Period(date(2023, 4, 1), date(2024, 3, 31)), 2)


def _finished_run(root, label, selection, finished, today=date(2026, 11, 19)):
    r = runs.new_run(label, root, today=today)
    data = {"selection": selection}
    if finished:
        data["finished"] = finished
    r.write_json("run.json", data)
    return r


def test_runs_constant_is_beside_module():
    assert runs.RUNS == Path(runs.__file__).parent / "runs"


def test_new_run_names_and_collisions(tmp_path):
    a = runs.new_run("packs", tmp_path, today=date(2026, 11, 19))
    b = runs.new_run("packs", tmp_path, today=date(2026, 11, 19))
    c = runs.new_run("packs", tmp_path, today=date(2026, 11, 19))
    assert (a.name, b.name, c.name) == ("2026-11-19-packs", "2026-11-19-packs-2", "2026-11-19-packs-3")
    assert a.path.is_dir() and b.path.is_dir()


def test_unit_dir_created_on_demand(tmp_path):
    r = runs.new_run("x", tmp_path, today=date(2026, 11, 19))
    u = _unit(tmp_path)
    d = r.unit_dir(u)
    assert d == r.path / "units" / "acme-2024-03-31-r2"
    assert d.is_dir()


def test_write_and_read_json(tmp_path):
    r = runs.RunDir(tmp_path / "r")
    r.write_json("a/b/c.json", {"x": [1, 2]})
    assert r.read_json("a/b/c.json") == {"x": [1, 2]}
    assert r.read_json("missing.json") is None
    assert r.read_json("missing.json", default={}) == {}


def test_write_json_is_atomic(tmp_path):
    r = runs.RunDir(tmp_path / "r")
    r.write_json("a.json", {"k": 1})
    r.write_json("a.json", {"k": 2})
    assert r.read_json("a.json") == {"k": 2}
    assert list(r.path.rglob("*.tmp")) == []


def test_write_json_failure_keeps_old_file_and_leaves_no_tmp(tmp_path):
    r = runs.RunDir(tmp_path / "r")
    r.write_json("a.json", {"k": 1})
    with pytest.raises(TypeError):
        r.write_json("a.json", {"k": object()})
    assert r.read_json("a.json") == {"k": 1}
    assert list(r.path.rglob("*.tmp")) == []


def test_write_json_is_utf8_and_handles_decimal_and_date(tmp_path):
    r = runs.RunDir(tmp_path / "r")
    r.write_json("a.json", {"name": "café £", "amt": Decimal("1.10"), "d": date(2026, 1, 2)})
    assert "café £" in (r.path / "a.json").read_text(encoding="utf-8")
    assert r.read_json("a.json") == {"name": "café £", "amt": "1.10", "d": "2026-01-02"}


def test_previous_run_same_selection_finished_only(tmp_path):
    a = _finished_run(tmp_path, "a", "packs", "2026-11-19T10:00:00")
    _finished_run(tmp_path, "b", "packs", None)
    _finished_run(tmp_path, "c", "agency", "2026-11-19T12:00:00")
    d = _finished_run(tmp_path, "d", "packs", None)
    assert runs.previous_run(d, "packs", tmp_path).name == a.name


def test_previous_run_picks_latest_by_finished_not_name(tmp_path):
    first = _finished_run(tmp_path, "p", "packs", "2026-11-19T09:00:00")
    for _ in range(9):
        runs.new_run("p", tmp_path, today=date(2026, 11, 19))  # -2 .. -10
    tenth = runs.open_run("2026-11-19-p-10", tmp_path)
    tenth.write_json("run.json", {"selection": "packs", "finished": "2026-11-19T08:00:00"})
    second = runs.open_run("2026-11-19-p-2", tmp_path)
    second.write_json("run.json", {"selection": "packs", "finished": "2026-11-19T11:00:00"})
    cur = _finished_run(tmp_path, "z", "packs", None)
    assert first.name == "2026-11-19-p"
    assert runs.previous_run(cur, "packs", tmp_path).name == "2026-11-19-p-2"


def test_previous_run_excludes_current_and_returns_none(tmp_path):
    cur = _finished_run(tmp_path, "a", "packs", "2026-11-19T10:00:00")
    assert runs.previous_run(cur, "packs", tmp_path) is None


def test_previous_run_ignores_folders_without_run_json(tmp_path):
    (tmp_path / "stray").mkdir()
    cur = runs.new_run("a", tmp_path, today=date(2026, 11, 19))
    assert runs.previous_run(cur, "packs", tmp_path) is None


def test_previous_run_with_missing_root(tmp_path):
    cur = runs.RunDir(tmp_path / "cur")
    assert runs.previous_run(cur, "packs", tmp_path / "nope") is None


def test_open_run_by_name_and_path(tmp_path, monkeypatch):
    a = runs.new_run("a", tmp_path, today=date(2026, 11, 19))
    assert runs.open_run(a.name, tmp_path).path == a.path
    assert runs.open_run(str(a.path), tmp_path / "elsewhere").path == a.path
    monkeypatch.chdir(tmp_path)
    assert runs.open_run(f"./{a.name}", tmp_path / "elsewhere").path.resolve() == a.path.resolve()


def test_open_run_missing_raises_with_name(tmp_path):
    with pytest.raises(FileNotFoundError, match="no-such-run"):
        runs.open_run("no-such-run", tmp_path)


def test_progress_defaults_are_independent():
    p, q = runs.Progress(), runs.Progress()
    p.bank_codes["x"] = "1"
    p.batches_done.append("b")
    p.uploads["f"] = {}
    p.replies["r"] = {}
    assert q == runs.Progress()
    assert (p.client_id, p.thread_id, p.chat_refusal, p.before_done, p.after_done) == (None, None, None, False, False)


def test_progress_round_trip(tmp_path):
    p = runs.Progress(
        client_id=3,
        app_year_start="2023-04-01",
        bank_codes={"hsbc": "1200"},
        batches_done=["2023-04-12"],
        uploads={"inbox/2023-04-12/a.pdf": {"status": "saved"}},
        before_done=True,
        replies={"q1": {"text": "ok"}},
        thread_id="t1",
        chat_year="2023-24",
        after_done=True,
        chat_refusal={"status": 409, "detail": "closed"},
        opening_done=True,
        review_waits={"2023-04-12": "timeout"},
    )
    runs.save_progress(tmp_path, p)
    assert runs.load_progress(tmp_path) == p
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_progress_without_file_is_fresh(tmp_path):
    assert runs.load_progress(tmp_path) == runs.Progress()


def test_load_progress_ignores_unknown_keys(tmp_path):
    (tmp_path / "progress.json").write_text(json.dumps({"client_id": 7, "future_field": [1]}))
    assert runs.load_progress(tmp_path) == runs.Progress(client_id=7)
