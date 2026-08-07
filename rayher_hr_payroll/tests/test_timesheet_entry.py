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
    "\u8c03\u4f11",
    "\u8bf7\u5047",
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
    frappe.db.exists = lambda *args, **kwargs: False

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
            assert filters == {"allow_rd_timesheet": 1, "status": ["not in", ["Completed", "Cancelled"]]}
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
                "status": ["not in", ["Completed", "Cancelled"]],
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
            "status": ["not in", ["Completed", "Cancelled"]],
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



def test_timesheet_entry_write_roles_are_manager_only_while_employee_and_finance_can_view(monkeypatch):
    mod, _frappe = _load_timesheet_entry(monkeypatch)

    assert "Department Manager" in mod.RD_TIMESHEET_ENTRY_ROLES
    assert "Employee" not in mod.RD_TIMESHEET_ENTRY_ROLES
    assert "Accounts User" not in mod.RD_TIMESHEET_ENTRY_ROLES
    assert "Employee" in mod.RD_TIMESHEET_VIEW_ROLES
    assert "Accounts User" in mod.RD_TIMESHEET_VIEW_ROLES


def test_all_project_access_does_not_expand_employee_timesheet_scope(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    frappe.session = SimpleNamespace(user="person070@staff.example.invalid")
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner", "All Project Access"]
    frappe.db.get_value = lambda *args, **kwargs: "EMP-ZHANG"

    assert mod._visible_employee_names() == ["EMP-ZHANG"]
    with pytest.raises(RuleError):
        mod._require_visible_employee("EMP-OTHER")


def test_project_owner_without_all_project_access_remains_self_scoped(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    frappe.session = SimpleNamespace(user="person041@staff.example.invalid")
    frappe.get_roles = lambda user=None: ["Employee", "Project Owner"]
    frappe.db.get_value = lambda *args, **kwargs: "EMP-OWNER"

    assert mod._visible_employee_names() == ["EMP-OWNER"]
    with pytest.raises(RuleError):
        mod._require_visible_employee("EMP-OTHER")


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


def test_daily_save_rejects_employee_month_with_monthly_entries(monkeypatch):
    mod, _frappe = _load_timesheet_entry(monkeypatch)

    monkeypatch.setattr(mod, "_require_visible_employee", lambda employee: None)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7))
    monkeypatch.setattr(mod, "_work_date_in_period", lambda value, year, month: date(2026, 7, 1))
    monkeypatch.setattr(mod, "_month_has_monthly_entries", lambda *args: True, raising=False)

    with pytest.raises(RuleError, match="按月工时"):
        mod._save_rd_hours_row(
            period="2026-07",
            employee="EMP-1",
            project="PROJ-1",
            project_code="RD14",
            project_name="ACONCA 7961",
            hours=8,
            work_date="2026-07-01",
        )


def test_daily_save_rechecks_monthly_entries_after_employee_lock(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = _prepare_zero_hour_save(mod, frappe, monkeypatch, "请假")
    checks = iter([False, True])
    monkeypatch.setattr(mod, "_month_has_monthly_entries", lambda *args: next(checks), raising=False)

    with pytest.raises(RuleError, match="按月工时"):
        mod._save_rd_hours_row(
            period="2026-07",
            employee="EMP-1",
            project="PROJ-1",
            project_code="RD14",
            project_name="ACONCA 7961",
            hours=0,
            work_date="2026-07-01",
            activity_type="请假",
        )

    assert "doc" not in captured

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
            SimpleNamespace(timesheet="TS-D1", employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 1), hours=4, rd_system_generated=0, rd_occurrence_days=0),
            SimpleNamespace(timesheet="TS-D2", employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 1), hours=2, rd_system_generated=0, rd_occurrence_days=0),
            SimpleNamespace(timesheet="TS-M1", employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 2), hours=8, rd_system_generated=1, rd_occurrence_days=1.25),
            SimpleNamespace(timesheet="TS-M1", employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 3), hours=2, rd_system_generated=1, rd_occurrence_days=1.25),
        ]

    frappe.db.sql = sql

    data = mod.get_rd_hour_summary("2026-07", employee="EMP-1")

    assert captured["roles"] == mod.RD_TIMESHEET_VIEW_ROLES
    assert captured["values"]["employee"] == "EMP-1"
    assert data == {
        "employee": "EMP-1",
        "employee_name": "Zhang Jun",
        "total_hours": 16.0,
        "filled_days": 2.25,
        "average_hours": 7.11,
        "standard_hours": 18.0,
        "standard_delta": -2.0,
    }


