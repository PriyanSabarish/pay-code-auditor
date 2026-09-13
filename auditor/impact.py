"""
auditor/impact.py

Every dollar figure in the audit comes from this module and nowhere else.
No LLM call, no free text field, no model output ever produces a number
here, per ADR-B01. Inputs are the validated output of ingest.py plus a
classification verdict

Penalty exposure is always a range with an explicit ceiling, never a single
figure, per ADR-B02: the administrative uplift is discretionary, up to 60%,
not a guaranteed charge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SUPER_GUARANTEE_RATE = 0.12
MAXIMUM_ADMINISTRATIVE_UPLIFT = 0.60

Verdict = Literal["should_count", "should_not_count"]


@dataclass
class DollarImpact:
    code: str
    verdict: Verdict
    current_setting_counts: bool
    annual_amount: float
    pay_runs_per_year: int
    super_guarantee_rate: float = SUPER_GUARANTEE_RATE

    # Populated only when the setting is wrong, otherwise both stay 0.0
    annual_shortfall: float = 0.0
    annual_overpayment: float = 0.0
    penalty_ceiling: float = 0.0  # up to 60% of the shortfall, shortfall side only

    @property
    def is_misconfigured(self) -> bool:
        return self.current_setting_counts != (self.verdict == "should_count")

    @property
    def direction(self) -> str:
        if not self.is_misconfigured:
            return "correct"
        return "underpayment" if self.verdict == "should_count" else "overpayment"


def calculate_annual_amount(average_amount_per_run: float, pay_runs_per_year: int) -> float:
    """The one multiplication every other figure in this module depends on.
    Kept as its own function so it has its own unit tests, since every
    downstream number is wrong if this is wrong."""
    return round(average_amount_per_run * pay_runs_per_year, 2)


def calculate_impact(
    code: str,
    verdict: Verdict,
    current_setting_counts: bool,
    average_amount_per_run: float,
    pay_runs_per_year: int | None,
) -> DollarImpact:
    """Computes the dollar impact of one pay code's configuration against
    its classified verdict. Returns a DollarImpact with either a shortfall
    (should count but doesn't, the costly direction) or an overpayment
    (counts but shouldn't), never both, and never a figure when the code is
    already configured correctly.

    verdict of "unclear" must never reach this function. That gate lives in
    compare.py, per ADR-B12: unclear codes go to human review and produce no
    dollar figure. Passing "unclear" here raises, deliberately, rather than
    silently returning a zeroed result that could be mistaken for a clean
    code.

    pay_runs_per_year of None means ingest.py could not determine the
    code's pay cycle, per ADR-B07, usually because it only appeared in one
    pay run in the uploaded history. This must also raise rather than
    silently produce a wrong or zeroed dollar figure: guessing a cadence
    here would misstate a real compliance number, and the correct handling
    is routing the code to human review before impact is ever attempted,
    the same principle as the unclear verdict guard above.
    """
    if verdict not in ("should_count", "should_not_count"):
        raise ValueError(
            f"calculate_impact received verdict='{verdict}'. Only "
            "'should_count' or 'should_not_count' may reach the impact "
            "engine, an 'unclear' classification must be routed to human "
            "review before impact is ever calculated."
        )

    if pay_runs_per_year is None:
        raise ValueError(
            f"calculate_impact received pay_runs_per_year=None for code "
            f"'{code}'. This means ingest.py could not determine the "
            "code's pay cycle (see the UNKNOWN_FREQUENCY or SINGLE_PAY_RUN "
            "warning), and the code must be routed to human review rather "
            "than have a dollar figure calculated against a guessed cadence."
        )

    annual_amount = calculate_annual_amount(average_amount_per_run, pay_runs_per_year)

    outcome = DollarImpact(
        code=code,
        verdict=verdict,
        current_setting_counts=current_setting_counts,
        annual_amount=annual_amount,
        pay_runs_per_year=pay_runs_per_year,
    )

    if not outcome.is_misconfigured:
        return outcome

    if outcome.direction == "underpayment":
        outcome.annual_shortfall = round(annual_amount * SUPER_GUARANTEE_RATE, 2)
        outcome.penalty_ceiling = round(outcome.annual_shortfall * MAXIMUM_ADMINISTRATIVE_UPLIFT, 2)
    else:  # overpayment
        outcome.annual_overpayment = round(annual_amount * SUPER_GUARANTEE_RATE, 2)

    return outcome


def format_penalty_note(impact: DollarImpact) -> str:
    """The wording the UI shows next to a shortfall. Written here, once, so
    no other module (or prompt) can drift into stating the uplift as a
    fixed figure rather than a ceiling."""
    if impact.direction != "underpayment":
        return ""
    return (
        f"Super guarantee charge of ${impact.annual_shortfall:,.2f} per year, "
        f"plus an administrative uplift of up to ${impact.penalty_ceiling:,.2f} "
        "(up to 60%), plus notional earnings (interest)."
    )