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

# --- G4: period lock must consider every time_log month, not just start_date ---

def test_periods_from_timesheet_includes_all_detail_months():
    from rayher_hr_payroll.timesheet_controls import periods_from_timesheet

    doc = SimpleNamespace(
        start_date=date(2026, 1, 28),
        time_logs=[
            SimpleNamespace(from_time="2026-01-28 09:00:00"),
            SimpleNamespace(from_time="2026-02-03 09:00:00"),
        ],
    )
    assert periods_from_timesheet(doc) == {"202601", "202602"}


def test_ensure_period_unlocked_blocks_detail_in_locked_month():
    doc = SimpleNamespace(
        start_date=date(2026, 1, 28),  # open month
        time_logs=[SimpleNamespace(from_time="2026-02-03 09:00:00")],  # locked month
    )
    with pytest.raises(RuleError, match="202602 is locked"):
        ensure_period_unlocked(doc, is_period_locked=lambda p: p == "202602", throw=throw)


# --- G5: every distinct project owner must be collected (no silent skip) ---

def test_distinct_project_owners_collects_all_not_just_single():
    from rayher_hr_payroll.timesheet_controls import distinct_project_owners

    time_logs = [
        SimpleNamespace(project="RD-CAP"),
        SimpleNamespace(project="RD-EXP"),
        SimpleNamespace(project="RD-CAP"),
        SimpleNamespace(project=None),
    ]
    owners = distinct_project_owners(time_logs, {"RD-CAP": "alice", "RD-EXP": "bob"}.get)
    assert owners == ["alice", "bob"]
