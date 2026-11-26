"""Test doubles shared by the test modules."""
import email.message
import io
import json
import urllib.error

from ledgersync.errors import ModelUnavailable
from ledgersync.model_client import ModelHealth

OFFLINE = "Cannot reach Groq at https://api.groq.com/openai/v1. Check the internet connection, then try again."

ROW = {"description": "BT Business Broadband", "date": "2026-09-01", "amount": 72.0, "direction": "out",
       "account": "7502 Telephone and Internet", "vat": None, "currency": "GBP"}


def transactions_json(*rows: dict) -> str:
    return json.dumps({"transactions": list(rows)})


def as_coding(reply):
    """A reader's answer (a "transactions" list) as the answer to coding a statement read in code (a "lines" list):
    the same accounts and payees, line by line. A reply already in that shape is left as it is."""
    try:
        parsed = json.loads(reply)
    except (TypeError, ValueError):
        return reply
    if not isinstance(parsed, dict) or "transactions" not in parsed:
        return reply
    return json.dumps({"lines": [{"n": n, "account": t.get("account", "9998"), "counterparty": t.get("counterparty"),
                                  "alternatives": t.get("alternatives", []), "bought": t.get("bought"),
                                  "people": t.get("people")}
                                 for n, t in enumerate(parsed["transactions"], start=1)]})


class FakeModel:
    """Stands in for ModelClient: chat_json returns (or raises) `replies` in order."""

    model = "fake-model"
    max_images = 3

    def __init__(self, replies=(), healthy: bool = True):
        self.replies = list(replies)
        self.healthy = healthy
        self.calls: list[dict] = []

    def health(self, force: bool = False) -> ModelHealth:
        return ModelHealth(True, True) if self.healthy else ModelHealth(False, False, OFFLINE)

    def ensure_available(self) -> None:
        if not self.healthy:
            raise ModelUnavailable(OFFLINE)

    def chat_json(self, messages, schema, images=None, reasoning_effort=None) -> str:
        self.calls.append({"messages": messages, "schema": schema, "images": images,
                           "reasoning_effort": reasoning_effort})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return as_coding(reply) if "lines" in schema.get("properties", {}) else reply

    def warm_up(self) -> None:
        pass



class FakeUrlopen:
    """Stands in for urllib.request.urlopen: returns (as JSON) or raises scripted outcomes in order."""

    def __init__(self, *outcomes):
        self.outcomes, self.requests = list(outcomes), []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, _Stream) or (req.data and json.loads(req.data).get("stream") and "choices" in outcome):
            return outcome if isinstance(outcome, _Stream) else _Stream.of(outcome)
        return _JsonResponse(outcome)

    def payload(self, n: int = -1) -> dict:
        return json.loads(self.requests[n][0].data)


class _JsonResponse:
    def __init__(self, body: dict):
        self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Stream:
    """A chat completion as server-sent events, one line at a time, as a streamed answer arrives; `read_lines` counts
    the lines the client took, so a test can see it stopped early."""
    def __init__(self, lines: list[bytes]):
        self._lines, self.read_lines = lines, 0

    @classmethod
    def of(cls, answer: dict, piece: int = 8) -> "_Stream":
        choice = answer["choices"][0]
        content = choice["message"]["content"]
        chunks = [{"choices": [{"index": 0, "delta": {"content": content[i:i + piece]}}]}
                  for i in range(0, len(content), piece)] or [{"choices": [{"index": 0, "delta": {}}]}]
        chunks[-1]["choices"][0]["finish_reason"] = choice.get("finish_reason")
        for chunk in chunks:
            if answer.get("provider"):
                chunk["provider"] = answer["provider"]
        return cls([f"data: {json.dumps(c)}\n".encode() for c in chunks] + [b"data: [DONE]\n"])

    def __iter__(self):
        for line in self._lines:
            self.read_lines += 1
            yield line

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def streamed(*pieces: str, finish_reason=None) -> _Stream:
    """An answer streamed in these pieces, ending with finish_reason (None: the stream is cut before it ends)."""
    chunks = [{"choices": [{"index": 0, "delta": {"content": p}}]} for p in pieces]
    if finish_reason:
        chunks[-1]["choices"][0]["finish_reason"] = finish_reason
    return _Stream([f"data: {json.dumps(c)}\n".encode() for c in chunks] + [b"data: [DONE]\n"])


def http_error(code: int, message: str = "failed", retry_after=None) -> urllib.error.HTTPError:
    """An HTTP error as OpenAI-compatible providers send it: {"error": {"message", "type"}}."""
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    body = json.dumps({"error": {"message": message, "type": "invalid_request_error"}}).encode()
    return urllib.error.HTTPError("https://api.example.test", code, message, headers, io.BytesIO(body))


def chat_answer(content: str = '{"transactions": []}', finish_reason: str = "stop", provider=None) -> dict:
    """A chat completion; OpenRouter's also names the provider that wrote it."""
    answer = {"choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                           "finish_reason": finish_reason}]}
    return {**answer, "provider": provider} if provider else answer
