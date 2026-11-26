"""The background AI review: once a client has been quiet for a while after a person changed its books, the agent
reviews what changed on its own. A change that needs a review makes the client due (note); the Worker runs the due
clients one at a time, and run() does one client's review: per open year, the agent is pointed at what changed and at
the issues no earlier review has looked at, the books are settled, and the run is recorded with what it decided and
asked. The watermark is the change `seq`; a change that arrives during a run leaves the client due, so one more run
follows."""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading
from typing import TYPE_CHECKING, Callable, Optional

from . import books, upkeep
from .agent.run import stream_turn
from .agent.tools import ChatContext, _to_look_at, family_of
from .errors import NotFound
from .models import Change, ChangeDraft, ReviewRun
from .records import AgentRecords

if TYPE_CHECKING:   # chat.py imports upkeep, which imports this module
    from .agent.chat import Chat
    from .config import Settings

logger = logging.getLogger(__name__)

RETRY_AFTER = dt.timedelta(minutes=10)
RETRY_SOON = dt.timedelta(minutes=1)   # after the database didn't answer for a few seconds
SOON_TEXT = " The review will try again in a minute."
# Said, once, to a run whose answer ran out of length while it thought: in the same conversation, so what it read stays.
NUDGE = ("Your last answer was cut off while you were thinking, before you did anything. Don't read more: settle each "
         "issue listed with resolve_issue now, or say in one line why it can't be settled.")
# The kinds of issue the AI has an action for (R1 set_date, R2 keep_one, R4 use_primary, R3 split_vat, R5 VAT from the
# document): only these start a run. A missing document, payroll or payout report is asked of the person by the rules.
AI_FAMILIES = {"date": ("date to settle", "dates to settle"),
               "duplicate": ("possible duplicate", "possible duplicates"),
               "conflict": ("disagreement between records", "disagreements between records"),
               "combined_vat": ("mixed-VAT row", "mixed-VAT rows"),
               "missing_vat": ("row with VAT not booked", "rows with VAT not booked")}
TICK_SECONDS = 2.0
LIMITED_NOTE = "AI review paused for today: limit reached"
NOTHING = "Nothing to change."
MAX_UNREVIEWED = 40   # issues a run's message names as not yet reviewed; the rest wait for the next run
MAX_UPLOAD_ROWS = 30   # rows a new file's line names
_DETAILS = ("vat_registered", "business_type", "first_year_end", "bank_accounts")
_NO_REVIEW = ("year_closed", "decision_applied", "question_closed")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(when: dt.datetime) -> str:
    return when.isoformat(timespec="seconds")


def _when(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text)


def triggers(change: ChangeDraft) -> bool:
    """Whether the change needs a review. Not the agent's own changes, those a chat turn made (it says so itself),
    the rules' own, closing a year or a question, applying a decision, a row's description alone, or a client's
    name, contact or review setting."""
    if change.actor.startswith("agent:") or change.actor == "rules" or change.in_chat:
        return False
    if change.kind in _NO_REVIEW:
        return False
    if change.kind == "row_edited" and all(k == "description" for k in change.after):
        return False
    if change.kind == "client_changed" and not any(k in _DETAILS for k in change.after):
        return False
    return True


def note(records: AgentRecords, change: ChangeDraft, *, now: dt.datetime, wait: int) -> None:
    """When the change needs a review, makes its client due `wait` seconds from now (a retry already waiting stays)."""
    if triggers(change):
        records.patch_review_state(change.client_id, due_at=_iso(now + dt.timedelta(seconds=wait)))


# ─── What the agent is told ────────────────────────────────────────────────────

_ROW_KINDS = ("row_edited", "row_added", "row_removed", "row_linked", "row_included", "rows_apart", "row_reverted")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def trigger_summary(changes: list[Change]) -> str:
    """"after 3 files were added and 2 rows were changed": one phrase for each group of kinds."""
    def count(kinds) -> list[Change]:
        return [c for c in changes if c.kind in kinds]

    phrases = []
    if found := count(("upload_read",)):
        phrases.append(f"{_plural(len(found), 'file was', 'files were')} added")
    if found := count(("upload_removed",)):
        phrases.append(f"{_plural(len(found), 'file was', 'files were')} removed")
    if found := count(("upload_bank_changed",)):
        phrases.append(f"the bank account of {_plural(len(found), 'file', 'files')} changed")
    if found := count(_ROW_KINDS):
        n = len({r for c in found for r in c.row_ids}) or len(found)
        phrases.append(f"{_plural(n, 'row was', 'rows were')} changed")
    if count(("client_changed",)):
        phrases.append("the client's details changed")
    if count(("opening_balances_changed",)):
        phrases.append("the opening balances changed")
    if found := count(("question_answered",)):
        phrases.append(f"{_plural(len(found), 'question was', 'questions were')} answered")
    if found := count(("decision_undone",)):
        phrases.append(f"{_plural(len(found), 'change was', 'changes were')} undone")
    if count(("year_reopened",)):
        phrases.append("the year was reopened")
    if found := count(("decision",)):
        phrases.append(f"{_plural(len(found), 'decision was', 'decisions were')} made")
    return "after " + " and ".join(phrases) if phrases else "after a change"


