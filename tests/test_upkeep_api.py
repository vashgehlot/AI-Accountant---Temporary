"""Every change a person makes from the pages is recorded and settles the client's books at once."""
import datetime as dt
import json
import time

import pytest
from fakes import ROW, FakeModel, transactions_json
from fastapi.testclient import TestClient

from ledgersync import ledger_book, upkeep
from ledgersync.blobs import MemoryBlobStore
from ledgersync.config import Settings
from ledgersync.models import Transaction
from ledgersync.records import AgentRecords
from server import create_app

CUBE = {"name": "Business Cube Ltd", "business_type": "limited_company", "contact_name": "Jenny Clarke",
        "contact_email": "jenny@businesscube.co.uk", "first_year_end": "2027-03-31",
        "bank_accounts": [{"code": "1200", "name": "Barclays current", "kind": "current"},
                          {"name": "Amex card", "kind": "credit_card"}]}
YEAR = "2026-04-01"
BILL = {"direction": "out", "gross": "72.00", "account_code": "7502", "date": "2026-09-01", "description": "BT",
        "document_type": "invoice", "counterparty": "BT Business", "document_ref": "bt"}
SCREWFIX_LINE = {"direction": "out", "gross": "86.40", "account_code": "5000", "date": "2026-10-03",
                 "description": "Screwfix", "document_type": "statement", "counterparty": "Screwfix Direct",
                 "document_ref": "sf-line"}
SCREWFIX_RECEIPT = {**SCREWFIX_LINE, "document_type": "receipt", "document_ref": "sf-receipt"}
STATEMENT_LINE = json.dumps({"transactions": [dict(ROW, document_type="statement")]})


@pytest.fixture
def api(mongo_store):
    opened = []

    def _make(model=None):
        app = create_app(Settings(warmup=False), model_client=model or FakeModel([STATEMENT_LINE]),
                         store=mongo_store, blobs=MemoryBlobStore())
        client = TestClient(app, headers={"X-LedgerSync": "1"})
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def add(client):
    resp = client.post("/api/clients", json=CUBE)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def manual(client, cid, *rows):
    resp = client.post(f"/api/clients/{cid}/uploads", json={"transactions": list(rows)})
    assert resp.status_code == 201, resp.text
    return resp.json()


