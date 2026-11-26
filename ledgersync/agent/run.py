"""One turn of the chat: the person's message goes to the agent, and what it does comes back as events, as the chat
page reads them (frontend/src/lib/chat.ts): a step for each tool it runs, its reply a token at a time, and an error if
the model fails or the run hits its limits. The API (chat.py) adds the status, the result and done around them."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Iterator, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from pymongo.errors import PyMongoError

from ledgersync.errors import LedgerSyncError, ModelUnavailable

from .middleware import StopWhenCancelled
from .tools import ChatContext

logger = logging.getLogger(__name__)

# LangGraph counts each middleware hook as a step of the run: here a model call takes up to seven (two hooks before
# it, the call, three hooks after it, and the tools), so the 30 model calls the limit allows take up to 212. This is
# only a backstop: the call limits end a run first, and cleanly, with every tool call answered.
RECURSION_LIMIT = 250
# The nodes of the limits that end a run, by the start of their names, and of the stop.
_LIMITS = ("ModelCallLimitMiddleware.", "ToolCallLimitMiddleware.")
_STOP = f"{StopWhenCancelled.__name__}.before_model"


@dataclass(frozen=True)
class ChatEvent:
    """One server-sent event of a chat turn, as the chat page reads it: status {text}, step {id, text, state, file?,
    rows?, reason?} (sent again under its id as it changes), token {text}, result (a TurnResult), error {code,
    message, steps?} or done {}. data is plain JSON already: money and dates as strings."""
    type: Literal["status", "step", "token", "result", "error", "done"]
    data: dict

    def sse(self) -> str:
        """The event as SSE: its type, then its data as one line of JSON."""
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


def _error(code: str, message: str, **more) -> ChatEvent:
    return ChatEvent("error", {"code": code, "message": message, **more})


def _finished(step: dict, result: ToolMessage) -> dict:
    """A step still running once its tool has answered: done, or failed with why when the tool returned an error."""
    if result.status != "error":
        return {**step, "state": "done"}
    return {**step, "text": step["text"].rstrip("…"), "state": "failed",
            "reason": str(result.content).removeprefix("Error: ")[:300]}


STORAGE_TEXT = "The database didn't answer for a few seconds (it may have been switching servers), so I stopped."
CUT_TEXT = "My answer ran past its length limit before I did anything, so I stopped."


def _failure(exc: Exception) -> ChatEvent:
    """The error event for a run that raised. The database not answering (Atlas moves its primary now and then, for
    about ten seconds) is said as such, code storage_unavailable, so a background review tries again soon."""
    if isinstance(exc, PyMongoError):
        logger.warning("The agent's run stopped: the database didn't answer: %s", exc)
        return _error("storage_unavailable", STORAGE_TEXT)
    if isinstance(exc, ModelUnavailable):
        logger.warning("The agent's model is unavailable: %s", exc.message)
        return _error("model_unavailable", exc.message)
    if isinstance(exc, LedgerSyncError):
        return _error(exc.code, exc.message)
    logger.exception("The agent's run failed")
    return _error("agent_failed", "Something went wrong while I was working, so I stopped. The server log says what.")


class _Reply:
    """The turn's reply as it streams: each model call's words without the whitespace around them (Qwen sends "\\n\\n"
    before a tool call, and around its words), and the words of separate model calls apart by one blank line."""

    def __init__(self):
        self.sent = False     # whether any words were sent
        self._begun = False   # whether the current model call's words have begun
        self._held = ""       # whitespace after its last words, sent only if more words follow

    def start(self) -> None:
        """A new model call starts saying something."""
        self._begun, self._held = False, ""

    def add(self, text: str) -> str:
        """What to send for this piece of the current model call's reply: "" while there are no new words."""
        text = self._held + text
        if not self._begun:
            text = text.lstrip()
        words = text.rstrip()
        self._held = text[len(words):]
        if not words:
            return ""
        if not self._begun and self.sent:
            words = "\n\n" + words
        self._begun = self.sent = True
        return words


