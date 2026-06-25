from datetime import date
from types import SimpleNamespace

import pytest

from rayher_hr_payroll.timesheet_controls import (
    ensure_no_submitted_allocation,
    rd_periods_for_lock,
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


def test_ensure_rd_projects_enabled_does_not_block_unknown_stage_by_default():
    seen = []
    doc = SimpleNamespace(
        start_date=date(2026, 1, 15),
        time_logs=[SimpleNamespace(project="RD-NO-DATES", from_time="2026-01-15 09:00:00")],
    )

    def project_stage_for_entry(project, posting_date):
        seen.append((project, posting_date))
        return "unknown"

    ensure_rd_projects_enabled(
        doc,
        is_project_enabled=lambda project: True,
        project_stage_for_entry=project_stage_for_entry,
        throw=throw,
    )

    assert seen == [("RD-NO-DATES", date(2026, 1, 15))]

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


def test_ensure_period_unlocked_translates_message_template():
    doc = SimpleNamespace(start_date=date(2026, 1, 15))

    with pytest.raises(RuleError, match='T:R&D period 202601 is locked'):
        ensure_period_unlocked(
            doc,
            is_period_locked=lambda period: True,
            throw=throw,
            translate=lambda text: f'T:{text}',
        )


def test_ensure_rd_projects_enabled_translates_message_template():
    doc = SimpleNamespace(time_logs=[SimpleNamespace(project='NON-RD')])

    with pytest.raises(RuleError, match='T:Project NON-RD is not enabled'):
        ensure_rd_projects_enabled(
            doc,
            is_project_enabled=lambda project: False,
            throw=throw,
            translate=lambda text: f'T:{text}',
        )


def _rd_doc():
    return SimpleNamespace(
        employee="EMP-1",
        time_logs=[SimpleNamespace(project="RD-CAP", from_time=date(2026, 5, 15))],
    )


def test_ensure_no_submitted_allocation_freezes_rd_row_in_allocated_period():
    with pytest.raises(RuleError, match="2026-05"):
        ensure_no_submitted_allocation(
            _rd_doc(),
            is_rd_employee=lambda e: True,
            project_rd_enabled=lambda pr: True,
            has_submitted_allocation=lambda y, m: (y, m) == (2026, 5),
            throw=throw,
        )


def test_ensure_no_submitted_allocation_ignores_non_rd_employee():
    # a non-R&D employee never feeds allocation, so the freeze must not fire
    ensure_no_submitted_allocation(
        _rd_doc(),
        is_rd_employee=lambda e: False,
        project_rd_enabled=lambda pr: True,
        has_submitted_allocation=lambda y, m: True,
        throw=throw,
    )


def test_ensure_no_submitted_allocation_ignores_non_rd_project_rows():
    ensure_no_submitted_allocation(
        _rd_doc(),
        is_rd_employee=lambda e: True,
        project_rd_enabled=lambda pr: False,
        has_submitted_allocation=lambda y, m: True,
        throw=throw,
    )


def test_ensure_no_submitted_allocation_allows_period_without_allocation():
    ensure_no_submitted_allocation(
        _rd_doc(),
        is_rd_employee=lambda e: True,
        project_rd_enabled=lambda pr: True,
        has_submitted_allocation=lambda y, m: False,
        throw=throw,
    )


def test_rd_periods_for_lock_is_sorted_and_distinct():
    # multi-month sheet, rows out of order, a non-R&D row mixed in
    doc = SimpleNamespace(time_logs=[
        SimpleNamespace(project="RD", from_time=date(2026, 2, 10)),
        SimpleNamespace(project="RD", from_time=date(2026, 1, 5)),
        SimpleNamespace(project="NON", from_time=date(2026, 3, 1)),
        SimpleNamespace(project="RD", from_time=date(2026, 2, 20)),
    ])
    # only R&D periods, de-duplicated, ascending -> stable lock order (no AB-BA deadlock)
    assert rd_periods_for_lock(doc, lambda pr: pr == "RD") == [(2026, 1), (2026, 2)]
