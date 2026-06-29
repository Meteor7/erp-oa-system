import types

import rayher_hr_payroll.payroll_bridge as pb


class Slip:
    def __init__(self, start_date, employee="EMP-1"):
        self.start_date = start_date
        self.employee = employee


def test_period_from_date():
    assert pb._period_from_date("2026-07-01") == (2026, 7)
    assert pb._period_from_date(None) is None


def test_blocks_slip_change_when_allocation_submitted(monkeypatch):
    import pytest

    def throw(msg):
        raise Exception(msg)

    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        get_all=lambda dt, filters=None, pluck=None: ["ALLOC-1"],
        db=types.SimpleNamespace(exists=lambda dt, flt: True),
        throw=throw))
    with pytest.raises(Exception):
        pb.block_locked_salary_slip_change(Slip("2026-07-31"))


def test_allows_slip_change_when_no_allocation(monkeypatch):
    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        get_all=lambda dt, filters=None, pluck=None: [],  # no submitted allocation
        db=types.SimpleNamespace(exists=lambda dt, flt: False),
        throw=lambda m: (_ for _ in ()).throw(Exception(m))))
    pb.block_locked_salary_slip_change(Slip("2026-07-31"))


def test_noop_without_start_date(monkeypatch):
    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        get_all=lambda *a, **k: ["ALLOC-1"],
        db=types.SimpleNamespace(exists=lambda *a: True),
        throw=lambda m: (_ for _ in ()).throw(Exception(m))))
    pb.block_locked_salary_slip_change(Slip(None))  # returns early, no throw


def test_allows_slip_whose_hours_were_not_captured(monkeypatch):
    # An employee whose hours were never captured by the allocation (exists False) -- e.g. a
    # non-R&D employee, or one reclassified before the period -- is not blocked.
    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        get_all=lambda dt, filters=None, pluck=None: ["ALLOC-1"],
        db=types.SimpleNamespace(exists=lambda dt, flt: False),  # no source-hour row for this employee
        throw=lambda m: (_ for _ in ()).throw(Exception(m))))
    pb.block_locked_salary_slip_change(Slip("2026-07-31", employee="EMP-NONRD"))  # no throw
