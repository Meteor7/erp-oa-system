from rayher_hr_payroll.payroll_bridge import month_bounds


def test_month_bounds_returns_first_and_last_day():
    assert month_bounds("2026-07") == ("2026-07-01", "2026-07-31")
    assert month_bounds("2026-02") == ("2026-02-01", "2026-02-28")


def test_month_bounds_rejects_bad_period():
    import pytest
    with pytest.raises(ValueError):
        month_bounds("2026/07")


def test_period_pay_totals_shape(monkeypatch):
    import rayher_hr_payroll.payroll_bridge as pb
    monkeypatch.setattr(pb.frappe, "get_all", lambda *a, **k: [
        {"gross_pay": 100.0, "total_deduction": 30.0},
        {"gross_pay": 200.0, "total_deduction": 40.0},
    ])
    out = pb.period_pay_totals("2026-07")
    assert out == {"gross": 300.0, "deductions": 70.0}
