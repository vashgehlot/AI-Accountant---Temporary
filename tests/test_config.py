import inspect
import re
from pathlib import Path

from ledgersync import config
from ledgersync.config import ENV_FILE, ENV_NAMES, Settings, read_env_file


def test_defaults_are_local_and_bounded():
    s = Settings.from_env({})
    assert s.host == "127.0.0.1"
    assert s.cors_origins == ("http://localhost:3000", "http://127.0.0.1:3000")
    assert s.reload is False and s.warmup is True
    assert s.max_upload_bytes == 20 * 1024 * 1024
    assert s.max_pdf_pages == 30


def test_env_overrides():
    s = Settings.from_env({
        "LEDGERSYNC_CORS_ORIGINS": "http://a:1, http://b:2",
        "LEDGERSYNC_RELOAD": "true",
        "LEDGERSYNC_WARMUP": "0",
        "LEDGERSYNC_MAX_UPLOAD_MB": "5",
    })
    assert s.cors_origins == ("http://a:1", "http://b:2")
    assert s.reload is True and s.warmup is False
    assert s.max_upload_bytes == 5 * 1024 * 1024


def test_groq_settings_have_working_defaults():
    s = Settings.from_env({})
    assert (s.groq_base_url, s.groq_model) == ("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b")
    assert (s.model_timeout, s.groq_max_output_tokens, s.reasoning_effort, s.max_images) == (200.0, 8192, "high", 3)
    assert (s.groq_api_key, s.openrouter_api_key, s.business_name, s.health_ttl) == ("", "", "", 300.0)


def test_groq_settings_use_groqs_own_names():
    s = Settings.from_env({
        "GROQ_API_KEY": " gsk-test ", "GROQ_MODEL": "some/model", "GROQ_BASE_URL": "https://example.test/v1/",
        "GROQ_REASONING_EFFORT": "", "LEDGERSYNC_BUSINESS_NAME": "Northbridge Consulting Ltd",
    })
    assert (s.groq_api_key, s.groq_model, s.groq_base_url) == ("gsk-test", "some/model", "https://example.test/v1")
    assert (s.reasoning_effort, s.business_name) == ("", "Northbridge Consulting Ltd")   # the name it had before


def test_how_a_document_is_read_has_openrouter_names_and_still_reads_the_old_groq_ones():
    # The app runs on OpenRouter, yet the timeout on every reader call was set with GROQ_TIMEOUT.
    new = Settings.from_env({"OPENROUTER_TIMEOUT": "600", "OPENROUTER_REASONING_EFFORT": "low",
                             "OPENROUTER_MAX_IMAGES": "1"})
    assert (new.model_timeout, new.reasoning_effort, new.max_images) == (600.0, "low", 1)
    old = Settings.from_env({"GROQ_TIMEOUT": "600", "GROQ_REASONING_EFFORT": "low", "GROQ_MAX_IMAGES": "1"})
    assert old == new
    both = Settings.from_env({"OPENROUTER_TIMEOUT": "120", "GROQ_TIMEOUT": "600",
                              "OPENROUTER_REASONING_EFFORT": "", "GROQ_REASONING_EFFORT": "low"})
    assert (both.model_timeout, both.reasoning_effort) == (120.0, "")   # the new name wins, even when blank


def test_a_read_may_be_silent_200_seconds_and_take_600_in_all():
    assert (Settings.from_env({}).model_timeout, Settings.from_env({}).model_total_timeout) == (200.0, 600.0)
    s = Settings.from_env({"OPENROUTER_TIMEOUT": "90", "OPENROUTER_TOTAL_TIMEOUT": "900"})
    assert (s.model_timeout, s.model_total_timeout) == (90.0, 900.0)


def test_without_an_openrouter_key_groq_reads_the_documents():
    s = Settings.from_env({"GROQ_API_KEY": "gsk-test"})
    assert (s.provider, s.api_key, s.base_url, s.model) == (
        "Groq", "gsk-test", "https://api.groq.com/openai/v1", "qwen/qwen3.8-27b")
    assert Settings.from_env({"OPENROUTER_API_KEY": " "}).provider == "Groq"   # a blank key is no key


