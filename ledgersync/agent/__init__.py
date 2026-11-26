"""The accountant chat's agent (design of 2026-11-02): LangChain's create_agent loop with the tools that read the books
and resolve what the evidence settles, a prompt that makes it the client's accountant, and limits on how long a run
goes. It only investigates and picks actions: the services check and make every change, and the server posts, asks
the rules' questions and builds the turn's result after each turn."""
from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelRetryMiddleware, ToolCallLimitMiddleware
from langgraph.checkpoint.mongodb import MongoDBSaver

from ledgersync.config import Settings

from .llm import chat_model
from .middleware import (ModelErrorsAsUnavailable, ReadsClientOnce, Specialists, StopWhenCancelled,
                         ToolErrorsAsMessages)
from .prompt import SYSTEM_PROMPT
from .run import ChatEvent, stream_turn
from .tools import AgentDeps, ChatContext, make_tools

__all__ = ["AgentDeps", "ChatContext", "ChatEvent", "build_agent", "stream_turn"]


def build_agent(settings: Settings, deps: AgentDeps, *, model=None, checkpointer=None):
    """The agent on `model` (by default OPENROUTER_MODEL through OpenRouter, the one model that also reads the files),
    with every tool, the system prompt and ChatContext as the run's context. Its threads' messages are kept by
    `checkpointer`: by default in MongoDB, in the database "<db>_checkpoints" on the store's one client (never a
    client of its own). A run plays the part its context names (ChatContext.specialist): the lead accountant, which is
    this whole agent, or a specialist with its own prompt and tools (specialists.py). A run:
    - stops before its next model call once deps.is_cancelled(thread_id) says so;
    - ends, with a message, before a 31st model call or when the model asks for an 81st tool call;
    - reads at most 20 documents (a call past that is answered "limit exceeded" and the run carries on);
    - retries a failing model call twice, and then raises ModelUnavailable;
    - answers a tool error (a tool that doesn't exist, arguments that don't fit, a LedgerSyncError) to the model;
    - reads the client once for each tool call, however many figures the tool works out of it."""
    if checkpointer is None:
        checkpointer = MongoDBSaver(deps.store.client, db_name=f"{deps.store.db_name}_checkpoints")
    middleware = [
        StopWhenCancelled(deps.is_cancelled),
        Specialists(),
        ModelCallLimitMiddleware(run_limit=30, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=80, exit_behavior="end"),
        ToolCallLimitMiddleware(tool_name="read_document", run_limit=20),
        # The retries' last failure is raised (by default it would end the run as if the model had answered), and
        # the middleware outside them says the model is unavailable.
        ModelErrorsAsUnavailable(settings.api_key),
        ModelRetryMiddleware(max_retries=2, on_failure="error"),
        ToolErrorsAsMessages(),
    ]
    if deps.store is not None:   # inside the errors' handling: each tool call reads the client once
        middleware.append(ReadsClientOnce(deps.store))
    return create_agent(model if model is not None else chat_model(settings),
                        make_tools(deps, actor=f"agent:{settings.chat_model_name}"), system_prompt=SYSTEM_PROMPT,
                        middleware=middleware, context_schema=ChatContext, checkpointer=checkpointer)
