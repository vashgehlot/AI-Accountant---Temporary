"""The agent eval's transcript (eval/run_agent_eval.py --transcripts): a message of the agent's history as JSON, the
thread's messages read from a checkpointer, and the file written for a run. No database: the checkpointer is a stand-in."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pymongo.errors import ServerSelectionTimeoutError

import run_agent_eval as agent_eval


class Saver:
    """Gives get_tuple the way a checkpointer does: the latest checkpoint of the thread asked for."""

    def __init__(self, messages=None, *, channels=None, missing=False, error=None):
        self.asked, self.missing, self.error = [], missing, error
        self.channels = {"messages": messages} if channels is None else channels

    def get_tuple(self, config):
        self.asked.append(config)
        if self.error:
            raise self.error
        return None if self.missing else SimpleNamespace(checkpoint={"channel_values": self.channels})


def test_an_ai_message_keeps_its_text_and_its_tool_calls():
    message = AIMessage(content="Checking the bank.",
                        tool_calls=[{"name": "get_overview", "args": {"year": "2026"}, "id": "call_1",
                                     "type": "tool_call"}],
                        response_metadata={"finish_reason": "tool_calls"})
    assert agent_eval.message_json(message) == {
        "type": "ai", "content": "Checking the bank.", "finish_reason": "tool_calls",
        "tool_calls": [{"name": "get_overview", "args": {"year": "2026"}, "id": "call_1"}]}


def test_an_ai_message_keeps_the_provider_and_model_that_answered():
    metadata = {"finish_reason": "stop", "provider": "DeepInfra", "model_name": "qwen/qwen3.8-27b",
                "model_provider": "openrouter", "id": "gen-1"}   # model_provider is LangChain's, not the host
    out = agent_eval.message_json(AIMessage(content="Done.", response_metadata=metadata))
    assert out["served_by"] == {"provider": "DeepInfra", "model_name": "qwen/qwen3.8-27b", "generation_id": "gen-1"}
    assert out["finish_reason"] == "stop"


def test_served_by_keeps_the_generation_id_so_the_host_can_be_looked_up():
    metadata = {"id": "gen-1", "model_name": "qwen/qwen3.8-27b", "finish_reason": "stop"}
    out = agent_eval.message_json(AIMessage(content="x", response_metadata=metadata))
    assert out["served_by"] == {"model_name": "qwen/qwen3.8-27b", "generation_id": "gen-1"}


def test_served_by_holds_what_the_metadata_has_and_is_left_out_when_it_has_nothing():
    # langchain-openrouter 0.2.9 names the model but not the host: the SDK drops OpenRouter's `provider` field.
    only_model = AIMessage(content="Done.", response_metadata={"model_name": "qwen/qwen3.8-27b",
                                                               "model_provider": "openrouter"})
    assert agent_eval.message_json(only_model)["served_by"] == {"model_name": "qwen/qwen3.8-27b"}
    nothing = ({}, {"finish_reason": "stop", "model_provider": "openrouter"}, {"provider": None, "model_name": ""})
    for metadata in nothing:
        assert "served_by" not in agent_eval.message_json(AIMessage(content="Done.", response_metadata=metadata))


def test_only_an_ai_message_says_who_served_it():
    metadata = {"provider": "DeepInfra", "model_name": "qwen/qwen3.8-27b"}
    for message in (HumanMessage("Hi", response_metadata=metadata),
                    ToolMessage(content="ok", tool_call_id="call_1", response_metadata=metadata)):
        assert "served_by" not in agent_eval.message_json(message)


def test_an_ai_message_with_no_tool_calls_has_an_empty_list():
    assert agent_eval.message_json(AIMessage(content="Done."))["tool_calls"] == []


def test_a_tool_message_keeps_its_status_and_all_of_its_result():
    result = "row 7 " * 5000
    out = agent_eval.message_json(ToolMessage(content=result, name="resolve", tool_call_id="call_1", status="error"))
    assert out == {"type": "tool", "content": result, "name": "resolve", "tool_call_id": "call_1", "status": "error"}
    assert len(out["content"]) == 30000


def test_human_and_system_messages_are_their_text():
    assert agent_eval.message_json(HumanMessage("Review these documents")) == {
        "type": "human", "content": "Review these documents"}
    assert agent_eval.message_json(SystemMessage("You are the accountant."))["type"] == "system"


def test_list_content_is_joined_and_its_reasoning_kept_and_labelled():
    message = AIMessage(content=[{"type": "reasoning", "reasoning": "The bank line comes first."},
                                 {"type": "text", "text": "Checking "}, {"type": "text", "text": "the bank."},
                                 {"type": "thinking", "thinking": "Then the receipt."}],
                        additional_kwargs={"reasoning_content": "Provider's own note.",
                                           "reasoning_details": [{"type": "reasoning.text", "text": "step"}]})
    out = agent_eval.message_json(message)
    assert out["content"] == "Checking the bank."
    assert out["reasoning"] == [
        {"from": "content block (reasoning)", "text": "The bank line comes first."},
        {"from": "content block (thinking)", "text": "Then the receipt."},
        {"from": "additional_kwargs.reasoning_content", "text": "Provider's own note."},
        {"from": "additional_kwargs.reasoning_details", "details": [{"type": "reasoning.text", "text": "step"}]}]


def test_a_garbled_tool_call_is_kept():
    message = AIMessage(content="", invalid_tool_calls=[{"name": "resolve", "args": "{not json", "id": "call_2",
                                                         "error": "bad json", "type": "invalid_tool_call"}])
    assert agent_eval.message_json(message)["invalid_tool_calls"][0]["args"] == "{not json"


def test_thread_messages_reads_the_latest_checkpoint_of_the_thread():
    saver = Saver([HumanMessage("Review these documents"), AIMessage(content="Done.")])
    assert [m["type"] for m in agent_eval.thread_messages(saver, "t-1")] == ["human", "ai"]
    assert saver.asked == [{"configurable": {"thread_id": "t-1"}}]


@pytest.mark.parametrize("saver", [Saver(missing=True), Saver(channels={}), Saver(channels={"messages": None})])
def test_a_thread_with_no_checkpoint_or_no_messages_has_none(saver):
    assert agent_eval.thread_messages(saver, "t-1") == []


def test_write_transcript_saves_messages_events_answers_and_the_result(tmp_path):
    trace = {"thread_id": "t-1", "client_id": 4, "events": [("status", {"text": "Working on it…"}),
                                                           ("token", {"text": "Hi"}), ("done", {})],
             "answers": [{"question": {"kind": "date"}, "route": "POST /x/answer", "sent": {"kind": "date"},
                          "status": 200, "body": {"ok": True}}]}
    saver = Saver([HumanMessage("Review these documents"), AIMessage(content="Done.")])
    path = agent_eval.write_transcript(tmp_path / "runs", "demo", 2, saver=saver, trace=trace, result={"case": "x"})

    assert path == tmp_path / "runs" / "demo-r2.json"
    saved = json.loads(path.read_text())
    assert saved["thread_id"] == "t-1" and saved["client_id"] == 4 and saved["run"] == 2
    assert [m["type"] for m in saved["messages"]] == ["human", "ai"]
    assert saved["events"][1] == ["token", {"text": "Hi"}] and len(saved["events"]) == 3
    assert saved["answers"] == trace["answers"] and saved["result"] == {"case": "x", "hosts": []}
    assert "error" not in saved and "messages_error" not in saved


def test_a_checkpoint_that_cant_be_read_is_recorded_without_the_cluster_address(tmp_path):
    saver = Saver(error=ServerSelectionTimeoutError("mongodb+srv://user:secret@cluster0.example.net timed out"))
    path = agent_eval.write_transcript(tmp_path, "clean-month", 1, saver=saver, trace={"thread_id": "t-1"},
                                       result=None, error="RuntimeError: the message was refused")
    saved = json.loads(path.read_text())
    assert saved["messages"] == [] and saved["messages_error"] == "ServerSelectionTimeoutError"
    assert saved["error"] == "RuntimeError: the message was refused" and saved["result"] is None
    assert "secret" not in path.read_text() and "cluster0" not in path.read_text()


def test_no_transcripts_by_default():
    parser = agent_eval.build_parser()
    assert parser.parse_args([]).transcripts is None
    assert str(parser.parse_args(["--transcripts", "runs"]).transcripts) == "runs"


# ─── The host that served each answer: found from the generation id, in the eval runner only ──────────────────────

def _served(generation_id=None, **more):
    meta = {"model_name": "qwen/qwen3.8-27b", "finish_reason": "stop", **more}
    if generation_id:
        meta["id"] = generation_id
    return AIMessage(content="x", response_metadata=meta)


def test_lookup_hosts_gives_the_provider_and_timing_of_each_distinct_id():
    asked = []

    def fetch(generation_id):
        asked.append(generation_id)
        return {"data": {"provider_name": "DeepInfra", "latency": 900, "generation_time": 4200}}

    found = agent_eval.lookup_hosts(["gen-1", "gen-1", "gen-2"], fetch)
    assert asked == ["gen-1", "gen-2"]
    assert found["gen-1"] == {"provider": "DeepInfra", "latency_ms": 900, "generation_time_ms": 4200}
    assert set(found) == {"gen-1", "gen-2"}


def test_lookup_hosts_accepts_a_provider_field_and_skips_what_it_cant_use():
    answers = {"gen-1": {"data": {"provider": "Novita"}}, "gen-2": None, "gen-3": {"data": {}}, "gen-4": {}}

    def fetch(generation_id):
        if generation_id == "gen-5":
            raise TimeoutError("slow")
        return answers[generation_id]

    found = agent_eval.lookup_hosts(["gen-1", "gen-2", "gen-3", "gen-4", "gen-5"], fetch)
    assert found == {"gen-1": {"provider": "Novita"}}


def test_the_host_is_filled_into_each_ai_message_and_the_transcript_lists_the_hosts():
    messages = [agent_eval.message_json(m) for m in (HumanMessage("Hi"), _served("gen-1"), _served("gen-2"))]
    hosts = agent_eval.fill_hosts(messages, lambda i: {"data": {"provider_name": "DeepInfra", "latency": 900}})
    assert hosts == ["DeepInfra"]
    assert messages[1]["served_by"] == {"model_name": "qwen/qwen3.8-27b", "generation_id": "gen-1",
                                        "provider": "DeepInfra", "latency_ms": 900}
    assert "served_by" not in messages[0]


def test_a_message_with_no_generation_id_is_left_as_it_is_and_a_failed_lookup_fills_nothing():
    messages = [agent_eval.message_json(_served())]
    before = json.dumps(messages)
    assert agent_eval.fill_hosts(messages, lambda i: pytest.fail("nothing to look up")) == []
    assert json.dumps(messages) == before

    messages = [agent_eval.message_json(_served("gen-1"))]

    def broken(generation_id):
        raise RuntimeError("down")

    assert agent_eval.fill_hosts(messages, broken) == []
    assert "provider" not in messages[0]["served_by"]


def test_write_transcript_records_the_hosts_in_the_file_and_the_result(tmp_path):
    saver = Saver([HumanMessage("Hi"), _served("gen-1"), _served("gen-2", provider="DeepInfra")])
    result = {"case": "x"}
    path = agent_eval.write_transcript(tmp_path, "demo", 1, saver=saver, trace={"thread_id": "t-1"}, result=result,
                                       fetch=lambda i: {"data": {"provider_name": "Novita"}})
    saved = json.loads(path.read_text())
    assert saved["hosts"] == ["DeepInfra", "Novita"] and saved["result"]["hosts"] == ["DeepInfra", "Novita"]
    ai = [m for m in saved["messages"] if m["type"] == "ai"]
    assert ai[0]["served_by"]["provider"] == "Novita" and ai[1]["served_by"]["provider"] == "DeepInfra"


def _generation_client(replies, seen):
    import httpx

    def handler(request):
        seen.append(request)
        return replies.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_real_fetch_asks_the_generation_route_with_the_key_in_a_header_only():
    import httpx
    from ledgersync.config import Settings

    seen, naps = [], []
    client = _generation_client([httpx.Response(404), httpx.Response(200, json={"data": {"provider_name": "X"}})], seen)
    settings = Settings(openrouter_api_key="sk-secret", openrouter_base_url="https://or.example/api/v1")
    fetch = agent_eval.generation_fetcher(settings, client=client, sleep=naps.append)
    assert fetch("gen-1") == {"data": {"provider_name": "X"}}
    assert naps == [2] and len(seen) == 2   # one retry after a 404
    assert str(seen[0].url) == "https://or.example/api/v1/generation?id=gen-1"
    assert seen[0].headers["authorization"] == "Bearer sk-secret" and "sk-secret" not in str(seen[0].url)


def test_the_real_fetch_gives_none_for_a_failure_and_without_a_key():
    import httpx
    from ledgersync.config import Settings

    seen = []
    settings = Settings(openrouter_api_key="sk-secret")
    naps = []
    client = _generation_client([httpx.Response(404)] * 4, seen)
    assert agent_eval.generation_fetcher(settings, client=client, sleep=naps.append)("gen-1") is None
    assert naps == [2, 5, 10]   # retried while the record may still be appearing, then given up
    client = _generation_client([httpx.Response(500)], seen)
    assert agent_eval.generation_fetcher(settings, client=client, sleep=lambda s: None)("gen-1") is None
    assert agent_eval.generation_fetcher(Settings(), client=client)("gen-1") is None   # no key: no call
