import importlib
import sys
import types
from datetime import date
from types import SimpleNamespace

import pytest


class PayrollRuleError(Exception):
    pass


class FakeInputs:
    """payroll_inputs 的替身：工时、社保公积金、个税累计都给固定的数（个税用真的累计预扣算法）。"""

    def __init__(self, social=None, fund=None, total=176.0, actual=176.0, leave=0.0, basis=None):
        self.social = {"employee_total": 300, "company_total": 900, "source": "社保月度记录"} if social is None else social
        self.fund = {"employee_amount": 200, "company_amount": 200, "source": "公积金月度记录"} if fund is None else fund
        self.hours = {"total_hours": total, "employed_hours": actual + leave, "personal_leave_hours": leave, "actual_hours": actual,
                      "work_days": int(total // 8), "calendar_source": "company_holiday_list"}
        self.basis = basis or {"tax_period": "2026-11", "year": 2026, "prior": {}, "low_income": False, "special_additional": 0,
                               "other": 0, "bonus_used": False, "has_profile": True, "warnings": []}
        self.materialized = []

    def contributions(self, employee_row, period):
        return {"social": dict(self.social), "fund": dict(self.fund)}

    def work_hours(self, employee, company, period, calendars=None):
        return dict(self.hours)

    def tax_basis(self, employee, company, period, exclude=None):
        return dict(self.basis)

    def compute_tax(self, basis, payable, social, fund, bonus, bonus_separate):
        import importlib
        return importlib.import_module("rayher_hr_payroll.payroll_inputs").compute_tax(basis, payable, social, fund, bonus, bonus_separate)

    def materialize(self, employee_row, period, found):
        self.materialized.append(period)


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
        total_hours=168, actual_hours=160, base_salary=10000, salary_adjustment=500,
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


def test_calculation_rejects_hours_above_total_and_negative_advance(monkeypatch):
    module, _ = _load(monkeypatch)
    base = dict(total_hours=168, actual_hours=160, base_salary=10000, salary_adjustment=0, company_subsidy=0, bonus=0, other_adjustment=0, social_insurance=0, housing_fund=0, income_tax=0, accommodation=0, advanced_paid=0)

    with pytest.raises(PayrollRuleError, match="实际工时"):
        module._calculate_amounts(**{**base, "actual_hours": 169})
    with pytest.raises(PayrollRuleError, match="已发放"):
        module._calculate_amounts(**{**base, "advanced_paid": -1})


def test_period_employee_query_includes_people_who_left_during_month(monkeypatch):
    module, _ = _load(monkeypatch)
    filters, or_filters = module._period_employee_filters(date(2026, 8, 1), date(2026, 8, 31))

    assert filters == {"date_of_joining": ["<=", date(2026, 8, 31)]}
    assert or_filters == [["relieving_date", "is", "not set"], ["relieving_date", ">=", date(2026, 8, 1)]]


def test_missing_social_or_housing_is_not_treated_as_zero(monkeypatch):
    module, _ = _load(monkeypatch)

    with pytest.raises(PayrollRuleError, match="社保算不出来：员工档案里没有社保基数"):
        module._require_contributions({"social": {"missing": "员工档案里没有社保基数"}, "fund": {"employee_amount": 1}})
    with pytest.raises(PayrollRuleError, match="公积金"):
        module._require_contributions({"social": {"employee_total": 1}, "fund": {"missing": "员工档案里没有公积金基数"}})


def test_only_spa_managed_draft_can_be_updated(monkeypatch):
    module, _ = _load(monkeypatch)

    assert module._assert_writable_slip(SimpleNamespace(docstatus=0, hr_spa_managed=1, name="SAL-1")) is None
    with pytest.raises(PayrollRuleError, match="其他来源"):
        module._assert_writable_slip(SimpleNamespace(docstatus=0, hr_spa_managed=0, name="SAL-X"))
    with pytest.raises(PayrollRuleError, match="已确认，不能修改；要改请先撤回确认"):
        module._assert_writable_slip(SimpleNamespace(docstatus=1, hr_spa_managed=1, name="SAL-SUB"))


def test_company_specific_structure_never_falls_back_to_other_company(monkeypatch):
    module, frappe = _load(monkeypatch)
    frappe.db.get_value = lambda doctype, filters, field=None: "标准月薪 - 示例研发科技" if filters == {"name": "标准月薪 - 示例研发科技", "company": "示例研发科技", "is_active": "Yes", "docstatus": 1} else None

    assert module._existing_structure_for_company("示例研发科技") == "标准月薪 - 示例研发科技"
    assert module._structure_name("乔岳科技") == "标准月薪 - 乔岳科技"


def test_apply_salary_adjustment_rejects_same_date_assignment_without_overwrite(monkeypatch):
    module, frappe = _load(monkeypatch)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "QIHENG Demo"})
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪"})
    frappe.db.get_value = lambda doctype, filters, field=None: "SSA-EXISTING" if doctype == "Salary Structure Assignment" else None

    with pytest.raises(PayrollRuleError, match="已有工资分配"):
        module.apply_salary_adjustment("EMP-1", "2026-08", 10500)


