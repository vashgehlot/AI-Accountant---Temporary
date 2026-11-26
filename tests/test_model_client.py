import json
import logging
import urllib.error
from typing import Optional

import pytest
from fakes import FakeUrlopen, chat_answer, http_error, streamed
from pydantic import BaseModel, Field

from ledgersync.config import Settings
from ledgersync.errors import LedgerSyncError, ModelError, ModelRateLimited, ModelTimeout, ModelUnavailable
from ledgersync.model_client import ModelClient, openrouter_route, strict_schema

KEY = "sk-test-1234"
SETTINGS = Settings(groq_api_key=KEY)
OPENROUTER = Settings(openrouter_api_key=KEY, groq_api_key="gsk-unused")
MODELS = {"object": "list", "data": [{"id": "qwen/qwen3.8-27b", "object": "model", "active": True}]}
MSG = [{"role": "system", "content": "rules"}, {"role": "user", "content": "doc"}]
SCHEMA = {"type": "object", "properties": {"transactions": {"type": "array", "items": {"type": "object"}}}}


def make_client(*outcomes, settings=SETTINGS):
    http, now, slept = FakeUrlopen(*outcomes), [0.0], []
    client = ModelClient(settings, opener=http, clock=lambda: now[0], sleep=slept.append)
    return client, http, now, slept


def test_chat_asks_the_configured_model_for_strict_json():
    client, http, _, _ = make_client(chat_answer('{"transactions": [1]}'))
    assert client.chat_json(MSG, SCHEMA) == '{"transactions": [1]}'
    req, timeout = http.requests[0]
    body = http.payload()
    assert req.full_url == "https://api.groq.com/openai/v1/chat/completions" and timeout == 200.0
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("User-agent").startswith("LedgerSync")   # urllib's default agent can be blocked
    assert (body["model"], body["temperature"], body["max_completion_tokens"], body["reasoning_effort"]) == (
        "qwen/qwen3.8-27b", 0, 8192, "high")
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["additionalProperties"] is False
    assert "provider" not in body and "stream" not in body   # OpenRouter's routing; Groq streams no structured output


def test_with_an_openrouter_key_the_same_model_is_asked_through_openrouter():
    client, http, _, _ = make_client(chat_answer('{"transactions": [1]}'), settings=OPENROUTER)
    assert client.chat_json(MSG, SCHEMA) == '{"transactions": [1]}'
    req, _ = http.requests[0]
    body = http.payload()
    assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert (body["model"], body["max_tokens"], body["reasoning_effort"]) == ("qwen/qwen3.8-27b", 32768, "high")
    assert "max_completion_tokens" not in body
    # Only providers that honour every setting, the strict schema above all; others would ignore it.
    assert body["provider"]["require_parameters"] is True
    assert body["response_format"]["json_schema"]["strict"] is True


def test_openrouter_asks_a_full_precision_host_first_and_never_a_4_bit_one():
    # Left to choose, OpenRouter sent every read to one 4-bit host, which left a line out of Jenny's expense
    # claim in 13 reads of 13; other hosts missed it less often (2026-10-08).
    client, http, _, _ = make_client(chat_answer(), settings=OPENROUTER)
    client.chat_json(MSG, SCHEMA)
    assert http.payload()["provider"] == {"require_parameters": True, "order": ["deepinfra/bf16"],
                                          "quantizations": ["bf16", "fp16", "fp32", "fp8"]}


def test_blank_routing_settings_leave_the_host_to_openrouter():
    settings = Settings(openrouter_api_key=KEY, openrouter_providers=(), openrouter_quantizations=())
    client, http, _, _ = make_client(chat_answer(), settings=settings)
    client.chat_json(MSG, SCHEMA)
    assert http.payload()["provider"] == {"require_parameters": True}


