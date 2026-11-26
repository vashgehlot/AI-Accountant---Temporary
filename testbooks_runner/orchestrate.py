"""Runs a selection: one relay, a pool of app copies, a spending guard, and a run folder that can be resumed.

Each unit gets its own copy of the app on its own throwaway database. A unit that fails is recorded and the
others carry on. Everything a resume needs is on disk: run.json, each unit's progress.json and the relay's
records.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, books, driver, estimate as estimating, mapping, report, score
from .appserver import (StartError, app_commit, app_env, check_database, free_port, live_db_name, preflight,
                        start_copy, stop_copy)
from .model import Unit
from .relay import Relay
from .runs import RUNS, RunDir, load_progress, new_run, open_run, save_progress
from .verdicts import VERDICTS_CSV

log = logging.getLogger(__name__)
_FORMAT = "%(asctime)s %(threadName)s %(message)s"
_MESSAGE_CHARS = 300


class RunError(StartError):
    """The selection can't be run as asked, and nothing was started."""


@dataclass
class RunOptions:
    set_dir: Path
    app_dir: Path
    python: str = sys.executable
    mongodb_uri: str = "mongodb://localhost:27017"
    pool: int = 4
    review: str = "automatic"
    replay: Path | None = None
    with_next_year: bool = False
    yes: bool = False
    label: str | None = None
    against: str | None = None
    upstream: str = "https://openrouter.ai/api/v1"
    selection: str = ""


class SpendGuard:
    """Says whether to carry on, once the spend has run past the estimate. Shared by the worker threads."""

    def __init__(self, estimate: Decimal | None, *, yes: bool, ask=None):
        self.threshold = estimate
        self.yes = yes
        self.ask = ask if ask is not None else input
        self._lock = threading.Lock()
        self._declined = False
        self._halted = threading.Event()

    def halt(self) -> None:
        """Make every later check say stop, so each running unit ends after its current batch."""
        self._halted.set()

    def check(self, spent: Decimal, unpriced: int = 0) -> bool:
        """`unpriced` calls have no cost yet, so `spent` is a lower bound: the question says so."""
        if self._halted.is_set():
            return False
        if self.threshold is None:
            return True
        with self._lock:  # one question at a time, and the others see its answer
            if self._declined:
                return False
            if spent <= self.threshold * Decimal("1.5"):
                return True
            if self.yes:
                return False
            note = f" ({report.unpriced_note(unpriced, 'the spend')})" if unpriced else ""
            answer = self.ask(f"Spent ${spent} against an estimate of ${self.threshold}{note}. Carry on? [y/N] ")
            if answer.strip().lower() in ("y", "yes"):
                self.threshold *= 2
                return True
            self._declined = True
            return False


class _State:
    """run.json held in memory and written whole, under a lock, whenever a thread changes it."""

    def __init__(self, run: RunDir, info: dict):
        self.run, self.info = run, info
        self.lock = threading.Lock()

    def save(self) -> None:
        with self.lock:
            self.run.write_json("run.json", self.info)

    def entry(self, slug: str) -> dict:
        return next(u for u in self.info["units"] if u["slug"] == slug)

    def status(self, slug: str, status: str) -> None:
        with self.lock:
            self.entry(slug)["status"] = status
            self.run.write_json("run.json", self.info)

    def note_health(self, health: dict) -> None:
        with self.lock:
            if "model" in self.info["app"]:
                return
            for name in ("model", "ai_reachable", "model_available"):
                self.info["app"][name] = health.get(name)
            self.run.write_json("run.json", self.info)


def _slug_of(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60] or "run"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _failure(exc: Exception) -> str:
    text = (str(exc).strip().splitlines() or [""])[0] or type(exc).__name__
    if not isinstance(exc, StartError):
        text = f"{type(exc).__name__}: {text}"
    secret = os.environ.get("OPENROUTER_API_KEY")
    if secret:
        text = text.replace(secret, "[key]")
    return f"failed: {text[:_MESSAGE_CHARS]}"


def _check_replay(units: list[Unit], options: RunOptions) -> None:
    if options.replay is None:
        return
    if any(u.repeat > 1 for u in units):
        raise RunError("A replay can't be combined with repeats: each repeat would be answered from the same "
                       "recording, so repeating measures nothing")
    if not (Path(options.replay) / "relay" / "calls.jsonl").is_file():
        raise RunError(f"No recording to replay: {Path(options.replay) / 'relay' / 'calls.jsonl'} is missing. "
                       "Without it the run would go to the real model and spend money")


def _options_record(options: RunOptions) -> dict:
    record = {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(options).items()}
    record["mongodb_uri"] = _hide_userinfo(record["mongodb_uri"])  # a password must not reach the disk
    return record


