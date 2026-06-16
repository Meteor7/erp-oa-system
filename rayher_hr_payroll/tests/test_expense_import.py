import pytest

from rayher_hr_payroll.import_controls import ensure_unique_submitted_period


class RuleError(Exception):
    pass


def throw(message):
    raise RuleError(str(message))


def test_ensure_unique_submitted_period_rejects_existing_submitted_period():
    with pytest.raises(RuleError, match="202601"):
        ensure_unique_submitted_period(
            "202601",
            current_name="NEW-IMPORT",
            find_conflict=lambda period, name: "OLD-IMPORT",
            throw=throw,
        )


def test_ensure_unique_submitted_period_allows_when_no_conflict():
    ensure_unique_submitted_period(
        "202601",
        current_name="NEW-IMPORT",
        find_conflict=lambda period, name: None,
        throw=throw,
    )
