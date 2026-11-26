"""Client for the hosted vision model, through the OpenAI-compatible chat API of OpenRouter or Groq
(settings.provider). The API key travels only in the Authorization header: it is never logged or put
into an error message."""
from __future__ import annotations

import http.client
import json
import logging
import math
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .config import Settings
from .errors import ModelError, ModelRateLimited, ModelTimeout, ModelUnavailable

logger = logging.getLogger(__name__)

USER_AGENT = "LedgerSync/0.3"   # urllib's default agent is refused by some API gateways
_STRICT_KEYWORDS = {"type", "properties", "required", "items", "enum", "anyOf", "description"}
TRANSCRIBE_RULES = ("You transcribe documents. Write out the complete text of the image, line by line, exactly as "
                    "printed: every word, number, date and amount unchanged, tables row by row with cells "
                    "separated by tabs. Add no commentary, summary or corrections.")
RATE_LIMIT_WAIT = 60.0      # most seconds one call waits out 429s before giving up
DEFAULT_RETRY_AFTER = 10.0  # when a 429 has no Retry-After header
RECHECK_FAILURE = 15.0      # a failed health check is tried again this soon (successes: settings.health_ttl)


@dataclass(frozen=True)
class ModelHealth:
    reachable: bool
    model_available: bool
    error: Optional[str] = None


class ModelAnswer(str):
    """The model's JSON text, with the host that wrote it: OpenRouter names the provider it chose, Groq hosts the
    model itself and names none."""

    def __new__(cls, text: str, host: Optional[str] = None):
        answer = super().__new__(cls, text)
        answer.host = host
        return answer


def strict_schema(schema: dict) -> dict:
    """The Pydantic JSON schema in the form strict structured outputs accept: $defs inlined,
    every object closed (additionalProperties false) with all its properties required, and
    only supported keywords kept (no titles, defaults or formats)."""
    defs = schema.get("$defs", {})

    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return convert(defs[node["$ref"].rsplit("/", 1)[-1]])
        out = {}
        for key, value in node.items():
            if key == "properties":
                out[key] = {name: convert(sub) for name, sub in value.items()}
            elif key in _STRICT_KEYWORDS:
                out[key] = convert(value)
        if out.get("type") == "object" or "properties" in out:
            out["required"] = list(out.get("properties", {}))
            out["additionalProperties"] = False
        return out

    return convert(schema)


def openrouter_route(settings: Settings, *, require_parameters: bool = False) -> dict:
    """OpenRouter's `provider` routing for the one model, shared by everything that asks it (the reader here and the
    chat agent): the hosts set are asked first (settings.openrouter_providers), and only hosts running the model at a
    precision set are used (settings.openrouter_quantizations), so never a 4-bit one; a blank setting leaves that to
    OpenRouter. With require_parameters, a host that would ignore a parameter of the request is not used."""
    route = {"require_parameters": True} if require_parameters else {}
    if settings.openrouter_providers:
        route["order"] = list(settings.openrouter_providers)
    if settings.openrouter_quantizations:
        route["quantizations"] = list(settings.openrouter_quantizations)
    return route


RUNAWAY, RUNAWAY_SPACE = "runaway", 512   # an answer stopped after this much whitespace: no JSON pads that much


def _closed(content: str) -> Optional[str]:
    """A trailed-off answer as JSON: as it stands, or with the one closing brace the model never wrote; None when
    neither parses (it stopped part way through)."""
    for text in (content.rstrip(), content.rstrip() + "}"):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            continue
    return None


