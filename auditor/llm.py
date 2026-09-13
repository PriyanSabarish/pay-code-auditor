"""Thin Groq wrapper for the model cascade (spec section 7, adapted to Groq-only).

Bulk classification uses a fast, low-cost model; escalated codes, the investigator agent,
the verifier and the remediation writer use a stronger model. Both tiers are configurable
via env vars so the lineup can change without touching call sites.

Every call returns its token counts and latency: two of the reported evaluation metrics
(cost and time per audit) need measured numbers, and adding the counters later would mean
re-running everything.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal, Optional

from dotenv import load_dotenv
from groq import BadRequestError, Groq, RateLimitError

load_dotenv()

ModelTier = Literal["fast", "strong"]

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_STRONG_MODEL = "openai/gpt-oss-120b"

# The Groq SDK already retries a couple of times internally, but a real audit can sustain
# enough back-to-back strong-tier calls (investigation + verifier, several steps each) to
# burn through a low free-tier tokens-per-minute cap for longer than that covers — this
# is the extra patience layer so a burst of investigated codes doesn't just crash the
# audit outright. 8000 TPM on the on_demand tier is genuinely easy to hit in "full" mode.
MAX_RATE_LIMIT_RETRIES = 5


@dataclass
class ToolCall:
    """One function call the model asked for, arguments already JSON-decoded."""

    id: str
    name: str
    arguments: dict


@dataclass
class CompletionResult:
    """One LLM call's output plus what it cost, for the evaluation's cost/latency metrics."""

    text: str
    tier: ModelTier
    model: str
    latency_seconds: float
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    tool_calls: list[ToolCall] = field(default_factory=list)


def _recover_failed_generation(exc: BadRequestError) -> Optional[str]:
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
    if error.get("code") != "tool_use_failed":
        return None
    failed_generation = error.get("failed_generation")
    if not failed_generation:
        return None
    # failed_generation is usually {"name": "json", "arguments": {...}} as text; if the
    # model's actual JSON is nested under "arguments", unwrap it so callers that expect
    # this to look like a normal text completion get the real payload, not the wrapper.
    try:
        parsed = json.loads(failed_generation)
        if isinstance(parsed, dict) and "arguments" in parsed:
            return json.dumps(parsed["arguments"])
    except json.JSONDecodeError:
        pass
    return failed_generation


def model_for_tier(tier: ModelTier) -> str:
    if tier == "fast":
        return os.getenv("GROQ_FAST_MODEL", DEFAULT_FAST_MODEL)
    if tier == "strong":
        return os.getenv("GROQ_STRONG_MODEL", DEFAULT_STRONG_MODEL)
    raise ValueError(f"unknown model tier: {tier!r}")


@lru_cache(maxsize=1)
def get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    return Groq(api_key=api_key)


def _seconds_until_retry(exc: RateLimitError, default: float) -> float:
    headers = getattr(exc.response, "headers", None) if getattr(exc, "response", None) else None
    if headers is not None:
        retry_ms = headers.get("retry-after-ms")
        if retry_ms is not None:
            try:
                return max(float(retry_ms) / 1000, 0.0)
            except ValueError:
                pass
        retry_seconds = headers.get("retry-after")
        if retry_seconds is not None:
            try:
                return max(float(retry_seconds), 0.0)
            except ValueError:
                pass
    return default


def complete(
    messages: list[dict],
    *,
    tier: ModelTier = "fast",
    temperature: float = 0.0,
    **kwargs,
) -> CompletionResult:
    """Run one chat completion on the given cascade tier, timed and token-counted."""

    client = get_client()
    model = model_for_tier(tier)

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        start = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                **kwargs,
            )
        except BadRequestError as exc:
            # Some tool-calling turns make gpt-oss models emit a synthetic "json" tool
            # call instead of plain text when they want to return structured output —
            # Groq rejects that server-side as a hard 400 before we see a normal
            # response at all. The JSON it tried to emit survives in the error body's
            # failed_generation, so recover it as plain text rather than letting a
            # model quirk crash the caller.
            recovered = _recover_failed_generation(exc)
            if recovered is None:
                raise
            latency = time.perf_counter() - start
            return CompletionResult(
                text=recovered, tier=tier, model=model, latency_seconds=latency,
                prompt_tokens=None, completion_tokens=None, total_tokens=None,
            )
        except RateLimitError as exc:
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            # Add a small buffer on top of Groq's own suggested wait — retrying at
            # exactly the boundary tends to just hit the limit again.
            wait_seconds = _seconds_until_retry(exc, default=2.0 * (attempt + 1)) + 0.25
            reason = getattr(exc, "message", None) or str(exc)
            print(
                f"[llm] rate limited on {tier} tier ({model}), retry {attempt + 1}/{MAX_RATE_LIMIT_RETRIES} "
                f"in {wait_seconds:.1f}s — {reason}",
                flush=True,
            )
            time.sleep(wait_seconds)
            continue

        latency = time.perf_counter() - start
        usage = getattr(response, "usage", None)
        message = response.choices[0].message

        tool_calls = []
        for raw_call in message.tool_calls or []:
            try:
                arguments = json.loads(raw_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(ToolCall(id=raw_call.id, name=raw_call.function.name, arguments=arguments))

        return CompletionResult(
            text=message.content or "",
            tier=tier,
            model=model,
            latency_seconds=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            total_tokens=getattr(usage, "total_tokens", None) if usage else None,
            tool_calls=tool_calls,
        )

    raise AssertionError("unreachable")  # pragma: no cover
