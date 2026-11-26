"""Puts each hand-worked agent case (eval/agent_cases/<case>/, and the demo, demo/northbridge/) through the real chat
API and scores it: the files uploaded in a "Review these documents" message, the case's answers applied through the
answer routes, then

- the posted trial balance against the expected one, to the penny (the demo: before the answers and after them);
- the decisions, a rule for each row, against expected_decisions.json;
- the questions open or waiting after the review turn and after the answers, a kind and a row each, against
  expected_questions.json;

and a run fails if it has an error event, a failed step, an answer that could not be applied or changes left unposted.

  .venv/bin/python eval/run_agent_eval.py                                   # every case and the demo, on the real model
  .venv/bin/python eval/run_agent_eval.py --case clean-month --read rows    # one case, files read from their .rows.json
  .venv/bin/python eval/run_agent_eval.py --runs 3 --case demo
  .venv/bin/python eval/run_agent_eval.py --case demo --transcripts /tmp/runs    # also save each run's transcript

It spends OpenRouter credit (the one model, OPENROUTER_MODEL, which runs the agent and, unless --read rows, reads the
files) and needs the MongoDB cluster; it uses its own database (--db), dropped by nobody. Writes
eval/results/<date>-agent.json (every run of every case) and prints a table; exits 0 only when every run passed all
three scores. With --transcripts DIR it also writes DIR/<case>-r<run>.json for each run, right after it: the thread's
whole message history as the agent saw it (read from the chat's checkpoints), the events of the review turn, what the
answer routes were sent and replied, and the run's result. A demo reset deletes the demo's checkpoints, so the
transcript is taken before the next run starts.

The scoring functions take plain data, so a test can score a case worked with no model."""
from __future__ import annotations

import argparse
import datetime as dt
import dataclasses
import json
import mimetypes
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

EVAL_DIR = Path(__file__).parent
ROOT = EVAL_DIR.parent
sys.path[:0] = [str(ROOT), str(EVAL_DIR)]   # run as a script, neither is on the path

import run_scripted_resolutions as scripted   # noqa: E402
from job_scoring import compare, net_by_account   # noqa: E402

CASES_DIR = EVAL_DIR / "agent_cases"
RESULTS_DIR = EVAL_DIR / "results"
DEMO_DIR = ROOT / "demo" / "northbridge"
MESSAGE = "Review these documents"


# ─── Scoring: plain data in, a list of differences out (empty when it passes) ─────────────────────────────────────

def expected_trial_balances(case_dir: Path) -> tuple[Optional[dict], dict]:
    """(the trial balance expected after the review turn, the one after the answers). The first is None for a case
    that has only the final one."""
    case_dir = Path(case_dir)
    read = lambda name: json.loads((case_dir / name).read_text())
    if (case_dir / "expected_trial_balance_before_answers.json").exists():
        return read("expected_trial_balance_before_answers.json"), read("expected_trial_balance_after_answers.json")
    return None, read("expected_trial_balance.json")


def score_trial_balance(expected: dict, posted: dict[str, Decimal]) -> list[dict]:
    """Every account whose net differs, as job_scoring.compare gives it. posted: net_by_account of the posted
    trial balance."""
    return compare(expected, posted)


def _key(name: dict) -> tuple[str, str]:
    return (name["file"], name["description"])


def _missing_and_extra(expected: list, actual: list) -> list[dict]:
    """What the expected list has and the actual lacks, and the reverse, each as a difference."""
    left = list(actual)
    differences = []
    for item in expected:
        if item in left:
            left.remove(item)
        else:
            differences.append({"missing": item})
    return differences + [{"unexpected": item} for item in left]


def expected_rows(entry: dict) -> list[dict]:
    """The rows an expected decision is about, named: its row and those in its arguments (keep, drop, primary, other)."""
    named = [entry["row"]]
    for value in entry.get("arguments", {}).values():
        named += [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, dict) and "file" in v]
    return named


def exact_ids(names: dict[int, dict]):
    """A row finder over rows named exactly: the id of the one row with that file and description, or None."""
    def find(name: dict) -> Optional[int]:
        found = [i for i, n in names.items() if n == name]
        return found[0] if len(found) == 1 else None
    return find


def _same_vat(read, wanted) -> bool:
    """Whether the VAT the reader booked is exactly the one wanted (both as amounts); False when either is absent."""
    try:
        return read is not None and Decimal(str(read)) == Decimal(str(wanted))
    except ArithmeticError:
        return False


