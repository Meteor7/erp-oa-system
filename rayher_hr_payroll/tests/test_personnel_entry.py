import importlib
import sys
import types
from types import SimpleNamespace


class RuleError(Exception):
    pass


def _install_fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.only_for = lambda roles: None
    frappe.has_permission = lambda *args, **kwargs: True
    frappe.get_roles = lambda user=None: ["System Manager"]
    frappe.session = SimpleNamespace(user="Administrator")

    def throw(message):
        raise RuleError(str(message))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.throw = throw
    frappe.whitelist = whitelist
    frappe.db = SimpleNamespace(commit=lambda: None)
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe


def _load_personnel_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.personnel_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.personnel_entry")
    return mod, frappe


def test_list_employees_returns_relieving_date_without_status_filter(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))

    def get_all(doctype, fields=None, order_by=None, **kwargs):
        captured["doctype"] = doctype
        captured["fields"] = fields
        captured["order_by"] = order_by
        captured["kwargs"] = kwargs
        return []

    frappe.get_all = get_all

    assert mod.list_employees() == []

    assert captured["roles"] == mod.RD_HR_WRITE
    assert captured["doctype"] == "Employee"
    assert "relieving_date" in captured["fields"]
    assert "designation" in captured["fields"]
    assert captured["kwargs"].get("filters") in (None, {})


def test_get_designation_options_returns_position_names(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, pluck=None, order_by=None, **kwargs):
        assert doctype == "Designation"
        assert pluck == "name"
        assert order_by == "name"
        return ["工程师", "财务主管"]

    frappe.get_all = get_all

    assert mod.get_designation_options() == ["工程师", "财务主管"]


def test_get_employment_type_options_returns_master_names(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.get_all = lambda doctype, pluck=None, order_by=None: ["劳动合同", "实习协议"]

    assert mod.get_employment_type_options() == ["劳动合同", "实习协议"]

def test_save_employee_sets_left_status_when_relieving_date_is_saved(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    class FakeDoc:
        name = "EMP-LEFT"

        def update(self, values):
            captured["values"] = dict(values)

        def save(self, ignore_permissions=False):
            captured["saved"] = ignore_permissions

    frappe.get_doc = lambda doctype, name=None: FakeDoc()

    result = mod.save_employee(
        name="EMP-LEFT",
        employee_name="Left Employee",
        relieving_date="2026-06-17",
        designation="工程师",
    )

    assert result == {"name": "EMP-LEFT"}
    assert captured["values"]["relieving_date"] == "2026-06-17"
    assert captured["values"]["status"] == "Left"
    assert captured["values"]["designation"] == "工程师"
    assert captured["saved"] is True


def test_list_employees_includes_reference_template_and_default_base_fields(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, fields=None, **kwargs):
        captured[doctype] = fields
        return []

    frappe.get_all = get_all
    mod.list_employees()

    assert {
        "company", "english_name", "default_monthly_salary", "salary_months",
        "first_education_level", "first_education_school", "first_education_major",
        "education_level_cn", "graduation_school", "major_cn", "cell_number",
        "bank_name", "bank_ac_no", "default_social_insurance_base",
        "default_housing_fund_base", "employee_number", "date_of_birth", "reports_to",
        "employment_type", "labour_contract_start_date", "probation_months",
        "probation_end_date", "degree_cn", "education_completion_type",
        "household_registration", "id_type_cn", "social_insurance_number",
        "housing_fund_number",
    }.issubset(set(captured["Employee"]))


def test_save_employee_updates_reference_template_fields(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda doctype, name: doctype == "Company" and name == "示例企业技术"

    class FakeDoc:
        name = "EMP-REF"

        def update(self, values):
            captured.update(values)

        def save(self, ignore_permissions=False):
            assert ignore_permissions is True

    frappe.get_doc = lambda doctype, name=None: FakeDoc()

    mod.save_employee(
        name="EMP-REF", employee_name="演示员工129", company="示例企业技术", english_name="Zhang San",
        default_monthly_salary=10000, salary_months=14,
        first_education_level="本科", first_education_school="A大学", first_education_major="电子",
        education_level_cn="硕士", graduation_school="B大学", major_cn="微电子",
        cell_number="13800000002", bank_name="中国银行深圳支行", bank_ac_no="62220001",
        default_social_insurance_base=8000, default_housing_fund_base=9000,
    )

    assert captured["company"] == "示例企业技术"
    assert captured["english_name"] == "Zhang San"
    assert captured["default_monthly_salary"] == 10000
    assert captured["salary_months"] == 14
    assert captured["first_education_school"] == "A大学"
    assert captured["graduation_school"] == "B大学"
    assert captured["cell_number"] == "13800000002"
    assert captured["bank_ac_no"] == "62220001"
    assert captured["default_social_insurance_base"] == 8000
    assert captured["default_housing_fund_base"] == 9000


def test_save_employee_rejects_negative_base_and_fractional_salary_months(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda *args: True

    for kwargs in (
        {"default_monthly_salary": -1},
        {"default_social_insurance_base": -1},
        {"default_housing_fund_base": -1},
        {"salary_months": 12.5},
    ):
        try:
            mod.save_employee(name="EMP-1", employee_name="员工", company="Rayher", **kwargs)
        except RuleError:
            pass
        else:
            raise AssertionError(f"invalid employee values accepted: {kwargs}")

def test_company_options_use_formal_names_and_supported_companies(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def get_all(doctype, fields=None, order_by=None, filters=None):
        assert doctype == "Company"
        assert fields == ["name", "company_name"]
        return [
            {"name": "Rayher", "company_name": "Rayher"},
            {"name": "示例研发中心", "company_name": "示例研发中心"},
            {"name": "Other", "company_name": "Other"},
        ]

    frappe.get_all = get_all
    assert mod.get_company_options() == [
        {"name": "Rayher", "company_name": "Rayher", "display_name": "示例总部"},
        {"name": "示例研发中心", "company_name": "示例研发中心", "display_name": "示例研发中心"},
    ]


def test_household_options_are_explicit(monkeypatch):
    mod, _frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    assert mod.get_household_options() == [
        "深圳", "广东省内城镇", "广东省内农村", "广东省外城镇", "广东省外农村",
    ]


def test_save_employee_accepts_explicit_legacy_household(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda *args, **kwargs: True
    saved = {}

    class Doc:
        name = "EMP-1"

        def update(self, values):
            saved.update(values)

        def save(self, ignore_permissions=False):
            return self

    frappe.get_doc = lambda *_args, **_kwargs: Doc()
    mod.save_employee(name="EMP-1", household_registration="湖北省襄阳市")
    assert saved["household_registration"] == "湖北省襄阳市"


def test_save_employee_rejects_unknown_household(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.exists = lambda *args, **kwargs: True
    try:
        mod.save_employee(name="EMP-1", household_registration="待确认")
    except RuleError as exc:
        assert "户口信息" in str(exc)
    else:
        raise AssertionError("unknown household value was accepted")


def test_list_employees_adds_household_classification(monkeypatch):
    mod, frappe = _load_personnel_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.get_all = lambda *args, **kwargs: [
        {"name": "A", "household_registration": "深圳"},
        {"name": "B", "household_registration": "广东省外农村"},
        {"name": "C", "household_registration": "非深城镇"},
        {"name": "D", "household_registration": "湖北省襄阳市"},
        {"name": "E", "household_registration": None},
    ]
    rows = mod.list_employees()
    assert [row["household_classification"] for row in rows] == [
        "深户", "非深户", "非深户", "非深户", "待完善"
    ]
