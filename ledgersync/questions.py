"""The accountant chat's questions for the person. The rules work them out from the books: a booked row with no date
asks for one, a row held in Suspense by the document rules asks for the document. A person's answer is applied here
without the model: a date goes through resolutions.set_date, "I don't have it" and "Not sure" leave the question
waiting. After an answer the questions are worked out again and the year is posted. A question goes when the books
no longer need it. One of the agent's own goes when a person has changed a row it is about since it was asked, or none
of its rows is in the books any more: it asked about the books as they were. An uploaded document is not an answer
here: the API reads it into the client's documents and then calls refresh."""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Annotated, Literal, NamedTuple, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from decimal import ROUND_HALF_UP, Decimal

from . import books, ledger, ledger_book
from .accounts import ALL_BANK_CODES, BY_CODE, AccountType
from .checks import booked, long_date
from .errors import InvalidInput, NotFound
from .evidence_rules import document_rule
from .ledger import settings_for
from .models import (ChangeDraft, Decision, DecisionDraft, Evidence, Ledger, ManualUpload, Offer, OfferSource,
                     PostResult, Question, QuestionDraft, RowPatch, Transaction)
from .money import ZERO
from .payees import processor
from .records import AgentRecords
from .resolutions import _SHORTEST_QUOTE, Texts, _normalised, check_quotes, set_date
from .rows import now_iso
from .store_mongo import MongoStore

_OVER = {"receipt_or_invoice": "£50 or more", "vat_invoice": "Over £250"}
_ASKS = {"receipt_or_invoice": "Can you upload the receipt or invoice?",
         "vat_invoice": "Can you upload the full VAT invoice?"}
# The questions a document answers: those of the document rules, and a payout or payroll report the books lack.
DOCUMENT_KINDS = frozenset({*_ASKS, "payout_report", "payroll_report"})


class DateAnswer(BaseModel):
    kind: Literal["date"]
    date: dt.date


class NoDocumentAnswer(BaseModel):
    kind: Literal["no_document"]


class NotSureAnswer(BaseModel):
    kind: Literal["not_sure"]


class WithoutDocumentAnswer(BaseModel):
    """Book the purchase without the receipt or invoice it needs: no VAT reclaimed. Only a person answers so."""
    kind: Literal["without_document"]
    reason: str


class WriteOffAnswer(BaseModel):
    """Write the invoice off as a bad debt, on the date given (by default the day its six months overdue end)."""
    kind: Literal["write_off"]
    date: Optional[dt.date] = None


class SplitLine(BaseModel):
    account: str
    amount: Decimal


class SplitAnswer(BaseModel):
    """Which costs an opening prepayment or accrual is for: the lines add up to what is still to be released."""
    kind: Literal["split"]
    lines: list[SplitLine]


Answer = Annotated[Union[DateAnswer, NoDocumentAnswer, NotSureAnswer, WithoutDocumentAnswer, SplitAnswer,
                         WriteOffAnswer],
                   Field(discriminator="kind")]
# An opening balance on Prepayments or Accruals is last year's: this year it is released, on the year's first day, to
# the costs it is for (a prepayment becomes a cost of this year; an accrual comes off the cost when its bill comes).
# The trial balance it came from doesn't say which costs, so the person is asked. kind: (account, word, its sign).
_OPENING = {"opening_prepayments": ("1103", "prepayments", 1), "opening_accruals": ("2109", "accruals", -1)}
BOOKED_WITHOUT = "Booked without a receipt: "


class Answered(NamedTuple):
    """What an answer leaves: the year's open and waiting questions, and the posting of the question's year."""
    questions: list[Question]
    post: PostResult


def _not_posted() -> PostResult:
    return PostResult(batch_id=None, entries_added=0, reversals_added=0, total_debits=ZERO, total_credits=ZERO)


def _gbp(amount) -> str:
    return f"£{amount:,.2f}"


def _on(tx: Transaction) -> str:
    return f" on {long_date(tx.date)}" if tx.date else ""


def _key(kind: str, row_id: Optional[int]) -> str:
    """The key a rule question is kept under: one date question and one document question per row, and one question
    for each opening balance to release."""
    if kind in _OPENING or kind == "opening_vat":
        return f"open:{kind}"
    if kind == "bad_debt":
        return f"debt:{row_id}"
    return f"{'date' if kind == 'date' else 'doc'}:{row_id}"


DUE_DAYS = 30   # an invoice records no due date: taken as 30 days after it


def _sales_owed(store: MongoStore, client_id: int, built: Ledger) -> list[Transaction]:
    """The booked sales invoices still owed as the year sees them: the year's own, and an earlier year's still unpaid,
    whose six months overdue may end in this one. A sale is on an income account (a supplier's credit note is not)."""
    def sale(tx: Transaction) -> bool:
        account = BY_CODE.get(tx.account_code)
        return (booked(tx) and tx.document_type == "invoice" and tx.direction.value == "in" and account is not None
                and account.type == AccountType.INCOME and bool(tx.owed) and tx.owed > ZERO)

    earlier = [r for r in books.all_rows(store, client_id) if r.date is not None and r.date < built.year.start]
    return [t for t in built.transactions if sale(t)] + [t for t in earlier if sale(t)]