def score_decisions(expected: dict, decisions: list[dict], row_id, rows_read: Optional[dict[int, dict]] = None) -> list[dict]:
    """Each expected decision (resolutions, automatic, from_answers) against the applied decisions the year's route
    gives: the same rule on exactly the same set of rows (its row and its keep, drop, primary or other), in any order
    (a split also names the rows it adds).
    An applied decision satisfies at most one expected one. row_id: finds a named row's id (RowNames.id, or
    exact_ids), None when the year has no such row, which leaves the expected decision missing.
    rows_read: row id -> {"vat": ...} as the reader left the rows. An expected R5 (set_vat_from_document) that no
    decision, applied or refused, names the row for, and whose VAT the reader already booked exactly, is
    {"already_in_reading": {rule, row}}, not missing: there was nothing to take from the document. An applied one is
    matched as always."""
    left = [d for d in decisions if d["status"] == "applied"]
    differences = []
    for part in ("resolutions", "automatic", "from_answers"):
        for e in expected[part]:
            ids = [row_id(n) for n in expected_rows(e)]
            parts = len(e["arguments"]["parts"]) if e.get("action") == "split_vat" else 0   # the split's new rows
            found = None if None in ids else next(
                (d for d in left if d["rule"] == e["rule"] and set(ids) <= set(d["row_ids"])
                 and len(set(d["row_ids"])) == len(set(ids)) + parts), None)
            if found is None:
                named = {"rule": e["rule"], "row": e["row"]}
                in_reading = (e.get("action") == "set_vat_from_document" and rows_read is not None
                              and None not in ids and ids[0] in rows_read
                              and not any(d["rule"] == e["rule"] and ids[0] in d["row_ids"] for d in decisions)
                              and _same_vat(rows_read[ids[0]].get("vat"), e["arguments"]["vat"]))
                differences.append({"already_in_reading": named} if in_reading else {"missing": named})
            else:
                left.remove(found)
    return differences + [{"unexpected": {"row_ids": d["row_ids"], "rule": d["rule"]}} for d in left]


def named_questions(questions: list[dict], names: dict[int, dict], aliases: Optional[dict[int, dict]] = None) -> list[dict]:
    """Questions as the route gives them, as {"kind", "row"} with the row named: as the case names it where aliases
    (row id -> the case's name for it) has it, else as the year's rows are named."""
    aliases = aliases or {}
    row = lambda q: (aliases.get(q["row_ids"][0]) or names[q["row_ids"][0]]) if q["row_ids"] else None
    return [{"kind": q["kind"], "row": row(q)} for q in questions]


def score_questions(expected: list[dict], asked: list[dict]) -> list[dict]:
    """The questions asked, each a kind and a row, against those expected (their status ignored)."""
    shape = lambda q: (q["kind"], *(_key(q["row"]) if q["row"] else ("", "")))
    return _missing_and_extra(sorted(shape(q) for q in expected), sorted(shape(q) for q in asked))


class RowNames:
    """Finds the case's rows in the year by the names the case gives them ({"file", "description"}). With `fallback`
    (the vision model words a description its own way) a name no row has exactly is matched to the one row in that file
    with the same gross, direction and, when the case's row has one, date; never a row another name has, and never
    a guess between several: those stay unmatched, and `unmatched` says why. `fallbacks` lists each name found by
    amount."""

    def __init__(self, store, client_id: int, case_dir: Path, fallback: bool = False):
        self.store, self.client_id, self.fallback = store, client_id, fallback
        self.fallbacks, self.unmatched = [], []
        self._claimed: dict[int, tuple] = {}   # row id -> the name that took it
        self._known: dict[tuple, Optional[tuple]] = {}   # name -> (gross, direction, date); None when named twice
        for path in case_files(Path(case_dir)):
            read = json.loads(path.with_name(f"{path.name}.rows.json").read_text())
            for t in read["transactions"]:
                key = (path.name, t["description"])
                self._known[key] = None if key in self._known else (
                    Decimal(str(t["gross"])), t["direction"], str(t["date"]) if t.get("date") else None)

    def _why(self, name: dict, reason: str) -> None:
        if {"name": name, "why": reason} not in self.unmatched:
            self.unmatched.append({"name": name, "why": reason})

    def id(self, name: dict) -> Optional[int]:
        files = {u["id"]: u["name"] for u in self.store.uploads(self.client_id)}
        rows = [(r, files[r.upload_id]) for r in self.store.rows(self.client_id)]
        exact = [r for r, file in rows if (file, r.tx.description) == _key(name)]
        if exact:
            return exact[0].id if len(exact) == 1 else None
        known = self._known.get(_key(name))
        if not self.fallback or known is None:
            return None
        gross, direction, date = known
        taken = {i for i, who in self._claimed.items() if who != _key(name)}
        candidates = [r for r, file in rows
                      if file == name["file"] and r.tx.gross == gross and r.tx.direction == direction
                      and (date is None or str(r.tx.date) == date) and r.id not in taken
                      and (file, r.tx.description) not in self._known]
        if len(candidates) != 1:
            self._why(name, f"{len(candidates)} rows in the file have the same amount, direction and date")
            return None
        self._claimed[candidates[0].id] = _key(name)
        found = {"file": name["file"], "description": candidates[0].tx.description}
        if {"expected": name, "found": found} not in self.fallbacks:
            self.fallbacks.append({"expected": name, "found": found})
        return candidates[0].id


