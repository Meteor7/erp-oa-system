from rayher_hr_payroll.payroll_bridge import month_bounds


def test_month_bounds_returns_first_and_last_day():
    assert month_bounds("2026-07") == ("2026-07-01", "2026-07-31")
    assert month_bounds("2026-02") == ("2026-02-01", "2026-02-28")


def test_month_bounds_rejects_bad_period():
    import pytest
    with pytest.raises(ValueError):
        month_bounds("2026/07")
