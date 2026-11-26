import hashlib
import json
import threading
import time

import pytest
from fakes import ROW, FakeModel, transactions_json
from fastapi.testclient import TestClient

from ledgersync.config import Settings
from ledgersync.blobs import MemoryBlobStore
from ledgersync.errors import ModelError
from ledgersync.store_mongo import MongoStore
from server import create_app

CUBE = {"name": "Business Cube Ltd", "business_type": "limited_company", "contact_name": "Jenny Clarke",
        "contact_email": "jenny@businesscube.co.uk", "first_year_end": "2027-03-31"}
YEAR = "2026-04-01"   # the year its rows are in
BILL = {"direction": "out", "gross": "72.00", "account_code": "7502", "date": "2026-09-01", "description": "BT",
        "document_type": "invoice", "counterparty": "BT Business", "document_ref": "bt"}
LINE = {**BILL, "date": "2026-09-05", "document_type": "statement", "counterparty": "BT BUSINESS DD",
        "document_ref": "l1"}


@pytest.fixture
def api(mongo_store):
    opened = []

    def _make(model=None):
        app = create_app(Settings(warmup=False), model_client=model or FakeModel([]),
                         store=mongo_store)
        client = TestClient(app, headers={"X-LedgerSync": "1"})   # as the LedgerSync pages send
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def add(client, **changes):
    resp = client.post("/api/clients", json={**CUBE, **changes})
    assert resp.status_code == 201, resp.text
    return resp.json()


def manual(client, client_id, *rows):
    resp = client.post(f"/api/clients/{client_id}/uploads", json={"transactions": list(rows)})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_client_is_added_listed_and_read(api):
    client = api()
    added = add(client)
    assert (added["name"], added["archived"], added["vat_registered"]) == ("Business Cube Ltd", False, True)
    [summary] = client.get("/api/clients").json()
    assert (summary["id"], summary["rows"], summary["to_review"]) == (added["id"], 0, 0)
    assert client.get(f"/api/clients/{added['id']}").json() == added


def test_archiving_hides_a_client_until_it_is_restored(api):
    client = api()
    added = add(client)
    assert client.patch(f"/api/clients/{added['id']}", json={"archived": True}).json()["archived"] is True
    assert client.get("/api/clients").json() == []
    assert [c["id"] for c in client.get("/api/clients?archived=true").json()] == [added["id"]]
    refused = client.patch(f"/api/clients/{added['id']}", json={"name": "Renamed"})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "client_archived")
    assert client.patch(f"/api/clients/{added['id']}", json={"archived": False}).json()["archived"] is False


@pytest.mark.parametrize("changes, message", [({"name": " "}, "Enter the company name."),
                                              ({"contact_name": ""}, "Enter the responsible person."),
                                              ({"contact_email": "jenny"}, "Enter a valid email.")])
def test_a_client_needs_its_details(api, changes, message):
    resp = api().post("/api/clients", json={**CUBE, **changes})
    assert (resp.status_code, resp.json()["detail"]) == (422, {"code": "invalid_input", "message": message})


def test_an_unknown_business_type_or_client_is_refused(api):
    client = api()
    assert client.post("/api/clients", json={**CUBE, "business_type": "charity"}).status_code == 422
    missing = client.get(f"/api/clients/99/years/{YEAR}/ledger")
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "not_found")


def test_the_ledger_pairs_a_bill_and_its_payment_saved_in_two_uploads(api):
    client = api()
    cid = add(client)["id"]
    manual(client, cid, BILL)
    ledger = manual(client, cid, LINE)
    bill, line = ledger["transactions"]
    assert ([s["ref"] for s in line["pays"]], bill["owed"]) == (["bt"], "0.00")
    assert [u["name"] for u in ledger["uploads"]] == ["Manual entry", "Manual entry"]
    assert (line["edited"], line["original"]) == (False, None)


def test_a_years_invoices_bank_checks_and_summary_are_served(api):
    client = api()
    cid = add(client)["id"]
    manual(client, cid, BILL)
    year = f"/api/clients/{cid}/years/{YEAR}"
    [bill] = client.get(f"{year}/invoices").json()
    assert (bill["kind"], bill["total"], bill["paid"], bill["owed"]) == ("purchase", "72.00", "0.00", "72.00")
    [bank] = client.get(f"{year}/bank").json()
    assert (bank["code"], bank["books"], bank["statement"]) == ("1200", "0.00", None)
    summary = client.get(f"{year}/summary").json()
    assert (summary["rows"], summary["unpaid_purchases"], summary["trial_balance"]) == (1, "72.00", "balanced")
    for view in ("invoices", "bank", "summary"):
        assert client.get(f"/api/clients/{cid}/years/2020-04-01/{view}").status_code == 404


def test_an_amount_in_another_currency_is_converted_by_an_edit_and_revert_puts_it_back(api):
    client = api()
    cid = add(client)["id"]
    manual(client, cid, {**BILL, "gross": "500.00", "currency": "USD", "document_total": "500.00"})
    year = f"/api/clients/{cid}/years/{YEAR}"
    [read] = client.get(f"{year}/ledger").json()["transactions"]
    assert [i["code"] for i in read["issues"]] == ["non_gbp_currency"]
    # the trial balance still shows, without the row, and says it is left out; so does the bank check
    assert client.get(f"{year}/trial-balance").status_code == 422
    blocked = client.get(f"{year}/trial-balance?shown=true")
    assert blocked.status_code == 200 and (blocked.json()["lines"], len(blocked.json()["left_out"])) == ([], 1)
    assert "Read as USD 500.00" in blocked.json()["left_out"][0]
    assert [c["left_out"] for c in client.get(f"{year}/bank").json()] == [1]
    refused = client.patch(f"/api/clients/{cid}/rows/{read['id']}", json={"currency": "EUR"})
    assert (refused.status_code, refused.json()["detail"]["message"]) == (
        422, "An amount can only be converted to pounds.")
    [row] = client.patch(f"/api/clients/{cid}/rows/{read['id']}",
                         json={"gross": "396.42", "currency": "GBP"}).json()["transactions"]
    assert (row["gross"], row["currency"], row["issues"], row["original"]["currency"]) == ("396.42", "GBP", [], "USD")
    fixed = client.get(f"{year}/trial-balance?shown=true")
    assert fixed.status_code == 200 and fixed.json()["left_out"] == [] and fixed.json()["lines"]
    [back] = client.patch(f"/api/clients/{cid}/rows/{read['id']}", json={"revert": True}).json()["transactions"]
    assert (back["gross"], back["currency"], back["document_total"]) == ("500.00", "USD", "500.00")


