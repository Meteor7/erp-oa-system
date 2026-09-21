import importlib
import sys
import types
from datetime import date
from types import SimpleNamespace

import pytest


class PayrollRuleError(Exception):
    pass


def _load(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else (lambda fn: fn)
    frappe.throw = lambda message: (_ for _ in ()).throw(PayrollRuleError(str(message)))
    frappe.db = SimpleNamespace()
    frappe.get_all = lambda *args, **kwargs: []
    frappe.get_cached_value = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(str(value))
    utils.get_last_day = lambda value: date(value.year, value.month, 31 if value.month in (1,3,5,7,8,10,12) else 30)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    guards = types.ModuleType("rayher_hr_payroll.api._guards")
    guards.require_rd_access = lambda roles: None
    guards.parse_period = lambda value: tuple(int(part) for part in str(value).split("-")[:2])
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", guards)
    sys.modules.pop("rayher_hr_payroll.api.hr_payroll_entry", None)
    module = importlib.import_module("rayher_hr_payroll.api.hr_payroll_entry")
    return module, frappe


def test_calculation_prorates_adjusted_base_and_deducts_advanced_payment(monkeypatch):
    module, _ = _load(monkeypatch)

    result = module._calculate_amounts(
        total_working_days=21, payment_days=20, base_salary=10000, salary_adjustment=500,
        company_subsidy=300, bonus=200, other_adjustment=-50, social_insurance=1050,
        housing_fund=700, income_tax=120, accommodation=500, advanced_paid=1000,
    )

    assert result == {
        "adjusted_base": 10500.0,
        "prorated_base": 10000.0,
        "payable_salary": 10450.0,
        "total_deduction": 3370.0,
        "net_pay": 7080.0,
    }


def test_calculation_rejects_payment_days_above_total_and_negative_advance(monkeypatch):
    module, _ = _load(monkeypatch)
    base = dict(total_working_days=21, payment_days=20, base_salary=10000, salary_adjustment=0, company_subsidy=0, bonus=0, other_adjustment=0, social_insurance=0, housing_fund=0, income_tax=0, accommodation=0, advanced_paid=0)

    with pytest.raises(PayrollRuleError, match="计薪天数"):
        module._calculate_amounts(**{**base, "payment_days": 22})
    with pytest.raises(PayrollRuleError, match="已发放"):
        module._calculate_amounts(**{**base, "advanced_paid": -1})


def test_period_employee_query_includes_people_who_left_during_month(monkeypatch):
    module, _ = _load(monkeypatch)
    filters, or_filters = module._period_employee_filters(date(2026, 8, 1), date(2026, 8, 31))

    assert filters == {"date_of_joining": ["<=", date(2026, 8, 31)]}
    assert or_filters == [["relieving_date", "is", "not set"], ["relieving_date", ">=", date(2026, 8, 1)]]


def test_missing_social_or_housing_record_is_not_treated_as_zero(monkeypatch):
    module, _ = _load(monkeypatch)

    with pytest.raises(PayrollRuleError, match="社保"):
        module._require_contribution_records(None, {"name": "FUND-1"})
    with pytest.raises(PayrollRuleError, match="公积金"):
        module._require_contribution_records({"name": "SOC-1"}, None)


def test_only_spa_managed_draft_can_be_updated(monkeypatch):
    module, _ = _load(monkeypatch)

    assert module._assert_writable_slip(SimpleNamespace(docstatus=0, hr_spa_managed=1, name="SAL-1")) is None
    with pytest.raises(PayrollRuleError, match="其他来源"):
        module._assert_writable_slip(SimpleNamespace(docstatus=0, hr_spa_managed=0, name="SAL-X"))
    with pytest.raises(PayrollRuleError, match="已提交"):
        module._assert_writable_slip(SimpleNamespace(docstatus=1, hr_spa_managed=1, name="SAL-SUB"))


def test_company_specific_structure_never_falls_back_to_other_company(monkeypatch):
    module, frappe = _load(monkeypatch)
    frappe.db.get_value = lambda doctype, filters, field=None: "标准月薪 - 示例研发科技" if filters == {"name": "标准月薪 - 示例研发科技", "company": "示例研发科技", "is_active": "Yes", "docstatus": 1} else None

    assert module._existing_structure_for_company("示例研发科技") == "标准月薪 - 示例研发科技"
    assert module._structure_name("乔岳科技") == "标准月薪 - 乔岳科技"


def test_apply_salary_adjustment_rejects_same_date_assignment_without_overwrite(monkeypatch):
    module, frappe = _load(monkeypatch)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "Rayher"})
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪"})
    frappe.db.get_value = lambda doctype, filters, field=None: "SSA-EXISTING" if doctype == "Salary Structure Assignment" else None

    with pytest.raises(PayrollRuleError, match="已有工资分配"):
        module.apply_salary_adjustment("EMP-1", "2026-08", 10500)


