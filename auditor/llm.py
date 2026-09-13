"""LLM wrapper for the model cascade (spec section 7), supporting Groq or Gemini behind
one interface, selected by the LLM_PROVIDER env var ("groq", the default, or "gemini").

Bulk classification uses a fast, low-cost model; escalated codes, the investigator agent,
the verifier and the remediation writer use a stronger model. Both tiers are configurable
via env vars so the lineup can change without touching call sites.

Every call returns its token counts and latency: two of the reported evaluation metrics
(cost and time per audit) need measured numbers, and adding the counters later would mean
re-running everything.

Every call site (classify.py, verifier.py, remediation.py, investigator.py) only ever
talks to `complete()`, passing OpenAI-shaped `messages` and, for the investigator,
OpenAI-shaped `tools`/`tool_choice`. That's deliberate: it means switching providers is
contained entirely to this file — the translation to Gemini's `contents`/`FunctionDeclaration`
shape happens here, once, rather than at every call site.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from groq import BadRequestError, Groq, RateLimitError

load_dotenv()

ModelTier = Literal["fast", "strong"]

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_STRONG_MODEL = "openai/gpt-oss-120b"
# gemini-flash-latest had a free-tier quota of only 20 requests/day on the key this was
# verified against (Pro-tier models had 0); gemini-3.1-flash-lite had 500/day instead, so
# despite the name it's the default for both tiers. Verify current numbers yourself at
# https://ai.dev/rate-limit before relying on this — Gemini's lineup and quotas both move
# fast, and this was picked from one live check, not a stable published guarantee.
DEFAULT_GEMINI_FAST_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GEMINI_STRONG_MODEL = "gemini-3.1-flash-lite"

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
    if LLM_PROVIDER == "gemini":
        if tier == "fast":
            return os.getenv("GEMINI_FAST_MODEL", DEFAULT_GEMINI_FAST_MODEL)
        if tier == "strong":
            return os.getenv("GEMINI_STRONG_MODEL", DEFAULT_GEMINI_STRONG_MODEL)
        raise ValueError(f"unknown model tier: {tier!r}")
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


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Get a key from https://aistudio.google.com/apikey.")
    return genai.Client(api_key=api_key)


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


def _to_gemini_contents(messages: list[dict]) -> tuple[Optional[str], list[genai_types.Content]]:
    """Splits OpenAI-shaped messages into Gemini's (system_instruction, contents).

    Gemini has no "system" or "tool" role: a system prompt is a separate config field,
    not a message, and a tool's result goes back as a function_response part on a "user"
    turn rather than its own role. Tool-call ids are OpenAI's mechanism for matching a
    call to its result — Gemini doesn't need them (it correlates by turn order), so they
    only need to survive long enough here to attach the right function *name* to each
    result; they're discarded once translated.
    """

    system_instruction: Optional[str] = None
    contents: list[genai_types.Content] = []
    call_names: dict[str, str] = {}

    for message in messages:
        role = message["role"]
        if role == "system":
            system_instruction = message["content"]
        elif role == "user":
            contents.append(genai_types.Content(role="user", parts=[genai_types.Part(text=message["content"])]))
        elif role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls:
                parts = []
                for call in tool_calls:
                    call_names[call["id"]] = call["function"]["name"]
                    raw_args = call["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    parts.append(genai_types.Part(function_call=genai_types.FunctionCall(
                        id=call["id"], name=call["function"]["name"], args=args,
                    )))
                contents.append(genai_types.Content(role="model", parts=parts))
            else:
                contents.append(genai_types.Content(role="model", parts=[genai_types.Part(text=message.get("content") or "")]))
        elif role == "tool":
            call_id = message["tool_call_id"]
            contents.append(genai_types.Content(role="user", parts=[genai_types.Part(function_response=genai_types.FunctionResponse(
                id=call_id, name=call_names.get(call_id, ""), response={"result": message["content"]},
            ))]))
        else:
            raise ValueError(f"unsupported message role for gemini: {role!r}")
    return system_instruction, contents


def _to_gemini_tool(tools: list[dict]) -> genai_types.Tool:
    declarations = [
        genai_types.FunctionDeclaration(
            name=tool["function"]["name"],
            description=tool["function"].get("description", ""),
            parameters_json_schema=tool["function"].get("parameters"),
        )
        for tool in tools
    ]
    return genai_types.Tool(function_declarations=declarations)


_TOOL_CHOICE_TO_GEMINI_MODE = {"auto": "AUTO", "none": "NONE", "required": "ANY"}


def _complete_gemini(
    messages: list[dict],
    tier: ModelTier,
    temperature: float,
    *,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = None,
    **_ignored: Any,
) -> CompletionResult:
    client = get_gemini_client()
    model = model_for_tier(tier)
    system_instruction, contents = _to_gemini_contents(messages)

    config_kwargs: dict[str, Any] = {"temperature": temperature}
    if system_instruction:
        config_kwargs["system_instruction"] = system_instruction
    if tools:
        config_kwargs["tools"] = [_to_gemini_tool(tools)]
        mode = _TOOL_CHOICE_TO_GEMINI_MODE.get(tool_choice or "auto", "AUTO")
        config_kwargs["tool_config"] = genai_types.ToolConfig(
            function_calling_config=genai_types.FunctionCallingConfig(mode=mode)
        )
    config = genai_types.GenerateContentConfig(**config_kwargs)

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        start = time.perf_counter()
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except genai_errors.APIError as exc:
            # 429 (quota) and 5xx (e.g. "model experiencing high demand") are both
            # transient-worth-retrying; anything else (400 bad request, etc.) is not.
            # Gemini's errors don't reliably carry a retry-after value the way Groq's
            # do, so this is a plain exponential backoff rather than a precise wait.
            if (exc.code != 429 and exc.code < 500) or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            wait_seconds = 2.0 * (attempt + 1)
            print(
                f"[llm] rate limited on {tier} tier ({model}), retry {attempt + 1}/{MAX_RATE_LIMIT_RETRIES} "
                f"in {wait_seconds:.1f}s — {exc.message}",
                flush=True,
            )
            time.sleep(wait_seconds)
            continue

        latency = time.perf_counter() - start
        usage = response.usage_metadata
        candidate = response.candidates[0] if response.candidates else None

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        if candidate is not None and candidate.content is not None and candidate.content.parts:
            for i, part in enumerate(candidate.content.parts):
                if part.function_call is not None:
                    call = part.function_call
                    tool_calls.append(ToolCall(id=call.id or f"call_{i}", name=call.name, arguments=dict(call.args or {})))
                elif part.text:
                    text_parts.append(part.text)

        return CompletionResult(
            text="".join(text_parts),
            tier=tier,
            model=model,
            latency_seconds=latency,
            prompt_tokens=getattr(usage, "prompt_token_count", None) if usage else None,
            completion_tokens=getattr(usage, "candidates_token_count", None) if usage else None,
            total_tokens=getattr(usage, "total_token_count", None) if usage else None,
            tool_calls=tool_calls,
        )

    raise AssertionError("unreachable")  # pragma: no cover


def complete(
    messages: list[dict],
    *,
    tier: ModelTier = "fast",
    temperature: float = 0.0,
    **kwargs,
) -> CompletionResult:
    """Run one chat completion on the given cascade tier, timed and token-counted.
    Dispatches to Groq or Gemini per LLM_PROVIDER — see the module docstring."""

    if LLM_PROVIDER == "gemini":
        return _complete_gemini(messages, tier, temperature, **kwargs)
    return _complete_groq(messages, tier, temperature, **kwargs)


def _complete_groq(
    messages: list[dict],
    tier: ModelTier,
    temperature: float,
    **kwargs: Any,
) -> CompletionResult:
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
