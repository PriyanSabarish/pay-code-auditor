"""Exact dollar-impact maths (spec section 6.6). Deliberately plain Python: the AI never does arithmetic."""

from __future__ import annotations

from .schemas import ImpactDirection, ImpactResult

SUPER_GUARANTEE_RATE = 0.12
MAX_ADMINISTRATIVE_UPLIFT_RATE = 0.60


def calculate_annual_amount(avg_amount_per_pay_run: float, pay_runs_per_year: float) -> float:
    return round(avg_amount_per_pay_run * pay_runs_per_year, 2)


def calculate_underpayment_impact(
    code: str, avg_amount_per_pay_run: float, pay_runs_per_year: float
) -> ImpactResult:
    """A code that should count towards super but is currently excluded."""

    annual_amount = calculate_annual_amount(avg_amount_per_pay_run, pay_runs_per_year)
    shortfall = round(annual_amount * SUPER_GUARANTEE_RATE, 2)
    max_uplift = round(shortfall * MAX_ADMINISTRATIVE_UPLIFT_RATE, 2)
    return ImpactResult(
        code=code,
        direction="should_count_not_counted",
        annual_amount=annual_amount,
        super_amount=shortfall,
        max_penalty_uplift=max_uplift,
        note=(
            f"Super shortfall of ${shortfall:,.2f} per year on this code, plus an "
            f"administrative uplift of up to ${max_uplift:,.2f}, plus interest."
        ),
    )


def calculate_overpayment_impact(
    code: str, avg_amount_per_pay_run: float, pay_runs_per_year: float
) -> ImpactResult:
    """A code that counts towards super but shouldn't."""

    annual_amount = calculate_annual_amount(avg_amount_per_pay_run, pay_runs_per_year)
    overpayment = round(annual_amount * SUPER_GUARANTEE_RATE, 2)
    return ImpactResult(
        code=code,
        direction="counts_should_not",
        annual_amount=annual_amount,
        super_amount=overpayment,
        max_penalty_uplift=None,
        note=f"Super overpaid by approximately ${overpayment:,.2f} per year on this code.",
    )


def calculate_impact(
    code: str,
    direction: ImpactDirection,
    avg_amount_per_pay_run: float,
    pay_runs_per_year: float,
) -> ImpactResult:
    if direction == "should_count_not_counted":
        return calculate_underpayment_impact(code, avg_amount_per_pay_run, pay_runs_per_year)
    if direction == "counts_should_not":
        return calculate_overpayment_impact(code, avg_amount_per_pay_run, pay_runs_per_year)
    raise ValueError(f"unknown impact direction: {direction!r}")
