import json
import signal
import shutil
import threading
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from testbooks_runner import orchestrate
from testbooks_runner.api import AppError
from testbooks_runner.appserver import StartError
from testbooks_runner.model import Period, Unit
from testbooks_runner.relay import Relay
from testbooks_runner.runs import RunDir, load_progress, open_run
from testbooks_runner.selection import select_units
from testbooks_runner.tests.fake_api import FakeApi
from testbooks_runner.tests.helpers import write_mini_client

FIX = Path(__file__).parent / "fixtures" / "set"
KEY = "sk-or-v1-notarealkey"
SCORE_READS = {"selection", "options", "review", "with_next_year", "app", "runner", "set", "estimate",
               "started", "finished", "units"}
UNIT_KEYS = {"slug", "db", "status", "name", "kind", "period_start", "period_end", "repeat"}


class Fakes:
    """Stands in for the app copies: one FakeApi per start_copy, and a record of what was asked of them."""

    def __init__(self):
        self.apis: dict[str, FakeApi] = {}
        self.starts: list[dict] = []
        self.stopped: list[str] = []
        self.databases: list[tuple] = []
        self.preflights = 0
        self.start_errors: dict[str, str] = {}  # unit name -> message
        self.api_errors: dict[str, dict] = {}   # unit name -> FakeApi.raise_on
        self.relays: list = []
        self.spent = Decimal(0)
        self.per_file = Decimal(0)
        self.unpriced = 0  # what the relay's totals say had no cost
        self.lock = threading.Lock()


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)

    def start_copy(app_dir, *, python, env, port, db, log, timeout=90.0):
        unit = env["OPENROUTER_BASE_URL"].rsplit("/c/", 1)[1].split("-2")[0]
        with f.lock:
            f.starts.append({"db": db, "env": env, "unit": unit, "python": python, "log": log})
        if unit in f.start_errors:
            raise StartError(f.start_errors[unit])
        if unit in f.apis:  # a resumed copy is the same app on the same database
            return SimpleNamespace(port=port, db=db, api=f.apis[unit], process=None, log=log, log_file=None)
        api = FakeApi()
        api.returns["health"] = {"ok": True, "model": "test/model", "ai_reachable": True, "model_available": True}
        api.raise_on.update(f.api_errors.get(unit, {}))
        analyze = api.analyze

        def priced(*a, **k):
            with f.lock:
                f.spent += f.per_file
            return analyze(*a, **k)

        api.analyze = priced
        f.apis[unit] = api
        return SimpleNamespace(port=port, db=db, api=api, process=None, log=log, log_file=None)

    class PricedRelay(Relay):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            f.relays.append(self)

        def totals(self):
            return {**super().totals(), "cost": f.spent, "unpriced": f.unpriced}

    monkeypatch.setattr(orchestrate, "start_copy", start_copy)
    monkeypatch.setattr(orchestrate, "stop_copy", lambda copy: f.stopped.append(copy.db))
    monkeypatch.setattr(orchestrate, "check_database", lambda uri, db, live, *, resume, **k:
                        f.databases.append((uri, db, live, resume)))
    monkeypatch.setattr(orchestrate, "preflight", lambda app_dir, environ: setattr(f, "preflights", f.preflights + 1))
    monkeypatch.setattr(orchestrate, "Relay", PricedRelay)
    return f


@pytest.fixture
def setdir(tmp_path):
    root = tmp_path / "set"
    shutil.copytree(FIX, root)
    mini = write_mini_client(root)
    shutil.copytree(mini, root / "clients" / "mini2")
    return root


def two_units(setdir):
    return [select_units(setdir, client="mini")[0], select_units(setdir, client="mini2")[0]]


def options(setdir, tmp_path, **kw):
    kw.setdefault("review", "off")
    kw.setdefault("pool", 2)
    return orchestrate.RunOptions(set_dir=setdir, app_dir=tmp_path / "app", **kw)


def run_it(units, opts, tmp_path, **kw):
    return orchestrate.run_selection(units, opts, runs_root=tmp_path / "runs",
                                     verdicts_path=tmp_path / "verdicts.csv",
                                     measurements_path=tmp_path / "measurements.json", **kw)