def stream_turn(agent, ctx: ChatContext, text: str, *, message_id: Optional[str] = None,
                called: Optional[set[str]] = None) -> Iterator[ChatEvent]:
    """Runs the agent on the person's message in the chat's thread (its earlier messages come from the checkpoints),
    for the context's client and year, and yields what it does:
    - a step for each tool it runs, as the tool says it (running, then done or failed); a tool call it couldn't run
      (a tool that doesn't exist, arguments that don't fit) is answered to the model and shows no step;
    - its reply, a token at a time, without the whitespace around each model call's words; the words of separate
      model calls apart by one blank line;
    - at the end, an error if the run stopped early: loop_limit at the model or tool call limit (or the recursion
      limit), with how many steps it took; model_unavailable when the model still failed after its retries; or the
      code of any other error.
    A chat asked to stop ends before its next model call, saying so. The message is kept in the thread under
    message_id (an id of its own when None), and the name of each tool the run calls is added to `called`, if given.
    As the run ends one line goes to the log: the part it played (ChatContext.specialist), whether it was handed
    over, its model calls and tool calls, and how long it took."""
    counts, started, part = {"model": 0, "tools": 0}, time.perf_counter(), getattr(ctx, "specialist", "lead")
    try:
        yield from _turn(agent, ctx, text, message_id, called, counts)
    finally:
        logger.info("A %s turn as the %s%s: %d model calls, %d tool calls, %.1f s", getattr(ctx, "trigger", "chat"),
                    part, ", handed over to the lead" if getattr(ctx, "handed_over", False) else "", counts["model"],
                    counts["tools"], time.perf_counter() - started)


def _turn(agent, ctx: ChatContext, text: str, message_id: Optional[str], called: Optional[set[str]],
          counts: dict[str, int]) -> Iterator[ChatEvent]:
    """stream_turn's run, counting its model calls and its tool calls into `counts`."""
    config = {"configurable": {"thread_id": ctx.thread_id}, "recursion_limit": RECURSION_LIMIT}
    steps: dict[str, dict] = {}
    limited = False
    garbled = False   # whether the last model message only had tool calls whose arguments weren't JSON
    cut = False       # whether the last model message ran out of its length (its thinking can use it all) and did nothing
    reply, last = _Reply(), None   # the reply so far, and the id of the model call it last came from
    try:
        for mode, chunk in agent.stream({"messages": [HumanMessage(content=text, id=message_id)]}, config,
                                        context=ctx, stream_mode=["messages", "updates", "custom"]):
            if mode == "custom" and isinstance(chunk, dict) and "step" in chunk:
                steps[chunk["step"]["id"]] = chunk["step"]
                yield ChatEvent("step", chunk["step"])
            elif mode == "messages":
                message, meta = chunk
                if meta.get("langgraph_node") == "model" and isinstance(message, AIMessage) and message.text:
                    if message.id != last:
                        reply.start()
                        last = message.id
                    if words := reply.add(message.text):
                        yield ChatEvent("token", {"text": words})
            elif mode == "updates":
                for node, update in chunk.items():
                    messages = update.get("messages", []) if isinstance(update, dict) else []
                    if node == "tools":
                        counts["tools"] += sum(isinstance(m, ToolMessage) for m in messages)
                        for result in messages:
                            if called is not None and isinstance(result, ToolMessage) and result.name:
                                called.add(result.name)
                            step = steps.get(getattr(result, "tool_call_id", None))
                            if isinstance(result, ToolMessage) and step and step["state"] == "running":
                                steps[step["id"]] = _finished(step, result)
                                yield ChatEvent("step", steps[step["id"]])
                    elif node == "model":
                        counts["model"] += 1
                        for made in (m for m in messages if isinstance(m, AIMessage)):
                            garbled = bool(made.invalid_tool_calls) and not made.tool_calls and not made.text.strip()
                            cut = (made.response_metadata.get("finish_reason") == "length" and not made.tool_calls
                                   and not made.text.strip())
                    elif node.startswith(_LIMITS) and any(isinstance(m, AIMessage) for m in messages):
                        limited = True
                    elif node == _STOP:
                        for said in (m for m in messages if isinstance(m, AIMessage)):
                            reply.start()
                            if words := reply.add(said.text):
                                yield ChatEvent("token", {"text": words})
    except GraphRecursionError:
        limited = True
    except Exception as exc:   # noqa: BLE001 - every failure ends the turn with an error event
        yield _failure(exc)
        return
    if cut and not limited:
        yield _error("cut_off", CUT_TEXT)
        return
    if garbled and not reply.sent and not limited:
        yield _error("agent_failed", "My last step came out garbled, so I stopped. Send it again.")
        return
    if limited:
        yield _error("loop_limit", f"Stopped after {len(steps)} steps, before finishing.", steps=len(steps))
