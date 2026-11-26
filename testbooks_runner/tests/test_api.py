import json
from datetime import date

import httpx
import pytest

from testbooks_runner import api


def make(handler, **kw):
    return api.Api("http://app.test", transport=httpx.MockTransport(handler), **kw)


def test_every_request_carries_the_header():
    seen = []

    def handler(request):
        seen.append(request.headers["X-LedgerSync"])
        return httpx.Response(200, json={"ok": True})

    client = make(handler)
    assert client.health() == {"ok": True}
    client.accounts(3)
    client.client(3)
    assert seen == ["testbooks-runner"] * 3


def test_errors_become_app_error(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"x")

    def handler(request):
        return httpx.Response(409, json={"detail": {"code": "same_file", "message": "Skipped a.pdf"}})

    with pytest.raises(api.AppError) as e:
        make(handler).analyze(1, date(2023, 4, 1), f, None)
    assert (e.value.status, e.value.code, e.value.message) == (409, "same_file", "Skipped a.pdf")


def test_list_detail_and_plain_body_errors():
    detail = [{"loc": ["body", "x"], "msg": "bad", "type": "value_error"}]

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(422, json={"detail": detail})
        return httpx.Response(502, text="y" * 800)

    client = make(handler)
    with pytest.raises(api.AppError) as e:
        client.health()
    assert (e.value.status, e.value.code) == (422, "http_422")
    assert e.value.message == json.dumps(detail, separators=(",", ":"))
    with pytest.raises(api.AppError) as e:
        client.client(1)
    assert (e.value.status, e.value.code) == (502, "http_502")
    assert e.value.message == "y" * 500


def test_long_list_detail_is_cut():
    def handler(request):
        return httpx.Response(422, json={"detail": ["z" * 900]})

    with pytest.raises(api.AppError) as e:
        make(handler).health()
    assert len(e.value.message) == 500


def test_analyze_sends_the_file_and_fields(tmp_path):
    f = tmp_path / "a b.pdf"
    f.write_bytes(b"PDFDATA")
    bodies = []

    def handler(request):
        bodies.append((request.method, request.url.path, request.read()))
        return httpx.Response(202, json={"job_id": "abc123", "status": "queued"})

    client = make(handler)
    assert client.analyze(7, date(2023, 4, 1), f, None) == "abc123"
    method, path, body = bodies[0]
    assert (method, path) == ("POST", "/api/analyze")
    assert b'filename="a b.pdf"' in body and b"PDFDATA" in body
    assert b'name="year_start"' in body and b"2023-04-01" in body
    assert b'name="client_id"' in body
    assert b'name="bank_account"' not in body
    client.analyze(7, date(2023, 4, 1), f, "1200")
    assert b'name="bank_account"' in bodies[1][2] and b"1200" in bodies[1][2]


def test_sse_events_until_done(tmp_path):
    f = tmp_path / "r 1.txt"
    f.write_bytes(b"hello file")
    captured = {}
    sse = (
        'event: status\ndata: {"text": "Reading"}\n\n'
        'event: token\ndata: {"text": "Hi"}\n\n'
        "event: done\ndata: {}\n\n"
        'event: token\ndata: {"text": "after"}\n\n'
    )

    def handler(request):
        captured["body"] = request.read()
        captured["path"] = request.url.path
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())

    client = make(handler)
    assert client.send_message("t1", "hello", []) == [
        ("status", {"text": "Reading"}),
        ("token", {"text": "Hi"}),
        ("done", {}),
    ]
    assert captured["path"] == "/api/chat/threads/t1/messages"
    client.send_message("t1", "hello", [f])
    assert b'name="text"' in captured["body"]
    assert b'name="files"; filename="r 1.txt"' in captured["body"]
    assert b"hello file" in captured["body"]


def test_send_message_error_before_stream():
    def handler(request):
        return httpx.Response(409, json={"detail": {"code": "still_working", "message": "busy"}})

    with pytest.raises(api.AppError) as e:
        make(handler).send_message("t1", "hi", [])
    assert (e.value.status, e.value.code) == (409, "still_working")


