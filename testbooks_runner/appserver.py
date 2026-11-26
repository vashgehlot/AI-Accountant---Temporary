"""Start, check and stop throwaway copies of the app, each on its own database."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

import httpx
import pymongo

from .api import Api, AppError

LOG_LINES = 20
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class StartError(Exception):
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _assignments(app_dir: Path):
    """Yield (name, raw value text) for each assignment line in app_dir/.env."""
    try:
        text = (Path(app_dir) / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and _NAME.match(name):
            yield name, value


def env_names(app_dir: Path) -> set[str]:
    """The variable names in app_dir/.env. Values are never returned."""
    return {name for name, _ in _assignments(app_dir)}


def _unquote(value: str) -> str:
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value[1:]
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


_SECRETIVE = re.compile(r"KEY|SECRET|TOKEN|PASSWORD", re.I)


def read_env_value(app_dir: Path, name: str) -> str | None:
    """One non-secret value from app_dir/.env (the last assignment), or None. Refuses names that look secret."""
    if _SECRETIVE.search(name):
        raise ValueError(f"Refusing to read {name} from .env: the runner reads no secrets")
    found = None
    for key, value in _assignments(app_dir):
        if key == name:
            found = _unquote(value)
    return found or None


def live_db_name(app_dir: Path, environ: Mapping[str, str]) -> str:
    """The app's own database name. The one value read from .env, and not a secret."""
    if environ.get("MONGODB_DB_NAME"):
        return environ["MONGODB_DB_NAME"]
    found = ""
    for name, value in _assignments(app_dir):
        if name == "MONGODB_DB_NAME":
            found = _unquote(value)
    return found or "ledgersync"


def preflight(app_dir: Path, environ: Mapping[str, str]) -> None:
    app_dir = Path(app_dir)
    if not (app_dir / "server.py").is_file():
        raise StartError(f"No server.py in {app_dir}: point --app-dir at the app's checkout")
    if not environ.get("OPENROUTER_API_KEY") and "OPENROUTER_API_KEY" not in env_names(app_dir):
        raise StartError(f"No OpenRouter key: the app reads it from {app_dir}/.env; copy .env from the main checkout")


def check_database(mongodb_uri: str, db: str, live: str, *, resume: bool,
                   client_factory: Callable = pymongo.MongoClient) -> None:
    if not db.startswith("tbrun_"):
        raise StartError(f"Refusing database {db!r}: run databases must start with tbrun_")
    if db == live:
        raise StartError(f"Refusing database {db!r}: it is the app's own database")
    client = None
    try:
        client = client_factory(mongodb_uri, serverSelectionTimeoutMS=5000)
        held = [name for name in (db, f"{db}_checkpoints") if client[name].list_collection_names()]
    except Exception as e:
        raise StartError(f"Cannot reach MongoDB at {mongodb_uri} to check database {db!r}: {type(e).__name__}") from e
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    if held and not resume:
        raise StartError(f"Database {' and '.join(repr(n) for n in held)} already has collections; "
                         "use --resume to carry on with it, or a new run name")


def app_env(environ: Mapping[str, str], *, mongodb_uri: str, db: str, port: int, relay_url: str) -> dict:
    env = dict(environ)
    env.update({
        "MONGODB_URI": mongodb_uri,
        "MONGODB_DB_NAME": db,
        "LEDGERSYNC_HOST": "127.0.0.1",
        "LEDGERSYNC_PORT": str(port),
        "OPENROUTER_BASE_URL": relay_url,
        "LEDGERSYNC_REVIEW_DAILY_LIMIT": "100000",
        "LEDGERSYNC_RELOAD": "0",
        # the app's shipped defaults, pinned so a developer's .env cannot change a run
        "LEDGERSYNC_WARMUP": "1",
        "LEDGERSYNC_REVIEW_WORKER": "1",
        "LEDGERSYNC_DEMO": "0",
    })
    return env


def _git(app_dir: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=app_dir, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def app_commit(app_dir: Path) -> dict:
    app_dir = Path(app_dir)
    head = _git(app_dir, "rev-parse", "HEAD")
    if head is None:
        return {"commit": None, "dirty": None}
    changes = _git(app_dir, "status", "--porcelain", "--", "server.py", "ledgersync")
    return {"commit": head.strip(), "dirty": None if changes is None else bool(changes.strip())}


@dataclass
class AppCopy:
    port: int
    db: str
    process: subprocess.Popen
    log: Path
    api: Api
    log_file: object = None


def _log_tail(log: Path) -> str:
    try:
        lines = Path(log).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return "\n".join(lines[-LOG_LINES:]) or "(log is empty)"


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(process.pid, sig)  # the copy leads its own process group (start_copy starts a new session)
    except (ProcessLookupError, PermissionError):
        process.send_signal(sig)  # no group of its own: the process alone (a no-op once it has exited)


def _terminate(process: subprocess.Popen) -> None:
    """Stop the copy and anything it started: its whole process group, asked first, then killed after 10 s."""
    if process.poll() is not None:
        return
    _signal_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        process.wait()


def start_copy(app_dir: Path, *, python: str, env: dict, port: int, db: str, log: Path,
               timeout: float = 90.0) -> AppCopy:
    app_dir = Path(app_dir)
    log = Path(log)
    log_file = open(log, "ab")
    try:
        # its own session, so a Ctrl-C in the runner's terminal reaches the runner alone: the copies keep serving
        # while each unit finishes its batch, and stop_copy stops them
        process = subprocess.Popen([python, "server.py"], cwd=app_dir, env=env, stdout=log_file,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except Exception:
        log_file.close()
        raise
    base = f"http://127.0.0.1:{port}"
    api = Api(base, timeout=2.0)  # for the start-up polls only: the copy's own client waits as long as the app needs
    try:
        deadline = time.monotonic() + timeout
        failure = None
        while failure is None:
            code = process.poll()
            if code is not None:
                failure = f"the app exited with code {code} before it answered"
                break
            try:
                api.health()
            except (httpx.HTTPError, AppError, ValueError):
                pass
            else:
                api.close()
                return AppCopy(port, db, process, log, Api(base), log_file)
            if time.monotonic() >= deadline:
                failure = f"the app did not answer on port {port} within {timeout:g} seconds"
                break
            time.sleep(0.5)
    except BaseException:
        _release(process, api, log_file)
        raise
    _release(process, api, log_file)
    raise StartError(f"The app copy for {db} did not start: {failure}. Last {LOG_LINES} lines of {log}:\n{_log_tail(log)}")


def _release(process: subprocess.Popen, api: Api, log_file) -> None:
    try:
        _terminate(process)
    finally:
        api.close()
        log_file.close()


def stop_copy(copy: AppCopy) -> None:
    _terminate(copy.process)
    copy.api.close()
    if copy.log_file is not None:
        copy.log_file.close()
