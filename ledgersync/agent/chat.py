"""The accountant chat as the API serves it (design of 2026-11-02, replies of 2026-11-03): its threads, a message's
turn, and the answers.

A turn reads the files sent with the message into the client's documents, runs the agent on the message, and then,
whatever the agent did, records the dates matching took from the bank, works the questions out and posts the year,
under the client's lock. It ends with its result, built from the records: what this chat sorted in the turn, the
questions the turn raised (every open one when the agent listed them), and the posted trial balance when the turn
posted something or the agent fetched it. The thread keeps the result with the files the turn read, under the id of
the person's message, and reopening the chat shows each with its reply. A turn runs on a thread of its own and goes
on to the end if the person goes away.
An answer is applied without the model (questions.answer) and then noted in the chat's memory, for the agent alone; a
document sent for a question is read, the year posted again, and the question says why the document didn't settle it
if it didn't. Each returns the question as it stands and only what that did."""
from __future__ import annotations

import datetime as dt
import logging
import queue
import re
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Callable, Iterator, Literal, Optional
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.constants import START
from pydantic import BaseModel, StringConstraints, ValidationError

from ledgersync import books, ledger_book, questions, upkeep
from ledgersync.blobs import BlobStore
from ledgersync.config import Settings
from ledgersync.errors import InvalidInput, LedgerSyncError, ModelUnavailable, NotFound, SameFile, YearClosed
from ledgersync.jobs import SUCCEEDED, Job
from ledgersync.ledger import require_active
from ledgersync.models import (ChangeDraft, ChatThread, Client, Decision, PostedTrialBalance, PostResult, Question,
                               Transaction)
from ledgersync.records import AgentRecords
from ledgersync.rows import now_iso
from ledgersync.store_mongo import MongoStore

from . import build_agent
from .briefing import briefing
from .llm import chat_model
from .locks import ClientLocks, ThreadRuns
from .router import LEAD, route
from .run import ChatEvent, stream_turn
from .specialists import PROFILES
from .tools import AgentDeps, ChatContext

logger = logging.getLogger(__name__)

NEW_CHAT = "New chat"
STOPPED_CALL = "Stopped before this finished."
FAILED = "Something went wrong while I was working, so I stopped. The server log says what."
LIMITED = "I stopped after too many steps, before finishing."
# What the call limits' middleware says when it ends a run (langchain's own words), which a reload shows as LIMITED.
_LIMIT_TEXT = re.compile(r"Model call limits exceeded: |(?:Tool|'[^']+' tool) call limit reached: ")
ANSWER_WAIT = 120.0   # seconds an answer waits for the message running on its chat, before it is refused
_DOCUMENT_KINDS = questions.DOCUMENT_KINDS


class FileRead(BaseModel):
    """How reading a file sent with a message went: the rows it gave, or why it wasn't read."""
    name: str
    state: Literal["done", "failed"]
    rows: Optional[int] = None
    reason: Optional[str] = None


class TurnResult(BaseModel):
    """What a turn did, and only that: a turn that did none of it has an empty result, and its reply no cards.
    sorted: the applied decisions this chat made since the message was sent. questions: those open or waiting when
    the turn ended but not when it began (every open one when the agent listed them). trial_balance: the posted one,
    when the turn's posting wrote something or the agent fetched it. post: the posting, when it wrote something or
    couldn't."""
    sorted: list[Decision] = []
    questions: list[Question] = []
    trial_balance: Optional[PostedTrialBalance] = None
    post: Optional[PostResult] = None

    def is_empty(self) -> bool:
        return not self.sorted and not self.questions and self.trial_balance is None and self.post is None


class AnswerResult(BaseModel):
    """What an answer, or a document sent for a question, returns: the question as it stands, the applied decisions
    this chat made since the answer began, and, when the posting wrote something, the posted trial balance and the
    posting (the posting too when it couldn't write)."""
    question: Question
    sorted: list[Decision] = []
    trial_balance: Optional[PostedTrialBalance] = None
    post: Optional[PostResult] = None


class TurnRecord(BaseModel):
    """A turn as its thread keeps it: the id of the person's message, the files it carried, the turn's result, the
    specialist the router gave the turn, and whether it handed the turn over to the lead accountant. A turn kept
    before there were specialists has neither."""
    message_id: str
    files: list[FileRead] = []
    result: TurnResult
    specialist: Optional[str] = None
    handed_over: bool = False