def test_an_openrouter_key_is_used_first_with_the_same_model():
    s = Settings.from_env({"OPENROUTER_API_KEY": " sk-or-test ", "GROQ_API_KEY": "gsk-test",
                           "GROQ_MODEL": "groq/other-model"})
    assert (s.provider, s.api_key, s.base_url, s.model) == (
        "OpenRouter", "sk-or-test", "https://openrouter.ai/api/v1", "qwen/qwen3.8-27b")


def test_openrouter_settings_use_openrouters_own_names():
    s = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_MODEL": "some/model",
                           "OPENROUTER_BASE_URL": "https://example.test/v1/", "OPENROUTER_MAX_OUTPUT_TOKENS": "16000"})
    assert (s.model, s.base_url, s.max_output_tokens) == ("some/model", "https://example.test/v1", 16000)


def test_openrouter_leaves_room_for_thinking_and_a_long_answer():
    # OpenRouter counts the thinking in the limit: a 60-row statement thought for 4,083 tokens and its
    # answer alone is about 9,000, so at Groq's 8,192 it was cut off.
    assert Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test"}).max_output_tokens == 32768
    assert Settings.from_env({"GROQ_API_KEY": "gsk-test"}).max_output_tokens == 8192   # Groq's plan limits stay


def test_openrouter_asks_a_full_precision_host_first_and_never_a_4_bit_one():
    s = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test"})
    assert s.openrouter_providers == ("deepinfra/bf16",)
    assert s.openrouter_quantizations == ("bf16", "fp16", "fp32", "fp8")
    s = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_PROVIDERS": " parasail/fp8, wafer ,",
                           "OPENROUTER_QUANTIZATIONS": " "})
    assert (s.openrouter_providers, s.openrouter_quantizations) == (("parasail/fp8", "wafer"), ())   # blank: any


def test_the_api_key_is_never_printed():
    assert "gsk-secret" not in repr(Settings(groq_api_key="gsk-secret"))
    assert "sk-or-secret" not in repr(Settings(openrouter_api_key="sk-or-secret"))


def test_env_file_values_are_used_but_real_environment_variables_win(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\n\nexport GROQ_API_KEY="gsk-from-file"\n'
                        "GROQ_MODEL='file/model'\nnot a setting\n")
    monkeypatch.setenv("GROQ_MODEL", "env/model")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = Settings.from_env(env_file=env_file)
    assert (s.groq_api_key, s.groq_model) == ("gsk-from-file", "env/model")


def test_a_missing_env_file_gives_no_values(tmp_path):
    assert read_env_file(tmp_path / "absent.env") == {}


def test_five_files_are_read_at_once_unless_set_otherwise():
    assert Settings.from_env({}).max_parallel_jobs == 5
    assert Settings.from_env({"LEDGERSYNC_MAX_PARALLEL_JOBS": "1"}).max_parallel_jobs == 1
    assert Settings.from_env({"LEDGERSYNC_MAX_PARALLEL_JOBS": "0"}).max_parallel_jobs == 1   # never below one


def test_the_mongodb_pool_is_ten_connections_unless_set_otherwise():
    assert Settings.from_env({}).mongodb_max_pool == 10
    assert Settings.from_env({"LEDGERSYNC_MONGO_MAX_POOL": "4"}).mongodb_max_pool == 4
    assert Settings.from_env({"LEDGERSYNC_MONGO_MAX_POOL": "0"}).mongodb_max_pool == 1   # never below one


def test_the_chat_takes_a_minute_an_answer_without_the_demo_unless_set_otherwise():
    d = Settings.from_env({})
    assert (d.agent_timeout, d.demo) == (60.0, False)
    chosen = Settings.from_env({"LEDGERSYNC_AGENT_TIMEOUT": "90", "LEDGERSYNC_DEMO": "1"})
    assert (chosen.agent_timeout, chosen.demo) == (90.0, True)


