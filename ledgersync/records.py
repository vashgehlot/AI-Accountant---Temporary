"""What the accountant chat keeps beyond the books: the decisions log, the questions it asks, the chat threads and
the texts read from documents. They live in their own collections of the database it is given, next to the clients."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Literal, Optional, get_args
from uuid import uuid4

import pymongo
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, OperationFailure

from .errors import NotFound
from .models import (Change, ChangeDraft, ChatThread, Decision, DecisionDraft, Offer, Question, QuestionDraft, ReviewRun,
                     ReviewState)
from .rows import now_iso

# What a document keeps besides its model: the idempotency key or question key it is found by, `seq`, the time in
# nanoseconds it was added, which orders records that were added in the same second, a thread's turns, and the last
# summary an older thread kept in their place.
_KEPT_APART = ("_id", "idempotency_key", "key", "seq", "turns", "summary")
# Leaves a thread's turns out of a read: they hold every result the chat gave, so only turns() reads them.
_WITHOUT_TURNS = {"turns": 0}


def _model(cls, doc: dict):
    return cls.model_validate({k: v for k, v in doc.items() if k not in _KEPT_APART})


def _run(doc: dict) -> ReviewRun:
    """A review run: unlike _model, this keeps `summary`, which is the run's own."""
    return ReviewRun.model_validate({k: v for k, v in doc.items() if k not in ("_id", "seq")})


