"""Runs a hand-worked agent case (eval/agent_cases/<case>/, or the demo in demo/northbridge/) through the accountant
chat's services with no model, as the chat would run if the agent made exactly the case's decisions.
tests/test_agent_cases.py compares what it returns with the figures the case's notes.md works out by hand.

The review turn: the client is added (the demo client is reset instead), and each file in documents/ is kept as
its original and added with the rows its <file>.rows.json gives, so no model reads it. The resolutions in
expected_decisions.json are applied in order through resolutions.resolve, each evidence quote checked against the
real file's text. Then record_automatic records what matching dated from the bank, the questions are worked out and
the year is posted.

The answers: those in the "Answers" section of notes.md are applied in order. A date, "I don't have it" or "Not sure"
goes through questions.answer. An uploaded document is added as the chat's document route adds it: its rows, then
the questions worked out again and the year posted. Then the questions are worked out and the year posted once more.

Rows are named by their file and description, which are unique within a case."""
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter

from job_scoring import net_by_account
from ledgersync import demo, documents, ledger, ledger_book, questions
from ledgersync.blobs import BlobStore, GridFSBlobStore
from ledgersync.models import ClientFields, Decision, Evidence, Transaction
from ledgersync.records import AgentRecords
from ledgersync.resolutions import Resolution, record_automatic, resolve
from ledgersync.store_mongo import MongoStore
from ledgersync.years import year_bounds

ACTOR = "agent:scripted"   # who the case's resolutions are recorded as made by
_RESOLUTION = TypeAdapter(Resolution)
_ANSWER = TypeAdapter(questions.Answer)
_ANSWERS = re.compile(r"^## Answers\n.*?```json\n(.*?)```", re.MULTILINE | re.DOTALL)


@dataclass
class Stage:
    """The books at one point of the run: the posted trial balance as each account's net (debit minus credit, so a
    credit is negative; accounts that net to nothing left out), the open and waiting questions as
    expected_questions.json lists them, and why the year couldn't be posted or its trial balance worked out."""
    trial_balance: dict[str, Decimal]
    questions: list[dict]
    problems: list[str]


@dataclass
class CaseResult:
    """What a case's run decided, and the books it left after the review turn and after the answers."""
    client_id: int
    year_start: dt.date
    resolutions: list[Decision]   # one for each of the case's resolutions, in order, applied or refused
    automatic: list[dict]         # the decisions record_automatic made, as expected_decisions.json lists them
    from_answers: list[dict]      # the decisions the answers made, likewise
    review: Stage                 # after the review turn
    answered: Stage               # after the answers


def _names(store: MongoStore, client_id: int) -> dict[int, dict]:
    """Each row's name, by its id: its upload's file name and its description."""
    files = {u["id"]: u["name"] for u in store.uploads(client_id)}
    return {r.id: {"file": files[r.upload_id], "description": r.tx.description} for r in store.rows(client_id)}


def _row_id(store: MongoStore, client_id: int, name: dict) -> int:
    found = [n for n, named in _names(store, client_id).items() if named == name]
    if len(found) != 1:
        raise LookupError(f"{len(found)} rows are named {name}, not one.")
    return found[0]


def _add_document(store: MongoStore, blobs: BlobStore, client_id: int, year_start: dt.date, path: Path) -> None:
    """Keeps the file and adds it with the rows its .rows.json gives, to the year, as the chat adds a file it read."""
    read = json.loads(path.with_name(f"{path.name}.rows.json").read_text())
    sha256 = blobs.put(path.read_bytes(), name=path.name,
                       content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    store.add_upload(client_id, path.name, read["kind"], [Transaction.model_validate(t) for t in read["transactions"]],
                     sha256=sha256, bank_account=read["bank_account"], year_start=year_start)


def _documents(case_dir: Path) -> list[Path]:
    """The case's files, by name, without their .rows.json or hidden files such as .DS_Store."""
    return sorted(p for p in (case_dir / "documents").iterdir()
                  if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".rows.json"))


# The arguments of each action, with its rows named as expected_decisions.json names them, as a Resolution takes them.
_ARGUMENTS = {
    "keep_one": lambda a, row_id: {"keep_row_id": row_id(a["keep"]), "drop_row_ids": [row_id(r) for r in a["drop"]]},
    "use_primary": lambda a, row_id: {"primary_row_id": row_id(a["primary"]), "other_row_id": row_id(a["other"])},
    "split_vat": lambda a, row_id: {"parts": a["parts"]},
    "set_vat_from_document": lambda a, row_id: {"vat": a["vat"]},
}


