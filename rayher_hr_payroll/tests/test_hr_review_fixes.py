"""PR #79 审查修正（2026-10-13）：考勤月度数字、部门合计对得上、确认工资前重算、看板工资只算已确认。"""
import importlib
import json
import sys
import types
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import attendance_board as board
from rayher_hr_payroll import attendance_requests as att
from rayher_hr_payroll import payroll_bridge
from rayher_hr_payroll.api import attendance_board_entry, overview_entry
from rayher_hr_payroll.dashboard import core, money

OCT = (date(2026, 10, 1), date(2026, 10, 31))
SEP = (date(2026, 9, 1), date(2026, 9, 30))
WORK = {date(2026, 9, 1) + timedelta(days=offset) for offset in range(122) if (date(2026, 9, 1) + timedelta(days=offset)).weekday() < 5}


def legacy(request_type, start, end, hours, leave_type="", employee="A", name="OLD"):
    """没有逐日明细的旧申请。"""
    return {"name": name, "employee": employee, "employee_name": "甲", "request_type": request_type, "leave_type": leave_type,
            "workflow_status": "已完成", "from_date": start, "to_date": end, "attendance_days": None, "duration_hours": hours}


# ================================================================ 1. 旧申请按 duration_hours、记在开始日期的月
def test_legacy_saturday_overtime_keeps_its_hours():
    rows = board.month_window([legacy(att.REQUEST_OVERTIME, "2026-10-17", "2026-10-17", 3)], *OCT)   # 周六
    assert [row["duration_hours"] for row in rows] == [3.0]
    assert board.leave_figures(rows)["overtime_hours"] == 3.0


def test_legacy_two_hour_weekday_overtime_is_not_eight_hours():
    rows = board.month_window([legacy(att.REQUEST_OVERTIME, "2026-10-14", "2026-10-14", 2)], *OCT)   # 周三
    assert [row["duration_hours"] for row in rows] == [2.0]


def test_legacy_half_day_leave_is_four_hours_not_a_whole_day():
    rows = board.month_window([legacy(att.REQUEST_LEAVE, "2026-10-14", "2026-10-14", 4, "事假")], *OCT)
    figures = board.leave_figures(rows, ["A"])
    assert (figures["leave_hours"], figures["leave_days"]) == (4.0, 0.5)


def test_legacy_request_counts_in_the_month_of_its_start_date():
    row = legacy(att.REQUEST_LEAVE, "2026-09-29", "2026-10-02", 32, "事假")
    assert [item["duration_hours"] for item in board.month_window([row], *SEP)] == [32.0]
    assert board.month_window([row], *OCT) == []


def test_requests_with_daily_detail_are_still_split_by_day():
    row = {"name": "NEW", "employee": "A", "request_type": att.REQUEST_LEAVE, "leave_type": "年假", "workflow_status": "已完成",
           "from_date": "2026-09-30", "to_date": "2026-10-01", "duration_hours": 16,
           "attendance_days": json.dumps([{"work_date": "2026-09-30", "hours": 8}, {"work_date": "2026-10-01", "hours": 8}])}
    assert [item["duration_hours"] for item in board.month_window([row], *OCT)] == [8.0]


def test_attendance_centre_month_figure_uses_the_same_legacy_rule():
    rows = [legacy(att.REQUEST_LEAVE, "2026-10-14", "2026-10-14", 4, "事假")]
    stats = board.build_stats(["A"], rows, first=date(2026, 10, 15), work_dates=WORK, month_first=OCT[0], month_last=OCT[1])
    assert (stats["month"]["hours"], stats["month"]["leave_days"]) == (4, 0.5)


def test_attendance_centre_rows_fetch_duration_hours(monkeypatch):
    seen = {}
    monkeypatch.setattr(attendance_board_entry.frappe, "db", SimpleNamespace(sql=lambda query, args, as_dict=False: seen.setdefault("q", query) and []),
                        raising=False)
    attendance_board_entry._rows(["A"], OCT[0], OCT[1])
    assert "duration_hours" in seen["q"] and "attendance_days" in seen["q"]


# ================================================================ 2. 各部门加起来等于卡片
def test_split_days_rows_add_up_to_the_total():
    split = overview_entry.split_days({"甲": 0.5, "乙": 0.5, "丙": 0.5}, 0.19)
    assert round(sum(split.values()), 2) == 0.19 and sorted(split.values()) == [0.06, 0.06, 0.07]
    assert overview_entry.split_days({}, 0) == {}
    assert overview_entry.split_days({"甲": 8, "乙": 4}, 1.5) == {"甲": 1.0, "乙": 0.5}