def _hash(prev_hash: str, decision: Decision) -> str:
    """The SHA-256 of the previous hash and the decision's canonical JSON (sorted keys, no spaces, no hash)."""
    # trigger, review_id and resolution joined the decision after hashes were first made: left out while at their
    # defaults, so earlier decisions (and new chat ones) hash exactly as they did.
    left_out = {"hash"}
    if decision.trigger == "chat":
        left_out.add("trigger")
    if decision.review_id is None:
        left_out.add("review_id")
    if decision.resolution is None:
        left_out.add("resolution")
    body = json.dumps(decision.model_dump(mode="json", exclude=left_out), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


class AgentRecords:
    def __init__(self, db: Database):
        """The records on `db`, which is the one the app's client already opened: this never makes a client."""
        self.db = db
        db.decisions.create_index([("client_id", pymongo.ASCENDING), ("year_start", pymongo.ASCENDING)])
        try:   # an older database has a unique index on the key alone, which would stop two clients using one key
            db.decisions.drop_index("idempotency_key_1")
        except OperationFailure:
            pass
        db.decisions.create_index([("client_id", pymongo.ASCENDING), ("idempotency_key", pymongo.ASCENDING)],
                                  unique=True)
        db.questions.create_index([("client_id", pymongo.ASCENDING), ("key", pymongo.ASCENDING)], unique=True)
        db.chat_threads.create_index([("client_id", pymongo.ASCENDING), ("updated_at", pymongo.ASCENDING)])
        db.changes.create_index([("client_id", pymongo.ASCENDING), ("seq", pymongo.ASCENDING)])
        db.changes.create_index([("client_id", pymongo.ASCENDING), ("actor", pymongo.ASCENDING),
                                 ("kind", pymongo.ASCENDING)])
        db.decisions.create_index([("client_id", pymongo.ASCENDING), ("reverses", pymongo.ASCENDING)])
        db.review_runs.create_index([("client_id", pymongo.ASCENDING), ("seq", pymongo.ASCENDING)])
        db.review_state.create_index("client_id", unique=True)
        db.review_rejected.create_index([("client_id", pymongo.ASCENDING), ("key", pymongo.ASCENDING)], unique=True)

    # ─── Decisions ─────────────────────────────────────────────────────────────

    def append_decision(self, d: DecisionDraft, idempotency_key: str,
                        id: Optional[str] = None) -> tuple[Decision, bool]:
        """Adds the decision to its client's chain and says it is new. Keys are per client: given a key the client already used, it adds nothing
        and returns the decision stored under it with False, so a retried tool call decides only once. Two
        appends racing for one client may both chain from the same previous decision; the log is not locked.
        id: the decision's id when its maker needed it before adding it (a split names the decision that
        replaced the row); a new one otherwise."""
        stored = self.decision_by_key(d.client_id, idempotency_key)
        if stored:
            return stored, False
        latest = self.db.decisions.find_one({"client_id": d.client_id}, sort=[("seq", pymongo.DESCENDING)])
        prev_hash = latest["hash"] if latest else ""
        decision = Decision(**d.model_dump(), id=id or uuid4().hex, created_at=now_iso(), prev_hash=prev_hash, hash="")
        decision.hash = _hash(prev_hash, decision)
        doc = {**decision.model_dump(mode="json"), "_id": decision.id, "idempotency_key": idempotency_key,
               "seq": time.time_ns()}
        try:
            self.db.decisions.insert_one(doc)
        except DuplicateKeyError:   # the same key was added meanwhile
            stored = self.decision_by_key(d.client_id, idempotency_key)
            if stored is None:   # not the key: the id is taken
                raise
            return stored, False
        self.add_change(ChangeDraft(
            client_id=decision.client_id, year_start=decision.year_start, actor=decision.actor, kind="decision",
            row_ids=decision.row_ids, after={"decision_id": decision.id}, summary=f"{decision.rule}: {decision.status}"))
        return decision, True

    def decision_by_key(self, client_id: int, idempotency_key: str) -> Optional[Decision]:
        """The client's decision stored under the key, if any."""
        doc = self.db.decisions.find_one({"client_id": client_id, "idempotency_key": idempotency_key})
        return _model(Decision, doc) if doc else None

    def decision(self, client_id: int, decision_id: str) -> Optional[Decision]:
        """The client's decision with the id, if any."""
        doc = self.db.decisions.find_one({"client_id": client_id, "_id": decision_id})
        return _model(Decision, doc) if doc else None

    def decisions_by_ids(self, client_id: int, ids) -> list[Decision]:
        """The client's decisions with these ids (one query), in the order of the ids; others are left out."""
        found = {doc["_id"]: _model(Decision, doc)
                 for doc in self.db.decisions.find({"client_id": client_id, "_id": {"$in": list(ids)}})}
        return [found[i] for i in ids if i in found]

    def reversal_of(self, client_id: int, decision_id: str) -> Optional[Decision]:
        """The client's decision that reverses the one given, if any."""
        doc = self.db.decisions.find_one({"client_id": client_id, "reverses": decision_id})
        return _model(Decision, doc) if doc else None

    def decision_key(self, client_id: int, decision_id: str) -> Optional[str]:
        """The idempotency key the client's decision was stored under (a decision's own model leaves it out)."""
        doc = self.db.decisions.find_one({"client_id": client_id, "_id": decision_id}, {"idempotency_key": 1})
        return doc["idempotency_key"] if doc else None

    def decisions(self, client_id: int, year_start: Optional[dt.date] = None,
                  since: Optional[str] = None) -> list[Decision]:
        """The client's decisions, oldest first; of one year, and made at or after `since` (an ISO time), if given."""
        query: dict = {"client_id": client_id}
        if year_start:
            query["year_start"] = year_start.isoformat()
        if since:
            query["created_at"] = {"$gte": since}
        return [_model(Decision, doc) for doc in self.db.decisions.find(query).sort("seq", pymongo.ASCENDING)]

    # ─── Changes ───────────────────────────────────────────────────────────────

    def add_change(self, c: ChangeDraft) -> Change:
        """Adds the change to the client's record of changes, which is only ever added to."""
        change = Change(**c.model_dump(), id=uuid4().hex, seq=time.time_ns(), created_at=now_iso())
        self.db.changes.insert_one({**change.model_dump(mode="json"), "_id": change.id})
        return change

    def changes(self, client_id: int, *, year_start: Optional[dt.date] = None, since: Optional[str] = None,
                limit: int = 200) -> list[Change]:
        """The client's latest `limit` changes, oldest first; of one year and those with no year, and made after
        `since` (an ISO time), if given."""
        query: dict = {"client_id": client_id}
        if year_start:
            query["year_start"] = {"$in": [year_start.isoformat(), None]}
        if since:
            query["created_at"] = {"$gt": since}
        docs = list(self.db.changes.find(query).sort("seq", pymongo.DESCENDING).limit(limit))
        # a change keeps its own seq and summary, which _model would set apart
        return [Change.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in reversed(docs)]

    def changes_after(self, client_id: int, seq: int, *, year_start: Optional[dt.date] = None) -> list[Change]:
        """Every change of the client with a seq above `seq`, ordered by (seq, id); of one year and those with no
        year, if given."""
        query: dict = {"client_id": client_id, "seq": {"$gt": seq}}
        if year_start:
            query["year_start"] = {"$in": [year_start.isoformat(), None]}
        docs = self.db.changes.find(query).sort([("seq", pymongo.ASCENDING), ("_id", pymongo.ASCENDING)])
        return [Change.model_validate({k: v for k, v in doc.items() if k != "_id"}) for doc in docs]

    def person_rows(self, client_id: int) -> set[int]:
        """The rows a person changed: those named by one of their edits, links, inclusions, not-the-sames, reverts or
        hand entries in the record of changes."""
        kinds = ["row_edited", "row_linked", "row_included", "rows_apart", "row_reverted", "row_added"]
        return {n for c in self.db.changes.find({"client_id": client_id, "actor": "user", "kind": {"$in": kinds}},
                                                {"row_ids": 1}) for n in c.get("row_ids", [])}

    def applied_suggestions(self, client_id: int) -> dict[str, str]:
        """The client's suggestions that were applied: the suggestion's decision id, and the applied decision's id."""
        return {c["after"]["decision_id"]: c["after"]["applied_as"]
                for c in self.db.changes.find({"client_id": client_id, "kind": "decision_applied"})
                if c.get("after", {}).get("applied_as")}

    # ─── Questions ─────────────────────────────────────────────────────────────

    def upsert_question(self, q: QuestionDraft, key: str) -> Question:
        """Asks the question, once per key for each client: asked again, it takes the new kind, year, text,
        reason and rows (a held row can change its year or its kind of document) and keeps its id, its status and any
        answer."""
        new_id = uuid4().hex
        fresh = {**q.model_dump(mode="json", exclude={"kind", "year_start", "text", "why", "row_ids"}), "_id": new_id, "id": new_id,
                 "status": "open", "answer": None, "created_at": now_iso(), "resolved_at": None,
                 "seq": time.time_ns()}
        update = {"$set": {"kind": q.kind, "year_start": q.year_start.isoformat(), "text": q.text, "why": q.why,
                           "row_ids": q.row_ids}, "$setOnInsert": fresh}
        where = {"client_id": q.client_id, "key": key}
        # An answer offered for other words (another amount to release, say) no longer fits the question.
        self.db.questions.update_one({**where, "text": {"$ne": q.text}, "offer": {"$exists": True}},
                                     {"$unset": {"offer": ""}})
        try:
            doc = self.db.questions.find_one_and_update(where, update, upsert=True,
                                                        return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:   # another asker inserted it between the find and the insert: update theirs
            doc = self.db.questions.find_one_and_update(where, update, return_document=ReturnDocument.AFTER)
        return _model(Question, doc)

    def question(self, id: str) -> Optional[Question]:
        """The question with this id, in any status, if there is one."""
        doc = self.db.questions.find_one({"id": id})
        return _model(Question, doc) if doc else None

    def questions_by_ids(self, client_id: int, ids) -> list[Question]:
        """The client's questions with these ids (one query), in the order of the ids; others are left out."""
        found = {doc["id"]: _model(Question, doc)
                 for doc in self.db.questions.find({"client_id": client_id, "id": {"$in": list(ids)}})}
        return [found[i] for i in ids if i in found]

    def questions(self, client_id: int, year_start: Optional[dt.date],
                  statuses: tuple[str, ...] = ("open", "waiting")) -> list[Question]:
        """The client's questions for the year (every year when None) in these statuses, oldest first."""
        query: dict = {"client_id": client_id, "status": {"$in": list(statuses)}}
        if year_start is not None:
            query["year_start"] = year_start.isoformat()
        return [_model(Question, doc) for doc in self.db.questions.find(query).sort("seq", pymongo.ASCENDING)]

    def set_question(self, id: str, status: str, answer: Optional[str] = None) -> Question:
        """Moves the question to the status, with the person's answer; resolved sets the time it was. An answer
        offered for it goes: the person has answered, or said they can't yet."""
        changes = {"status": status, "answer": answer, "resolved_at": now_iso() if status == "resolved" else None}
        doc = self.db.questions.find_one_and_update({"id": id}, {"$set": changes, "$unset": {"offer": ""}},
                                                    return_document=ReturnDocument.AFTER)
        if not doc:
            raise NotFound("This question was not found.")
        return _model(Question, doc)

    def set_offer(self, id: str, offer: Offer) -> Question:
        """Keeps an answer offered for the question, in place of any offered before."""
        doc = self.db.questions.find_one_and_update(
            {"id": id}, {"$set": {"offer": offer.model_dump(mode="json", by_alias=True)}},
            return_document=ReturnDocument.AFTER)
        if not doc:
            raise NotFound("This question was not found.")
        return _model(Question, doc)

    def clear_offer(self, id: str) -> None:
        self.db.questions.update_one({"id": id}, {"$unset": {"offer": ""}})

    def set_question_why(self, id: str, why: str) -> Question:
        """Says why the question is still asked; the rules' next refresh puts their own reason back."""
        doc = self.db.questions.find_one_and_update({"id": id}, {"$set": {"why": why}},
                                                    return_document=ReturnDocument.AFTER)
        if not doc:
            raise NotFound("This question was not found.")
        return _model(Question, doc)

    # ─── Chat threads ──────────────────────────────────────────────────────────

    def create_thread(self, client_id: int, year_start: dt.date, title: str) -> ChatThread:
        now = now_iso()
        thread = ChatThread(id=uuid4().hex, client_id=client_id, year_start=year_start, title=title,
                            created_at=now, updated_at=now)
        self.db.chat_threads.insert_one({**thread.model_dump(mode="json"), "_id": thread.id})
        return thread

    def threads(self, client_id: Optional[int] = None) -> list[ChatThread]:
        """The threads, of one client if given, the most recently used first."""
        query = {} if client_id is None else {"client_id": client_id}
        return [_model(ChatThread, doc) for doc in self.db.chat_threads.find(query, _WITHOUT_TURNS).sort(
            [("updated_at", pymongo.DESCENDING), ("_id", pymongo.ASCENDING)])]

    def thread(self, id: str) -> Optional[ChatThread]:
        doc = self.db.chat_threads.find_one({"_id": id}, _WITHOUT_TURNS)
        return _model(ChatThread, doc) if doc else None

    def touch_thread(self, id: str, title: Optional[str] = None) -> ChatThread:
        """Marks the thread as used now, and retitles it if given a title."""
        changes = {"updated_at": now_iso(), **({"title": title} if title is not None else {})}
        doc = self.db.chat_threads.find_one_and_update({"_id": id}, {"$set": changes}, projection=_WITHOUT_TURNS,
                                                       return_document=ReturnDocument.AFTER)
        if not doc:
            raise NotFound("This chat was not found.")
        return _model(ChatThread, doc)

    def add_turn(self, thread_id: str, turn: dict) -> None:
        """Keeps the turn (as JSON) after the thread's earlier ones: the id of the person's message, the files it
        carried and the result its turn ended with."""
        self.db.chat_threads.update_one({"_id": thread_id}, {"$push": {"turns": turn}})

    def turns(self, thread_id: str) -> list[dict]:
        """The thread's turns as JSON, oldest first; none before its first (or for a chat saved before turns were
        kept)."""
        doc = self.db.chat_threads.find_one({"_id": thread_id}, {"turns": 1})
        return list(doc.get("turns") or []) if doc else []

    def delete_thread(self, id: str) -> None:
        """Removes the thread's record; what else was kept for it is removed by whoever kept it."""
        self.db.chat_threads.delete_one({"_id": id})

    # ─── Document texts ────────────────────────────────────────────────────────

    def document_text(self, sha256: str) -> Optional[list[str]]:
        """The pages of text read from the document with this hash, or None if it was not read before."""
        doc = self.db.document_texts.find_one({"_id": sha256})
        return list(doc["pages"]) if doc else None

    def save_document_text(self, sha256: str, pages: list[str], method: str, model: str) -> None:
        self.db.document_texts.update_one(
            {"_id": sha256}, {"$set": {"pages": list(pages), "method": method, "model": model,
                                       "created_at": now_iso()}}, upsert=True)

    # ─── Background reviews ────────────────────────────────────────────────────

    def review_state(self, client_id: int) -> ReviewState:
        """Where the client's background review stands; a client never reviewed is at the start."""
        doc = self.db.review_state.find_one({"client_id": client_id})
        return ReviewState.model_validate({k: v for k, v in doc.items() if k != "_id"}) if doc \
            else ReviewState(client_id=client_id)

    def set_review_state(self, state: ReviewState) -> None:
        self.db.review_state.replace_one({"client_id": state.client_id}, state.model_dump(mode="json"), upsert=True)

    def patch_review_state(self, client_id: int, **fields) -> None:
        """Sets only these fields of the client's review state, so a write to one field (a change making the client
        due) never undoes another's (the worker marking it running)."""
        unknown = set(fields) - set(ReviewState.model_fields) - {"client_id"}
        if unknown:
            raise ValueError(f"Not review state fields: {sorted(unknown)}")
        self.db.review_state.update_one({"client_id": client_id}, {"$set": fields}, upsert=True)

    def claim_review(self, client_id: int) -> bool:
        """Marks the client's review running unless it is already, in one step; whether this call claimed it."""
        doc = self.db.review_state.find_one_and_update(
            {"client_id": client_id, "running": {"$ne": True}}, {"$set": {"running": True}})
        return doc is not None

    def due_review_states(self) -> list[ReviewState]:
        """The states of the clients with a review due (not yet whether the time has come)."""
        return [ReviewState.model_validate({k: v for k, v in doc.items() if k != "_id"})
                for doc in self.db.review_state.find({"due_at": {"$ne": None}})]

    def running_review_states(self) -> list[ReviewState]:
        return [ReviewState.model_validate({k: v for k, v in doc.items() if k != "_id"})
                for doc in self.db.review_state.find({"running": True})]

    def start_review(self, client_id: int, year_start: dt.date, *, from_seq: int, to_seq: int,
                     trigger_summary: str, looked_at=(), issues_seen=()) -> ReviewRun:
        """Records a run that has started, over the changes after from_seq up to to_seq, pointed at these rows and
        shown these issues."""
        run = ReviewRun(id=uuid4().hex, client_id=client_id, year_start=year_start, status="running",
                        started_at=now_iso(), trigger_summary=trigger_summary, from_seq=from_seq, to_seq=to_seq,
                        looked_at=list(looked_at), issues_seen=list(issues_seen))
        self.db.review_runs.insert_one({**run.model_dump(mode="json"), "_id": run.id, "seq": time.time_ns()})
        return run

    def finish_review(self, id: str, *, status: Literal["running", "done", "failed", "limited", "off"], decision_ids=(),
                      question_ids=(), summary: str = "", error: Optional[str] = None) -> ReviewRun:
        """Ends the run with its outcome and what it decided and asked."""
        if status not in get_args(ReviewRun.model_fields["status"].annotation):
            raise ValueError(f"Not a review status: {status!r}")
        changes = {"status": status, "finished_at": now_iso(), "decision_ids": list(decision_ids),
                   "question_ids": list(question_ids), "summary": summary, "error": error}
        doc = self.db.review_runs.find_one_and_update({"_id": id}, {"$set": changes},
                                                      return_document=ReturnDocument.AFTER)
        if not doc:
            raise NotFound("This review was not found.")
        return _run(doc)

    def reviews(self, client_id: int, *, year_start: Optional[dt.date] = None, limit: int = 50) -> list[ReviewRun]:
        """The client's runs, newest first; of one year if given."""
        query: dict = {"client_id": client_id}
        if year_start:
            query["year_start"] = year_start.isoformat()
        return [_run(doc) for doc in self.db.review_runs.find(query).sort("seq", pymongo.DESCENDING).limit(limit)]

    def runs_on(self, client_id: int, day: dt.date) -> int:
        """How many runs that started on the (UTC) day are done or failed: the ones that count against the limit."""
        return self.db.review_runs.count_documents({
            "client_id": client_id, "status": {"$in": ["done", "failed"]},
            "started_at": {"$regex": "^" + day.isoformat()}})

    def looked_at(self, client_id: int, year_start: dt.date) -> set[int]:
        """Every row id the year's earlier runs were pointed at."""
        found: set[int] = set()
        for doc in self.db.review_runs.find({"client_id": client_id, "year_start": year_start.isoformat()},
                                            {"looked_at": 1}):
            found.update(doc.get("looked_at") or [])
        return found

    def issues_seen(self, client_id: int, year_start: dt.date) -> set[str]:
        """Every issue the year's earlier runs that finished were shown, by key (reviews.issue_keys)."""
        found: set[str] = set()
        for doc in self.db.review_runs.find({"client_id": client_id, "year_start": year_start.isoformat(),
                                             "status": "done"}, {"issues_seen": 1}):
            found.update(doc.get("issues_seen") or [])
        return found

    def mark_reviews_seen(self, client_id: int) -> int:
        """Marks the client's finished runs seen, and says how many were not."""
        return self.db.review_runs.update_many(
            {"client_id": client_id, "status": "done", "seen": False}, {"$set": {"seen": True}}).modified_count

    def unseen_background_changes(self, client_id: int) -> int:
        """The applied and suggested decisions in the client's unseen done runs."""
        ids = [i for doc in self.db.review_runs.find({"client_id": client_id, "status": "done", "seen": False},
                                                     {"decision_ids": 1}) for i in doc.get("decision_ids") or []]
        return self.db.decisions.count_documents(
            {"client_id": client_id, "_id": {"$in": ids}, "status": {"$in": ["applied", "suggested"]}}) if ids else 0

    def reject_key(self, client_id: int, key: str) -> None:
        """Keeps the key of a change the person undid, so the review does not make it again."""
        self.db.review_rejected.update_one({"client_id": client_id, "key": key},
                                           {"$setOnInsert": {"created_at": now_iso()}}, upsert=True)

    def unreject_key(self, client_id: int, key: str) -> None:
        """Takes a key back out, when the undo that added it could not be finished."""
        self.db.review_rejected.delete_one({"client_id": client_id, "key": key})

    def is_rejected(self, client_id: int, key: str) -> bool:
        return self.db.review_rejected.count_documents({"client_id": client_id, "key": key}, limit=1) > 0