# ─── Reading the files from their prepared rows, so only the agent is real ────────────────────────────────────────

class PreparedRows:
    """Replaces the vision model: ledgersync.pipeline.analyze finds which file it was given and returns nothing, and
    adapter.to_transactions then returns that file's rows from its .rows.json. Files are known as the server's
    intake.load_upload reads them: by their bytes (pdf, image) or their text (text, table, a spreadsheet's cells
    comma-separated). `use` says which case's files are in play, since two cases may hold a file of the same name
    with different rows."""

    def __init__(self):
        self.by_bytes: dict[bytes, Path] = {}
        self.by_text: dict[str, Path] = {}
        self.current = threading.local()
        self._analyze = self._to_transactions = None

    def use(self, files: list[Path]) -> None:
        from ledgersync import intake
        self.by_bytes, self.by_text = {}, {}
        for path in files:
            item = intake.load_upload(path.name, path.read_bytes(), 1000)
            known, key = (self.by_bytes, item.data) if item.data is not None else (self.by_text, item.text.strip())
            if known.get(key, path) != path:
                raise ValueError(f"{path.name} and {known[key].name} read the same, so their rows can't be told apart.")
            known[key] = path

    def _find(self, item) -> Path:
        path = None
        if item.data is not None:
            path = self.by_bytes.get(item.data)
        elif item.text is not None:
            path = self.by_text.get(item.text.strip())
        if path is None:
            raise ValueError("--read rows: this file is not one of the case's documents.")
        return path

    def install(self) -> None:
        from ledgersync import adapter, pipeline
        from ledgersync.extractor import TransactionExtractionResult
        from ledgersync.models import Transaction
        self._analyze, self._to_transactions = pipeline.analyze, adapter.to_transactions

        def analyze(item, reader, ctx):
            self.current.path = self._find(item)
            ctx.report(f"Reading {self.current.path.name} from its prepared rows")
            return TransactionExtractionResult(data=[], model="prepared rows")

        def to_transactions(rows, source, settings, **kw):
            path, self.current.path = getattr(self.current, "path", None), None
            if path is None:
                return self._to_transactions(rows, source, settings, **kw)
            read = json.loads(path.with_name(f"{path.name}.rows.json").read_text())
            return [Transaction.model_validate(t) for t in read["transactions"]]

        pipeline.analyze, adapter.to_transactions = analyze, to_transactions

    def uninstall(self) -> None:
        from ledgersync import adapter, pipeline
        pipeline.analyze, adapter.to_transactions = self._analyze, self._to_transactions


# ─── The run ──────────────────────────────────────────────────────────────────────────────────────────────────────

# ─── A run's transcript: what the agent saw and said, for finding why a run went wrong ──────────────────────────────

def _blocks(content) -> tuple[str, list[dict], list]:
    """Message content as (its text, its reasoning, its other blocks). A list's text blocks are joined as they come;
    a reasoning, thinking or redacted block is kept as reasoning, labelled with where it was found."""
    if isinstance(content, str):
        return content, [], []
    text, reasoning, other = [], [], []
    for block in content or []:
        if isinstance(block, str):
            text.append(block)
        elif block.get("type") == "text":
            text.append(block.get("text", ""))
        elif block.get("type") in ("reasoning", "thinking", "redacted_thinking"):
            summary = " ".join(p.get("text", "") for p in block.get("summary") or [] if isinstance(p, dict))
            said = block.get("reasoning") or block.get("thinking") or block.get("text") or summary
            reasoning.append({"from": f"content block ({block['type']})", "text": said or json.dumps(block, default=str)})
        else:
            other.append(block)
    return "".join(text), reasoning, other