def issue_keys(row, held=None) -> list[tuple[str, str]]:
    """The row's issues the AI has an action for (AI_FAMILIES), each with its key, "row:code:digest": the same issue on
    the same row keeps its key, so a review isn't shown it twice; a new issue, or one whose message changed, gets a new
    key. held is accepted for the callers' sake: a missing document is the person's to send, not the AI's."""
    return [(f"{row.id}:{i.code}:{hashlib.sha1(i.message.encode()).hexdigest()[:8]}", f"{i.code}: {i.message}")
            for i in row.issues if i.severity != "info" and family_of(i.code) in AI_FAMILIES]


def issue_summary(codes: list[str]) -> str:
    """"for 2 dates to settle and 1 possible duplicate": what a run looks at, by kind."""
    counts: dict[str, int] = {}
    for code in codes:
        family = family_of(code)
        counts[family] = counts.get(family, 0) + 1
    kinds = [_plural(n, *AI_FAMILIES[family]) for family, n in counts.items()]
    return "for " + (", ".join(kinds[:-1]) + " and " + kinds[-1] if len(kinds) > 1 else kinds[0])


def _describe(row) -> str:
    when = row.date.isoformat() if row.date else "no date"
    return f"{row.description[:60]}, £{row.gross} {row.direction.value}, {when}"


def _message(changes: list[Change], unreviewed: list[tuple[object, str]], first: bool, summary: str,
             upload_rows: dict[int, list[int]], more: int, suggest: bool = False) -> str:
    lines = [f"Background review {summary}. These changes were made by people or imports since the last review:"]
    for c in changes:
        rows = c.row_ids or upload_rows.get(c.upload_id or -1, [])[:MAX_UPLOAD_ROWS]
        lines.append(f"- {c.summary}" + (f" (rows {', '.join(map(str, rows))})" if rows else ""))
    if unreviewed:
        lines.append("Issues no review has looked at yet:")
        for row, said in unreviewed:
            lines.append(f"- Row {row.id} ({_describe(row)}) {said}")
        if more:
            lines.append(f"- and {more} more: list_issues shows them all.")
    if first:
        lines.append("First review of this year: look at everything.")
    if suggest:
        lines.append("This client is on suggest-only: your resolutions are kept as suggestions and change nothing "
                     "until a person applies them. Suggest what the evidence supports, ask the person about what it "
                     "doesn't, and finish with one line saying what you suggest and that it waits for them. Never say "
                     "you made a change.")
    else:
        lines.append("Settle each issue the evidence supports, ask the person about what it doesn't, and finish with "
                     "one line saying what you did, or why nothing could be settled.")
    return "\n".join(lines)


# ─── One client's review ───────────────────────────────────────────────────────

def _noted_today(records: AgentRecords, client_id: int, status: str, day: dt.date) -> bool:
    return any(r.status == status and r.started_at.startswith(day.isoformat())
               for r in records.reviews(client_id, limit=50))


def _midnight_after(now: dt.datetime) -> dt.datetime:
    return dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time(), tzinfo=dt.timezone.utc)


def _open_years(chat: "Chat", client_id: int, today: dt.date) -> list[dt.date]:
    return [y.start for y in books.years_of(chat.store, client_id, today) if not y.closed]


def _quiet_run(records: AgentRecords, client_id: int, year: dt.date, seq: int, status: str, summary: str) -> ReviewRun:
    run = records.start_review(client_id, year, from_seq=seq, to_seq=seq, trigger_summary="")
    return records.finish_review(run.id, status=status, summary=summary)


