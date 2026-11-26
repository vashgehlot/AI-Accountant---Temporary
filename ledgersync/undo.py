"""Taking back a decision a person doesn't want, and making one the background review only suggested. Neither changes
a stored decision: the log only grows. An undo is a decision of its own that reverses the first; an applied
suggestion is a new applied decision, and the change record says which suggestion it came from."""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import TypeAdapter

from . import questions, resolutions, upkeep
from .agent.locks import ClientLocks
from .errors import InvalidInput
from .ledger import ensure_open
from .models import ChangeDraft, Decision, DecisionDraft
from .records import AgentRecords
from .resolutions import Resolution, Texts
from .store_mongo import MongoStore

logger = logging.getLogger(__name__)
_NUMBERS = {"gross", "vat"}


def _same(field: str, now, wanted) -> bool:
    if field in _NUMBERS and now is not None and wanted is not None:
        try:
            return Decimal(str(now)) == Decimal(str(wanted))
        except InvalidOperation:
            pass
    return now == wanted


def _restore(store, records, client_id, key, was_rejected, saved, rows, uploads) -> None:
    """Puts back what a failed undo changed. Never raises: the failure that called it is what gets reported."""
    for step in (lambda: store.restore_rows(client_id, rows, uploads),
                 lambda: store.put_row_data(client_id, saved),
                 lambda: None if was_rejected else records.unreject_key(client_id, key)):
        try:
            step()
        except Exception:   # noqa: BLE001 - best effort; the rest is still put back
            logger.exception("Couldn't put back client %s's rows after a failed undo", client_id)


def undo_decision(store: MongoStore, records: AgentRecords, locks: ClientLocks, *, client_id: int,
                  decision_id: str, wait: int = 20) -> Decision:
    """Puts back what an applied decision changed and records the reversal. InvalidInput when the decision isn't the
    client's, isn't applied, was undone already, or a row it changed has changed since (the person changes it by
    hand then). The change is remembered, so neither the chat nor the review makes it again. wait: seconds before the
    background review of the undo starts."""
    d = records.decision(client_id, decision_id)
    if d is None:
        raise InvalidInput("This decision was not found.")
    if d.status != "applied" or d.action == "undo":
        raise InvalidInput("Only a change that was made can be undone.")
    if records.reversal_of(client_id, decision_id) is not None:
        raise InvalidInput("This change was undone already.")
    key = records.decision_key(client_id, decision_id) or ""
    if d.action == "close_question":
        undone = _undo_close(records, locks, client_id, d, key)
    else:
        undone = _undo_rows(store, records, locks, client_id, d, key)
    upkeep.after_change(store, records, locks, ChangeDraft(
        client_id=client_id, year_start=d.year_start, actor="user", kind="decision_undone", row_ids=d.row_ids,
        before=d.after, after={"decision_id": decision_id}, summary=f"Undid {d.rule} (rows {', '.join(map(str, d.row_ids))})"), wait=wait)
    return undone


def _undone(records: AgentRecords, d: Decision) -> Decision:
    """Records the decision that reverses d."""
    return records.append_decision(DecisionDraft(
        client_id=d.client_id, year_start=d.year_start, action="undo", rule=f"Undo: {d.rule}",
        status="applied", row_ids=d.row_ids, reason=f"A person undid {d.rule}.", before=d.after,
        after=d.before, actor="user", reverses=d.id), f"undo|{d.id}")[0]


def _undo_close(records: AgentRecords, locks: ClientLocks, client_id: int, d: Decision, key: str) -> Decision:
    """Reopens the question a close_question decision closed, to the status it had, and remembers that a person
    reopened it, so the AI doesn't close it again. If the undo fails before its decision is written the question is
    put back as it was closed. InvalidInput when the question has changed since (it was answered or reopened)."""
    q = records.question(key.split("|")[1]) if key.startswith("close|") else None
    if q is None or q.client_id != client_id or q.status != "resolved" \
            or not (q.answer or "").startswith(questions.CLOSED_BY_THE_AI):
        raise InvalidInput("The question has changed since; leave it as it is.")
    with locks.hold(client_id):
        was_rejected = records.is_rejected(client_id, key)
        written = False
        try:
            records.set_question(q.id, d.before["question"]["status"], d.before["question"].get("answer"))
            records.reject_key(client_id, key)
            undone = _undone(records, d)
            written = True
            return undone
        except Exception:
            if not written:
                for step in (lambda: records.set_question(q.id, "resolved", q.answer),
                             lambda: None if was_rejected else records.unreject_key(client_id, key)):
                    try:
                        step()
                    except Exception:   # noqa: BLE001 - best effort; the rest is still put back
                        logger.exception("Couldn't put back question %s after a failed undo", q.id)
            raise


