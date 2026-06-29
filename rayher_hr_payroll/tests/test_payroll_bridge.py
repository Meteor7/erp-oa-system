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


def test_period_salaries_sums_multiple_slips_per_employee(monkeypatch):
    # Weekly/off-cycle payroll -> several submitted slips per employee in one month.
    # Must SUM, not overwrite (consistent with period_pay_totals).
    import rayher_hr_payroll.payroll_bridge as pb

    rows = [
        {"employee": "E1", "gross_pay": 1000.0},
        {"employee": "E1", "gross_pay": 1500.0},
        {"employee": "E2", "gross_pay": 2000.0},
    ]
    monkeypatch.setattr(pb.frappe, "get_all", lambda *a, **k: [pb.frappe._dict(r) for r in rows])
    out = pb.period_salaries("2026-07")
    assert out == {"E1": 2500.0, "E2": 2000.0}


def test_get_period_salary_sums_all_slips(monkeypatch):
    import rayher_hr_payroll.payroll_bridge as pb

    monkeypatch.setattr(
        pb.frappe, "get_all",
        lambda *a, **k: [pb.frappe._dict({"gross_pay": 1000.0}), pb.frappe._dict({"gross_pay": 1500.0})],
    )
    assert pb.get_period_salary("E1", "2026-07") == 2500.0
