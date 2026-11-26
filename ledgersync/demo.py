"""The directors' demo client, Northbridge Consulting Ltd (demo/northbridge/), put back as the demo starts: the
client as client.json describes it, its opening balances, and September already read, with nothing the chat or a
person has done since.

  .venv/bin/python -m ledgersync.demo reset
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from pymongo.database import Database

from . import books, ledger, upkeep
from .config import Settings
from .models import Client, ClientFields, ClientPatch, OpeningBalances, Transaction
from .records import AgentRecords
from .store_mongo import MongoStore
from .years import year_bounds

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo" / "northbridge"
# What the chat keeps for a client beside its rows. decisions, ledger_entries and posting_batches are append-only;
# the demo reset is the one thing that deletes from them.
_KEPT_FOR_CLIENT = ("decisions", "questions", "chat_threads", "ledger_entries", "posting_batches", "changes",
                     "review_runs", "review_state", "review_rejected")


def _read(name: str):
    return json.loads((DEMO_DIR / name).read_text())


def _find(store: MongoStore, name: str) -> Optional[Client]:
    """The client of this name, archived or not."""
    return next((c for c in [*store.list_clients(), *store.list_clients(archived=True)] if c.name == name), None)


def _clear(store: MongoStore, records: AgentRecords, db: Database, client: Client) -> None:
    """Removes everything the client has gained: its uploads and rows, any closed year, and the chat's records,
    threads and checkpoints. Restores it if archived."""
    if client.archived:
        store.update_client(client.id, {"archived": False})
    for year in client.closed_years:
        store.reopen_year(client.id, year.start)
    for upload in store.uploads(client.id):
        store.delete_upload(client.id, upload["id"])
    threads = [t.id for t in records.threads(client.id)]
    for name in ("checkpoints", "checkpoint_writes"):   # LangGraph's MongoDBSaver, by thread
        db[name].delete_many({"thread_id": {"$in": threads}})
    for name in _KEPT_FOR_CLIENT:
        records.db[name].delete_many({"client_id": client.id})


def reset(store: MongoStore, records: AgentRecords, db: Database) -> int:
    """Puts the demo client back as the demo starts, and returns its id: found by name (or added the first time)
    so its id and links stay the same, emptied (see _clear), given client.json's fields and opening_balances.json,
    and loaded with existing/*.json as uploads already read, added to its first year, then settled as a change
    would settle it (the rules' questions asked, the books posted). Those have no original file, so no text. db: the database the chat's LangGraph checkpoints are kept in. Run twice, it leaves the same rows."""
    fields = ClientFields.model_validate(_read("client.json"))
    found = _find(store, fields.name)
    if found is None:
        client = ledger.add_client(store, fields)
    else:
        _clear(store, records, db, found)
        client = ledger.change_client(store, found.id, ClientPatch(**fields.model_dump()))
    books.set_opening(store, client.id, OpeningBalances.model_validate(_read("opening_balances.json")))
    year_start = year_bounds(client.first_year_end, 0)[0]
    for path in sorted((DEMO_DIR / "existing").glob("*.json")):
        upload = json.loads(path.read_text())
        store.add_upload(client.id, upload["name"], upload["kind"],
                         [Transaction.model_validate(t) for t in upload["transactions"]],
                         bank_account=upload["bank_account"], year_start=year_start)
    upkeep.settle_open_years(store, records, client.id)   # the demo starts up to date: questions asked, books posted
    return client.id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ledgersync.demo", description="The directors' demo client.")
    parser.add_argument("command", choices=["reset"], help="put Northbridge Consulting Ltd back as the demo starts")
    parser.parse_args(argv)
    settings = Settings.from_env()
    if not settings.mongodb_uri:
        print("Set MONGODB_URI in .env: the demo client is kept in MongoDB.")
        return 1
    store = MongoStore(settings.mongodb_uri, settings.mongodb_db_name, max_pool=settings.mongodb_max_pool)
    try:
        client_id = reset(store, AgentRecords(store.db), store.client[f"{settings.mongodb_db_name}_checkpoints"])
    finally:
        store.close()
    print(f"Northbridge Consulting Ltd is reset (client {client_id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