def _overdue_from(tx: Transaction) -> Optional[dt.date]:
    """The day an invoice has been unpaid six months past its due date (its date plus DUE_DAYS)."""
    if tx.date is None:
        return None
    due = tx.date + dt.timedelta(days=DUE_DAYS)
    month = due.month + 6
    year, month = due.year + (month - 1) // 12, (month - 1) % 12 + 1
    last = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, month, min(due.day, last))


def _released(tx: Transaction, code: str, sign: int) -> Decimal:
    """What a journal takes off an opening balance on `code`: a prepayment (a debit) is released by crediting it, an
    accrual (a credit) by debiting it."""
    if tx.document_type != "journal":
        return ZERO
    debits = (tx.account_code == code) == (tx.direction.value == "out")
    touches = code in (tx.account_code, tx.contra_account_code)
    return tx.gross if touches and debits == (sign < 0) else ZERO


def _vat_difference(store: MongoStore, client_id: int, year_start: dt.date,
                    built: Ledger) -> Optional[tuple[Transaction, Decimal, Decimal]]:
    """When the year opens owing VAT and its first VAT payment differs from it: that payment, the VAT owed, and the
    difference still to account for (positive when more was paid), less what journals on the payment's day already
    take. None otherwise."""
    owed = -books.opening(store, client_id, year_start).get("2202", ZERO)
    if owed <= ZERO:
        return None
    paid = sorted((t for t in built.transactions if booked(t) and t.document_type == "statement"
                   and t.direction.value == "out" and t.account_code == "2202" and t.date), key=lambda t: t.date)
    if not paid:
        return None
    first = paid[0]
    difference = first.gross - owed
    sign = 1 if difference > ZERO else -1
    done = sum((_released(t, "2202", sign) for t in built.transactions if booked(t) and t.date == first.date),
               ZERO)
    left = difference - sign * done
    return (first, owed, left) if left != ZERO else None


def _opening_left(store: MongoStore, client_id: int, year_start: dt.date, built: Ledger) -> dict[str, Decimal]:
    """Each opening prepayment or accrual still to be released, by question kind: the opening balance less what the
    journals of the year's first day already release."""
    opening = books.opening(store, client_id, year_start)
    left = {}
    for kind, (code, _, sign) in _OPENING.items():
        balance = sign * opening.get(code, ZERO)
        done = sum((_released(t, code, sign) for t in built.transactions if booked(t) and t.date == year_start), ZERO)
        if balance - done > ZERO:
            left[kind] = balance - done
    return left


