"""CSV parsing and validation for paycodes.csv and payruns.csv (spec section 9)."""

from __future__ import annotations

import warnings
from statistics import median
from typing import Union

import pandas as pd
from pydantic import ValidationError

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


def _parse_amount(raw_value: object, row_number: int) -> float:
    """Fix 1: previously a bad value here raised a bare ValueError from
    float(), which api/routes.py's `except IngestError` does not catch,
    since ValueError is IngestError's parent, not a subclass. Real payroll
    exports carry currency symbols and thousands separators often enough
    that this was a live gap, not a theoretical one."""
    try:
        amount = float(raw_value)
    except (ValueError, TypeError) as exc:
        raise IngestError(
            f"payruns file, row {row_number}, column 'total_amount': "
            f"could not parse {raw_value!r} as a number"
        ) from exc
    if amount < 0:
        raise IngestError(
            f"payruns file, row {row_number}, column 'total_amount': "
            f"amount cannot be negative, got {amount}"
        )
    return amount


def _parse_headcount(raw_value: object, row_number: int) -> int:
    try:
        return int(float(raw_value))
    except (ValueError, TypeError) as exc:
        raise IngestError(
            f"payruns file, row {row_number}, column 'employees_paid': "
            f"could not parse {raw_value!r} as a whole number"
        ) from exc


def load_paycodes(path_or_buffer: PathOrBuffer) -> list[PayCode]:
    df = _clean_columns(pd.read_csv(path_or_buffer, dtype=str))
    missing = REQUIRED_PAYCODE_COLUMNS - set(df.columns)
    if missing:
        raise IngestError(f"paycodes file is missing required columns: {sorted(missing)}")

    codes: list[PayCode] = []
    for row_number, row in enumerate(df.to_dict(orient="records"), start=2):
        try:
            codes.append(
                PayCode(
                    code=str(row["code"]).strip(),
                    name=str(row["name"]).strip(),
                    description=_blank_to_none(row.get("description")),
                    counts_for_super=row["counts_for_super"],
                    payroll_category=_blank_to_none(row.get("payroll_category")),
                )
            )
        except (ValidationError, ValueError, TypeError) as exc:
            # Fix 1: a bad Y/N value previously raised a raw pydantic
            # ValidationError here, also not caught by `except IngestError`.
            raise IngestError(f"paycodes file, row {row_number}: invalid data ({exc})") from exc
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


def load_payruns(
    path_or_buffer: PathOrBuffer, known_codes: set[str] | None = None
) -> list[PayRunRow]:
    """Fix 2: known_codes is new and optional, defaulting to None, which
    preserves the exact current behaviour for the existing call site in
    api/routes.py. Passing the set of codes already loaded from
    paycodes.csv activates an orphan-code check that did not exist before,
    a pay run referencing a code absent from paycodes.csv previously
    passed through silently."""
    df = _clean_columns(pd.read_csv(path_or_buffer, dtype=str))
    missing = REQUIRED_PAYRUN_COLUMNS - set(df.columns)
    if missing:
        raise IngestError(f"payruns file is missing required columns: {sorted(missing)}")

    runs: list[PayRunRow] = []
    for row_number, row in enumerate(df.to_dict(orient="records"), start=2):
        code = str(row["code"]).strip()
        if known_codes is not None and code not in known_codes:
            raise IngestError(
                f"payruns file, row {row_number}, column 'code': "
                f"{code!r} does not appear in paycodes.csv"
            )

        overtime_raw = _blank_to_none(row.get("overtime_hours"))
        total_amount = _parse_amount(row["total_amount"], row_number)
        employees_paid = _parse_headcount(row["employees_paid"], row_number)

        try:
            runs.append(
                PayRunRow(
                    pay_date=str(row["pay_date"]).strip(),
                    code=code,
                    total_amount=total_amount,
                    employees_paid=employees_paid,
                    overtime_hours=float(overtime_raw) if overtime_raw is not None else None,
                )
            )
        except (ValidationError, ValueError, TypeError) as exc:
            # Fix 1: a malformed pay_date previously raised a raw pydantic
            # ValidationError here too, same uncaught-by-IngestError gap.
            raise IngestError(f"payruns file, row {row_number}: invalid data ({exc})") from exc
    return runs


def infer_pay_runs_per_year(pay_runs: list[PayRunRow], default: float = DEFAULT_PAY_RUNS_PER_YEAR) -> float:
    """Infer the payroll's cadence from the typical gap between pay dates.

    Fix 3: the fallback to `default` is now surfaced with warnings.warn
    rather than staying completely silent. Return type and every call site
    are unchanged, this is additive only. A guessed cadence flowing
    unflagged into a dollar figure was the single easiest way this tool
    could misstate a real compliance number without anyone noticing.
    """
    dates = sorted({r.pay_date for r in pay_runs})
    if len(dates) < 2:
        warnings.warn(
            f"infer_pay_runs_per_year: fewer than two distinct pay dates, "
            f"defaulting to {default} pay runs per year",
            stacklevel=2,
        )
        return default
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    typical_gap = median(gaps)
    if typical_gap <= 0:
        warnings.warn(
            f"infer_pay_runs_per_year: non-positive typical gap ({typical_gap} days), "
            f"defaulting to {default} pay runs per year",
            stacklevel=2,
        )
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