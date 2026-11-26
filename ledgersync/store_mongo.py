"""The MongoDB store of clients, uploads and rows (Embedded Client Document pattern).
Optimized for:
1. Batch Sequence Counter (single DB call instead of N calls during bulk upload)
2. Field-level projection (never pulling rows when only client or upload metadata is needed)
3. Atomic array filters & in-database updates for patch_row and delete_row
4. Clean connection pooling and robust index creation
5. 100% Client Isolation (no client data crossover)
"""
from __future__ import annotations

import contextvars
import datetime as dt
from decimal import Decimal
import logging
import re
import threading
import time
from collections import Counter
from contextlib import contextmanager
from typing import Iterator, Optional

import pymongo
from pymongo import MongoClient, ReturnDocument

from .errors import ChangedMeanwhile, ClientArchived, NotFound
from .models import BankAccount, Client, ClientFields, ClosedYear, OpeningBalances, Owner, Transaction
from .rows import EDITABLE, OLD_TOTAL, WHOLE_DOCUMENT, StoredRow, now_iso, saved_form

logger = logging.getLogger(__name__)

# How many times patch_row reads and writes again when another write to the client got in between.
_PATCH_TRIES = 5
# The client documents a reading block has fetched, where the block runs (MongoStore.reading); None outside one.
_READING: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("ledgersync_reading", default=None)
# Seconds a reading block trusts its copy of a client. A write by this process drops the copy at once; this is for a
# write by another process on the same database, which a block that runs for long would otherwise never see.
FRESH_FOR = 5.0

_CLIENT_FIELDS = ("name", "business_type", "contact_name", "contact_email", "contact_phone", "vat_registered",
                  "vat_from",
                  "bank_accounts", "owners", "first_year_end", "ai_review", "company_number", "utr", "vat_number",
                  "paye_reference", "materiality", "capitalise_from", "nature_of_business", "sic_code")
_REFERENCES = ("company_number", "utr", "vat_number", "paye_reference", "nature_of_business", "sic_code")
_CLIENT_PROJECTION = {
    "id": 1,
    "name": 1,
    "business_type": 1,
    "contact_name": 1,
    "contact_email": 1,
    "contact_phone": 1,
    "vat_registered": 1,
    "vat_from": 1,
    "bank_accounts": 1,
    "owners": 1,
    "first_year_end": 1,
    "ai_review": 1,
    "materiality": 1,
    "capitalise_from": 1,
    "company_number": 1,
    "utr": 1,
    "vat_number": 1,
    "paye_reference": 1,
    "nature_of_business": 1,
    "sic_code": 1,
    "closed_years": 1,
    "archived_at": 1,
    "created_at": 1,
    "updated_at": 1,
}


