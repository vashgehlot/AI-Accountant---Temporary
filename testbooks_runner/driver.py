"""Drives one unit through the app the way a person would: set the client up, then send its papers batch by batch."""
from __future__ import annotations

import fnmatch
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from . import align as aligning
from . import books, selection, setup
from .api import AppError
from .model import Key, Period, Unit
from .runs import Progress, RunDir, save_progress
from .setup import SetupError

MAX_IN_FLIGHT = 5
FINISHED = {"succeeded", "failed", "cancelled"}
PROVIDER_CODES = {"ai_rate_limited", "ai_timeout", "ai_offline", "ai_error"}
REFUSED_CODES = {"invalid_input", "unreadable_file", "unsupported_file", "file_too_large", "year_closed"}
PROVIDER_STATUS = 503


@dataclass
class Options:
    review: str = "automatic"
    with_next_year: bool = False
    job_timeout: float = 900.0
    review_timeout: float = 900.0
    review_grace: float = 25.0
    poll: float = 2.0
    retry_pause: float = 20.0  # before a file goes again: the app keeps a failed model check for 15 seconds


class Stopped(Exception):
    """The caller asked to stop after a batch was saved."""


def set_up(api, unit: Unit, key: Key, profile: dict, chart, progress: Progress, options: Options) -> list[str]:
    """Run each set-up step still missing, so a call after a partial failure carries on where it stopped."""
    client = None
    if progress.client_id is None:
        client = api.create_client(setup.client_fields(profile, unit.period, options.review))
        progress.client_id = client["id"]
    if progress.app_year_start is None:
        wanted = unit.period.end.isoformat()
        starts = [y["start"] for y in api.years(progress.client_id) if y["end"] == wanted]
        if not starts:
            raise SetupError(f"the app has no year ending {wanted} for {unit.name}; it starts "
                             f"{unit.period.start}, so the first year end is wrong")
        progress.app_year_start = starts[0]
    if not progress.bank_codes:
        progress.bank_codes = setup.bank_codes(profile, client or api.client(progress.client_id))
    warnings: list[str] = []
    if not progress.opening_done:
        opening, warnings = setup.opening_balances(key, chart)
        api.put_opening(progress.client_id, opening)
        progress.opening_done = True
    return warnings


