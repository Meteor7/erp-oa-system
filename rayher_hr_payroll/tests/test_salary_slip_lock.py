import types

import rayher_hr_payroll.payroll_bridge as pb


class Slip:
    def __init__(self, start_date):
        self.start_date = start_date


def test_period_from_date():
    assert pb._period_from_date("2026-07-01") == (2026, 7)
    assert pb._period_from_date(None) is None


def test_blocks_slip_change_when_allocation_submitted(monkeypatch):
    import pytest

    def throw(msg):
        raise Exception(msg)

    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        db=types.SimpleNamespace(exists=lambda dt, flt: True), throw=throw))
    with pytest.raises(Exception):
        pb.block_locked_salary_slip_change(Slip("2026-07-31"))


def test_allows_slip_change_when_no_allocation(monkeypatch):
    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        db=types.SimpleNamespace(exists=lambda dt, flt: False),
        throw=lambda m: (_ for _ in ()).throw(Exception(m))))
    # no submitted allocation -> no throw
    pb.block_locked_salary_slip_change(Slip("2026-07-31"))


def test_noop_without_start_date(monkeypatch):
    monkeypatch.setattr(pb, "frappe", types.SimpleNamespace(
        db=types.SimpleNamespace(exists=lambda *a: True),
        throw=lambda m: (_ for _ in ()).throw(Exception(m))))
    pb.block_locked_salary_slip_change(Slip(None))  # returns early, no throw