def _wanted(store: MongoStore, client_id: int,
            year_start: dt.date) -> tuple[dict[str, QuestionDraft], Ledger]:
    """The questions the year's books ask now, by key. A row with no date asks for one (a date in its file name is
    only ever offered on the row, never taken: matching dates a row from its bank line, so a row still undated has
    none). A booked row the document rules hold asks for the document it needs."""
    built = books.ledger(store, client_id, year_start)
    settings = settings_for(built.client)
    wanted: dict[str, QuestionDraft] = {}

    def want(tx: Transaction, kind: str, text: str, why: str) -> None:
        wanted[_key(kind, tx.id)] = QuestionDraft(client_id=client_id, year_start=year_start, row_ids=[tx.id],
                                                  kind=kind, text=text, why=why, source="rules")

    for tx in (t for t in built.transactions if booked(t)):
        if tx.date is None:
            want(tx, "date", f"When was this {tx.description}?",
                 f"{_gbp(tx.gross)}, no date on it and no matching bank line.")
        codes = {i.code for i in tx.issues}
        if "payout_report" in codes:
            who = processor(tx.counterparty, tx.description) or "payment processor"
            want(tx, "payout_report", f"Can you upload the {who} payout report?",
                 f"{_gbp(tx.gross)} paid out by {tx.counterparty or who}{_on(tx)} is sales less {who}'s fees and "
                 "refunds. Held in Payment Processor Clearing until the report shows each.")
        if "no_payroll" in codes and tx.date:
            want(tx, "payroll_report", f"Can you upload the payroll report for {tx.date:%B %Y}?",
                 f"{_gbp(tx.gross)} paid to {tx.counterparty or tx.description}{_on(tx)}, and no payroll report "
                 "books the wages it is for.")
        rule = document_rule(tx, settings)
        if rule.action == "hold" and rule.needs:
            when = f" on {long_date(tx.date)}" if tx.date else ""
            asks = _ASKS[rule.needs] if settings.vat_registered else _ASKS["receipt_or_invoice"]
            want(tx, rule.needs, asks,
                 f"{_gbp(tx.gross)} to {tx.counterparty or tx.description}{when}. {_OVER[rule.needs]}, so I need it. "
                 "Held in Suspense as Documentation required until then.")
    # Unpaid only as far as the statements in the books show: an invoice whose payment may be on a statement not yet
    # uploaded is not a bad debt. No statement at all: none can be told unpaid.
    statements = [t.date for t in built.transactions if booked(t) and t.document_type == "statement" and t.date]
    by = min(dt.date.today(), built.year.end, max(statements)) if statements else None
    # A question about the books brought in, or a debt gone bad, is asked in one year: the earliest open year it
    # arises in. Its key names no year, so a later year asking it too would take it over (the opening's
    # prepayments, never released while unanswered, are carried into every later year).
    closed = {c.start for c in built.client.closed_years}
    first_open = min((y.start for y in books.years_of(store, client_id, dt.date.today()) if y.start not in closed),
                     default=year_start)
    seen: set[str] = set()
    for tx in _sales_owed(store, client_id, built) if by else []:
        ref = tx.document_ref or f"row-{tx.id}"
        overdue = _overdue_from(tx)
        if overdue is not None and overdue < year_start and first_open <= overdue:
            continue   # it went bad in an earlier year still open: asked there
        if overdue is not None and overdue <= by and ref not in seen:
            seen.add(ref)
            want(tx, "bad_debt", f"Write off the {_gbp(tx.owed)} {tx.counterparty or 'the customer'} owes as a bad "
                                 "debt?",
                 f"Invoice {tx.document_number or tx.description} of {long_date(tx.date)} is unpaid more than six "
                 "months after it fell due. Written off, it is a cost (Bad Debts), and the VAT on it can be claimed "
                 "back as VAT bad debt relief.")
    if year_start != first_open:
        return wanted, built
    vat = _vat_difference(store, client_id, year_start, built)
    if vat is not None:
        payment, owed, left = vat
        wanted[_key("opening_vat", None)] = QuestionDraft(
            client_id=client_id, year_start=year_start, kind="opening_vat", source="rules", row_ids=[payment.id],
            text=f"The VAT payment of {_gbp(payment.gross)} on {long_date(payment.date)} is {_gbp(abs(left))} "
                 f"{'more' if left > ZERO else 'less'} than the {_gbp(owed)} owed when the year began: what was "
                 "the difference for?",
            why="It pays the VAT owed brought forward; the difference is this year's (a VAT figure corrected, "
                "interest or a penalty): choose the account for it.")
    for kind, amount in _opening_left(store, client_id, year_start, built).items():
        code, word, _ = _OPENING[kind]
        wanted[_key(kind, None)] = QuestionDraft(
            client_id=client_id, year_start=year_start, kind=kind, source="rules",
            text=f"Opening {word} of {_gbp(amount)}: which costs are they for?",
            why=(f"{BY_CODE[code].name} carried in from last year: this year it is released on "
                 f"{long_date(year_start)} to the costs it is for, and the trial balance it came from doesn't say "
                 "which." + (" A prepayment becomes a cost of this year." if code == "1103" else
                             " An accrual comes off the cost when its bill arrives.")))
    return wanted, built


def rule_questions(store: MongoStore, client_id: int, year_start: dt.date) -> list[QuestionDraft]:
    """The questions the year's books ask the person now, so the agent doesn't ask them again."""
    return list(_wanted(store, client_id, year_start)[0].values())


def _settled_by(store: MongoStore, client_id: int, q: Question) -> Optional[str]:
    """For a resolved document question, "Matched to <file>" when its row is now settled by a document, the file that
    document is in; otherwise None. A bank line pays a document (pays) or is recorded by it (recorded_by, as a card
    payment is by its receipt). The document is looked up among all the client's rows: a card receipt can sit in
    another year than its line."""
    if q.kind not in DOCUMENT_KINDS or not q.row_ids:
        return None
    rows = books.all_rows(store, client_id)
    tx = next((t for t in rows if t.id == q.row_ids[0]), None)
    if tx is None:
        return None
    if tx.without_document:
        return f"{BOOKED_WITHOUT}{tx.without_document}"
    ref = (tx.pays[0].ref if tx.pays else tx.recorded_by.ref if tx.recorded_by else
           tx.documented_by.ref if tx.documented_by else None)
    paid = next((t for t in rows if ref and t.document_ref == ref), None)
    name = next((u["name"] for u in store.uploads(client_id) if paid is not None and u["id"] == paid.upload_id), None)
    return f"Matched to {name}" if name else None


def _same(stored: Question, draft: QuestionDraft) -> bool:
    """Whether the stored question already says what the draft says."""
    return (stored.kind, stored.text, stored.why, stored.row_ids, stored.year_start) == (
        draft.kind, draft.text, draft.why, draft.row_ids, draft.year_start)


