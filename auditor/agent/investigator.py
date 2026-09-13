"""The bounded, tool-using investigator (spec section 6.3) — the centrepiece.

For each suspicious code the classifier couldn't confidently resolve, this drives a real
Groq function-calling loop: the model picks a tool, the tool runs, the result feeds back,
and the model decides what to do next — until it concludes, asks the bookkeeper, or hits
the step cap.

The six-step cap is enforced by the `for` loop below, not by anything in the prompt. A
model that ignores its instructions and tries to keep going past step 6 simply can't —
the loop stops calling it. Every step, valid or not, becomes exactly one InvestigationStep
in this shape (frozen, per auditor/schemas.py — IT has been rendering this since hour 7):
    {step_number, tool, input, output, citation}
Announce it in the team channel before changing any of those field names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import ValidationError

from .. import llm
from ..classify import _extract_json  # shared JSON-fence stripping, not worth duplicating
from ..prompts import (
    INVESTIGATOR_CONCLUSION_RETRY_SUFFIX,
    INVESTIGATOR_SYSTEM_PROMPT,
    INVESTIGATOR_USER_TEMPLATE,
)
from ..schemas import (
    Classification,
    ClarifyingQuestion,
    InvestigationStep,
    PayCode,
    PayRunRow,
)
from . import tools as agent_tools
from .tools import TOOL_NAMES, ToolResult

MAX_STEPS = 6

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_payment_history",
            "description": (
                "Get how this pay code has actually been paid, from the uploaded pay run "
                "data: amounts, frequency, number of employees, and any overtime hours "
                "recorded alongside it. Takes no arguments — it's always about the code "
                "under investigation."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ato_guidance",
            "description": "Search the ATO qualifying earnings guidance for passages relevant to a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "e.g. 'on-call allowance outside ordinary hours'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_award",
            "description": "Search the business's award for clauses relevant to a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_impact",
            "description": (
                "Calculate the exact annual dollar impact once you've decided the "
                "direction of the error. You don't supply any numbers — it re-derives "
                "the amounts itself from the pay run data. Only call this after you've "
                "decided the code is actually misconfigured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["should_count_not_counted", "counts_should_not"],
                        "description": (
                            "should_count_not_counted: should count towards super but is "
                            "currently excluded. counts_should_not: currently counts but "
                            "shouldn't."
                        ),
                    }
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_bookkeeper",
            "description": (
                "Pause the investigation and ask the bookkeeper one specific, answerable "
                "question. Use this only when the payment history and guidance genuinely "
                "cannot resolve the ambiguity between them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "context": {
                        "type": "string",
                        "description": "One sentence on why this distinction matters.",
                    },
                },
                "required": ["question"],
            },
        },
    },
]


@dataclass
class InvestigationOutcome:
    steps: list[InvestigationStep] = field(default_factory=list)
    status: Literal["complete", "awaiting_input", "step_limit_reached"] = "complete"
    pending_question: Optional[ClarifyingQuestion] = None
    conclusion: Optional[Classification] = None
    calls: list[llm.CompletionResult] = field(default_factory=list)


def _execute_tool(name: str, arguments: dict, *, pay_code: PayCode, payruns: list[PayRunRow]) -> ToolResult:
    if name == "get_payment_history":
        return agent_tools.get_payment_history(pay_code.code, payruns)
    if name == "search_ato_guidance":
        return agent_tools.search_ato_guidance(arguments.get("query", pay_code.name))
    if name == "search_award":
        return agent_tools.search_award(arguments.get("query", pay_code.name))
    if name == "calculate_impact":
        return agent_tools.calculate_impact(pay_code.code, arguments["direction"], payruns)
    if name == "ask_bookkeeper":
        return agent_tools.ask_bookkeeper(pay_code.code, arguments["question"], arguments.get("context"))
    raise ValueError(f"unknown tool: {name!r}")


def _tool_call_message(tool_call: llm.ToolCall) -> dict:
    entry = {
        "id": tool_call.id,
        "type": "function",
        "function": {"name": tool_call.name, "arguments": json.dumps(tool_call.arguments)},
    }
    if tool_call.thought_signature is not None:
        # Gemini-only — see llm.ToolCall.thought_signature. Groq's ToolCall never sets
        # this, so this key simply never appears when running against Groq.
        entry["thought_signature"] = tool_call.thought_signature
    return {"role": "assistant", "tool_calls": [entry]}


def _tool_result_message(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _rebuild_messages(
    pay_code: PayCode,
    classification: Classification,
    steps: list[InvestigationStep],
    resume_answer: Optional[str],
) -> list[dict]:
    """Replay prior steps as conversation history so a resumed investigation has full
    context — including the answer to the question it paused on."""

    messages = [
        {
            "role": "system",
            "content": INVESTIGATOR_SYSTEM_PROMPT.format(
                code=pay_code.code, name=pay_code.name, steps_remaining=MAX_STEPS
            ),
        },
        {
            "role": "user",
            "content": INVESTIGATOR_USER_TEMPLATE.format(
                code=pay_code.code,
                name=pay_code.name,
                description=pay_code.description or "(none given)",
                current_setting="Y" if pay_code.counts_for_super == "Y" else "N",
                counts_towards_super=classification.counts_towards_super,
                confidence=classification.confidence,
                reasoning=classification.reasoning,
            ),
        },
    ]
    for i, step in enumerate(steps):
        synthetic_id = f"step-{i + 1}"
        synthetic_call = llm.ToolCall(id=synthetic_id, name=step.tool, arguments=step.input)
        messages.append(_tool_call_message(synthetic_call))
        is_last_and_paused = i == len(steps) - 1 and step.tool == "ask_bookkeeper"
        content = resume_answer if (is_last_and_paused and resume_answer is not None) else step.output
        messages.append(_tool_result_message(synthetic_id, content))
    return messages


def _parse_conclusion(
    pay_code: PayCode, messages: list[dict], text: str
) -> tuple[Classification, list[llm.CompletionResult]]:
    """Validate the model's final JSON, retrying once with the error appended — mirrors
    classify.py's retry-once-then-unclear pattern, just without a tier escalation (the
    investigator already runs on the strong tier)."""

    extra_calls: list[llm.CompletionResult] = []
    for attempt in range(2):
        try:
            payload = json.loads(_extract_json(text))
            payload["code"] = pay_code.code
            return Classification.model_validate(payload), extra_calls
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                fallback = Classification(
                    code=pay_code.code,
                    normalised_name=pay_code.name,
                    ato_category="unresolved_parse_error",
                    counts_towards_super="unclear",
                    confidence="low",
                    citations=[],
                    reasoning=(
                        "The investigator's conclusion could not be validated after one "
                        f"retry ({exc}); this code needs manual review."
                    ),
                    question_for_reviewer="This code needs manual review — the investigator could not produce a valid conclusion.",
                )
                return fallback, extra_calls
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": INVESTIGATOR_CONCLUSION_RETRY_SUFFIX.format(validation_error=str(exc))},
            ]
            result = llm.complete(messages, tier="strong", temperature=0.0, tools=TOOL_SCHEMAS, tool_choice="auto")
            extra_calls.append(result)
            text = result.text
    raise AssertionError("unreachable")  # pragma: no cover


def investigate(
    pay_code: PayCode,
    payruns: list[PayRunRow],
    classification: Classification,
    *,
    resume_steps: Optional[list[InvestigationStep]] = None,
    resume_answer: Optional[str] = None,
) -> InvestigationOutcome:
    """Run (or resume) a bounded investigation of one code.

    Fresh call: resume_steps=None. Resuming after ask_bookkeeper: pass back the steps
    from the paused InvestigationOutcome plus the bookkeeper's answer text.
    """

    steps = list(resume_steps or [])
    messages = _rebuild_messages(pay_code, classification, steps, resume_answer)
    calls: list[llm.CompletionResult] = []

    for _ in range(MAX_STEPS - len(steps)):
        step_number = len(steps) + 1
        print(f"[investigator] {pay_code.code}: step {step_number}/{MAX_STEPS} — calling model...", flush=True)
        result = llm.complete(messages, tier="strong", temperature=0.0, tools=TOOL_SCHEMAS, tool_choice="auto")
        calls.append(result)

        if not result.tool_calls:
            print(f"[investigator] {pay_code.code}: step {step_number} — model concluded, validating...", flush=True)
            conclusion, extra_calls = _parse_conclusion(pay_code, messages, result.text)
            calls.extend(extra_calls)
            return InvestigationOutcome(steps=steps, status="complete", conclusion=conclusion, calls=calls)

        tool_call = result.tool_calls[0]

        if tool_call.name not in TOOL_NAMES:
            print(f"[investigator] {pay_code.code}: step {step_number} — unknown tool {tool_call.name!r}, retrying", flush=True)
            messages.append(_tool_call_message(tool_call))
            messages.append(
                _tool_result_message(tool_call.id, f"Unknown tool {tool_call.name!r}. Choose one of: {TOOL_NAMES}.")
            )
            continue

        print(f"[investigator] {pay_code.code}: step {step_number} -> tool={tool_call.name} args={tool_call.arguments}", flush=True)
        tool_result = _execute_tool(tool_call.name, tool_call.arguments, pay_code=pay_code, payruns=payruns)
        steps.append(
            InvestigationStep(
                step_number=step_number,
                tool=tool_call.name,
                input=tool_call.arguments,
                output=tool_result.summary,
                citation=tool_result.citation,
            )
        )

        if tool_call.name == "ask_bookkeeper":
            question: ClarifyingQuestion = tool_result.data
            print(f"[investigator] {pay_code.code}: step {step_number} — pausing for bookkeeper answer", flush=True)
            return InvestigationOutcome(
                steps=steps, status="awaiting_input", pending_question=question, calls=calls
            )

        messages.append(_tool_call_message(tool_call))
        messages.append(_tool_result_message(tool_call.id, tool_result.summary))

    print(f"[investigator] {pay_code.code}: hit the {MAX_STEPS}-step limit without concluding", flush=True)

    forced_unclear = Classification(
        code=pay_code.code,
        normalised_name=pay_code.name,
        ato_category="step_limit_reached",
        counts_towards_super="unclear",
        confidence="low",
        citations=[],
        reasoning=(
            f"The investigation used its full {MAX_STEPS}-step budget without reaching a "
            "clear conclusion; this needs manual review rather than a guess."
        ),
        question_for_reviewer="This code needs manual review — the investigation ran out of steps before concluding.",
    )
    return InvestigationOutcome(steps=steps, status="step_limit_reached", conclusion=forced_unclear, calls=calls)
