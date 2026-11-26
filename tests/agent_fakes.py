"""A scripted chat model for the agent's tests: it answers each call with the next reply it was given, and never calls
a real model."""
from __future__ import annotations

from typing import Any, Callable, Union
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

# A reply: the message to answer with, an exception to raise, or a function of the messages the call was given that
# returns either.
Reply = Union[AIMessage, Exception, Callable[[list[BaseMessage]], Union[AIMessage, Exception]]]


def call(name: str, **args: Any) -> AIMessage:
    """A reply that calls one tool, with a fresh call id."""
    return calls((name, args))


def calls(*named: tuple[str, dict]) -> AIMessage:
    """A reply that calls several tools at once, each with a fresh call id."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid4().hex[:12]}",
                                              "type": "tool_call"} for name, args in named])


def say(text: str) -> AIMessage:
    """A reply in words, which ends the run."""
    return AIMessage(content=text)


class ScriptedChatModel(BaseChatModel):
    """Answers call n with replies[n]; past the end, with `then` if given (a reply for every further call), or else an
    error. `seen` keeps the messages each call was given, `tools` the names of the tools it was offered."""

    replies: list = Field(default_factory=list)
    then: Any = None
    seen: list = Field(default_factory=list)
    tools: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.tools = [getattr(t, "name", None) or t.get("name") for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        n = len(self.seen) - 1
        if n < len(self.replies):
            reply = self.replies[n]
        elif self.then is not None:
            reply = self.then
        else:
            raise AssertionError(f"The script has no reply for call {n + 1}.")
        if callable(reply) and not isinstance(reply, (AIMessage, Exception)):
            reply = reply(list(messages))
        if isinstance(reply, Exception):
            raise reply
        message = reply.model_copy(update={"id": f"scripted-{uuid4().hex[:12]}"})
        return ChatResult(generations=[ChatGeneration(message=message)])
