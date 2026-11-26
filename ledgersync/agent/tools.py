"""The accountant agent's tools. Each takes the client, the year the chat is on and the chat itself from the run's
context (ToolRuntime), never from the model's arguments, and its arguments are checked by Pydantic. They read the
books, the documents, the questions and the decisions. Two change rows: resolve_issue, through resolutions.resolve,
which checks the evidence and records the decision, and edit_row, which makes a change the person in the chat asked
for (resolutions.edit_as_told: the Edit dialog's change, recorded as a decision). ask_user adds a question. No tool
posts: the server posts at the end of each turn. Each tool says what it is
doing as a step of the turn, under its tool call's id, which run.stream_turn passes on."""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Literal, Optional

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BeforeValidator, Field
from pydantic_core import to_jsonable_python

from ledgersync import books, documents, ledger_book, questions
from ledgersync.blobs import BlobStore
from ledgersync.checks import booked
from ledgersync.errors import InvalidInput, InvalidTransactions, NotFound
from ledgersync.evidence_rules import DocumentRule, document_rule
from ledgersync.accounts import choosable
from ledgersync.ledger import bank_choices, owners_of, settings_for
from ledgersync.models import Evidence, Ledger, OfferSource, SavedRow
from ledgersync.records import AgentRecords
from ledgersync.resolutions import AgentResolution, RowEdit, edit_as_told, resolve
from ledgersync.store_mongo import MongoStore

from .locks import ClientLocks

Family = Literal["date", "duplicate", "combined_vat", "conflict", "missing_vat", "documents", "coding", "other"]

# The family of each issue code, as list_issues sorts them. The codes are those checks.py, matching.py,
# statements.py, file_dates.py and adapter.py give; any code not here is "other". A row the document rules hold in
# Suspense (evidence_rules) is "documents" too.
FAMILIES: dict[str, Family] = {
    # The date: none, read differently from the bank's, outside the year, or only in the file name.
    "date_missing": "date", "date_conflict": "date", "date_out_of_period": "date", "before_first_year": "date",
    "file_date": "date",
    # One purchase recorded twice: by two records, a copy of a document, or lines over a document's total.
    "booked_twice": "duplicate", "duplicate_document": "duplicate", "total_mismatch": "duplicate",
    "claim_receipts_unclear": "duplicate",
    "possible_duplicate": "duplicate",
    # One VAT total over items at different rates.
    "mixed_items": "combined_vat", "vat_rate_mismatch": "combined_vat",
    # Two records of one purchase disagree on its amount or its VAT.
    "amount_conflict": "conflict", "claim_vat": "conflict",
    # VAT the document shows that the row doesn't book.
    "vat_not_booked": "missing_vat", "not_vat_invoice": "missing_vat",
    # A document that isn't a transaction, or that is missing.
    "not_booked": "documents", "open_document": "documents", "no_payroll": "documents",
    "needs_document": "documents", "document_wanted": "documents", "not_claimed": "documents", "hotel_vat": "documents",
    # The account a purchase is on: none found by the reader (parked in Suspense), another than its supplier's
    # usual one, or a cost account for equipment and a fixed asset for something small.
    "account_unclear": "coding", "unusual_account": "coding", "asset_check": "coding", "should_be_asset": "coding", "whose_account": "coding", "claim_note": "coding",
    "sundry_check": "coding", "account_fact": "coding", "meal_check": "coding",
    "small_asset": "coding",
}

# The one slip live runs made in evidence sent as a JSON string: a stray quote after the integer upload id.
_STRAY_QUOTE = re.compile(r'("upload_id"\s*:\s*\d+)"')