def test_stream_has_a_long_read_timeout():
    seen = {}

    def handler(request):
        seen[request.url.path] = request.extensions["timeout"]["read"]
        if request.url.path == "/api/health":
            return httpx.Response(200, json={})
        return httpx.Response(200, content=b"event: done\ndata: {}\n\n", headers={"content-type": "text/event-stream"})

    client = make(handler)
    client.send_message("t1", "hi", [])
    client.health()
    assert seen["/api/chat/threads/t1/messages"] >= 600
    assert seen["/api/health"] == 120.0


def test_vat_passes_the_period():
    def handler(request):
        assert request.url.path == "/api/clients/5/years/2023-04-01/vat"
        assert request.url.params["period_start"] == "2023-06-01"
        assert request.url.params["period_end"] == "2023-08-31"
        return httpx.Response(200, json={"boxes": {}})

    assert make(handler).vat(5, date(2023, 4, 1), date(2023, 6, 1), date(2023, 8, 31)) == {"boxes": {}}


def test_routes_and_bodies():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.url.query.decode(), request.content))
        if request.url.path.endswith("export.xlsx"):
            return httpx.Response(200, content=b"XLSX")
        return httpx.Response(200, json={})

    c = make(handler)
    y = date(2023, 4, 1)
    c.accounts(1)
    c.create_client({"name": "A"})
    c.years(1)
    c.put_opening(1, {"k": "v"})
    c.job("j1")
    for name in ("ledger", "posted_tb", "tb_shown", "invoices", "bank", "summary", "suggestions"):
        getattr(c, name)(1, y)
    assert c.export_xlsx(1, y) == b"XLSX"
    c.questions(1)
    c.decisions(1)
    c.reviews(1)
    c.new_thread(1)
    c.thread("t1")
    base = "/api/clients/1/years/2023-04-01"
    got = [(m, p, q) for m, p, q, _ in calls]
    assert got == [
        ("GET", "/api/accounts", "client_id=1"),
        ("POST", "/api/clients", ""),
        ("GET", "/api/clients/1/years", ""),
        ("PUT", "/api/clients/1/opening-balances", ""),
        ("GET", "/api/jobs/j1", ""),
        ("GET", base + "/ledger", ""),
        ("GET", base + "/posted-trial-balance", ""),
        ("GET", base + "/trial-balance", "shown=true"),
        ("GET", base + "/invoices", ""),
        ("GET", base + "/bank", ""),
        ("GET", base + "/summary", ""),
        ("GET", base + "/suggestions", ""),
        ("GET", base + "/export.xlsx", ""),
        ("GET", "/api/clients/1/questions", ""),
        ("GET", "/api/clients/1/decisions", ""),
        ("GET", "/api/clients/1/reviews", ""),
        ("POST", "/api/chat/threads", ""),
        ("GET", "/api/chat/threads/t1", ""),
    ]
    assert json.loads(calls[1][3]) == {"name": "A"}
    assert json.loads(calls[3][3]) == {"k": "v"}
    assert json.loads(calls[16][3]) == {"client_id": 1}


def test_stream_without_done_raises_with_the_events_so_far():
    sse = 'event: status\ndata: {"text": "Reading"}\n\nevent: token\ndata: {"text": "Hi"}\n\n'

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())

    with pytest.raises(api.AppError) as e:
        make(handler).send_message("t1", "hello", [])
    assert (e.value.status, e.value.code) == (200, "stream_ended")
    assert e.value.events == [("status", {"text": "Reading"}), ("token", {"text": "Hi"})]
    assert api.AppError(500, "x", "y").events == []


def test_new_thread_sends_the_year_only_when_given():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"id": "t"})

    client = make(handler)
    client.new_thread(3)
    client.new_thread(3, date(2023, 4, 1))
    assert bodies == [{"client_id": 3}, {"client_id": 3, "year_start": "2023-04-01"}]
