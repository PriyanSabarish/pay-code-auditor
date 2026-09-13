"""CSV parsing and validation for paycodes.csv and payruns.csv (spec section 9)."""

from __future__ import annotations

from statistics import median
from typing import Union

import pandas as pd

from .schemas import PayCode, PaymentHistory, PayRunRow

PathOrBuffer = Union[str, "pd.io.common.FilePath", object]

REQUIRED_PAYCODE_COLUMNS = {"code", "name", "counts_for_super"}
REQUIRED_PAYRUN_COLUMNS = {"pay_date", "code", "total_amount", "employees_paid"}

DEFAULT_PAY_RUNS_PER_YEAR = 26.0  # fortnightly, matching the spec's sample businesses


class IngestError(ValueError):
    """Raised when an uploaded file is missing columns or otherwise malformed."""


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def _blank_to_none(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def load_paycodes(path_or_buffer: PathOrBuffer) -> list[PayCode]:
    df = _clean_columns(pd.read_csv(path_or_buffer, dtype=str))
    missing = REQUIRED_PAYCODE_COLUMNS - set(df.columns)
    if missing:
        raise IngestError(f"paycodes file is missing required columns: {sorted(missing)}")

    codes: list[PayCode] = []
    for row in df.to_dict(orient="records"):
        codes.append(
            PayCode(
                code=str(row["code"]).strip(),
                name=str(row["name"]).strip(),
                description=_blank_to_none(row.get("description")),
                counts_for_super=row["counts_for_super"],
                payroll_category=_blank_to_none(row.get("payroll_category")),
            )
        )
    _check_duplicate_codes(codes)
    return codes


def _check_duplicate_codes(codes: list[PayCode]) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for c in codes:
        if c.code in seen:
            dupes.add(c.code)
        seen.add(c.code)
    if dupes:
        raise IngestError(f"duplicate pay codes in paycodes file: {sorted(dupes)}")


def load_payruns(path_or_buffer: PathOrBuffer) -> list[PayRunRow]:
    df = _clean_columns(pd.read_csv(path_or_buffer, dtype=str))
    missing = REQUIRED_PAYRUN_COLUMNS - set(df.columns)
    if missing:
        raise IngestError(f"payruns file is missing required columns: {sorted(missing)}")

    runs: list[PayRunRow] = []
    for row in df.to_dict(orient="records"):
        overtime_raw = _blank_to_none(row.get("overtime_hours"))
        runs.append(
            PayRunRow(
                pay_date=str(row["pay_date"]).strip(),
                code=str(row["code"]).strip(),
                total_amount=float(row["total_amount"]),
                employees_paid=int(float(row["employees_paid"])),
                overtime_hours=float(overtime_raw) if overtime_raw is not None else None,
            )
        )
    return runs


def infer_pay_runs_per_year(pay_runs: list[PayRunRow], default: float = DEFAULT_PAY_RUNS_PER_YEAR) -> float:
    """Infer the payroll's cadence from the typical gap between pay dates."""

    dates = sorted({r.pay_date for r in pay_runs})
    if len(dates) < 2:
        return default
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    typical_gap = median(gaps)
    if typical_gap <= 0:
        return default
    return round(365.0 / typical_gap, 2)


def payment_history_for_code(
    code: str, pay_runs: list[PayRunRow], pay_runs_per_year: float | None = None
) -> PaymentHistory:
    matches = [r for r in pay_runs if r.code == code]
    if not matches:
        raise IngestError(f"no pay run history found for code {code!r}")

    if pay_runs_per_year is None:
        pay_runs_per_year = infer_pay_runs_per_year(pay_runs)

    num = len(matches)
    total_amount = sum(r.total_amount for r in matches)
    total_overtime = sum(r.overtime_hours or 0.0 for r in matches)
    return PaymentHistory(
        code=code,
        num_pay_runs=num,
        avg_amount_per_pay_run=round(total_amount / num, 2),
        total_amount=round(total_amount, 2),
        avg_employees_paid=round(sum(r.employees_paid for r in matches) / num, 2),
        total_overtime_hours=round(total_overtime, 2),
        pay_runs_per_year=pay_runs_per_year,
    )
