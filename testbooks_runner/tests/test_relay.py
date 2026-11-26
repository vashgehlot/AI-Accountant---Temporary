import json
import threading
import time

import httpx
import pytest

from testbooks_runner import relay
from testbooks_runner.tests.fake_upstream import make_upstream
from testbooks_runner.tests.servers import serve


@pytest.fixture
def env(tmp_path):
    calls: list = []
    port, stop_up = serve(make_upstream(calls))
    r = relay.Relay(f"http://127.0.0.1:{port}/api/v1", tmp_path)
    r.start()
    try:
        yield r, calls, tmp_path
    finally:
        r.stop()
        stop_up()


def records(path):
    f = path / "calls.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def wait_for_records(path, n, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = records(path)
        if len(got) >= n:
            return got
        time.sleep(0.02)
    raise AssertionError(f"only {len(records(path))} records")


def test_json_call_passes_through_unchanged(env):
    r, calls, tmp = env
    body = json.dumps({"messages": [], "response_format": {"type": "json_object"}}).encode()
    resp = httpx.post(r.base_url("u1") + "/chat/completions", content=body,
                      headers={"content-type": "application/json"})
    direct_port = calls[0]["headers"]["host"].split(":")[1]
    direct = httpx.post(f"http://127.0.0.1:{direct_port}/api/v1/chat/completions", content=body,
                        headers={"content-type": "application/json"})
    assert resp.status_code == 200
    assert resp.content == direct.content
    assert calls[0]["body"] == body
    rec = wait_for_records(tmp, 1)[0]
    assert rec["streamed"] is False and rec["status"] == 200
    assert rec["generation_id"] == "gen-1"
    assert rec["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert rec["response"]["id"] == "gen-1"
    assert rec["events"] is None and rec["replayed"] is False


def test_streamed_call_arrives_chunk_by_chunk(env):
    r, calls, tmp = env
    body = {"stream": True, "tools": []}
    seen = []
    with httpx.stream("POST", r.base_url("u1") + "/chat/completions", json=body) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line:
                seen.append((time.monotonic(), line))
    assert [line.split(": ", 1)[0] for _, line in seen] == ["data"] * 4
    assert seen[-1][1] == "data: [DONE]"
    assert seen[-1][0] - seen[0][0] > 0.2  # the first chunk was not held back until the end
    rec = wait_for_records(tmp, 1)[0]
    assert rec["streamed"] is True and rec["response"] is None
    assert len(rec["events"]) == 4 and rec["events"][-1] == "[DONE]"
    assert rec["generation_id"] == "gen-1"
    assert rec["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert rec["part"] == "review"


def test_client_disconnect_mid_stream_records_what_arrived(env):
    r, calls, tmp = env
    with httpx.stream("POST", r.base_url("u1") + "/chat/completions",
                      json={"stream": True, "slow": True, "tools": []}) as resp:
        for line in resp.iter_lines():
            if line:
                break
    rec = wait_for_records(tmp, 1)[0]
    assert rec["streamed"] is True
    assert 1 <= len(rec["events"]) < 4
    assert rec["generation_id"] == "gen-1"


def test_record_never_holds_the_key(env):
    r, calls, tmp = env
    key = "sk-or-secret-123"
    httpx.post(r.base_url("u1") + "/chat/completions", json={"messages": []},
               headers={"Authorization": f"Bearer {key}"})
    with httpx.stream("POST", r.base_url("u1") + "/chat/completions", json={"stream": True, "tools": []},
                      headers={"Authorization": f"Bearer {key}"}) as resp:
        resp.read()
    httpx.get(r.base_url("u1") + "/key", headers={"Authorization": f"Bearer {key}"})
    wait_for_records(tmp, 3)
    assert calls[0]["headers"]["authorization"] == f"Bearer {key}"  # still forwarded upstream
    files = [p for p in tmp.rglob("*") if p.is_file()]
    assert files
    assert all(key not in p.read_text() for p in files)


def test_unit_prefix_is_stripped(env):
    r, calls, tmp = env
    httpx.post(r.base_url("u1") + "/chat/completions", json={"messages": []})
    assert calls[0]["path"] == "/api/v1/chat/completions"
    rec = wait_for_records(tmp, 1)[0]
    assert rec["unit"] == "u1" and rec["path"] == "/chat/completions" and rec["method"] == "POST"
    assert rec["part"] == "reader" and rec["seq"] == 1
    assert rec["request"] == {"messages": []}
    assert rec["fingerprint"] == relay.fingerprint("POST", "/chat/completions", b'{"messages": []}')


def test_query_string_is_forwarded(env):
    r, calls, tmp = env
    resp = httpx.get(r.base_url("u1") + "/generation?id=gen-1")
    assert resp.json()["data"]["total_cost"] == 0.0012
    assert calls[0]["query"] == "id=gen-1"
    rec = wait_for_records(tmp, 1)[0]
    assert rec["part"] == "health" and rec["path"] == "/generation"


def test_parts():
    assert relay.part_of("GET", b"", False) == "health"
    assert relay.part_of("POST", b'{"messages": []}', False) == "reader"
    assert relay.part_of("POST", b'{"tools": []}', False) == "review"
    assert relay.part_of("POST", b'{"tools": []}', True) == "chat"
    assert relay.part_of("POST", b"not json", True) == "reader"
    assert relay.part_of("GET", b'{"tools": []}', True) == "health"


def test_set_part_chat_marks_a_units_tool_calls(env):
    r, calls, tmp = env
    r.set_part("u1", "chat")
    httpx.post(r.base_url("u1") + "/chat/completions", json={"tools": []})
    httpx.post(r.base_url("u2") + "/chat/completions", json={"tools": []})
    r.set_part("u1", None)
    httpx.post(r.base_url("u1") + "/chat/completions", json={"tools": []})
    parts = {(x["unit"], x["seq"]): x["part"] for x in wait_for_records(tmp, 3)}
    assert parts == {("u1", 1): "chat", ("u2", 2): "review", ("u1", 3): "review"}


def test_fingerprint_ignores_key_order_and_spacing():
    a = relay.fingerprint("POST", "/x", b'{"a": 1, "b": [1, 2]}')
    b = relay.fingerprint("POST", "/x", b'{"b":[1,2],"a":1}')
    assert a == b
    assert a != relay.fingerprint("POST", "/y", b'{"a": 1, "b": [1, 2]}')
    assert relay.fingerprint("POST", "/x", b"raw") != relay.fingerprint("POST", "/x", b"raw2")


def test_upstream_error_passes_through(env):
    r, calls, tmp = env
    bad = httpx.post(r.base_url("u1") + "/fail", json={})
    assert bad.status_code == 429
    assert bad.json() == {"error": {"message": "slow down"}}
    ok = httpx.post(r.base_url("u1") + "/chat/completions", json={"messages": []})
    assert ok.status_code == 200
    recs = wait_for_records(tmp, 2)
    assert [x["status"] for x in recs] == [429, 200]


def test_bodies_pass_decoded_and_encoding_headers_are_dropped(env):
    r, calls, tmp = env
    resp = httpx.get(r.base_url("u1") + "/gzipped", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.json() == {"data": {"zipped": True}}
    assert calls[0]["headers"]["accept-encoding"] == "identity"
    assert wait_for_records(tmp, 1)[0]["response"] == {"data": {"zipped": True}}


def test_a_compressed_stream_reaches_the_app_decoded(env):
    r, calls, tmp = env
    with httpx.stream("POST", r.base_url("u1") + "/gzipped-stream", json={"tools": []}) as resp:
        assert "content-encoding" not in resp.headers  # dropped, so the body must be the decoded one
        lines = [line for line in resp.iter_lines() if line]
    assert lines == ['data: {"id": "gen-7", "choices": []}', "data: [DONE]"]
    rec = wait_for_records(tmp, 1)[0]
    assert rec["events"] == ['{"id": "gen-7", "choices": []}', "[DONE]"] and rec["generation_id"] == "gen-7"


def test_unreachable_upstream_answers_502_and_keeps_serving(tmp_path):
    r = relay.Relay("http://127.0.0.1:1/api/v1", tmp_path)
    r.start()
    try:
        for _ in range(2):
            resp = httpx.post(r.base_url("u1") + "/chat/completions", json={"messages": []},
                              headers={"Authorization": "Bearer sk-or-secret-123"})
            assert resp.status_code == 502
            assert resp.json()["error"]["message"].startswith("relay could not reach upstream: ")
        recs = wait_for_records(tmp_path, 2)
        assert [x["status"] for x in recs] == [502, 502]
        assert recs[0]["response"]["error"]["message"].startswith("relay could not reach upstream")
        assert all("sk-or-secret-123" not in p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    finally:
        r.stop()


def test_concurrent_calls_are_all_recorded(env):
    r, calls, tmp = env
    def one(i):
        httpx.post(r.base_url(f"u{i % 3}") + "/chat/completions", json={"messages": [i]})
    threads = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    recs = wait_for_records(tmp, 12)
    assert sorted(x["seq"] for x in recs) == list(range(1, 13))
    assert r.totals()["calls"] == 12


def test_stop_leaves_no_thread_behind(tmp_path):
    before = threading.active_count()
    r = relay.Relay("http://127.0.0.1:1/api/v1", tmp_path)
    r.start()
    r.stop()
    assert threading.active_count() <= before


def test_stream_dropped_by_upstream_fails_for_the_app_and_is_recorded(env):
    r, calls, tmp = env
    lines = []
    with pytest.raises(httpx.RemoteProtocolError):
        with httpx.stream("POST", r.base_url("u1") + "/drop", json={"tools": []}) as resp:
            for line in resp.iter_lines():
                lines.append(line)
    rec = wait_for_records(tmp, 1)[0]
    assert rec["streamed"] is True
    assert "[DONE]" not in rec["events"]
    assert len(rec["events"]) == 2 and rec["generation_id"] == "gen-9"
    # and the relay still serves
    assert httpx.get(r.base_url("u1") + "/models/user").status_code == 200


def test_stop_with_a_call_in_flight_is_clean_and_records_the_call(tmp_path):
    calls: list = []
    port, stop_up = serve(make_upstream(calls))
    r = relay.Relay(f"http://127.0.0.1:{port}/api/v1", tmp_path)
    r.start()
    thread = r._thread

    def client():
        try:
            with httpx.stream("POST", r.base_url("u1") + "/stall", json={"tools": []}, timeout=30) as resp:
                for _ in resp.iter_lines():
                    pass
        except httpx.HTTPError:
            pass

    t = threading.Thread(target=client)
    t.start()
    try:
        end = time.monotonic() + 5
        while not calls and time.monotonic() < end:
            time.sleep(0.02)
        time.sleep(0.3)  # let the two chunks through
        t0 = time.monotonic()
        r.stop()
        assert time.monotonic() - t0 < 10
        assert not thread.is_alive()
        recs = records(tmp_path)
        assert len(recs) == 1 and recs[0]["generation_id"] == "gen-8"
    finally:
        t.join(timeout=10)
        stop_up()


def test_key_answer_is_not_recorded(env):
    r, calls, tmp = env
    resp = httpx.get(r.base_url("u1") + "/key", headers={"Authorization": "Bearer sk-or-x"})
    assert resp.json() == {"data": {"label": "fake"}}  # the app still gets the real answer
    rec = wait_for_records(tmp, 1)[0]
    assert rec["status"] == 200 and rec["seconds"] >= 0
    assert rec["response"] == {"redacted": "key details are not recorded"}
    assert "fake" not in (tmp / "calls.jsonl").read_text()


def test_seq_continues_after_the_records_already_in_the_folder(tmp_path):
    (tmp_path / "calls.jsonl").write_text(
        json.dumps({"seq": 1}) + "\n" + json.dumps({"seq": 7}) + "\n" + json.dumps({"seq": 3}) + "\n")
    port, stop_up = serve(make_upstream([]))
    r = relay.Relay(f"http://127.0.0.1:{port}/api/v1", tmp_path, cost_lookup=False)
    r.start()
    try:
        httpx.post(r.base_url("u1") + "/chat/completions", json={"messages": []})
        recs = wait_for_records(tmp_path, 4)
    finally:
        r.stop()
        stop_up()
    assert recs[-1]["seq"] == 8
    assert r.totals()["calls"] == 8


def test_a_call_whose_answer_carries_its_cost_is_priced_without_a_lookup(tmp_path):
    # The agency run: OpenRouter's /generation answered 404 for 183 calls whose answers held usage.cost, so the
    # guard and the report counted them as unpriced ($0).
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def chat(request):
        return JSONResponse({"id": "gen-9", "choices": [{"message": {"content": "{}"}}],
                             "usage": {"prompt_tokens": 5207, "completion_tokens": 1308, "cost": 0.0016651002}})

    async def generation(request):
        return JSONResponse({"error": {"message": "not found"}}, status_code=404)

    app = Starlette(routes=[Route("/api/v1/chat/completions", chat, methods=["POST"]),
                            Route("/api/v1/generation", generation)])
    port, stop_up = serve(app)
    r = relay.Relay(f"http://127.0.0.1:{port}/api/v1", tmp_path)
    r.start()
    try:
        httpx.post(f"{r.base_url('u1')}/chat/completions", json={"model": "m", "messages": []}, timeout=10)
        wait_for_records(tmp_path, 1)
    finally:
        r.stop()   # waits for any cost lookup
        stop_up()
    totals = r.totals()
    assert (str(totals["cost"]), totals["unpriced"]) == ("0.0016651002", 0)
    [row] = [json.loads(line) for line in (tmp_path / "costs.jsonl").read_text().splitlines()]
    assert (row["tokens_in"], row["tokens_out"]) == (5207, 1308)