# A person's own changes to a row: after one, a question the agent asked about that row is about the row as it was.
_PERSON_CHANGES = frozenset({"row_edited", "row_removed", "row_reverted", "row_linked", "row_included", "rows_apart"})
CHANGED_SINCE = "You changed this row after it was asked."
ROWS_GONE = "Its row is no longer in the books."
SAID_APART = "You said these are not the same."
PAIRED_SINCE = "The papers it waited for came in later, and the books now pair each of its rows with them."


def _partners(rows) -> dict[int, set[int]]:
    """For each row, the rows matching pairs it with as records of the same purchase: the receipt or invoice a claim
    line or card payment is booked from, the claim it is on, a copy, and the bank line that pays a document."""
    by_ref: dict[str, list[int]] = {}
    for r in rows:
        if r.document_ref:
            by_ref.setdefault(r.document_ref, []).append(r.id)
    found: dict[int, set[int]] = {}
    for r in rows:
        refs = [s.ref for s in (r.recorded_by, r.copy_of, r.documented_by) if s is not None]
        refs += [s.ref for s in (r.pays or [])] + [s.ref for s in (r.paid_by or [])]
        for ref in refs:
            for other in by_ref.get(ref, []):
                if other != r.id:
                    found.setdefault(r.id, set()).add(other)
                    found.setdefault(other, set()).add(r.id)
    return found


def _close_answered(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date) -> None:
    """Resolves the year's open and waiting questions of the agent's that the books have moved past: none of its
    rows is in the books any more (removed, left out or replaced), a person said two of its rows are not the same
    (whenever they said it: a review that read the books just before may ask after), or a person changed one of them
    after it was asked, or every one of its rows is now paired with a record uploaded after it was asked (the card
    statement a question about receipts waited for). A question about no row is left alone. Each closing is recorded
    as a change."""
    asked = [q for q in records.questions(client_id, year_start) if q.source == "agent" and q.row_ids]
    if not asked:
        return
    rows = store.rows(client_id)
    in_books = {r.id for r in rows if not (r.tx.excluded or r.tx.superseded_by)}
    apart = {frozenset((r.id, other)) for r in rows for other in r.tx.apart_from}   # Not the same, by pair
    theirs = [c for c in records.changes(client_id, since=min(q.created_at for q in asked), limit=1000)
              if c.actor == "user" and c.kind in _PERSON_CHANGES]
    uploaded = {u["id"]: u["created_at"] for u in store.uploads(client_id)}
    first = min(q.created_at for q in asked)
    # Matching every row is the costly part: only when a person changed something, or papers came in, since.
    partners = (_partners(books.all_rows(store, client_id))
                if theirs or any(when > first for when in uploaded.values()) else {})
    row_upload = {r.id: r.upload_id for r in rows}

    def paired_since(q) -> bool:
        """Each of the question's rows still in the books has a partner from an upload added after it was asked."""
        kept = [n for n in q.row_ids if n in in_books]
        return bool(kept) and all(any(uploaded.get(row_upload.get(p), "") > q.created_at
                                      for p in partners.get(n, ())) for n in kept)

    for q in asked:
        # The rows the question is about, and the other record of each (a claim line's receipt, a bill's bank line):
        # a question about one of a pair is answered by a change to either.
        about = set(q.row_ids) | {p for n in q.row_ids for p in partners.get(n, ())}
        if not set(q.row_ids) & in_books:
            said = ROWS_GONE
        elif any(frozenset((a, b)) in apart for a in q.row_ids for b in q.row_ids if a != b):
            said = SAID_APART
        elif any(c.created_at > q.created_at and set(c.row_ids) & about for c in theirs):
            said = CHANGED_SINCE
        elif paired_since(q):
            said = PAIRED_SINCE
        else:
            continue
        records.set_question(q.id, "resolved", said)
        records.add_change(ChangeDraft(
            client_id=client_id, year_start=q.year_start, actor="rules", kind="question_closed", row_ids=list(q.row_ids),
            before={"question": {"status": q.status, "answer": q.answer}}, after={"question": {"status": "resolved"}},
            summary=f"Closed the question: {q.text} {said}"))


def close_answered(store: MongoStore, records: AgentRecords, client_id: int) -> None:
    """Resolves the agent's questions, of every year of the client, that the books have moved past (_close_answered).
    For a page that lists the questions: it shows none whose row has since been changed or removed, whether or not
    the books were settled after that change. It reads the questions once when the agent has none open."""
    years = {q.year_start for q in records.questions(client_id, None) if q.source == "agent" and q.row_ids}
    for year_start in sorted(years):
        _close_answered(store, records, client_id, year_start)


