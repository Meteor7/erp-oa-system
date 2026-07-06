import importlib
import sys
import types
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

PLM_ACTIVITY_TYPES = (
    "\u9700\u6c42\u5206\u6790",
    "\u65b9\u6848\u8bbe\u8ba1",
    "\u7f16\u7801\u5f00\u53d1",
    "\u4ee3\u7801\u8bc4\u5ba1",
    "\u5355\u5143\u6d4b\u8bd5",
    "\u96c6\u6210\u6d4b\u8bd5",
    "\u7f3a\u9677\u4fee\u590d",
    "\u6280\u672f\u8c03\u7814",
    "\u6587\u6863\u7f16\u5199",
    "\u9879\u76ee\u4f1a\u8bae",
    "\u6280\u672f\u5206\u4eab",
    "\u8fd0\u7ef4\u652f\u6301",
    "\u5176\u4ed6",
)


class RuleError(Exception):
    pass


def _getdate(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).split()[0]
    return date.fromisoformat(text)


def _get_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value)
    if len(text) == 10:
        text += " 00:00:00"
    return datetime.fromisoformat(text.replace(" ", "T"))


def _add_month(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    return dt.replace(year=year, month=month)


def _add_to_date(value, months=0, seconds=0):
    dt = _get_datetime(value)
    if months:
        dt = _add_month(dt, months)
    if seconds:
        dt = dt + timedelta(seconds=seconds)
    return dt


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
    frappe.utils = types.ModuleType("frappe.utils")
    frappe.utils.getdate = _getdate
    frappe.utils.get_datetime = _get_datetime
    frappe.utils.add_to_date = _add_to_date
    frappe.db = SimpleNamespace()

    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe.utils)
    return frappe


def _load_timesheet_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.timesheet_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.timesheet_entry")
    return mod, frappe


def test_plm_activity_types_are_declared_in_backend(monkeypatch):
    mod, _frappe = _load_timesheet_entry(monkeypatch)

    assert mod.RD_ACTIVITY_TYPES == PLM_ACTIVITY_TYPES