def _hide_userinfo(uri: str) -> str:
    return re.sub(r"^([A-Za-z][\w+.-]*://)[^/]*@", r"\1***@", uri)


_PATHS = ("set_dir", "app_dir", "replay")


def _recorded_options(info: dict, caller: RunOptions) -> RunOptions:
    """The run's own settings, so a resume can't go live when the run was a replay or the reverse.

    The caller supplies only `yes` and the MongoDB address (the recorded one has its password hidden).
    """
    recorded = dict(info.get("options") or {})
    known = {f.name for f in fields(RunOptions)}
    values = {k: v for k, v in recorded.items() if k in known and k not in ("yes", "mongodb_uri")}
    for name in _PATHS:
        if values.get(name) is not None:
            values[name] = Path(values[name])
    values.setdefault("set_dir", (info.get("set") or {}).get("path") or caller.set_dir)
    values.setdefault("app_dir", caller.app_dir)
    values["set_dir"] = Path(values["set_dir"])
    return RunOptions(yes=caller.yes, mongodb_uri=caller.mongodb_uri, **values)


def _run_unit(unit: Unit, entry: dict, state: _State, relay: Relay, guard: SpendGuard, options: RunOptions,
              before_spend: Decimal, resume: bool, before_unpriced: int = 0) -> None:
    slug, run = unit.slug, state.run
    unit_dir = progress = copy = None
    try:
        unit_dir = run.unit_dir(unit)
        progress = load_progress(unit_dir)
        log.info("unit start %s on %s", slug, entry["db"])
        state.status(slug, "running")
        key = books.load_key(unit.key_dir)
        profile = books.load_profile(unit.folder)
        opts = driver.Options(review=options.review, with_next_year=options.with_next_year)
        check_database(options.mongodb_uri, entry["db"], live_db_name(options.app_dir, os.environ),
                       resume=resume)
        port = free_port()
        env = app_env(os.environ, mongodb_uri=options.mongodb_uri, db=entry["db"], port=port,
                      relay_url=relay.base_url(slug))
        copy = start_copy(options.app_dir, python=options.python, env=env, port=port, db=entry["db"],
                          log=unit_dir / "app.log")
        try:
            state.note_health(copy.api.health())
        except Exception as exc:  # the model's name is a nicety; the run doesn't depend on it
            log.info("health unreadable for %s: %s", slug, type(exc).__name__)
        driver.set_up(copy.api, unit, key, profile, mapping.load_chart(), progress, opts)
        save_progress(unit_dir, progress)  # set_up changes progress without saving it

        def after_batch() -> bool:
            totals = relay.totals()
            spent, unpriced = before_spend + totals["cost"], before_unpriced + totals["unpriced"]
            log.info("batch done %s (%s), spent $%s%s", slug, progress.batches_done[-1], spent,
                     f" and {unpriced} calls not priced" if unpriced else "")
            return guard.check(spent, unpriced)

        driver.send_batches(copy.api, unit, key, profile, progress, opts, unit_dir=unit_dir,
                            after_batch=after_batch)
        periods = driver.vat_periods(key, unit.period)
        if not progress.before_done:
            driver.take_snapshot(copy.api, progress, unit_dir, "before", periods)
            log.info("snapshot before %s", slug)
        driver.send_replies(copy.api, unit, key, progress, unit_dir, relay=relay, options=opts)
        sent = sum(1 for r in progress.replies.values() if r.get("sent"))
        log.info("replies %s: %d sent of %d considered", slug, sent, len(progress.replies))
        if not progress.after_done:
            driver.take_snapshot(copy.api, progress, unit_dir, "after", periods)
            log.info("snapshot after %s", slug)
        status = "done"
    except driver.Stopped as stop:
        status = "stopped"
        log.info("unit stopped %s: %s", slug, stop)
    except Exception as exc:
        status = _failure(exc)
    finally:
        try:
            if progress is not None:
                save_progress(unit_dir, progress)
        except Exception as exc:  # the unit's status must still be recorded
            log.info("saving progress for %s failed: %s", slug, type(exc).__name__)
        if copy is not None:
            try:
                stop_copy(copy)
            except Exception as exc:
                log.info("stopping the copy for %s failed: %s", slug, type(exc).__name__)
    state.status(slug, status)
    log.info("unit end %s: %s", slug, status)