def test_apply_salary_adjustment_creates_submitted_assignment_for_employee_company(monkeypatch):
    module, frappe = _load(monkeypatch)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "QIHENG Demo"})
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
    assert captured["company"] == "QIHENG Demo"
    assert captured["base"] == 10500.0
    assert captured["insert"] is True and captured["submit"] is True

@pytest.mark.parametrize("managed,docstatus", [(1, 1), (0, 1), (0, 0)])
def test_saved_salary_is_not_recalculated_from_changed_hr_data(monkeypatch, managed, docstatus):
    module, _ = _load(monkeypatch)
    def forbidden(*args, **kwargs): raise AssertionError("must not read current HR data")
    for name in ("_inputs", "_assignment", "_accommodation"):
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


class NewSlip:
    name = "NEW"
    default_series = ""
    def update(self, values): self.__dict__.update(values)
    def set(self, table, rows): setattr(self, table, list(rows))
    def append(self, table, row): getattr(self, table).append(row)
    def insert(self, ignore_permissions=False): self.inserted = True


def _draft_world(monkeypatch, module, frappe, inputs):
    monkeypatch.setattr(module, "_inputs", lambda: inputs)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "QIHENG Demo", "employee_name": "南通工厂8"})
    monkeypatch.setattr(module, "_accommodation", lambda *args: 150)
    monkeypatch.setattr(module, "_slip", lambda *args: None)
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪 - QIHENG Demo"})
    slip = NewSlip()
    frappe.new_doc = lambda doctype: slip
    return slip


def test_draft_prorates_by_hours_and_withholds_tax_cumulatively(monkeypatch):
    """决定 2026-10-14：基本工资 × 实际工时 ÷ 总工时；社保公积金后扣个税（累计预扣）；工资条记下全部中间数。"""
    module, frappe = _load(monkeypatch)
    inputs = FakeInputs(social={"employee_total": 1020, "company_total": 3000, "source": "按档案基数 10000"},
                        fund={"employee_amount": 700, "company_amount": 700, "source": "按档案基数 10000 × 7%"},
                        total=176, actual=160, leave=16)
    slip = _draft_world(monkeypatch, module, frappe, inputs)
    result = module.save_payroll_draft("E1", "2026-10", base_salary=11000, income_tax=999)
    # 11000 × 160 / 176 = 10000；(10000 − 5000 − 1720) × 3% = 98.4；传进来的 999 不算（没勾手动）
    assert result["prorated_base"] == 10000.0 and result["income_tax"] == 98.4
    assert (slip.hr_total_hours, slip.hr_actual_hours, slip.hr_personal_leave_hours, slip.hr_hours_manual) == (176, 160, 16, 0)
    assert (slip.payment_days, slip.total_working_days) == (20.0, 22.0)
    assert slip.hr_tax_period == "2026-11" and slip.hr_tax_cum_taxable == 3280.0 and slip.hr_tax_manual == 0
    assert (slip.hr_social_company, slip.hr_fund_company) == (3000.0, 700.0) and slip.hr_amounts_v2 == 1
    assert {line["salary_component"]: line["amount"] for line in slip.deductions} == {
        "社保个人": 1020.0, "公积金个人": 700.0, "宿舍扣款": 150.0, "个税": 98.4}
    assert slip.net_pay == round(10000 - 1020 - 700 - 150 - 98.4, 2) and inputs.materialized == ["2026-10"]


def test_manual_tax_and_hours_need_a_reason_and_are_kept(monkeypatch):
    module, frappe = _load(monkeypatch)
    slip = _draft_world(monkeypatch, module, frappe, FakeInputs(total=176, actual=176))
    with pytest.raises(PayrollRuleError, match="手动改个税要写原因"):
        module.save_payroll_draft("E1", "2026-10", base_salary=8800, income_tax=50, tax_manual=1)
    module.save_payroll_draft("E1", "2026-10", base_salary=8800, income_tax=50, tax_manual=1, tax_manual_reason="按扣缴客户端",
                              hours_manual=1, actual_hours=88)
    assert slip.hr_income_tax == 50.0 and slip.hr_tax_manual == 1 and slip.hr_tax_manual_reason == "按扣缴客户端"
    assert slip.hr_actual_hours == 88.0 and slip.hr_hours_manual == 1 and slip.hr_prorated_base == 4400.0


def test_separate_bonus_can_only_be_used_once_a_year(monkeypatch):
    module, frappe = _load(monkeypatch)
    inputs = FakeInputs()
    inputs.basis["bonus_used"] = True
    _draft_world(monkeypatch, module, frappe, inputs)
    with pytest.raises(PayrollRuleError, match="一年只能用一次"):
        module.save_payroll_draft("E1", "2026-10", base_salary=8800, bonus=20000, bonus_separate=1)


def test_missing_contributions_block_the_draft(monkeypatch):
    module, frappe = _load(monkeypatch)
    _draft_world(monkeypatch, module, frappe, FakeInputs(social={"missing": "示例研发中心 2026 年的社保政策还没配置"}))
    with pytest.raises(PayrollRuleError, match="社保政策还没配置"):
        module.save_payroll_draft("E1", "2026-10", base_salary=8800)
