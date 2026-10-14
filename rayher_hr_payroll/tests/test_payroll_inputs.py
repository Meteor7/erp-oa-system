"""薪酬计算的三样输入（决定 2026-10-14）：工时只扣事假、社保公积金按账单 → 记录 → 档案基数取数、个税累计从期初 + 已确认工资条来。"""
import importlib
import sys
import types
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest


def _load(monkeypatch, get_value=None, get_all=None):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.db = SimpleNamespace(get_value=get_value or (lambda *args, **kwargs: None))
    frappe.get_all = get_all or (lambda *args, **kwargs: [])
    frappe.inserted = []

    class Doc(dict):
        def __init__(self, doctype):
            super().__init__(doctype=doctype)
            self.flags = SimpleNamespace()
        def update(self, values): super().update(values)
        def insert(self, ignore_permissions=False): frappe.inserted.append((self["doctype"], dict(self), vars(self.flags)))

    frappe.new_doc = Doc
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.payroll_inputs", None)
    module = importlib.import_module("rayher_hr_payroll.payroll_inputs")
    return module, frappe


EMPLOYEE = {"name": "E1", "employee_name": "演示员工128", "company": "Rayher", "default_social_insurance_base": 5000,
            "default_housing_fund_base": 6000, "household_registration": "湖南省长沙市"}


def test_social_prefers_the_current_bill_then_the_monthly_record(monkeypatch):
    calls = []

    def get_value(doctype, filters, fields=None, as_dict=False):
        calls.append(doctype)
        if doctype == "Social Insurance Import Batch":
            return "SIB-1"
        if doctype == "Social Insurance Import Row":
            assert filters["status"] == ["in", ["Matched", "Confirmed Difference"]] and filters["company"] == "Rayher"
            return {"name": "SIR-1", "employee_total": 1020, "company_total": 3000}
        if doctype == "Employee Housing Fund":
            return {"name": "EHF-1", "employee_amount": 700, "company_amount": 700, "remark": "公积金导入 HFB-1", "contribution_base": 10000}
        raise AssertionError(doctype)

    module, _ = _load(monkeypatch, get_value)
    found = module.contributions(EMPLOYEE, "2026-10")
    assert found["social"]["employee_total"] == 1020 and found["social"]["source"] == "社保账单（2026-10）"
    assert "Employee Social Insurance" not in calls


def test_without_bill_or_record_social_and_fund_come_from_the_archive_base_and_policy(monkeypatch):
    module, frappe = _load(monkeypatch)
    found = module.contributions(EMPLOYEE, "2026-10")
    social, fund = found["social"], found["fund"]
    # 示例总部 2026：养老 8%、医疗 2%（最低基数 6727）、失业 0.2%；基数 5000 → 400 + 134.54 + 10
    assert (social["employee_pension"], social["employee_medical"], social["employee_unemployment"]) == (400.0, 134.54, 10.0)
    assert social["employee_total"] == 544.54 and social["auto"] and "按档案基数 5000" in social["source"]
    # 公积金 6000 × 7%
    assert fund["employee_amount"] == 420.0 and fund["company_amount"] == 420.0
    # 保存草稿时写成本月记录；社保的金额按政策算好，不让记录自己按比例重算
    module.materialize(EMPLOYEE, "2026-10", found)
    (si_type, si, si_flags), (hf_type, hf, _) = frappe.inserted
    assert si_type == "Employee Social Insurance" and si["employee_total"] == 544.54 and si_flags["keep_amounts"] is True
    assert si["remark"].startswith(module.AUTO_REMARK) and si["status"] == "Confirmed"
    assert hf_type == "Employee Housing Fund" and hf["employee_rate"] == 7.0 and hf["remark"] == module.AUTO_REMARK


@pytest.mark.parametrize("employee, company, missing", [
    ({**EMPLOYEE, "default_social_insurance_base": 0}, "Rayher", "员工档案里没有社保基数"),
    ({**EMPLOYEE, "company": "示例研发中心"}, "示例研发中心", "示例研发中心 2026 年的社保政策还没配置"),
])
def test_missing_inputs_are_reported_not_treated_as_zero(monkeypatch, employee, company, missing):
    module, _ = _load(monkeypatch)
    assert module.contributions(employee, "2026-10")["social"] == {"missing": missing}