def message_json(message) -> dict:
    """One message of the agent's history as plain JSON: its type (human, ai, tool, system), its content in full as
    text, the reasoning it carries (from its content blocks or from additional_kwargs, labelled), and for an AI message
    its tool calls (name, args, id; those the model garbled under invalid_tool_calls), its finish_reason and
    served_by (the provider and model_name its response_metadata names, and its OpenRouter generation id as
    generation_id, whichever it has; left out when it has none), for a tool message its name, tool_call_id and status."""
    text, reasoning, other = _blocks(message.content)
    extra = getattr(message, "additional_kwargs", None) or {}
    for key in ("reasoning_content", "reasoning"):
        if extra.get(key):
            reasoning.append({"from": f"additional_kwargs.{key}", "text": extra[key]})
    if extra.get("reasoning_details"):
        reasoning.append({"from": "additional_kwargs.reasoning_details", "details": extra["reasoning_details"]})
    out = {"type": message.type, "content": text}
    if getattr(message, "name", None):
        out["name"] = message.name
    if reasoning:
        out["reasoning"] = reasoning
    if other:
        out["other_blocks"] = other
    if message.type == "ai":
        out["tool_calls"] = [{"name": c["name"], "args": c["args"], "id": c["id"]}
                             for c in getattr(message, "tool_calls", None) or []]
        if getattr(message, "invalid_tool_calls", None):
            out["invalid_tool_calls"] = list(message.invalid_tool_calls)
        meta = getattr(message, "response_metadata", None) or {}
        if meta.get("finish_reason"):
            out["finish_reason"] = meta["finish_reason"]
        served_by = {key: meta[key] for key in ("provider", "model_name") if meta.get(key)}
        if meta.get("id"):
            served_by["generation_id"] = meta["id"]
        if served_by:
            out["served_by"] = served_by
    if message.type == "tool":
        out["tool_call_id"] = message.tool_call_id
        out["status"] = getattr(message, "status", None)
    return out


def stored_rows(store, client_id: int) -> list[dict]:
    """The client's rows as stored, for a transcript: each row's id and upload with its fields."""
    return [{"id": r.id, "upload_id": r.upload_id, **r.tx.model_dump(mode="json"), "edited": r.original is not None}
            for r in store.rows(client_id)]


def thread_messages(saver, thread_id: str) -> list[dict]:
    """The thread's whole message history, read from the checkpointer the chat keeps it in (the latest checkpoint's
    "messages"), each as message_json gives it; [] when the thread has no checkpoint or no messages in it."""
    found = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    if found is None:
        return []
    return [message_json(m) for m in (found.checkpoint.get("channel_values") or {}).get("messages") or []]


# ─── The host behind each answer: OpenRouter doesn't send it with the stream, so it is looked up by generation id ───

def generation_fetcher(settings=None, *, client=None, sleep=time.sleep):
    """A fetch(generation_id) for lookup_hosts: OpenRouter's GET <base url>/generation?id=<id> as its JSON, or None
    when there is no key, the call fails or the record isn't there. The record can take a few seconds to appear (the
    run's last answer is looked up just after it), so a 404 is tried again after 2, 5 and 10 s. The key goes in the Authorization header only, and is never printed."""
    if settings is None:
        from ledgersync.config import Settings
        settings = Settings.from_env()

    def fetch(generation_id: str) -> Optional[dict]:
        if not settings.openrouter_api_key:
            return None
        import httpx
        http = client or httpx.Client(timeout=10)
        url = f"{settings.openrouter_base_url}/generation"
        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        for wait in (2, 5, 10, None):
            response = http.get(url, params={"id": generation_id}, headers=headers)
            if response.status_code == 404 and wait is not None:
                sleep(wait)
                continue
            return response.json() if response.status_code == 200 else None
        return None

    return fetch