def test_the_route_is_one_builder_for_the_reader_and_the_chat_agent():
    # The chat agent (tests/test_agent.py) sends this same route, with its own data_collection added.
    default = {"order": ["deepinfra/bf16"], "quantizations": ["bf16", "fp16", "fp32", "fp8"]}
    assert openrouter_route(Settings()) == default
    assert openrouter_route(Settings(), require_parameters=True) == {"require_parameters": True, **default}
    chosen = Settings(openrouter_providers=("parasail/fp8", "wafer"), openrouter_quantizations=("bf16",))
    assert openrouter_route(chosen) == {"order": ["parasail/fp8", "wafer"], "quantizations": ["bf16"]}
    assert openrouter_route(Settings(openrouter_providers=(), openrouter_quantizations=())) == {}


def test_the_answer_names_the_host_that_wrote_it():
    client, _, _, _ = make_client(chat_answer('{"transactions": [1]}', provider="DeepInfra"), settings=OPENROUTER)
    answer = client.chat_json(MSG, SCHEMA)
    assert answer == '{"transactions": [1]}' and answer.host == "DeepInfra"
    client, _, _, _ = make_client(chat_answer())   # Groq hosts the model itself and names no one
    assert client.chat_json(MSG, SCHEMA).host is None


def test_images_are_sent_as_jpeg_parts_of_the_last_message():
    client, http, _, _ = make_client(chat_answer())
    client.chat_json(MSG, SCHEMA, images=["AAAA", "BBBB"])
    system, user = http.payload()["messages"]
    assert system == {"role": "system", "content": "rules"}
    assert user["content"] == [
        {"type": "text", "text": "doc"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBBB"}},
    ]


def test_chat_json_can_ask_for_less_thinking():
    # A statement read in code only needs its lines coded: that needs little thinking.
    client, http, _, _ = make_client(chat_answer())
    client.chat_json(MSG, SCHEMA, reasoning_effort="low")
    assert http.payload()["reasoning_effort"] == "low"


def test_reasoning_effort_is_left_out_when_blank():
    client, http, _, _ = make_client(chat_answer(), settings=Settings(groq_api_key=KEY, reasoning_effort=""))
    client.chat_json(MSG, SCHEMA)
    assert "reasoning_effort" not in http.payload()


def test_an_answer_cut_off_at_the_token_limit_is_an_error():
    client, _, _, _ = make_client(chat_answer('{"transactions": [', finish_reason="length"))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_output_truncated"


def test_an_answer_that_trails_off_into_whitespace_is_stopped_and_closed():
    # The agency run: for a notice of administration the model wrote {"transactions": [] and then only whitespace for
    # 14 minutes, to the 32,768-token cap; the app had given up at 300 seconds.
    stream = streamed('{"transactions": []', *["\n\n  "] * 400, finish_reason="length")
    client, http, _, _ = make_client(stream, settings=OPENROUTER)
    assert json.loads(client.chat_json(MSG, SCHEMA)) == {"transactions": []}
    assert http.payload()["stream"] is True and stream.read_lines < 200   # stopped well before the end


def test_a_trailing_off_answer_that_cannot_be_closed_is_an_error():
    client, _, _, _ = make_client(streamed('{"transactions": [{"amount": 1', *["   "] * 400), settings=OPENROUTER)
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_output_invalid"


def test_a_streamed_answer_still_arriving_after_the_silence_limit_is_read():
    # A long statement keeps sending: only silence (OPENROUTER_TIMEOUT, 200 s) is a reason to give up on it.
    client, _, _, _ = make_client(streamed('{"transactions": [', '1', ']}', finish_reason="stop"), settings=OPENROUTER)
    ticks = iter([0.0, 150.0, 300.0, 450.0, 450.0])
    client._clock = lambda: next(ticks)
    assert client.chat_json(MSG, SCHEMA) == '{"transactions": [1]}'


def test_a_streamed_answer_past_the_overall_cap_is_a_timeout():
    client, _, _, _ = make_client(streamed('{"transactions": [', '1', ']}', finish_reason="stop"), settings=OPENROUTER)
    ticks = iter([0.0, 300.0, 601.0, 601.0])
    client._clock = lambda: next(ticks)
    with pytest.raises(ModelTimeout) as info:
        client.chat_json(MSG, SCHEMA)
    assert "600 seconds" in info.value.message and "OPENROUTER_TOTAL_TIMEOUT" in info.value.message


def test_the_silence_limit_is_the_wait_for_each_piece_of_the_answer():
    client, http, _, _ = make_client(chat_answer('{"transactions": []}'), settings=OPENROUTER)
    client.chat_json(MSG, SCHEMA)
    assert http.requests[0][1] == 200.0


def test_an_empty_answer_is_an_error():
    client, _, _, _ = make_client(chat_answer(""))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_output_invalid"


def test_strict_schema_inlines_refs_closes_objects_and_drops_unsupported_keywords():
    class Row(BaseModel):
        name: str = Field(..., title="Name", description="who")
        note: Optional[str] = None

    class Doc(BaseModel):
        rows: list[Row]

    schema = strict_schema(Doc.model_json_schema())
    text = json.dumps(schema)
    row = schema["properties"]["rows"]["items"]
    assert "$ref" not in text and "$defs" not in text and "title" not in text and "default" not in text
    assert schema["additionalProperties"] is False and row["additionalProperties"] is False
    assert row["required"] == ["name", "note"] and row["properties"]["name"]["description"] == "who"
    assert row["properties"]["note"]["anyOf"] == [{"type": "string"}, {"type": "null"}]


def test_the_client_sends_three_pages_per_request_by_default():
    # Groq's most. Three pages are about 7.2K tokens before any answer, over the free plan's 8K tokens a
    # minute, so there GROQ_MAX_IMAGES=1.
    client, _, _, _ = make_client()
    assert client.max_images == 3


def test_health_needs_a_key():
    client, http, _, _ = make_client(settings=Settings())
    health = client.health()
    assert not health.model_available and http.requests == []
    assert "Set OPENROUTER_API_KEY or GROQ_API_KEY in .env" in health.error


def test_health_finds_the_model_in_the_providers_list():
    client, http, _, _ = make_client(MODELS)
    assert client.health().model_available
    assert http.requests[0][0].full_url == "https://api.groq.com/openai/v1/models"


def test_openrouter_health_asks_for_the_keys_own_record_and_then_the_accounts_model_list():
    # OpenRouter's /models answers without a key, and /models/user still lists the models for a key that has
    # expired: the key's own record is asked first, which doesn't answer for one.
    client, http, _, _ = make_client({"data": {"label": "sk-or-...", "usage": 1.5}}, MODELS, settings=OPENROUTER)
    assert client.health().model_available
    (key, _), (listing, _) = http.requests
    assert key.full_url == "https://openrouter.ai/api/v1/key" and key.get_header("Authorization") == f"Bearer {KEY}"
    assert listing.full_url == "https://openrouter.ai/api/v1/models/user"
    assert listing.get_header("Authorization") == f"Bearer {KEY}"


def test_openrouter_health_says_when_the_key_has_expired_though_the_models_are_still_listed():
    # 15 Nov 2026: the header said "AI online" while every model call was refused with "API key expired."
    client, http, _, _ = make_client(http_error(401, "API key expired."), MODELS, settings=OPENROUTER)
    health = client.health()
    assert health.reachable and not health.model_available
    assert health.error == ("OpenRouter's API key has expired. Put a new key in OPENROUTER_API_KEY in .env, then "
                            "restart the API.")
    assert len(http.requests) == 1 and KEY not in health.error


def test_openrouter_health_goes_by_the_model_list_when_the_keys_record_is_not_to_be_had():
    # Another gateway on OPENROUTER_BASE_URL may not serve /key, and a rate limit proves the key works.
    for outcome in (http_error(404), http_error(429), http_error(500)):
        client, http, _, _ = make_client(outcome, MODELS, settings=OPENROUTER)
        assert client.health().model_available and len(http.requests) == 2


def test_a_call_refused_for_an_expired_key_says_the_key_has_expired():
    client, _, _, _ = make_client(http_error(401, "API key expired."), settings=OPENROUTER)
    with pytest.raises(LedgerSyncError) as info:
        client.chat_json(MSG, SCHEMA)
    assert "OpenRouter's API key has expired. Put a new key in OPENROUTER_API_KEY" in info.value.message


def test_health_reports_a_model_the_provider_does_not_offer():
    client, _, _, _ = make_client({"data": [{"id": "openai/gpt-oss-20b", "active": True}]})
    health = client.health()
    assert health.reachable and not health.model_available and "qwen/qwen3.8-27b" in health.error


def test_health_is_cached_for_five_minutes():
    # The UI polls every 30 s, and free plans count requests.
    client, http, now, _ = make_client(MODELS, MODELS)
    client.health()
    now[0] += 299
    client.health()
    assert len(http.requests) == 1
    now[0] += 2
    client.health()
    assert len(http.requests) == 2


def test_ensure_available_explains_a_missing_key():
    # Settings are read once at startup, so the fix needs a restart.
    client, _, _, _ = make_client(settings=Settings())
    with pytest.raises(ModelUnavailable, match="GROQ_API_KEY in .env, then restart the API"):
        client.ensure_available()


@pytest.mark.parametrize("status, error, code, words", [
    (401, ModelUnavailable, "ai_offline", "Groq rejected the API key"),
    (403, ModelUnavailable, "ai_offline", "Groq rejected the API key"),
    (404, ModelUnavailable, "ai_offline", "Groq does not offer the model 'qwen/qwen3.8-27b'"),
    (413, ModelError, "ai_input_too_long", "too large for Groq"),
])
def test_provider_refusals_become_clear_errors(status, error, code, words):
    client, _, _, _ = make_client(http_error(status))
    with pytest.raises(error) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == code and words in info.value.message


@pytest.mark.parametrize("outcome, words", [
    (http_error(401), "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env"),
    (http_error(404), "OpenRouter does not offer the model 'qwen/qwen3.8-27b'. Check OPENROUTER_MODEL in .env"),
    (http_error(429, retry_after=120), "OpenRouter's rate limit is used up"),
    (TimeoutError(), "OpenRouter sent nothing for 200 seconds"),
])
def test_openrouter_errors_name_openrouter_and_its_settings(outcome, words):
    client, _, _, _ = make_client(outcome, settings=OPENROUTER)
    with pytest.raises(LedgerSyncError) as info:
        client.chat_json(MSG, SCHEMA)
    assert words in info.value.message and "Groq" not in info.value.message


def test_a_404_passes_on_the_providers_reason():
    client, _, _, _ = make_client(http_error(404, "No endpoints found matching your data policy"),
                                  settings=OPENROUTER)
    with pytest.raises(ModelUnavailable, match="No endpoints found matching your data policy"):
        client.chat_json(MSG, SCHEMA)


def test_a_context_length_400_means_the_document_is_too_long():
    client, _, _, _ = make_client(http_error(400, "Please reduce the length of the messages or completion."))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_input_too_long"


def test_other_400s_pass_on_the_providers_message():
    client, _, _, _ = make_client(http_error(400, "response_format is invalid"))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_error" and "response_format is invalid" in info.value.message


def test_a_rate_limit_is_waited_out_then_the_call_succeeds():
    client, _, _, slept = make_client(http_error(429, "rate limit", retry_after=7), chat_answer())
    assert client.chat_json(MSG, SCHEMA) == '{"transactions": []}'
    assert slept == [7.0]


def test_a_rate_limit_without_retry_after_waits_ten_seconds():
    client, _, _, slept = make_client(http_error(429), chat_answer())
    client.chat_json(MSG, SCHEMA)
    assert slept == [10.0]


def test_a_rate_limit_that_lasts_gives_up_after_a_minute():
    client, _, _, slept = make_client(*(http_error(429, retry_after=25) for _ in range(3)))
    with pytest.raises(ModelRateLimited) as info:
        client.chat_json(MSG, SCHEMA)
    assert (info.value.code, info.value.status_code, slept) == ("ai_rate_limited", 503, [25.0, 25.0])


def test_a_server_error_is_retried_once():
    client, _, _, slept = make_client(http_error(503), chat_answer())
    assert client.chat_json(MSG, SCHEMA) == '{"transactions": []}' and slept == [1.0]
    client, _, _, _ = make_client(http_error(500), http_error(502))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_error"


def test_no_connection_after_one_retry_is_ai_offline():
    client, _, _, _ = make_client(*(urllib.error.URLError(ConnectionRefusedError()) for _ in range(2)))
    with pytest.raises(ModelUnavailable) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.code == "ai_offline" and "Cannot reach Groq" in info.value.message
    client, _, _, _ = make_client(*(urllib.error.URLError(ConnectionRefusedError()) for _ in range(2)),
                                  settings=OPENROUTER)
    with pytest.raises(ModelUnavailable, match="Cannot reach OpenRouter at https://openrouter.ai/api/v1"):
        client.chat_json(MSG, SCHEMA)


def test_a_slow_provider_times_out_with_504():
    client, _, _, _ = make_client(TimeoutError())
    with pytest.raises(ModelTimeout) as info:
        client.chat_json(MSG, SCHEMA)
    assert info.value.status_code == 504


def test_the_key_never_reaches_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    for settings in (SETTINGS, OPENROUTER):
        client, _, _, _ = make_client(http_error(400, f"bad request from key {KEY}"), settings=settings)
        with pytest.raises(ModelError) as info:
            client.chat_json(MSG, SCHEMA)
        assert KEY not in info.value.message and KEY not in caplog.text


def test_health_reports_a_rejected_key():
    client, _, _, _ = make_client(http_error(401))
    health = client.health()
    assert health.reachable and not health.model_available and "rejected the API key" in health.error


def test_health_counts_a_rate_limited_check_as_available():
    # Being rate limited proves the key works; refusing analyses for the 5-minute cache would not help.
    client, _, _, _ = make_client(http_error(429))
    assert client.health().model_available


def test_a_failed_check_is_tried_again_soon_so_the_app_recovers_with_the_network():
    # Only successful checks are kept for five minutes; a failure must not lock the app out that long.
    client, http, now, _ = make_client(urllib.error.URLError(ConnectionRefusedError()), MODELS)
    assert not client.health().model_available
    now[0] += 20
    client.ensure_available()
    assert len(http.requests) == 2


def test_a_daily_limit_says_when_it_resets_instead_of_a_minute():
    # Groq's free plan also caps tokens per day; its Retry-After can be many minutes.
    client, _, _, slept = make_client(http_error(429, "Rate limit reached on tokens per day (TPD). "
                                                      "Please try again in 16m27s.", retry_after=987))
    with pytest.raises(ModelRateLimited) as info:
        client.chat_json(MSG, SCHEMA)
    assert slept == [] and "about 17 minutes" in info.value.message and "in a minute" not in info.value.message


def test_the_key_is_blanked_before_a_long_error_is_shortened():
    # Shortening first could cut a real-length key in half and leave most of it in the message.
    key = "gsk_" + "a1b2" * 13
    client, _, _, _ = make_client(http_error(400, "x" * 270 + key), settings=Settings(groq_api_key=key))
    with pytest.raises(ModelError) as info:
        client.chat_json(MSG, SCHEMA)
    assert key[:20] not in info.value.message