def resume_it(run, opts, tmp_path):
    return orchestrate.resume_run(run, opts, verdicts_path=tmp_path / "verdicts.csv",
                                  measurements_path=tmp_path / "measurements.json")


def statuses(run):
    return {u["name"]: u["status"] for u in run.read_json("run.json")["units"]}


def test_spend_guard():
    asked = []
    guard = orchestrate.SpendGuard(None, yes=False, ask=asked.append)
    assert guard.check(Decimal("1000")) is True and asked == []

    guard = orchestrate.SpendGuard(Decimal("10"), yes=True, ask=asked.append)
    assert guard.check(Decimal("15")) is True  # exactly 1.5 times is allowed
    assert guard.check(Decimal("15.01")) is False and asked == []

    prompts = []
    answers = iter(["y", ""])
    guard = orchestrate.SpendGuard(Decimal("10"), yes=False, ask=lambda p: prompts.append(p) or next(answers))
    assert guard.check(Decimal("15")) is True and prompts == []
    assert guard.check(Decimal("16")) is True
    assert prompts == ["Spent $16 against an estimate of $10. Carry on? [y/N] "]
    assert guard.check(Decimal("29")) is True and len(prompts) == 1  # the threshold is now 20
    assert guard.check(Decimal("31")) is False and len(prompts) == 2  # answered ""
    assert guard.check(Decimal("31")) is False and len(prompts) == 2  # a refusal stands


def test_the_guard_says_when_calls_have_no_cost(setdir, tmp_path, fakes, monkeypatch):
    prompts = []
    guard = orchestrate.SpendGuard(Decimal("10"), yes=False, ask=lambda p: prompts.append(p) or "n")
    assert guard.check(Decimal("16"), unpriced=3) is False
    assert prompts == ["Spent $16 against an estimate of $10 (3 calls had no cost from the provider, so the spend is "
                       "a lower bound). Carry on? [y/N] "]
    # and in a run, the relay's count of calls with no cost reaches the question
    fakes.per_file, fakes.unpriced = Decimal("2"), 1
    prompts.clear()
    monkeypatch.setattr("builtins.input", lambda p: prompts.append(p) or "n")
    run = run_it([two_units(setdir)[0]], options(setdir, tmp_path, pool=1), tmp_path, estimate=Decimal("1"))
    assert statuses(run) == {"mini": "stopped"}
    assert prompts == ["Spent $2 against an estimate of $1 (1 call had no cost from the provider, so the spend is a "
                       "lower bound). Carry on? [y/N] "]
    assert "spent $2 and 1 calls not priced" in (run.path / "run.log").read_text()