def test_one_model_reads_the_files_and_runs_the_chat():
    # The chat runs on OPENROUTER_MODEL through OpenRouter: the model that reads the files when OpenRouter reads them.
    d = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test"})
    assert d.openrouter_model == d.model == "qwen/qwen3.8-27b"
    chosen = Settings.from_env({"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_MODEL": " some/model "})
    assert chosen.openrouter_model == chosen.model == "some/model"


def test_the_old_agent_model_variable_changes_nothing():
    assert "LEDGERSYNC_AGENT_MODEL" not in ENV_NAMES
    assert not hasattr(Settings(), "agent_model")
    base = {"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_MODEL": "some/model"}
    assert Settings.from_env({**base, "LEDGERSYNC_AGENT_MODEL": "x/y"}) == Settings.from_env(base)
    assert Settings.from_env({**base, "LEDGERSYNC_AGENT_MODEL": "x/y"}).openrouter_model == "some/model"
    assert Settings.from_env({"LEDGERSYNC_AGENT_MODEL": "x/y"}) == Settings.from_env({})


def test_a_blank_number_setting_uses_its_default():
    blank = {name: "" for name in ("LEDGERSYNC_PORT", "LEDGERSYNC_MAX_UPLOAD_MB", "LEDGERSYNC_MAX_PDF_PAGES",
                                   "LEDGERSYNC_MAX_PARALLEL_JOBS", "OPENROUTER_MAX_OUTPUT_TOKENS", "GROQ_TIMEOUT",
                                   "GROQ_MAX_OUTPUT_TOKENS", "GROQ_MAX_IMAGES", "OPENROUTER_TIMEOUT",
                                   "OPENROUTER_MAX_IMAGES")}
    assert Settings.from_env(blank) == Settings.from_env({})
    assert Settings.from_env({"LEDGERSYNC_PORT": " 9000 "}).port == 9000


def test_env_names_are_the_variables_from_env_reads():
    source = inspect.getsource(Settings.from_env)
    read = re.findall(r'(?:env\.get\(|_number\(env, |_named\(env, )"([A-Z][A-Z0-9_]+)"', source)
    old = re.findall(r'_named\(env, "[A-Z0-9_]+", "([A-Z][A-Z0-9_]+)"\)', source)   # a setting's earlier name
    assert set(ENV_NAMES) == set(read + old)


def example_values() -> dict[str, str]:
    """NAME=value for each setting .env.example lists, commented out or not."""
    lines = (ENV_FILE.parent / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(line.lstrip("# ").split("=", 1) for line in lines if re.match(r"#? ?[A-Z][A-Z0-9_]+=", line))


def test_env_example_lists_every_setting():
    assert set(ENV_NAMES) <= set(example_values())


def test_the_defaults_in_env_example_are_the_defaults():
    assert Settings.from_env(example_values()) == Settings.from_env({})


def test_review_settings_read_from_env():
    d = Settings.from_env({})
    assert (d.review_wait_seconds, d.review_daily_limit) == (20, 20)
    s = Settings.from_env({"LEDGERSYNC_REVIEW_WAIT": "5", "LEDGERSYNC_REVIEW_DAILY_LIMIT": "3"})
    assert (s.review_wait_seconds, s.review_daily_limit) == (5, 3)
    assert {"LEDGERSYNC_REVIEW_WAIT", "LEDGERSYNC_REVIEW_DAILY_LIMIT"} <= set(ENV_NAMES)


def test_the_chat_can_run_on_another_model_than_the_one_that_reads_the_files():
    base = {"OPENROUTER_API_KEY": "sk-or-test", "OPENROUTER_MODEL": "reader/model"}
    assert Settings.from_env(base).chat_model_name == "reader/model"
    split = Settings.from_env({**base, "OPENROUTER_CHAT_MODEL": " stronger/model "})
    assert (split.model, split.chat_model_name) == ("reader/model", "stronger/model")
    assert "OPENROUTER_CHAT_MODEL" in ENV_NAMES