def finish(client, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_a_receipt_uploaded_outside_the_chat_clears_its_question(api, mongo_store):
    client = api()
    cid = add(client)
    manual(client, cid, SCREWFIX_LINE)
    [question] = client.get(f"/api/clients/{cid}/questions").json()
    assert question["kind"] == "receipt_or_invoice"
    posted = client.get(f"/api/clients/{cid}/years/{YEAR}/posted-trial-balance").json()
    assert [s["gross"] for s in posted["suspense"]] == ["86.40"] and posted["unposted_changes"] == 0

    receipt = manual(client, cid, SCREWFIX_RECEIPT)
    assert client.get(f"/api/clients/{cid}/questions").json() == []
    [resolved] = AgentRecords(mongo_store.db).questions(cid, None, statuses=("resolved",))
    upload_of_receipt = next(t["upload_id"] for t in receipt["transactions"] if t["document_type"] == "receipt")
    name = next(u["name"] for u in receipt["uploads"] if u["id"] == upload_of_receipt)
    assert resolved.answer == f"Matched to {name}"
    posted = client.get(f"/api/clients/{cid}/years/{YEAR}/posted-trial-balance").json()
    assert posted["suspense"] == [] and posted["unposted_changes"] == 0
    tb = client.get(f"/api/clients/{cid}/years/{YEAR}/trial-balance").json()
    assert all(line["code"] != "9998" for line in tb["lines"])


def _setup_row(client, cid):
    ledger = manual(client, cid, BILL)
    return ledger["transactions"][0]["id"]


def _row_edit(client, cid, row):
    return client.patch(f"/api/clients/{cid}/rows/{row}", json={"description": "BT broadband"})


def _row_include(client, cid, row):
    return client.patch(f"/api/clients/{cid}/rows/{row}", json={"include": False})


def _row_apart(client, cid, row):
    other = manual(client, cid, {**BILL, "document_ref": "bt2"})["transactions"][-1]["id"]
    return client.patch(f"/api/clients/{cid}/rows/{row}", json={"apart_from": [other]})


def _row_revert(client, cid, row):
    client.patch(f"/api/clients/{cid}/rows/{row}", json={"description": "BT broadband"})
    return client.patch(f"/api/clients/{cid}/rows/{row}", json={"revert": True})


def _row_link(client, cid, row):
    line = manual(client, cid, SCREWFIX_LINE)["transactions"][-1]["id"]
    return client.patch(f"/api/clients/{cid}/rows/{line}", json={"link": ["bt"]})


ROW_CASES = [
    (_row_edit, "row_edited", "Row {row} changed: description"),
    (_row_include, "row_included", "Row {row} changed: include"),
    (_row_apart, "rows_apart", "Row {row} changed: apart_from"),
    (_row_revert, "row_reverted", "Row {row} changed: revert"),
    (_row_link, "row_linked", "Row {row} changed: link"),
]


@pytest.mark.parametrize("act,kind,summary", ROW_CASES)
def test_each_row_patch_records_one_change(api, mongo_db, act, kind, summary):
    client = api()
    cid = add(client)
    row = _setup_row(client, cid)
    resp = act(client, cid, row)
    assert resp.status_code == 200, resp.text
    last = AgentRecords(mongo_db).changes(cid)[-1]
    assert (last.kind, last.actor) == (kind, "user")
    assert last.summary == summary.format(row=last.row_ids[0])


def _last(mongo_db, cid):
    return AgentRecords(mongo_db).changes(cid)[-1]


def test_each_other_route_records_one_change(api, mongo_db):
    client = api()
    cid = add(client)
    ledger = manual(client, cid, BILL, BILL | {"document_ref": "bt3"})
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary) == ("row_added", "2 rows added by hand")
    row = ledger["transactions"][0]["id"]
    manual_upload = ledger["uploads"][-1]["id"]

    assert client.delete(f"/api/clients/{cid}/rows/{row}").status_code == 200
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary, last.row_ids) == ("row_removed", f"Row {row} removed", [row])
    assert last.before["description"] == "BT" and last.before["gross"] == "72.00"

    assert client.patch(f"/api/clients/{cid}", json={"contact_name": "Jen"}).status_code == 200
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary) == ("client_changed", "Client details changed: contact_name")
    assert (last.before, last.after) == ({"contact_name": "Jenny Clarke"}, {"contact_name": "Jen"})

    opening = {"lines": [{"code": "1200", "debit": "200.00", "credit": "0.00"},
                         {"code": "3200", "debit": "0.00", "credit": "200.00"}], "unpaid": []}
    resp = client.put(f"/api/clients/{cid}/opening-balances", json=opening)
    assert resp.status_code == 200, resp.text
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary) == ("opening_balances_changed", "Opening balances changed")

    assert client.delete(f"/api/clients/{cid}/uploads/{manual_upload}").status_code == 200
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary, last.upload_id) == ("upload_removed", "Manual entry removed", manual_upload)

    assert client.post(f"/api/clients/{cid}/years/{YEAR}/close").status_code == 200
    assert client.post(f"/api/clients/{cid}/years/{YEAR}/reopen").status_code == 200
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary, str(last.year_start)) == ("year_reopened",
                                                               "Year to 31 Mar 2027 reopened", YEAR)


def test_moving_an_upload_to_another_bank_records_it(api, mongo_db):
    client = api()
    cid = add(client)
    job = client.post("/api/analyze", data={"client_id": str(cid), "text": "Amex lines", "bank_account": "1240"})
    assert finish(client, job.json()["job_id"])["status"] == "succeeded"
    [upload] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"]
    resp = client.patch(f"/api/clients/{cid}/uploads/{upload['id']}", json={"bank_account": "1200"})
    assert resp.status_code == 200, resp.text
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary, last.upload_id) == ("upload_bank_changed", "Pasted text moved to 1200",
                                                         upload["id"])
    assert (last.before, last.after) == ({"bank_account": "1240"}, {"bank_account": "1200"})


