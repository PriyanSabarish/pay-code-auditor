"""Prompt templates. Kept as module-level constants so diffs stay readable — one prompt
changes, one line changes.

There is no retrieval yet (that's retrieval.py, hours 7-10), so the classification prompt
carries QE_RULES_SUMMARY as its grounding for now — a static digest of the ATO's qualifying
earnings table (spec section 8). Once retrieval.py exists, the caller can additionally pass
real cited passages in `context`; the summary stays as a fallback so the prompt still makes
sense with no retrieval at all (the "no_rag" eval baseline just omits it).
"""

from __future__ import annotations

QE_RULES_SUMMARY = """\
Counts towards super:
- Ordinary hours wages and salary, including daily rates and flexi-time
- Casual loading
- Shift penalties, including public holiday penalties, for ordinary hours
- Piece rates for ordinary hours
- Paid annual leave, sick leave, long service leave (except portable long service leave schemes)
- All commissions, including commissions for work entirely outside ordinary hours
- Bonuses for ordinary hours work (performance, Christmas, sign-on, referral)
- Task, skill, higher duties, leading hand, first aid, supervisor allowances
- Allowances for adverse working conditions (heat, heights, confined spaces)
- Expense allowances paid regardless of whether the expense is incurred
- Payment in lieu of notice
- Directors' fees
- Salary sacrifice amounts, where the underlying payment would count
- Payments to contractors paid mainly for their labour

Does not count towards super:
- Overtime, where ordinary hours are clearly set by an award or agreement
- Annual leave loading linked to lost overtime
- On-call allowances outside ordinary hours; call-back allowances
- Cash-out of time off in lieu (TOIL)
- Bonuses solely for work entirely outside ordinary hours (commissions are different: they count)
- Parental leave (employer or government paid)
- Jury duty, defence reserve and community service leave
- Workers' compensation when not required to work
- Expense allowances expected to be fully spent (e.g. a tool allowance fully used for tools)
- Unused leave paid on termination; genuine redundancy
- Expense reimbursements
"""

CLASSIFICATION_SYSTEM_PROMPT = """\
You are a payroll auditor classifying Australian pay codes against the Payday Super \
qualifying earnings (QE) rules, in force from 1 July 2026. For each pay code you are given \
its name, description and how it is actually paid, decide whether it counts towards \
qualifying earnings.

Reference rules:
{qe_rules_summary}
{context_block}
Respond with a single JSON object and nothing else — no markdown fences, no commentary. \
The object must have exactly these keys:
{{
  "normalised_name": string, a clean human-readable name for the code,
  "ato_category": string, a short snake_case label for which rule applies,
  "counts_towards_super": one of "yes", "no", "unclear",
  "confidence": one of "high", "medium", "low",
  "citations": array of objects {{"source": string, "reference": string}} naming the rule \
relied on (use "ATO qualifying earnings reference" as the source when using the summary \
above, or the given context's source when it applies),
  "reasoning": string, one or two sentences,
  "question_for_reviewer": string or null, a specific question ONLY if genuinely unclear
}}
Use "unclear" whenever the name and payment pattern do not clearly settle it — never guess. \
If the retrieved context contains more than one entry with different qualifying-earnings \
verdicts (for example, one rule says a payment counts and another says the same kind of \
payment does not, depending on circumstance), that is a sign the code is genuinely unclear \
unless the payment pattern tells you which circumstance applies — do not silently pick \
whichever entry sounds closer to the code's name. In that case, cite both conflicting \
entries and ask a question_for_reviewer that names the specific distinguishing fact you \
are missing (for example, which of two circumstances the payment was made under)."""

CLASSIFICATION_USER_TEMPLATE = """\
Pay code: {code}
Name: {name}
Description: {description}
Payroll category: {payroll_category}
Payment pattern: {payment_pattern}

Classify this pay code."""

CLASSIFICATION_RETRY_SUFFIX = """

Your previous response was not valid: {validation_error}
Reply again with ONLY the corrected JSON object, matching the schema exactly."""


VERIFIER_SYSTEM_PROMPT = """\
You are checking another payroll auditor's conclusion, not re-deriving it. You will be \
given a pay code, its conclusion, the reasoning, and the rule it cites. Answer one \
question only: does the cited rule actually support this conclusion?

Respond with a single JSON object and nothing else:
{{
  "agrees": true or false,
  "note": string, one sentence explaining agreement or, if false, exactly what the cited \
rule actually says instead
}}"""

VERIFIER_USER_TEMPLATE = """\
Pay code: {code} ({normalised_name})
Conclusion: counts_towards_super = {counts_towards_super}
Reasoning: {reasoning}
Cited rule(s): {citations}

Does the cited rule support this conclusion?"""


REMEDIATION_SYSTEM_PROMPT = """\
You are drafting a short, plain-English letter from a bookkeeper to their client about one \
pay code found during a Payday Super audit. Dollar figures are given to you already \
calculated — never compute or restate them differently, just use the numbers you are given. \
Write only the prose around them: what was found, why it matters, and that it is a draft \
for professional review. Two to four short paragraphs. No legal or tax advice, no promises \
about outcomes."""

REMEDIATION_USER_TEMPLATE = """\
Pay code: {code} ({name})
Finding: {direction_description}
Reasoning: {reasoning}
Dollar impact (already calculated, use exactly as given): {impact_note}

Draft the client letter body."""
