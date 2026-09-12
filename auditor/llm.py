"""Thin Groq wrapper for the model cascade (spec section 7, adapted to Groq-only).

Bulk classification uses a fast, low-cost model; escalated codes, the investigator agent,
the verifier and the remediation writer use a stronger model. Both tiers are configurable
via env vars so the lineup can change without touching call sites.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

ModelTier = Literal["fast", "strong"]

DEFAULT_FAST_MODEL = "openai/gpt-oss-20b"
DEFAULT_STRONG_MODEL = "openai/gpt-oss-120b"


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
) -> str:
    """Run one chat completion on the given cascade tier and return the text content."""

    client = get_client()
    response = client.chat.completions.create(
        model=model_for_tier(tier),
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    return response.choices[0].message.content or ""