def test_get_rd_hour_summary_for_all_employees_uses_employee_days_and_max_filled_days(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_visible_employee_names", lambda include_finance=False: None)

    def sql(query, values=None, as_dict=False, **kwargs):
        assert "ts.employee = %(employee)s" not in query
        assert as_dict is True
        return [
            SimpleNamespace(employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 1), hours=8),
            SimpleNamespace(employee="EMP-1", employee_name="Zhang Jun", work_date=date(2026, 7, 2), hours=8),
            SimpleNamespace(employee="EMP-2", employee_name="Li Si", work_date=date(2026, 7, 1), hours=8),
            SimpleNamespace(employee="EMP-3", employee_name="Wang Wu", work_date=date(2026, 7, 2), hours=4),
        ]

    frappe.db.sql = sql

    data = mod.get_rd_hour_summary("2026-07")

    assert data == {
        "employee": None,
        "employee_name": "",
        "total_hours": 28.0,
        "filled_days": 2,
        "average_hours": 7.0,
        "standard_hours": 32.0,
        "standard_delta": -4.0,
    }


def test_list_rd_hours_accepts_employee_filter(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "_visible_employee_names", lambda include_finance=False: None)

    def sql(query, values=None, as_dict=False, **kwargs):
        captured["query"] = query
        captured["values"] = values
        assert "ts.employee = %(employee)s" in query
        assert as_dict is True
        return [{"employee": "EMP-1"}]

    frappe.db.sql = sql

    data = mod.list_rd_hours("2026-07", employee="EMP-1")

    assert captured["roles"] == mod.RD_TIMESHEET_VIEW_ROLES
    assert captured["values"]["employee"] == "EMP-1"
    assert data == [{"employee": "EMP-1"}]
def test_get_rd_hour_summary_rejects_invisible_employee(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_visible_employee_names", lambda include_finance=False: ["EMP-SELF"])
    frappe.db.sql = lambda *args, **kwargs: []

    with pytest.raises(RuleError, match="无权"):
        mod.get_rd_hour_summary("2026-07", employee="EMP-OTHER")
def test_bulk_save_rd_hours_uses_one_transaction_and_returns_refreshed_rows(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {"saved": []}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "list_rd_hours", lambda period: [{"period": period, "ok": True}])
    monkeypatch.setattr(mod, "_save_rd_hours_row", lambda allow_replace=True, **kwargs: captured["saved"].append((allow_replace, kwargs)))
    frappe.db.savepoint = lambda name: captured.setdefault("savepoint", name)
    frappe.db.rollback = lambda save_point=None: captured.setdefault("rollback", save_point)
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.bulk_save_rd_hours("2026-07", '[{"employee":"EMP-1","work_date":"2026-07-01","project":"PROJ-1","project_code":"RD14","project_name":"ACONCA 7961","activity_type":"方案设计","hours":2,"description":"work"}]')

    assert captured["roles"] == mod.RD_TIMESHEET_ENTRY_ROLES
    assert captured["savepoint"] == "rd_bulk_timesheet"
    assert captured["committed"] is True
    assert captured["saved"][0][0] is False
    assert captured["saved"][0][1]["period"] == "2026-07"
    assert captured["saved"][0][1]["employee"] == "EMP-1"
    assert result == [{"period": "2026-07", "ok": True}]


def test_bulk_save_rd_hours_rolls_back_when_any_row_fails(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {"calls": 0}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    def fail_on_second(**kwargs):
        captured["calls"] += 1
        if captured["calls"] == 2:
            raise RuleError("bad row")
    monkeypatch.setattr(mod, "_save_rd_hours_row", fail_on_second)
    monkeypatch.setattr(mod, "list_rd_hours", lambda period: (_ for _ in ()).throw(AssertionError("should not refresh after failure")))
    frappe.db.savepoint = lambda name: captured.setdefault("savepoint", name)
    frappe.db.rollback = lambda save_point=None: captured.setdefault("rollback", save_point)
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    rows = '[{"employee":"EMP-1","work_date":"2026-07-01","project_code":"RD14","project_name":"A","hours":1},{"employee":"EMP-1","work_date":"2026-07-02","project_code":"RD14","project_name":"A","hours":1}]'
    with pytest.raises(RuleError, match="bad row"):
        mod.bulk_save_rd_hours("2026-07", rows)

    assert captured["rollback"] == "rd_bulk_timesheet"
    assert "committed" not in captured

def test_resolve_rd_project_rejects_completed_and_cancelled_projects(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)

    def get_all(doctype, filters=None, pluck=None, limit=None, **kwargs):
        assert doctype == "Project"
        assert filters == {
            "rd_project_code": "RD20",
            "project_name": "Active Project",
            "allow_rd_timesheet": 1,
            "status": ["not in", ["Completed", "Cancelled"]],
        }
        return ["RD20"]

    frappe.get_all = get_all

    assert mod._resolve_rd_project("RD20", "Active Project", "RD20") == "RD20"

def _prepare_zero_hour_save(mod, frappe, monkeypatch, activity):
    captured = {}
    monkeypatch.setattr(mod, "_require_visible_employee", lambda employee: None)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7))
    monkeypatch.setattr(mod, "_work_date_in_period", lambda value, year, month: date(2026, 7, 2))
    monkeypatch.setattr(mod, "_ensure_activity", lambda value: activity)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_period_has_submitted_allocation", lambda *args, **kwargs: False)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "_resolve_rd_project", lambda code, name, selected_project=None: "PROJ-1")
    monkeypatch.setattr(mod, "_drop_combo", lambda *args, **kwargs: None)
    frappe.db.get_value = lambda doctype, target, fieldname=None, **kwargs: {
        "rd_personnel_type": mod.RD_TYPES[0],
        "company": "Rayher",
        "name": target,
    }.get(fieldname)

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "Timesheet":
            captured["doc"] = arg
            captured["timesheet"] = SimpleNamespace(
                docstatus=0,
                flags=SimpleNamespace(),
                insert=lambda ignore_permissions=False: captured.setdefault("inserted", ignore_permissions),
                submit=lambda: captured.setdefault("submitted", True),
            )
            return captured["timesheet"]
        raise AssertionError(arg)

    frappe.get_doc = get_doc
    return captured


