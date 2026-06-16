from datetime import date
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.timesheet_controls import (
    ensure_period_unlocked,
    ensure_rd_projects_enabled,
    period_from_timesheet,
)


class RuleError(Exception):
    pass


def throw(message):
    raise RuleError(str(message))


def test_period_from_timesheet_uses_start_date():
    doc = SimpleNamespace(start_date=date(2026, 1, 15))
    assert period_from_timesheet(doc) == "202601"


def test_ensure_period_unlocked_blocks_locked_timesheet_period():
    doc = SimpleNamespace(start_date=date(2026, 1, 15))

    with pytest.raises(RuleError, match="202601 is locked"):
        ensure_period_unlocked(doc, is_period_locked=lambda period: True, throw=throw)


def test_ensure_rd_projects_enabled_blocks_non_rd_project():
    doc = SimpleNamespace(
        time_logs=[
            SimpleNamespace(project="RD-CAP"),
            SimpleNamespace(project="NON-RD"),
        ]
    )

    with pytest.raises(RuleError, match="Project NON-RD is not enabled"):
        ensure_rd_projects_enabled(
            doc,
            is_project_enabled=lambda project: project != "NON-RD",
            throw=throw,
        )