def refresh(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date) -> list[Question]:
    """Works the year's rule questions out from the books and keeps them: each is asked once under its key (asked
    again, it keeps its status and answer, so one waiting stays waiting), one that was resolved and is needed again
    is reopened, and one the books no longer need is resolved with no answer. The agent's questions that the books
    have moved past are resolved too (_close_answered).
    The year's questions are read once and only those that are new or have changed are written, so settling after
    every change costs a read when nothing moved. Returns the year's open and waiting questions, oldest first."""
    wanted, _ = _wanted(store, client_id, year_start)
    stored = {_key(q.kind, q.row_ids[0] if q.row_ids else None): q for q in records.questions(
        client_id, year_start, statuses=("open", "waiting", "resolved"))
        if q.source == "rules" and (q.row_ids or q.kind in _OPENING or q.kind == "opening_vat")}
    for key, draft in wanted.items():
        asked = stored.get(key)
        if asked is None or not _same(asked, draft):
            asked = records.upsert_question(draft, key)
        if asked.status == "resolved":
            records.set_question(asked.id, "open")
    for key, q in stored.items():
        if key not in wanted and q.status != "resolved":
            records.set_question(q.id, "resolved", _settled_by(store, client_id, q))
    _close_answered(store, records, client_id, year_start)
    return records.questions(client_id, year_start)


def ask(records: AgentRecords, *, client_id: int, year_start: dt.date, row_ids: list[int], text: str,
        why: str) -> Question:
    """Asks the person a question of the agent's own, once for the same rows and words (asked again, it takes the
    new reason)."""
    body = f"{client_id}|{year_start.isoformat()}|{sorted(row_ids)}|{text}"
    return records.upsert_question(
        QuestionDraft(client_id=client_id, year_start=year_start, row_ids=row_ids, kind="other", text=text, why=why,
                      source="agent"),
        f"agent:{hashlib.sha256(body.encode()).hexdigest()}")


def answer(store: MongoStore, records: AgentRecords, *, client_id: int, thread_id: Optional[str], question_id: str,
           answer: Answer, now: Optional[dt.datetime] = None, wait: int = 20) -> Answered:
    """Applies the person's answer, then works the questions out again and posts the year. A date answers a date
    question: the row is dated by resolutions.set_date (a date outside the books is InvalidInput, and the question
    stays open) and the question is resolved. "I don't have it" and "Not sure" leave the question waiting. A
    question already resolved is left as it is (and nothing is posted); the same answer twice is one decision.
    Returns the year's open and waiting questions, and the posting of the question's year (the year a date moved
    the row to is posted too). An answer outside a chat (no thread_id) makes the client due for a background review
    `wait` seconds after `now`."""
    q = records.question(question_id)
    if q is None or q.client_id != client_id:
        raise NotFound("This question was not found.")
    if q.status == "resolved":
        return Answered(records.questions(client_id, q.year_start), _not_posted())
    years, decision_ids, said = [q.year_start], [], ""
    if isinstance(answer, DateAnswer):
        if q.kind != "date" or not q.row_ids:
            raise InvalidInput("This question isn't asking for a date.")
        decision = set_date(store, records, client_id=client_id, thread_id=thread_id, row_id=q.row_ids[0],
                            date=answer.date, question_id=q.id)
        if decision.status != "applied":
            raise InvalidInput(decision.reason)
        said = long_date(answer.date)
        records.set_question(q.id, "resolved", said)
        decision_ids = [decision.id]
        if decision.year_start not in years:   # the date moved the row to another year
            years.append(decision.year_start)
    elif isinstance(answer, WithoutDocumentAnswer):
        reason = answer.reason.strip()
        if q.kind not in _ASKS or not q.row_ids:
            raise InvalidInput("Only a purchase waiting for its receipt or invoice can be booked without it.")
        if not reason:
            raise InvalidInput("Say why it is booked without its receipt or invoice.")
        for row_id in q.row_ids:
            ledger.change_row(store, client_id, row_id, RowPatch(without_document=reason))
        said = f"{BOOKED_WITHOUT}{reason}"
        records.set_question(q.id, "resolved", said)
    elif isinstance(answer, WriteOffAnswer):
        said = _write_off(store, client_id, q, answer)
        records.set_question(q.id, "resolved", said)
    elif isinstance(answer, SplitAnswer):
        said = _release_vat(store, client_id, q, answer) if q.kind == "opening_vat" else _release(store, client_id,
                                                                                                    q, answer)
        records.set_question(q.id, "resolved", said)
    elif isinstance(answer, NoDocumentAnswer):
        if q.kind not in DOCUMENT_KINDS:
            raise InvalidInput("This question isn't asking for a document.")
        said = "I don't have it"
        records.set_question(q.id, "waiting", said)
    else:
        said = "Not sure"
        records.set_question(q.id, "waiting", said)
    if not (q.status == "waiting" and q.answer == said):   # the same answer again changes nothing to record
        made = ChangeDraft(client_id=client_id, year_start=q.year_start, actor="user", kind="question_answered",
                           row_ids=list(q.row_ids), after={"answer": said}, summary=f"Answered: {q.text}")
        records.add_change(made)
        if thread_id is None:   # in a chat, the chat's agent handles the answer
            from . import reviews   # here: reviews imports the agent
            reviews.note(records, made, now=now or reviews.utcnow(), wait=wait)
    posts = []
    for year in years:
        refresh(store, records, client_id, year)
        posts.append(ledger_book.post(store, records, client_id, year, decision_ids=decision_ids))
    return Answered(records.questions(client_id, q.year_start), posts[0])


