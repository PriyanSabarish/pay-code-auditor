"""Unit tests for auditor.ingest."""

import io

import pytest

from auditor.ingest import (
    IngestError,
    infer_pay_runs_per_year,
    load_paycodes,
    load_payruns,
    payment_history_for_code,
)

PAYCODES_CSV = """code,name,description,counts_for_super,payroll_category
SUNPEN,Sunday Penalty 175%,Sunday ordinary hours penalty,Y,Allowance
OTMEAL,Overtime meal allowance,,N,Allowance
"""

PAYRUNS_CSV = """pay_date,code,total_amount,employees_paid,overtime_hours
2026-07-03,SITEALLOW,1125.00,25,
2026-07-17,SITEALLOW,1125.00,25,
2026-07-31,SITEALLOW,1125.00,25,36
"""


def test_load_paycodes_parses_rows():
    codes = load_paycodes(io.StringIO(PAYCODES_CSV))
    assert len(codes) == 2
    assert codes[0].code == "SUNPEN"
    assert codes[0].counts_for_super == "Y"
    assert codes[1].description is None


def test_load_paycodes_rejects_missing_columns():
    with pytest.raises(IngestError):
        load_paycodes(io.StringIO("code,name\nA,B\n"))


def test_load_paycodes_rejects_duplicates():
    csv = "code,name,counts_for_super\nA,First,Y\nA,Second,N\n"
    with pytest.raises(IngestError):
        load_paycodes(io.StringIO(csv))


def test_load_payruns_parses_rows_and_optional_overtime():
    runs = load_payruns(io.StringIO(PAYRUNS_CSV))
    assert len(runs) == 3
    assert runs[0].overtime_hours is None
    assert runs[2].overtime_hours == 36


def test_infer_pay_runs_per_year_detects_fortnightly():
    runs = load_payruns(io.StringIO(PAYRUNS_CSV))
    assert infer_pay_runs_per_year(runs) == 26.07  # 365 / 14, rounded


def test_payment_history_for_code_matches_spec_example():
    runs = load_payruns(io.StringIO(PAYRUNS_CSV))
    history = payment_history_for_code("SITEALLOW", runs, pay_runs_per_year=26)
    assert history.num_pay_runs == 3
    assert history.avg_amount_per_pay_run == 1125.0
    assert history.avg_employees_paid == 25.0
    assert history.total_overtime_hours == 36.0


def test_payment_history_for_unknown_code_raises():
    runs = load_payruns(io.StringIO(PAYRUNS_CSV))
    with pytest.raises(IngestError):
        payment_history_for_code("NOPE", runs)


def test_malformed_currency_amount_raises_ingest_error_not_bare_valueerror():
    csv = "pay_date,code,total_amount,employees_paid\n2026-07-10,A,$4,210.50,3\n"
    with pytest.raises(IngestError):
        load_payruns(io.StringIO(csv))


def test_negative_amount_raises_ingest_error():
    csv = "pay_date,code,total_amount,employees_paid\n2026-07-10,A,-50.00,3\n"
    with pytest.raises(IngestError):
        load_payruns(io.StringIO(csv))


def test_invalid_counts_for_super_value_raises_ingest_error():
    csv = "code,name,counts_for_super\nA,Test Code,Maybe\n"
    with pytest.raises(IngestError):
        load_paycodes(io.StringIO(csv))


def test_orphan_code_raises_when_known_codes_supplied():
    csv = "pay_date,code,total_amount,employees_paid\n2026-07-10,GHOST,100.00,3\n"
    with pytest.raises(IngestError):
        load_payruns(io.StringIO(csv), known_codes={"REALCODE"})


def test_orphan_code_check_is_skipped_when_known_codes_not_supplied():
    csv = "pay_date,code,total_amount,employees_paid\n2026-07-10,GHOST,100.00,3\n"
    runs = load_payruns(io.StringIO(csv))  # no known_codes passed, preserves old behaviour
    assert len(runs) == 1


def test_frequency_fallback_now_warns_instead_of_staying_silent():
    runs = load_payruns(io.StringIO(PAYRUNS_CSV))
    single_run = runs[:1]
    with pytest.warns(UserWarning, match="defaulting to"):
        infer_pay_runs_per_year(single_run)
