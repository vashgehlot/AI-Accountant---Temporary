import json
import time
from decimal import Decimal

import httpx
import pytest
from starlette.responses import JSONResponse
from starlette.routing import Route

from testbooks_runner import relay
from testbooks_runner.tests.fake_upstream import make_upstream
from testbooks_runner.tests.servers import serve


@pytest.fixture
def stops():
    fns = []
    yield fns
    for fn in reversed(fns):
        fn()


def live_upstream(stops):
    calls: list = []
    port, stop = serve(make_upstream(calls))
    stops.append(stop)
    return f"http://127.0.0.1:{port}/api/v1", calls, stop


def make_relay(stops, upstream, folder, **kw):
    r = relay.Relay(upstream, folder, **kw)
    r.start()
    stops.append(r.stop)
    return r


def records(folder):
    f = folder / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def stream_lines(r, body, headers=None):
    with httpx.stream("POST", r.base_url("u") + "/chat/completions", json=body, headers=headers) as resp:
        return resp.status_code, [x for x in resp.iter_lines() if x]


def wait_until(fn, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def record_first_run(stops, tmp_path, upstream, bodies=(), gets=()):
    a_dir = tmp_path / "a"
    a = make_relay(stops, upstream, a_dir, cost_lookup=False)
    for b in bodies:
        httpx.post(a.base_url("u") + "/chat/completions", json=b)
    for g in gets:
        httpx.get(a.base_url("u") + g)
    wait_until(lambda: len(records(a_dir)) >= len(bodies) + len(gets))
    return a_dir


def test_replay_answers_without_upstream(tmp_path, stops):
    up, calls, stop_up = live_upstream(stops)
    json_body = {"messages": [], "n": 1}
    stream_body = {"stream": True, "tools": []}
    a_dir = record_first_run(stops, tmp_path, up, bodies=[json_body, stream_body])
    # what A gave the app, from its own records
    rec_json, rec_stream = records(a_dir)
    stop_up()
    stops.remove(stop_up)

    b_dir = tmp_path / "b"
    b = make_relay(stops, "http://127.0.0.1:9/api/v1", b_dir, replay_from=a_dir)
    resp = httpx.post(b.base_url("u") + "/chat/completions", json=json_body)
    assert resp.status_code == 200 and resp.json() == rec_json["response"]
    status, lines = stream_lines(b, stream_body)
    assert status == 200
    assert lines == [f"data: {e}" for e in rec_stream["events"]]
    got = records(b_dir)
    assert [r["replayed"] for r in got] == [True, True]
    assert got[1]["streamed"] is True and got[1]["generation_id"] == "gen-1"
    t = b.totals()
    assert t["cost"] == 0 and t["calls"] == 2 and t["replayed"] == 2


def test_replay_miss_goes_live(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    a_dir = record_first_run(stops, tmp_path, up, bodies=[{"n": 1}])
    n = len(calls)
    b = make_relay(stops, up, tmp_path / "b", replay_from=a_dir, cost_lookup=False)
    httpx.post(b.base_url("u") + "/chat/completions", json={"n": 2})
    assert len(calls) == n + 1
    assert records(tmp_path / "b")[0]["replayed"] is False


def test_strict_miss_is_refused(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    a_dir = record_first_run(stops, tmp_path, up, bodies=[{"n": 1}])
    n = len(calls)
    b = make_relay(stops, up, tmp_path / "b", replay_from=a_dir, strict=True)
    resp = httpx.post(b.base_url("u") + "/chat/completions", json={"n": 2})
    assert resp.status_code == 502
    assert resp.json() == {"error": {"message": "no recording for this call"}}
    assert len(calls) == n
    ok = httpx.post(b.base_url("u") + "/chat/completions", json={"n": 1})
    assert ok.status_code == 200 and len(calls) == n


def test_recordings_are_used_in_order_then_post_goes_live(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    a_dir = record_first_run(stops, tmp_path, up, bodies=[{"n": 1}, {"n": 1}])
    n = len(calls)
    b = make_relay(stops, up, tmp_path / "b", replay_from=a_dir, cost_lookup=False)
    for _ in range(2):
        httpx.post(b.base_url("u") + "/chat/completions", json={"n": 1})
    assert len(calls) == n
    httpx.post(b.base_url("u") + "/chat/completions", json={"n": 1})
    assert len(calls) == n + 1  # used up: goes live


def test_error_and_unfinished_recordings_are_not_replayed(tmp_path):
    folder = tmp_path / "a"
    folder.mkdir()
    fp_err = relay.fingerprint("POST", "/chat/completions", json.dumps({"e": 1}).encode())
    fp_cut = relay.fingerprint("POST", "/chat/completions", json.dumps({"c": 1}).encode())
    rows = [
        {"fingerprint": fp_err, "status": 429, "streamed": False, "response": {"error": {}}, "events": None},
        {"fingerprint": fp_cut, "status": 200, "streamed": True, "response": None,
         "events": ['{"id": "gen-9"}']},
    ]
    (folder / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = relay.Relay("http://127.0.0.1:9/api/v1", tmp_path / "b", replay_from=folder, strict=True)
    assert r._recordings == {}
    r.start()
    try:
        for body in ({"e": 1}, {"c": 1}):
            resp = httpx.post(r.base_url("u") + "/chat/completions", json=body)
            assert resp.status_code == 502
            assert resp.json() == {"error": {"message": "no recording for this call"}}
    finally:
        r.stop()


def test_exhausted_get_keeps_answering_from_its_last_recording(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    a_dir = record_first_run(stops, tmp_path, up, gets=["/models/user"])
    n = len(calls)
    b = make_relay(stops, up, tmp_path / "b", replay_from=a_dir, strict=True)
    answers = [httpx.get(b.base_url("u") + "/models/user") for _ in range(3)]
    assert [a.status_code for a in answers] == [200] * 3
    assert answers[0].json() == answers[2].json() == {"data": [{"id": "qwen/qwen3.8-27b", "active": True}]}
    assert len(calls) == n
    assert [r["replayed"] for r in records(tmp_path / "b")] == [True] * 3


def test_cost_is_looked_up(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    d = tmp_path / "a"
    a = make_relay(stops, up, d)
    httpx.post(a.base_url("u") + "/chat/completions", json={"messages": [], "tools": []})
    wait_until(lambda: (d / "costs.jsonl").exists() and len((d / "costs.jsonl").read_text().splitlines()) == 1)
    row = json.loads((d / "costs.jsonl").read_text())
    assert row == {"seq": 1, "cost": "0.0012", "tokens_in": 100, "tokens_out": 50}
    t = a.totals()
    assert t["cost"] == Decimal("0.0012") and t["unpriced"] == 0
    assert t["by_part"] == {"review": Decimal("0.0012")}


def test_lookup_uses_the_callers_key(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    d = tmp_path / "a"
    a = make_relay(stops, up, d)
    httpx.post(a.base_url("u") + "/chat/completions", json={"n": 1},
               headers={"Authorization": "Bearer sk-test-123"})
    wait_until(lambda: any(c["path"].endswith("/generation") for c in calls))
    look = [c for c in calls if c["path"].endswith("/generation")][0]
    assert look["headers"]["authorization"] == "Bearer sk-test-123"
    assert look["query"] == "id=gen-1"
    wait_until(lambda: (d / "costs.jsonl").exists())
    a.stop()
    for f in d.iterdir():
        assert "sk-test-123" not in f.read_text()
    assert "sk-test-123" not in repr(vars(a))


def test_replayed_call_gets_no_lookup(tmp_path, stops):
    up, calls, _ = live_upstream(stops)
    a_dir = record_first_run(stops, tmp_path, up, bodies=[{"n": 1}])
    n = len(calls)
    b = make_relay(stops, up, tmp_path / "b", replay_from=a_dir)
    httpx.post(b.base_url("u") + "/chat/completions", json={"n": 1})
    b.stop()
    assert len(calls) == n
    assert not (tmp_path / "b" / "costs.jsonl").exists()


def test_lookup_that_keeps_failing_is_unpriced(tmp_path, stops, monkeypatch):
    monkeypatch.setattr(relay, "_LOOKUP_DELAY", 0.01)
    monkeypatch.setattr(relay, "_LOOKUP_GAP", 0.01)
    calls: list = []
    app = make_upstream(calls)

    async def not_booked(request):
        return JSONResponse({"error": {"message": "not found"}}, status_code=404)

    app.router.routes.insert(0, Route("/api/v1/generation", not_booked))
    port, stop_up = serve(app)
    stops.append(stop_up)
    d = tmp_path / "a"
    a = make_relay(stops, f"http://127.0.0.1:{port}/api/v1", d)
    assert httpx.post(a.base_url("u") + "/chat/completions", json={"n": 1}).status_code == 200
    wait_until(lambda: (d / "costs.jsonl").exists())
    row = json.loads((d / "costs.jsonl").read_text())
    assert row == {"seq": 1, "cost": None, "tokens_in": None, "tokens_out": None, "error": "404"}
    t = a.totals()
    assert t["cost"] == 0 and t["unpriced"] == 1 and t["calls"] == 1 and t["by_part"] == {}