# An answer the agent may offer for the person to confirm: a split or a write-off.
OfferedAnswer = Annotated[Union[SplitAnswer, WriteOffAnswer], Field(discriminator="kind")]

# The books questions whose answer is a choice the agent may fill in for the person to confirm (offer).
OFFERABLE = frozenset({"opening_vat", "opening_prepayments", "opening_accruals", "bad_debt"})


def check_answer(store: MongoStore, client_id: int, q: Question, answer: Answer) -> Optional[str]:
    """What answering the question so would be refused with, or None: the answer service's own checks, run without
    booking anything. Only the answers that are a choice (a split, a write-off) can be checked so."""
    try:
        if isinstance(answer, WriteOffAnswer):
            _write_off(store, client_id, q, answer, dry=True)
        elif isinstance(answer, SplitAnswer):
            (_release_vat if q.kind == "opening_vat" else _release)(store, client_id, q, answer, dry=True)
        else:
            return "Only a split or a write-off can be checked."
    except InvalidInput as exc:
        return exc.message
    return None


def offer(store: MongoStore, records: AgentRecords, *, client_id: int, thread_id: str, question_id: str,
          answer: Union[SplitAnswer, WriteOffAnswer], sources: list[OfferSource], reason: str, texts: Texts,
          said: list[str], actor: str) -> Question:
    """Keeps an answer to a books question that the agent filled in from what the person said in this chat, for them
    to change or confirm on the question's card: nothing is booked here. It must rest on the person's own words
    (a said source quoting said, their messages in the chat), pass the answer service's checks (check_answer), and
    every line, and the write-off date, needs a source: the person's words, a document of the client's (any of its
    uploads, the quote in its text) or the question itself (its amount, the default date). Refused with
    InvalidInput saying why. Offered again, it replaces the earlier offer; each is recorded as a change."""
    q = records.question(question_id)
    if q is None or q.client_id != client_id:
        raise NotFound("This question was not found.")
    if q.source != "rules" or q.kind not in OFFERABLE:
        raise InvalidInput("This isn't a books question that takes an answer: only the VAT difference, the opening "
                           "prepayments or accruals and a bad debt do.")
    if q.status == "resolved":
        raise InvalidInput("This question is already answered.")
    if (problem := check_answer(store, client_id, q, answer)) is not None:
        raise InvalidInput(problem)
    if not any(s.kind == "said" for s in sources):
        raise InvalidInput("An offer needs the person's own words in this chat: quote what they said.")
    heard = _normalised(" ".join(said))
    for s in sources:
        if s.kind != "said":
            continue
        if len("".join(s.quote.split())) < _SHORTEST_QUOTE:
            raise InvalidInput(f"\"{s.quote}\" is too short to show anything: quote {_SHORTEST_QUOTE} characters or "
                               "more of what the person said.")
        if _normalised(s.quote) not in heard:
            raise InvalidInput(f"\"{s.quote}\" isn't in what the person said in this chat.")
    uploads = {u["id"]: u["name"] for u in store.uploads(client_id)}
    for s in sources:
        if s.kind != "document":
            continue
        if s.upload_id not in uploads:
            raise InvalidInput(f"Upload {s.upload_id} isn't one of the client's documents.")
        if len("".join(s.quote.split())) < _SHORTEST_QUOTE:
            raise InvalidInput(f"\"{s.quote}\" is too short to show anything: quote {_SHORTEST_QUOTE} characters or "
                               "more.")
        if _normalised(s.quote) not in _normalised(" ".join(texts(s.upload_id) or [])):
            raise InvalidInput(f"\"{s.quote}\" isn't in {uploads[s.upload_id]}.")
    parts = ([f"line:{n}" for n in range(1, len(answer.lines) + 1)] if isinstance(answer, SplitAnswer) else ["date"])
    for s in sources:
        if s.kind == "document" and s.for_ not in parts:
            raise InvalidInput(f"The quote from {uploads[s.upload_id]} names no line or date of this answer: say "
                               f"which it backs ({', '.join(parts)}).")
    from_question = any(s.kind == "question" for s in sources)
    for part in parts:
        # The question's own figure is the whole amount (or the default date): it backs a split of one line only.
        own = from_question and (len(parts) == 1 if isinstance(answer, SplitAnswer) else answer.date is None)
        backed = own or any(s.for_ == part for s in sources) or (part == "date" and answer.date is None)
        if not backed:
            raise InvalidInput(f"{part.replace(':', ' ')} has no source: quote what it comes from, or say it is the "
                               "question's own figure.")
    named = [s.model_copy(update={"upload_name": uploads.get(s.upload_id, "")}) if s.kind == "document" else s
             for s in sources]
    made = records.set_offer(q.id, Offer(answer=answer.model_dump(mode="json"), sources=named, reason=reason.strip(),
                                         thread_id=thread_id, offered_at=now_iso(), offered_by=actor))
    records.add_change(ChangeDraft(client_id=client_id, year_start=q.year_start, actor=actor, kind="question_offered",
                                   row_ids=list(q.row_ids), after={"offer": made.offer.model_dump(mode="json", by_alias=True)},
                                   summary=f"Offered an answer to: {q.text}", in_chat=True))
    return made