def test_a_refused_change_records_nothing(api, mongo_db):
    client = api()
    cid = add(client)
    before = len(AgentRecords(mongo_db).changes(cid))
    assert client.patch(f"/api/clients/{cid}/rows/999", json={"description": "x"}).status_code == 404
    assert len(AgentRecords(mongo_db).changes(cid)) == before


def test_reading_an_upload_records_upload_read(api, mongo_db):
    client = api()
    cid = add(client)
    job = client.post("/api/analyze", data={"client_id": str(cid), "text": "Amex lines", "bank_account": "1240"})
    result = finish(client, job.json()["job_id"])
    assert result["status"] == "succeeded"
    last = _last(mongo_db, cid)
    assert (last.kind, last.upload_id, last.summary) == ("upload_read", result["result"]["upload_id"],
                                                         "Pasted text read: 1 row")
    assert last.actor == "user"


def test_a_row_edit_succeeds_when_upkeep_fails(api, monkeypatch):
    client = api()
    cid = add(client)
    row = _setup_row(client, cid)

    def broken(*args, **kwargs):
        raise RuntimeError("settling failed")

    monkeypatch.setattr(upkeep, "settle", broken)
    resp = client.patch(f"/api/clients/{cid}/rows/{row}", json={"description": "BT broadband"})
    assert resp.status_code == 200, resp.text
    saved = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    assert [t["description"] for t in saved if t["id"] == row] == ["BT broadband"]


def test_manual_rows_and_row_changes_record_their_year_upload_and_rows(api, mongo_db):
    client = api()
    cid = add(client)
    ledger = manual(client, cid, BILL)
    last = _last(mongo_db, cid)
    row = ledger["transactions"][0]["id"]
    assert (str(last.year_start), last.upload_id, last.row_ids) == (YEAR, ledger["uploads"][-1]["id"], [row])

    assert _row_edit(client, cid, row).status_code == 200
    assert str(_last(mongo_db, cid).year_start) == YEAR
    assert client.delete(f"/api/clients/{cid}/rows/{row}").status_code == 200
    assert str(_last(mongo_db, cid).year_start) == YEAR


def test_closing_a_year_records_it(api, mongo_db):
    client = api()
    cid = add(client)
    assert client.post(f"/api/clients/{cid}/years/{YEAR}/close").status_code == 200
    last = _last(mongo_db, cid)
    assert (last.kind, last.summary, str(last.year_start)) == ("year_closed", "Year to 31 Mar 2027 closed", YEAR)


def test_a_change_succeeds_when_recording_it_fails(api, monkeypatch, caplog):
    client = api()
    cid = add(client)
    row = _setup_row(client, cid)

    def broken(self, change):
        raise RuntimeError("the record is down")

    monkeypatch.setattr(AgentRecords, "add_change", broken)
    with caplog.at_level("ERROR", logger="ledgersync.upkeep"):
        resp = client.patch(f"/api/clients/{cid}/rows/{row}", json={"description": "BT broadband"})
    assert resp.status_code == 200, resp.text
    assert any(r.name == "ledgersync.upkeep" and r.exc_info for r in caplog.records)


def test_a_client_whose_rows_were_saved_without_the_upkeep_reads_nothing_unposted(api, mongo_store):
    client = api()
    cid = add(client)
    mongo_store.add_upload(cid, "old.csv", "csv", [Transaction(**BILL | {"gross": "72.00", "direction": "out"})],
                           year_start=dt.date.fromisoformat(YEAR))
    assert ledger_book.unposted_changes(mongo_store, AgentRecords(mongo_store.db), cid,
                                        dt.date.fromisoformat(YEAR)) > 0

    posted = client.get(f"/api/clients/{cid}/years/{YEAR}/posted-trial-balance").json()

    assert posted["unposted_changes"] == 0 and posted["lines"]