def test_links_and_edits_rematch_the_ledger_and_revert_undoes_an_edit(api):
    client = api()
    cid = add(client)["id"]
    manual(client, cid, BILL, LINE)
    bill_id, line_id = (r["id"] for r in client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"])
    unlinked = client.patch(f"/api/clients/{cid}/rows/{line_id}", json={"link": []}).json()["transactions"]
    assert (unlinked[0]["owed"], unlinked[1]["pays"]) == ("72.00", [])
    [edited, _] = client.patch(f"/api/clients/{cid}/rows/{bill_id}", json={"gross": "70.00"}).json()["transactions"]
    assert (edited["gross"], edited["edited"], edited["original"]["gross"]) == ("70.00", True, "72.00")
    bad = client.patch(f"/api/clients/{cid}/rows/{bill_id}", json={"link": []})
    assert (bad.status_code, bad.json()["detail"]["message"]) == (
        422, "Only a bank line, or an item of an agent's statement, can be linked to documents.")
    [back, _] = client.patch(f"/api/clients/{cid}/rows/{bill_id}", json={"revert": True}).json()["transactions"]
    assert (back["gross"], back["edited"]) == ("72.00", False)


def test_removing_an_upload_leaves_a_stale_link(api):
    client = api()
    cid = add(client)["id"]
    bill_upload = manual(client, cid, BILL)["uploads"][0]["id"]
    manual(client, cid, {**LINE, "link": ["bt"]})
    [line] = client.delete(f"/api/clients/{cid}/uploads/{bill_upload}").json()["transactions"]
    assert "stale_link" in [i["code"] for i in line["issues"]]


def test_removing_a_copy_row_clears_its_warning_and_books_the_bill_again(api):
    # A person removes one row: the ledger is worked out again without it, and nothing else goes.
    client = api()
    cid = add(client)["id"]
    manual(client, cid, BILL, {**BILL, "document_ref": "bt-again", "counterparty": "BT", "document_number": "BT-1"},
           LINE)
    [bill, copy, line] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    after = client.delete(f"/api/clients/{cid}/rows/{bill['id']}")
    assert after.status_code == 200, after.text
    assert [r["id"] for r in after.json()["transactions"]] == [copy["id"], line["id"]]
    assert client.delete(f"/api/clients/{cid}/rows/{bill['id']}").status_code == 404


def test_a_line_added_by_hand_joins_its_document_and_clears_its_total_warning(api):
    client = api()
    cid = add(client)["id"]
    claim = {"date": "2026-09-09", "description": "Jenny Hogg - car park", "direction": "out", "gross": "36.00",
             "account_code": "7400", "document_type": "expense_claim", "counterparty": "Jenny Hogg",
             "document_ref": "claim", "document_total": "90.00"}
    [first] = manual(client, cid, claim)["transactions"]
    assert "total_mismatch" in [i["code"] for i in first["issues"]]
    rows = manual(client, cid, {**claim, "date": "2026-09-24", "gross": "54.00", "document_total": None})["transactions"]
    # (the claim's lines have no receipts, so the £54.00 one says its receipt is still wanted; that is not what this
    # is about)
    assert [[i["code"] for i in r["issues"] if i["code"] != "document_wanted"] for r in rows] == [[], []] and {r["owed"] for r in rows} == {"90.00"}


def test_an_archived_client_takes_no_new_rows(api):
    client = api()
    cid = add(client)["id"]
    client.patch(f"/api/clients/{cid}", json={"archived": True})
    resp = client.post(f"/api/clients/{cid}/uploads", json={"transactions": [BILL]})
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "client_archived")


def test_a_clients_trial_balance_uses_its_vat_setting(api):
    client = api()
    cid = add(client, vat_registered=False)["id"]
    manual(client, cid, {**BILL, "document_type": "receipt", "vat": "12.00"})
    lines = client.get(f"/api/clients/{cid}/years/{YEAR}/trial-balance").json()["lines"]
    assert [(l["code"], l["debit"], l["credit"]) for l in lines] == [("1200", "0.00", "72.00"), ("7502", "72.00", "0.00")]


def test_accounts_can_be_listed_for_a_kind_of_business(api):
    client = api()
    company = {a["code"] for a in client.get("/api/accounts?business_type=limited_company").json()}
    assert "2250" in company and "3260" not in company and "1200" not in company
    assert "1200" in {a["code"] for a in client.get("/api/accounts").json()}   # the whole chart, as before


def test_the_browser_may_send_patch(api):
    preflight = api().options("/api/clients/1", headers={"Origin": "http://localhost:3000",
                                                          "Access-Control-Request-Method": "PATCH"})
    assert "PATCH" in preflight.headers.get("access-control-allow-methods", "")


class GatedModel(FakeModel):
    """Answers only once the test opens the gate, so the test can act while the job is running."""

    def __init__(self, replies, gate):
        super().__init__(replies)
        self.gate = gate

    def chat_json(self, messages, schema, images=None, reasoning_effort=None):
        self.gate.wait(5)
        return super().chat_json(messages, schema, images)


