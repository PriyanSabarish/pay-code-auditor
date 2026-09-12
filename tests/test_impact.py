"""

Locks in the arithmetic in auditor/impact.py. This is the module every
other lane's dollar figures depend on, so every branch gets a test:
underpayment, overpayment, correct configuration, all three pay frequencies,
zero and single employee edges, and the deliberate raise on an unclear
verdict.
"""

import pytest

from auditor.impact import (
    SUPER_GUARANTEE_RATE,
    MAXIMUM_ADMINISTRATIVE_UPLIFT,
    calculate_annual_amount,
    calculate_impact,
    format_penalty_note,
)


# ---- calculate_annual_amount: the multiplication everything else depends on ----

class TestCalculateAnnualAmount:

    def test_weekly_conversion(self):
        assert calculate_annual_amount(average_amount_per_run=500.00, pay_runs_per_year=52) == 26000.00

    def test_fortnightly_conversion(self):
        assert calculate_annual_amount(average_amount_per_run=1000.00, pay_runs_per_year=26) == 26000.00

    def test_monthly_conversion(self):
        assert calculate_annual_amount(average_amount_per_run=2166.67, pay_runs_per_year=12) == 26000.04

    def test_rounds_to_two_decimal_places(self):
    # 333.333 per run, 3 runs -> 999.999, which rounds up to 1000.00
        assert calculate_annual_amount(average_amount_per_run=333.333, pay_runs_per_year=3) == 1000.00

    def test_zero_amount_gives_zero(self):
        assert calculate_annual_amount(average_amount_per_run=0.0, pay_runs_per_year=26) == 0.0


# ---- calculate_impact: underpayment direction ----

class TestUnderpayment:

    def test_should_count_but_does_not_produces_shortfall(self):
        result = calculate_impact(
            code="FIRSTAID", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=120.00, pay_runs_per_year=26,
        )
        assert result.direction == "underpayment"
        assert result.annual_amount == 3120.00
        assert result.annual_shortfall == 374.40
        assert result.annual_overpayment == 0.0

    def test_penalty_ceiling_is_sixty_percent_of_shortfall(self):
        result = calculate_impact(
            code="FIRSTAID", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=120.00, pay_runs_per_year=26,
        )
        expected_ceiling = round(result.annual_shortfall * MAXIMUM_ADMINISTRATIVE_UPLIFT, 2)
        assert result.penalty_ceiling == expected_ceiling
        assert result.penalty_ceiling == 224.64

    def test_penalty_note_states_a_ceiling_never_a_fixed_figure(self):
        result = calculate_impact(
            code="FIRSTAID", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=120.00, pay_runs_per_year=26,
        )
        note = format_penalty_note(result)
        assert "up to" in note
        assert "60%" in note
        assert "notional earnings" in note


# ---- calculate_impact: overpayment direction ----

class TestOverpayment:

    def test_should_not_count_but_does_produces_overpayment(self):
        result = calculate_impact(
            code="OT15", verdict="should_not_count", current_setting_counts=True,
            average_amount_per_run=1050.00, pay_runs_per_year=26,
        )
        assert result.direction == "overpayment"
        assert result.annual_amount == 27300.00
        assert result.annual_overpayment == 3276.00
        assert result.annual_shortfall == 0.0

    def test_overpayment_has_no_penalty_ceiling(self):
        # Overpaying super is not a compliance breach in the same sense,
        # so there is deliberately no uplift figure on this side.
        result = calculate_impact(
            code="OT15", verdict="should_not_count", current_setting_counts=True,
            average_amount_per_run=1050.00, pay_runs_per_year=26,
        )
        assert result.penalty_ceiling == 0.0

    def test_penalty_note_is_empty_for_overpayment(self):
        result = calculate_impact(
            code="OT15", verdict="should_not_count", current_setting_counts=True,
            average_amount_per_run=1050.00, pay_runs_per_year=26,
        )
        assert format_penalty_note(result) == ""


# ---- calculate_impact: correctly configured codes produce nothing ----

class TestCorrectConfiguration:

    def test_correctly_included_code_produces_no_dollar_figure(self):
        result = calculate_impact(
            code="ORDHRS", verdict="should_count", current_setting_counts=True,
            average_amount_per_run=24810.00, pay_runs_per_year=26,
        )
        assert result.direction == "correct"
        assert result.annual_shortfall == 0.0
        assert result.annual_overpayment == 0.0
        assert result.penalty_ceiling == 0.0

    def test_correctly_excluded_code_produces_no_dollar_figure(self):
        result = calculate_impact(
            code="REIMB", verdict="should_not_count", current_setting_counts=False,
            average_amount_per_run=200.00, pay_runs_per_year=26,
        )
        assert result.direction == "correct"
        assert result.annual_shortfall == 0.0
        assert result.annual_overpayment == 0.0


# ---- The deliberate guard: unclear must never reach this function ----

class TestUnclearVerdictGuard:

    def test_unclear_verdict_raises_rather_than_returning_zero(self):
        with pytest.raises(ValueError, match="unclear"):
            calculate_impact(
                code="RDOPAYOUT", verdict="unclear", current_setting_counts=False,
                average_amount_per_run=500.00, pay_runs_per_year=26,
            )

    def test_garbage_verdict_also_raises(self):
        with pytest.raises(ValueError):
            calculate_impact(
                code="XXXX", verdict="maybe", current_setting_counts=False,
                average_amount_per_run=500.00, pay_runs_per_year=26,
            )


# ---- Zero and single employee edge cases, called out explicitly in the Lane B brief ----

class TestZeroAndSingleEmployeeEdges:

    def test_zero_average_amount_never_divides_by_anything_or_crashes(self):
        result = calculate_impact(
            code="DORMANT", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=0.0, pay_runs_per_year=26,
        )
        assert result.annual_amount == 0.0
        assert result.annual_shortfall == 0.0

    def test_single_employee_small_amount_still_rounds_correctly(self):
        # One employee, a small first aid allowance, paid weekly.
        result = calculate_impact(
            code="FIRSTAID_SOLO", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=15.00, pay_runs_per_year=52,
        )
        assert result.annual_amount == 780.00
        assert result.annual_shortfall == 93.60

    def test_zero_pay_runs_per_year_gives_zero_annual_amount(self):
        # Defensive case: if pay_runs_per_year somehow reaches here as 0
        # rather than being caught upstream as UNKNOWN_FREQUENCY, this must
        # not raise or divide by zero, since there is no division here.
        result = calculate_impact(
            code="EDGE", verdict="should_count", current_setting_counts=False,
            average_amount_per_run=1000.00, pay_runs_per_year=0,
        )
        assert result.annual_amount == 0.0
        assert result.annual_shortfall == 0.0


# ---- is_misconfigured property, the switch everything else is built on ----

class TestIsMisconfiguredProperty:

    @pytest.mark.parametrize(
        "verdict,current_setting_counts,expected",
        [
            ("should_count", True, False),      # correct: counts, and should
            ("should_count", False, True),      # wrong: should count, doesn't
            ("should_not_count", False, False),  # correct: excluded, and should be
            ("should_not_count", True, True),   # wrong: counts, but shouldn't
        ],
    )
    def test_all_four_combinations(self, verdict, current_setting_counts, expected):
        result = calculate_impact(
            code="MATRIX", verdict=verdict, current_setting_counts=current_setting_counts,
            average_amount_per_run=1000.00, pay_runs_per_year=26,
        )
        assert result.is_misconfigured == expected