def _date(value: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(value) if value else None


def _march_on_or_after(day: dt.date) -> dt.date:
    end = dt.date(day.year, 3, 31)
    return end if day <= end else dt.date(day.year + 1, 3, 31)


def _client(doc: dict, earliest: Optional[dt.date] = None) -> Client:
    """A client as its document keeps it; one saved before it had bank accounts has the one current account. One saved
    before clients had a first year end (old test data) reads with the 31 March on or after its earliest row
    (earliest), or on or after today when it has none."""
    return Client(
        id=doc["id"],
        name=doc["name"],
        business_type=doc["business_type"],
        contact_name=doc["contact_name"],
        first_year_end=_date(doc.get("first_year_end")) or _march_on_or_after(earliest or dt.date.today()),
        contact_email=doc.get("contact_email", ""),
        contact_phone=doc.get("contact_phone", ""),
        vat_registered=bool(doc.get("vat_registered", True)),
        vat_from=_date(doc.get("vat_from")),
        ai_review=doc.get("ai_review", "automatic"),
        materiality=Decimal(doc["materiality"]) if doc.get("materiality") else None,
        capitalise_from=Decimal(doc["capitalise_from"]) if doc.get("capitalise_from") else None,
        **{field: doc.get(field, "") for field in _REFERENCES},
        **({"bank_accounts": doc["bank_accounts"]} if doc.get("bank_accounts") else {}),
        owners=doc.get("owners") or [],
        closed_years=[ClosedYear.model_validate(y) for y in doc.get("closed_years") or []],
        archived=doc.get("archived_at") is not None,
        archived_at=doc.get("archived_at"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _stored_accounts(accounts: list[BankAccount]) -> list[dict]:
    return [a.model_dump() for a in accounts]


def _stored(rows: list[dict]) -> list[StoredRow]:
    """The rows of a client's document as the store gives them: in the order of their uploads and their place in
    them, each with what was first read when a person has edited it."""
    stored_rows = []
    for r in sorted(rows, key=lambda r: (r.get("upload_id", 0), r.get("position", 0))):
        data = dict(r["data"])
        original = data.pop("original", None)
        data.pop("original_issues", None)
        data.pop("original_printed", None)
        if data.get("document_total") is None:
            old = [OLD_TOTAL.search(i.get("message", "")) for i in data.get("issues", []) if i.get("code") == "total_mismatch"]
            if old and old[0]:
                data["document_total"] = old[0].group(1).replace(",", "")
        chosen = bool(original) and "account_code" in original and original["account_code"] != data.get("account_code")
        stored_rows.append(StoredRow(r["id"], r["upload_id"], Transaction.model_validate({**data, "account_chosen": chosen}),
                                     original))
    return stored_rows


def _listed(client_id: int, uploads: list[dict], counts) -> list[dict]:
    """The uploads of a client's document as the store lists them, the newest first, each with how many rows it has
    (counts, by upload id)."""
    return [{
        "id": u["id"],
        "client_id": client_id,
        "name": u["name"],
        "kind": u["kind"],
        "sha256": u.get("sha256", ""),
        "model": u.get("model", ""),
        "warnings": list(u.get("warnings", [])),
        "bank_account": u.get("bank_account"),
        "year_start": _date(u.get("year_start")),
        "created_at": u["created_at"],
        "row_count": counts.get(u["id"], 0)
    } for u in sorted(uploads, key=lambda x: x["id"], reverse=True)]


def _earliest(doc: dict) -> Optional[dt.date]:
    """For a client's whole document saved without a first year end (old data): the date of its earliest row."""
    if doc.get("first_year_end"):
        return None
    dates = [r["data"]["date"] for r in doc.get("rows", []) if r.get("data", {}).get("date")]
    return _date(min(dates)) if dates else None


def _new_client(uri: str, max_pool: int) -> MongoClient:
    """A client whose pool stays small and drops idle connections: Atlas M0 allows 500 connections in all, counted
    on each node of the replica set, so nothing is kept open ahead of need."""
    return MongoClient(
        uri,
        maxPoolSize=max_pool,
        minPoolSize=0,
        maxIdleTimeMS=60000,
        serverSelectionTimeoutMS=15000,   # Atlas takes up to about 12 s to choose a new primary
        connectTimeoutMS=10000,
        socketTimeoutMS=20000,
    )


class MongoStore:
    def __init__(self, uri: str = "mongodb://localhost:27017", db_name: str = "ledgersync", *,
                 client: Optional[MongoClient] = None, max_pool: int = 10):
        """The store on `db_name`. Given a `client` it uses that one (to share its pool) and never closes it;
        otherwise it opens its own, of at most `max_pool` connections."""
        self.uri = uri
        self.db_name = db_name
        self._owns_client = client is None
        self.client = _new_client(uri, max_pool) if client is None else client
        self.db = self.client[db_name]
        self._writes: Counter = Counter()   # this process's writes to each client, which outdate a reading block's copy
        self._writes_lock = threading.Lock()
        self._init_indexes()

    # ─── Reading a client once ─────────────────────────────────────────────────

    @contextmanager
    def reading(self) -> Iterator[None]:
        """While the block runs, where it runs (a request with the work it hands to other threads, one of the agent's
        tool calls, the upkeep after a change), a client's document is fetched once: get_client, rows, uploads,
        opening, revision and whole answer from that copy until this process writes to the client or FRESH_FOR
        seconds pass. Several figures worked out of one client then cost one round trip to the database, not one
        each, which is what a person waits for when the database is far away. A block inside a block shares the
        outer one's copies; outside any block every read asks the database, as it always did."""
        if _READING.get() is not None:
            yield
            return
        token = _READING.set({})
        try:
            yield
        finally:
            _READING.reset(token)

    def _held(self, client_id: int) -> Optional[dict]:
        """Inside a reading block: the client's whole document, fetched now unless the block holds a copy that no
        write of this process has outdated; NotFound when there is no such client. Outside a block: None, and the
        caller asks the database for the part it wants."""
        held = _READING.get()
        if held is None:
            return None
        key = (id(self), client_id)
        writes = self._writes[client_id]   # read before the document, so a write made meanwhile outdates the copy
        copy = held.get(key)
        if copy is None or copy[0] != writes or time.monotonic() - copy[1] > FRESH_FOR:
            doc = self.db.clients.find_one({"id": client_id})
            if doc is None:
                held.pop(key, None)
                raise NotFound("This client was not found.")
            copy = held[key] = (writes, time.monotonic(), doc)
        return copy[2]

    def _wrote(self, client_id: int) -> None:
        """Counts a write to the client: every reading block's copy of it is out of date from here."""
        with self._writes_lock:
            self._writes[client_id] += 1

    def close(self) -> None:
        """Closes the client this store opened; a client it was given is left to whoever made it."""
        if self._owns_client:
            self.client.close()

    def _init_indexes(self):
        """Creates compound indexes for lightning-fast queries and constraints."""
        try:
            self.db.clients.create_index([("id", pymongo.ASCENDING)], unique=True)
            self.db.clients.create_index(
                [("archived_at", pymongo.ASCENDING), ("name", pymongo.ASCENDING)],
                collation={"locale": "en", "strength": 2}
            )
            self.db.clients.create_index([("id", pymongo.ASCENDING), ("uploads.id", pymongo.ASCENDING)])
            self.db.clients.create_index([("id", pymongo.ASCENDING), ("rows.id", pymongo.ASCENDING)])
            self.db.clients.create_index([("id", pymongo.ASCENDING), ("rows.upload_id", pymongo.ASCENDING)])
        except Exception as exc:
            logger.warning("Index optimization notice: %s", exc)

    def _as_client(self, doc: dict) -> Client:
        """The client of a document; for one without a first year end, its earliest row's date is looked up."""
        earliest = None
        if not doc.get("first_year_end"):
            found = self.db.clients.find_one({"id": doc["id"]}, {"rows.data.date": 1}) or {}
            dates = [r["data"]["date"] for r in found.get("rows", []) if r.get("data", {}).get("date")]
            earliest = _date(min(dates)) if dates else None
        return _client(doc, earliest)

    def _next_id(self, sequence_name: str, count: int = 1) -> int:
        """Atomically allocates `count` sequential IDs in a single round-trip."""
        counter = self.db.counters.find_one_and_update(
            {"_id": sequence_name},
            {"$inc": {"seq": count}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        # Returns starting ID of the reserved batch
        return counter["seq"] - count + 1

    def revision(self, client_id: int) -> int:
        """How many writes this client's document has had. It lives in the document, so every
        store on the same database sees the same number; older documents without one give 0."""
        try:
            doc = self._held(client_id)
        except NotFound:
            return 0
        if doc is None:
            doc = self.db.clients.find_one({"id": client_id}, {"revision": 1})
        return int(doc.get("revision", 0)) if doc else 0

    # ─── Clients ───────────────────────────────────────────────────────────────

    def create_client(self, fields: ClientFields) -> Client:
        client_id = self._next_id("client_id")
        now = now_iso()
        doc = {
            "id": client_id,
            "name": fields.name,
            "business_type": fields.business_type,
            "contact_name": fields.contact_name,
            "contact_email": fields.contact_email,
            "contact_phone": fields.contact_phone,
            "vat_registered": bool(fields.vat_registered),
            "vat_from": fields.vat_from.isoformat() if fields.vat_from else None,
            "bank_accounts": _stored_accounts(fields.bank_accounts),
            "owners": [o.model_dump(mode="json") for o in fields.owners],
            "first_year_end": fields.first_year_end.isoformat() if fields.first_year_end else None,
            "ai_review": fields.ai_review,
            "materiality": str(fields.materiality) if fields.materiality is not None else None,
            "capitalise_from": str(fields.capitalise_from) if fields.capitalise_from is not None else None,
            **{field: getattr(fields, field) for field in _REFERENCES},
            "opening": OpeningBalances().model_dump(mode="json"),
            "closed_years": [],
            "archived_at": None,
            "created_at": now,
            "updated_at": now,
            "revision": 0,
            "uploads": [],
            "rows": []
        }
        self.db.clients.insert_one(dict(doc))   # a copy: insert_one adds the _id
        self._wrote(client_id)
        return _client(doc)

    def get_client(self, client_id: int) -> Client:
        held = self._held(client_id)
        if held is not None:
            return _client(held, _earliest(held))
        doc = self.db.clients.find_one({"id": client_id}, _CLIENT_PROJECTION)
        if not doc:
            raise NotFound("This client was not found.")
        return self._as_client(doc)

    def list_clients(self, archived: bool = False) -> list[Client]:
        query = {"archived_at": {"$ne": None}} if archived else {"archived_at": None}
        docs = self.db.clients.find(
            query,
            _CLIENT_PROJECTION,
            collation={"locale": "en", "strength": 2}
        ).sort([("name", pymongo.ASCENDING), ("id", pymongo.ASCENDING)])

        return [self._as_client(d) for d in docs]

    def update_client(self, client_id: int, changes: dict) -> Client:
        client = self.get_client(client_id)
        fields = {k: changes[k] for k in _CLIENT_FIELDS if changes.get(k) is not None}
        if client.archived and fields:
            raise ClientArchived(f"Restore {client.name} to change it.")

        now = now_iso()
        set_dict = {k: bool(v) if isinstance(v, bool) else v.isoformat() if isinstance(v, dt.date)
                    else str(v) if isinstance(v, Decimal) else v for k, v in fields.items()}
        if "bank_accounts" in set_dict:
            set_dict["bank_accounts"] = _stored_accounts(
                [BankAccount.model_validate(a) for a in set_dict["bank_accounts"]])
        if "owners" in set_dict:
            set_dict["owners"] = [Owner.model_validate(o).model_dump(mode="json") for o in set_dict["owners"]]
        if "vat_from" in changes and changes["vat_from"] is None and not client.archived:
            set_dict["vat_from"] = None   # cleared: registered throughout
        if "materiality" in changes and changes["materiality"] is None and not client.archived:
            set_dict["materiality"] = None   # cleared: worked out from the client's figures
        if "capitalise_from" in changes and changes["capitalise_from"] is None and not client.archived:
            set_dict["capitalise_from"] = None   # cleared: no capitalisation threshold
        archived = changes.get("archived")
        if archived is not None and archived != client.archived:
            set_dict["archived_at"] = now if archived else None

        if set_dict:
            set_dict["updated_at"] = now
            updated = self.db.clients.find_one_and_update(
                {"id": client_id},
                {"$set": set_dict, "$inc": {"revision": 1}},
                projection=_CLIENT_PROJECTION,
                return_document=ReturnDocument.AFTER
            )
            self._wrote(client_id)
            if not updated:
                raise NotFound("This client was not found.")
            return self._as_client(updated)

        return client

    def opening(self, client_id: int) -> OpeningBalances:
        """The client's first year's opening balances; none for a client saved before it had them."""
        doc = self._held(client_id) or self.db.clients.find_one({"id": client_id}, {"opening": 1})
        if not doc:
            raise NotFound("This client was not found.")
        return OpeningBalances.model_validate(doc.get("opening") or {})

    def set_opening(self, client_id: int, opening: OpeningBalances) -> None:
        res = self.db.clients.update_one(
            {"id": client_id},
            {"$set": {"opening": opening.model_dump(mode="json"), "updated_at": now_iso()}, "$inc": {"revision": 1}})
        self._wrote(client_id)
        if res.matched_count == 0:
            raise NotFound("This client was not found.")

    def close_year(self, client_id: int, closed: ClosedYear) -> Client:
        """Adds a closed year, its closing balances kept as exact decimal strings; NotFound unless the client is
        there with that year open."""
        updated = self.db.clients.find_one_and_update(
            {"id": client_id, "closed_years.start": {"$ne": closed.start.isoformat()}},
            {"$push": {"closed_years": closed.model_dump(mode="json")}, "$set": {"updated_at": now_iso()},
             "$inc": {"revision": 1}},
            projection=_CLIENT_PROJECTION, return_document=ReturnDocument.AFTER)
        self._wrote(client_id)
        if not updated:
            raise NotFound("This client was not found, or that year is closed already.")
        return self._as_client(updated)

    def reopen_year(self, client_id: int, start: dt.date) -> Client:
        """Removes the closed year starting on start, and its saved closing balances."""
        updated = self.db.clients.find_one_and_update(
            {"id": client_id},
            {"$pull": {"closed_years": {"start": start.isoformat()}}, "$set": {"updated_at": now_iso()},
             "$inc": {"revision": 1}},
            projection=_CLIENT_PROJECTION, return_document=ReturnDocument.AFTER)
        self._wrote(client_id)
        if not updated:
            raise NotFound("This client was not found.")
        return self._as_client(updated)

    # ─── Uploads and rows ──────────────────────────────────────────────────────

    def add_upload(self, client_id: int, name: str, kind: str, rows: list[Transaction], *, sha256: str = "",
                   model: str = "", warnings=(), bank_account: Optional[str] = None,
                   year_start: Optional[dt.date] = None) -> int:
        """Saves an upload and its rows; bank_account: the account or card its statement is for, which its statement
        lines are on; year_start: the year it was added to, which its undated rows wait in."""
        self.get_client(client_id)
        upload_id = self._next_id("upload_id")
        now = now_iso()

        upload_doc = {
            "id": upload_id,
            "name": name,
            "kind": kind,
            "sha256": sha256,
            "model": model or "",
            "warnings": list(warnings),
            "bank_account": bank_account,
            "year_start": year_start.isoformat() if year_start else None,
            "created_at": now
        }

        # Optimized: Batch allocation of row IDs in single atomic DB round-trip
        count = len(rows)
        start_row_id = self._next_id("row_id", count) if count > 0 else 0

        row_docs = []
        for n, tx in enumerate(rows):
            data = saved_form(tx)
            if bank_account and data["document_type"] == "statement":
                data["bank_account"] = bank_account
            row_docs.append({
                "id": start_row_id + n,
                "upload_id": upload_id,
                "position": n,
                "data": data
            })

        self.db.clients.update_one(
            {"id": client_id},
            {
                "$push": {
                    "uploads": upload_doc,
                    "rows": {"$each": row_docs}
                },
                "$set": {"updated_at": now},
                "$inc": {"revision": 1}
            }
        )
        self._wrote(client_id)
        return upload_id

    def uploads(self, client_id: int) -> list[dict]:
        """Loads only upload metadata and row-counts using fast aggregation pipeline."""
        held = self._held(client_id)
        if held is not None:
            return _listed(client_id, held.get("uploads", []), Counter(r.get("upload_id") for r in held.get("rows", [])))
        pipeline = [
            {"$match": {"id": client_id}},
            {"$project": {
                "uploads": 1,
                "row_counts": {
                    "$map": {
                        "input": "$uploads",
                        "as": "u",
                        "in": {
                            "upload_id": "$$u.id",
                            "count": {
                                "$size": {
                                    "$filter": {
                                        "input": "$rows",
                                        "as": "r",
                                        "cond": {"$eq": ["$$r.upload_id", "$$u.id"]}
                                    }
                                }
                            }
                        }
                    }
                }
            }}
        ]
        result_docs = list(self.db.clients.aggregate(pipeline))
        if not result_docs:
            raise NotFound("This client was not found.")

        doc = result_docs[0]
        counts = {item["upload_id"]: item["count"] for item in doc.get("row_counts", [])}
        return _listed(client_id, doc.get("uploads", []), counts)

    def set_upload_bank(self, client_id: int, upload_id: int, code: str) -> None:
        """Puts the upload, and its statement lines, on another bank account or card."""
        res = self.db.clients.update_one(
            {"id": client_id, "uploads.id": upload_id},
            {
                "$set": {"uploads.$[u].bank_account": code, "rows.$[r].data.bank_account": code,
                         "updated_at": now_iso()},
                "$inc": {"revision": 1}
            },
            array_filters=[{"u.id": upload_id}, {"r.upload_id": upload_id, "r.data.document_type": "statement"}]
        )
        self._wrote(client_id)
        if res.matched_count == 0:
            raise NotFound("This upload was not found.")

    def delete_upload(self, client_id: int, upload_id: int) -> None:
        now = now_iso()
        res = self.db.clients.update_one(
            {"id": client_id, "uploads.id": upload_id},
            {
                "$pull": {
                    "uploads": {"id": upload_id},
                    "rows": {"upload_id": upload_id}
                },
                "$set": {"updated_at": now},
                "$inc": {"revision": 1}
            }
        )
        self._wrote(client_id)
        if res.matched_count == 0:
            raise NotFound("This upload was not found.")

    def delete_row(self, client_id: int, row_id: int) -> None:
        doc = self.db.clients.find_one(
            {"id": client_id, "rows.id": row_id},
            {"rows": {"$elemMatch": {"id": row_id}}}
        )
        if not doc or not doc.get("rows"):
            raise NotFound("This row was not found.")

        upload_id = doc["rows"][0]["upload_id"]

        # Check if any other rows belong to this upload
        sibling = self.db.clients.find_one(
            {"id": client_id, "rows": {"$elemMatch": {"upload_id": upload_id, "id": {"$ne": row_id}}}},
            {"_id": 1}
        )
        remaining = sibling is not None

        now = now_iso()
        pull_dict = {"rows": {"id": row_id}}
        if not remaining:
            pull_dict["uploads"] = {"id": upload_id}

        self.db.clients.update_one(
            {"id": client_id},
            {
                "$pull": pull_dict,
                "$set": {"updated_at": now},
                "$inc": {"revision": 1}
            }
        )
        self._wrote(client_id)

    def rows(self, client_id: int) -> list[StoredRow]:
        doc = self._held(client_id) or self.db.clients.find_one({"id": client_id}, {"rows": 1, "id": 1})
        if not doc:
            raise NotFound("This client was not found.")

        return _stored(doc.get("rows", []))

    def whole(self, client_id: int) -> tuple[Client, list[StoredRow], list[dict], OpeningBalances]:
        """The client, its rows, its uploads and its opening balances, each as get_client, rows, uploads and opening
        give it, read together in one round trip to the database. A calculation that needs them all (books._books)
        asks once instead of four times, which matters when the database is far away, and works from one moment of
        the client rather than four."""
        doc = self._held(client_id) or self.db.clients.find_one({"id": client_id})
        if not doc:
            raise NotFound("This client was not found.")
        rows = doc.get("rows", [])
        counts = Counter(r.get("upload_id") for r in rows)
        return (_client(doc, _earliest(doc)), _stored(rows), _listed(client_id, doc.get("uploads", []), counts),
                OpeningBalances.model_validate(doc.get("opening") or {}))

    def patch_row(self, client_id: int, row_id: int, changes: dict, *, revert: bool = False) -> None:
        """Changes a row (and a whole-document field on the rows of its document), or puts them back as read.

        The rows are read, changed here and written back whole, so the write only goes through when the client's
        document still has the revision it was read at: an upload or another change saved in between (say, a
        job saving an upload while a person edits a row) would otherwise be overwritten. Then it reads and
        tries again, and after _PATCH_TRIES lost races it gives up and asks the person to try again."""
        for _ in range(_PATCH_TRIES):
            doc = self.db.clients.find_one({"id": client_id, "rows.id": row_id}, {"rows": 1, "revision": 1})
            if not doc:
                raise NotFound("This row was not found.")
            rows = doc.get("rows", [])
            if not self._patched(rows, row_id, changes, revert):
                return
            # A document saved before revisions were kept has none: $inc starts it at 1.
            read_at = doc["revision"] if "revision" in doc else {"$exists": False}
            saved = self.db.clients.update_one(
                {"id": client_id, "revision": read_at},
                {"$set": {"rows": rows, "updated_at": now_iso()}, "$inc": {"revision": 1}})
            if saved.matched_count:
                self._wrote(client_id)
                return
        raise ChangedMeanwhile("The client's rows changed while this change was being saved, so it wasn't saved. "
                               "Try again.")

    def add_split(self, client_id: int, row_id: int, parts: list[Transaction], decision_id: str) -> list[int]:
        """Replaces a row with parts (a mixed-VAT receipt split by its VAT rates): the row is kept, marked as
        superseded by the decision, and the parts are added as a new upload, "<its upload's name> (split)", of
        the same year. Returns the parts' row ids. Like patch_row, it writes only if the client's document still
        has the revision it was read at, and otherwise reads and tries again."""
        ids: Optional[tuple[int, int]] = None   # the new upload's id and its first row id, allocated once
        for _ in range(_PATCH_TRIES):
            doc = self.db.clients.find_one({"id": client_id, "rows.id": row_id}, {"rows": 1, "uploads": 1, "revision": 1})
            if not doc:
                raise NotFound("This row was not found.")
            rows = doc.get("rows", [])
            target = next(r for r in rows if r["id"] == row_id)
            if target["data"].get("superseded_by") or target["data"].get("excluded"):
                raise ChangedMeanwhile("The row was split or dropped while this split was being made, so it "
                                       "wasn't saved.")
            upload = next((u for u in doc.get("uploads", []) if u["id"] == target["upload_id"]), {})
            if ids is None:
                ids = (self._next_id("upload_id"), self._next_id("row_id", len(parts)) if parts else 0)
            upload_id, first_row_id = ids

            now = now_iso()
            target["data"]["superseded_by"] = decision_id
            target["data"]["decision_ids"] = [*target["data"].get("decision_ids", []), decision_id]
            part_docs = [{"id": first_row_id + n, "upload_id": upload_id, "position": n,
                          "data": saved_form(part.model_copy(update={"decision_ids": [decision_id]}))}
                         for n, part in enumerate(parts)]
            upload_doc = {"id": upload_id, "name": f"{upload.get('name', '')} (split)", "kind": "split", "sha256": "",
                          "model": "", "warnings": [], "bank_account": None,
                          "year_start": upload.get("year_start"), "created_at": now}
            read_at = doc["revision"] if "revision" in doc else {"$exists": False}
            saved = self.db.clients.update_one(
                {"id": client_id, "revision": read_at},
                {"$set": {"rows": [*rows, *part_docs], "updated_at": now},
                 "$push": {"uploads": upload_doc}, "$inc": {"revision": 1}})
            if saved.matched_count:
                self._wrote(client_id)
                return [p["id"] for p in part_docs]
        raise ChangedMeanwhile("The client's rows changed while this split was being saved, so it wasn't saved. "
                               "Try again.")

    def row_data(self, client_id: int, row_ids) -> dict[int, dict]:
        """The rows' data exactly as stored, by row id: the inputs, the saved issues, and what a person's first edit
        kept (original, original_issues), for put_row_data to write back."""
        doc = self.db.clients.find_one({"id": client_id}, {"rows": 1})
        if not doc:
            raise NotFound("This client was not found.")
        wanted = set(row_ids)
        return {r["id"]: r["data"] for r in doc.get("rows", []) if r["id"] in wanted}

    def raw_rows(self, client_id: int, row_ids) -> tuple[list[dict], list[dict]]:
        """The stored rows with these ids, and the uploads they belong to, whole, for restore_rows to put back."""
        doc = self.db.clients.find_one({"id": client_id}, {"rows": 1, "uploads": 1})
        if not doc:
            raise NotFound("This client was not found.")
        rows = [r for r in doc.get("rows", []) if r["id"] in set(row_ids)]
        wanted = {r["upload_id"] for r in rows}
        return rows, [u for u in doc.get("uploads", []) if u["id"] in wanted]

    def restore_rows(self, client_id: int, rows: list[dict], uploads: list[dict]) -> None:
        """Adds back whichever of these rows and uploads (as raw_rows read them) the client no longer has."""
        doc = self.db.clients.find_one({"id": client_id}, {"rows.id": 1, "uploads.id": 1})
        if not doc:
            raise NotFound("This client was not found.")
        have_rows = {r["id"] for r in doc.get("rows", [])}
        have_uploads = {u["id"] for u in doc.get("uploads", [])}
        push = {}
        if missing := [r for r in rows if r["id"] not in have_rows]:
            push["rows"] = {"$each": missing}
        if missing_uploads := [u for u in uploads if u["id"] not in have_uploads]:
            push["uploads"] = {"$each": missing_uploads}
        if push:
            self.db.clients.update_one({"id": client_id}, {"$push": push, "$set": {"updated_at": now_iso()},
                                                           "$inc": {"revision": 1}})
            self._wrote(client_id)

    def put_row_data(self, client_id: int, data: dict[int, dict]) -> None:
        """Writes rows' data back as row_data read it, replacing it whole. Like patch_row, it writes only if the
        client's document still has the revision it was read at, and otherwise reads and tries again."""
        for _ in range(_PATCH_TRIES):
            doc = self.db.clients.find_one({"id": client_id}, {"rows": 1, "revision": 1})
            if not doc:
                raise NotFound("This client was not found.")
            rows = doc.get("rows", [])
            found = [r for r in rows if r["id"] in data]
            if not found:
                return
            for r in found:
                r["data"] = data[r["id"]]
            read_at = doc["revision"] if "revision" in doc else {"$exists": False}
            saved = self.db.clients.update_one(
                {"id": client_id, "revision": read_at},
                {"$set": {"rows": rows, "updated_at": now_iso()}, "$inc": {"revision": 1}})
            if saved.matched_count:
                self._wrote(client_id)
                return
        raise ChangedMeanwhile("The client's rows changed while they were being put back, so they weren't. "
                               "Try again.")

    @staticmethod
    def _patched(rows: list[dict], row_id: int, changes: dict, revert: bool) -> bool:
        """Applies the change to the rows as read, in place, and says whether anything changed."""
        target = next((r for r in rows if r["id"] == row_id), None)
        if not target:
            raise NotFound("This row was not found.")

        ref = target["data"].get("document_ref")
        claim_line = target["data"].get("document_type") == "expense_claim"
        whole = WHOLE_DOCUMENT - {"include"} if claim_line else WHOLE_DOCUMENT

        # An amount converted from another currency: the totals its document prints are in that currency, so they
        # are set aside on every row of the document (and come back on revert) rather than checked against pounds.
        converted = "currency" in changes and changes["currency"] != target["data"].get("currency")
        modified = False
        for r in rows:
            rid = r["id"]
            r_data = r["data"]
            if rid != row_id and not (ref and r_data.get("document_ref") == ref):
                continue

            if revert:
                if "original_printed" in r_data:
                    r_data.update(r_data.pop("original_printed"))
                    modified = True
                if "original" not in r_data:
                    continue
                r_data.update(r_data.pop("original"))
                r_data["issues"] = r_data.pop("original_issues", r_data.get("issues", []))
                r_data.pop("vat_confirmed", None)   # as read: no person vouches for its VAT
                modified = True
            else:
                change = changes if rid == row_id else {k: v for k, v in changes.items() if k in whole}
                if converted and "original_printed" not in r_data and (
                        r_data.get("document_total") is not None or r_data.get("document_net") is not None):
                    r_data["original_printed"] = {k: r_data.get(k) for k in ("document_total", "document_net")}
                    r_data.update(document_total=None, document_net=None)
                    modified = True
                if not change:
                    continue
                if "original" not in r_data and any(k in EDITABLE and r_data.get(k) != v for k, v in change.items()):
                    r_data["original"] = {k: r_data.get(k) for k in EDITABLE}
                    r_data["original_issues"] = r_data.get("issues", [])
                    r_data["issues"] = []
                r_data.update(change)
                modified = True
        return modified
