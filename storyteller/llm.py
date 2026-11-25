"""The only module that talks to the Claude API.

Every call goes through `ClaudeClient.text` (free text) or `ClaudeClient.parse` (structured
output validated into a pydantic model). Both check `stop_reason` before trusting the content,
record usage for the trace, and raise `LLMError` with a message that is safe to show a user.
"""

import logging
import os
import time
from typing import Callable, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import MODEL, ROLES

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

UsageHook = Callable[[dict], None]


class LLMError(RuntimeError):
    """A model call failed for good. `str(err)` is safe to show the user."""


class RefusalError(LLMError):
    """The model declined the request (HTTP 200 with stop_reason == "refusal")."""


class MissingAPIKeyError(LLMError):
    pass


class LLM(Protocol):
    """What the rest of the code depends on; tests swap in a scripted fake."""

    def text(self, role: str, system: str, user: str) -> str: ...

    def parse(self, role: str, system: str, user: str, schema: type[T]) -> T: ...


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise MissingAPIKeyError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")


class ClaudeClient:
    """Thin wrapper over the Anthropic SDK. The SDK already retries 429/5xx/connection errors
    with backoff (max_retries); this class adds stop-reason checks, one retry on unparseable
    structured output, and usage reporting."""

    def __init__(self, on_usage: UsageHook | None = None, max_retries: int = 3):
        require_api_key()
        self._client = anthropic.Anthropic(max_retries=max_retries)
        self._on_usage = on_usage

    def text(self, role: str, system: str, user: str) -> str:
        resp = self._call(role, system, user, schema=None)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise LLMError(f"The {role} step returned an empty reply.")
        return text

    def parse(self, role: str, system: str, user: str, schema: type[T]) -> T:
        # Structured outputs guarantee the JSON shape; a parse miss is rare, so retry once.
        for attempt in (1, 2):
            try:
                resp = self._call(role, system, user, schema=schema)
            except ValidationError as e:
                log.warning("%s: output failed validation (attempt %d): %s", role, attempt, e)
                continue
            if resp.parsed_output is not None:
                return resp.parsed_output
            log.warning("%s: no parsed output (attempt %d)", role, attempt)
        raise LLMError(f"The {role} step returned output I couldn't understand.")

    def _call(self, role: str, system: str, user: str, schema: type[BaseModel] | None):
        cfg = ROLES[role]
        kwargs = dict(
            model=MODEL,
            max_tokens=cfg.max_tokens,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": cfg.effort},
        )
        if system:  # the baseline sends no system prompt, like the original skeleton
            kwargs["system"] = system
        start = time.monotonic()
        try:
            if schema is None:
                resp = self._client.messages.create(**kwargs)
            else:
                resp = self._client.messages.parse(**kwargs, output_format=schema)
        except anthropic.AuthenticationError as e:
            raise LLMError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("The API is rate limiting us right now. Please try again in a minute.") from e
        except anthropic.APIStatusError as e:
            # Full detail goes to the operator's log; the user gets a short, actionable message.
            log.error("%s: HTTP %s request_id=%s: %s", role, e.status_code,
                      getattr(e, "request_id", None), e.message)
            if "credit balance" in str(e.message).lower():
                raise LLMError("The Anthropic account has no credit left (Plans & Billing in the console).") from e
            raise LLMError(f"The model API returned an error (HTTP {e.status_code}).") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Couldn't reach the model API. Check your connection.") from e

        if self._on_usage:
            self._on_usage({
                "role": role,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "seconds": round(time.monotonic() - start, 2),
                "stop_reason": resp.stop_reason,
            })
        # A refusal or truncation is HTTP 200; the SDK doesn't raise, so check explicitly.
        # Refusals are not retried: Haiku 5.5 has no fallback and would likely refuse again.
        if resp.stop_reason == "refusal":
            raise RefusalError("The model declined this request.")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"The {role} step ran out of room before finishing.")
        return resp