def _evidence_from_json(value: Any) -> Any:
    """The model sometimes sends the evidence list as a JSON string. Parses it; if that fails, mends only the stray
    quote after an upload id (`"upload_id": 516"`) and parses once more. Anything else is left for validation to
    refuse, as is a value that isn't a string."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        pass
    try:
        return json.loads(_STRAY_QUOTE.sub(r"\1", value))
    except ValueError:
        return value


# The matches that tie a row to another record of the same purchase (claimed_in names a whole expenses sheet).
_MATCHES = ("paid_by", "pays", "recorded_by", "copy_of")


@dataclass
class ChatContext:
    """Who a run works for, from the server: the client, the year the chat is on, and the chat. trigger: a chat turn or the
    background review; mode: whether its resolutions are made (apply) or only suggested; review_id: the review run."""
    client_id: int
    thread_id: str
    year_start: dt.date
    trigger: Literal["chat", "background"] = "chat"
    mode: Literal["apply", "suggest"] = "apply"
    review_id: Optional[str] = None
    # The part the agent plays for this run (specialists.PROFILES): the lead accountant, which is the whole agent,
    # unless the router picked a specialist. briefing: the state of the books as the turn began, which a specialist
    # starts from instead of fetching it. hand_over sets handed_over and makes the rest of the run the lead's.
    specialist: str = "lead"
    briefing: str = ""
    handed_over: bool = False


def _never(thread_id: str) -> bool:
    return False


@dataclass
class AgentDeps:
    """What the tools need: the store and the agent's records, on the app's one MongoDB client; where the original
    files are kept; the vision model that transcribes images and scans (ModelClient; None: they can't be read); and
    whether a chat was asked to stop, by its thread id."""
    store: MongoStore
    records: AgentRecords
    blobs: BlobStore
    vision: Optional[Any] = None
    is_cancelled: Callable[[str], bool] = field(default=_never)
    locks: ClientLocks = field(default_factory=ClientLocks)


def upload_texts(deps: AgentDeps, client_id: int) -> Callable[[int], list[str]]:
    """The pages of one of the client's uploads, by its id (none for an upload that isn't the client's)."""
    uploads = {u["id"]: u for u in deps.store.uploads(client_id)}

    def pages(upload_id: int) -> list[str]:
        upload = uploads.get(upload_id)
        return documents.text_of(upload, deps.blobs, deps.records, deps.vision) if upload else []
    return pages


def _reviews_since_last_chat(records: AgentRecords, ctx: ChatContext) -> list[dict]:
    """Up to five of the background reviews that finished after the client's previous chat was last used (all of
    them when there is none), newest first: when each ran, what it said, how many changes it made and how many
    questions it asked."""
    previous = next((t for t in records.threads(ctx.client_id) if t.id != ctx.thread_id), None)
    ran = [r for r in records.reviews(ctx.client_id, limit=50)
           if r.status == "done" and r.finished_at and (previous is None or r.finished_at > previous.updated_at)]
    return [{"ran_at": r.finished_at, "summary": r.summary,
             "sorted": sum((d := records.decision(ctx.client_id, n)) is not None and d.status == "applied"
                           for n in r.decision_ids),
             "asked": len(r.question_ids)} for r in ran[:5]]


def family_of(code: str) -> Family:
    return FAMILIES.get(code, "other")


def _step(runtime: ToolRuntime, text: str, state: str = "running", reason: Optional[str] = None) -> None:
    """Tells the turn what the tool is doing, as a step under its tool call's id."""
    step = {"id": runtime.tool_call_id, "text": text, "state": state, **({"reason": reason} if reason else {})}
    runtime.stream_writer({"step": step})


def _kept(fields: dict) -> dict:
    """The fields that say something: without None, empty lists or empty dicts."""
    return {k: v for k, v in fields.items() if v is not None and v != [] and v != {}}


def _out(value) -> Any:
    """The value as JSON: money and dates as strings ("12.50", "2026-10-14")."""
    return to_jsonable_python(value)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _held(row: SavedRow, settings) -> Optional[DocumentRule]:
    """The document rule holding the row in Suspense, if one does (only a booked row is held)."""
    if not booked(row):
        return None
    rule = document_rule(row, settings)
    return rule if rule.action == "hold" else None


def _brief(row: SavedRow, names: dict[int, str], held: Optional[DocumentRule] = None) -> dict:
    """A row as the tools list it."""
    return _kept({
        "row_id": row.id, "upload_id": row.upload_id, "file": names.get(row.upload_id), "kind": row.document_type,
        "date": row.date, "description": row.description, "counterparty": row.counterparty,
        "direction": row.direction.value, "gross": row.gross, "vat": row.vat, "account_code": row.account_code,
        "account_name": row.account_name,
        # A row paying a document posts against the account its document was owed on, not its own account.
        "posts_against": row.paid_against, "posts_against_name": row.paid_against_name if row.paid_against else None,
        "issues": [_kept({"code": i.code, "family": family_of(i.code), "severity": i.severity, "message": i.message,
                          "related_rows": i.related}) for i in row.issues],
        "held": {"needs": held.needs, "reason": held.reason} if held else None,
    })


def _to_look_at(built: Ledger) -> list[tuple[SavedRow, Optional[DocumentRule], set[str]]]:
    """The year's rows that need a look, by row id: those with a warning or an error, and those the document rules
    hold in Suspense; each with its rule if held and the families it falls in. Rows a decision took out of the books
    or replaced are left out."""
    settings = settings_for(built.client)
    found = []
    for row in sorted(built.transactions, key=lambda r: r.id):
        if row.excluded or row.superseded_by:
            continue
        held = _held(row, settings)
        families = {family_of(i.code) for i in row.issues if i.severity != "info"} | ({"documents"} if held else set())
        if families:
            found.append((row, held, families))
    return found


def _related(row: SavedRow, rows: list[SavedRow]) -> list[SavedRow]:
    """The rows an issue on the row names, and the records matching pairs it with, either way round."""
    def refs(r: SavedRow) -> set[str]:
        matched = [s for name in _MATCHES for s in (getattr(r, name) if isinstance(getattr(r, name), list)
                                                    else [getattr(r, name)]) if s]
        return {s.ref for s in matched} | set(r.recorded_by_refs)   # a claim line's receipts, when several

    named, its = {n for i in row.issues for n in i.related}, refs(row)
    return [o for o in rows if o.id != row.id and (o.id in named or (o.document_ref and o.document_ref in its)
                                                   or (row.document_ref and row.document_ref in refs(o)))]


def _bank_position(store, client_id: int, year_start) -> dict:
    """Each bank account's books against its latest statement, and what paperwork is missing; empty while rows need
    fixing, which blocks the trial balance these are worked out from."""
    summary = books.summary(store, client_id, year_start)
    return {"bank": [{"account": c.name, "code": c.code, "books": c.books, "statement": c.statement,
                      "statement_date": c.statement_date, "difference": c.difference,
                      "agrees": c.difference is not None and c.difference == 0} for c in summary.bank],
            "missing_paperwork": summary.missing_paperwork}


# What five of the tools return, before it is made JSON: the tools call these, and so does the briefing a specialist
# starts its turn from (briefing.py), which therefore says exactly what the tools would.

def overview(deps: AgentDeps, ctx: ChatContext) -> dict:
    """What get_overview returns."""
    store, records = deps.store, deps.records
    built = books.ledger(store, ctx.client_id, ctx.year_start)
    looked = _to_look_at(built)
    return {
        "client": {"name": built.client.name, "business_type": built.client.business_type,
                   "vat_registered": built.client.vat_registered},
        "years": [y.label for y in built.years],
        "year": {"start": built.year.start, "end": built.year.end, "label": built.year.label,
                 "closed": built.year.closed},
        "rows": len(built.transactions), "documents": len(built.uploads),
        "need_a_look": dict(Counter(f for _, _, families in looked for f in families)),
        "held_in_suspense": sum(held is not None for _, held, _ in looked),
        "open_questions": len(records.questions(ctx.client_id, ctx.year_start)),
        "decisions": len(records.decisions(ctx.client_id, ctx.year_start)),
        "background_reviews_since_last_chat": _reviews_since_last_chat(records, ctx),
        "accounts": [{"code": a.code, "name": a.name}
                     for a in choosable(built.client.business_type, bank_choices(built.client),
                                        owners_of(built.client))],
        **_bank_position(store, ctx.client_id, ctx.year_start),
    }


def issues(deps: AgentDeps, ctx: ChatContext, family: Optional[Family] = None, after_row_id: int = 0,
           limit: int = 20) -> dict:
    """What list_issues returns."""
    built = books.ledger(deps.store, ctx.client_id, ctx.year_start)
    rows = [(row, held) for row, held, families in _to_look_at(built)
            if row.id > after_row_id and (family is None or family in families)]
    names = {u.id: u.name for u in built.uploads}
    page = rows[:limit]
    return _kept({"rows": [_brief(row, names, held) for row, held in page],
                  "next_after_row_id": page[-1][0].id if len(rows) > limit else None})


def open_questions(deps: AgentDeps, ctx: ChatContext) -> dict:
    """What list_questions returns: the chat year's questions, and the books' own questions of the client's other
    open years (a books question is asked in the earliest open year it belongs to), each with its year and any answer
    offered for the person to confirm."""
    closed = {c.start for c in deps.store.get_client(ctx.client_id).closed_years}
    asked = [q for q in deps.records.questions(ctx.client_id, None) if q.year_start == ctx.year_start
             or (q.source == "rules" and q.year_start not in closed)]
    return {"questions": [_kept({"question_id": q.id, "year_start": q.year_start.isoformat(), "kind": q.kind,
                                 "text": q.text, "why": q.why, "status": q.status, "answer": q.answer,
                                 "row_ids": q.row_ids, "asked_by": q.source, "asked_at": q.created_at,
                                 "offer": q.offer.model_dump(mode="json", by_alias=True) if q.offer else None})
                          for q in asked]}


_ANSWER_TO = re.compile(r'^Answer to ".*?":\s*', re.DOTALL)


def _own_words(text: str) -> str:
    """A message without the question it quotes: a card's answer is sent as 'Answer to "<question>": <words>', and a
    reply may quote the question in lines starting "> "."""
    text = _ANSWER_TO.sub("", text.strip())
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">")).strip()