def lookup_hosts(ids, fetch) -> dict:
    """For each distinct generation id, what fetch(id) says served it: {id: {"provider", and "latency_ms" and
    "generation_time_ms" when the record has them}}. An id whose lookup fails, or whose record names no provider, is
    left out; this never raises."""
    found = {}
    for generation_id in dict.fromkeys(ids):
        try:
            body = fetch(generation_id)
            data = body.get("data") if isinstance(body, dict) else None
            data = data if isinstance(data, dict) else {}
            provider = data.get("provider_name") or data.get("provider")
        except Exception as exc:
            print(f"host lookup for {generation_id} failed: {type(exc).__name__}", file=sys.stderr)
            continue
        if not provider:
            continue
        found[generation_id] = {"provider": provider}
        for field, key in (("latency", "latency_ms"), ("generation_time", "generation_time_ms")):
            if isinstance(data.get(field), (int, float)):
                found[generation_id][key] = data[field]
    return found


def fill_hosts(messages: list[dict], fetch) -> list[str]:
    """Fills the host (and timing) found by lookup_hosts into the served_by of each AI message in messages (as
    message_json gives them) that has a generation_id, in place; a message with a provider already keeps it. Gives the
    sorted distinct providers of all the messages."""
    served = [m["served_by"] for m in messages if m.get("type") == "ai" and m.get("served_by")]
    found = lookup_hosts([s["generation_id"] for s in served if s.get("generation_id")], fetch)
    for s in served:
        for key, value in found.get(s.get("generation_id"), {}).items():
            s.setdefault(key, value)
    return sorted({s["provider"] for s in served if s.get("provider")})


def _safe_error(exc: Exception) -> str:
    """An error as a line for the transcript; a database error is named only, as its text can carry the cluster's
    address."""
    return type(exc).__name__ if type(exc).__module__.startswith("pymongo") else f"{type(exc).__name__}: {exc}"


def write_transcript(directory: Path, name: str, run: int, *, saver, trace: dict, result: Optional[dict],
                     error: Optional[str] = None, fetch=None) -> Path:
    """Writes directory/<name>-r<run>.json: the run's messages (from saver, by the thread's id), the events of the
    review turn as [kind, data], the answers sent and what the routes replied, and the run's result (None when it
    couldn't finish, with error saying why). A failure to read the messages is recorded, not raised. Each AI message
    gets the host that served it (see fill_hosts; fetch is the lookup, OpenRouter's by default), and the distinct
    hosts are the transcript's "hosts" and added to result."""
    messages, messages_error = [], None
    if saver is not None and trace.get("thread_id"):
        try:
            messages = thread_messages(saver, trace["thread_id"])
        except Exception as exc:
            messages_error = _safe_error(exc)
    hosts = fill_hosts(messages, fetch or generation_fetcher())
    if result is not None:
        result["hosts"] = hosts
    document = {"case": name, "run": run, "thread_id": trace.get("thread_id"), "client_id": trace.get("client_id"),
                "hosts": hosts, "messages": messages, "events": trace.get("events", []), "answers": trace.get("answers", []),
                "rows_after_review": trace.get("rows_after_review", []),
                "questions_after_review": trace.get("questions_after_review", []),
                "rows_final": trace.get("rows_final", []), "decisions": trace.get("decisions", []),
                "result": result}
    if messages_error:
        document["messages_error"] = messages_error
    if error:
        document["error"] = error
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}-r{run}.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=str) + "\n")
    return path


def events_of(body: str) -> list[tuple[str, dict]]:
    """The server-sent events of a stream, as (type, data)."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def case_files(case_dir: Path) -> list[Path]:
    """Every file a case reads: its documents, and the files its answers upload."""
    uploaded = [case_dir / a["answer"]["file"] for a in scripted.answers(case_dir) if a["answer"]["kind"] == "upload"]
    return scripted._documents(case_dir) + uploaded


def _multipart(path: Path) -> tuple[str, bytes, str]:
    return (path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def _check(response) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url.path}: {response.status_code} "
                           f"{response.text[:300]}")
    return response.json()


def _add_client(api, store, records, case_dir: Path) -> int:
    """The case's client, as the chat starts from it: the demo reset, any other case added by the API. The cases'
    clients share a name, and two clients that aren't archived can't: the one an earlier case or run left in this
    database is archived first."""
    if case_dir.resolve() == DEMO_DIR.resolve():
        from ledgersync import demo
        return demo.reset(store, records, store.client[f"{store.db_name}_checkpoints"])
    fields = json.loads((case_dir / "client.json").read_text())
    wanted = " ".join(fields["name"].lower().split())
    for earlier in store.list_clients():
        if " ".join(earlier.name.lower().split()) == wanted:
            store.update_client(earlier.id, {"archived": True})
    client_id = _check(api.post("/api/clients", json=fields))["id"]
    if (case_dir / "opening_balances.json").exists():
        _check(api.put(f"/api/clients/{client_id}/opening-balances",
                       json=json.loads((case_dir / "opening_balances.json").read_text())))
    return client_id


def _posted(api, client_id: int, year_start: dt.date) -> dict:
    """The year's posted trial balance as the route gives it."""
    return _check(api.get(f"/api/clients/{client_id}/years/{year_start}/posted-trial-balance"))


