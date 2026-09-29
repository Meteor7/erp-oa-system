from datetime import date

import pytest

from rayher_hr_payroll.api import overview_entry as ov
from rayher_hr_payroll import attendance_requests as att


def test_parse_scope_reads_month_and_year():
    assert ov.parse_scope("month", "2026-09") == ("month", 2026, 9)
    assert ov.parse_scope("year", "2026 年") == ("year", 2026, None)


def test_period_and_previous_months_wrap_the_year():
    assert ov.period_months("month", 2026, 1) == [(2026, 1)]
    assert ov.previous_months("month", 2026, 1) == [(2025, 12)]
    assert ov.previous_months("month", 2026, 9) == [(2026, 8)]
    assert ov.period_months("year", 2026, None)[0] == (2026, 1)
    assert len(ov.period_months("year", 2026, None)) == 12
    assert ov.previous_months("year", 2026, None)[-1] == (2025, 12)


def test_trend_covers_twelve_months_or_five_years():
    months = ov.trend_periods("month", 2026, 2)
    assert len(months) == 12
    assert months[0]["months"] == [(2025, 3)]
    assert months[-1]["months"] == [(2026, 2)]
    years = ov.trend_periods("year", 2026, None)
    assert [bucket["label"] for bucket in years] == ["2022", "2023", "2024", "2025", "2026"]


def test_month_range_spans_whole_months():
    assert ov.month_range([(2026, 2)]) == (date(2026, 2, 1), date(2026, 2, 28))
    assert ov.month_range([(2026, 1), (2026, 12)]) == (date(2026, 1, 1), date(2026, 12, 31))


def test_project_costs_group_by_project_and_bucket_unassigned():
    rows = [{"project": "PRJ-1", "kind": "rd", "amount": 100},
            {"project": "PRJ-1", "kind": "po", "amount": 50},
            {"project": None, "kind": "expense", "amount": 20}]
    costs = ov.project_costs(rows)
    assert costs["PRJ-1"] == {"rd": 100.0, "po": 50.0, "expense": 0.0, "total": 150.0}
    assert costs[ov.NON_PROJECT]["expense"] == 20.0
    assert ov.sum_costs(costs)["total"] == 170.0


@pytest.mark.parametrize("current,previous,expected", [(120, 100, 20.0), (80, 100, -20.0), (10, 0, None)])
def test_delta_percent(current, previous, expected):
    assert ov.delta_percent(current, previous) == expected


def test_leave_stats_convert_hours_to_days_by_type_and_department():
    rows = [
        {"request_type": att.REQUEST_LEAVE, "leave_type": "事假", "duration_hours": 12, "department": "研发部"},
        {"request_type": att.REQUEST_LEAVE, "leave_type": "年假", "duration_hours": 8, "department": "研发部"},
        {"request_type": att.REQUEST_OVERTIME, "duration_hours": 16, "department": "工程部"},
        {"request_type": att.REQUEST_COMP_TIME, "duration_hours": 4, "department": "工程部"},
    ]
    stats = ov.leave_stats(rows)
    assert stats["totals"] == {"leave_days": 2.5, "leave_count": 2, "overtime_days": 2.0, "comp_days": 0.5}
    assert {row["label"]: row["days"] for row in stats["by_type"]} == {"事假": 1.5, "年假": 1.0, "调休": 0.5}
    departments = {row["label"]: row for row in stats["by_department"]}
    assert departments["研发部"]["leave"] == 2.5
    assert departments["工程部"] == {"label": "工程部", "leave": 0.5, "overtime": 2.0}


def test_leave_without_department_or_type_is_still_counted():
    stats = ov.leave_stats([{"request_type": att.REQUEST_LEAVE, "duration_hours": 4}])
    assert stats["by_type"][0]["label"] == "未填类别"
    assert stats["by_department"][0]["label"] == "未分配部门"


def test_days_uses_eight_hour_workday():
    assert ov.days(12) == 1.5
    assert ov.days(None) == 0


def test_attendance_rows_split_cross_month_requests_by_day(monkeypatch):
    # 审查 #56 P3：9 月 30 日到 10 月 2 日的假原来全记在 9 月。
    import json as _json
    rows = [
        {"request_type": att.REQUEST_LEAVE, "leave_type": "事假", "duration_hours": 20, "department": "研发部",
         "employee": "E1", "employee_name": "甲", "from_date": "2026-09-30", "to_date": "2026-10-02",
         "attendance_days": _json.dumps([{"work_date": "2026-09-30", "hours": 8}, {"work_date": "2026-10-01", "hours": 8},
                                          {"work_date": "2026-10-02", "hours": 4}])},
        {"request_type": att.REQUEST_LEAVE, "leave_type": "事假", "duration_hours": 8, "department": "研发部",
         "employee": "E2", "employee_name": "乙", "from_date": "2026-09-10", "to_date": "2026-09-10", "attendance_days": ""},
    ]
    monkeypatch.setattr(ov.frappe, "get_all", lambda *args, **kwargs: [dict(row) for row in rows], raising=False)
    september = ov._attendance_rows([(2026, 9)])
    october = ov._attendance_rows([(2026, 10)])
    assert sorted((row["employee"], row["duration_hours"]) for row in september) == [("E1", 8.0), ("E2", 8)]
    assert [(row["employee"], row["duration_hours"]) for row in october] == [("E1", 12.0)]
    both = ov._attendance_rows([(2026, 9), (2026, 10)])
    assert sorted((row["employee"], row["duration_hours"]) for row in both) == [("E1", 20.0), ("E2", 8)]


def test_allocated_months_drop_rd_project_purchases_and_expenses_only():
    # 审查 X2-10（决定 D7）：已提交分摊的月份，研发项目的采购和报销已在分摊里，不再重复计入。
    rows = [
        {"project": "RD02", "kind": "rd", "amount": 100, "period": (2026, 6)},
        {"project": "RD02", "kind": "po", "amount": 50, "cost_month": (2026, 6)},
        {"project": "RD02", "kind": "expense", "amount": 30, "cost_month": (2026, 7)},
        {"project": "OFFICE", "kind": "expense", "amount": 20, "cost_month": (2026, 6)},
        {"project": None, "kind": "po", "amount": 10, "cost_month": (2026, 6)},
    ]

    kept = ov.drop_allocated_rd_duplicates(rows, {(2026, 6)}, {"RD02"})

    assert [(row["project"], row["kind"], row["amount"]) for row in kept] == [
        ("RD02", "rd", 100), ("RD02", "expense", 30), ("OFFICE", "expense", 20), (None, "po", 10),
    ]


def test_cost_rows_include_foreign_rd_and_apply_the_dedup(monkeypatch):
    monkeypatch.setattr(ov, "_rd_rows", lambda months: [{"project": "RD02", "kind": "rd", "amount": 100}])
    monkeypatch.setattr(ov, "_foreign_rd_rows", lambda months: [{"project": "RD06", "kind": "rd", "amount": 40, "label": ov.FOREIGN_RD_LABEL}])
    monkeypatch.setattr(ov, "_po_rows", lambda months: [{"project": "RD02", "kind": "po", "amount": 50, "cost_month": (2026, 6)}])
    monkeypatch.setattr(ov, "_expense_rows", lambda months: [])
    monkeypatch.setattr(ov, "_allocated_months", lambda months: {(2026, 6)})
    monkeypatch.setattr(ov, "_rd_project_names", lambda: {"RD02", "RD06"})

    totals = ov.sum_costs(ov.project_costs(ov.cost_rows([(2026, 6)])))

    assert totals == {"rd": 140.0, "po": 0.0, "expense": 0.0, "total": 140.0}
