"""Unit tests for the project stage-lock classifier (pure logic, no DB)."""
from types import SimpleNamespace

import pytest

pytest.importorskip("frappe")

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
