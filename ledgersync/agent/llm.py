"""The chat model the accountant agent runs on: OPENROUTER_MODEL (qwen/qwen3.8-27b), the one model that also reads the
uploaded files, through OpenRouter on the same route as the reader (model_client.openrouter_route: the hosts in
OPENROUTER_PROVIDERS first, and only hosts at a precision in OPENROUTER_QUANTIZATIONS, never a 4-bit one), told besides
to use only hosts that take every parameter sent and keep none of the data."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from ledgersync.config import Settings
from ledgersync.errors import ModelUnavailable
from ledgersync.model_client import openrouter_route

# The most one answer may run to: the agent's replies are tool calls and short words, so a runaway generation is cut
# off at this many tokens (the reader's own, larger cap is OPENROUTER_MAX_OUTPUT_TOKENS, for whole documents).
AGENT_MAX_OUTPUT_TOKENS = 8192

NOT_CONFIGURED = "The accountant chat needs OPENROUTER_API_KEY. Set it in .env."


def chat_model(settings: Settings) -> BaseChatModel:
    """The agent's model: the one that reads the files (settings.openrouter_model), or OPENROUTER_CHAT_MODEL when
    that names another, which OpenRouter routes itself. On the reader's route
    (openrouter_route, with require_parameters) and data_collection denied, reasoning at medium effort. Each request
    may take settings.agent_timeout seconds (ChatOpenRouter takes milliseconds); after a 5XX answer or a lost
    connection the OpenRouter SDK tries again with backoff, for up to about five minutes (max_retries=2 gives 150
    seconds a retry), and one answer is cut off at AGENT_MAX_OUTPUT_TOKENS. Building it calls nothing;
    ModelUnavailable when OPENROUTER_API_KEY isn't set."""
    if not settings.openrouter_api_key:
        raise ModelUnavailable(NOT_CONFIGURED)
    # The hosts and precisions set are the reader's model's: another model for the chat is routed by OpenRouter.
    own = settings.chat_model_name == settings.openrouter_model
    route = openrouter_route(settings, require_parameters=True) if own else {"require_parameters": True}
    return ChatOpenRouter(model=settings.chat_model_name, api_key=settings.openrouter_api_key,
                          base_url=settings.openrouter_base_url, reasoning={"effort": "medium"},
                          openrouter_provider={**route, "data_collection": "deny"},
                          timeout=round(settings.agent_timeout * 1000), max_retries=2,
                          max_tokens=AGENT_MAX_OUTPUT_TOKENS)
