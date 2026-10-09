import json
import threading
import time

import pymupdf
import pytest
from fakes import ROW, FakeModel, FakeUrlopen, http_error, transactions_json
from fastapi.testclient import TestClient

from ledgersync.config import Settings
from ledgersync.errors import ModelTimeout, ModelUnavailable
from ledgersync.model_client import ModelClient
from server import create_app


@pytest.fixture
def make_client():
    clients = []

    def _make(model=None):
        settings = Settings(warmup=False, max_upload_mb=1, max_pdf_pages=3)
        app = create_app(settings, model_client=model or FakeModel([transactions_json(ROW)]))
        client = TestClient(app, headers={"X-LedgerSync": "1"})   # as the LedgerSync pages send
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def wait_for(client, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish in time")


def run_text_job(client, text="BT Broadband 72.00"):
    resp = client.post("/api/analyze", data={"text": text})
    assert resp.status_code == 202, resp.text
    return wait_for(client, resp.json()["job_id"])


def test_health_reports_model_status(make_client):
    body = make_client().get("/api/health").json()
    assert body["model"] == "fake-model" and body["model_available"] is True
    assert {"ai_reachable", "ai_error"} <= set(body)


def test_health_reports_upload_limit_for_the_ui(make_client):
    # The UI must refuse bigger files itself: the Next proxy truncates large bodies instead of failing.
    assert make_client().get("/api/health").json()["max_upload_mb"] == 1


def test_health_when_ai_offline_still_answers(make_client):
    body = make_client(FakeModel(healthy=False)).get("/api/health").json()
    assert body["ai_reachable"] is False and "Cannot reach Groq" in body["ai_error"]


def test_analyze_text_runs_as_job(make_client):
    job = run_text_job(make_client())
    assert job["status"] == "succeeded" and job["result"]["model"] == "fake-model"
    [t] = job["result"]["transactions"]
    assert (t["direction"], t["gross"], t["account_code"], t["account_name"]) == (
        "out", "72.00", "7502", "Telephone and Internet")


def test_analyze_when_ai_offline_is_503_with_advice(make_client):
    resp = make_client(FakeModel(healthy=False)).post("/api/analyze", data={"text": "BT 72.00"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "ai_offline" and "Cannot reach Groq" in resp.json()["detail"]["message"]


def test_model_timeout_fails_the_job_with_504_code(make_client):
    job = run_text_job(make_client(FakeModel([ModelTimeout("Groq did not answer within 60 seconds.")])))
    assert job["status"] == "failed"
    assert (job["error"]["code"], job["error"]["status_code"]) == ("ai_timeout", 504)


def test_ai_dies_mid_job_fails_clearly(make_client):
    job = run_text_job(make_client(FakeModel([ModelUnavailable("Lost the connection to Groq.")])))
    assert job["status"] == "failed" and job["error"]["code"] == "ai_offline"


def test_partial_success_returns_valid_rows_and_warnings(make_client):
    job = run_text_job(make_client(FakeModel([transactions_json(dict(ROW, direction="sideways"), ROW)])))
    assert len(job["result"]["transactions"]) == 1 and len(job["result"]["warnings"]) == 1


def test_upload_over_limit_is_413(make_client):
    resp = make_client().post("/api/analyze", files={"file": ("big.csv", b"a,b\n" * 300_000, "text/csv")})
    assert resp.status_code == 413 and resp.json()["detail"]["code"] == "file_too_large"


def test_unsupported_file_is_415(make_client):
    resp = make_client().post("/api/analyze", files={"file": ("notes.docx", b"PK\x03\x04" + b"\x00" * 50, "application/octet-stream")})
    assert resp.status_code == 415


def test_corrupt_xls_is_422_and_never_reaches_the_model(make_client):
    model = FakeModel([])
    resp = make_client(model).post("/api/analyze", files={"file": ("s.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "application/vnd.ms-excel")})
    assert resp.status_code == 422 and model.calls == []


def test_password_protected_pdf_is_422(make_client):
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    resp = make_client().post("/api/analyze", files={"file": ("s.pdf", data, "application/pdf")})
    assert resp.status_code == 422 and "password" in resp.json()["detail"]["message"]


def test_missing_input_is_422(make_client):
    resp = make_client().post("/api/analyze", data={})
    assert resp.status_code == 422


def test_cancel_running_job_via_api(make_client):
    class BlockingModel(FakeModel):
        def __init__(self):
            super().__init__()
            self.entered, self.release = threading.Event(), threading.Event()

        def chat_json(self, messages, schema, images=None):
            self.entered.set()
            self.release.wait(5)
            return transactions_json(ROW)

    model = BlockingModel()
    client = make_client(model)
    job_id = client.post("/api/analyze", data={"text": "x"}).json()["job_id"]
    assert model.entered.wait(5)
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    model.release.set()
    job = wait_for(client, job_id)
    assert job["status"] == "cancelled" and job["result"] is None


def test_unknown_job_is_404_with_retry_advice(make_client):
    resp = make_client().get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "job_not_found" and "run it again" in resp.json()["detail"]["message"]


BT = {"direction": "out", "gross": "72.00", "account_code": "7502", "date": "2026-09-01", "description": "BT"}


def test_accounts_are_listed(make_client):
    accounts = make_client().get("/api/accounts").json()
    assert {"code": "7502", "name": "Telephone and Internet", "type": "expense", "vat": "standard"} in accounts


def test_validate_books_no_vat_when_the_document_shows_none(make_client):
    [t] = make_client().post("/api/transactions/validate", json={"transactions": [BT]}).json()["transactions"]
    assert (t["vat"], t["vat_posted"], t["net"], t["contra_account_code"]) == (None, "0.00", "72.00", "1200")
    assert t["issues"] == []


def test_validate_splits_vat_at_a_rate_a_person_chose(make_client):
    row = {**BT, "vat_treatment": "standard"}
    [t] = make_client().post("/api/transactions/validate", json={"transactions": [row]}).json()["transactions"]
    assert (t["vat_posted"], t["net"]) == ("12.00", "60.00")
    assert [i["code"] for i in t["issues"]] == ["vat_estimated"]



def test_absurd_amounts_get_a_422_not_a_server_error(make_client):
    resp = make_client().post("/api/transactions/validate", json={"transactions": [{**BT, "gross": 1e26}]})
    assert resp.status_code == 422

def test_trial_balance_balances_with_bank_and_vat_legs(make_client):
    sale = {**BT, "direction": "in", "gross": "240.00", "account_code": "4000", "vat": "40.00"}
    tb = make_client().post("/api/trial-balance", json={"transactions": [{**BT, "vat": "12.00"}, sale]}).json()
    assert tb["is_balanced"] is True and tb["total_debits"] == tb["total_credits"] == "240.00"
    assert [(l["code"], l["debit"], l["credit"]) for l in tb["lines"]] == [
        ("1200", "168.00", "0.00"), ("4000", "0.00", "200.00"), ("7502", "60.00", "0.00"),
        ("2200", "0.00", "40.00"), ("2201", "12.00", "0.00")]


def test_trial_balance_rejects_unpostable_rows_with_422(make_client):
    resp = make_client().post("/api/trial-balance", json={"transactions": [BT, {**BT, "account_code": "9999"}]})
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "transactions_need_fixing"
    assert "#2" in resp.json()["detail"]["message"]


def test_non_vat_registered_business_gets_gross_postings(make_client):
    tb = make_client().post("/api/trial-balance",
                            json={"transactions": [BT], "settings": {"vat_registered": False}}).json()
    assert [(l["code"], l["debit"], l["credit"]) for l in tb["lines"]] == [
        ("1200", "0.00", "72.00"), ("7502", "72.00", "0.00")]


def test_source_code_and_git_are_not_served(make_client):
    client = make_client()
    for path in ("/server.py", "/ledgersync/extractor.py", "/.git/config", "/requirements.txt", "/.venv/pyvenv.cfg"):
        assert client.get(path).status_code == 404, path


def test_the_api_serves_no_web_pages(make_client):
    # The retired HTML page is gone; the UI is the Next.js app.
    assert make_client().get("/").status_code == 404


def test_cors_allows_only_the_frontend(make_client):
    client = make_client()
    preflight = {"Access-Control-Request-Method": "GET"}
    ok = client.options("/api/health", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/api/health", headers={"Origin": "http://evil.example", **preflight})
    assert "access-control-allow-origin" not in bad.headers


def test_health_never_shows_the_api_key(make_client):
    # Pins the rule at the API boundary: health passes on the client's error, which never holds the key.
    groq = ModelClient(Settings(groq_api_key="gsk-secret"), opener=FakeUrlopen(http_error(401, "Invalid API Key gsk-secret")))
    body = make_client(groq).get("/api/health").text
    assert "gsk-secret" not in body and "rejected the API key" in body


def test_the_business_name_setting_reaches_the_model():
    model = FakeModel([transactions_json(ROW)])
    with TestClient(create_app(Settings(warmup=False, business_name="Acme Ltd"), model_client=model),
                    headers={"X-LedgerSync": "1"}) as client:
        run_text_job(client)
    assert "Acme Ltd" in model.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("account", ["1200 Bank Current Account", "9999 Nonsense", None])
def test_an_account_the_ledger_cannot_post_to_lands_in_suspense(make_client, account):
    # The schema's list of accounts guides the model, but a row outside it must reach the ledger
    # as a Suspense row to review, not vanish with a warning.
    job = run_text_job(make_client(FakeModel([transactions_json(dict(ROW, account=account))])))
    [t] = job["result"]["transactions"]
    assert t["account_code"] == "9998" and "account_not_recognised" in [i["code"] for i in t["issues"]]


def test_health_tells_the_ui_how_many_files_to_send_at_once(make_client):
    assert make_client().get("/api/health").json()["max_parallel_jobs"] == 5


def test_validate_matches_a_payment_to_its_bill(make_client):
    bill = {**BT, "document_type": "invoice", "counterparty": "BT Business", "document_ref": "bt-sept"}
    line = {**BT, "date": "2026-09-05", "document_type": "statement", "counterparty": "BT BUSINESS DD",
            "document_ref": "line-1"}
    out_bill, out_line = make_client().post("/api/transactions/validate",
                                            json={"transactions": [bill, line]}).json()["transactions"]
    assert out_line["pays"] == [{"ref": "bt-sept", "amount": "72.00", "date": "2026-09-01", "description": "BT",
                                 "kind": "invoice"}]
    assert (out_line["paid_against"], out_line["paid_against_name"]) == ("2100", "Creditors")
    assert (out_bill["owed"], out_bill["contra_account_code"]) == ("0.00", "2100")


def test_trial_balance_waits_for_a_person_to_choose_a_payment(make_client):
    bills = [{**BT, "document_type": "invoice", "counterparty": "BT Business", "document_ref": r} for r in "ab"]
    line = {**BT, "date": "2026-09-05", "document_type": "statement", "counterparty": "BT BUSINESS",
            "document_ref": "l"}
    resp = make_client().post("/api/trial-balance", json={"transactions": [*bills, line]})
    assert resp.status_code == 422 and "Choose one" in resp.json()["detail"]["message"]
