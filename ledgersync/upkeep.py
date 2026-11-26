"""Keeping a client's books up to date after a change: the rows matching dated from the bank are recorded, the rule
questions are worked out again and the year is posted. A person's change is recorded first and never fails because the
upkeep after it did."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional, Sequence

from . import books, ledger_book, questions
from .agent.locks import ClientLocks
from .errors import InvalidTransactions
from .models import ChangeDraft, PostResult
from .records import AgentRecords
from .resolutions import record_automatic, suggest_account_changes
from .store_mongo import MongoStore

logger = logging.getLogger(__name__)


def settle(store: MongoStore, records: AgentRecords, client_id: int, year_start: dt.date, *,
           thread_id: Optional[str] = None, decision_ids: Sequence[str] = ()) -> PostResult:
    """With the client's lock held by the caller: records the rows matching dated from the bank, suggests the usual
    account for a bill on another, works the year's questions out and posts the year, with the decisions behind the
    posting. The four steps work from one copy of the client, read again only after one of them changes it
    (MongoStore.reading). Questions that can't be worked out while an earlier year's row needs a fix wait; the year
    still posts."""
    with store.reading():
        record_automatic(store, records, client_id=client_id, year_start=year_start, thread_id=thread_id)
        suggest_account_changes(store, records, client_id=client_id, year_start=year_start)
        try:
            questions.refresh(store, records, client_id, year_start)
        except InvalidTransactions as exc:
            # An earlier year's row needing a fix leaves this year without opening balances (books._opening): its
            # questions stay as they were until the fix, but its own rows still post.
            logger.info("Questions of client %s, year %s wait for a fix: %s", client_id, year_start, exc.message)
        return ledger_book.post(store, records, client_id, year_start, decision_ids=decision_ids)


def _open_years(store: MongoStore, client_id: int, today: Optional[dt.date]) -> list[dt.date]:
    return [y.start for y in books.years_of(store, client_id, today or dt.date.today()) if not y.closed]


def settle_open_years(store: MongoStore, records: AgentRecords, client_id: int, *, except_year: Optional[dt.date] = None,
                      today: Optional[dt.date] = None, thread_id: Optional[str] = None) -> dict[dt.date, PostResult]:
    """With the client's lock held by the caller: settles every year of the client that isn't closed, apart from
    except_year. A year whose settling fails is logged and left out of the result; nothing is raised."""
    results: dict[dt.date, PostResult] = {}
    try:
        years = _open_years(store, client_id, today)
    except Exception:
        logger.exception("Couldn't list the years of client %s to settle", client_id)
        return results
    for start in years:
        if start == except_year:
            continue
        try:
            results[start] = settle(store, records, client_id, start, thread_id=thread_id)
        except Exception:
            logger.exception("Couldn't settle client %s, year %s", client_id, start)
    return results


def after_change(store: MongoStore, records: AgentRecords, locks: ClientLocks, change: ChangeDraft, *,
                 today: Optional[dt.date] = None, wait: int = 20,
                 now: Optional[dt.datetime] = None) -> dict[dt.date, PostResult]:
    """Records the change, makes the client due for a background review `wait` seconds from `now` (the current time)
    when the change needs one, then settles every year of the client that isn't closed, each under the client's lock
    (which re-checks that the year is still open). A year whose settling fails is logged and left out of the result;
    nothing is raised, recording the change included."""
    results: dict[dt.date, PostResult] = {}
    try:
        records.add_change(change)
        from . import reviews   # here: reviews imports the agent, which imports this module
        reviews.note(records, change, now=now or reviews.utcnow(), wait=wait)
    except Exception:
        logger.exception("Couldn't record a change to client %s: %s", change.client_id, change.summary)
    try:
        years = _open_years(store, change.client_id, today)
    except Exception:
        logger.exception("Couldn't list the years of client %s to settle", change.client_id)
        return results
    for start in years:
        try:
            with locks.hold(change.client_id):
                if any(c.start == start for c in store.get_client(change.client_id).closed_years):
                    continue   # closed while this waited for the lock
                results[start] = settle(store, records, change.client_id, start)
        except Exception:
            logger.exception("Couldn't settle client %s, year %s", change.client_id, start)
    return results