class ChatMessage(BaseModel):
    """A message as the page shows it: the person's with the files it carried; an assistant's with the result of the
    turn it ends (None when the turn did nothing)."""
    role: Literal["user", "assistant"]
    text: str
    files: list[FileRead] = []
    result: Optional[TurnResult] = None


class ThreadDetail(BaseModel):
    """A thread with its messages so far, and whether a turn is still running on it (its reply and result are not in
    the messages until it ends)."""
    thread: ChatThread
    messages: list[ChatMessage]
    running: bool = False


class NewThread(BaseModel):
    client_id: int
    year_start: Optional[dt.date] = None   # an open year of the client's to chat about; None: the open year now


class ThreadPatch(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


@dataclass(frozen=True)
class ChatFile:
    """A file sent to the chat: its name, its bytes (read up to the upload limit and one byte more, so a larger one
    is refused), its type, and for a statement the bank account it goes on (None: the client's first current
    account)."""
    name: str
    data: bytes
    content_type: str
    bank_account: Optional[str] = None


# Reads a file for the client into the year, as /api/analyze reads an upload: the job reading it; LedgerSyncError
# when the file is refused before it is read.
Reader = Callable[[Client, ChatFile, dt.date], Job]


@dataclass(frozen=True)
class Since:
    """Where a turn or an answer starts in the client's decisions: the time (to the second), and the decisions
    already made in that second."""
    at: str
    before: frozenset[str]


def since_now(records: AgentRecords, client_id: int) -> Since:
    at = now_iso()
    return Since(at, frozenset(d.id for d in records.decisions(client_id, since=at)))


def sorted_since(records: AgentRecords, thread: ChatThread, since: Since) -> list[Decision]:
    """The decisions this chat applied since then, oldest first."""
    return _applied_since(records, thread.client_id, thread.id, since)


def _applied_since(records: AgentRecords, client_id: int, thread_id: Optional[str], since: Since) -> list[Decision]:
    """The decisions applied since then under this thread id (None: outside any chat), oldest first."""
    return [d for d in records.decisions(client_id, since=since.at)
            if d.id not in since.before and d.status == "applied" and d.thread_id == thread_id]


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _error(code: str, message: str) -> ChatEvent:
    return ChatEvent("error", {"code": code, "message": message})


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _gbp(amount) -> str:
    return f"£{Decimal(str(amount)):,.2f}"


def _title(text: str) -> str:
    """A chat's title from its first message: its first 60 characters, on one line."""
    return " ".join(text.split())[:60]


def _open_year(store: MongoStore, client_id: int) -> dt.date:
    """The start of the client's open year: the one holding today if it is open, otherwise the latest open one."""
    today = dt.date.today()
    open_years = [y for y in books.years_of(store, client_id, today) if not y.closed]
    if not open_years:
        raise YearClosed("Every year of this client is closed. Reopen one to chat about it.")
    return next((y.start for y in open_years if y.start <= today <= y.end), open_years[-1].start)


def _messages(messages: list, turns: dict[str, TurnRecord]) -> list[ChatMessage]:
    """The chat's messages as the page shows them: the person's, with the files they carried, and the agent's replies
    (a turn's replies in one, each trimmed and apart by a blank line) with their turn's result when that isn't empty.
    A turn that has a result but no reply gets a reply with no text. `turns` holds the kept turns by the id of the
    person's message; one whose message isn't in the memory is shown after the rest, as a reply with no text. Tool
    calls and their results are left out, and so are notes, which are for the agent alone."""
    kept = dict(turns)
    replies: list[str] = []   # the texts of the replies since the person's last message
    exchanges: list[tuple[Optional[HumanMessage], list[str]]] = [(None, replies)]   # a reply before any message
    for m in messages:
        if isinstance(m, HumanMessage):
            if not m.additional_kwargs.get("note"):
                replies = []
                exchanges.append((m, replies))
        elif isinstance(m, AIMessage) and (said := m.text.strip()):   # not the whitespace sent around tool calls
            replies.append(LIMITED if _LIMIT_TEXT.match(said) else said)
    shown: list[ChatMessage] = []
    for person, texts in exchanges:
        turn = kept.pop(person.id, None) if person else None
        if person:
            shown.append(ChatMessage(role="user", text=person.text, files=turn.files if turn else []))
        result = turn.result if turn and not turn.result.is_empty() else None
        if texts or result:
            shown.append(ChatMessage(role="assistant", text="\n\n".join(texts), result=result))
    for turn in kept.values():   # their messages aren't in the memory
        if not turn.result.is_empty():
            shown.append(ChatMessage(role="assistant", text="", result=turn.result))
    return shown


def _close_open_calls(agent, thread_id: str) -> None:
    """Answers each tool call of the chat's last model reply that has no result, which a server that stopped while
    the tool ran leaves behind, with "Stopped before this finished.": the model refuses a chat with a call
    unanswered."""
    config = _config(thread_id)
    messages = agent.get_state(config).values.get("messages", [])
    last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    open_calls = [c for c in (last.tool_calls if last else []) if c["id"] not in answered]
    if open_calls:
        agent.update_state(config, {"messages": [ToolMessage(STOPPED_CALL, tool_call_id=c["id"], name=c["name"],
                                                             status="error") for c in open_calls]},
                           as_node="tools")


def _say(agent, thread_id: str, text: str, *, message_id: Optional[str] = None, note: bool = False) -> None:
    """Adds a message from the person to the chat's memory without running the agent (after answering any tool call
    left open, so it follows a complete exchange), under message_id if given. A note is for the agent alone: the chat
    doesn't show it."""
    _close_open_calls(agent, thread_id)
    said = HumanMessage(text, id=message_id, additional_kwargs={"note": True} if note else {})
    agent.update_state(_config(thread_id), {"messages": [said]}, as_node=START)


def _outcome(job: Job) -> tuple[list[dict], Optional[dict]]:
    """Waits for the job reading a file: the rows it read, or its error ({code, message, status_code})."""
    job.done.wait()
    if job.status == SUCCEEDED:
        return job.result["transactions"], None
    return [], job.error or {"code": "cancelled", "message": "Reading it was cancelled.", "status_code": 409}


def _unread(step: dict, name: str, reason: str, *, skipped: bool = False) -> dict:
    """A file not read: one refused says "Couldn't read <name>: <reason>"; one skipped as already saved says why in
    full ("Skipped <name>: same file as ...")."""
    return {**step, "text": reason if skipped else f"Couldn't read {name}: {reason}", "state": "failed", "reason": reason}


def _file_read(step: dict) -> FileRead:
    """How a file's reading went, from its last step."""
    return FileRead(name=step["file"], state=step["state"], rows=step.get("rows"), reason=step.get("reason"))


def _mismatch(name: str, rows: list[dict], payment: Optional[Transaction]) -> str:
    """Why a document sent for a question didn't settle it: what it is for against the payment."""
    read = rows[0] if rows else None
    theirs = (f"{read.get('counterparty') or read['description']}, {_gbp(read.get('document_total') or read['gross'])}"
              if read else "nothing to pay")
    ours = f"{payment.counterparty or payment.description}, {_gbp(payment.gross)}" if payment else "the payment"
    return (f"Read {name}, but it doesn't match: {theirs} against {ours}. "
            "It's saved and booked; remove it in Transactions if it isn't theirs.")


def _until_done(events: queue.Queue) -> Iterator[ChatEvent]:
    while True:
        event = events.get()
        yield event
        if event.type == "done":
            return


class _NoModel(BaseChatModel):
    """Stands in for the agent's model when it can't be had (OPENROUTER_API_KEY isn't set), so the chats' memory
    can still be read and written. A turn checks Chat.unavailable and never calls it."""

    message: str

    @property
    def _llm_type(self) -> str:
        return "unavailable"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise ModelUnavailable(self.message)


class Chat:
    """The chat of one app: its records and agent (made on first use, so the app starts without the database
    answering or a model key), which chats are running, and the clients' locks."""

    def __init__(self, settings: Settings, store: MongoStore, blobs: BlobStore, *, read: Reader, vision=None,
                 model: Optional[BaseChatModel] = None):
        """read: reads a file sent to the chat. vision: the model client that transcribes images for the agent's
        tools. model: the agent's chat model; by default OPENROUTER_MODEL (the one that reads the files) through
        OpenRouter."""
        self.settings, self.store, self.blobs, self.read_file, self.vision = settings, store, blobs, read, vision
        self._model = model
        self.locks, self.runs = ClientLocks(), ThreadRuns()
        self.unavailable: Optional[str] = None   # why the agent's model can't be used, once the agent is made
        self._making = threading.Lock()
        self._records: Optional[AgentRecords] = None
        self._agent = None
        self._deps: Optional[AgentDeps] = None   # what the agent's tools work on, once the agent is made

    @property
    def records(self) -> AgentRecords:
        with self._making:
            if self._records is None:
                self._records = AgentRecords(self.store.db)
            return self._records

    @property
    def agent(self):
        records = self.records
        with self._making:
            if self._agent is None:
                model = self._model
                if model is None:
                    try:
                        model = chat_model(self.settings)
                    except ModelUnavailable as exc:
                        model, self.unavailable = _NoModel(message=exc.message), exc.message
                self._deps = AgentDeps(store=self.store, records=records, blobs=self.blobs, vision=self.vision,
                                       is_cancelled=self.runs.is_cancelled, locks=self.locks)
                self._agent = build_agent(self.settings, self._deps, model=model)
            return self._agent

    def brief(self, ctx: ChatContext, text: str, has_files: bool = False) -> None:
        """Gives the run to the specialist its message asks for (router.route; a chat's message that no rule places
        stays with the specialist of its turn before, the lead accountant if that turn was handed over) and fetches
        the briefing that specialist starts from. The run stays the lead accountant's, the whole agent's, when no
        specialist takes the message, and when the briefing can't be built (a row that can't be posted stops the
        figures): the lead finds its own way."""
        self.agent   # its tools' deps are made with it
        previous = None
        if ctx.trigger == "chat":
            last = (self.records.turns(ctx.thread_id) or [{}])[-1]
            previous = None if last.get("handed_over") else last.get("specialist")
        ctx.specialist = route(ctx.trigger, text, has_files, previous)
        if ctx.specialist == LEAD:
            return
        try:
            ctx.briefing = briefing(self._deps, ctx)
        except Exception:   # noqa: BLE001 - whatever stopped the figures: the lead accountant takes the turn
            logger.exception("Couldn't brief the %s for client %s, so the lead accountant takes the turn",
                             ctx.specialist, ctx.client_id)
            ctx.specialist, ctx.briefing = LEAD, ""

    # ─── Threads ───────────────────────────────────────────────────────────────

    def thread(self, thread_id: str) -> ChatThread:
        found = self.records.thread(thread_id)
        if found is None:
            raise NotFound("This chat was not found.")
        return found

    def new_thread(self, client_id: int, year_start: Optional[dt.date] = None) -> ChatThread:
        """A chat on the client's open year (or the open year named, an earlier one being caught up, say), called
        "New chat" until its first message."""
        require_active(self.store.get_client(client_id))
        if year_start is None:
            year_start = self._year_waiting(client_id) or _open_year(self.store, client_id)
        elif not any(y.start == year_start and not y.closed
                     for y in books.years_of(self.store, client_id, dt.date.today())):
            raise InvalidInput(f"{year_start:%-d %b %Y} isn't one of this client's open years.")
        return self.records.create_thread(client_id, year_start, NEW_CHAT)

    def _year_waiting(self, client_id: int) -> Optional[dt.date]:
        """The earliest open year with questions waiting for an answer, where a chat about what needs attention
        belongs (books caught up from years back); None when no open year has any."""
        waiting = {q.year_start for q in self.records.questions(client_id, None)}
        return next((y.start for y in books.years_of(self.store, client_id, dt.date.today())
                     if not y.closed and y.start in waiting), None)

    def detail(self, thread: ChatThread) -> ThreadDetail:
        """The chat's messages from its memory, with each turn's files on the person's message and its result on the
        reply. A result's questions are read as they are now (an answer, or a document sent in another chat, may have
        settled one since). `running` says a turn is working on the chat now. A chat saved before turns were kept
        shows its messages alone, and so does a reply whose turn record cannot be read."""
        # Read first: a turn that ends after this is caught by the page's next load, and one that ended before it has
        # its record kept already.
        running = self.runs.is_running(thread.id)
        turns: dict[str, TurnRecord] = {}   # read before the memory: a turn is kept only after its messages are in it
        for kept in self.records.turns(thread.id):
            try:
                turn = TurnRecord.model_validate(kept)
            except ValidationError:
                logger.warning("A turn record of chat %s could not be read and was skipped", thread.id)
                continue
            current = (self.records.question(q.id) for q in turn.result.questions)
            turn.result.questions = [q for q in current if q is not None]
            turns[turn.message_id] = turn
        state = self.agent.get_state(_config(thread.id))
        return ThreadDetail(thread=thread, messages=_messages(state.values.get("messages", []), turns), running=running)

    def delete(self, thread: ChatThread) -> None:
        """Removes the chat and its memory; StillWorking while a message runs on it."""
        with self.runs.running(thread.id):
            self.agent.checkpointer.delete_thread(thread.id)
            self.records.delete_thread(thread.id)

    # ─── A message ─────────────────────────────────────────────────────────────

    def send(self, thread: ChatThread, text: str, files: list[ChatFile]) -> Iterator[ChatEvent]:
        """Takes the chat's one run (StillWorking while it has one) and works the message on a thread of its own,
        which lets the run go when it ends however it ends. Returns its events as they come, ending with done."""
        self.runs.start(thread.id)
        events: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                for event in self.turn(thread, text, files):
                    events.put(event)
            except LedgerSyncError as exc:
                events.put(_error(exc.code, exc.message))
            except Exception:   # noqa: BLE001 - every failure ends the turn with an error event
                logger.exception("A chat turn failed")
                events.put(_error("agent_failed", FAILED))
            finally:
                self.runs.finish(thread.id)
                events.put(ChatEvent("done", {}))

        try:
            threading.Thread(target=work, name=f"chat-{thread.id[:8]}", daemon=True).start()
        except BaseException:
            self.runs.finish(thread.id)
            raise
        return _until_done(events)

    def turn(self, thread: ChatThread, text: str, files: list[ChatFile]) -> Iterator[ChatEvent]:
        """One message: the files read, the agent's run (or model_unavailable), then the dates from the bank
        recorded, the questions worked out and the year posted, and the turn's result, which the thread keeps with the
        files read. The first message titles the chat."""
        client = self.store.get_client(thread.client_id)
        since = since_now(self.records, client.id)
        # The questions as the books ask them now: one a change on a page has answered since isn't put to the agent,
        # or to the person, again. Never fails the turn; a closed year's questions stay as they are.
        if all(c.start != thread.year_start for c in client.closed_years):
            try:
                with self.locks.hold(client.id):
                    questions.refresh(self.store, self.records, client.id, thread.year_start)
            except Exception:   # noqa: BLE001
                logger.exception("Couldn't work out the questions of client %s before a turn", client.id)
        before = {q.id for q in self.records.questions(client.id, thread.year_start)}   # open or waiting already
        message_id = uuid4().hex   # the person's message in the chat's memory, and the turn on the thread
        called: set[str] = set()   # the tools the agent calls
        read: list[FileRead] = []
        self.records.touch_thread(thread.id, title=_title(text) if thread.title == NEW_CHAT else None)
        try:
            if files:
                yield ChatEvent("status", {"text": f"Reading {_count(len(files), 'file')}…"})
                yield from self._read_all(client, thread.year_start, files, read)
            agent = self.agent
            ctx = ChatContext(client.id, thread.id, thread.year_start)
            if not self.unavailable:
                self.brief(ctx, text, bool(files))   # once the files are read: its briefing has their rows
            took = ctx.specialist   # who the turn was given to; hand_over makes ctx.specialist the lead
            yield ChatEvent("status", {"text": PROFILES[took].status})
            if self.unavailable:   # the message is kept, so the chat shows it
                _say(agent, thread.id, text, message_id=message_id)
                yield _error("model_unavailable", self.unavailable)
            else:
                _close_open_calls(agent, thread.id)
                yield from stream_turn(agent, ctx, text, message_id=message_id, called=called)
            yield ChatEvent("status", {"text": "Posting the books…"})
        finally:   # the files read in this turn are settled even if the stream raised or the caller stopped
            with self.locks.hold(client.id):
                post = self._write(thread, since)
        open_now = self.records.questions(thread.client_id, thread.year_start)
        raised = open_now if "list_questions" in called else [q for q in open_now if q.id not in before]
        # An answer the agent filled in this turn, for the person to confirm on its card: shown whatever its year.
        offered = [q for q in self.records.questions(thread.client_id, None)
                   if q.offer is not None and q.offer.thread_id == thread.id and q.offer.offered_at >= since.at
                   and q.id not in {r.id for r in raised}]
        raised = raised + offered
        wrote = post.batch_id is not None
        result = TurnResult(
            sorted=sorted_since(self.records, thread, since), questions=raised,
            trial_balance=(ledger_book.posted_trial_balance(self.store, self.records, thread.client_id,
                                                            thread.year_start)
                           if wrote or "get_trial_balance" in called else None),
            post=post if wrote or post.problems or post.left_out else None)
        self.records.add_turn(thread.id, TurnRecord(message_id=message_id, files=read, result=result, specialist=took,
                                                    handed_over=ctx.handed_over).model_dump(mode="json"))
        yield ChatEvent("result", result.model_dump(mode="json"))

    def _read_all(self, client: Client, year_start: dt.date, files: list[ChatFile],
                  read: list[FileRead]) -> Iterator[ChatEvent]:
        """Starts reading every file (side by side, as many as the job registry runs at once), then says how each
        went, in order: "Reading <name>…", then "Read <name> (n rows)", "Couldn't read <name>: <reason>", or "Skipped
        <name>: same file as ..." for a file already saved for the client or sent twice. Each
        file's outcome is added to `read` as its last step is said."""
        reading = []
        for k, file in enumerate(files):
            step = {"id": f"read-{k}", "text": f"Reading {file.name}…", "state": "running", "file": file.name}
            yield ChatEvent("step", step)
            try:
                reading.append((step, file.name, self.read_file(client, file, year_start)))
            except LedgerSyncError as exc:
                unread = _unread(step, file.name, exc.message, skipped=isinstance(exc, SameFile))
                read.append(_file_read(unread))
                yield ChatEvent("step", unread)
        for step, name, job in reading:
            rows, error = _outcome(job)
            last = _unread(step, name, error["message"]) if error else {
                **step, "text": f"Read {name} ({_count(len(rows), 'row')})", "state": "done", "rows": len(rows)}
            read.append(_file_read(last))
            yield ChatEvent("step", last)

    def _write(self, thread: ChatThread, since: Since) -> PostResult:
        return self._write_for(thread.client_id, thread.year_start, thread.id, since)

    def _write_for(self, client_id: int, year_start: dt.date, thread_id: Optional[str], since: Since) -> PostResult:
        """With the client's lock held: records the rows matching dated from the bank, works the questions out and
        posts the year, with the decisions this chat made since then behind the posting; then settles the client's other
        open years, which the files read may have put rows in."""
        try:
            return upkeep.settle(self.store, self.records, client_id, year_start, thread_id=thread_id,
                                 decision_ids=[d.id for d in _applied_since(self.records, client_id, thread_id, since)])
        finally:   # a file read in the chat can hold rows of any open year: they are settled too
            upkeep.settle_open_years(self.store, self.records, client_id, except_year=year_start,
                                     thread_id=thread_id)

    def _answered(self, thread: ChatThread, since: Since, question_id: str, post: PostResult) -> AnswerResult:
        return self._answered_for(thread.client_id, thread.year_start, thread.id, since, question_id, post)

    def _answered_for(self, client_id: int, year_start: dt.date, thread_id: Optional[str], since: Since,
                      question_id: str, post: PostResult) -> AnswerResult:
        """The question as it stands, with what this chat sorted since then and, when the posting wrote something,
        the year's posted trial balance and the posting (the posting too when it couldn't write)."""
        wrote = post.batch_id is not None
        return AnswerResult(
            question=self.records.question(question_id),
            sorted=_applied_since(self.records, client_id, thread_id, since),
            trial_balance=(ledger_book.posted_trial_balance(self.store, self.records, client_id, year_start)
                           if wrote else None),
            post=post if wrote or post.problems or post.left_out else None)

    # ─── Answers ───────────────────────────────────────────────────────────────

    def _question(self, thread: ChatThread, question_id: str) -> Question:
        asked = self.records.question(question_id)
        if asked is None or asked.client_id != thread.client_id:
            raise NotFound("This question was not found.")
        return asked

    def answer(self, thread: ChatThread, question_id: str, answer: questions.Answer) -> AnswerResult:
        """Applies the person's answer without the model (questions.answer works the questions out and posts),
        notes it in the chat's memory as "Answered: <question> → <answer>" (a note, which the chat doesn't show), and
        returns the question with what the answer did. It waits for a message running on the chat (ANSWER_WAIT, then
        StillWorking), as the note mustn't race the run; an answer to a question already resolved changes nothing."""
        require_active(self.store.get_client(thread.client_id))
        with self.runs.running(thread.id, wait=ANSWER_WAIT):
            asked = self._question(thread, question_id)
            since = since_now(self.records, thread.client_id)
            with self.locks.hold(thread.client_id):
                answered = questions.answer(self.store, self.records, client_id=thread.client_id,
                                            thread_id=thread.id, question_id=question_id, answer=answer)
            if asked.status != "resolved":
                said = self.records.question(question_id)
                _say(self.agent, thread.id, f"Answered: {said.text} → {said.answer}", note=True)
            self.records.touch_thread(thread.id)
            return self._answered(thread, since, question_id, answered.post)

    def answer_outside(self, client_id: int, question_id: str, answer: questions.Answer, *,
                       wait: int) -> AnswerResult:
        """Applies the person's answer given outside any chat (a question card on the client's page), and returns
        what a chat's answer returns: the question as it stands, with what the answer did. The client is made due for
        a background review `wait` seconds on (questions.answer)."""
        require_active(self.store.get_client(client_id))
        asked = self.records.question(question_id)
        if asked is None or asked.client_id != client_id:
            raise NotFound("This question was not found.")
        since = since_now(self.records, client_id)
        with self.locks.hold(client_id):
            answered = questions.answer(self.store, self.records, client_id=client_id, thread_id=None,
                                        question_id=question_id, answer=answer, wait=wait)
        return self._answered_for(client_id, asked.year_start, None, since, question_id, answered.post)

    def document(self, thread: ChatThread, question_id: str, file: ChatFile) -> AnswerResult:
        """A document sent for a question in a chat: see answer_with_document."""
        require_active(self.store.get_client(thread.client_id))
        asked = self._question(thread, question_id)
        result = self.answer_with_document(self.store.get_client(thread.client_id), thread.year_start, asked.id, file,
                                           thread_id=thread.id)
        self.records.touch_thread(thread.id)
        return result

    def answer_with_document(self, client: Client, year_start: dt.date, question_id: str, file: ChatFile, *,
                             thread_id: Optional[str] = None) -> AnswerResult:
        """Reads the file sent for a question into the client's documents, then records, works the questions out and
        posts as a turn ends. If the question is still asked, its reason says the file didn't match: "Read <name>,
        but it doesn't match: <payee>, £<total> against <payee>, £<amount>." Returns the question with what the file
        did. thread_id: the chat it was sent in (None: the question's list, outside any chat)."""
        require_active(client)
        asked = self.records.question(question_id)
        if asked is None or asked.client_id != client.id:
            raise NotFound("This question was not found.")
        if asked.kind not in _DOCUMENT_KINDS:
            raise InvalidInput("This question isn't asking for a document.")
        since = since_now(self.records, client.id)
        rows, error = _outcome(self.read_file(client, file, year_start))
        if error:
            refused = LedgerSyncError(f"Couldn't read {file.name}: {error['message']}", code=error.get("code"))
            refused.status_code = error.get("status_code", 422)
            raise refused
        with self.locks.hold(client.id):
            post = self._write_for(client.id, year_start, thread_id, since)
            still = self.records.question(question_id)
            if still.status != "resolved":
                payment = next((r.tx for r in self.store.rows(client.id) if r.id in still.row_ids[:1]), None)
                self.records.set_question_why(question_id, _mismatch(file.name, rows, payment))
        if thread_id is None and still.status == "resolved":   # outside a chat nobody else handles the answer
            try:   # the books are settled: recording the answer must never fail the request
                from .. import reviews   # here: reviews imports the agent
                made = ChangeDraft(client_id=client.id, year_start=asked.year_start, actor="user",
                                   kind="question_answered", row_ids=list(asked.row_ids), after={"answer": file.name},
                                   summary=f"Answered: {asked.text}", in_chat=False)
                self.records.add_change(made)
                reviews.note(self.records, made, now=reviews.utcnow(), wait=self.settings.review_wait_seconds)
            except Exception:
                logging.getLogger("ledgersync.upkeep").exception(
                    "Couldn't record the answer to question %s for client %s", question_id, client.id)
        return self._answered_for(client.id, year_start, thread_id, since, question_id, post)