def test_work_hours_cut_only_approved_personal_leave(monkeypatch):
    seen = {}

    def get_all(doctype, filters=None, fields=None, **kwargs):
        seen["filters"] = filters
        return [{"request_type": "请假申请", "workflow_status": "已完成", "leave_type": "事假",
                 "attendance_days": '[{"work_date": "2026-10-20", "hours": 8}, {"work_date": "2026-10-21", "hours": 3}]'}]

    module, _ = _load(monkeypatch, get_all=get_all)
    work = [date(2026, 10, day) for day in range(1, 32) if date(2026, 10, day).weekday() < 5]
    calendar = types.ModuleType("rayher_hr_payroll.working_calendar")
    calendar.resolve_monthly_calendar = lambda year, month, employee=None, company=None: {
        "work_dates": [d for d in work if not employee or d >= date(2026, 10, 12)], "calendar_source": "company_holiday_list"}
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.working_calendar", calendar)
    hours = module.work_hours("E1", "Rayher", "2026-10")
    assert seen["filters"]["leave_type"] == "事假" and sorted(seen["filters"]["workflow_status"][1]) == ["已完成", "已通过"]
    # 10 月 22 个工作日 = 176 小时；10/12 入职 → 在职 15 天 = 120 小时；事假 11 小时
    assert (hours["total_hours"], hours["employed_hours"], hours["personal_leave_hours"], hours["actual_hours"]) == (176.0, 120.0, 11.0, 109.0)


def test_tax_basis_adds_opening_balance_and_confirmed_slips_of_the_same_tax_year(monkeypatch):
    def get_value(doctype, filters, fields=None, as_dict=False):
        assert doctype == "Employee Tax Profile" and filters == {"employee": "E1", "year": 2026}
        return {"opening_to_period": "2026-09", "opening_months": 9, "opening_income": 90000, "opening_special": 15480,
                "opening_special_additional": 27000, "opening_tax": 120, "special_total": 3000, "low_income_rule": 0}

    def get_all(doctype, filters=None, fields=None, **kwargs):
        if filters.get("docstatus") == 1:
            return [
                {"name": "S-OCT", "hr_tax_period": "2026-10", "hr_tax_income": 10000, "hr_tax_special": 1720,
                 "hr_tax_special_additional": 3000, "hr_income_tax": 50, "hr_bonus_tax": 0},
                # 期初已经包含的月份不重复算
                {"name": "S-SEP", "hr_tax_period": "2026-09", "hr_tax_income": 99999, "hr_income_tax": 999},
            ]
        return []

    module, _ = _load(monkeypatch, get_value, get_all)
    basis = module.tax_basis("E1", "Rayher", "2026-10")   # 10 月工资 → 11 月个税
    assert basis["tax_period"] == "2026-11"
    assert basis["prior"] == {"months": 10, "income": 100000.0, "tax_free": 0.0, "special": 17200.0,
                              "special_additional": 30000.0, "other": 0.0, "tax": 170.0}
    assert basis["special_additional"] == 3000.0 and basis["warnings"] == []
    tax = module.compute_tax(basis, payable=10000, social=1020, fund=700, bonus=0, bonus_separate=False)
    # 累计 110000 − 55000 − 18920 − 33000 = 3080 × 3% = 92.4，已扣 170 → 本月 0
    assert tax["cum_taxable"] == 3080.0 and tax["total"] == 0.0


def test_a_missing_opening_balance_late_in_the_year_is_flagged(monkeypatch):
    module, _ = _load(monkeypatch)
    basis = module.tax_basis("E1", "Rayher", "2026-10")
    assert basis["prior"]["months"] == 0 and basis["warnings"] and "累计数没有录入" in basis["warnings"][0]


def test_separate_bonus_is_taxed_on_its_own_and_left_out_of_the_cumulative_income(monkeypatch):
    module, _ = _load(monkeypatch)
    basis = {"prior": {}, "low_income": False, "special_additional": 0, "other": 0, "tax_period": "2027-01"}
    together = module.compute_tax(basis, payable=46000, social=1000, fund=0, bonus=36000, bonus_separate=False)
    apart = module.compute_tax(basis, payable=46000, social=1000, fund=0, bonus=36000, bonus_separate=True)
    assert together["bonus_tax"] == 0 and together["income"] == 46000
    assert apart["income"] == 10000 and apart["bonus_tax"] == 1080.0
    assert apart["total"] == round(float(Decimal("120.00")) + 1080.0, 2)
