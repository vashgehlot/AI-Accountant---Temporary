import os
import subprocess
import sys
import time

import pytest

from testbooks_runner import appserver

HEALTH_SERVER = """
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"status": "online"}).encode()
        code = 200 if self.path == "/api/health" else 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(os.environ["LEDGERSYNC_PORT"])), H).serve_forever()
"""


class FakeDb:
    def __init__(self, names):
        self._names = names

    def list_collection_names(self):
        return list(self._names)


class FakeClient:
    def __init__(self, dbs):
        self._dbs = dbs
        self.closed = False

    def __getitem__(self, db):
        return FakeDb(self._dbs.get(db, []))

    def close(self):
        self.closed = True


def fake(uri, **kw):
    return FakeClient({"tbrun_full": ["clients"], "tbrun_mem_checkpoints": ["checkpoints"]})


def test_app_env_points_the_app_at_its_database_and_the_relay():
    e = appserver.app_env({"PATH": "/bin"}, mongodb_uri="mongodb://localhost:27017", db="tbrun_x_1", port=9001,
                          relay_url="http://127.0.0.1:9002/c/u")
    assert (e["MONGODB_DB_NAME"], e["LEDGERSYNC_PORT"], e["OPENROUTER_BASE_URL"],
            e["LEDGERSYNC_REVIEW_DAILY_LIMIT"]) == ("tbrun_x_1", "9001", "http://127.0.0.1:9002/c/u", "100000")
    assert (e["MONGODB_URI"], e["LEDGERSYNC_HOST"], e["LEDGERSYNC_RELOAD"], e["PATH"]) == (
        "mongodb://localhost:27017", "127.0.0.1", "0", "/bin")


def test_app_env_pins_the_shipped_defaults_over_the_callers_environment():
    e = appserver.app_env({"LEDGERSYNC_WARMUP": "0", "LEDGERSYNC_REVIEW_WORKER": "", "LEDGERSYNC_DEMO": "1"},
                          mongodb_uri="mongodb://x", db="tbrun_x_1", port=1, relay_url="http://r")
    assert (e["LEDGERSYNC_WARMUP"], e["LEDGERSYNC_REVIEW_WORKER"], e["LEDGERSYNC_DEMO"]) == ("1", "1", "0")


def test_databases_refused():
    for db, live in [("ledgersync", "ledgersync"), ("mine", "ledgersync"), ("tbrun_full", "ledgersync"),
                     ("tbrun_a", "tbrun_a")]:
        with pytest.raises(appserver.StartError):
            appserver.check_database("mongodb://x", db, live, resume=False, client_factory=fake)
    appserver.check_database("mongodb://x", "tbrun_full", "ledgersync", resume=True, client_factory=fake)
    appserver.check_database("mongodb://x", "tbrun_empty", "ledgersync", resume=False, client_factory=fake)


def test_check_database_wraps_connection_failures_and_closes_the_client():
    def broken(uri, **kw):
        raise OSError("no route")

    with pytest.raises(appserver.StartError, match="MongoDB"):
        appserver.check_database("mongodb://x", "tbrun_a", "ledgersync", resume=False, client_factory=broken)
    client = FakeClient({})
    appserver.check_database("mongodb://x", "tbrun_a", "ledgersync", resume=False, client_factory=lambda u, **kw: client)
    assert client.closed


def test_checkpoints_database_counts_as_holding_data():
    with pytest.raises(appserver.StartError, match="tbrun_mem_checkpoints"):
        appserver.check_database("mongodb://x", "tbrun_mem", "ledgersync", resume=False, client_factory=fake)
    appserver.check_database("mongodb://x", "tbrun_mem", "ledgersync", resume=True, client_factory=fake)


def test_check_database_asks_for_a_short_server_selection_timeout():
    seen = {}

    def factory(uri, **kw):
        seen.update(kw)
        return FakeClient({})

    appserver.check_database("mongodb://x", "tbrun_a", "ledgersync", resume=False, client_factory=factory)
    assert seen == {"serverSelectionTimeoutMS": 5000}


def test_env_names_returns_names_only(tmp_path):
    (tmp_path / ".env").write_text(
        "# comment\n\nMONGODB_URI=mongodb://secret-host\nexport OPENROUTER_API_KEY = sk-secret\n"
        "  SPACED=1\nNOT A NAME=1\nnoequals\n#COMMENTED=1\n")
    names = appserver.env_names(tmp_path)
    assert names == {"MONGODB_URI", "OPENROUTER_API_KEY", "SPACED"}
    assert appserver.env_names(tmp_path / "missing") == set()


def test_live_db_name_prefers_environment_then_env_file_then_default(tmp_path):
    assert appserver.live_db_name(tmp_path, {}) == "ledgersync"
    (tmp_path / ".env").write_text("OTHER=x\nMONGODB_DB_NAME=\"books_live\"  # note\n")
    assert appserver.live_db_name(tmp_path, {}) == "books_live"
    assert appserver.live_db_name(tmp_path, {"MONGODB_DB_NAME": "from_env"}) == "from_env"
    (tmp_path / ".env").write_text("export MONGODB_DB_NAME=plain\n")
    assert appserver.live_db_name(tmp_path, {}) == "plain"


def test_preflight_names_the_missing_key(tmp_path):
    (tmp_path / "server.py").write_text("")
    (tmp_path / ".env").write_text("MONGODB_URI=x\n")
    with pytest.raises(appserver.StartError, match=r"\.env"):
        appserver.preflight(tmp_path, {})
    appserver.preflight(tmp_path, {"OPENROUTER_API_KEY": "k"})
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=k\n")
    appserver.preflight(tmp_path, {})


