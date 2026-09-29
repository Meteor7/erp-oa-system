"""Unit tests for the project stage-lock classifier (pure logic, no DB)."""
from types import SimpleNamespace

import pytest

pytest.importorskip("frappe")

from rayher_hr_payroll import project_controls
from rayher_hr_payroll.project_controls import _stage


def _proj(start, end, rd_stage=None):
    return SimpleNamespace(capitalization_start_date=start, capitalization_end_date=end, rd_stage=rd_stage)


def test_stage_capitalized_inside_window():
    assert _stage(_proj("2026-01-01", "2026-12-31"), "202606") == "capitalized"


def test_stage_expensed_outside_window():
    assert _stage(_proj("2025-01-01", "2025-12-31"), "202606") == "expensed"


def test_stage_unknown_when_dates_missing():
    assert _stage(_proj(None, None), "202606") == "unknown"
    assert _stage(None, "202606") == "unknown"


def test_stage_within_month_start_shift_flips_classification():
    # The lock must detect a within-month start-date shift, mirroring
    # stage_for_period (compare actual date vs first-of-month).
    # Period 202601, first-of-month = 2026-01-01.
    assert _stage(_proj("2026-01-01", "2026-12-31"), "202601") == "capitalized"
    # Move start to mid-month: 2026-01-15 > 2026-01-01 => January now expensed.
    assert _stage(_proj("2026-01-15", "2026-12-31"), "202601") == "expensed"


def test_stage_prefers_backend_rd_stage():
    assert _stage(_proj(None, None, "资本化"), "202606") == "capitalized"
    assert _stage(_proj("2026-01-01", "2026-12-31", "费用化"), "202606") == "expensed"


class _Project(SimpleNamespace):
    def __init__(self, before, changed, **values):
        super().__init__(name="PROJ-1", **values)
        self._before = before
        self._changed = changed

    def is_new(self):
        return False

    def has_value_changed(self, key):
        return key in self._changed

    def get_doc_before_save(self):
        return self._before


def _guard(monkeypatch, *, locked=(), allocated=(), hours=()):
    monkeypatch.setattr(project_controls, "guarded_rd_periods", lambda frappe_module: (set(locked), set(allocated)))
    monkeypatch.setattr(project_controls, "_has_rd_hours", lambda project, ym: ym in hours)
    monkeypatch.setattr(project_controls.frappe, "_", lambda text: text, raising=False)

    def deny(message):
        raise ValueError(message)

    monkeypatch.setattr(project_controls.frappe, "throw", deny, raising=False)


def test_clearing_the_rd_code_is_blocked_for_an_allocated_period(monkeypatch):
    # 审查 X2-5 / 17-c：已分摊期间有工时的项目不能去掉研发编号（这些工时会从分摊取数里消失）。
    _guard(monkeypatch, allocated={"202606"}, hours={"202606"})
    doc = _Project(SimpleNamespace(rd_project_code="RD02"), {"rd_project_code"}, rd_project_code="")
    with pytest.raises(ValueError, match="2026-06"):
        project_controls.validate_project_stage_lock(doc)

    renamed = _Project(SimpleNamespace(rd_project_code="RD02"), {"rd_project_code"}, rd_project_code="RD02A")
    project_controls.validate_project_stage_lock(renamed)


def test_stage_change_is_only_blocked_by_stage_locks(monkeypatch):
    # 已提交分摊的阶段是快照，改阶段不影响它们；阶段锁定的期间照旧拦。
    before = _proj(None, None, "费用化")
    doc = _Project(before, {"rd_stage"}, rd_stage="资本化", capitalization_start_date=None, capitalization_end_date=None)
    _guard(monkeypatch, allocated={"202606"}, hours={"202606"})
    project_controls.validate_project_stage_lock(doc)
    _guard(monkeypatch, locked={"202606"})
    with pytest.raises(ValueError, match="已锁定期间"):
        project_controls.validate_project_stage_lock(doc)


def test_cancelling_a_project_is_not_blocked_by_history(monkeypatch):
    # 决定 D9：取消只关掉新填报，历史工时照样算研发成本。
    _guard(monkeypatch, allocated={"202606"}, hours={"202606"})
    doc = _Project(SimpleNamespace(rd_project_code="RD02"), {"allow_rd_timesheet", "status"}, rd_project_code="RD02")
    project_controls.validate_project_stage_lock(doc)


def test_guarded_periods_read_locks_and_submitted_allocations():
    calls = []

    def get_all(doctype, **kwargs):
        calls.append((doctype, kwargs["filters"]))
        if doctype == "RD Period Lock":
            return [SimpleNamespace(period="2026-05"), SimpleNamespace(period="")]
        return [{"year": 2026, "month": 6}, {"year": None, "month": None}]

    locked, allocated = project_controls.guarded_rd_periods(SimpleNamespace(get_all=get_all))
    assert locked == {"202605"} and allocated == {"202606"}
    assert ("RD Cost Allocation", {"docstatus": 1}) in calls