def _parse_time(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def wait_jobs(api, job_ids: list[str], *, timeout: float, poll: float, clock=time.monotonic,
              sleep=time.sleep) -> dict[str, dict]:
    """Poll until every job has finished or the timeout passes; unfinished jobs come back as last seen."""
    start = clock()
    jobs: dict[str, dict] = {}
    waiting = list(job_ids)
    while True:
        for job_id in list(waiting):
            jobs[job_id] = api.job(job_id)
            if jobs[job_id]["status"] in FINISHED:
                waiting.remove(job_id)
        if not waiting or clock() - start >= timeout:
            return jobs
        sleep(poll)


def wait_review(api, client_id: int, since: datetime, *, timeout: float, grace: float, poll: float,
                clock=time.monotonic, sleep=time.sleep) -> str:
    start = clock()
    while True:
        reviews = api.reviews(client_id)
        recent = [r for r in reviews if _parse_time(r["started_at"]) >= since]
        if any(r["status"] != "running" for r in recent):
            return "done"
        elapsed = clock() - start
        if not recent and elapsed >= grace and not any(r["status"] == "running" for r in reviews):
            return "none"
        if elapsed >= timeout:
            return "timeout"
        sleep(poll)


def _error(code: str, message: str, status: int | None) -> dict:
    return {"code": code, "message": message, "status": status}


class _Batch:
    """The files of one batch going through the app, at most MAX_IN_FLIGHT being read at once."""

    def __init__(self, api, unit: Unit, profile: dict, progress: Progress, options: Options, unit_dir: Path,
                 clock, now, sleep):
        self.api, self.unit, self.profile, self.progress = api, unit, profile, progress
        self.options, self.unit_dir, self.clock, self.now, self.sleep = options, unit_dir, clock, now, sleep
        self.year = date.fromisoformat(progress.app_year_start)
        self.rows: list[dict] = []

    def account(self, rel: str) -> str | None:
        for row in self.rows:
            if row["file"] == rel:
                named = setup.statement_account(row["doc_id"], self.profile)
                return self.progress.bank_codes.get(named) if named else None
        return None

    def finish(self, rel: str, entry: dict, status: str, error: dict | None = None, job: dict | None = None):
        job = job or {}
        entry.update(status=status, error=error, finished=self.now().timestamp(),
                     job_id=job.get("job_id", entry.get("job_id")),
                     upload_id=(job.get("result") or {}).get("upload_id") if status == "saved" else None)
        self.progress.uploads[rel] = entry
        save_progress(self.unit_dir, self.progress)

    def run(self, files: list[Path], rows: list[dict]) -> None:
        self.rows = rows
        pending = deque((p.relative_to(self.unit.folder).as_posix(), p) for p in files
                        if p.relative_to(self.unit.folder).as_posix() not in self.progress.uploads)
        active: dict[str, tuple[str, Path, dict, float]] = {}
        while pending or active:
            while pending and len(active) < MAX_IN_FLIGHT:
                rel, path = pending.popleft()
                self.submit(rel, path, {"submitted": self.now().timestamp(), "tries": 0}, active)
            if not active:
                continue
            progressed = False
            for job_id in list(active):
                rel, path, entry, began = active[job_id]
                try:
                    job = self.api.job(job_id)
                except AppError as err:
                    del active[job_id]
                    progressed = True
                    self.finish(rel, entry, "failed", _error(err.code, err.message, err.status))
                    continue
                if job["status"] in FINISHED:
                    del active[job_id]
                    progressed = True
                    self.judge(rel, path, entry, job, active)
                elif self.clock() - began >= self.options.job_timeout:
                    del active[job_id]
                    progressed = True
                    self.finish(rel, entry, "failed", _error("job_timeout", "The job did not finish in time", None),
                                job)
            if active and not progressed:
                self.sleep(self.options.poll)

    def submit(self, rel: str, path: Path, entry: dict, active: dict) -> None:
        while True:
            entry["tries"] += 1
            try:
                job_id = self.api.analyze(self.progress.client_id, self.year, path, self.account(rel))
            except AppError as err:
                failure = _error(err.code, err.message, err.status)
                if err.status == 409 and err.code == "same_file":
                    return self.finish(rel, entry, "same file", failure)
                if err.status == PROVIDER_STATUS:
                    if entry["tries"] < 2:
                        self.sleep(self.options.retry_pause)
                        continue
                    return self.finish(rel, entry, "failed", failure)
                return self.finish(rel, entry, "refused", failure)
            entry["job_id"] = job_id
            active[job_id] = (rel, path, entry, self.clock())
            return

    def judge(self, rel: str, path: Path, entry: dict, job: dict, active: dict) -> None:
        if job["status"] == "succeeded":
            has_rows = (job.get("result") or {}).get("upload_id")
            return self.finish(rel, entry, "saved" if has_rows else "no rows", None, job)
        err = job.get("error") or {}
        code = err.get("code") or job["status"]
        failure = _error(code, err.get("message") or "", err.get("status_code"))
        if job["status"] == "failed" and code in PROVIDER_CODES and entry["tries"] < 2:
            self.sleep(self.options.retry_pause)
            return self.submit(rel, path, entry, active)
        if job["status"] == "failed" and code in REFUSED_CODES:
            return self.finish(rel, entry, "refused", failure, job)
        self.finish(rel, entry, "failed", failure, job)


def send_batches(api, unit: Unit, key: Key, profile: dict, progress: Progress, options: Options, *,
                 unit_dir: Path, clock=time.monotonic, now=lambda: datetime.now(timezone.utc),
                 sleep=time.sleep, after_batch: Callable[[], bool] | None = None) -> None:
    rows = key.documents
    for day, files in selection.files_to_send(unit, key, options.with_next_year):
        label = day.isoformat()
        if label in progress.batches_done:
            continue
        batch = _Batch(api, unit, profile, progress, options, Path(unit_dir), clock, now, sleep)
        batch.run(files, rows)
        mine = [progress.uploads[p.relative_to(unit.folder).as_posix()] for p in files]
        if options.review != "off" and any(e["status"] == "saved" for e in mine):
            since = datetime.fromtimestamp(max(e["finished"] for e in mine), timezone.utc)
            outcome = wait_review(api, progress.client_id, since, timeout=options.review_timeout,
                                  grace=options.review_grace, poll=options.poll, clock=clock, sleep=sleep)
            progress.review_waits[label] = outcome
        progress.batches_done.append(label)
        save_progress(Path(unit_dir), progress)
        if after_batch is not None and not after_batch():
            raise Stopped(f"stopped after the {label} batch")


def vat_periods(key: Key, period: Period) -> list[tuple[date, date]]:
    """The key's VAT return periods lying wholly inside the period, in date order."""
    found = []
    for row in key.vat_returns:
        start, end = date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"])
        if start >= period.start and end <= period.end:
            found.append((start, end))
    return sorted(found)


def _save(raw: RunDir, name: str, call: Callable[[], object], *, binary: bool = False):
    """Save one call's answer as <name>.json (or <name>.xlsx); an AppError becomes <name>.error.json instead.

    Only one of the two files is left in the folder. Anything but AppError (the app down) propagates.
    """
    ok_name = name + (".xlsx" if binary else ".json")
    err_name = name + ".error.json"
    try:
        data = call()
    except AppError as err:
        (raw.path / ok_name).unlink(missing_ok=True)
        raw.write_json(err_name, {"status": err.status, "code": err.code, "message": err.message})
        return None
    (raw.path / err_name).unlink(missing_ok=True)
    if binary:
        target = raw.path / ok_name
        tmp = target.with_name(target.name + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        raw.write_json(ok_name, data)
    return data


def take_snapshot(api, progress: Progress, unit_dir: Path, which: str,
                  vat_periods: list[tuple[date, date]]) -> None:
    """Save the app's books as the API returned them, to unit_dir/raw/<which>/, then mark the snapshot done."""
    raw = RunDir(Path(unit_dir) / "raw" / which)
    raw.path.mkdir(parents=True, exist_ok=True)
    cid = progress.client_id
    scored = date.fromisoformat(progress.app_year_start)
    _save(raw, "client", lambda: api.client(cid))
    listed = _save(raw, "years", lambda: api.years(cid))
    _save(raw, "accounts", lambda: api.accounts(cid))
    starts = [date.fromisoformat(y["start"]) for y in listed or []]
    if scored not in starts:
        starts.append(scored)
    for start in starts:
        ledger = _save(raw, f"ledger-{start}", lambda s=start: api.ledger(cid, s))
        if start == scored or (isinstance(ledger, dict) and ledger.get("transactions")):
            _save(raw, f"posted-{start}", lambda s=start: api.posted_tb(cid, s))
    _save(raw, "tb-shown", lambda: api.tb_shown(cid, scored))
    for start, end in vat_periods:
        _save(raw, f"vat-{start}-{end}", lambda a=start, b=end: api.vat(cid, scored, a, b))
    _save(raw, "invoices", lambda: api.invoices(cid, scored))
    _save(raw, "bank", lambda: api.bank(cid, scored))
    _save(raw, "summary", lambda: api.summary(cid, scored))
    _save(raw, "suggestions", lambda: api.suggestions(cid, scored))
    _save(raw, "questions", lambda: api.questions(cid))
    _save(raw, "decisions", lambda: api.decisions(cid))
    _save(raw, "reviews", lambda: api.reviews(cid))
    _save(raw, "export", lambda: api.export_xlsx(cid, scored), binary=True)
    if which == "after" and progress.thread_id:
        _save(raw, "chat", lambda: api.thread(progress.thread_id))
    if which == "before":
        progress.before_done = True
    else:
        progress.after_done = True
    save_progress(Path(unit_dir), progress)


def client_words(text: str) -> str:
    """The client's reply without its opening "Re:" line (the key's question) and the blank lines after it."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("Re:"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def reply_files(answer_file: Path) -> list[Path]:
    """The files that came with a reply: the others in its folder, apart from the replies themselves."""
    answer_file = Path(answer_file)
    return sorted(p for p in answer_file.parent.iterdir()
                  if p.is_file() and p != answer_file and not p.name.startswith(".") and not fnmatch.fnmatch(p.name, "*_reply_*.txt"))


def _asked(snap) -> list[dict]:
    """The app's open or waiting questions, from its question list and its reviews, each once."""
    found, seen = [], set()
    for q in list(snap.questions) + [q for r in snap.reviews for q in r.get("questions") or []]:
        if q.get("status") in ("open", "waiting") and q.get("id") not in seen:
            seen.add(q.get("id"))
            found.append(q)
    return found


def plan_replies(unit: Unit, key: Key, snap, al) -> list[dict]:
    """One entry per query with a reply file, in answer_date order; `send` when the app asked that question."""
    asked = sorted(_asked(snap), key=lambda q: str(q.get("created_at") or ""))
    matches: dict[str, dict] = {}
    for q in asked:
        found = aligning.query_for(q, key, al)
        if found is not None:
            matches.setdefault(found, q)
    plan = []
    for query in sorted((q for q in key.queries if q.get("answer_file")),
                        key=lambda q: (q.get("answer_date") or "", q["query_id"])):
        match = matches.get(query["query_id"])
        plan.append({"query_id": query["query_id"], "answer_file": query["answer_file"],
                     "question_id": match.get("id") if match else None,
                     "question_text": match.get("text") if match else None,
                     "send": match is not None})
    return plan


def _failure(err: AppError) -> dict:
    return {"status": err.status, "code": err.code, "message": err.message}


def _wait_idle(api, thread_id: str, options: Options, clock, sleep) -> None:
    start = clock()
    while api.thread(thread_id).get("running") and clock() - start < options.review_timeout:
        sleep(options.poll)


def _turn(api, thread_id: str, text: str, files: list[Path], options: Options, clock, sleep) -> list:
    try:
        return api.send_message(thread_id, text, files)
    except AppError as err:
        if not (err.status == 409 and err.code == "still_working"):
            raise
    _wait_idle(api, thread_id, options, clock, sleep)
    return api.send_message(thread_id, text, files)


def _open_thread(api, progress: Progress) -> None:
    year = date.fromisoformat(progress.app_year_start)
    try:
        thread = api.new_thread(progress.client_id, year)
    except AppError as err:
        progress.chat_refusal = _failure(err)
        thread = api.new_thread(progress.client_id)
    progress.thread_id = thread["id"]
    progress.chat_year = thread.get("year_start")


def _confirm_offers(api, progress: Progress) -> list[dict]:
    """The answers the app's agent filled in from the client's reply in this chat, confirmed unchanged: the client's
    yes, as they would press Confirm on the card. An answer the app now refuses is recorded with why, not retried."""
    confirmed = []
    for q in api.questions(progress.client_id):
        offer = q.get("offer") or {}
        if q.get("status") == "resolved" or offer.get("thread_id") != progress.thread_id:
            continue
        item = {"question_id": q["id"], "answer": offer.get("answer")}
        try:
            api.answer_question(progress.thread_id, q["id"], offer.get("answer"))
        except AppError as err:
            item["refused"] = err.message
        confirmed.append(item)
    return confirmed


def send_replies(api, unit: Unit, key: Key, progress: Progress, unit_dir: Path, *, relay=None,
                 options: Options, clock=time.monotonic, now=lambda: datetime.now(timezone.utc),
                 sleep=time.sleep) -> None:
    """Send the client's replies through the chat, each only under a question the app itself asked.

    The message is the app's question in its own words, then the client's words, and nothing else.
    """
    unit_dir = Path(unit_dir)
    snap = aligning.load_snapshot(unit_dir, "before")
    profile = books.load_profile(unit.folder)
    al = aligning.align(key, snap, progress.uploads, profile, progress.bank_codes)
    began = now()
    last_turn_end = None
    sent_now = False
    for item in plan_replies(unit, key, snap, al):
        qid = item["query_id"]
        if (progress.replies.get(qid) or {}).get("sent"):
            continue
        record = {"sent": False, "question_id": item["question_id"], "events": [], "asked_back": []}
        progress.replies[qid] = record
        if not item["send"]:
            save_progress(unit_dir, progress)
            continue
        if progress.thread_id is None:
            _open_thread(api, progress)
            save_progress(unit_dir, progress)
        answer = unit.folder / item["answer_file"]
        text = "> " + item["question_text"] + "\n\n" + client_words(answer.read_text(encoding="utf-8"))
        known = {q["id"] for q in api.questions(progress.client_id)}
        if relay is not None:
            relay.set_part(unit.slug, "chat")
        try:
            events = _turn(api, progress.thread_id, text, reply_files(answer), options, clock, sleep)
            record["sent"] = True
        except AppError as err:
            events = err.events
            record["error"] = _failure(err)
            record["sent"] = err.code == "stream_ended"
        finally:
            if relay is not None:
                relay.set_part(unit.slug, None)
        record["events"] = [[kind, data] for kind, data in events]
        record["asked_back"] = [q for kind, data in events if kind == "result"
                                for q in data.get("questions") or [] if q.get("id") not in known]
        if record["sent"]:
            sent_now = True
            last_turn_end = now()
            record["confirmed"] = _confirm_offers(api, progress)
        with (unit_dir / "chat.jsonl").open("a", encoding="utf-8") as fh:
            for kind, data in events:
                fh.write(json.dumps({"query_id": qid, "event": kind, "data": data}, ensure_ascii=False) + "\n")
        save_progress(unit_dir, progress)
    any_sent = any(r.get("sent") for r in progress.replies.values())
    if any_sent and options.review != "off" and (sent_now or "after-replies" not in progress.review_waits):
        progress.review_waits["after-replies"] = wait_review(
            api, progress.client_id, last_turn_end or began, timeout=options.review_timeout, grace=options.review_grace,
            poll=options.poll, clock=clock, sleep=sleep)
    save_progress(unit_dir, progress)
