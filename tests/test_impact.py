"""Unit tests for auditor.impact, replicating the worked examples in the spec."""

from auditor.impact import calculate_impact, calculate_overpayment_impact, calculate_underpayment_impact


def test_site_allow_example_from_spec():
    # Spec 6.3: $45 to 25 workers every fortnight, wrongly excluded from super.
    result = calculate_underpayment_impact("SITE ALLOW", avg_amount_per_pay_run=45 * 25, pay_runs_per_year=26)
    assert result.annual_amount == 29_250.0
    assert result.super_amount == 3_510.0
    assert result.max_penalty_uplift == 2_106.0


def test_weekly_allowance_example_from_spec():
    # Spec 2.4: $50/week allowance wrongly excluded for 30 staff.
    result = calculate_underpayment_impact("WEEKLY ALLOW", avg_amount_per_pay_run=50 * 30, pay_runs_per_year=52)
    assert result.annual_amount == 78_000.0
    assert result.super_amount == 9_360.0
    assert result.max_penalty_uplift == 5_616.0


def test_overpayment_direction():
    result = calculate_overpayment_impact("BONUS OT", avg_amount_per_pay_run=1_000, pay_runs_per_year=26)
    assert result.annual_amount == 26_000.0
    assert result.super_amount == 3_120.0
    assert result.max_penalty_uplift is None


def test_calculate_impact_dispatches_on_direction():
    under = calculate_impact("A", "should_count_not_counted", 100, 26)
    over = calculate_impact("B", "counts_should_not", 100, 26)
    assert under.direction == "should_count_not_counted"
    assert over.direction == "counts_should_not"


def test_calculate_impact_rejects_unknown_direction():
    import pytest

    with pytest.raises(ValueError):
        calculate_impact("A", "bogus", 100, 26)  # type: ignore[arg-type]
