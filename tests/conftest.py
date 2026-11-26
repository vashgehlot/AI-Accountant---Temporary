"""Shared fixtures. The MongoDB ones run against a throwaway database on the test cluster."""
import os
from datetime import date
from uuid import uuid4

import pytest
from pymongo import MongoClient

from ledgersync.config import ENV_FILE, read_env_file
from ledgersync.models import ClientFields
from ledgersync.store_mongo import MongoStore


def _test_uri():
    """The test cluster's URI from the process environment laid over .env (pytest doesn't load .env)."""
    return {**read_env_file(ENV_FILE), **os.environ}.get("LEDGERSYNC_TEST_MONGODB_URI")


@pytest.fixture(scope="session")
def mongo_client():
    """The one small client every MongoDB test shares (Atlas M0 allows 500 connections in all), closed when the
    session ends."""
    uri = _test_uri()
    if not uri:
        pytest.skip("Set LEDGERSYNC_TEST_MONGODB_URI to run MongoDB tests")
    client = MongoClient(uri, maxPoolSize=5, minPoolSize=0)
    yield client
    client.close()


@pytest.fixture
def mongo_db(mongo_client):
    """A fresh `ledgersync_test_<hex>` database, dropped after the test with the `<name>_checkpoints`
    database an app on it writes LangGraph's checkpoints to."""
    db = mongo_client[f"ledgersync_test_{uuid4().hex[:8]}"]
    try:
        yield db
    finally:
        mongo_client.drop_database(db.name)
        mongo_client.drop_database(f"{db.name}_checkpoints")


@pytest.fixture
def mongo_store(mongo_db, mongo_client):
    """A MongoStore on the throwaway database, sharing the session's client."""
    return MongoStore(_test_uri(), mongo_db.name, client=mongo_client)


@pytest.fixture
def acme(mongo_store) -> int:
    """The id of Acme Ltd: a VAT registered limited company whose first year ends on 31 Mar 2026, with one bank
    account (1200) and no rows."""
    return mongo_store.create_client(ClientFields(name="Acme Ltd", business_type="limited_company",
                                                  contact_name="Ann Smith", vat_registered=True,
                                                  first_year_end=date(2026, 3, 31))).id