def test_month_leave_department_rows_add_up_to_the_card(monkeypatch):
    staff = [{"name": "A", "department": "一部"}, {"name": "B", "department": "二部"}, {"name": "C", "department": "三部"}]
    windowed = [{"name": f"L{index}", "employee": employee, "employee_name": employee, "request_type": att.REQUEST_LEAVE,
                 "leave_type": leave_type, "duration_hours": 0.5}
                for index, (employee, leave_type) in enumerate([("A", "年假"), ("B", "事假"), ("C", "病假")])]
    monkeypatch.setattr(overview_entry.frappe, "get_all", lambda *args, **kwargs: staff, raising=False)
    monkeypatch.setattr(overview_entry, "_attendance_rows", lambda months, department=None, employees=None: windowed)
    result = overview_entry.month_leave([(2026, 10)])
    assert result["totals"]["leave_days"] == 0.19
    assert round(sum(row["leave"] for row in result["by_department"]), 2) == 0.19
    assert round(sum(row["days"] for row in result["by_type"]), 2) == 0.19


# ================================================================ 4. 确认本月工资前按现在的社保 / 公积金 / 宿舍重算
class PayrollRuleError(Exception):
    pass


def _load_payroll(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else (lambda fn: fn)
    frappe.throw = lambda message: (_ for _ in ()).throw(PayrollRuleError(str(message)))
    frappe.flags = SimpleNamespace(via_payroll_entry=None)
    frappe.session = SimpleNamespace(user="hr@tests-x.example.invalid")
    frappe.parse_json = lambda value: json.loads(value) if isinstance(value, str) else value
    frappe.clear_messages = lambda: None
    frappe.db = SimpleNamespace(savepoints=[], rollbacks=[])
    frappe.db.savepoint = lambda name: frappe.db.savepoints.append(name)
    frappe.db.rollback = lambda save_point=None: frappe.db.rollbacks.append(save_point)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(str(value))
    utils.get_last_day = lambda value: date(value.year, value.month, 31 if value.month in (1, 3, 5, 7, 8, 10, 12) else 30)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    guards = types.ModuleType("rayher_hr_payroll.api._guards")
    guards.require_rd_access = lambda roles: None
    guards.parse_period = lambda value: tuple(int(part) for part in str(value).split("-")[:2])
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", guards)
    monkeypatch.delitem(sys.modules, "rayher_hr_payroll.api.hr_payroll_entry", raising=False)
    module = importlib.import_module("rayher_hr_payroll.api.hr_payroll_entry")
    return module, frappe


class DraftSlip:
    """页面生成的草稿：存的是当时的金额，hr_* 是人事填的数。"""

    def __init__(self):
        self.name, self.employee, self.docstatus, self.hr_spa_managed = "SAL-1", "E1", 0, 1
        self.payment_days, self.hr_base_salary, self.hr_salary_adjustment = 20, 8800, 0
        self.hr_company_subsidy, self.hr_bonus, self.hr_other_adjustment, self.hr_income_tax, self.hr_advanced_paid = 500, 0, 0, 100, 0
        self.earnings, self.deductions = [{"salary_component": "社保个人", "amount": 999}], []
        self.flags = SimpleNamespace(ignore_permissions=False)
        self.events = []

    def update(self, values): self.__dict__.update(values)
    def set(self, table, rows): setattr(self, table, list(rows))
    def append(self, table, row): getattr(self, table).append(row)
    def save(self, ignore_permissions=False): self.events.append("save")
    def submit(self): self.events.append("submit")


def _payroll_world(monkeypatch, module, frappe, slip, social):
    frappe.get_all = lambda *args, **kwargs: [{"name": "SAL-1", "employee": "E1", "employee_name": "演示员工128", "hr_spa_managed": 1}]
    frappe.get_doc = lambda doctype, name: slip
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "Rayher", "employee_name": "演示员工128"})
    monkeypatch.setattr(module, "_social_record", lambda *args: social)
    monkeypatch.setattr(module, "_monthly_record", lambda *args: {"employee_amount": 200})
    monkeypatch.setattr(module, "_working_days", lambda *args: (22.0, 22.0, "hrms"))
    monkeypatch.setattr(module, "_accommodation", lambda *args: 150)
    monkeypatch.setattr(module, "_slip", lambda *args: slip)
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪 - Rayher"})


def test_confirm_resaves_each_draft_with_current_contributions_before_submitting(monkeypatch):
    module, frappe = _load_payroll(monkeypatch)
    slip = DraftSlip()
    _payroll_world(monkeypatch, module, frappe, slip, {"employee_total": 300})
    result = module.confirm_payroll("2026-10")
    assert result["confirmed"] == 1 and result["skipped"] == []
    assert slip.events == ["save", "submit"], "先按现在的数重存，再确认"
    # 人事填的数原样保留，社保 / 公积金 / 宿舍取现在的
    assert (slip.payment_days, slip.hr_base_salary, slip.hr_company_subsidy, slip.hr_income_tax) == (20.0, 8800.0, 500.0, 100.0)
    assert {line["salary_component"]: line["amount"] for line in slip.deductions} == {"社保个人": 300, "公积金个人": 200, "宿舍扣款": 150, "个税": 100}
    assert {line["salary_component"]: line["amount"] for line in slip.earnings} == {"基本工资": 8000.0, "公司补贴": 500}


def test_confirm_skips_a_draft_that_can_no_longer_be_recalculated(monkeypatch):
    module, frappe = _load_payroll(monkeypatch)
    slip = DraftSlip()
    _payroll_world(monkeypatch, module, frappe, slip, None)   # 社保记录没了
    result = module.confirm_payroll("2026-10")
    assert result["confirmed"] == 0 and slip.events == []
    assert result["skipped"] == [{"employee": "E1", "employee_name": "演示员工128", "reason": module.RESAVE_FAILED + "该员工尚未维护本月社保记录。"}]
    assert frappe.db.rollbacks == ["confirm_payroll"]


# ================================================================ 5. 看板工资只算已确认；草稿只数本页生成的
def test_pay_totals_count_only_this_pages_drafts_and_report_external_ones(monkeypatch):
    seen = {}
    rows = [{"employee": "E1", "docstatus": 1, "gross_pay": 1000, "total_deduction": 100, "hr_spa_managed": 1},
            {"employee": "E2", "docstatus": 0, "gross_pay": 500, "total_deduction": 0, "hr_spa_managed": 1},
            {"employee": "E3", "docstatus": 0, "gross_pay": 700, "total_deduction": 0, "hr_spa_managed": 0},
            {"employee": "E1", "docstatus": 0, "gross_pay": 50, "total_deduction": 0, "hr_spa_managed": 0}]   # 已确认的人不再算草稿

    def get_all(doctype, filters=None, fields=None, **kwargs):
        seen["fields"] = fields
        return rows

    monkeypatch.setattr(payroll_bridge.frappe, "get_all", get_all, raising=False)
    totals = payroll_bridge.period_pay_totals("2026-10")
    assert "hr_spa_managed" in seen["fields"]
    assert (totals["gross"], totals["confirmed"], totals["draft"], totals["draft_gross"]) == (1000.0, 1, 1, 500.0)
    assert (totals["external_draft"], totals["external_draft_gross"]) == (1, 700.0)


def _ctx():
    return core.Ctx(user="hr@example.com", roles=frozenset({"HR Manager", "Employee"}), positions=frozenset({"hr_manager"}),
                    period="2026-10", today="2026-10-15")


def _labor(**kw):
    base = {"gross": 100000.0, "draft": 2, "external_draft": 0, "social": 0.0, "fund": 0.0, "has_contributions": False,
            "dorm_company": 0.0, "dorm_registered": False}
    base.update(kw)
    return base


def test_labor_wage_row_links_to_confirmed_payroll_only():
    ctx = _ctx()
    ctx._memo["money.labor"] = _labor()
    detail = core.get_detail_for(ctx, "cost.labor")
    assert detail["rows"][0]["target"] == {"key": "payroll", "params": {"period": "2026-10", "status": "submitted"}}


def test_labor_wage_row_mentions_external_drafts_separately():
    assert money._wage_cells(_labor(external_draft=3))[0] == "已确认的工资条；另有 2 人没确认；3 人是别处生成的草稿"
    assert money._wage_cells(_labor(gross=0.0, draft=0, external_draft=3)) == ("本期还没有已确认的工资条；3 人是别处生成的草稿", "—")