class ModelClient:
    def __init__(self, settings: Settings, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._s = settings
        self._open = opener
        self._clock = clock
        self._sleep = sleep
        self._health: Optional[ModelHealth] = None
        self._health_at = 0.0
        # Uploads sent side by side all ask for health at once: one checks, the others use its answer.
        self._health_lock = threading.Lock()

    @property
    def model(self) -> str:
        return self._s.model

    @property
    def _openrouter(self) -> bool:
        return self._s.provider == "OpenRouter"

    def _setting(self, name: str) -> str:
        """The provider's own variable for a setting, e.g. OPENROUTER_API_KEY or GROQ_MODEL."""
        return f"{self._s.provider.upper()}_{name}"

    @property
    def max_images(self) -> int:
        return self._s.max_images

    def health(self, force: bool = False) -> ModelHealth:
        with self._health_lock:
            now = self._clock()
            ttl = self._s.health_ttl if self._health is not None and self._health.model_available else RECHECK_FAILURE
            if not force and self._health is not None and now - self._health_at < ttl:
                return self._health
            self._health, self._health_at = self._check(), now
            return self._health

    def ensure_available(self) -> None:
        health = self.health()
        if not health.model_available:
            raise ModelUnavailable(health.error or self._unreachable_message())

    def chat_json(self, messages: list[dict], schema: dict, images: Optional[list[str]] = None,
                  reasoning_effort: Optional[str] = None) -> ModelAnswer:
        """The model's JSON text, held to `schema` by strict structured outputs, with the host that wrote it.
        Images are base64 JPEGs (pipeline.prepare_image), added to the last message. reasoning_effort, when given,
        replaces the setting for this call (coding lines read in code needs little thinking)."""
        messages = [dict(m) for m in messages]
        if images:
            messages[-1]["content"] = [
                {"type": "text", "text": messages[-1]["content"]},
                *({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}
                  for image in images),
            ]
        # OpenRouter's providers list max_tokens among the parameters they take, not its newer name.
        max_tokens = "max_tokens" if self._openrouter else "max_completion_tokens"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            max_tokens: self._s.max_output_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "transactions", "schema": strict_schema(schema), "strict": True}},
        }
        if self._openrouter:   # streamed, so an answer that trails off into whitespace is stopped, not waited out
            payload["stream"] = True   # (_read_stream); Groq doesn't stream structured outputs
        effort = self._s.reasoning_effort if reasoning_effort is None else reasoning_effort
        if effort:
            payload["reasoning_effort"] = effort
        if self._openrouter:
            # Only to providers that honour every parameter above, the strict schema above all;
            # otherwise OpenRouter may pick one that ignores it.
            payload["provider"] = self._route(require_parameters=True)
        response = self._chat(payload)
        choice = (response.get("choices") or [{}])[0]
        if choice.get("finish_reason") == RUNAWAY:
            content = _closed((choice.get("message") or {}).get("content") or "")
            if content is None:
                raise ModelError("The AI model's answer trailed off before it was complete. Try again.",
                                 code="ai_output_invalid")
            return ModelAnswer(content, host=response.get("provider"))
        if choice.get("finish_reason") == "length":
            raise ModelError("The document is too long for the AI model to answer in one pass. "
                             "Split it into smaller files and try again.", code="ai_output_truncated")
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            raise ModelError("The AI model returned an empty answer.", code="ai_output_invalid")
        return ModelAnswer(content, host=response.get("provider"))

    def _route(self, require_parameters: bool = False) -> dict:
        """OpenRouter's routing for a read: openrouter_route(), the same the chat agent is held to."""
        return openrouter_route(self._s, require_parameters=require_parameters)

    def transcribe(self, image_b64: str) -> str:
        """Everything printed on one page image (a base64 JPEG from pipeline.prepare_image), as plain text:
        a faithful transcript, not an extraction. Raises ModelError if the model answers with nothing."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": TRANSCRIBE_RULES},
                {"role": "user", "content": [
                    {"type": "text", "text": "Transcribe this document."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]},
            ],
            "temperature": 0,
            "max_tokens" if self._openrouter else "max_completion_tokens": self._s.max_output_tokens,
        }
        if self._s.reasoning_effort:
            payload["reasoning_effort"] = self._s.reasoning_effort
        if self._openrouter and (route := self._route()):
            payload["provider"] = route   # a transcript is kept for good: not from a low-precision host
        response = self._chat(payload)
        choice = (response.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise ModelError("The page is too long for the AI model to transcribe in one pass.",
                             code="ai_output_truncated")
        content = ((choice.get("message") or {}).get("content") or "").strip()
        if not content:
            raise ModelError("The AI model returned an empty answer.", code="ai_output_invalid")
        return content

    def warm_up(self) -> None:
        """Nothing to load on a hosted model: checks the key and model once. Never raises."""
        logger.info("Documents are read by %s on %s", self.model, self._s.provider)
        try:
            self.health(force=True)
        except Exception as exc:
            logger.warning("%s check failed (%s)", self._s.provider, type(exc).__name__)

    def _check(self) -> ModelHealth:
        if not self._s.api_key:
            return ModelHealth(False, False, "Set OPENROUTER_API_KEY or GROQ_API_KEY in .env, then restart the API.")
        if self._openrouter:
            # OpenRouter's /models answers without a key, and /models/user still lists the models for a key that has
            # expired, so the header said "AI online" while every call was refused. The key's own record doesn't
            # answer for a key that is wrong or has expired. Any other trouble with it (a gateway that doesn't serve
            # it, a rate limit, no connection) is left to the listing below.
            try:
                self._request("GET", "/key", None, timeout=10)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    return ModelHealth(True, False, self._http_error(exc.code, self._detail(exc)).message)
            except Exception:   # noqa: BLE001 - the listing says whether the provider can be reached
                pass
        path = "/models/user" if self._openrouter else "/models"
        try:
            listing = self._request("GET", path, None, timeout=10)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:   # rate limited: the key works, and the next chat call waits it out
                return self._health or ModelHealth(True, True)
            return ModelHealth(True, False, self._http_error(exc.code, self._detail(exc)).message)
        except Exception as exc:
            logger.info("%s not reachable (%s)", self._s.provider, type(exc).__name__)
            return ModelHealth(False, False, self._unreachable_message())
        offered = {m.get("id") for m in listing.get("data", []) if m.get("active", True)}
        if self.model in offered:
            return ModelHealth(True, True)
        return ModelHealth(True, False, self._missing_model_message())

    def _chat(self, payload: dict) -> dict:
        """POST /chat/completions. Waits out rate limits (up to RATE_LIMIT_WAIT seconds), retries a
        dropped connection or a server error once, and turns every other failure into a typed
        error that names neither the document nor the key."""
        waited, retried = 0.0, False
        while True:
            try:
                return self._request("POST", "/chat/completions", payload, timeout=self._s.model_timeout)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    wait = self._retry_after(exc)
                    if waited + wait > RATE_LIMIT_WAIT:
                        raise ModelRateLimited(self._rate_limit_message(wait, self._detail(exc))) from None
                    logger.info("%s rate limit reached; waiting %.0f s", self._s.provider, wait)
                    self._sleep(wait)
                    waited += wait
                elif exc.code >= 500 and not retried:
                    logger.warning("%s returned HTTP %d; retrying once", self._s.provider, exc.code)
                    retried = True
                    self._sleep(1.0)
                else:
                    raise self._http_error(exc.code, self._detail(exc)) from None
            except TimeoutError:
                raise ModelTimeout(self._timeout_message()) from None
            except (urllib.error.URLError, ConnectionResetError, http.client.HTTPException) as exc:
                if isinstance(getattr(exc, "reason", None), TimeoutError):
                    raise ModelTimeout(self._timeout_message()) from None
                if retried:
                    self._health = None
                    raise ModelUnavailable(self._unreachable_message()) from None
                logger.warning("Lost the connection to %s; retrying once", self._s.provider)
                retried = True
                self._sleep(1.0)
            except json.JSONDecodeError:
                raise ModelError(f"{self._s.provider} returned a response that is not JSON.",
                                 code="ai_output_invalid") from None

    def _http_error(self, status: int, detail: str) -> Exception:
        if status in (401, 403):
            self._health = None
            if "expired" in detail.lower():   # the provider's own word for it: a new key is needed, not a check of this one
                return ModelUnavailable(f"{self._s.provider}'s API key has expired. Put a new key in "
                                        f"{self._setting('API_KEY')} in .env, then restart the API.")
            return ModelUnavailable(f"{self._s.provider} rejected the API key. "
                                    f"Check {self._setting('API_KEY')} in .env, then restart the API.")
        if status == 404:   # OpenRouter's reason can be that no host fits, e.g. the account's privacy settings
            self._health = None
            return ModelUnavailable(f"{self._missing_model_message()} ({detail})")
        lowered = detail.lower()
        if status == 413 or (status == 400 and ("context" in lowered or "reduce the length" in lowered)):
            return ModelError(f"This document is too large for {self._s.provider}'s limits on the current plan. "
                              "Split it into smaller files and try again.", code="ai_input_too_long")
        return ModelError(f"{self._s.provider} returned HTTP {status}: {detail}")

    def _detail(self, exc: urllib.error.HTTPError) -> str:
        """The provider's own error message, shortened, with the key blanked in case it is echoed."""
        raw = exc.read().decode("utf-8", "replace")
        try:
            message = str(json.loads(raw)["error"]["message"])
        except (ValueError, KeyError, TypeError):
            message = raw
        if self._s.api_key:   # blank first: shortening first could cut the key in half
            message = message.replace(self._s.api_key, "***")
        return message[:300]

    def _rate_limit_message(self, wait: float, detail: str) -> str:
        """When to try again, from Retry-After: a free plan's daily limit can be minutes or hours away."""
        minutes = max(1, math.ceil(wait / 60))
        when = ("about a minute" if minutes == 1 else f"about {minutes} minutes" if minutes < 90
                else f"about {round(minutes / 60)} hours")
        return f"{self._s.provider}'s rate limit is used up; try again in {when}. ({detail})"

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float:
        try:
            return max(1.0, float(exc.headers.get("retry-after")))
        except (AttributeError, TypeError, ValueError):
            return DEFAULT_RETRY_AFTER

    def _timeout_message(self) -> str:
        return (f"{self._s.provider} sent nothing for {self._s.model_timeout:.0f} seconds. "
                "Try again, or raise OPENROUTER_TIMEOUT.")

    def _request(self, method: str, path: str, payload: Optional[dict], timeout: float) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(f"{self._s.base_url}{path}", data=data, method=method, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._s.api_key}",
            "User-Agent": USER_AGENT,
        })
        with self._open(req, timeout=timeout) as resp:
            if payload is not None and payload.get("stream"):
                return self._read_stream(resp)
            return json.loads(resp.read())

    def _read_stream(self, resp) -> dict:
        """A streamed chat completion put together as an unstreamed one is: its content, finish_reason, host and usage.
        Read line by line, so it stops early: once the content ends in more than RUNAWAY_SPACE characters of
        whitespace (a model that has finished its JSON but not closed it can write nothing else to the token cap;
        finish_reason RUNAWAY), and once the whole answer has taken longer than model_total_timeout. Silence is
        the connection's own timeout (model_timeout), between one piece and the next."""
        started, parts, finish, provider, usage, space = self._clock(), [], None, None, None, 0
        for raw in resp:
            if self._clock() - started > self._s.model_total_timeout:
                raise ModelTimeout(f"{self._s.provider} had not finished reading the document after "
                                   f"{self._s.model_total_timeout:.0f} seconds. Try again, or raise "
                                   "OPENROUTER_TOTAL_TIMEOUT.")
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            provider, usage = chunk.get("provider") or provider, chunk.get("usage") or usage
            choice = (chunk.get("choices") or [{}])[0]
            piece = (choice.get("delta") or {}).get("content") or ""
            parts.append(piece)
            space = space + len(piece) if not piece.strip() else len(piece) - len(piece.rstrip())
            finish = choice.get("finish_reason") or finish
            if space > RUNAWAY_SPACE:
                finish = RUNAWAY
                break
        return {"choices": [{"message": {"content": "".join(parts)}, "finish_reason": finish}],
                "provider": provider, "usage": usage}

    def _unreachable_message(self) -> str:
        return (f"Cannot reach {self._s.provider} at {self._s.base_url}. "
                "Check the internet connection, then try again.")

    def _missing_model_message(self) -> str:
        return (f"{self._s.provider} does not offer the model '{self.model}'. "
                f"Check {self._setting('MODEL')} in .env, then restart the API.")