def _undo_rows(store: MongoStore, records: AgentRecords, locks: ClientLocks, client_id: int, d: Decision,
               key: str) -> Decision:
    """Puts back the rows a decision changed (and removes the parts it made), and records the reversal."""
    with locks.hold(client_id):
        rows = {r.id: r.tx for r in store.rows(client_id)}
        # A closed year's rows are locked: neither the rows as they are nor the dates they would go back to.
        days = [rows[int(n)].date for n in d.before if n.isdigit() and int(n) in rows]
        days += [dt.date.fromisoformat(v["date"]) for v in d.before.values() if isinstance(v, dict) and v.get("date")]
        ensure_open(store.get_client(client_id), days, d.year_start)
        for n, wanted in d.after.items():
            tx = rows.get(int(n)) if n.isdigit() else None
            if tx is not None and tx.removed:   # a person's Remove is theirs: only their Put back books it again
                raise InvalidInput(f"Row {n} was removed by a person; put it back by hand instead.")
            now = tx.model_dump(mode="json") if tx else {}
            if tx is None or not all(_same(f, now.get(f), v) for f, v in wanted.items()):
                raise InvalidInput(f"Row {n} has changed since; change it by hand instead.")
        touched = [int(n) for n in d.before]
        parts = [int(n) for n in d.after if n not in d.before]
        saved = store.row_data(client_id, touched)
        kept_rows, kept_uploads = store.raw_rows(client_id, parts)
        was_rejected = records.is_rejected(client_id, key)
        # The undo decision is the commit point: it is written last, and a failure in this process before it is
        # written puts everything back (the rows, the parts, the rejected key). A crash of the process between
        # reject_key and the decision is not covered.
        # written: set once append_decision returns. A failure inside it after its insert (recording its change)
        # still runs the restore; that gap is parked.
        written = False
        try:
            for n, values in d.before.items():
                store.patch_row(client_id, int(n), dict(values))
            for n in parts:
                store.delete_row(client_id, n)
            records.reject_key(client_id, key)
            undone = _undone(records, d)
            written = True
        except Exception:
            if not written:
                _restore(store, records, client_id, key, was_rejected, saved, kept_rows, kept_uploads)
            raise
    return undone


def apply_suggestion(store: MongoStore, records: AgentRecords, locks: ClientLocks, *, client_id: int,
                     decision_id: str, texts: Texts, wait: int = 20) -> Decision:
    """Makes a suggested decision as the person: the stored resolution and evidence go through resolve again, which
    checks them against the rows as they are now. Returns the new decision, which is refused if they no longer hold.
    InvalidInput when the decision isn't the client's suggestion, or was applied already."""
    d = records.decision(client_id, decision_id)
    if d is None or d.status != "suggested" or d.resolution is None:
        raise InvalidInput("This is not a suggestion.")
    if decision_id in records.applied_suggestions(client_id):
        raise InvalidInput("This suggestion was applied already.")
    if d.resolution.get("action") == "close_question":
        with locks.hold(client_id):
            made = questions.close(
                store, records, client_id=client_id, year_start=d.year_start, question_id=d.resolution["question_id"],
                reason=d.resolution["reason"], evidence=d.evidence, texts=texts, actor="user", trigger="background",
                review_id=d.review_id, suggest=False)
    else:
        resolution = TypeAdapter(Resolution).validate_python(d.resolution)
        with locks.hold(client_id):
            made = resolutions.resolve(
                store, records, client_id=client_id, thread_id=d.thread_id, actor="user", row_id=d.row_ids[0],
                resolution=resolution, evidence=d.evidence, reason=d.reason, texts=texts, trigger="background",
                review_id=d.review_id, suggest=False)
    if made.status == "applied":
        upkeep.after_change(store, records, locks, ChangeDraft(
            client_id=client_id, year_start=made.year_start, actor="user", kind="decision_applied",
            row_ids=made.row_ids, after={"decision_id": decision_id, "applied_as": made.id},
            summary=f"Applied the suggestion: {made.rule} (rows {', '.join(map(str, made.row_ids))})"), wait=wait)
    return made