def person_said(state) -> list[str]:
    """The person's own words in the chat so far: the app's notes in the chat's memory are not theirs, nor the
    question a reply quotes."""
    messages = (state or {}).get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    return [_own_words(m.content if isinstance(m.content, str) else str(m.content)) for m in messages
            if isinstance(m, HumanMessage) and not (m.additional_kwargs or {}).get("note")]


def changes(deps: AgentDeps, ctx: ChatContext, when: Optional[str] = None, limit: int = 50) -> dict:
    """What list_changes returns for the changes since `when` (as the changes' times are kept), at most `limit`."""
    made = deps.records.changes(ctx.client_id, year_start=ctx.year_start, since=when, limit=limit)
    return {"changes": [_kept({
        "changed_at": c.created_at, "by": c.actor, "kind": c.kind, "summary": c.summary, "row_ids": c.row_ids,
        "upload_id": c.upload_id, "before": c.before, "after": c.after}) for c in made]}


def trial_balance(deps: AgentDeps, ctx: ChatContext) -> dict:
    """What get_trial_balance returns."""
    store, records = deps.store, deps.records
    tb = ledger_book.posted_trial_balance(store, records, ctx.client_id, ctx.year_start)
    # Rows changed since the last posting (an edit on a page, a new upload): the figures a person sees on the
    # Trial balance page are the books as they stand, so those are given, and said.
    unposted = ledger_book.unposted_changes(store, records, ctx.client_id, ctx.year_start)
    now = None
    if unposted and tb.journal:
        try:
            now = books.trial_balance_shown(store, ctx.client_id, ctx.year_start)
        except InvalidTransactions:
            now = None
    shown = now or tb
    note = (f"{_count(unposted, 'row')} changed since the last posting: these are the books as they stand now, "
            "as the Trial balance page shows them." if now else
            None if tb.journal else "Nothing is posted yet for this year: the system posts at the end of the "
                                    "turn. This isn't a sign the year has no rows; list_rows shows them.")
    return _kept({
        "lines": [{"code": l.code, "name": l.name, "debit": l.debit, "credit": l.credit} for l in shown.lines],
        "total_debits": shown.total_debits, "total_credits": shown.total_credits,
        "is_balanced": shown.is_balanced, "entries_posted": len(tb.journal),
        "suspense": [_kept(s.model_dump()) for s in tb.suspense], "problems": tb.problems, "note": note})


