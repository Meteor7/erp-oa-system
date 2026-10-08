from datetime import date
from decimal import Decimal
from types import SimpleNamespace

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


# ---------------------------------------------------------------------------
# 没定版的月份用预览顶上研发成本（2026-10）
# ---------------------------------------------------------------------------
def _preview_stub(monkeypatch, *, imports, previews, finalized=(), built=None):
    """imports: 有费用导入的月份 {(y, m)}; previews: {(y, m): 成本行列表 | None（算不出来）}。"""
    built = built if built is not None else []
    monkeypatch.setattr(ov.PreviewBook, "_imported", lambda self, year: {m for (y, m) in imports if y == year})

    def compute(self, year, month):
        built.append((year, month))
        return previews.get((year, month))

    monkeypatch.setattr(ov.PreviewBook, "_compute", compute)
    monkeypatch.setattr(ov, "_allocated_months", lambda months: set(finalized) & set(months))
    monkeypatch.setattr(ov, "_rd_rows", lambda months: [])
    monkeypatch.setattr(ov, "_po_rows", lambda months: [])
    monkeypatch.setattr(ov, "_expense_rows", lambda months: [])
    monkeypatch.setattr(ov, "_foreign_rd_rows", lambda months, extra_months=(): [
        {"project": "RD06", "kind": "rd", "amount": 40, "label": ov.FOREIGN_RD_LABEL, "period": m}
        for m in sorted(set(extra_months) & set(months))
    ])
    monkeypatch.setattr(ov, "_rd_project_names", lambda: {"RD02", "RD06"})
    return built


def _plain(function):
    import inspect

    return inspect.unwrap(function)  # 去掉 frappe.whitelist 的类型检查包装（需要请求上下文）


def _rd(project, amount, period):
    return {"project": project, "kind": "rd", "amount": amount, "label": "差旅费", "hours": 10, "period": period}


def test_cost_rows_use_the_preview_for_unfinalized_imported_months(monkeypatch):
    built = _preview_stub(monkeypatch, imports={(2026, 9), (2026, 8)}, finalized={(2026, 8)},
                          previews={(2026, 9): [_rd("RD02", 100, (2026, 9))]})
    monkeypatch.setattr(ov, "_po_rows", lambda months: [
        {"project": "RD02", "kind": "po", "amount": 50, "cost_month": (2026, 9)},
        {"project": "OFFICE", "kind": "po", "amount": 7, "cost_month": (2026, 9)},
    ])
    book = ov.PreviewBook()

    rows = ov.cost_rows([(2026, 8), (2026, 9), (2026, 10)], book)

    assert built == [(2026, 9)]            # 8 月已定版，10 月没有费用导入
    assert book.preview_months([(2026, 8), (2026, 9), (2026, 10)]) == ["2026-09"]
    assert [(row["project"], row["kind"], row["amount"]) for row in rows] == [
        ("RD02", "rd", 100), ("RD06", "rd", 40), ("OFFICE", "po", 7),   # 境外行跟着预览月份；研发项目的采购不再重复计入
    ]


def test_cost_rows_without_a_book_never_preview(monkeypatch):
    built = _preview_stub(monkeypatch, imports={(2026, 9)}, previews={(2026, 9): [_rd("RD02", 100, (2026, 9))]})

    assert ov.cost_rows([(2026, 9)]) == []
    assert built == []


def test_preview_book_computes_each_month_once_and_stops_at_the_limit(monkeypatch):
    months = [(2026, m) for m in range(1, 13)] + [(2025, 12), (2025, 11)]
    built = _preview_stub(monkeypatch, imports=set(months), previews={key: [_rd("RD02", 1, key)] for key in months})
    book = ov.PreviewBook()

    first = book.lines_for(months, set())
    again = book.lines_for(months, set())

    assert len(built) == 12 == book.computed        # 最多 12 个月
    assert built[0] == (2026, 12)                   # 最近的月份优先
    assert set(first) == set(again) == set(built)
    assert len(built) == len(set(built))            # 第二次调用没有重算
    assert (2025, 11) not in first


