from types import SimpleNamespace

import pytest

from rayher_hr_payroll.leave_controls import validate_compensatory_leave_dates


class RuleError(Exception):
    pass


def throw(message):
    raise RuleError(str(message))


def test_validate_compensatory_leave_dates_blocks_statutory_holiday():
    doc = SimpleNamespace(work_from_date="2026-10-01", work_end_date=None)

    with pytest.raises(RuleError, match="Statutory holiday overtime cannot be converted"):
        validate_compensatory_leave_dates(
            doc,
            is_statutory_holiday=lambda work_date: work_date == "2026-10-01",
            throw=throw,
        )


def test_validate_compensatory_leave_dates_allows_normal_holiday():
    doc = SimpleNamespace(work_from_date="2026-01-10", work_end_date=None)

    validate_compensatory_leave_dates(
        doc,
        is_statutory_holiday=lambda work_date: False,
        throw=throw,
    )