def _apply_answer(api, row_names: RowNames, thread_id: str, case_dir: Path, item: dict,
                  log: Optional[list] = None) -> Optional[str]:
    """Answers the question item names, through its route; why it couldn't be, or None. log: where to note what was
    sent and what came back (or why nothing was sent)."""
    log = [] if log is None else log
    asked, given = item["question"], item["answer"]
    client_id = row_names.client_id
    row_id = row_names.id(asked["row"])
    if row_id is None:
        log.append({"question": asked, "not_sent": f"No row is named {asked['row']}."})
        return f"No row is named {asked['row']}."
    question = next((q for q in _check(api.get(f"/api/clients/{client_id}/questions"))
                     if q["kind"] == asked["kind"] and q["row_ids"][:1] == [row_id]), None)
    if question is None:
        log.append({"question": asked, "not_sent": f"No {asked['kind']} question is open on {asked['row']}."})
        return f"No {asked['kind']} question is open on {asked['row']}."
    base = f"/api/chat/threads/{thread_id}/questions/{question['id']}"
    if given["kind"] == "upload":
        route, sent = f"{base}/document", {"file": given["file"]}
        response = api.post(route, files={"file": _multipart(case_dir / given["file"])})
    else:
        route, sent = f"{base}/answer", given
        response = api.post(route, json=given)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    log.append({"question": asked, "question_id": question["id"], "route": f"POST {route}", "sent": sent,
                "status": response.status_code, "body": body})
    return None if response.status_code < 400 else f"{response.status_code} {response.text[:300]}"