def test_spend_guard_asks_one_thread_at_a_time():
    asked = []

    def slow_ask(prompt):
        asked.append(prompt)
        time.sleep(0.05)
        return "y"

    guard = orchestrate.SpendGuard(Decimal("10"), yes=False, ask=slow_ask)
    results = []
    threads = [threading.Thread(target=lambda: results.append(guard.check(Decimal("16")))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 8 and len(asked) == 1


def test_replay_with_repeat_is_refused(setdir, tmp_path, fakes):
    folder = tmp_path / "earlier"
    (folder / "relay").mkdir(parents=True)
    (folder / "relay" / "calls.jsonl").write_text("")
    units = select_units(setdir, client="mini", repeat=2)
    with pytest.raises(StartError, match="repeat"):
        run_it(units, options(setdir, tmp_path, replay=folder), tmp_path)
    assert fakes.preflights == 0 and not (tmp_path / "runs").exists()


def test_replay_folder_without_recordings_is_refused(setdir, tmp_path, fakes):
    folder = tmp_path / "earlier"
    folder.mkdir()
    with pytest.raises(StartError, match="calls.jsonl"):
        run_it(two_units(setdir), options(setdir, tmp_path, replay=folder), tmp_path)
    assert fakes.preflights == 0 and fakes.starts == [] and not (tmp_path / "runs").exists()


def test_run_selection_with_fakes(setdir, tmp_path, fakes):
    units = two_units(setdir)
    run = run_it(units, options(setdir, tmp_path, selection="--client mini mini2", label="pair"), tmp_path,
                 estimate=Decimal("2.50"))
    info = run.read_json("run.json")
    assert {u["status"] for u in info["units"]} == {"done"} and (run.path / "report.md").exists()
    assert run.name.endswith("-pair")
    # everything score.py reads
    assert SCORE_READS <= set(info) and all(UNIT_KEYS <= set(u) for u in info["units"])
    assert info["selection"] == "--client mini mini2" and info["estimate"] == "2.50"
    assert info["review"] == "off" and info["with_next_year"] is False and info["runner"]
    assert info["options"]["set_dir"] == str(setdir) and info["options"]["pool"] == 2
    assert info["app"]["model"] == "test/model" and info["app"]["ai_reachable"] is True
    assert info["app"]["model_available"] is True and "commit" in info["app"] and "dirty" in info["app"]
    assert info["set"]["path"] == str(setdir)
    assert set(info["set"]["key_hashes"]) == {u.slug for u in units}
    assert info["started"] <= info["finished"]
    assert [u["db"] for u in info["units"]] == [f"{info['units'][0]['db'][:-2]}_{i}" for i in (1, 2)]
    assert sorted(db for _, db, _, _ in fakes.databases) == sorted(u["db"] for u in info["units"])
    assert all(resume is False for *_, resume in fakes.databases)
    assert sorted(fakes.stopped) == sorted(u["db"] for u in info["units"])
    for start in fakes.starts:
        assert start["env"]["OPENROUTER_BASE_URL"].startswith("http://127.0.0.1:")
        assert start["log"] == run.path / "units" / next(u.slug for u in units if u.name == start["unit"]) / "app.log"
    for u in units:
        unit_dir = run.path / "units" / u.slug
        assert load_progress(unit_dir).after_done and (unit_dir / "raw" / "before").is_dir()
    assert (tmp_path / "measurements.json").exists()


def test_a_stand_in_model_on_this_machine_is_never_measured(setdir, tmp_path, fakes):
    for upstream in ("http://127.0.0.1:9/api/v1", "http://localhost:9/api/v1", "http://[::1]:9/api/v1"):
        run = run_it(two_units(setdir)[:1], options(setdir, tmp_path, upstream=upstream), tmp_path)
        assert statuses(run) == {"mini": "done"} and (run.path / "report.md").exists()
        assert not (tmp_path / "measurements.json").exists(), upstream
        assert "no measurements kept" in (run.path / "run.log").read_text()
    assert [orchestrate.on_this_machine(u) for u in ("https://openrouter.ai/api/v1", "http://10.0.0.5/v1",
                                                     "http://127.8.0.1/v1", "http://app.localhost:80/v1")] == \
        [False, False, True, True]


def test_database_names_fit_atlas_with_the_checkpoints_suffix(setdir, tmp_path, fakes):
    units = two_units(setdir)
    names = []
    for label in ("a-rather-long-label-for-a-run", "another-long-label"):
        opts = options(setdir, tmp_path, label=label, yes=True)
        run = run_it(units, opts, tmp_path)
        names.append([u["db"] for u in run.read_json("run.json")["units"]])
    flat = [n for group in names for n in group]
    assert all(n.startswith("tbrun_") and len(n + "_checkpoints") <= 38 and len(n) <= 26 for n in flat)
    assert len(set(flat)) == len(flat)  # different runs, different databases


def test_the_selection_defaults_to_the_unit_names(setdir, tmp_path, fakes):
    run = run_it(two_units(setdir)[:1], options(setdir, tmp_path), tmp_path)
    assert run.read_json("run.json")["selection"] == "mini"
    assert run.name.endswith("-mini")


def test_unit_failure_does_not_stop_the_others(setdir, tmp_path, fakes):
    fakes.start_errors["mini2"] = f"The app copy did not start with {KEY} in it.\nLast 20 lines of the log:\n..."
    run = run_it(two_units(setdir), options(setdir, tmp_path), tmp_path)
    got = statuses(run)
    assert got["mini"] == "done"
    assert got["mini2"].startswith("failed: The app copy did not start")
    assert "\n" not in got["mini2"]
    for path in run.path.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md", ".log", ".jsonl"}:
            assert KEY not in path.read_text(encoding="utf-8", errors="replace"), path
    assert (run.path / "report.md").exists()
    assert "mini2" in (run.path / "run.log").read_text()


def test_a_failure_after_set_up_keeps_what_set_up_did(setdir, tmp_path, fakes):
    fakes.api_errors["mini"] = {"put_opening": AppError(500, "boom", "the opening failed")}
    run = run_it(two_units(setdir)[:1], options(setdir, tmp_path), tmp_path)
    assert statuses(run)["mini"].startswith("failed: ")
    assert "the opening failed" in statuses(run)["mini"] or "boom" in statuses(run)["mini"]
    unit = two_units(setdir)[0]
    assert load_progress(run.path / "units" / unit.slug).client_id == 1  # set_up's work was saved
    assert fakes.stopped  # the copy was stopped


def test_stop_by_spend_guard_marks_unit_stopped_and_resume_finishes_it(setdir, tmp_path, fakes):
    fakes.per_file = Decimal("2")
    unit = two_units(setdir)[0]
    run = run_it([unit], options(setdir, tmp_path, pool=1, yes=True), tmp_path, estimate=Decimal("1"))
    assert statuses(run) == {"mini": "stopped"}
    progress = load_progress(run.path / "units" / unit.slug)
    assert progress.batches_done == ["2023-04-12"] and not progress.before_done
    sent = [c for c in fakes.apis["mini"].calls if c[0] == "analyze"]
    assert len(sent) == 1  # nothing further was sent after the stop

    fakes.per_file = Decimal("0")
    fakes.spent = Decimal("0")
    seen = len(fakes.apis["mini"].calls)
    fakes.databases.clear()
    again = resume_it(run, options(setdir, tmp_path, pool=1, yes=True), tmp_path)
    assert again.path == run.path and statuses(run) == {"mini": "done"}
    assert fakes.databases and all(resume is True for *_, resume in fakes.databases)
    names = [Path(c[1][2]).name for c in fakes.apis["mini"].calls[seen:] if c[0] == "analyze"]
    assert not any("prior_tb" in n for n in names) and len(names) == 2  # the saved batch was not sent again
    assert load_progress(run.path / "units" / unit.slug).after_done
    assert (run.path / "report.md").exists()


def test_resume_restarts_only_the_units_that_are_not_done(setdir, tmp_path, fakes):
    fakes.start_errors["mini2"] = "no luck"
    units = two_units(setdir)
    opts = options(setdir, tmp_path)
    run = run_it(units, opts, tmp_path)
    assert statuses(run) == {"mini": "done", "mini2": "failed: no luck"}
    before = run.read_json("run.json")
    fakes.start_errors.clear()
    fakes.starts.clear()
    fakes.databases.clear()
    stopped_before = list(fakes.stopped)
    resume_it(open_run(run.name, tmp_path / "runs"), opts, tmp_path)
    after = run.read_json("run.json")
    assert statuses(run) == {"mini": "done", "mini2": "done"}
    assert [s["unit"] for s in fakes.starts] == ["mini2"]
    assert [d[1] for d in fakes.databases] == [before["units"][1]["db"]] and fakes.databases[0][3] is True
    assert len(fakes.stopped) == len(stopped_before) + 1
    assert after["started"] == before["started"] and after["units"][0] == before["units"][0]
    assert (run.path / "units" / units[1].slug / "raw" / "after").is_dir()


def test_run_log_has_one_line_per_event_and_none_twice_after_a_resume(setdir, tmp_path, fakes):
    fakes.start_errors["mini2"] = "no luck"
    units = two_units(setdir)
    opts = options(setdir, tmp_path)
    run = run_it(units, opts, tmp_path)
    assert orchestrate.log.handlers == []  # the file handler is gone
    fakes.start_errors.clear()
    resume_it(run, opts, tmp_path)
    assert orchestrate.log.handlers == []
    lines = (run.path / "run.log").read_text().splitlines()
    starts = [ln for ln in lines if "unit start" in ln]
    assert sum(units[0].slug in ln for ln in starts) == 1  # the done unit was not started again
    assert sum(units[1].slug in ln for ln in starts) == 2  # started, failed, started again
    text = "\n".join(lines)
    for word in ("batch done", "snapshot before", "snapshot after", "unit end"):
        assert word in text
    assert KEY not in text and "Bearer" not in text and "Authorization" not in text


def spent_run(setdir, tmp_path, fakes):
    """A run the guard stopped after its first batch."""
    fakes.per_file = Decimal("2")
    unit = two_units(setdir)[0]
    run = run_it([unit], options(setdir, tmp_path, pool=1, yes=True), tmp_path, estimate=Decimal("1"))
    assert statuses(run) == {"mini": "stopped"}
    fakes.per_file = Decimal("0")
    fakes.spent = Decimal("0")
    fakes.starts.clear()
    return run, unit


def write_costs(run, *amounts):
    (run.path / "relay").mkdir(exist_ok=True)
    (run.path / "relay" / "costs.jsonl").write_text(
        "".join(json.dumps({"seq": i, "cost": a}) + "\n" for i, a in enumerate(amounts, 1)))


def test_resume_with_the_earlier_spend_over_the_limit_sends_nothing_under_yes(setdir, tmp_path, fakes):
    run, unit = spent_run(setdir, tmp_path, fakes)
    write_costs(run, "1.00", "2.00")  # $3 against an estimate of $1
    resume_it(run, options(setdir, tmp_path, pool=1, yes=True), tmp_path)
    assert fakes.starts == [] and statuses(run) == {"mini": "stopped"}
    assert "resume not started" in (run.path / "run.log").read_text()
    assert orchestrate.log.handlers == []


def test_resume_asks_once_with_the_earlier_spend_and_carries_on_after_yes(setdir, tmp_path, fakes, monkeypatch):
    run, unit = spent_run(setdir, tmp_path, fakes)
    write_costs(run, "3.00")
    prompts = []
    monkeypatch.setattr("builtins.input", lambda p: prompts.append(p) or "y")
    resume_it(run, options(setdir, tmp_path, pool=1), tmp_path)
    assert prompts == ["Spent $3.00 against an estimate of $1. Carry on? [y/N] "]
    assert statuses(run) == {"mini": "done"}


def test_resume_keeps_the_earlier_spend_in_view_for_each_batch(setdir, tmp_path, fakes):
    run, unit = spent_run(setdir, tmp_path, fakes)
    write_costs(run, "1.00")  # inside the limit, so the resume starts, but the next batch tips it over
    fakes.per_file = Decimal("0.4")
    fakes.spent = Decimal("0")
    resume_it(run, options(setdir, tmp_path, pool=1, yes=True), tmp_path)
    assert statuses(run) == {"mini": "stopped"}  # $1.00 earlier plus this session's $0.80 passes $1.50


def test_a_failed_save_does_not_lose_the_unit_or_stop_the_run(setdir, tmp_path, fakes, monkeypatch):
    def broken(unit_dir, progress):
        raise OSError("disk full")

    monkeypatch.setattr(orchestrate, "save_progress", broken)
    run = run_it(two_units(setdir), options(setdir, tmp_path), tmp_path)
    got = statuses(run)
    assert all(s.startswith("failed: ") for s in got.values()), got
    assert (run.path / "report.md").exists() and run.read_json("run.json")["finished"]
    assert sorted(fakes.stopped) == sorted(u["db"] for u in run.read_json("run.json")["units"])


def test_a_failure_before_the_unit_folder_is_read_is_recorded(setdir, tmp_path, fakes, monkeypatch):
    def broken(unit_dir):
        raise ValueError("progress.json is not json")

    monkeypatch.setattr(orchestrate, "load_progress", broken)
    run = run_it(two_units(setdir), options(setdir, tmp_path), tmp_path)
    assert all(s.startswith("failed: ValueError") for s in statuses(run).values())


def test_a_replayed_run_resumes_with_its_own_replay_folder(setdir, tmp_path, fakes):
    folder = tmp_path / "earlier"
    (folder / "relay").mkdir(parents=True)
    (folder / "relay" / "calls.jsonl").write_text("")
    fakes.start_errors["mini2"] = "no luck"
    run = run_it(two_units(setdir), options(setdir, tmp_path, replay=folder), tmp_path)
    assert fakes.relays[-1].replay_from == folder / "relay"
    fakes.start_errors.clear()
    # the caller says: no replay, automatic review (which would wait for a review that never comes)
    started = time.monotonic()
    resume_it(run, options(setdir, tmp_path, review="automatic", yes=True), tmp_path)
    assert fakes.relays[-1].replay_from == folder / "relay"
    assert statuses(run) == {"mini": "done", "mini2": "done"} and time.monotonic() - started < 20
    assert run.read_json("run.json")["options"]["review"] == "off"


def test_a_live_run_does_not_resume_as_a_replay(setdir, tmp_path, fakes):
    folder = tmp_path / "earlier"
    (folder / "relay").mkdir(parents=True)
    (folder / "relay" / "calls.jsonl").write_text("")
    fakes.start_errors["mini2"] = "no luck"
    run = run_it(two_units(setdir), options(setdir, tmp_path), tmp_path)
    fakes.start_errors.clear()
    resume_it(run, options(setdir, tmp_path, replay=folder), tmp_path)
    assert fakes.relays[-1].replay_from is None


def test_the_mongodb_password_is_not_written_to_disk(setdir, tmp_path, fakes):
    uri = "mongodb://runner:hunter2@db.example:27017/?authSource=admin"
    run = run_it(two_units(setdir)[:1], options(setdir, tmp_path, mongodb_uri=uri), tmp_path)
    assert run.read_json("run.json")["options"]["mongodb_uri"] == "mongodb://***@db.example:27017/?authSource=admin"
    assert fakes.databases[0][0] == uri  # the run itself still uses it
    for path in run.path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "hunter2" not in text and "runner:" not in text, path
    assert orchestrate._hide_userinfo("mongodb://localhost:27017") == "mongodb://localhost:27017"


def test_a_halted_guard_stops_even_without_an_estimate():
    guard = orchestrate.SpendGuard(None, yes=False, ask=lambda p: "y")
    assert guard.check(Decimal("1")) is True
    guard.halt()
    assert guard.check(Decimal("1")) is False


def test_halting_stops_a_running_unit_after_its_batch(setdir, tmp_path, fakes, monkeypatch):
    guards = []

    class Seen(orchestrate.SpendGuard):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            guards.append(self)

    monkeypatch.setattr(orchestrate, "SpendGuard", Seen)
    unit = two_units(setdir)[0]
    original = FakeApi.analyze

    def halting(self, *a, **k):
        guards[0].halt()
        return original(self, *a, **k)

    monkeypatch.setattr(FakeApi, "analyze", halting)
    run = run_it([unit], options(setdir, tmp_path, pool=1), tmp_path)
    assert statuses(run) == {"mini": "stopped"}
    assert load_progress(run.path / "units" / unit.slug).batches_done == ["2023-04-12"]


def test_ctrl_c_stops_the_running_unit_after_its_batch_and_starts_no_more(setdir, tmp_path, fakes, monkeypatch):
    original = FakeApi.analyze

    def interrupting(self, *a, **k):
        signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)  # Ctrl-C, to the main thread
        time.sleep(0.3)
        return original(self, *a, **k)

    monkeypatch.setattr(FakeApi, "analyze", interrupting)
    units = two_units(setdir)
    with pytest.raises(KeyboardInterrupt):
        run_it(units, options(setdir, tmp_path, pool=1), tmp_path)
    run = open_run(next((tmp_path / "runs").iterdir()).name, tmp_path / "runs")
    assert statuses(run) == {"mini": "stopped", "mini2": "pending"}
    assert [s["unit"] for s in fakes.starts] == ["mini"]
    assert load_progress(run.path / "units" / units[0].slug).batches_done == ["2023-04-12"]
    assert orchestrate.log.handlers == []