def run(chat: "Chat", client_id: int, *, now: dt.datetime) -> list[ReviewRun]:
    """Reviews the client: one run for each open year with changes that need one since the last review. Returns the
    runs recorded. See the module's note for what happens to the client's mark, due time and retry."""
    records, store, settings = chat.records, chat.store, chat.settings
    state = records.review_state(client_id)
    new = records.changes_after(client_id, state.last_seq)
    to_seq = max((c.seq for c in new), default=state.last_seq)
    today = now.date()
    years = _open_years(chat, client_id, today)
    mode = store.get_client(client_id).ai_review
    runs: list[ReviewRun] = []

    if mode == "off" or records.runs_on(client_id, today) >= settings.review_daily_limit:
        quiet, summary = ("off", "") if mode == "off" else ("limited", LIMITED_NOTE)
        if years and not _noted_today(records, client_id, quiet, today):
            runs.append(_quiet_run(records, client_id, years[-1], to_seq, quiet, summary))
        if mode == "off":
            records.patch_review_state(client_id, last_seq=to_seq, due_at=None, running=False, retry_at=None)
        else:   # the changes wait for the next day
            records.patch_review_state(client_id, running=False, retry_at=_iso(_midnight_after(now)))
        return runs

    needing = [c for c in new if triggers(c)]
    failed = False
    left_over: list[str] = []   # the years whose run had more issues than it could show: they run again at once
    for year in years:
        changes = [c for c in needing if c.year_start in (year, None)]
        if not changes and year.isoformat() not in state.left_over:
            continue
        done = _review_year(chat, client_id, year, changes, state.last_seq, to_seq, mode, now, left_over)
        if done is None:
            continue
        runs.append(done)
        if done.status == "failed":
            failed = True
            break

    if failed:
        wait = RETRY_SOON if (runs[-1].error or "").endswith(SOON_TEXT) else RETRY_AFTER
        records.patch_review_state(client_id, running=False, retry_at=_iso(now + wait))
        return runs
    records.patch_review_state(client_id, last_seq=to_seq, running=False, retry_at=None, left_over=left_over)
    if left_over:
        records.patch_review_state(client_id, due_at=_iso(now))
    elif not any(triggers(c) for c in records.changes_after(client_id, to_seq)):
        records.patch_review_state(client_id, due_at=None)
        # a change recorded between that look and the write above still leaves the client due
        if any(triggers(c) for c in records.changes_after(client_id, to_seq)):
            records.patch_review_state(client_id, due_at=_iso(now))
    return runs