def on_this_machine(url: str) -> bool:
    """True when the address is a loopback one (127.0.0.1, localhost, ::1): a stand-in for the model, never the
    provider, so what it costs and how long it takes say nothing about a real run."""
    host = (urlsplit(url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def prior_spend(run: RunDir) -> Decimal:
    total = Decimal(0)
    path = run.path / "relay" / "costs.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                cost = json.loads(line).get("cost")
            except (ValueError, AttributeError):
                continue
            if cost is not None:
                total += Decimal(str(cost))
    return total


def _execute(state: _State, todo: list[Unit], options: RunOptions, *, resume: bool, verdicts_path: Path,
             measurements_path: Path | None) -> RunDir:
    run = state.run
    handler = logging.FileHandler(run.path / "run.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    relay = None
    try:
        raw = state.info.get("estimate")
        guard = SpendGuard(Decimal(str(raw)) if raw not in (None, "") else None, yes=options.yes)
        before_spend = prior_spend(run) if resume else Decimal(0)
        before_unpriced = score.unpriced_calls(run) if resume else 0
        if resume and not guard.check(before_spend, before_unpriced):
            log.info("resume not started: $%s is already spent against an estimate of $%s%s", before_spend,
                     state.info.get("estimate"), f", and {before_unpriced} calls not priced" if before_unpriced else "")
            return run
        replay = Path(options.replay) / "relay" if options.replay else None
        relay = Relay(options.upstream, run.path / "relay", replay_from=replay)
        relay.start()
        by_slug = {u["slug"]: u for u in state.info["units"]}
        try:
            with ThreadPoolExecutor(max_workers=max(1, options.pool), thread_name_prefix="unit") as pool:
                futures = [pool.submit(_run_unit, u, by_slug[u.slug], state, relay, guard, options, before_spend,
                                       resume, before_unpriced) for u in todo]
                try:
                    for f in futures:
                        f.result()
                except KeyboardInterrupt:
                    # units not yet started never start; running ones stop after their current batch
                    log.info("interrupted: stopping after the batches now running")
                    guard.halt()
                    for f in futures:
                        f.cancel()
                    raise
        except KeyboardInterrupt:
            state.save()  # the pool has waited for the running units
            raise
        relay.stop()
        relay = None
        state.info["finished"] = _now()
        state.save()
        if on_this_machine(options.upstream):
            log.info("no measurements kept: the model at %s is a stand-in on this machine", options.upstream)
        else:
            measured = {} if measurements_path is None else {"path": measurements_path}
            estimating.update_measurements(run.path, **measured)
        against = open_run(options.against, run.path.parent) if options.against else None
        score.score_run(run, Path(options.set_dir), verdicts_path=verdicts_path, against=against)
        log.info("run finished and scored")
        return run
    finally:
        if relay is not None:
            relay.stop()
        log.removeHandler(handler)
        handler.close()


def run_selection(units: list[Unit], options: RunOptions, *, runs_root: Path = RUNS,
                  estimate: Decimal | None = None, verdicts_path: Path = VERDICTS_CSV,
                  measurements_path: Path | None = None) -> RunDir:
    units = list(units)
    _check_replay(units, options)
    preflight(options.app_dir, os.environ)
    selection = options.selection or " ".join(dict.fromkeys(u.name for u in units))
    run = new_run(options.label or _slug_of(selection), runs_root)
    # Atlas allows 38 bytes for a database name and the app adds "_checkpoints", so keep these to 26 characters
    prefix = f"tbrun_{hashlib.sha1(run.name.encode('utf-8')).hexdigest()[:8]}"
    info = {
        "selection": selection, "options": _options_record(options), "review": options.review,
        "with_next_year": options.with_next_year, "app": dict(app_commit(options.app_dir)),
        "runner": __version__,
        "set": {"path": str(options.set_dir), "key_hashes": {u.slug: books.key_hash(u) for u in units}},
        "estimate": None if estimate is None else str(estimate), "started": _now(), "finished": None,
        "units": [{"slug": u.slug, "db": f"{prefix}_{i}", "status": "pending", "name": u.name, "kind": u.kind,
                   "period_start": u.period.start.isoformat(), "period_end": u.period.end.isoformat(),
                   "repeat": u.repeat} for i, u in enumerate(units, 1)],
    }
    run.write_json("run.json", info)
    return _execute(_State(run, info), units, options, resume=False, verdicts_path=verdicts_path,
                    measurements_path=measurements_path)


def resume_run(run: RunDir, options: RunOptions, *, verdicts_path: Path = VERDICTS_CSV,
               measurements_path: Path | None = None) -> RunDir:
    info = run.read_json("run.json")
    if not isinstance(info, dict) or not info.get("units"):
        raise RunError(f"{run.path} has no run.json to resume from")
    options = _recorded_options(info, options)
    todo = [score._unit_from(e, Path(options.set_dir)) for e in info["units"] if e.get("status") != "done"]
    _check_replay(todo, options)
    preflight(options.app_dir, os.environ)
    return _execute(_State(run, info), todo, options, resume=True, verdicts_path=verdicts_path,
                    measurements_path=measurements_path)