def test_preview_book_skips_months_whose_preview_fails(monkeypatch):
    built = _preview_stub(monkeypatch, imports={(2026, 9)}, previews={(2026, 9): None})
    book = ov.PreviewBook()

    assert book.lines_for([(2026, 9)], set()) == {}
    assert book.months == set()
    assert built == [(2026, 9)]
    book.lines_for([(2026, 9)], set())
    assert built == [(2026, 9)]


def test_preview_book_compute_wraps_build_preview(monkeypatch):
    from rayher_hr_payroll.rd_cost import allocation_preview

    line = SimpleNamespace(project="RD02", allocated_amount=Decimal("12.50"), account_level_3="", expense_item_name="差旅",
                           basis_hours=8)
    seen = []

    def build(period, year, month):
        seen.append((period, year, month))
        return SimpleNamespace(doc=SimpleNamespace(lines=[line]), error=None)

    monkeypatch.setattr(allocation_preview, "build_preview", build)
    book = ov.PreviewBook()

    assert book._compute(2026, 9) == [
        {"project": "RD02", "kind": "rd", "amount": Decimal("12.50"), "label": "差旅", "hours": 8, "period": (2026, 9)},
    ]
    assert seen == [("2026-09", 2026, 9)]

    monkeypatch.setattr(allocation_preview, "build_preview", lambda *args: SimpleNamespace(doc=None, error="本月还没有研发工时"))
    assert book._compute(2026, 9) is None
    monkeypatch.setattr(allocation_preview, "build_preview", lambda *args: None)
    assert book._compute(2026, 9) is None
    monkeypatch.setattr(allocation_preview, "build_preview", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    assert book._compute(2026, 9) is None


def test_cost_overview_reports_which_months_are_previews(monkeypatch):
    _preview_stub(
        monkeypatch, imports={(2026, 9), (2026, 8)},
        previews={(2026, 9): [_rd("RD02", 100, (2026, 9))], (2026, 8): [_rd("RD02", 60, (2026, 8))]},
    )
    monkeypatch.setattr(ov, "can_view_cost", lambda: True)
    monkeypatch.setattr(ov, "_project_labels", lambda keys: {})

    month = _plain(ov.get_cost_overview)("month", "2026-09")

    assert month["preview"] is True
    assert month["preview_months"] == ["2026-09"]
    assert month["totals"]["rd"] == 140            # 本月预览 100 + 境外 40
    assert month["deltas"]["rd"] == 40.0            # 上月也是预览：60 + 境外 40 = 100
    assert len(month["trend"]) == 12
    assert [row["preview"] for row in month["trend"]] == [False] * 10 + [True, True]
    assert month["trend"][-1]["rd"] == 140

    year = _plain(ov.get_cost_overview)("year", "2026")
    assert year["preview"] is True
    assert year["preview_months"] == ["2026-08", "2026-09"]


def test_cost_overview_without_previews_keeps_preview_false(monkeypatch):
    _preview_stub(monkeypatch, imports=set(), previews={})
    monkeypatch.setattr(ov, "can_view_cost", lambda: True)
    monkeypatch.setattr(ov, "_project_labels", lambda keys: {})

    result = _plain(ov.get_cost_overview)("month", "2026-09")

    assert result["preview"] is False
    assert result["preview_months"] == []
    assert all(row["preview"] is False for row in result["trend"])


def test_project_cost_detail_includes_preview_rows_and_flag(monkeypatch):
    _preview_stub(monkeypatch, imports={(2026, 9)}, previews={(2026, 9): [_rd("RD02", 100, (2026, 9))]})
    monkeypatch.setattr(ov, "can_view_cost", lambda: True)
    monkeypatch.setattr(ov.frappe, "db", SimpleNamespace(get_value=lambda *args, **kwargs: {"project_name": "ADC", "project_owner_name": "王"}), raising=False)
    monkeypatch.setattr(ov, "_project_team", lambda project, months: 3)

    detail = _plain(ov.get_project_cost_detail)("RD02", "month", "2026-09")

    assert detail["totals"]["rd"] == 100
    assert detail["hours"] == 10.0
    assert detail["preview"] is True
    assert detail["preview_months"] == ["2026-09"]