def _review_year(chat: "Chat", client_id: int, year: dt.date, changes: list[Change], from_seq: int, to_seq: int,
                 mode: str, now: dt.datetime, left_over: list[str]) -> Optional[ReviewRun]:
    """One run over one year: start it, have the agent review, settle the books and finish the run, once. The run is
    pointed at the issues no earlier run was shown (up to MAX_UNREVIEWED; with more, the year goes on left_over and
    runs again at once), and at the rows a person changed; with neither, the model isn't asked and no run is
    recorded (None)."""
    records, store = chat.records, chat.store
    touched = sorted({r for c in changes for r in c.row_ids})
    first = not any(r.status in ("done", "failed") for r in records.reviews(client_id, year_start=year, limit=50))
    seen = records.issues_seen(client_id, year)
    theirs = records.person_rows(client_id)   # a background review leaves these to the person (R0)
    new_issues: list[tuple[object, str, str]] = []   # row, key, what it says
    upload_rows: dict[int, list[int]] = {}
    try:
        built = books.ledger(store, client_id, year)
        for saved in built.transactions:
            upload_rows.setdefault(saved.upload_id, []).append(saved.id)
        for row, held, _ in _to_look_at(built):
            if row.id not in theirs:
                new_issues += [(row, key, said) for key, said in issue_keys(row, held) if key not in seen]
    except Exception:
        logger.exception("Couldn't list the issues of client %s, year %s", client_id, year)
    # A person's change matters to the AI only where it may answer a question the AI asked about those rows.
    asked = {r for q in records.questions(client_id, year, ("open", "waiting")) if q.source == "agent"
             for r in q.row_ids}
    questioned = [n for n in touched if n in asked]
    if not new_issues and not questioned:
        return None   # nothing the AI can settle: the deterministic step has already settled the books
    shown, more = new_issues[:MAX_UNREVIEWED], max(0, len(new_issues) - MAX_UNREVIEWED)
    if more:
        left_over.append(year.isoformat())
    looked = sorted({*questioned, *(row.id for row, _, _ in shown)}, key=lambda n: (n not in questioned, n))
    summary = (issue_summary([key.split(":")[1] for _, key, _ in new_issues]) if new_issues
               else trigger_summary(changes))
    run = records.start_review(client_id, year, from_seq=from_seq, to_seq=to_seq, trigger_summary=summary,
                               looked_at=looked, issues_seen=[key for _, key, _ in shown])
    error: Optional[str] = None
    said = ""
    try:
        ctx = ChatContext(client_id, f"review-{run.id}", year, trigger="background",
                          mode="suggest" if mode == "suggest" else "apply", review_id=run.id)
        message = _message(changes, [(row, text) for row, _, text in shown], first, summary, upload_rows, more,
                           suggest=mode == "suggest")
        chat.brief(ctx, message)   # the run is the reviewer's, starting from its briefing
        for attempt in range(2):   # a run cut off while thinking is nudged once
            error, code = None, None
            for event in stream_turn(chat.agent, ctx, message):
                if event.type == "token":
                    said += event.data.get("text", "")
                elif event.type == "error" and error is None:
                    error = event.data.get("message") or event.data.get("code") or "The review failed."
                    code = event.data.get("code")
                    if code == "storage_unavailable":
                        error += SOON_TEXT
            if code != "cut_off" or attempt:
                break
            message, said = NUDGE, ""
    except Exception as exc:   # noqa: BLE001 - a run that raised is a failed run
        logger.exception("The background review of client %s failed", client_id)
        error = str(exc) or type(exc).__name__
    try:
        with chat.locks.hold(client_id):
            upkeep.settle_open_years(store, records, client_id, today=now.date())
    except Exception:
        logger.exception("Couldn't settle client %s after its review", client_id)

    decisions = [d.id for d in records.decisions(client_id, year) if d.review_id == run.id]
    asked = [q.id for q in records.questions(client_id, year, ("open", "waiting", "resolved"))
             if q.source == "agent" and q.created_at >= run.started_at]
    if error is not None:
        return records.finish_review(run.id, status="failed", decision_ids=decisions, question_ids=asked, error=error)
    lines = [ln.strip() for ln in said.splitlines() if ln.strip()]
    text = lines[-1] if lines else NOTHING   # its own words: what it did, or why nothing could be settled
    return records.finish_review(run.id, status="done", decision_ids=decisions, question_ids=asked, summary=text)


# ─── The worker ────────────────────────────────────────────────────────────────

class Worker:
    """Runs the due reviews, one client at a time, on a daemon thread that ticks every two seconds. busy(client_id):
    whether files are being read for the client, which a review waits for."""

    def __init__(self, chat: "Chat", settings: "Settings", *, busy: Callable[[int], bool],
                 clock: Callable[[], dt.datetime] = utcnow):
        self.chat, self.settings, self.busy, self.clock = chat, settings, busy, clock
        self._stop, self._thread = threading.Event(), None

    def recover(self) -> None:
        """After a restart: a review that was running is due at once."""
        records = self.chat.records
        for state in records.running_review_states():
            records.patch_review_state(state.client_id, running=False, due_at=_iso(self.clock()), retry_at=None)

    def tick(self, now: Optional[dt.datetime] = None) -> list[ReviewRun]:
        """Runs every client that is due: its time has come, it isn't running or waiting to retry, and no file is
        being read for it. Returns the runs."""
        now = now or self.clock()
        records, runs = self.chat.records, []
        for state in records.due_review_states():
            try:
                if state.running or _when(state.due_at) > now or self.busy(state.client_id):
                    continue
                if state.retry_at and _when(state.retry_at) > now:
                    continue
                try:
                    client = self.chat.store.get_client(state.client_id)
                except NotFound:
                    client = None
                if client is None or client.archived:   # gone or archived: there is nothing to review
                    records.patch_review_state(state.client_id, due_at=None, retry_at=None)
                    continue
                if not records.claim_review(state.client_id):   # another worker has it
                    continue
            except Exception:
                logger.exception("The review worker couldn't look at client %s", state.client_id)
                continue
            try:
                runs.extend(run(self.chat, state.client_id, now=now))
            except Exception:
                logger.exception("The background review of client %s couldn't run", state.client_id)
                records.patch_review_state(state.client_id, running=False, retry_at=_iso(now + RETRY_AFTER))
        return runs

    def start(self) -> None:
        self.recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="review-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                logger.exception("The review worker's tick failed")