def test_preflight_message_never_contains_env_values(tmp_path):
    (tmp_path / "server.py").write_text("")
    (tmp_path / ".env").write_text("MONGODB_URI=hunter2-secret\n")
    with pytest.raises(appserver.StartError) as e:
        appserver.preflight(tmp_path, {})
    assert "hunter2" not in str(e.value)


def test_preflight_needs_server_py(tmp_path):
    with pytest.raises(appserver.StartError, match="server.py"):
        appserver.preflight(tmp_path, {"OPENROUTER_API_KEY": "k"})


def test_start_failure_shows_the_log(tmp_path):
    (tmp_path / "server.py").write_text("print('boom'); raise SystemExit(1)")
    with pytest.raises(appserver.StartError, match="boom"):
        appserver.start_copy(tmp_path, python=sys.executable, env=dict(os.environ), port=appserver.free_port(),
                             db="tbrun_t_1", log=tmp_path / "app.log", timeout=10)


def test_start_timeout_stops_the_process_and_shows_the_log(tmp_path):
    (tmp_path / "server.py").write_text(
        "import os, time\nopen('pid', 'w').write(str(os.getpid()))\nprint('warming', flush=True)\ntime.sleep(60)\n")
    with pytest.raises(appserver.StartError, match="warming") as e:
        appserver.start_copy(tmp_path, python=sys.executable, env=dict(os.environ), port=appserver.free_port(),
                             db="tbrun_t_1", log=tmp_path / "app.log", timeout=2)
    assert "within 2 seconds" in str(e.value)
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_interrupt_during_the_wait_leaves_no_process_behind(tmp_path, monkeypatch):
    (tmp_path / "server.py").write_text(
        "import os, time\nopen('pid', 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
    pidfile = tmp_path / "pid"
    real_sleep = time.sleep

    def interrupt(seconds):
        if seconds != 0.5:  # subprocess's own waits also sleep; only the start loop's pause interrupts
            return real_sleep(seconds)
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                break
            real_sleep(0.05)
        raise KeyboardInterrupt

    monkeypatch.setattr(appserver.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        appserver.start_copy(tmp_path, python=sys.executable, env=dict(os.environ), port=appserver.free_port(),
                             db="tbrun_t_1", log=tmp_path / "app.log", timeout=30)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_start_copy_from_a_path_with_spaces(tmp_path):
    app = tmp_path / "ACTING OFFICE- WORK"
    app.mkdir()
    (app / "server.py").write_text(HEALTH_SERVER)
    port = appserver.free_port()
    copy = appserver.start_copy(app, python=sys.executable, env={**os.environ, "LEDGERSYNC_PORT": str(port)},
                                port=port, db="tbrun_t_1", log=app / "app.log", timeout=20)
    try:
        assert copy.api.health()["status"] == "online"
    finally:
        appserver.stop_copy(copy)
    assert copy.process.poll() is not None
    appserver.stop_copy(copy)  # idempotent


SLOW_SERVER = """
import json, os, time
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/health":
            time.sleep(3)  # a busy app: longer than the start-up polls wait
        body = json.dumps([{"start": "2023-04-01"}]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(os.environ["LEDGERSYNC_PORT"])), H).serve_forever()
"""


def test_the_copys_client_waits_longer_than_the_start_up_polls(tmp_path):
    (tmp_path / "server.py").write_text(SLOW_SERVER)
    port = appserver.free_port()
    copy = appserver.start_copy(tmp_path, python=sys.executable, env={**os.environ, "LEDGERSYNC_PORT": str(port)},
                                port=port, db="tbrun_t_1", log=tmp_path / "app.log", timeout=20)
    try:
        started = time.monotonic()
        assert copy.api.years(1) == [{"start": "2023-04-01"}]  # a slow answer, not a time-out
        assert time.monotonic() - started >= 3
    finally:
        appserver.stop_copy(copy)


GROUP_SERVER = """
import os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open("child.pid", "w").write(str(child.pid))
""" + HEALTH_SERVER


def _gone(pid: int, within: float = 10.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_copy_runs_in_its_own_process_group_and_stops_with_everything_in_it(tmp_path):
    (tmp_path / "server.py").write_text(GROUP_SERVER)
    port = appserver.free_port()
    copy = appserver.start_copy(tmp_path, python=sys.executable, env={**os.environ, "LEDGERSYNC_PORT": str(port)},
                                port=port, db="tbrun_t_1", log=tmp_path / "app.log", timeout=20)
    child = int((tmp_path / "child.pid").read_text())  # written before the copy answered its first poll
    try:
        # a Ctrl-C at the runner's terminal goes to the runner's process group, so not to the copy
        assert os.getpgid(copy.process.pid) == copy.process.pid != os.getpgrp()
        assert os.getpgid(child) == copy.process.pid
    finally:
        appserver.stop_copy(copy)
        alive = not _gone(child)
        if alive:
            os.kill(child, 9)
    assert not alive, "a process the copy started outlived it"


def test_app_commit_reports_head_and_dirty(tmp_path):
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=tmp_path, check=True,
                       capture_output=True)

    assert appserver.app_commit(tmp_path) == {"commit": None, "dirty": None}
    git("init", "-q")
    (tmp_path / "server.py").write_text("x = 1\n")
    (tmp_path / "other.txt").write_text("a")
    git("add", ".")
    git("commit", "-q", "-m", "m")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert appserver.app_commit(tmp_path) == {"commit": head, "dirty": False}
    (tmp_path / "other.txt").write_text("b")
    assert appserver.app_commit(tmp_path)["dirty"] is False
    (tmp_path / "server.py").write_text("x = 2\n")
    assert appserver.app_commit(tmp_path) == {"commit": head, "dirty": True}