def _write_off(store: MongoStore, client_id: int, q: Question, answer: WriteOffAnswer, *, dry: bool = False) -> str:
    """Adds the row that writes off what is still owed on the question's invoice as a bad debt, with the VAT on it as
    relief (checks books it only when the client was VAT registered); what the person said."""
    if q.kind != "bad_debt" or not q.row_ids:
        raise InvalidInput("This question isn't asking about a bad debt.")
    built = books.ledger(store, client_id, q.year_start)
    tx = next((t for t in _sales_owed(store, client_id, built) if t.id == q.row_ids[0]), None)
    if tx is None:
        raise InvalidInput("This invoice is no longer owed.")
    overdue = _overdue_from(tx)
    # By default today, or the day the six months end if later: never a VAT quarter already filed. Kept in the year.
    day = answer.date or max(overdue, min(dt.date.today(), built.year.end))
    if not (built.year.start <= day <= built.year.end):
        raise InvalidInput(f"Choose a date in the year, {long_date(built.year.start)} to {long_date(built.year.end)}.")
    if day < overdue:
        raise InvalidInput(f"Bad debt relief can be claimed from {long_date(overdue)}, six months after the invoice "
                           "fell due: choose that day or later.")
    if dry:
        return ""
    parts = [t for t in books.all_rows(store, client_id) if booked(t) and (t.document_ref or f"row-{t.id}") == (tx.document_ref or f"row-{tx.id}")]
    gross = sum((t.gross for t in parts), ZERO)
    vat = sum((t.vat_posted or ZERO for t in parts), ZERO)
    share = (tx.owed * vat / gross).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if gross else ZERO
    off = Transaction(date=day, direction="out", gross=tx.owed, vat=share, account_code="8100",
                      document_type="write_off", counterparty=tx.counterparty, writes_off=tx.document_ref,
                      description=f"Bad debt written off: {tx.description}")
    ledger.add_manual(store, client_id, ManualUpload(name="Bad debt written off", transactions=[off],
                                                     year_start=q.year_start))
    return f"Written off on {long_date(day)}: {_gbp(tx.owed)}"


def _release_vat(store: MongoStore, client_id: int, q: Question, answer: SplitAnswer, *, dry: bool = False) -> str:
    """Posts the journal of a VAT payment's difference from the VAT owed brought forward, on the payment's day."""
    built = books.ledger(store, client_id, q.year_start)
    found = _vat_difference(store, client_id, q.year_start, built)
    if found is None:
        raise InvalidInput("The VAT payment no longer differs from the VAT owed.")
    payment, _, left = found
    if not answer.lines or any(line.amount <= ZERO for line in answer.lines):
        raise InvalidInput("Give each account an amount above zero.")
    if any(line.account not in BY_CODE or line.account in ("2202", *ALL_BANK_CODES) for line in answer.lines):
        raise InvalidInput("Choose an account for each line, not the VAT liability or a bank.")
    total = sum((line.amount for line in answer.lines), ZERO)
    if total != abs(left):
        raise InvalidInput(f"The lines add up to {_gbp(total)}; the difference is {_gbp(abs(left))}.")
    if dry:
        return ""
    more = left > ZERO   # paid more: Dr the account, Cr VAT Liability; paid less: the other way
    journals = [Transaction(date=payment.date, direction="out", gross=line.amount, document_type="journal",
                            description=f"VAT payment's difference from the VAT owed: {BY_CODE[line.account].name}",
                            account_code=line.account if more else "2202",
                            contra_account_code="2202" if more else line.account) for line in answer.lines]
    ledger.add_manual(store, client_id, ManualUpload(name="VAT difference", transactions=journals,
                                                     year_start=q.year_start))
    return "Booked to " + "; ".join(f"{line.account} {BY_CODE[line.account].name} {_gbp(line.amount)}"
                                    for line in answer.lines)