def test_get_rd_options_syncs_activity_types_and_returns_project_codes(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    created = []

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    def exists(doctype, name_or_filters=None):
        if doctype == "Activity Type":
            return False
        return False

    def get_doc(doc):
        return SimpleNamespace(
            insert=lambda ignore_permissions=False: created.append(doc["activity_type"])
        )

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        if doctype == "Employee":
            return [{"name": "EMP-1", "employee_name": "Zhang San"}]
        if doctype == "Project":
            assert "rd_project_code" in fields
            assert "rd_project_key" in fields
            return [{
                "name": "PROJ-1",
                "project_name": "New Product",
                "rd_project_code": "RD-001",
                "rd_project_key": "RD-001 | New Product",
            }]
        raise AssertionError(doctype)

    frappe.db.exists = exists
    frappe.get_doc = get_doc
    frappe.get_all = get_all

    data = mod.get_rd_options()

    assert created == list(PLM_ACTIVITY_TYPES)
    assert data["activity_types"] == [{"name": item} for item in PLM_ACTIVITY_TYPES]
    assert data["projects"] == [{
        "name": "PROJ-1",
        "project_name": "New Product",
        "rd_project_code": "RD-001",
        "rd_project_key": "RD-001 | New Product",
    }]


def test_save_rd_hours_writes_date_activity_description_and_project_code_to_timesheet(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_period_has_submitted_allocation", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "list_rd_hours", lambda period: [{"period": period, "ok": True}])

    frappe.has_permission = lambda *args, **kwargs: True
    frappe.db.exists = lambda *args, **kwargs: False
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"

    def get_value(doctype, name_or_filters, fieldname=None, **kwargs):
        if doctype == "Employee" and fieldname == "rd_personnel_type":
            return mod.RD_TYPES[0]
        if doctype == "Employee" and fieldname == "company":
            return "Rayher"
        if doctype == "Employee" and fieldname == "name":
            return name_or_filters
        if doctype == "Project" and fieldname == "allow_rd_timesheet":
            return 1
        if doctype == "Project" and fieldname == "rd_project_code":
            return "RD-001"
        return None

    def sql(query, values=None, pluck=False, as_dict=False):
        if pluck:
            return []
        if as_dict:
            return []
        return []

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "Activity Type":
            return SimpleNamespace(insert=lambda ignore_permissions=False: None)
        if isinstance(arg, dict) and arg.get("doctype") == "Timesheet":
            captured["doc"] = arg
            return SimpleNamespace(
                flags=SimpleNamespace(),
                insert=lambda ignore_permissions=False: captured.setdefault("inserted", ignore_permissions),
                submit=lambda: captured.setdefault("submitted", True),
            )
        raise AssertionError(arg)

    def get_all(doctype, filters=None, pluck=None, limit=None, **kwargs):
        if doctype == "Project":
            assert filters == {
                "rd_project_code": "RD-001",
                "project_name": "\u7814\u53d1\u9879\u76eeA",
                "allow_rd_timesheet": 1,
            }
            assert pluck == "name"
            return ["PROJ-1"]
        return []

    frappe.db.get_value = get_value
    frappe.db.sql = sql
    frappe.get_all = get_all
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.save_rd_hours(
        period="2026-07",
        employee="EMP-1",
        project="PROJ-1",
        hours=3.5,
        work_date="2026-07-02",
        activity_type="\u7f16\u7801\u5f00\u53d1",
        description="\u5b8c\u6210\u63a5\u53e3\u8054\u8c03",
        project_code="RD-001",
        project_name="\u7814\u53d1\u9879\u76eeA",
    )

    assert result == [{"period": "2026-07", "ok": True}]
    detail = captured["doc"]["time_logs"][0]
    assert captured["doc"]["employee"] == "EMP-1"
    assert detail["project"] == "PROJ-1"
    assert detail["rd_project_code"] == "RD-001"
    assert detail["rd_project_name"] == "\u7814\u53d1\u9879\u76eeA"
    assert detail["rd_project_key"] == "RD-001 | \u7814\u53d1\u9879\u76eeA"
    assert detail["hours"] == 3.5
    assert detail["activity_type"] == "\u7f16\u7801\u5f00\u53d1"
    assert detail["description"] == "\u5b8c\u6210\u63a5\u53e3\u8054\u8c03"
    assert detail["from_time"].date().isoformat() == "2026-07-02"
    assert captured["submitted"] is True


def test_save_rd_hours_rejects_unknown_project_code_and_name(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_period_has_submitted_allocation", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "list_rd_hours", lambda period: [{"period": period, "ok": True}])

    frappe.has_permission = lambda *args, **kwargs: True
    frappe.db.exists = lambda *args, **kwargs: False
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"

    def get_value(doctype, name_or_filters, fieldname=None, **kwargs):
        if doctype == "Employee" and fieldname == "rd_personnel_type":
            return mod.RD_TYPES[0]
        if doctype == "Employee" and fieldname == "company":
            return "Rayher"
        if doctype == "Employee" and fieldname == "name":
            return name_or_filters
        return None

    def get_all(doctype, filters=None, pluck=None, limit=None, **kwargs):
        if doctype == "Project" and filters == {
            "rd_project_code": "003",
            "project_name": "新项目",
            "allow_rd_timesheet": 1,
        }:
            return []
        return []

    frappe.db.get_value = get_value
    frappe.get_all = get_all
    frappe.get_doc = lambda doc: SimpleNamespace(insert=lambda ignore_permissions=False: None)

    with pytest.raises(RuleError, match="项目管理"):
        mod.save_rd_hours(
            period="2026-07",
            employee="EMP-1",
            project="",
            hours=2,
            work_date="2026-07-02",
            activity_type="编码开发",
            description="work",
            project_code="003",
            project_name="新项目",
        )

def test_install_syncs_rd_activity_types_on_migrate():
    source = Path("rayher_hr_payroll/install.py").read_text(encoding="utf-8")

    assert "ensure_rd_activity_types" in source



def test_timesheet_entry_roles_include_employee_and_department_manager(monkeypatch):
    mod, _frappe = _load_timesheet_entry(monkeypatch)

    assert "Employee" in mod.RD_TIMESHEET_ENTRY_ROLES
    assert "Department Manager" in mod.RD_TIMESHEET_ENTRY_ROLES


def test_department_manager_options_are_scoped_to_self_and_direct_reports(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {"employee_filters": []}

    monkeypatch.setattr(mod, "ensure_rd_activity_types", lambda: None)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    frappe.session = SimpleNamespace(user="manager@legacy-business.example.invalid")
    frappe.get_roles = lambda user=None: ["Employee", "Department Manager"]

    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype == "Employee" and filters == {"user_id": "manager@legacy-business.example.invalid"} and fieldname == "name":
            return "MGR"
        return None

    def get_all(doctype, filters=None, fields=None, order_by=None, pluck=None, **kwargs):
        if doctype == "Employee" and pluck == "name":
            assert filters == {"reports_to": "MGR"}
            return ["EMP-1"]
        if doctype == "Employee":
            captured["employee_filters"].append(filters)
            return []
        if doctype == "Project":
            return []
        raise AssertionError(doctype)

    frappe.db.get_value = get_value
    frappe.get_all = get_all

    mod.get_rd_options()

    assert captured["roles"] == mod.RD_TIMESHEET_VIEW_ROLES
    employee_filter = captured["employee_filters"][0]
    assert set(employee_filter["name"][1]) == {"MGR", "EMP-1"}


def test_finance_options_are_view_only_and_unscoped(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {"employee_filters": []}

    monkeypatch.setattr(mod, "ensure_rd_activity_types", lambda: None)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    frappe.session = SimpleNamespace(user="finance@legacy-business.example.invalid")
    frappe.get_roles = lambda user=None: ["Accounts User"]
    frappe.db.get_value = lambda *args, **kwargs: None

    def get_all(doctype, filters=None, fields=None, order_by=None, pluck=None, **kwargs):
        if doctype == "Employee":
            captured["employee_filters"].append(filters)
            return []
        if doctype == "Project":
            return []
        raise AssertionError(doctype)

    frappe.get_all = get_all

    mod.get_rd_options()

    assert captured["roles"] == mod.RD_TIMESHEET_VIEW_ROLES
    assert "name" not in captured["employee_filters"][0]


def test_save_rd_hours_stays_edit_role_gated(monkeypatch):
    mod, _frappe = _load_timesheet_entry(monkeypatch)
    captured = {}

    def deny(roles):
        captured["roles"] = roles
        raise RuleError("blocked")

    monkeypatch.setattr(mod, "require_rd_access", deny)

    with pytest.raises(RuleError, match="blocked"):
        mod.save_rd_hours(period="2026-07", employee="EMP-1", project_code="001", project_name="RD")

    assert captured["roles"] == mod.RD_TIMESHEET_ENTRY_ROLES

def test_save_rd_hours_rejects_employee_daily_total_over_eight_hours(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_period_has_submitted_allocation", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "list_rd_hours", lambda period: [])
    monkeypatch.setattr(mod, "_resolve_rd_project", lambda code, name, selected_project=None: "PROJ-1")

    frappe.has_permission = lambda *args, **kwargs: True
    frappe.db.exists = lambda *args, **kwargs: False
    frappe.db.get_single_value = lambda *args, **kwargs: "Rayher"

    def get_value(doctype, name_or_filters, fieldname=None, **kwargs):
        if doctype == "Employee" and fieldname == "rd_personnel_type":
            return mod.RD_TYPES[0]
        if doctype == "Employee" and fieldname == "company":
            return "Rayher"
        if doctype == "Employee" and fieldname == "name":
            return name_or_filters
        return None

    def sql(query, values=None, pluck=False, as_dict=False):
        if pluck:
            return []
        if as_dict:
            assert values["work_date"] == date(2026, 7, 2)
            return [SimpleNamespace(
                from_time=datetime(2026, 7, 2, 9, 0, 0),
                to_time=datetime(2026, 7, 2, 15, 0, 0),
            )]
        return []

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "Activity Type":
            return SimpleNamespace(insert=lambda ignore_permissions=False: None)
        if isinstance(arg, dict) and arg.get("doctype") == "Timesheet":
            captured["doc"] = arg
            return SimpleNamespace(
                flags=SimpleNamespace(),
                insert=lambda ignore_permissions=False: captured.setdefault("inserted", ignore_permissions),
                submit=lambda: captured.setdefault("submitted", True),
            )
        raise AssertionError(arg)

    frappe.db.get_value = get_value
    frappe.db.sql = sql
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    with pytest.raises(RuleError, match="8"):
        mod.save_rd_hours(
            period="2026-07",
            employee="EMP-1",
            project="PROJ-1",
            hours=3,
            work_date="2026-07-02",
            activity_type=PLM_ACTIVITY_TYPES[2],
            description="work",
            project_code="001",
            project_name="RD-CAP",
        )

    assert "doc" not in captured

def test_get_rd_hour_summary_calculates_plm_metrics_for_selected_employee(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "_visible_employee_names", lambda include_finance=False: None)

    def sql(query, values=None, as_dict=False, **kwargs):
        captured["values"] = values
        assert "ts.employee = %(employee)s" in query
        assert as_dict is True
        return [
            SimpleNamespace(employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 1), hours=4),
            SimpleNamespace(employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 1), hours=2),
            SimpleNamespace(employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 2), hours=8),
        ]

    frappe.db.sql = sql

    data = mod.get_rd_hour_summary("2026-07", employee="EMP-1")

    assert captured["roles"] == mod.RD_TIMESHEET_VIEW_ROLES
    assert captured["values"]["employee"] == "EMP-1"
    assert data == {
        "employee": "EMP-1",
        "employee_name": "Zhang Jun",
        "total_hours": 14.0,
        "filled_days": 2,
        "average_hours": 7.0,
        "standard_hours": 16.0,
        "standard_delta": -2.0,
    }


def test_get_rd_hour_summary_rejects_invisible_employee(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_visible_employee_names", lambda include_finance=False: ["EMP-SELF"])
    frappe.db.sql = lambda *args, **kwargs: []

    with pytest.raises(RuleError, match="无权"):
        mod.get_rd_hour_summary("2026-07", employee="EMP-OTHER")