def _resolve(store: MongoStore, records: AgentRecords, blobs: BlobStore, client_id: int, step: dict) -> Decision:
    """Applies one of the case's resolutions, quoting the real files: their text as documents.text_of reads it."""
    uploads = {u["id"]: u for u in store.uploads(client_id)}
    by_name = {u["name"]: n for n, u in uploads.items()}

    def row_id(name: dict) -> int:
        return _row_id(store, client_id, name)

    resolution = _RESOLUTION.validate_python({"action": step["action"],
                                              **_ARGUMENTS[step["action"]](step["arguments"], row_id)})
    return resolve(store, records, client_id=client_id, thread_id=None, actor=ACTOR, row_id=row_id(step["row"]),
                   resolution=resolution, reason=step["reason"],
                   evidence=[Evidence(upload_id=by_name[e["file"]], quote=e["quote"]) for e in step["evidence"]],
                   texts=lambda upload_id: documents.text_of(uploads[upload_id], blobs, records))


def _described(decision: Decision, names: dict[int, dict]) -> dict:
    """A decision that dated a row, as expected_decisions.json lists it."""
    [row_id] = decision.row_ids
    described = {"action": decision.action, "rule": decision.rule, "actor": decision.actor, "row": names[row_id],
                 "date": decision.after[str(row_id)]["date"]}
    if decision.evidence:
        described["evidence"] = [{"file": e.upload_name, "quote": e.quote} for e in decision.evidence]
    return described


def answers(case_dir: Path) -> list[dict]:
    """The answers in the "Answers" section of the case's notes.md, in order."""
    found = _ANSWERS.search((case_dir / "notes.md").read_text())
    if found is None:
        raise ValueError(f"{case_dir.name}/notes.md has no Answers section with a JSON list.")
    return json.loads(found.group(1))


def _answer(store: MongoStore, records: AgentRecords, blobs: BlobStore, case_dir: Path, client_id: int,
            year_start: dt.date, item: dict) -> None:
    """Answers the open question of the item's kind on its row: an uploaded document as the chat's document route
    adds it, anything else through questions.answer."""
    asked, given = item["question"], item["answer"]
    row_id = _row_id(store, client_id, asked["row"])
    question = next((q for q in records.questions(client_id, year_start)
                     if q.kind == asked["kind"] and q.row_ids[:1] == [row_id]), None)
    if question is None:
        raise LookupError(f"No {asked['kind']} question is open on {asked['row']}.")
    if given["kind"] == "upload":
        _add_document(store, blobs, client_id, year_start, case_dir / given["file"])
        questions.refresh(store, records, client_id, year_start)
        ledger_book.post(store, records, client_id, year_start)
    else:
        questions.answer(store, records, client_id=client_id, thread_id=None, question_id=question.id,
                         answer=_ANSWER.validate_python(given))


def _stage(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date) -> Stage:
    """Works the questions out and posts the year, as the end of a chat turn does; then the books as they stand."""
    questions.refresh(store, records, client_id, year_start)
    posted = ledger_book.post(store, records, client_id, year_start)
    tb = ledger_book.posted_trial_balance(store, records, client_id, year_start)
    names = _names(store, client_id)
    asked = [{"kind": q.kind, "row": names[q.row_ids[0]] if q.row_ids else None, "status": q.status,
              **({"answer": q.answer} if q.answer is not None else {})}
             for q in records.questions(client_id, year_start)]
    return Stage(trial_balance=net_by_account(tb.model_dump()), questions=asked, problems=posted.problems + tb.problems)


def _client(case_dir: Path, store: MongoStore, records: AgentRecords) -> int:
    """The case's client, added as POST /api/clients adds it; the demo client reset as the demo starts."""
    if case_dir.resolve() == demo.DEMO_DIR:
        return demo.reset(store, records, store.client[f"{store.db_name}_checkpoints"])
    fields = ClientFields.model_validate(json.loads((case_dir / "client.json").read_text()))
    return ledger.add_client(store, fields).id


def run(case_dir: Path, store: MongoStore, records: AgentRecords, blobs: Optional[BlobStore] = None) -> CaseResult:
    """The case run through the services, on the client it adds to the store: the decisions made, and the books after
    the review turn and after the answers. blobs: where the original files are kept, beside the rows by default."""
    case_dir = Path(case_dir)
    blobs = blobs or GridFSBlobStore(store.db)
    expected = json.loads((case_dir / "expected_decisions.json").read_text())
    client_id = _client(case_dir, store, records)
    year_start = year_bounds(store.get_client(client_id).first_year_end, 0)[0]

    for path in _documents(case_dir):
        _add_document(store, blobs, client_id, year_start, path)
    resolved = [_resolve(store, records, blobs, client_id, step) for step in expected["resolutions"]]
    automatic = record_automatic(store, records, client_id=client_id, year_start=year_start, thread_id=None)
    review = _stage(store, records, client_id, year_start)

    before = {d.id for d in records.decisions(client_id)}
    for item in answers(case_dir):
        _answer(store, records, blobs, case_dir, client_id, year_start, item)
    answered = _stage(store, records, client_id, year_start)

    names = _names(store, client_id)
    return CaseResult(client_id=client_id, year_start=year_start, resolutions=resolved,
                      automatic=[_described(d, names) for d in automatic],
                      from_answers=[_described(d, names) for d in records.decisions(client_id)
                                    if d.id not in before and d.status == "applied"],
                      review=review, answered=answered)