def finish(client, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_analysing_for_a_client_saves_the_rows_as_an_upload(api):
    model = FakeModel([transactions_json(ROW)])
    client = api(model)
    cid = add(client)["id"]
    data = b"Date,Description,Amount\n01/09/2026,BT Business Broadband,-72.00\n"
    resp = client.post("/api/analyze", data={"client_id": str(cid)},
                       files={"file": ("Barclays Sept.csv", data, "text/csv")})
    job = finish(client, resp.json()["job_id"])
    assert (job["status"], job["result"]["client_id"]) == ("succeeded", cid)
    [upload] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"]
    assert (upload["id"], upload["name"], upload["kind"], upload["rows"]) == (
        job["result"]["upload_id"], "Barclays Sept.csv", "table", 1)
    assert upload["sha256"] == hashlib.sha256(data).hexdigest()
    assert "You keep the books of Business Cube Ltd, a UK limited company." in model.calls[0]["messages"][0]["content"]


def test_pasted_text_is_saved_and_the_clients_vat_setting_applies(api):
    client = api(FakeModel([transactions_json(dict(ROW, vat=12.0))]))
    cid = add(client, vat_registered=False)["id"]
    finish(client, client.post("/api/analyze", data={"text": "BT 72.00", "client_id": str(cid)}).json()["job_id"])
    ledger = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()
    assert (ledger["uploads"][0]["name"], ledger["transactions"][0]["vat_posted"]) == ("Pasted text", "0.00")


@pytest.mark.parametrize("reply", [transactions_json(), ModelError("The AI model's answer was not valid JSON.")])
def test_nothing_is_saved_when_a_job_finds_no_rows_or_fails(api, reply):
    client = api(FakeModel([reply]))
    cid = add(client)["id"]
    finish(client, client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"])
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def test_a_post_from_another_web_page_cannot_add_rows(api):
    # Final review #4: a form on any web page could post here unasked and book rows to a client. The LedgerSync
    # pages send X-LedgerSync, which a form can't send.
    model = FakeModel([transactions_json(ROW)])
    client = api(model)
    cid = add(client)["id"]
    del client.headers["X-LedgerSync"]
    resp = client.post("/api/analyze", data={"text": "BT 72.00", "client_id": str(cid)})
    assert (resp.status_code, resp.json()["detail"]["code"]) == (403, "refused_request")
    assert model.calls == [] and client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def test_an_unknown_or_archived_client_is_refused_before_anything_is_queued(api):
    model = FakeModel([transactions_json(ROW)])
    client = api(model)
    assert client.post("/api/analyze", data={"text": "x", "client_id": "99"}).status_code == 404
    cid = add(client)["id"]
    client.patch(f"/api/clients/{cid}", json={"archived": True})
    archived = client.post("/api/analyze", data={"text": "x", "client_id": str(cid)})
    assert (archived.status_code, archived.json()["detail"]["code"]) == (409, "client_archived")
    assert model.calls == []


def test_a_job_that_finishes_after_its_client_was_archived_is_still_saved(api):
    # Review focus: archiving stops new work, not work already running.
    gate = threading.Event()
    client = api(GatedModel([transactions_json(ROW)], gate))
    cid = add(client)["id"]
    job_id = client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"]
    client.patch(f"/api/clients/{cid}", json={"archived": True})
    gate.set()
    assert finish(client, job_id)["status"] == "succeeded"
    assert len(client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]) == 1


def test_a_cancelled_job_saves_nothing(api):
    gate = threading.Event()
    client = api(GatedModel([transactions_json(ROW)], gate))
    cid = add(client)["id"]
    job_id = client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"]
    client.delete(f"/api/jobs/{job_id}")
    gate.set()
    assert finish(client, job_id)["status"] == "cancelled"
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def test_analysing_without_a_client_saves_nothing(api):
    client = api(FakeModel([transactions_json(ROW)]))
    cid = add(client)["id"]
    job = finish(client, client.post("/api/analyze", data={"text": "x"}).json()["job_id"])
    assert "upload_id" not in job["result"]
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def test_the_export_downloads_with_the_clients_name_even_when_archived(api):
    client = api()
    cid = add(client, name="Café/Bar Ltd")["id"]
    client.patch(f"/api/clients/{cid}", json={"archived": True})
    resp = client.get(f"/api/clients/{cid}/years/{YEAR}/export.xlsx")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    disposition = resp.headers["content-disposition"]
    assert "filename*=UTF-8''Caf%C3%A9%20Bar%20Ltd%20" in disposition and 'filename="Caf_ Bar Ltd ' in disposition


def test_a_statements_balances_reach_the_saved_rows_and_are_checked(api):
    reply = json.dumps({"transactions": [dict(ROW, document_type="statement", balance=928.0)],
                        "opening_balance": 1000.0, "closing_balance": 928.0})
    client = api(FakeModel([reply]))
    cid = add(client)["id"]
    finish(client, client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"])
    [upload] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"]
    assert upload["statement"] == {"status": "ok", "difference": None}


def test_a_cancel_that_arrives_after_the_rows_were_saved_leaves_the_job_succeeded(api, monkeypatch):
    # Final review #2: the job was marked cancelled after its rows were saved, so Retry booked them twice.
    saving, release = threading.Event(), threading.Event()
    real_add = MongoStore.add_upload

    def slow_add(self, *args, **kwargs):
        upload_id = real_add(self, *args, **kwargs)
        saving.set()
        release.wait(5)
        return upload_id

    monkeypatch.setattr(MongoStore, "add_upload", slow_add)
    client = api(FakeModel([transactions_json(ROW)]))
    cid = add(client)["id"]
    job_id = client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"]
    assert saving.wait(5)
    client.delete(f"/api/jobs/{job_id}")
    release.set()
    assert finish(client, job_id)["status"] == "succeeded"
    assert len(client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"]) == 1


BT_CSV = b"Date,Description,Amount\n01/09/2026,BT Business Broadband,-72.00\n"


def test_an_analysed_file_can_be_downloaded_again(mongo_store):
    app = create_app(Settings(warmup=False), model_client=FakeModel([transactions_json(ROW)]),
                     store=mongo_store, blobs=MemoryBlobStore())
    with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
        cid = add(api)["id"]
        resp = api.post("/api/analyze", data={"client_id": str(cid)}, files={"file": ("bt.csv", BT_CSV, "text/csv")})
        upload_id = finish(api, resp.json()["job_id"])["result"]["upload_id"]
        resp = api.get(f"/api/clients/{cid}/uploads/{upload_id}/file")
        assert resp.status_code == 200 and resp.content == BT_CSV
        assert 'filename="bt.csv"' in resp.headers["content-disposition"]
        assert resp.headers["content-type"].startswith("text/csv")


@pytest.mark.parametrize("name, content_type, shown", [
    ("r.pdf", "application/pdf", True), ("r.png", "image/png", True), ("r.jpg", "image/jpeg; charset=binary", True),
    ("r.svg", "image/svg+xml", False), ("r.html", "text/html", False), ("r.csv", "text/csv", False),
])
def test_only_a_pdf_or_an_image_is_sent_for_showing(mongo_store, name, content_type, shown):
    blobs = MemoryBlobStore()
    app = create_app(Settings(warmup=False), model_client=FakeModel([transactions_json(ROW)]), store=mongo_store, blobs=blobs)
    with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
        cid = add(api)["id"]
        resp = api.post("/api/analyze", data={"client_id": str(cid)}, files={"file": ("bt.csv", BT_CSV, "text/csv")})
        upload_id = finish(api, resp.json()["job_id"])["result"]["upload_id"]
        sha = blobs.put(b"the file", name=name, content_type=content_type)
        mongo_store.db.clients.update_one({"id": cid, "uploads.id": upload_id}, {"$set": {"uploads.$.sha256": sha}})
        file = f"/api/clients/{cid}/uploads/{upload_id}/file"

        asked = api.get(f"{file}?show=1")

        assert asked.status_code == 200 and asked.content == b"the file"
        assert asked.headers["content-disposition"].startswith("inline" if shown else "attachment")
        assert asked.headers["x-content-type-options"] == "nosniff"
        assert api.get(file).headers["content-disposition"].startswith("attachment")


def test_pasted_text_has_no_file_to_download(api):
    client = api(FakeModel([transactions_json(ROW)]))
    cid = add(client)["id"]
    job = finish(client, client.post("/api/analyze", data={"text": "BT 72.00", "client_id": str(cid)}).json()["job_id"])
    resp = client.get(f"/api/clients/{cid}/uploads/{job['result']['upload_id']}/file")
    assert resp.status_code == 404 and resp.json()["detail"]["message"] == "The original file wasn't kept for this upload."


# ─── Bank accounts and credit cards ──────────────────────────────────────────

TWO_ACCOUNTS = [{"code": "1200", "name": "Barclays current", "kind": "current"},
                {"name": "Amex card", "kind": "credit_card"}]
STATEMENT_LINE = json.dumps({"transactions": [dict(ROW, document_type="statement")]})


def client_with_two_accounts(client) -> int:
    return add(client, bank_accounts=TWO_ACCOUNTS)["id"]


def test_a_client_is_saved_with_its_bank_accounts_and_cards(api):
    client = api()
    added = add(client, bank_accounts=TWO_ACCOUNTS)
    assert [(a["code"], a["name"], a["kind"]) for a in added["bank_accounts"]] == [
        ("1200", "Barclays current", "current"), ("1240", "Amex card", "credit_card")]
    assert add(client, name="Second Cube Ltd")["bank_accounts"] == [{"code": "1200", "name": "Bank current account", "kind": "current"}]
    codes = {a["code"] for a in client.get(f"/api/accounts?client_id={added['id']}").json()}
    assert {"1200", "1240"} <= codes and "1241" not in codes


def test_a_one_account_client_is_offered_the_accounts_it_was_before(api):
    client = api()
    codes = {a["code"] for a in client.get(f"/api/accounts?client_id={add(client)['id']}").json()}
    assert "1210" in codes and "1200" not in codes


def test_a_statement_for_a_client_with_two_accounts_must_say_which(api):
    # the fake model answers with one bank statement line
    client = api(FakeModel([STATEMENT_LINE]))
    cid = client_with_two_accounts(client)
    job = client.post("/api/analyze", data={"client_id": str(cid), "text": "Bank lines"}).json()
    failed = finish(client, job["job_id"])
    assert failed["status"] == "failed" and "Choose which bank account" in failed["error"]["message"]
    assert failed["error"]["message"] == "Choose which bank account this statement is for."
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def test_a_statement_sent_with_its_account_is_saved_on_it_and_can_be_moved(api):
    model = FakeModel([STATEMENT_LINE])
    client = api(model)
    cid = client_with_two_accounts(client)
    job = client.post("/api/analyze", data={"client_id": str(cid), "text": "Amex lines", "bank_account": "1240"}).json()
    assert finish(client, job["job_id"])["status"] == "succeeded"
    ledger = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()
    [upload], [line] = ledger["uploads"], ledger["transactions"]
    assert (upload["bank_account"], line["bank_account"], line["contra_account_code"]) == ("1240", "1240", "1240")
    assert "1200 Bank Current Account" in model.calls[0]["messages"][0]["content"]   # paying the card off
    moved = client.patch(f"/api/clients/{cid}/uploads/{upload['id']}", json={"bank_account": "1200"}).json()
    assert (moved["uploads"][0]["bank_account"], moved["transactions"][0]["contra_account_code"]) == ("1200", "1200")


def test_a_card_statement_read_on_the_bank_account_is_put_right_when_it_is_moved_to_the_card(api):
    paid = {"description": "PAYMENT RECEIVED - THANK YOU", "date": "2026-09-06", "amount": 850.0, "direction": "in",
            "account": "4000 Sales", "vat": None, "currency": "GBP", "document_type": "statement",
            "counterparty": "PAYMENT RECEIVED - THANK YOU"}
    client = api(FakeModel([json.dumps({"transactions": [paid]})]))
    cid = client_with_two_accounts(client)
    job = client.post("/api/analyze", data={"client_id": str(cid), "text": "Amex lines", "bank_account": "1200"}).json()
    assert finish(client, job["job_id"])["status"] == "succeeded"
    ledger = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()
    assert ledger["transactions"][0]["account_code"] == "4000"
    moved = client.patch(f"/api/clients/{cid}/uploads/{ledger['uploads'][0]['id']}", json={"bank_account": "1240"}).json()
    [line] = moved["transactions"]
    assert (line["bank_account"], line["account_code"], line["issues"]) == ("1240", "1200", [])


def test_a_bank_account_the_client_does_not_have_is_refused(api):
    client = api(FakeModel([STATEMENT_LINE]))
    cid = client_with_two_accounts(client)
    resp = client.post("/api/analyze", data={"client_id": str(cid), "text": "x", "bank_account": "1210"})
    assert (resp.status_code, resp.json()["detail"]["message"]) == (
        422, "Choose one of Business Cube Ltd's bank accounts.")


def test_a_client_with_one_account_has_its_statements_put_on_it(api):
    client = api(FakeModel([STATEMENT_LINE]))
    cid = add(client)["id"]
    finish(client, client.post("/api/analyze", data={"client_id": str(cid), "text": "x"}).json()["job_id"])
    [line] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    assert (line["bank_account"], line["contra_account_code"]) == ("1200", "1200")


# ─── Years and opening balances ──────────────────────────────────────────────

def test_a_client_needs_its_first_year_end(api):
    resp = api().post("/api/clients", json={**CUBE, "first_year_end": ""})
    assert (resp.status_code, resp.json()["detail"]["message"]) == (422, "Enter the client's first year end.")


def test_a_clients_years_and_a_years_ledger_and_trial_balance(api):
    client = api()
    cid = add(client, first_year_end="2026-03-31")["id"]
    manual(client, cid, {**BILL, "document_type": "receipt"})
    years = client.get(f"/api/clients/{cid}/years").json()
    assert [(y["start"], y["end"], y["label"], y["closed"]) for y in years][:2] == [
        ("2025-04-01", "2026-03-31", "Year to 31 Mar 2026", False),
        ("2026-04-01", "2027-03-31", "Year to 31 Mar 2027", False)]
    first = client.get(f"/api/clients/{cid}/years/2025-04-01/ledger").json()
    second = client.get(f"/api/clients/{cid}/years/2026-04-01/ledger").json()
    assert (first["transactions"], len(second["transactions"])) == ([], 1)
    assert second["year"]["label"] == "Year to 31 Mar 2027"
    tb = client.get(f"/api/clients/{cid}/years/2026-04-01/trial-balance").json()
    assert (tb["opening"], tb["is_balanced"]) == ([], True)
    assert client.get(f"/api/clients/{cid}/years/2026-04-01/export.xlsx").status_code == 200


@pytest.mark.parametrize("path", ["ledger", "trial-balance", "export.xlsx"])
def test_a_year_the_client_does_not_have_is_not_found(api, path):
    client = api()
    cid = add(client)["id"]
    resp = client.get(f"/api/clients/{cid}/years/2026-04-02/{path}")
    assert (resp.status_code, resp.json()["detail"]["message"]) == (404, "That year was not found.")


def test_opening_balances_are_saved_and_read_back(api):
    client = api()
    cid = add(client)["id"]
    assert client.get(f"/api/clients/{cid}/opening-balances").json() == {"lines": [], "unpaid": []}
    opening = {"lines": [{"code": "1100", "debit": "200.00", "credit": "0.00"},
                         {"code": "3200", "debit": "0.00", "credit": "200.00"}],
               "unpaid": [{"id": "1", "direction": "in", "counterparty": "Bright Cafe", "amount": "200.00",
                           "number": "INV-7", "date": None}]}
    saved = client.put(f"/api/clients/{cid}/opening-balances", json=opening)
    assert (saved.status_code, saved.json()) == (200, opening)
    tb = client.get(f"/api/clients/{cid}/years/{YEAR}/trial-balance").json()
    assert [(l["code"], l["debit"], l["credit"]) for l in tb["opening"]] == [("1100", "200.00", "0.00"),
                                                                             ("3200", "0.00", "200.00")]
    refused = client.put(f"/api/clients/{cid}/opening-balances", json={"lines": [opening["lines"][0]]})
    assert (refused.status_code, refused.json()["detail"]["message"]) == (
        422, "Opening debits £200.00 and credits £0.00 must be the same.")


def test_the_browser_may_send_put(api):
    preflight = api().options("/api/clients/1/opening-balances", headers={"Origin": "http://localhost:3000",
                                                                          "Access-Control-Request-Method": "PUT"})
    assert "PUT" in preflight.headers.get("access-control-allow-methods", "")


def test_an_analysis_is_added_to_the_year_picked(api):
    client = api(FakeModel([transactions_json(dict(ROW, date=None))]))
    cid = add(client, first_year_end="2026-03-31")["id"]
    refused = client.post("/api/analyze", data={"text": "x", "client_id": str(cid), "year_start": "2025-04-02"})
    assert (refused.status_code, refused.json()["detail"]["message"]) == (404, "That year was not found.")
    job = client.post("/api/analyze", data={"text": "x", "client_id": str(cid), "year_start": "2025-04-01"}).json()
    assert finish(client, job["job_id"])["status"] == "succeeded"
    first = client.get(f"/api/clients/{cid}/years/2025-04-01/ledger").json()
    assert first["uploads"][0]["year_start"] == "2025-04-01" and len(first["transactions"]) == 1
    assert client.get(f"/api/clients/{cid}/years/2026-04-01/ledger").json()["transactions"] == []


def test_a_year_is_closed_and_reopened(api):
    client = api()
    cid = add(client)["id"]
    manual(client, cid, BILL)
    closed = client.post(f"/api/clients/{cid}/years/{YEAR}/close")
    assert closed.status_code == 200
    [saved] = closed.json()["closed_years"]
    assert (saved["start"], saved["end"], saved["closing"]) == (YEAR, "2027-03-31",
                                                                {"2100": "-72.00", "7502": "72.00"})
    assert [y["closed"] for y in client.get(f"/api/clients/{cid}/years").json()] == [True]
    refused = client.post(f"/api/clients/{cid}/uploads", json={"transactions": [LINE]})
    assert (refused.status_code, refused.json()["detail"]) == (409, {
        "code": "year_closed", "message": "The year to 31 Mar 2027 is closed. Reopen it to change it."})
    moved = client.patch(f"/api/clients/{cid}", json={"first_year_end": "2027-12-31"})
    assert (moved.status_code, moved.json()["detail"]["message"]) == (
        422, "The year end can't change once a year is closed.")
    reopened = client.post(f"/api/clients/{cid}/years/{YEAR}/reopen")
    assert (reopened.status_code, reopened.json()["closed_years"]) == (200, [])
    assert client.post(f"/api/clients/{cid}/uploads", json={"transactions": [LINE]}).status_code == 201


def test_an_analysis_isnt_saved_into_a_closed_year(api):
    client = api(FakeModel([transactions_json(ROW)]))
    cid = add(client)["id"]
    client.post(f"/api/clients/{cid}/years/{YEAR}/close")
    job = finish(client, client.post("/api/analyze", data={"text": "x", "client_id": str(cid)}).json()["job_id"])
    assert (job["status"], job["error"]["code"]) == ("failed", "year_closed")
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"] == []


def upload_file(client, cid, data=BT_CSV, name="bt.csv"):
    return client.post("/api/analyze", data={"client_id": str(cid), "year_start": YEAR},
                       files={"file": (name, data, "text/csv")})


def test_a_file_already_saved_for_the_client_is_refused_whatever_its_name(api):
    client = api(FakeModel([transactions_json(ROW)]))
    cid = add(client)["id"]
    assert finish(client, upload_file(client, cid).json()["job_id"])["status"] == "succeeded"
    resp = upload_file(client, cid, name="bt (copy).csv")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "same_file"
    assert "bt.csv" in resp.json()["detail"]["message"]
    assert len(client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["uploads"]) == 1


def test_a_file_still_being_read_for_the_client_is_refused(api):
    gate = threading.Event()
    client = api(GatedModel([transactions_json(ROW)], gate))
    cid = add(client)["id"]
    try:
        first = upload_file(client, cid).json()
        resp = upload_file(client, cid, name="again.csv")
        assert resp.status_code == 409 and "still being read" in resp.json()["detail"]["message"]
    finally:
        gate.set()
    assert finish(client, first["job_id"])["status"] == "succeeded"


def test_the_files_being_read_for_a_client_are_listed_until_they_are_saved(api):
    gate = threading.Event()
    client = api(GatedModel([transactions_json(ROW)], gate))
    cid = add(client)["id"]
    try:
        job_id = upload_file(client, cid).json()["job_id"]
        [reading] = client.get(f"/api/clients/{cid}/reading").json()
        assert (reading["job_id"], reading["name"], reading["year_start"]) == (job_id, "bt.csv", YEAR)
        assert reading["status"] in ("queued", "running")
    finally:
        gate.set()
    finish(client, job_id)
    assert client.get(f"/api/clients/{cid}/reading").json() == []


def test_a_receipt_the_statement_does_not_show_is_parked_until_a_person_says_who_paid(api):
    client = api()
    cid = add(client)["id"]
    line = {**LINE, "counterparty": "NATWEST", "description": "Charges", "account_code": "7901", "gross": "14.50"}
    tv = {"direction": "out", "gross": "499.00", "account_code": "0030", "date": "2026-05-16", "description": "TV",
          "document_type": "receipt", "counterparty": "Currys", "document_ref": "tv"}
    manual(client, cid, {**line, "date": "2026-05-11", "document_ref": "a"},
           {**line, "date": "2026-05-22", "document_ref": "b"}, tv)
    rows = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    parked = next(r for r in rows if r["document_type"] == "receipt")
    # Off the bank, in Suspense, until someone says who paid. The receipt shows no VAT, so it is the record of the
    # cost and no VAT invoice is waited for: it only notes that none is reclaimed.
    assert parked["contra_account_code"] == "9998"
    # (No sales are booked, so its materiality isn't set: whether a £499 TV is kept as an asset waits for it.)
    assert sorted(i["code"] for i in parked["issues"] if i["code"] != "left_unset") == ["not_on_statement",
                                                                                         "vat_unclaimed"]
    bank = next(c for c in client.get(f"/api/clients/{cid}/years/{YEAR}/bank").json() if c["code"] == "1200")
    assert bank["books"] == "-29.00"           # only the two bank lines: the receipt is not on the bank

    refused = client.patch(f"/api/clients/{cid}/rows/{parked['id']}", json={"bank_account": "7400"})
    assert (refused.status_code, refused.json()["detail"]["message"]) == (
        422, "Choose one of Business Cube Ltd's bank accounts, or who paid it themselves.")
    on_a_line = client.patch(f"/api/clients/{cid}/rows/{rows[0]['id']}", json={"bank_account": "2250"})
    assert on_a_line.status_code == 422 and on_a_line.json()["detail"]["message"].startswith("Only a receipt says")

    said = client.patch(f"/api/clients/{cid}/rows/{parked['id']}", json={"bank_account": "2250"}).json()
    paid = next(r for r in said["transactions"] if r["id"] == parked["id"])
    assert paid["contra_account_code"] == "2250" and "not_on_statement" not in [i["code"] for i in paid["issues"]]


def test_a_request_reads_the_client_once_however_many_figures_it_works_out(api, monkeypatch):
    # Each read is a round trip to the database, which may be far away: the posted trial balance made twelve.
    from pymongo.collection import Collection
    client = api()
    cid = add(client)["id"]
    manual(client, cid, {**LINE, "date": "2026-05-11"})
    assert client.get(f"/api/clients/{cid}/years/{YEAR}/posted-trial-balance").status_code == 200   # settled by now
    reads = []
    for name in ("find", "aggregate"):
        real = getattr(Collection, name)
        monkeypatch.setattr(Collection, name, lambda self, *a, _real=real, **k: (
            reads.append(self.name) if self.name == "clients" else None) or _real(self, *a, **k))
    for route in ("posted-trial-balance", "vat", "suggestions", "ledger"):
        reads.clear()
        assert client.get(f"/api/clients/{cid}/years/{YEAR}/{route}").status_code == 200
        assert reads == ["clients"], route


def test_a_change_made_in_a_request_is_in_what_the_request_answers(api):
    # The request reads the client once, and reads it again after its own change.
    client = api()
    cid = add(client)["id"]
    [row] = manual(client, cid, {**LINE, "date": "2026-05-11"})["transactions"]
    changed = client.patch(f"/api/clients/{cid}/rows/{row['id']}", json={"description": "Line rental"}).json()
    assert [r["description"] for r in changed["transactions"]] == ["Line rental"]
    assert client.patch(f"/api/clients/{cid}", json={"contact_name": "Sam Lee"}).json()["contact_name"] == "Sam Lee"


# ─── Remove sets a read row aside; Put back ────────────────────────────────────

def read_claim(store, cid, *lines, total="90.00"):
    """A claim read from a file (not typed in): its lines, each printing the claim's total."""
    from ledgersync.models import Transaction
    store.add_upload(cid, "claim.pdf", "pdf", [Transaction(
        date="2026-09-09", description=f"Jenny Hogg - {gross}", direction="out", gross=gross, account_code="7400",
        document_type="expense_claim", counterparty="Jenny Hogg", document_ref="claim", document_total=total)
        for gross in lines])


def codes_of(ledger):
    return [[i["code"] for i in r["issues"]] for r in ledger["transactions"]]


def test_removing_a_read_line_sets_it_aside_and_its_claim_still_adds_up(api, mongo_store):
    # A person removed a claim's line on purpose: the claim said "£54.00 missing: add the line" on its first line.
    client = api()
    cid = add(client)["id"]
    read_claim(mongo_store, cid, "36.00", "54.00")
    [first, second] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    after = client.delete(f"/api/clients/{cid}/rows/{second['id']}")
    assert after.status_code == 200, after.text
    [kept, removed] = after.json()["transactions"]
    assert (removed["id"], removed["excluded"], removed["removed"]) == (second["id"], True, True)
    assert not kept["removed"] and "total_mismatch" not in sum(codes_of(after.json()), [])


def test_put_back_books_a_removed_line_again(api, mongo_store):
    client = api()
    cid = add(client)["id"]
    read_claim(mongo_store, cid, "36.00", "54.00")
    second = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"][1]
    client.delete(f"/api/clients/{cid}/rows/{second['id']}")
    back = client.patch(f"/api/clients/{cid}/rows/{second['id']}", json={"removed": False})
    assert back.status_code == 200, back.text
    row = back.json()["transactions"][1]
    assert (row["excluded"], row["removed"]) == (False, False)
    assert "total_mismatch" not in sum(codes_of(back.json()), [])


def test_a_row_added_by_hand_is_still_deleted(api):
    client = api()
    cid = add(client)["id"]
    [row] = manual(client, cid, BILL)["transactions"]
    assert client.delete(f"/api/clients/{cid}/rows/{row['id']}").json()["transactions"] == []


def test_put_back_is_refused_on_a_row_that_was_not_removed(api, mongo_store):
    client = api()
    cid = add(client)["id"]
    read_claim(mongo_store, cid, "90.00")
    [row] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    refused = client.patch(f"/api/clients/{cid}/rows/{row['id']}", json={"removed": False})
    assert refused.status_code == 422 and "was not removed" in refused.text


def test_removed_true_is_refused(api, mongo_store):
    client = api()
    cid = add(client)["id"]
    read_claim(mongo_store, cid, "90.00")
    [row] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    refused = client.patch(f"/api/clients/{cid}/rows/{row['id']}", json={"removed": True})
    assert refused.status_code == 422 and "Use Remove to take a row out of the books." in refused.text
    assert mongo_store.rows(cid)[0].tx.excluded is False


def test_put_back_is_refused_for_an_archived_client(api, mongo_store):
    client = api()
    cid = add(client)["id"]
    read_claim(mongo_store, cid, "36.00", "54.00")
    second = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"][1]
    client.delete(f"/api/clients/{cid}/rows/{second['id']}")
    client.patch(f"/api/clients/{cid}", json={"archived": True})
    refused = client.patch(f"/api/clients/{cid}/rows/{second['id']}", json={"removed": False})
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "client_archived")


def test_a_removed_statement_line_raises_nothing_new(api, mongo_store):
    # Review focus: a bank line a person removes is treated as one a decision left out, no worse.
    from ledgersync.models import Transaction
    client = api()
    cid = add(client)["id"]
    mongo_store.add_upload(cid, "bank.csv", "csv", [Transaction(
        date=f"2026-09-0{n}", description=f"line {n}", direction="out", gross="10.00", account_code="7502",
        document_type="statement", document_ref=f"l{n}", balance=str(100 - 10 * n)) for n in (1, 2, 3)])
    middle = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"][1]["id"]
    removed = codes_of(client.delete(f"/api/clients/{cid}/rows/{middle}").json())
    mongo_store.patch_row(cid, middle, {"removed": False})   # as a decision leaves it: excluded only
    left_out = codes_of(client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json())
    assert removed == left_out and len(removed) == 3


# ─── Leave it as it is ─────────────────────────────────────────────────────────

def test_leave_it_as_it_is_clears_a_total_and_undo_brings_it_back(api):
    # A total that is out on purpose (a line deleted long ago, a total printed wrong) had no way out but adding a line.
    client = api()
    cid = add(client)["id"]
    claim = {"date": "2026-09-09", "description": "Jenny Hogg - car park", "direction": "out", "gross": "36.00",
             "account_code": "7400", "document_type": "expense_claim", "counterparty": "Jenny Hogg",
             "document_ref": "claim", "document_total": "90.00"}
    manual(client, cid, claim)
    [first, second] = manual(client, cid, {**claim, "gross": "10.00", "document_total": None})["transactions"]
    [short] = [i for i in first["issues"] if i["code"] == "total_mismatch"]
    assert (short["about"], short["difference"]) == ("document", "44.00")
    left = client.patch(f"/api/clients/{cid}/rows/{second['id']}", json={"total_accepted": short["difference"]})
    assert left.status_code == 200, left.text
    codes = [[i["code"] for i in r["issues"] if i["code"].startswith("total_")] for r in left.json()["transactions"]]
    assert codes == [["total_accepted"], []]
    assert {r["total_accepted"] for r in left.json()["transactions"]} == {"44.00"}   # kept on the whole document
    undone = client.patch(f"/api/clients/{cid}/rows/{first['id']}", json={"total_accepted": None})
    assert [i["code"] for i in undone.json()["transactions"][0]["issues"] if i["code"].startswith("total_")] == ["total_mismatch"]
    assert {r["total_accepted"] for r in undone.json()["transactions"]} == {None}


def test_a_zero_difference_is_refused(api):
    client = api()
    cid = add(client)["id"]
    [row] = manual(client, cid, BILL)["transactions"]
    refused = client.patch(f"/api/clients/{cid}/rows/{row['id']}", json={"total_accepted": "0.00"})
    assert refused.status_code == 422 and "There is no difference to leave." in refused.text


def test_a_firm_sets_a_clients_materiality_and_can_clear_it(api):
    client = api()
    made = add(client)
    assert made["materiality"] is None
    changed = client.patch(f"/api/clients/{made['id']}", json={"materiality": "2000"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["materiality"] == "2000"
    year = client.get(f"/api/clients/{made['id']}/years").json()[0]["start"]
    levels = client.get(f"/api/clients/{made['id']}/years/{year}/materiality").json()
    assert (levels["benchmark"], levels["overall"]) == ("firm", "2000.00")
    cleared = client.patch(f"/api/clients/{made['id']}", json={"materiality": None})
    assert cleared.json()["materiality"] is None


def test_a_card_export_uploaded_for_the_card_books_its_spending_as_money_out(api):
    # Amex exports spending as a positive amount: read in code, it must be money out on the card.
    coded = json.dumps({"lines": [{"n": 1, "account": "7502", "counterparty": "Streamflix", "alternatives": [],
                                   "bought": None, "people": None}]})
    client = api(FakeModel([coded]))
    cid = client_with_two_accounts(client)
    data = b"Date,Description,Amount\n09/09/2026,STREAMFLIX.COM,10.99\n"
    resp = client.post("/api/analyze", data={"client_id": str(cid), "bank_account": "1240"},
                       files={"file": ("amex.csv", data, "text/csv")})
    assert finish(client, resp.json()["job_id"])["status"] == "succeeded"
    [line] = client.get(f"/api/clients/{cid}/years/{YEAR}/ledger").json()["transactions"]
    assert (line["direction"], line["gross"], line["contra_account_code"]) == ("out", "10.99", "1240")


def test_a_firm_sets_a_clients_capitalisation_threshold_and_it_books_small_equipment_as_a_cost(api):
    model = FakeModel([transactions_json(dict(ROW, description="Cabot Office Supplies, 27-inch monitor", amount=420.0,
                                              vat=None, account="0030", document_type="invoice"))])   # under £500
    client = api(model)
    made = add(client)
    assert made["capitalise_from"] is None
    assert client.patch(f"/api/clients/{made['id']}", json={"capitalise_from": "500"}).json()["capitalise_from"] == "500"
    job = client.post("/api/analyze", data={"client_id": str(made["id"]), "text": "Monitor invoice"}).json()
    assert finish(client, job["job_id"])["status"] == "succeeded"
    [line] = client.get(f"/api/clients/{made['id']}/years/{YEAR}/ledger").json()["transactions"]
    assert line["account_code"] == "7504"
    assert client.patch(f"/api/clients/{made['id']}", json={"capitalise_from": None}).json()["capitalise_from"] is None


def test_a_firm_says_what_the_business_does_and_the_client_keeps_it(api):
    client = api(FakeModel([]))
    made = add(client)
    assert (made["nature_of_business"], made["sic_code"]) == ("", "")
    changed = client.patch(f"/api/clients/{made['id']}",
                           json={"nature_of_business": "  Film and TV production ", "sic_code": " 59111 "}).json()
    assert (changed["nature_of_business"], changed["sic_code"]) == ("Film and TV production", "59111")
    again = client.get(f"/api/clients/{made['id']}").json()
    assert (again["nature_of_business"], again["sic_code"]) == ("Film and TV production", "59111")