def test_apply_salary_adjustment_creates_submitted_assignment_for_employee_company(monkeypatch):
    module, frappe = _load(monkeypatch)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "Rayher"})
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪"})
    frappe.db.get_value = lambda *args, **kwargs: None
    frappe.db.commit = lambda: (_ for _ in ()).throw(AssertionError("business APIs must not commit partial transactions"))
    captured = {}

    class Assignment:
        name = "SSA-NEW"
        def update(self, values): captured.update(values)
        def insert(self, ignore_permissions=False): captured["insert"] = ignore_permissions
        def submit(self): captured["submit"] = True

    frappe.new_doc = lambda doctype: Assignment()
    result = module.apply_salary_adjustment("EMP-1", "2026-08", 10500)

    assert result == {"name": "SSA-NEW", "base": 10500.0, "from_date": date(2026, 8, 1)}
    assert captured["company"] == "Rayher"
    assert captured["base"] == 10500.0
    assert captured["insert"] is True and captured["submit"] is True

def test_working_days_falls_back_to_employment_calendar_when_holiday_list_is_missing(monkeypatch):
    module, frappe = _load(monkeypatch)

    class Slip:
        def update(self, values):
            self.values = values

        def get_working_days_details(self):
            raise PayrollRuleError("Please set a default Holiday List")

    frappe.new_doc = lambda doctype: Slip()
    result = module._working_days(
        "EMP-1", "Rayher", date(2026, 8, 1), date(2026, 8, 31),
        date(2026, 8, 10), date(2026, 8, 20),
    )

    assert result == (31.0, 11.0, "calendar_fallback")

def test_social_record_uses_employee_company_on_mixed_company_batch(monkeypatch):
    module, frappe = _load(monkeypatch)
    calls = []

    def get_value(doctype, filters, fields=None, as_dict=False, **kwargs):
        calls.append((doctype, filters))
        if doctype == "Employee":
            return "示例研发中心"
        if doctype == "Social Insurance Import Batch":
            assert filters == {"period": "2026-07", "is_current": 1}
            return "SIB-1"
        if doctype == "Social Insurance Import Row":
            assert filters["batch"] == "SIB-1"
            assert filters["company"] == "示例研发中心"
            assert filters["status"] == ["in", ["Matched", "Confirmed Difference"]]
            return {"name": "SIR-1", "employee_total": 1020}
        raise AssertionError(doctype)

    frappe.db.get_value = get_value
    assert module._social_record("EMP-1", "2026-07", ["name", "employee_total"]) == {
        "name": "SIR-1", "employee_total": 1020
    }
    assert not any(call[0] == "Employee Social Insurance" for call in calls)


@pytest.mark.parametrize("managed,docstatus", [(1, 1), (0, 1), (0, 0)])
def test_saved_salary_is_not_recalculated_from_changed_hr_data(monkeypatch, managed, docstatus):
    module, _ = _load(monkeypatch)
    def forbidden(*args, **kwargs): raise AssertionError("must not read current HR data")
    for name in ("_social_record", "_monthly_record", "_working_days", "_assignment", "_accommodation"):
        monkeypatch.setattr(module, name, forbidden)
    slip = SimpleNamespace(name="SAL-SAVED", docstatus=docstatus, hr_spa_managed=managed,
        net_pay=9000, total_deduction=1000, gross_pay=10000,
        company="Historical Company", bank_account_no="historical-bank",
        earnings=[SimpleNamespace(salary_component="基本工资", amount=10000)],
        deductions=[SimpleNamespace(salary_component="社保个人", amount=1000)])
    result = module._row({"name": "EMP-1", "company": "New company"}, "2026-08", None, None, slip)
    assert result["net_pay"] == 9000
    assert result["social_insurance"] == 1000
    assert result["company"] == "Historical Company"
    assert result["bank_ac_no"] == "historical-bank"
    assert result["employee_pension"] is None
    assert result["amount_source"] == "salary_slip"
