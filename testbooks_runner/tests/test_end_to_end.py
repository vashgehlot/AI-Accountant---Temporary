"""A pack through the real app, on a throwaway MongoDB database, with a fake model that spends nothing."""
import hashlib
import json
import os
from pathlib import Path

import pytest
from pymongo import MongoClient

from testbooks_runner import orchestrate, report, runs, selection
from testbooks_runner.orchestrate import RunOptions
from testbooks_runner.tests.fake_upstream import make_minimal_upstream
from testbooks_runner.tests.servers import serve

FIX = Path(__file__).parent / "fixtures" / "set"
REPO = Path(__file__).resolve().parents[2]
URI = os.environ.get("LEDGERSYNC_TEST_MONGODB_URI")


@pytest.mark.mongo
@pytest.mark.skipif(not URI, reason="needs LEDGERSYNC_TEST_MONGODB_URI")
def test_fixture_pack_runs_through_the_real_app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")  # env wins over .env; the fake upstream never checks it
    monkeypatch.setenv("OPENROUTER_MODEL", "qwen/qwen3.8-27b")
    calls: list = []
    up_port, stop_upstream = serve(make_minimal_upstream(calls))
    units = selection.select_units(FIX, packs=["EC-0346"])
    client = None
    try:
        client = MongoClient(URI)
        options = RunOptions(set_dir=FIX, app_dir=REPO, mongodb_uri=URI, pool=1, review="off", yes=True,
                             upstream=f"http://127.0.0.1:{up_port}/api/v1")
        measurements, verdicts = tmp_path / "measurements.json", tmp_path / "verdicts.csv"
        run = orchestrate.run_selection(units, options, runs_root=tmp_path, measurements_path=measurements,
                                        verdicts_path=verdicts)
        u = run.read_json("run.json")["units"][0]
        assert u["db"].startswith("tbrun_")
        assert u["status"] == "done", u["status"]
        progress = runs.load_progress(run.unit_dir(units[0]))
        sent = {p.relative_to(units[0].folder).as_posix() for p in (units[0].folder / "inbox").rglob("*")
                if p.is_file()}
        assert sent and set(progress.uploads) == sent
        assert (run.path / "report.md").is_file()
        assert report.UNREVIEWED in (run.path / "report.md").read_text()
        rows = [json.loads(line) for line in (run.path / "relay" / "calls.jsonl").read_text().splitlines()]
        assert any(r["part"] == "reader" for r in rows)
        assert calls and all(c["path"].startswith("/api/v1/") for c in calls)
        # the reader's calls reached the model with the app's key, which the relay passes on and never records
        assert any(c["path"] == "/api/v1/chat/completions" and c["headers"].get("authorization") == "Bearer test-key"
                   for c in calls)
        assert not measurements.exists()  # a stand-in on this machine is never measured
    finally:
        try:
            stop_upstream()
        finally:
            try:
                if client is not None:
                    _drop_own_databases(client, tmp_path)
            finally:
                if client is not None:
                    client.close()


def _drop_own_databases(client, runs_root: Path) -> None:
    """Drops this run's databases only: those in its run.json and any under its own name prefix."""
    names: set[str] = set()
    prefixes: list[str] = []
    for folder in (p for p in runs_root.iterdir() if p.is_dir()):  # the test's own, fresh runs_root
        prefixes.append(f"tbrun_{hashlib.sha1(folder.name.encode('utf-8')).hexdigest()[:8]}_")
        try:
            names.update(u["db"] for u in json.loads((folder / "run.json").read_text())["units"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for existing in client.list_database_names():
        if any(existing.startswith(prefix) for prefix in prefixes):
            names.add(existing)
    for name in sorted(names):
        if name.startswith("tbrun_"):
            base = name[: -len("_checkpoints")] if name.endswith("_checkpoints") else name
            client.drop_database(base)
            client.drop_database(base + "_checkpoints")
