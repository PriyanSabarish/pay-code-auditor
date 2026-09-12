"""Thin Groq wrapper for the model cascade (spec section 7, adapted to Groq-only).

Bulk classification uses a fast, low-cost model; escalated codes, the investigator agent,
the verifier and the remediation writer use a stronger model. Both tiers are configurable
via env vars so the lineup can change without touching call sites.

Every call returns its token counts and latency: two of the reported evaluation metrics
(cost and time per audit) need measured numbers, and adding the counters later would mean
re-running everything.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

ModelTier = Literal["fast", "strong"]

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_STRONG_MODEL = "openai/gpt-oss-120b"


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
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    latency = time.perf_counter() - start
    usage = getattr(response, "usage", None)
    return CompletionResult(
        text=response.choices[0].message.content or "",
        tier=tier,
        model=model,
        latency_seconds=latency,
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        total_tokens=getattr(usage, "total_tokens", None) if usage else None,
    )