def run_case(api, store, records, case_dir: Path, rows: Optional[PreparedRows], model: str, *, run: int = 1,
             transcripts: Optional[Path] = None, saver=None, label: Optional[str] = None) -> dict:
    """One run of a case: its scores, and what the turn cost (seconds, steps, failed steps, error events, refused
    decisions), with the ids of its client and thread. transcripts: a folder to write the run's transcript in, as
    write_transcript does, before this returns (or raises); saver is the checkpointer the thread's messages are read
    from, and label what the file is named (the case's name by default)."""
    trace = {"events": [], "answers": []}
    try:
        result = _run_case(api, store, records, Path(case_dir), rows, model, trace)
    except Exception as exc:
        if transcripts is not None:
            write_transcript(transcripts, label or Path(case_dir).name, run, saver=saver, trace=trace, result=None,
                             error=_safe_error(exc))
        raise
    result["run"] = run
    if transcripts is not None:
        try:
            path = write_transcript(transcripts, label or Path(case_dir).name, run, saver=saver, trace=trace,
                                    result=result)
            result["transcript"] = path.name
        except OSError as exc:   # a folder that can't be written doesn't lose the run's scores
            result["transcript_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _run_case(api, store, records, case_dir: Path, rows: Optional[PreparedRows], model: str, trace: dict) -> dict:
    """run_case without the transcript: trace gets the run's ids, the events of its review turn and the answers sent
    as they happen, so a run that fails part way still leaves what it had."""
    expected_decisions = json.loads((case_dir / "expected_decisions.json").read_text())
    expected_questions = json.loads((case_dir / "expected_questions.json").read_text())
    before_tb, after_tb = expected_trial_balances(case_dir)
    if rows is not None:
        rows.use(case_files(case_dir))
    started = time.monotonic()
    client_id = _add_client(api, store, records, case_dir)
    year_start = dt.date.fromisoformat(_check(api.get(f"/api/clients/{client_id}/years"))[0]["start"])
    thread = _check(api.post("/api/chat/threads", json={"client_id": client_id}))
    trace.update(client_id=client_id, thread_id=thread["id"])

    sent = api.post(f"/api/chat/threads/{thread['id']}/messages", data={"text": MESSAGE},
                    files=[("files", _multipart(p)) for p in scripted._documents(case_dir)])
    if sent.status_code != 200:
        raise RuntimeError(f"The message was refused: {sent.status_code} {sent.text[:300]}")
    events = events_of(sent.text)
    trace["events"] = events
    steps: dict[str, dict] = {}
    for kind, data in events:
        if kind == "step":
            steps[data["id"]] = data
    row_names = RowNames(store, client_id, case_dir, fallback=rows is None)
    expected_names = [n for part in ("resolutions", "automatic", "from_answers") for e in expected_decisions[part]
                      for n in expected_rows(e)]
    expected_names += [q["row"] for stage in expected_questions.values() for q in stage]
    expected_names += [a["question"]["row"] for a in scripted.answers(case_dir)]

    def aliases() -> dict[int, dict]:
        """Each row the case names, by id, as the case names it."""
        found = {row_names.id(n): n for n in expected_names}
        return {i: n for i, n in found.items() if i is not None}

    names = scripted._names(store, client_id)
    questions_after_review = _check(api.get(f"/api/clients/{client_id}/questions"))
    asked = named_questions(questions_after_review, names, aliases())
    review_posted = _posted(api, client_id, year_start)
    review_tb = net_by_account(review_posted)
    # What the review left, for the transcript: the rows as stored and the questions as the routes give them.
    trace["rows_after_review"] = stored_rows(store, client_id)
    trace["questions_after_review"] = questions_after_review

    unapplied = [problem for item in scripted.answers(case_dir)
                 if (problem := _apply_answer(api, row_names, thread["id"], case_dir, item, trace["answers"]))]
    seconds = round(time.monotonic() - started, 1)
    names = scripted._names(store, client_id)   # an answer's document adds rows
    asked_after = named_questions(_check(api.get(f"/api/clients/{client_id}/questions")), names, aliases())
    final_posted = _posted(api, client_id, year_start)
    final_tb = net_by_account(final_posted)
    decisions = _check(api.get(f"/api/clients/{client_id}/decisions?year_start={year_start}"))
    trace["rows_final"] = stored_rows(store, client_id)
    trace["decisions"] = decisions

    tb_diff = score_trial_balance(after_tb, final_tb)
    if before_tb is not None:
        tb_diff = [{"stage": "after answers", **d} for d in tb_diff] + \
                  [{"stage": "before answers", **d} for d in score_trial_balance(before_tb, review_tb)]
    q_diff = [{"stage": "before answers", **d}
              for d in score_questions(expected_questions["before_answers"], asked)]
    if "after_answers" in expected_questions:
        q_diff += [{"stage": "after answers", **d}
                   for d in score_questions(expected_questions["after_answers"], asked_after)]
    rows_read = {r["id"]: {"vat": r.get("vat")} for r in trace["rows_after_review"]}
    d_all = score_decisions(expected_decisions, decisions, row_names.id, rows_read)
    d_diff = [d for d in d_all if "already_in_reading" not in d]   # an R5 the reader already did is not a failure
    d_read = [d["already_in_reading"] for d in d_all if "already_in_reading" in d]
    failed = [s["text"] for s in steps.values() if s["state"] == "failed"]
    errors = [data for kind, data in events if kind == "error"]
    problems = ([f"error event: {e.get('code')}: {e.get('message')}" for e in errors]
                + [f"answer not applied: {u}" for u in unapplied]
                + ([f"{final_posted['unposted_changes']} changes are not posted"]
                   if final_posted["unposted_changes"] else []))
    return {
        "case": case_dir.name, "model": model, "seconds": seconds,   # the review turn and the answers
        "client_id": client_id, "thread_id": thread["id"],
        "trial_balance": {"passed": not tb_diff, "differences": tb_diff},
        "decisions": {"passed": not d_diff, "differences": d_diff, "already_in_reading": d_read},
        "questions": {"passed": not q_diff, "differences": q_diff},
        "problems": problems,   # a run with any of these fails, however its scores come out
        "row_fallbacks": row_names.fallbacks,   # rows found by file and amount: the model named them differently
        "unmatched_names": row_names.unmatched,   # case rows not found, and why
        "posted_problems": final_posted["problems"],   # why the books couldn't be fully worked out; not gating
        "steps": len(steps), "failed_steps": failed, "error_events": errors,
        "refused_decisions": [{"rule": d["rule"], "reason": d["reason"]} for d in decisions
                              if d["status"] == "refused"],
        "answers_not_applied": unapplied,
    }


def passed(result: dict) -> bool:
    """Whether a run passed all three scores and had no problems (error events, answers not applied, changes left
    unposted). Failed steps and refused decisions are recorded but don't fail it."""
    return all(result[s]["passed"] for s in ("trial_balance", "decisions", "questions")) and not result["problems"]


def clean(result: dict) -> bool:
    """Whether a run had no problems, no failed step and no refused decision."""
    return not (result["problems"] or result["failed_steps"] or result["refused_decisions"])


def table(runs: list[dict]) -> str:
    rows = [("case", "run", "TB", "decisions", "questions", "clean", "fallbacks", "seconds")]
    for r in runs:
        mark = lambda score: "pass" if r[score]["passed"] else "FAIL"
        rows.append((r["case"], str(r["run"]), mark("trial_balance"), mark("decisions"), mark("questions"),
                     "yes" if clean(r) else "NO", str(len(r["row_fallbacks"])), str(r["seconds"])))
    widths = [max(len(row[i]) for row in rows) for i in range(8)]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The accountant chat on every hand-worked case, scored.")
    parser.add_argument("--case", action="append", help='a case folder name, or "demo"; repeat for several')
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--read", choices=["model", "rows"], default="model",
                        help="rows: files read from their .rows.json, so only the agent is real")
    parser.add_argument("--db", default="ledgersync_agent_eval")
    parser.add_argument("--transcripts", type=Path, default=None, metavar="DIR",
                        help="also write DIR/<case>-r<run>.json for each run: the agent's messages, the events, "
                             "the answers sent and the result")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    available = {p.name: p for p in sorted(CASES_DIR.iterdir()) if (p / "client.json").exists()}
    available["demo"] = DEMO_DIR
    chosen = args.case or list(available)
    unknown = [c for c in chosen if c not in available]
    if unknown:
        parser.error(f"unknown case {unknown}; choose from {sorted(available)}")

    from fastapi.testclient import TestClient
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from ledgersync.config import Settings
    from ledgersync.records import AgentRecords
    from ledgersync.store_mongo import MongoStore
    from server import create_app

    settings = dataclasses.replace(Settings.from_env(), warmup=False, mongodb_db_name=args.db)
    rows = PreparedRows() if args.read == "rows" else None
    store = MongoStore(settings.mongodb_uri, args.db, max_pool=settings.mongodb_max_pool)
    runs = []
    try:
        # the chat's own checkpoints, read on the store's one client; the thread is gone once the demo resets
        saver = MongoDBSaver(store.client, db_name=f"{store.db_name}_checkpoints") if args.transcripts else None
        if rows:
            rows.install()
        with TestClient(create_app(settings, store=store), headers={"X-LedgerSync": "1"}) as api:
            records = AgentRecords(store.db)
            for name in chosen:
                for n in range(1, args.runs + 1):
                    try:
                        result = run_case(api, store, records, available[name], rows, settings.openrouter_model, run=n,
                                          transcripts=args.transcripts, saver=saver, label=name)
                    except Exception as exc:   # a case that can't run is a failed run, not the end of the eval
                        result = {"case": name, "model": settings.openrouter_model, "seconds": 0,
                                  "client_id": None, "thread_id": None,
                                  **{s: {"passed": False, "differences": []} for s in
                                     ("trial_balance", "decisions", "questions")},
                                  "problems": [f"the run failed: {type(exc).__name__}: {exc}"], "posted_problems": [],
                                  "steps": 0, "failed_steps": [], "error_events": [], "refused_decisions": [],
                                  "answers_not_applied": [], "row_fallbacks": [], "unmatched_names": []}
                    result["run"] = n
                    runs.append(result)
                    print(f"{name} run {n}: " + ("passed" if passed(result) else "FAILED"), flush=True)
    finally:
        if rows and rows._analyze:
            rows.uninstall()
        store.close()

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{dt.date.today().isoformat()}-agent.json"
    out.write_text(json.dumps({"date": dt.date.today().isoformat(), "read": args.read,
                               "model": settings.openrouter_model, "runs": runs}, indent=2, ensure_ascii=False) + "\n")
    print("\n" + table(runs) + f"\n\nWrote {out.relative_to(ROOT)}"
          + (f"\nTranscripts in {args.transcripts}" if args.transcripts else ""))
    return 0 if all(passed(r) for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