@pytest.mark.parametrize("activity", ["请假", "调休"])
def test_zero_hour_leave_or_comp_time_is_saved_as_draft(monkeypatch, activity):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = _prepare_zero_hour_save(mod, frappe, monkeypatch, activity)

    mod._save_rd_hours_row(
        period="2026-07",
        employee="EMP-1",
        project="PROJ-1",
        hours=0,
        work_date="2026-07-02",
        activity_type=activity,
        description="special attendance",
        project_code="RD04",
        project_name="VEYMONT 2341",
    )

    assert captured["inserted"] is True
    assert "submitted" not in captured
    detail = captured["doc"]["time_logs"][0]
    assert detail["hours"] == 0
    assert detail["activity_type"] == activity
    assert detail["from_time"] == detail["to_time"]


def test_zero_hour_normal_activity_is_rejected(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    _prepare_zero_hour_save(mod, frappe, monkeypatch, "编码开发")

    with pytest.raises(RuleError, match="请假或调休"):
        mod._save_rd_hours_row(
            period="2026-07",
            employee="EMP-1",
            project="PROJ-1",
            hours=0,
            work_date="2026-07-02",
            activity_type="编码开发",
            description="work",
            project_code="RD04",
            project_name="VEYMONT 2341",
        )


def test_list_rd_hours_includes_only_marked_zero_hour_special_drafts(monkeypatch):
    mod, frappe = _load_timesheet_entry(monkeypatch)
    captured = {}
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7))
    monkeypatch.setattr(mod, "_summary_employee_filter", lambda employee=None: ("", None, None))

    def sql(query, values=None, as_dict=False):
        captured["query"] = query
        captured["values"] = values
        return []

    frappe.db.sql = sql
    mod.list_rd_hours("2026-07")

    query = " ".join(captured["query"].split())
    assert "ts.docstatus = 1" in query
    assert "ts.docstatus = 0" in query
    assert "ts.rd_spa_managed = 1" in query
    assert "tsd.hours = 0" in query
    assert set(captured["values"]["zero_hour_activity_types"]) == {"请假", "调休"}
