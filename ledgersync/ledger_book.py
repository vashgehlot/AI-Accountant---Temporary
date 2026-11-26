"""The posted ledger the accountant chat shows. The pages' trial balance is worked out from the rows on every read and
never stored; this one is stored, and only ever added to. Each posting compares what every row of a year should
post now, after the document rules, with what is already posted for that row, and writes the difference as one
batch: a row whose lines changed gets a reversal of each line it has posted and its lines afresh; a row no longer
booked gets the reversals alone. A batch is checked whole before anything is written. Money is kept as Decimal128.
It lives in the ledger_entries and posting_batches collections of the records' database."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence
from uuid import uuid4

import pymongo
from bson import Decimal128
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from . import books
from .accounts import BY_CODE, CIS_DEDUCTED, CIS_PAYABLE, PURCHASE_VAT, SALES_VAT, SUSPENSE
from .checks import most_vat
from .errors import InvalidTransactions
from .evidence_rules import DocumentRule, document_rule, journal_with_rule
from .ledger import settings_for
from .models import BusinessSettings, JournalLine, PostedTrialBalance, PostResult, SuspenseItem, Transaction
from .money import PENNY, ZERO
from .posting import summarise
from .records import AgentRecords
from .rows import now_iso
from .store_mongo import MongoStore

Ruled = list[tuple[int, Transaction, DocumentRule]]


def _money(value) -> Decimal:
    """Pennies from a Decimal128 as stored, or a Decimal."""
    return (value.to_decimal() if isinstance(value, Decimal128) else Decimal(value)).quantize(PENNY)


def _stored(amount: Decimal) -> Decimal128:
    return Decimal128(str(amount.quantize(PENNY)))


_INDEXED: set[str] = set()   # the databases whose indexes this process has made: each is made once, not on every post


def _ensure_indexes(db: Database) -> None:
    if db.name in _INDEXED:
        return
    db.ledger_entries.create_index([("client_id", pymongo.ASCENDING), ("year_start", pymongo.ASCENDING)])
    db.ledger_entries.create_index([("batch_id", pymongo.ASCENDING)])
    db.posting_batches.create_index([("client_id", pymongo.ASCENDING), ("year_start", pymongo.ASCENDING),
                                     ("key", pymongo.ASCENDING)], unique=True)
    # Each batch follows the one before it, and no two follow the same one: of two postings worked out from the
    # same ledger, the second to write is refused, so a line is never reversed twice.
    db.posting_batches.create_index([("client_id", pymongo.ASCENDING), ("year_start", pymongo.ASCENDING),
                                     ("after", pymongo.ASCENDING)], unique=True)
    _INDEXED.add(db.name)


def _ruled(store: MongoStore, client_id: int, year_start: dt.date,
           held: Optional[dict[int, list[str]]] = None) -> tuple[BusinessSettings, Ruled]:
    """The client's settings, and the year's booked rows by row id with the document rule each falls under;
    InvalidTransactions while rows need fixing, unless held (a dict) is given: then those rows are left out and held
    gets their ids with their problems (books.booked_rows)."""
    settings = settings_for(store.get_client(client_id))
    return settings, [(row_id, tx, document_rule(tx, settings))
                      for row_id, tx in books.booked_rows(store, client_id, year_start, held)]


def wanted_journal(store: MongoStore, client_id: int, year_start: dt.date,
                   ruled: Optional[Ruled] = None) -> dict[int, list[JournalLine]]:
    """What each of the year's booked rows should post now, by row id: its journal lines after the document rules,
    with the row id as their transaction. ruled: the rows and their rules, when the caller has them already.
    InvalidTransactions while rows need fixing (their journal can't be worked out)."""
    if ruled is None:
        ruled = _ruled(store, client_id, year_start)[1]
    return {row_id: journal_with_rule(tx, row_id, rule) for row_id, tx, rule in ruled}


def _net(lines: Iterable[tuple[str, Decimal, Decimal]]) -> dict[str, Decimal]:
    """Debits less credits by account, leaving out the accounts that come to nothing."""
    net: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for code, debit, credit in lines:
        net[code] += debit - credit
    return {code: amount for code, amount in net.items() if amount != 0}


def _legs(lines: list[JournalLine]) -> list[tuple[str, Decimal, Decimal]]:
    """The lines' accounts and amounts in pennies, as they would be posted."""
    return [(l.code, l.debit.quantize(PENNY), l.credit.quantize(PENNY)) for l in lines]


@dataclass
class _Posted:
    """What is posted for a client's year: every entry, oldest first, with its money as Decimal; the lines of each
    row that are neither reversals nor reversed; each row's net by account; the latest batch, the end of the
    chain; and whether all its entries were written when it was read."""
    entries: list[dict]
    live: dict[int, list[dict]] = field(default_factory=dict)
    net: dict[int, dict[str, Decimal]] = field(default_factory=dict)
    last_batch: Optional[str] = None
    complete: bool = True


def _posted(db: Database, client_id: int, year_start: dt.date) -> _Posted:
    """What is posted. The batches are read before the entries: a batch is written before its entries, so once the
    end of the chain is found with all its entries written, the entries read after include them all."""
    where = {"client_id": client_id, "year_start": year_start.isoformat()}
    batches = list(db.posting_batches.find(where, {"_id": 1, "after": 1, "entries": 1, "reversals": 1}))
    followed = {b["after"] for b in batches}
    latest = next((b for b in batches if b["_id"] not in followed), None)
    complete = latest is None or db.ledger_entries.count_documents(
        {"batch_id": latest["_id"]}) >= latest.get("entries", 0) + latest.get("reversals", 0)
    entries = [{**d, "debit": _money(d["debit"]), "credit": _money(d["credit"])}
               for d in db.ledger_entries.find(where).sort([("seq", pymongo.ASCENDING), ("_id", pymongo.ASCENDING)])]
    reversed_ = {d["reverses"] for d in entries if d["reverses"]}
    by_row: dict[int, list[dict]] = defaultdict(list)
    for d in entries:
        by_row[d["row_id"]].append(d)
    live = {r: [d for d in ds if not d["reverses"] and d["_id"] not in reversed_] for r, ds in by_row.items()}
    net = {r: n for r, ds in by_row.items() if (n := _net((d["code"], d["debit"], d["credit"]) for d in ds))}
    return _Posted(entries=entries, live=live, net=net, last_batch=latest["_id"] if latest else None,
                   complete=complete)


def _changed(wanted: dict[int, list[JournalLine]], posted: _Posted, held: Iterable[int] = ()) -> list[int]:
    """The rows whose wanted lines come to something other than what is posted for them, by account: changed rows,
    new rows, and rows posted that are no longer booked. A row held for a fix (held) is none of these: what it posted
    stays as it is until it is fixed."""
    held = set(held)
    return sorted(r for r in set(wanted) | set(posted.net)
                  if r not in held and _net(_legs(wanted.get(r, []))) != posted.net.get(r, {}))


def _new_lines(wanted: dict[int, list[JournalLine]], posted: _Posted, held: Iterable[int] = ()) -> list[dict]:
    """For each changed row (_changed), the reversal of each line it has posted (debit and credit swapped), then its
    wanted lines."""
    lines = []
    for r in _changed(wanted, posted, held):
        lines += [dict(row_id=r, code=d["code"], description=d["description"], debit=d["credit"], credit=d["debit"],
                       reverses=d["_id"]) for d in posted.live.get(r, [])]
        lines += [dict(row_id=r, code=l.code, description=l.description, debit=l.debit.quantize(PENNY),
                       credit=l.credit.quantize(PENNY), reverses=None) for l in wanted.get(r, [])]
    return lines


def _problems(lines: list[dict], rows: dict[int, Transaction], vat_registered: bool, posted: _Posted) -> list[str]:
    """Why the batch can't be posted: a row's lines or the whole batch not balancing; an account not in the chart;
    a reversal of an entry that isn't posted, is reversed already or is itself a reversal; or a new VAT leg that is
    not on Sales or Purchase VAT, is more than the row's gross can hold (a sixth, with the rounding allowance
    checks.normalise allows), or is for a client that isn't VAT registered. A VAT leg is a line on an account other
    than the row's own, its bank (or contra) and Suspense."""
    problems = []
    by_row: dict[int, list[dict]] = defaultdict(list)
    for line in lines:
        by_row[line["row_id"]].append(line)
    by_id = {d["_id"]: d for d in posted.entries}
    reversed_ = {d["reverses"] for d in posted.entries if d["reverses"]}
    for line in (l for l in lines if l["reverses"]):
        target = by_id.get(line["reverses"])
        if target is None:
            problems.append(f"Row {line['row_id']}: entry {line['reverses']} to reverse isn't posted.")
        elif target["reverses"]:
            problems.append(f"Row {line['row_id']}: entry {line['reverses']} is itself a reversal.")
        elif line["reverses"] in reversed_:
            problems.append(f"Row {line['row_id']}: entry {line['reverses']} is already reversed.")
        reversed_.add(line["reverses"])   # and twice in one batch is once too many
    for r, ls in by_row.items():
        debits, credits = sum((l["debit"] for l in ls), ZERO), sum((l["credit"] for l in ls), ZERO)
        if debits != credits:
            problems.append(f"Row {r}: debits £{debits} and credits £{credits} do not balance.")
        problems += [f"Row {r}: {l['code']} isn't an account in the chart." for l in ls if l["code"] not in BY_CODE]
        fresh = [l for l in ls if l["reverses"] is None and l["code"] in BY_CODE]
        tx = rows.get(r)
        if tx is None:
            if fresh:
                problems.append(f"Row {r} isn't one of the year's booked rows.")
            continue
        own = {tx.paid_against or tx.account_code, tx.contra_account_code, SUSPENSE,
               *((CIS_DEDUCTED, CIS_PAYABLE) if tx.cis_deducted else ())}
        for l in (l for l in fresh if l["code"] not in own):
            amount = abs(l["debit"] - l["credit"])
            if l["code"] not in (SALES_VAT, PURCHASE_VAT):
                problems.append(f"Row {r}: VAT goes only on 2200 or 2201, not {l['code']}.")
            elif not vat_registered:
                problems.append(f"Row {r}: the client isn't VAT registered, so no VAT goes on {l['code']}.")
            elif amount > max(most_vat(tx.gross), (tx.gross / 5).quantize(PENNY, ROUND_HALF_UP)):
                # a fifth, to the penny as VAT is booked: the reverse charge, or VAT charged before a voucher came off
                problems.append(f"Row {r}: VAT of £{amount} is more than a sixth of its £{tx.gross}.")
    debits, credits = sum((l["debit"] for l in lines), ZERO), sum((l["credit"] for l in lines), ZERO)
    if debits != credits:
        problems.append(f"The batch's debits £{debits} and credits £{credits} do not balance.")
    return problems


def _key(lines: list[dict], after: Optional[str]) -> str:
    """The SHA-256 of the canonical JSON of the batch's lines and the batch it follows: a second posting of the same
    difference (a retry, or two at once) has the same key, which the unique index refuses. The batch it follows is
    in it so a row put back after being reversed can post the very lines it posted before."""
    body = {"after": after, "lines": [{"row_id": l["row_id"], "code": l["code"], "debit": str(l["debit"]),
                                       "credit": str(l["credit"]), "reverses": l["reverses"]} for l in lines]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _nothing(problems: Sequence[str] = ()) -> PostResult:
    return PostResult(batch_id=None, entries_added=0, reversals_added=0, total_debits=ZERO, total_credits=ZERO,
                      problems=list(problems))


def post(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date, *,
         decision_ids: Sequence[str] = ()) -> PostResult:
    """Posts the year's changes since the last posting as one batch, recording the decisions behind it. Nothing is
    written when there is nothing to post, when another posting worked out from the same ledger was written first,
    or (with the problems) when the batch fails its checks, rows need fixing, the year is closed, or the latest
    batch's entries are still being written. entries_added counts the new lines, reversals_added the reversals."""
    db = records.db
    _ensure_indexes(db)
    if any(c.start == year_start for c in store.get_client(client_id).closed_years):
        return _nothing(["That year is closed."])   # closed is closed: nothing is posted to it
    held: dict[int, list[str]] = {}   # rows needing a fix: left as they are, and listed
    try:
        settings, ruled = _ruled(store, client_id, year_start, held)
    except InvalidTransactions as exc:   # an earlier year's: this year's opening can't be worked out
        return _nothing(exc.problems)
    left_out = [p for problems in held.values() for p in problems]
    posted = _posted(db, client_id, year_start)
    if not posted.complete:   # its entries would be missing from what this posting reverses
        return _nothing(["Another posting is still being written; try again."])
    lines = _new_lines(wanted_journal(store, client_id, year_start, ruled=ruled), posted, held)
    if not lines:
        return _nothing().model_copy(update={"left_out": left_out})
    problems = _problems(lines, {r: tx for r, tx, _ in ruled}, settings.vat_registered, posted)
    if problems:
        return _nothing(problems).model_copy(update={"left_out": left_out})
    debits, credits = sum((l["debit"] for l in lines), ZERO), sum((l["credit"] for l in lines), ZERO)
    reversals = sum(1 for l in lines if l["reverses"])
    batch_id, now, seq, year = uuid4().hex, now_iso(), time.time_ns(), year_start.isoformat()
    try:
        db.posting_batches.insert_one({
            "_id": batch_id, "client_id": client_id, "year_start": year, "key": _key(lines, posted.last_batch),
            "after": posted.last_batch, "decision_ids": list(decision_ids), "entries": len(lines) - reversals,
            "reversals": reversals, "total_debits": _stored(debits), "total_credits": _stored(credits),
            "created_at": now, "seq": seq})
    except DuplicateKeyError:   # this very batch, or another worked out from the same ledger, was posted meanwhile
        return _nothing()
    try:
        db.ledger_entries.insert_many([
            {"_id": uuid4().hex, "client_id": client_id, "year_start": year, "batch_id": batch_id,
             "row_id": l["row_id"], "code": l["code"], "description": l["description"], "debit": _stored(l["debit"]),
             "credit": _stored(l["credit"]), "reverses": l["reverses"], "created_at": now, "seq": seq + k}
            for k, l in enumerate(lines)])
    except Exception:   # take back what was written of the batch, so it can be posted again
        db.ledger_entries.delete_many({"batch_id": batch_id})
        db.posting_batches.delete_one({"_id": batch_id})
        raise
    return PostResult(batch_id=batch_id, entries_added=len(lines) - reversals, reversals_added=reversals,
                      total_debits=debits, total_credits=credits, left_out=left_out)


def posted_trial_balance(store: MongoStore, records: AgentRecords, client_id: int,
                         year_start: dt.date) -> PostedTrialBalance:
    """The year's opening balances plus every entry posted for it, laid out as posting.trial_balance lays out the
    rows', and the rows whose posted lines leave something in Suspense. The posted entries are facts, so it never
    waits for rows to be fixed: while the opening can't be worked out (an earlier year needs fixing) it shows the
    entries alone, and while this year's rows need fixing a Suspense item doesn't say what it needs; problems
    says why."""
    problems: list[str] = []
    try:
        opening = books.opening(store, client_id, year_start)
    except InvalidTransactions as exc:
        opening, problems = {}, [exc.message]
    posted = _posted(records.db, client_id, year_start)
    journal = [JournalLine(transaction=d["row_id"], code=d["code"], description=d["description"], debit=d["debit"],
                           credit=d["credit"]) for d in posted.entries]
    held: dict[int, list[str]] = {}
    try:
        rules = {r: rule for r, _, rule in _ruled(store, client_id, year_start, held)[1]}
    except InvalidTransactions as exc:
        rules = {}
        problems += exc.problems
    problems += [p for found in held.values() for p in found]   # rows left out of posting until they are fixed
    suspense = []
    for r, net in posted.net.items():
        if net.get(SUSPENSE):
            rule = rules.get(r)
            last = next(d for d in reversed(posted.entries) if d["row_id"] == r and d["code"] == SUSPENSE)
            suspense.append(SuspenseItem(row_id=r, description=last["description"], gross=abs(net[SUSPENSE]),
                                         needs=rule.needs if rule and rule.action == "hold" else None))
    return PostedTrialBalance(**summarise(journal, opening).model_dump(), suspense=suspense, problems=problems)


def unposted_changes(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date) -> int:
    """How many rows would post something on the next posting: their wanted lines differ from what is posted for
    them, or they are posted and no longer booked. A row needing a fix is not among them: it posts once fixed. While
    an earlier year needs fixing nothing can be posted, so it is the number of its problems (it never raises)."""
    held: dict[int, list[str]] = {}
    try:
        ruled = _ruled(store, client_id, year_start, held)[1]
    except InvalidTransactions as exc:
        return len({p.split(":", 1)[0] for p in exc.problems})   # each problem starts with its row: "#3: ..."
    return len(_changed(wanted_journal(store, client_id, year_start, ruled=ruled),
                        _posted(records.db, client_id, year_start), held))