def _release(store: MongoStore, client_id: int, q: Question, answer: SplitAnswer, *, dry: bool = False) -> str:
    """Posts the journals that release an opening prepayment or accrual to the costs the answer gives, on the year's
    first day; what the person said. The lines must add up to what is still to be released."""
    if q.kind not in _OPENING:
        raise InvalidInput("This question isn't asking which costs an opening balance is for.")
    code, word, sign = _OPENING[q.kind]
    if not answer.lines or any(line.amount <= ZERO for line in answer.lines):
        raise InvalidInput("Give each cost an amount above zero.")
    if any(line.account not in BY_CODE or line.account == code or line.account in ALL_BANK_CODES
           for line in answer.lines):
        raise InvalidInput("Choose a cost account for each line.")
    left = _opening_left(store, client_id, q.year_start, books.ledger(store, client_id, q.year_start)).get(q.kind,
                                                                                                           ZERO)
    total = sum((line.amount for line in answer.lines), ZERO)
    if total != left:
        raise InvalidInput(f"The lines add up to {_gbp(total)}; the opening {word} still to release are {_gbp(left)}.")
    if dry:
        return ""
    journals = [Transaction(date=q.year_start, direction="out", gross=line.amount, document_type="journal",
                            description=f"Opening {word} released: {BY_CODE[line.account].name}",
                            account_code=line.account if sign > 0 else code,
                            contra_account_code=code if sign > 0 else line.account) for line in answer.lines]
    ledger.add_manual(store, client_id, ManualUpload(name=f"Opening {word} released", transactions=journals,
                                                     year_start=q.year_start))
    return "Released to " + "; ".join(f"{line.account} {BY_CODE[line.account].name} {_gbp(line.amount)}"
                                      for line in answer.lines)


CLOSED_BY_THE_AI = "Closed by the AI: "


def close(store: MongoStore, records: AgentRecords, *, client_id: int, year_start: dt.date, question_id: str, reason: str,
          evidence: list[Evidence], texts: Texts, actor: str, trigger: str, review_id: Optional[str] = None,
          suggest: bool = False) -> Decision:
    """Closes a question of the agent's own that the books have since answered, and records it as a decision. Only an
    open or waiting question of the agent's can be closed. It needs one of two things: a change by a person, made
    after the question was asked, to one of its rows (the change's summary is the evidence), or quotes from the rows'
    documents that pass the same check as a resolution's. Without either the decision is refused. Asked again once
    closed it returns that decision; a closing that a person undid is refused. suggest=True records the closing as a
    suggested decision and leaves the question as it is."""
    q = records.question(question_id)
    if q is None or q.client_id != client_id:
        raise NotFound("This question was not found.")
    if q.year_start != year_start:
        raise InvalidInput("That question belongs to another year.")
    key = f"close|{q.id}"
    if (done := records.decision_by_key(client_id, key)) is not None and done.status == "applied" \
            and not records.is_rejected(client_id, key):
        return done
    if q.source != "agent" or q.status not in ("open", "waiting"):
        raise InvalidInput("Only an open question the AI asked can be closed.")
    draft = dict(client_id=client_id, year_start=q.year_start, action="close_question",
                 rule="Closed a question the books answer", row_ids=list(q.row_ids), actor=actor,
                 trigger=trigger, review_id=review_id)

    def refused(why: str) -> Decision:
        return records.append_decision(DecisionDraft(**draft, status="refused", reason=why),
                                       f"{key}|refused|{uuid4().hex}")[0]

    if records.is_rejected(client_id, key):
        return refused("A person undid this change.")
    theirs = [c for c in records.changes(client_id, year_start=q.year_start, since=q.created_at, limit=1000)
              if c.actor == "user" and c.kind != "question_answered" and set(c.row_ids) & set(q.row_ids)]
    if theirs:
        quotes = [Evidence(upload_id=0, upload_name="change record", quote=theirs[-1].summary)]
    else:
        b = books._books(store, client_id)
        rows = {r.id: r for r in books._saved_rows(b, None)[0]}
        why = check_quotes(b, rows, list(q.row_ids), evidence, texts) if evidence else None
        if not evidence or why is not None:
            return refused(why or "Nothing since the question was asked answers it.")
        names = {u["id"]: u["name"] for u in b.uploads}
        quotes = [e.model_copy(update={"upload_name": names.get(e.upload_id, "")}) for e in evidence]
    before, after = {"question": {"status": q.status, "answer": q.answer}}, {"question": {"status": "resolved"}}
    if suggest:
        return records.append_decision(DecisionDraft(**draft, status="suggested", reason=reason, evidence=quotes, before=before,
                                                     after=after, resolution={"action": "close_question",
                                                                              "question_id": q.id, "reason": reason}), f"{key}|suggested")[0]
    made = records.append_decision(DecisionDraft(**draft, status="applied", reason=reason, evidence=quotes, before=before,
                                                 after=after), key)[0]
    records.set_question(q.id, "resolved", f"{CLOSED_BY_THE_AI}{reason}")
    records.add_change(ChangeDraft(client_id=client_id, year_start=q.year_start, actor=actor, kind="question_closed",
                                   row_ids=list(q.row_ids), before=before, after=after,
                                   summary=f"Closed the question: {q.text}", in_chat=trigger == "chat"))
    return made