def make_tools(deps: AgentDeps, actor: str) -> list[BaseTool]:
    """The tools, working on deps. actor: who resolve_issue records its decisions as made by ("agent:<model>")."""
    store, records = deps.store, deps.records

    def texts(client_id: int) -> Callable[[int], list[str]]:
        return upload_texts(deps, client_id)

    @tool
    def get_overview(runtime: ToolRuntime[ChatContext]) -> dict:
        """The client, its years, and the year this chat is on: its rows and documents, how many rows need a look in
        each family of issue, how many are held in Suspense for a document, the questions still open, the
        decisions made so far, the background reviews since the last chat, the accounts a row can be coded to (code and name),
        each bank account's balance in the books against its latest statement (agrees only when the difference is
        £0.00), and the statements the books are missing."""
        ctx = runtime.context
        _step(runtime, "Looking over the books…")
        result = overview(deps, ctx)
        _step(runtime, "Looked over the books", "done")
        return _out(result)

    @tool
    def list_issues(runtime: ToolRuntime[ChatContext],
                    family: Annotated[Optional[Family], Field(description="Only rows with an issue of this family; "
                                                                           "all rows that need a look when left out.")]
                    = None,
                    after_row_id: Annotated[int, Field(ge=0, description="List rows after this row id, to page "
                                                                          "through them.")] = 0,
                    limit: Annotated[int, Field(ge=1, le=20, description="The most rows to list.")] = 20) -> dict:
        """The year's rows that need a look, by row id: each with its issues (code, family, message and the rows it
        names) and, if the document rules hold it in Suspense, the document it needs. Families: date, duplicate,
        combined_vat (one VAT total over items at different rates), conflict (two records disagree), missing_vat (VAT
        on the document but not booked), documents (a document missing, or held in Suspense for one), coding (the
        account a purchase is on), other."""
        ctx = runtime.context
        _step(runtime, "Listing what needs a look…")
        result = issues(deps, ctx, family, after_row_id, limit)
        found = len(result.get("rows", []))
        _step(runtime, f"Found {_count(found, 'row')} that {'needs' if found == 1 else 'need'} a look", "done")
        return _out(result)

    @tool
    def list_rows(runtime: ToolRuntime[ChatContext],
                  upload_id: Annotated[Optional[int], Field(description="Only the rows read from this document "
                                                                        "(an id from list_documents).")] = None,
                  after_row_id: Annotated[int, Field(ge=0, description="List rows after this row id, to page "
                                                                       "through them.")] = 0,
                  limit: Annotated[int, Field(ge=1, le=50, description="The most rows to list.")] = 20) -> dict:
        """The year's rows by row id, with or without issues: each as list_issues shows it, plus whether it is
        booked. upload_id: only the rows read from that document (ids from list_documents). Rows a decision took out
        of the books or replaced are left out. Page with after_row_id."""
        ctx = runtime.context
        _step(runtime, "Listing the rows…")
        built = books.ledger(store, ctx.client_id, ctx.year_start)
        settings = settings_for(built.client)
        rows = [row for row in sorted(built.transactions, key=lambda r: r.id)
                if row.id > after_row_id and not row.excluded and not row.superseded_by
                and (upload_id is None or row.upload_id == upload_id)]
        names = {u.id: u.name for u in built.uploads}
        page = rows[:limit]
        result = _kept({"rows": [{**_brief(row, names, _held(row, settings)), "booked": booked(row)} for row in page],
                        "next_after_row_id": page[-1].id if len(rows) > limit else None})
        _step(runtime, f"Listed {_count(len(page), 'row')}", "done")
        return _out(result)

    @tool
    def get_row(row_id: Annotated[int, Field(description="The row's id.")],
                runtime: ToolRuntime[ChatContext]) -> dict:
        """One row in full: what was read, what is booked, its issues, the records it is matched with (paid_by,
        pays, recorded_by, claimed_in, copy_of), what the original reading said before a person's edit, the rows it
        is related to, and the decisions already made on it."""
        ctx = runtime.context
        _step(runtime, f"Looking at row {row_id}…")
        rows = books.all_rows(store, ctx.client_id)
        row = next((r for r in rows if r.id == row_id), None)
        if row is None:
            raise NotFound(f"Row {row_id} was not found among this client's rows.")
        names = {u["id"]: u["name"] for u in store.uploads(ctx.client_id)}
        held = _held(row, settings_for(store.get_client(ctx.client_id)))
        result = {**_brief(row, names, held), **_kept({
            "booked": booked(row), "vat_posted": row.vat_posted, "net": row.net,
            "contra_account_code": row.contra_account_code, "document_number": row.document_number,
            "document_total": row.document_total, "document_net": row.document_net,
            "supplier_vat_number": row.supplier_vat_number, "not_vat_invoice": row.not_vat_invoice or None,
            "excluded": row.excluded or None, "superseded_by": row.superseded_by, "edited": row.edited or None,
            "as_read": row.original, "paid_by": row.paid_by, "pays": row.pays, "recorded_by": row.recorded_by,
            "claimed_in": row.claimed_in, "copy_of": row.copy_of, "date_found": row.date_found,
            "amount_found": row.amount_found, "vat_found": row.vat_found,
            "related": [_brief(o, names) for o in _related(row, rows)],
            "decisions": [{"decision_id": d.id, "rule": d.rule, "status": d.status, "reason": d.reason}
                          for d in records.decisions(ctx.client_id) if row_id in d.row_ids],
        })}
        _step(runtime, f"Looked at row {row_id}", "done")
        return _out(result)

    @tool
    def list_documents(runtime: ToolRuntime[ChatContext],
                       year_start: Annotated[Optional[dt.date], Field(description=(
                           "Another year's documents, by the year's first day (last year's invoices for an opening "
                           "balance question); the chat's year when left out."))] = None) -> dict:
        """The year's documents: each upload's id, file name, kind, how many rows were read from it, and for a bank
        statement whether its lines agree with the balances it prints. list_rows with an upload_id gives its rows."""
        ctx = runtime.context
        _step(runtime, "Listing the documents…")
        uploads = books.ledger(store, ctx.client_id, year_start or ctx.year_start).uploads
        result = {"documents": [_kept({"upload_id": u.id, "name": u.name, "kind": u.kind, "rows": u.rows,
                                       "added": u.created_at, "bank_account": u.bank_account,
                                       "statement_check": _kept(u.statement.model_dump()) if u.statement else None})
                                for u in uploads]}
        _step(runtime, f"Listed {_count(len(uploads), 'document')}", "done")
        return _out(result)

    @tool
    def read_document(upload_id: Annotated[int, Field(description="The document's upload id.")],
                      runtime: ToolRuntime[ChatContext],
                      page: Annotated[int, Field(ge=1, description="Which page of its text, from 1.")] = 1) -> dict:
        """The text of one of the client's original documents, a page at a time (12,000 characters at most a page),
        with how many pages it has. Images and scans are transcribed once and kept."""
        ctx = runtime.context
        upload = next((u for u in store.uploads(ctx.client_id) if u["id"] == upload_id), None)
        if upload is None:
            raise NotFound(f"Document {upload_id} was not found among this client's documents.")
        name = upload["name"]
        _step(runtime, f"Opening {name}…")
        pages = documents.text_of(upload, deps.blobs, records, deps.vision)
        if not pages:
            raise InvalidInput(f"{name} has no text to read: it was typed in, or replaced by a split.")
        if page > len(pages):
            raise InvalidInput(f"{name} has {_count(len(pages), 'page')} of text.")
        _step(runtime, f"Opened {name}" + (f", page {page}" if page > 1 else ""), "done")
        return {"upload_id": upload_id, "name": name, "page": page, "pages": len(pages), "text": pages[page - 1]}

    @tool
    def resolve_issue(row_id: Annotated[int, Field(description="The row the resolution is about.")],
                      resolution: AgentResolution,
                      evidence: Annotated[list[Evidence], BeforeValidator(_evidence_from_json), Field(
                          min_length=1, max_length=3,
                          description="One to three quotes, each exactly as printed in the document with this upload "
                                      "id: the row's own, that of a record it is matched with or named as "
                                      "source_row_id, or the bank line that pays the invoice or receipt being kept. "
                                      "For set_date from a file name, quote the file name. upload_name is "
                                      "filled in for you.")],
                      reason: Annotated[str, Field(min_length=1, max_length=600,
                                                   description="Why, in a sentence or two the person will read.")],
                      runtime: ToolRuntime[ChatContext]) -> dict:
        """Resolves an issue on a row, when the evidence settles it. keep_one: the same purchase recorded more than
        once; keep the best-ranked record and drop the other records of it. A bank line that pays the receipt or
        invoice you keep is its payment, not a duplicate: leave it out of drop_row_ids. row_id can be the kept row.
        use_primary: two records disagree; use the better-ranked one. split_vat: one VAT total over items at
        different rates; split the row into parts that add up exactly to it, with VAT at each part's rate matching the
        VAT printed. set_vat_from_document: the document prints VAT the row doesn't book. set_date: a row with no date,
        two dates or another date in its file name; the date from another record of the same purchase
        (source_row_id), a date printed in the row's document (quote it), or the file name of a row with no date
        (quote the file name). who_was_there: a meal or drink the books ask who was at; who the documents show was
        there (the claimant alone, staff only, or any guest) moves it to Subsistence, Staff Welfare or Entertainment
        and answers the question. The services check the
        resolution against the evidence and refuse what it doesn't support, saying
        why. Sent again once applied, it returns the same decision."""
        ctx = runtime.context
        _step(runtime, f"Checking row {row_id}…")
        with deps.locks.hold(ctx.client_id):
            decision = resolve(store, records, client_id=ctx.client_id, thread_id=ctx.thread_id, actor=actor,
                               row_id=row_id, resolution=resolution, evidence=evidence, reason=reason,
                               texts=texts(ctx.client_id), trigger=ctx.trigger, review_id=ctx.review_id,
                               suggest=ctx.mode == "suggest")
        if decision.status == "suggested":
            _step(runtime, f"Row {row_id}: suggested {decision.rule}", "done")
            return _out({"decision_id": decision.id, "status": "suggested", "rule": decision.rule,
                         "before": decision.before, "after": decision.after,
                         "note": "Suggested only: nothing has changed. A person applies it or leaves it. Say you "
                                 "suggest it, never that you did it."})
        if decision.status != "applied":
            _step(runtime, f"Didn't change row {row_id}", "failed", decision.reason)
            return {"status": "refused", "why": decision.reason}
        _step(runtime, f"Row {row_id}: {decision.rule}", "done")
        return _out({"decision_id": decision.id, "status": "applied", "rule": decision.rule,
                     "before": decision.before, "after": decision.after})

    @tool
    def edit_row(row_id: Annotated[int, Field(description="The row to change.")],
                 change: RowEdit,
                 reason: Annotated[str, Field(min_length=1, max_length=400,
                                              description="What the person asked for, in a sentence they will read.")],
                 runtime: ToolRuntime[ChatContext]) -> dict:
        """Changes a row as the person in this chat told you to: its account, its VAT (vat, or no_vat to clear it;
        reclaim_vat true when they say to reclaim VAT the books hold back, such as a row waiting for a VAT invoice), its
        VAT treatment, date, amount, description or direction; marks warnings on it as fine (accept_warnings); keeps
        it apart from rows the person says are different purchases (not_same_as: answers a possible duplicate); or
        books a row held in Suspense without its receipt (without_document, the person's reason). Use it when the
        person says what a row should be, in a message or in their answer to a question: "put the toll to Travel",
        "use the VAT on the claim", "that warning is fine". Give only the fields to change. The person's word is the
        authority, so no evidence is needed, but never use it on your own judgement, and it is refused in a
        background review. The books check the change as they check an edit and refuse what can't be booked, saying
        why. It is shown to the person as a change they can undo."""
        ctx = runtime.context
        if ctx.trigger != "chat":
            _step(runtime, f"Didn't change row {row_id}", "failed", "Only a person in a chat can ask for this.")
            return {"status": "refused", "why": "edit_row makes a change a person asked for in a chat. In a "
                                                "background review, use resolve_issue or ask_user."}
        _step(runtime, f"Changing row {row_id}…")
        with deps.locks.hold(ctx.client_id):
            decision = edit_as_told(store, records, client_id=ctx.client_id, thread_id=ctx.thread_id, actor=actor,
                                    row_id=row_id, edit=change, reason=reason)
        if decision.status != "applied":
            _step(runtime, f"Didn't change row {row_id}", "failed", decision.reason)
            return {"status": "refused", "why": decision.reason}
        _step(runtime, f"Row {row_id}: changed as asked", "done")
        return _out({"decision_id": decision.id, "status": "applied", "before": decision.before,
                     "after": decision.after,
                     "note": "Changed. A question you asked about this row closes by itself after this turn."})

    @tool
    def ask_user(row_ids: Annotated[list[int], Field(description="The rows the question is about.")],
                 question: Annotated[str, Field(min_length=1, max_length=300,
                                                description="One specific question, in a plain sentence.")],
                 why: Annotated[str, Field(min_length=1, max_length=400,
                                           description="Why it matters, and what would settle it.")],
                 runtime: ToolRuntime[ChatContext]) -> dict:
        """Asks the person a question the evidence can't settle and the rules don't already ask. It is shown as a
        card in this reply, and stays open on the client until it is answered. Asked again with the same rows
        and words, it is the same question."""
        ctx = runtime.context
        _step(runtime, "Writing a question…")
        known = {r.id for r in store.rows(ctx.client_id)}
        stray = [n for n in row_ids if n not in known]
        if stray:
            raise NotFound(f"Row {stray[0]} was not found among this client's rows.")
        # The books ask these after the turn; asking too would put two questions to the person about one thing.
        covered: dict[int, list[str]] = {}
        for q in questions.rule_questions(store, ctx.client_id, ctx.year_start):
            for n in q.row_ids:
                if n in row_ids:
                    covered.setdefault(n, []).append(q.kind)
        if covered:
            what = {"date": "a date", "receipt_or_invoice": "a receipt or invoice", "vat_invoice": "a VAT invoice"}
            named = ", ".join(f"row {n} ({' and '.join(what.get(k, k) for k in kinds)})"
                              for n, kinds in sorted(covered.items()))
            if len(covered) == len(set(row_ids)):
                message = f"The books already ask the person about {named}, so there's no need to ask."
                _step(runtime, "The books already ask this", "done")
                return {"asked": False, "message": message}
            row_ids = [n for n in row_ids if n not in covered]
            dropped = f"The books already ask the person about {named}, so the question is about the other rows only."
        else:
            dropped = None
        asked = questions.ask(records, client_id=ctx.client_id, year_start=ctx.year_start, row_ids=row_ids,
                              text=question.strip(), why=why.strip())
        _step(runtime, f"Asked: {asked.text}", "done")
        return {"question_id": asked.id, "status": asked.status, **({"note": dropped} if dropped else {})}

    @tool
    def close_question(question_id: Annotated[str, Field(description="A question you asked (an id from list_questions "
                                                                     "whose asked_by is agent).")],
                       reason: Annotated[str, Field(min_length=1, max_length=300,
                                                    description="Why the question no longer needs asking, in a "
                                                                "sentence the person will read.")],
                       runtime: ToolRuntime[ChatContext],
                       evidence: Annotated[list[Evidence], BeforeValidator(_evidence_from_json), Field(
                           max_length=3, description="Quotes, exactly as printed in the documents of the question's "
                                                     "rows, that answer it. Not needed when a person has changed "
                                                     "one of its rows since it was asked.")] = []) -> dict:
        """Closes a question you asked that the books have since answered: a person changed one of its rows after it
        was asked, or a document of its rows (quoted in evidence) says the answer. The services check this and refuse
        otherwise, saying why. Questions the rules ask can't be closed."""
        ctx = runtime.context
        _step(runtime, "Checking whether the question is answered…")
        with deps.locks.hold(ctx.client_id):
            decision = questions.close(store, records, client_id=ctx.client_id, year_start=ctx.year_start,
                                       question_id=question_id, reason=reason,
                                       evidence=evidence, texts=texts(ctx.client_id), actor=actor,
                                       trigger=ctx.trigger, review_id=ctx.review_id, suggest=ctx.mode == "suggest")
        if decision.status == "refused":
            _step(runtime, "Left the question open", "failed", decision.reason)
            return {"status": "refused", "why": decision.reason}
        _step(runtime, "Closed the question" if decision.status == "applied" else "Suggested closing the question",
              "done")
        return _out({"decision_id": decision.id, "status": decision.status, "rule": decision.rule})

    @tool
    def offer_answer(question_id: Annotated[str, Field(description="A books question (asked_by rules) of kind "
                                                                    "opening_vat, opening_prepayments, "
                                                                    "opening_accruals or bad_debt.")],
                     answer: Annotated[questions.OfferedAnswer, Field(description=(
                         "The answer: {kind: split, lines: [{account, amount}]} for the VAT difference or an opening "
                         "balance, the lines adding up to the question's amount; {kind: write_off, date} for a bad "
                         "debt (date left out: when its six months end)."))],
                     sources: Annotated[list[OfferSource], Field(min_length=1, description=(
                         "Where each part comes from. At least one {kind: said, quote} quoting the person's own "
                         "words in this chat. {kind: document, upload_id, quote, for: 'line:<n>' or 'date', working} "
                         "for a figure from one of the client's documents (any year), with how you worked it out. "
                         "{kind: question} when a figure is the question's own amount or the default date."))],
                     reason: Annotated[str, Field(min_length=1, max_length=300,
                                                  description="Why this is the answer, in a sentence the person reads.")],
                     runtime: ToolRuntime[ChatContext]) -> dict:
        """Fills in the answer card of one of the books' own questions (the VAT difference, the opening prepayments
        or accruals, a bad debt) from what the person said in this chat, for them to change or confirm. Use it when
        their words, with the documents, settle the answer: quote their words, and work out any amounts from
        documents you quote, saying how. Nothing is booked: the books check it as they check the card's answer and
        refuse what they would refuse, saying why. It is refused in a background review. The person confirms on the
        card: never say it is booked."""
        ctx = runtime.context
        if ctx.trigger != "chat":
            _step(runtime, "Didn't fill in the answer", "failed", "Only a person in a chat can answer.")
            return {"status": "refused", "why": "Only a person in a chat can answer a books question: offer_answer "
                                                "fills in an answer from their words, so it isn't used in a review."}
        _step(runtime, "Filling in the answer…")
        try:
            with deps.locks.hold(ctx.client_id):
                made = questions.offer(store, records, client_id=ctx.client_id, thread_id=ctx.thread_id,
                                       question_id=question_id, answer=answer, sources=sources, reason=reason,
                                       texts=texts(ctx.client_id), said=person_said(runtime.state), actor=actor)
        except InvalidInput as exc:
            _step(runtime, "Didn't fill in the answer", "failed", exc.message)
            return {"status": "refused", "why": exc.message}
        _step(runtime, "Filled in the answer for the person to confirm", "done")
        return {"status": "offered", "question_id": made.id,
                "note": "Filled in on the question's card: the person confirms it there. Nothing is booked yet."}

    @tool
    def list_questions(runtime: ToolRuntime[ChatContext]) -> dict:
        """The questions still open on the client's year, from this chat or earlier ones: what each asks and why,
        its rows, whether it is open or waiting (the person said "I don't have it" or "Not sure"), and who asked it
        (the rules or the agent)."""
        ctx = runtime.context
        _step(runtime, "Checking the open questions…")
        result = open_questions(deps, ctx)
        asked = result["questions"]
        _step(runtime, f"{_count(len(asked), 'question')} still open" if asked else "No questions open", "done")
        return _out(result)

    @tool
    def list_decisions(runtime: ToolRuntime[ChatContext]) -> dict:
        """The decisions made on the client's year so far, oldest first, by the agent, the rules or the person:
        each with its rule, whether it was applied or refused, its rows, the reason, the evidence quoted, and the
        values before and after."""
        ctx = runtime.context
        _step(runtime, "Checking the decisions so far…")
        made = records.decisions(ctx.client_id, ctx.year_start)
        result = {"decisions": [_kept({
            "decision_id": d.id, "made_at": d.created_at, "by": d.actor, "action": d.action, "rule": d.rule,
            "status": d.status, "row_ids": d.row_ids, "reason": d.reason,
            "evidence": [{"upload_id": e.upload_id, "file": e.upload_name, "quote": e.quote} for e in d.evidence],
            "before": d.before, "after": d.after}) for d in made]}
        _step(runtime, f"Read {_count(len(made), 'decision')}", "done")
        return _out(result)

    @tool
    def list_changes(runtime: ToolRuntime[ChatContext], since: Optional[str] = None) -> dict:
        """What has changed on the client's year, oldest first: who changed it (the person, an import, the rules or
        the agent), what kind of change, the rows and file it touched, the values before and after, and a one-line
        summary. since: an ISO date and time (a trailing Z or an offset is fine); leave it out for the latest 50. With
        since, at most 200 come back and "more" says there were more. Use it to say what has changed since the last
        review."""
        ctx = runtime.context
        _step(runtime, "Checking what has changed…")
        when = None
        if since:
            try:
                parsed = dt.datetime.fromisoformat(since.strip().replace("Z", "+00:00").replace("z", "+00:00"))
            except ValueError:
                _step(runtime, "Couldn't read the time", "done")
                return {"error": "since must be an ISO date and time, for example 2026-11-04T10:00:00"}
            when = parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
            when = when.isoformat(timespec="seconds")   # as the changes' times are kept
        limit = 200 if since else 50
        result = changes(deps, ctx, when, limit)
        made = result["changes"]
        if since and len(made) >= limit:
            result["more"] = True
        _step(runtime, f"Read {_count(len(made), 'change')}" if made else "Nothing has changed", "done")
        return _out(result)

    @tool
    def get_trial_balance(runtime: ToolRuntime[ChatContext]) -> dict:
        """The trial balance of what is posted for the client's year (the opening balances and every entry posted so
        far): each account's debit and credit, the totals, whether it balances, the rows held in Suspense and what
        each needs, and any problems. The system posts at the end of each turn, so this turn's changes aren't in it
        yet."""
        ctx = runtime.context
        _step(runtime, "Checking the posted trial balance…")
        result = trial_balance(deps, ctx)
        _step(runtime, "Checked the posted trial balance", "done")
        return _out(result)

    @tool
    def get_vat_figures(runtime: ToolRuntime[ChatContext],
                        start: Annotated[Optional[str], Field(description="The first day of the period, YYYY-MM-DD; "
                                                                          "leave out for the whole year.")] = None,
                        end: Annotated[Optional[str], Field(description="The last day of the period, YYYY-MM-DD; "
                                                                        "leave out for the whole year.")] = None
                        ) -> dict:
        """The nine VAT return boxes for the client's year, or for a period inside it, exactly as the VAT card on the
        Trial balance page shows them, with notes on what they leave out. Use it for every VAT box figure; never
        work a box out from the rows or the trial balance."""
        ctx = runtime.context
        _step(runtime, "Working out the VAT figures…")
        try:
            figures = books.vat_figures(store, ctx.client_id, ctx.year_start,
                                        dt.date.fromisoformat(start) if start else None,
                                        dt.date.fromisoformat(end) if end else None)
        except (InvalidInput, InvalidTransactions, ValueError) as exc:
            _step(runtime, "Couldn't work out the VAT figures", "failed", str(exc))
            return {"status": "refused", "why": getattr(exc, "message", None) or str(exc)}
        _step(runtime, "Worked out the VAT figures", "done")
        return _out(figures.model_dump())

    @tool
    def hand_over(why: Annotated[str, Field(min_length=1, max_length=300,
                                            description="Why the request is outside your part, in a sentence.")],
                  runtime: ToolRuntime[ChatContext]) -> dict:
        """Gives the rest of this turn to the lead accountant, who has every tool, when the request is outside your
        part. Call it straight away, before anything else, instead of attempting the work or replying that you
        can't do it."""
        ctx = runtime.context
        ctx.specialist, ctx.handed_over = "lead", True   # the run's next model call is the lead's (middleware.Specialists)
        _step(runtime, "Passed to the lead accountant", "done")
        return {"handed_over": True, "note": "You are now the lead accountant, with every tool. Carry on with the "
                                             "person's request; don't mention the hand-over."}

    # hand_over is the specialists' own: the lead accountant is never offered it (specialists.PROFILES).
    return [get_overview, list_issues, list_rows, get_row, list_documents, read_document, resolve_issue, edit_row,
            ask_user,
            close_question, offer_answer, list_questions, list_decisions, list_changes, get_trial_balance, get_vat_figures,
            hand_over]
