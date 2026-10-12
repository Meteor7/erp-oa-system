import importlib
import sys
import types
from datetime import datetime
from decimal import Decimal

import pytest


class RuleError(Exception):
    pass


@pytest.fixture
def monthly_module(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.throw = lambda message: (_ for _ in ()).throw(RuleError(str(message)))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.whitelist = whitelist
    frappe.utils = types.ModuleType("frappe.utils")
    frappe.utils.getdate = lambda value: value if hasattr(value, "year") else datetime.fromisoformat(str(value)).date()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe.utils)
    sys.modules.pop("rayher_hr_payroll.api.monthly_timesheet_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.monthly_timesheet_entry")
    monkeypatch.setattr(
        mod,
        "resolve_monthly_work_limit",
        lambda year, month, employee=None, company=None, lock=False: {
            "day_limit": 31,
            "hour_limit": 248,
            "calendar_source": "company_holiday_list",
            "holiday_list": "Default Calendar",
            "work_dates": [],
        },
        raising=False,
    )
    return mod, frappe


def _install_monthly_scope_frappe(frappe, roles, employees, user="worker@example.com"):
    frappe.session = types.SimpleNamespace(user=user)
    frappe.get_roles = lambda selected_user=None: list(roles)

    def get_all(doctype, filters=None, fields=None, order_by=None, pluck=None, **kwargs):
        assert doctype == "Employee"
        rows = list(employees)
        for key, expected in (filters or {}).items():
            if isinstance(expected, (list, tuple)) and expected and expected[0] == "in":
                allowed = set(expected[1])
                rows = [row for row in rows if row.get(key) in allowed]
            else:
                rows = [row for row in rows if row.get(key) == expected]
        rows.sort(key=lambda row: row["name"])
        if pluck:
            return [row.get(pluck) for row in rows]
        return [dict(row) for row in rows]

    frappe.get_all = get_all


def _rd_employee(name, user_id=None, reports_to=None, status="Active", personnel_type="全时研发"):
    return {
        "name": name,
        "employee_name": name,
        "user_id": user_id,
        "reports_to": reports_to,
        "status": status,
        "rd_personnel_type": personnel_type,
    }


def test_employee_scope_is_self_only_even_with_project_roles(monthly_module):
    mod, frappe = monthly_module
    _install_monthly_scope_frappe(
        frappe,
        ["Employee", "Project Owner", "All Project Access"],
        [
            _rd_employee("EMP-SELF", user_id="worker@example.com"),
            _rd_employee("EMP-OTHER", user_id="other@example.com"),
        ],
    )

    assert mod._monthly_employee_scope("view") == ["EMP-SELF"]
    assert mod._monthly_employee_scope("edit") == ["EMP-SELF"]


def test_accounts_user_is_read_only_but_management_roles_take_precedence(monthly_module):
    mod, frappe = monthly_module
    employees = [_rd_employee("EMP-SELF", user_id="worker@example.com")]

    _install_monthly_scope_frappe(frappe, ["Employee", "Accounts User"], employees)
    assert mod._monthly_employee_scope("view") is None
    assert mod._monthly_employee_scope("edit") == []

    _install_monthly_scope_frappe(frappe, ["Employee", "Accounts User", "HR User"], employees)
    assert mod._monthly_employee_scope("edit") is None

    _install_monthly_scope_frappe(frappe, ["Employee", "Accounts User", "System Manager"], employees)
    assert mod._monthly_employee_scope("edit") is None


def test_department_manager_scope_is_self_and_active_rd_direct_reports(monthly_module):
    mod, frappe = monthly_module
    _install_monthly_scope_frappe(
        frappe,
        ["Employee", "Department Manager", "All Project Access"],
        [
            _rd_employee("EMP-MANAGER", user_id="worker@example.com"),
            _rd_employee("EMP-ACTIVE", user_id="active@example.com", reports_to="EMP-MANAGER"),
            _rd_employee("EMP-LEFT", user_id="left@example.com", reports_to="EMP-MANAGER", status="Left"),
            _rd_employee("EMP-NON-RD", user_id="office@example.com", reports_to="EMP-MANAGER", personnel_type=""),
        ],
    )

    assert mod._monthly_employee_scope("edit") == ["EMP-ACTIVE", "EMP-MANAGER"]


def test_department_manager_scope_follows_the_reporting_line_below_not_just_direct_reports(monthly_module):
    # 决定 2026-10-12：团队 = 汇报关系向下。下属的下属也算；不是下属的同部门研发人员不算。
    mod, frappe = monthly_module
    _install_monthly_scope_frappe(
        frappe,
        ["Employee", "Department Manager"],
        [
            _rd_employee("EMP-MANAGER", user_id="worker@example.com"),
            _rd_employee("EMP-LEAD", user_id="lead@example.com", reports_to="EMP-MANAGER"),
            _rd_employee("EMP-UNDER-LEAD", user_id="under@example.com", reports_to="EMP-LEAD"),
            _rd_employee("EMP-PEER", user_id="peer@example.com"),
        ],
    )

    assert mod._monthly_employee_scope("edit") == ["EMP-LEAD", "EMP-MANAGER", "EMP-UNDER-LEAD"]


def test_a_left_person_in_the_chain_does_not_hide_the_people_below_them(monthly_module):
    mod, frappe = monthly_module
    from datetime import date
    _install_monthly_scope_frappe(
        frappe,
        ["Employee", "Department Manager"],
        [
            _rd_employee("EMP-MANAGER", user_id="worker@example.com"),
            _rd_employee("EMP-GONE", user_id="gone@example.com", reports_to="EMP-MANAGER", status="Left"),
            _rd_employee("EMP-BELOW", user_id="below@example.com", reports_to="EMP-GONE"),
        ],
    )

    assert mod._monthly_employee_scope("edit") == ["EMP-BELOW", "EMP-MANAGER"]
    assert "EMP-BELOW" in mod._team_research_names("EMP-MANAGER")


@pytest.mark.parametrize(
    "employees, message",
    [
        ([], "未关联"),
        (
            [
                _rd_employee("EMP-ONE", user_id="worker@example.com"),
                _rd_employee("EMP-TWO", user_id="worker@example.com"),
            ],
            "多个",
        ),
        ([_rd_employee("EMP-LEFT", user_id="worker@example.com", status="Left")], "未关联"),
        ([_rd_employee("EMP-NON-RD", user_id="worker@example.com", personnel_type="")], "未关联"),
    ],
)
def test_employee_scope_rejects_invalid_current_employee_links(monthly_module, employees, message):
    mod, frappe = monthly_module
    _install_monthly_scope_frappe(frappe, ["Employee"], employees)

    with pytest.raises(RuleError, match=message):
        mod._monthly_employee_scope("edit")


def test_monthly_options_separates_visible_and_editable_employees(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    employees = [
        _rd_employee("EMP-SELF", user_id="worker@example.com"),
        _rd_employee("EMP-OTHER", user_id="other@example.com"),
    ]
    _install_monthly_scope_frappe(frappe, ["Employee", "All Project Access"], employees)
    monkeypatch.setattr(
        mod,
        "_daily_module",
        lambda: types.SimpleNamespace(
            RD_TYPES=("全时研发", "非全时研发", "研发辅助"),
            get_rd_options=lambda: {
                "employees": employees,
                "projects": [{"name": "PROJ-1"}],
                "activity_types": [{"name": "编码开发"}],
            },
        ),
    )
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)

    result = mod.get_monthly_options()

    assert [row["name"] for row in result["employees"]] == ["EMP-SELF"]
    assert set(result["employees"][0]) == {"name", "employee_name"}
    assert result["editable_employees"] == ["EMP-SELF"]
    assert result["projects"] == [{"name": "PROJ-1"}]


def test_cross_employee_list_is_rejected_before_business_queries(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7))
    monkeypatch.setattr(mod, "_monthly_employee_scope", lambda mode, period_start=None: ["EMP-SELF"], raising=False)
    business_queries = []
    monkeypatch.setattr(mod, "_query_monthly_entries", lambda *args: business_queries.append(args))
    monkeypatch.setattr(mod, "_query_legacy_monthly_entries", lambda *args: business_queries.append(args))

    with pytest.raises(RuleError, match="无权"):
        mod.list_monthly_entries("2026-07", employee="EMP-OTHER")

    assert business_queries == []


def test_cross_employee_save_is_rejected_before_business_reads(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    frappe.db = TransactionDb()
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7))
    monkeypatch.setattr(mod, "_monthly_employee_scope", lambda mode, period_start=None: ["EMP-SELF"], raising=False)

    with pytest.raises(RuleError, match="无权"):
        mod.save_monthly_entries(
            "2026-07",
            "EMP-OTHER",
            [],
            expected_revision="loaded-revision",
        )

    assert frappe.db.events == []


def test_delete_authorizes_actual_timesheet_employee_before_mutation(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    doc = types.SimpleNamespace(
        name="TS-OTHER",
        employee="EMP-OTHER",
        rd_system_generated=1,
        rd_monthly_entry_id="entry-other",
        get=lambda key: {
            "rd_entry_period": "2026-07",
            "rd_system_generated": 1,
            "rd_monthly_entry_id": "entry-other",
        }.get(key),
    )
    frappe.db = types.SimpleNamespace(
        get_value=lambda *args, **kwargs: "TS-OTHER",
    )
    frappe.get_doc = lambda doctype, name: doc
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_monthly_employee_scope", lambda mode, period_start=None: ["EMP-SELF"], raising=False)
    mutations = []
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: mutations.append(("lock", args)))
    monkeypatch.setattr(mod, "_delete_monthly_document", lambda *args: mutations.append(("delete", args)))

    with pytest.raises(RuleError, match="无权"):
        mod.delete_monthly_entry("entry-other")

    assert mutations == []


def test_two_decimal_days_split_into_full_and_partial_hours(monthly_module):
    mod, _frappe = monthly_module

    days = mod.parse_occurrence_days("2.35", 2026, 7)

    assert days == Decimal("2.35")
    assert mod.calculated_hours(days) == Decimal("18.80")
    assert mod.split_day_hours(days) == [Decimal("8.00"), Decimal("8.00"), Decimal("2.80")]


@pytest.mark.parametrize("value", ["0", "-1", "1.001", "abc", ""])
def test_invalid_days_are_rejected(monthly_module, value):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.parse_occurrence_days(value, 2026, 7)


def test_days_cannot_exceed_calendar_month(monthly_module):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.parse_occurrence_days("29.01", 2026, 2)


def test_leap_year_allows_twenty_nine_days(monthly_module):
    mod, _frappe = monthly_module

    assert mod.parse_occurrence_days("29.00", 2028, 2) == Decimal("29.00")


def test_prepare_monthly_rows_resolves_projects_and_rejects_duplicates(monthly_module):
    mod, _frappe = monthly_module
    project_map = {
        ("RD14", "ACONCA 7961", "PROJ-1"): "PROJ-1",
        ("RD15", "DRAKENS 4482", "PROJ-2"): "PROJ-2",
    }

    def resolve(code, name, selected):
        return project_map[(code, name, selected)]

    prepared = mod.prepare_monthly_rows(
        [
            {"monthly_entry_id": "keep-1", "project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "occurrence_days": "2.35", "remark": "work one"},
            {"project": "PROJ-2", "project_code": "RD15", "project_name": "DRAKENS 4482", "occurrence_days": "1.25", "remark": "work two"},
        ],
        2026,
        7,
        resolve,
    )

    assert [row["project"] for row in prepared] == ["PROJ-1", "PROJ-2"]
    assert prepared[0]["occurrence_days"] == Decimal("2.35")
    assert prepared[0]["calculated_hours"] == Decimal("18.80")
    assert prepared[0]["monthly_entry_id"] == "keep-1"

    with pytest.raises(RuleError):
        mod.prepare_monthly_rows(
            [
                {"project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "occurrence_days": "1"},
                {"project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "occurrence_days": "2"},
            ],
            2026,
            7,
            resolve,
        )


def test_prepare_monthly_rows_rejects_total_above_month_limit(monthly_module):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.prepare_monthly_rows(
            [
                {"project": "PROJ-1", "project_code": "RD14", "project_name": "A", "occurrence_days": "20"},
                {"project": "PROJ-2", "project_code": "RD15", "project_name": "B", "occurrence_days": "9.01"},
            ],
            2026,
            2,
            lambda code, name, selected: selected,
        )


def test_prepare_monthly_rows_rejects_total_above_resolved_workday_limit(monthly_module):
    mod, _frappe = monthly_module

    with pytest.raises(RuleError):
        mod.prepare_monthly_rows(
            [
                {"project": "PROJ-1", "project_code": "RD14", "project_name": "A", "occurrence_days": "20.01"},
            ],
            2026,
            7,
            lambda code, name, selected: selected,
            day_limit=Decimal("20.00"),
        )


def test_technical_logs_use_only_resolved_work_dates(monthly_module):
    mod, _frappe = monthly_module
    allowed = [datetime(2026, 7, 2).date(), datetime(2026, 7, 6).date()]

    rows = mod.build_technical_time_logs(
        2026,
        7,
        [Decimal("8.00"), Decimal("4.00")],
        project="PROJ-1",
        project_code="RD14",
        project_name="ACONCA 7961",
        remark="calendar constrained",
        occupied_hours={},
        work_dates=allowed,
    )

    assert [row["from_time"].date() for row in rows] == allowed
    assert [row["hours"] for row in rows] == [8.0, 4.0]


def test_technical_logs_pack_full_and_partial_days_without_crossing_month(monthly_module):
    mod, _frappe = monthly_module

    occupied = {}
    first = mod.build_technical_time_logs(
        2026,
        7,
        [Decimal("8.00"), Decimal("8.00"), Decimal("2.80")],
        project="PROJ-1",
        project_code="RD14",
        project_name="ACONCA 7961",
        remark="first",
        occupied_hours=occupied,
    )
    second = mod.build_technical_time_logs(
        2026,
        7,
        [Decimal("5.20"), Decimal("8.00")],
        project="PROJ-2",
        project_code="RD15",
        project_name="DRAKENS 4482",
        remark="second",
        occupied_hours=occupied,
    )

    assert [row["hours"] for row in first] == [8.0, 8.0, 2.8]
    assert first[0]["from_time"] == datetime(2026, 7, 1, 0, 0)
    assert first[-1]["to_time"] == datetime(2026, 7, 3, 2, 48)
    assert second[0]["from_time"] == datetime(2026, 7, 3, 2, 48)
    assert second[0]["to_time"] == datetime(2026, 7, 3, 8, 0)
    assert second[1]["from_time"] == datetime(2026, 7, 4, 0, 0)
    assert all(row["from_time"].month == 7 and row["to_time"].month == 7 for row in first + second)


def test_timesheet_payload_keeps_monthly_metadata_on_parent(monthly_module):
    mod, _frappe = monthly_module
    row = {
        "project": "PROJ-1",
        "project_code": "RD14",
        "project_name": "ACONCA 7961",
        "occurrence_days": Decimal("2.35"),
        "calculated_hours": Decimal("18.80"),
        "remark": "monthly work",
    }
    logs = mod.build_technical_time_logs(
        2026,
        7,
        mod.split_day_hours(row["occurrence_days"]),
        project=row["project"],
        project_code=row["project_code"],
        project_name=row["project_name"],
        remark=row["remark"],
        occupied_hours={},
    )

    payload = mod.build_timesheet_payload(
        employee="EMP-1",
        company="Rayher",
        period="2026-07",
        entry_id="entry-1",
        row=row,
        time_logs=logs,
    )

    assert payload["doctype"] == "Timesheet"
    assert payload["rd_spa_managed"] == 1
    assert payload["rd_system_generated"] == 1
    assert payload["rd_monthly_entry_id"] == "entry-1"
    assert payload["rd_entry_period"] == "2026-07"
    assert payload["rd_occurrence_days"] == 2.35
    assert payload["rd_calculated_hours"] == 18.8
    assert sum(Decimal(str(log["hours"])) for log in payload["time_logs"]) == Decimal("18.8")


class TransactionDb:
    def __init__(self):
        self.events = []

    def savepoint(self, name):
        self.events.append(("savepoint", name))

    def commit(self):
        self.events.append(("commit", None))

    def rollback(self, save_point=None):
        self.events.append(("rollback", save_point))

    def get_value(self, *args, **kwargs):
        self.events.append(("get_value", args, kwargs))
        return None


def _install_save_dependencies(monkeypatch, mod, frappe):
    frappe.db = TransactionDb()
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None, raising=False)
    monkeypatch.setattr(mod, "_require_monthly_employee", lambda employee, mode, period_start=None: None, raising=False)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7), raising=False)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: None, raising=False)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args: None, raising=False)
    daily = types.SimpleNamespace(
        _require_visible_employee=lambda employee: None,
        _resolve_rd_project=lambda code, name, selected=None: selected or code,
        _period_has_submitted_allocation=lambda year, month: False,
        _company=lambda: "Rayher",
    )
    monkeypatch.setattr(mod, "_daily_module", lambda: daily, raising=False)
    return daily


def test_save_monthly_entries_commits_one_atomic_replacement(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)
    original_get_value = frappe.db.get_value

    def employee_value(*args, **kwargs):
        original_get_value(*args, **kwargs)
        if len(args) >= 3 and args[0] == "Employee" and args[2] == "company":
            return "Employee Company"
        return None

    frappe.db.get_value = employee_value
    replaced = []
    monkeypatch.setattr(mod, "_legacy_daily_exists", lambda *args: False, raising=False)
    monkeypatch.setattr(
        mod,
        "_replace_monthly_documents",
        lambda **kwargs: replaced.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        mod,
        "list_monthly_entries",
        lambda period, employee=None: {"period": period, "employee": employee, "total_days": 2.35},
        raising=False,
    )

    result = mod.save_monthly_entries(
        "2026-07",
        "EMP-1",
        [{"project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "occurrence_days": "2.35"}],
        expected_revision="loaded-revision",
    )

    assert result["total_days"] == 2.35
    assert len(replaced) == 1
    assert replaced[0]["company"] == "Employee Company"
    assert replaced[0]["rows"][0]["calculated_hours"] == Decimal("18.80")
    assert frappe.db.events[0][0] == "get_value"
    assert ("savepoint", "rd_monthly_timesheet") in frappe.db.events
    assert frappe.db.events.index(("savepoint", "rd_monthly_timesheet")) < frappe.db.events.index(("commit", None))
    assert frappe.db.events[-1] == ("commit", None)
    assert not any(event[0] == "rollback" for event in frappe.db.events)


def test_save_monthly_entries_rolls_back_complete_replacement_on_failure(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)
    monkeypatch.setattr(mod, "_legacy_daily_exists", lambda *args: False, raising=False)

    def fail(**kwargs):
        raise RuleError("submit failed")

    monkeypatch.setattr(mod, "_replace_monthly_documents", fail, raising=False)

    with pytest.raises(RuleError, match="submit failed"):
        mod.save_monthly_entries(
            "2026-07",
            "EMP-1",
            [{"project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "occurrence_days": "1"}],
            expected_revision="loaded-revision",
        )

    assert ("rollback", "rd_monthly_timesheet") in frappe.db.events
    assert not any(event[0] == "commit" for event in frappe.db.events)


def test_save_monthly_entries_requires_an_employee(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)

    with pytest.raises(RuleError, match="人员"):
        mod.save_monthly_entries("2026-07", "", [])


def test_list_monthly_entries_returns_parent_rows_without_technical_dates(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None, raising=False)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7), raising=False)
    monkeypatch.setattr(mod, "_require_monthly_employee", lambda employee, mode, period_start=None: None, raising=False)
    monkeypatch.setattr(
        mod,
        "_query_monthly_entries",
        lambda *args: [
            {
                "monthly_entry_id": "entry-1",
                "employee": "EMP-1",
                "employee_name": "演示员工132",
                "project": "PROJ-1",
                "project_code": "RD14",
                "project_name": "ACONCA 7961",
                "occurrence_days": 2.35,
                "hours": 18.8,
                "remark": "monthly work",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(mod, "_legacy_daily_exists", lambda *args: False, raising=False)
    monkeypatch.setattr(mod, "_query_legacy_monthly_entries", lambda *args: [], raising=False)

    result = mod.list_monthly_entries("2026-07", employee="EMP-1")

    assert result["entries"][0]["monthly_entry_id"] == "entry-1"
    assert result["total_days"] == 2.35
    assert result["total_hours"] == 18.8
    assert result["day_limit"] == 31
    assert "work_date" not in result["entries"][0]
    assert "from_time" not in result["entries"][0]


def test_list_monthly_entries_returns_resolved_day_and_hour_limits(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None, raising=False)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 7), raising=False)
    monkeypatch.setattr(mod, "_require_monthly_employee", lambda employee, mode, period_start=None: None, raising=False)
    monkeypatch.setattr(mod, "_query_monthly_entries", lambda *args: [], raising=False)
    monkeypatch.setattr(mod, "_query_legacy_monthly_entries", lambda *args: [], raising=False)
    monkeypatch.setattr(
        mod,
        "resolve_monthly_work_limit",
        lambda year, month, employee=None, company=None, lock=False: {
            "day_limit": 22,
            "hour_limit": 176,
            "calendar_source": "company_holiday_list",
            "holiday_list": "2026 Company Holidays",
            "work_dates": [],
        },
    )
    monkeypatch.setattr(mod, "_daily_module", lambda: types.SimpleNamespace(_company=lambda: "Planck"))

    result = mod.list_monthly_entries("2026-07", employee="EMP-1")

    assert result["day_limit"] == 22
    assert result["hour_limit"] == 176
    assert result["calendar_source"] == "company_holiday_list"
    assert result["holiday_list"] == "2026 Company Holidays"


def test_save_monthly_entries_rejects_total_above_resolved_workday_limit(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)
    monkeypatch.setattr(mod, "_legacy_daily_exists", lambda *args: False, raising=False)
    monkeypatch.setattr(
        mod,
        "resolve_monthly_work_limit",
        lambda year, month, employee=None, company=None, lock=False: {
            "day_limit": 20,
            "hour_limit": 160,
            "calendar_source": "employee_holiday_list",
            "holiday_list": "Employee Calendar",
            "work_dates": [],
        },
    )

    with pytest.raises(RuleError):
        mod.save_monthly_entries(
            "2026-07",
            "EMP-1",
            [{"project": "PROJ-1", "project_code": "RD14", "project_name": "A", "occurrence_days": "20.01"}],
            expected_revision="loaded-revision",
        )


def test_replace_monthly_documents_preserves_ids_and_submits_generated_parents(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    inserted = []
    deleted = []
    ensured = []

    class OldDoc:
        name = "TS-OLD"
        employee = "EMP-1"
        docstatus = 1

        def __init__(self):
            self.flags = types.SimpleNamespace(ignore_permissions=False)
            self.cancelled = False

        def get(self, key):
            return {
                "rd_monthly_entry_id": "keep-1",
                "rd_system_generated": 1,
                "rd_entry_period": "2026-07",
            }.get(key)

        def cancel(self):
            self.cancelled = True

    old_doc = OldDoc()

    class NewDoc:
        def __init__(self, payload):
            self.payload = payload
            self.flags = types.SimpleNamespace(ignore_permissions=False)
            self.inserted = False
            self.submitted = False

        def insert(self, ignore_permissions=False):
            self.inserted = ignore_permissions
            inserted.append(self)

        def submit(self):
            self.submitted = True

    frappe.db = types.SimpleNamespace(get_values=lambda *args, **kwargs: ["TS-OLD"])

    def get_doc(*args):
        if len(args) == 2:
            return old_doc
        return NewDoc(args[0])

    frappe.get_doc = get_doc
    frappe.delete_doc = lambda doctype, name, **kwargs: deleted.append((doctype, name, kwargs))
    monkeypatch.setattr(
        mod,
        "_daily_module",
        lambda: types.SimpleNamespace(_ensure_activity=lambda: ensured.append(True)),
    )

    mod._replace_monthly_documents(
        employee="EMP-1",
        period="2026-07",
        year=2026,
        month=7,
        company="Rayher",
        expected_revision=mod._monthly_revision([old_doc]),
        rows=[
            {
                "monthly_entry_id": "keep-1",
                "project": "PROJ-1",
                "project_code": "RD14",
                "project_name": "ACONCA 7961",
                "occurrence_days": Decimal("2.35"),
                "calculated_hours": Decimal("18.80"),
                "remark": "monthly work",
            }
        ],
    )

    assert old_doc.cancelled is True
    assert deleted[0][0:2] == ("Timesheet", "TS-OLD")
    assert ensured == [True]
    assert len(inserted) == 1
    assert inserted[0].submitted is True
    assert inserted[0].payload["rd_monthly_entry_id"] == "keep-1"
    assert [row["hours"] for row in inserted[0].payload["time_logs"]] == [8.0, 8.0, 2.8]


def test_delete_monthly_entry_uses_parent_id_and_period_locks(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)
    deleted = []
    locks = []

    class MonthlyDoc:
        name = "TS-1"
        employee = "EMP-1"
        docstatus = 1

        def get(self, key):
            return {
                "rd_monthly_entry_id": "entry-1",
                "rd_entry_period": "2026-07",
                "rd_system_generated": 1,
            }.get(key)

    original_get_value = frappe.db.get_value

    def get_value(doctype, key, fieldname, **kwargs):
        if doctype == "Timesheet":
            return "TS-1"
        return original_get_value(doctype, key, fieldname, **kwargs)

    frappe.db.get_value = get_value
    frappe.get_doc = lambda doctype, name: MonthlyDoc()
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: locks.append(("period", args)), raising=False)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args: locks.append(("import", args)), raising=False)
    monkeypatch.setattr(mod, "_delete_monthly_document", lambda doc, employee, period: deleted.append((doc.name, employee, period)))
    monkeypatch.setattr(mod, "list_monthly_entries", lambda period, employee=None: {"entries": [], "employee": employee})

    result = mod.delete_monthly_entry("entry-1")

    assert deleted == [("TS-1", "EMP-1", "2026-07")]
    assert locks[0][0] == "period"
    assert locks[1] == ("import", (2026, 7))
    assert result == {"entries": [], "employee": "EMP-1"}
    assert frappe.db.events[-1] == ("commit", None)

def test_merge_monthly_rows_normalizes_legacy_daily_sources(monthly_module):
    mod, _frappe = monthly_module

    rows = mod._merge_monthly_entry_rows(
        [],
        [{
            "employee": "HR-EMP-90014",
            "employee_name": "演示员工112",
            "project": "PROJ-1",
            "project_code": "RD14",
            "project_name": "项目甲",
            "hours": 12,
            "occurrence_days": 1.5,
            "remark": "需求分析；编码开发",
            "source_kind": "legacy_daily",
        }],
        "2026-06",
    )

    assert rows[0]["monthly_entry_id"] == "legacy:2026-06:HR-EMP-90014:PROJ-1"
    assert rows[0]["period"] == "2026-06"
    assert rows[0]["employee_name"] == "演示员工112"
    assert rows[0]["project_name"] == "项目甲"
    assert rows[0]["occurrence_days"] == 1.5
    assert rows[0]["hours"] == 12.0
    assert rows[0]["source_kind"] == "legacy_daily"
    assert rows[0]["editable"] is False


def test_list_monthly_entries_returns_legacy_rows_and_employee_count(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None, raising=False)
    monkeypatch.setattr(mod, "parse_period", lambda period: (2026, 6), raising=False)
    monkeypatch.setattr(mod, "_query_monthly_entries", lambda *args: [], raising=False)
    monkeypatch.setattr(
        mod,
        "_query_legacy_monthly_entries",
        lambda *args: [
            {"employee": "HR-EMP-90014", "employee_name": "演示员工112", "project": "PROJ-1", "project_code": "RD14", "project_name": "项目甲", "hours": 12, "occurrence_days": 1.5, "remark": "历史按日汇总", "source_kind": "legacy_daily"},
            {"employee": "HR-EMP-90015", "employee_name": "演示员工162", "project": "PROJ-2", "project_code": "RD15", "project_name": "项目乙", "hours": 8, "occurrence_days": 1, "remark": "", "source_kind": "legacy_daily"},
        ],
        raising=False,
    )

    result = mod.list_monthly_entries("2026-06", employee=None)

    assert len(result["entries"]) == 2
    assert result["total_days"] == 2.5
    assert result["total_hours"] == 20
    assert result["employee_count"] == 2
    assert result["has_legacy_sources"] is True
    assert result["legacy_daily_present"] is True


def test_monthly_revision_is_deterministic_and_tracks_snapshot_changes(monthly_module):
    mod, _frappe = monthly_module
    first = {
        "timesheet": "TS-1",
        "monthly_entry_id": "entry-1",
        "modified": "2026-07-29 10:00:00",
    }
    second = {
        "timesheet": "TS-2",
        "monthly_entry_id": "entry-2",
        "modified": "2026-07-29 10:05:00",
    }

    assert mod._monthly_revision([]) == "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    assert mod._monthly_revision([first, second]) == mod._monthly_revision([second, first])
    changed = {**second, "modified": "2026-07-29 10:06:00"}
    assert mod._monthly_revision([first, changed]) != mod._monthly_revision([first, second])


def test_save_monthly_entries_requires_loaded_revision(monthly_module, monkeypatch):
    mod, frappe = monthly_module
    _install_save_dependencies(monkeypatch, mod, frappe)

    with pytest.raises(RuleError, match="\u5237\u65b0"):
        mod.save_monthly_entries("2026-07", "EMP-1", [])


def test_replace_monthly_documents_rejects_stale_revision_before_delete(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    current = types.SimpleNamespace(
        name="TS-NEW",
        rd_monthly_entry_id="entry-new",
        modified="2026-07-29 10:05:00",
    )
    deleted = []
    monkeypatch.setattr(mod, "_load_existing_monthly_documents", lambda *args: [current])
    monkeypatch.setattr(mod, "_delete_monthly_document", lambda *args: deleted.append(args))

    with pytest.raises(RuleError, match="\u5237\u65b0"):
        mod._replace_monthly_documents(
            employee="EMP-1",
            period="2026-07",
            year=2026,
            month=7,
            rows=[],
            company="Rayher",
            expected_revision="stale-revision",
        )

    assert deleted == []




def test_replace_monthly_documents_allows_intentional_empty_save(monthly_module, monkeypatch):
    mod, _frappe = monthly_module
    deleted = []

    class OldDoc:
        name = "TS-OLD"
        modified = "2026-07-29 10:00:00"

        def get(self, key):
            return {"rd_monthly_entry_id": "entry-1"}.get(key)

    old_doc = OldDoc()
    monkeypatch.setattr(mod, "_load_existing_monthly_documents", lambda *args: [old_doc])
    monkeypatch.setattr(mod, "_delete_monthly_document", lambda *args: deleted.append(args))
    monkeypatch.setattr(mod, "_daily_module", lambda: types.SimpleNamespace(_ensure_activity=lambda: None))

    mod._replace_monthly_documents(
        employee="EMP-1",
        period="2026-07",
        year=2026,
        month=7,
        rows=[],
        company="Rayher",
        expected_revision=mod._monthly_revision([old_doc]),
    )

    assert deleted == [(old_doc, "EMP-1", "2026-07")]


def test_existing_monthly_documents_are_read_with_a_lock(monthly_module):
    # 审查第一轮 #9：加锁后当前读；frappe.get_all 不支持 for_update，要用 get_values。
    mod, frappe = monthly_module
    calls = []

    def get_values(doctype, filters, fieldname, **kwargs):
        calls.append((doctype, filters, fieldname, kwargs))
        return ["TS-1"]

    frappe.db = types.SimpleNamespace(get_values=get_values)
    frappe.get_doc = lambda doctype, name: (doctype, name)

    assert mod._load_existing_monthly_documents("EMP-1", "2026-07") == [("Timesheet", "TS-1")]
    assert calls[0][0] == "Timesheet" and calls[0][1]["rd_entry_period"] == "2026-07"
    assert calls[0][3] == {"for_update": True, "pluck": True}


def test_left_employee_can_be_backfilled_for_the_relieving_month_only(monthly_module):
    # 审查 X3-6：离职当天账号就停用，离职当月的工时原来谁都补登不了。
    from datetime import date

    mod, frappe = monthly_module
    mod._daily_module = lambda: types.SimpleNamespace(RD_TYPES=("全时研发", "非全时研发", "研发辅助"))
    left = dict(_rd_employee("EMP-LEFT", status="Left"), relieving_date=date(2026, 9, 15))
    _install_monthly_scope_frappe(frappe, ["HR User"], [_rd_employee("EMP-ACTIVE"), left])

    mod._require_monthly_employee("EMP-LEFT", "edit", date(2026, 9, 1))
    mod._require_monthly_employee("EMP-LEFT", "edit", date(2026, 8, 1))
    with pytest.raises(RuleError, match="离职当月"):
        mod._require_monthly_employee("EMP-LEFT", "edit", date(2026, 10, 1))
    with pytest.raises(RuleError, match="在职研发员工"):
        mod._require_monthly_employee("EMP-LEFT", "edit")
    names = [row["name"] for row in mod._employees_for_scope(None, date(2026, 9, 1))]
    assert names == ["EMP-ACTIVE", "EMP-LEFT"]
    assert [row["name"] for row in mod._employees_for_scope(None, date(2026, 10, 1))] == ["EMP-ACTIVE"]


def test_left_employee_without_relieving_date_is_not_offered(monthly_module):
    from datetime import date

    mod, frappe = monthly_module
    mod._daily_module = lambda: types.SimpleNamespace(RD_TYPES=("全时研发",))
    _install_monthly_scope_frappe(frappe, ["HR User"], [dict(_rd_employee("EMP-LEFT", status="Left"), relieving_date=None)])
    assert mod._employees_for_scope(None, date(2026, 9, 1)) == []


def test_monthly_spreading_skips_hours_already_taken_by_approved_leave(monthly_module, monkeypatch):
    # 审查 X2-7：请假那天不能再排 8 小时研发工时。
    from datetime import date

    mod, frappe = monthly_module
    inserted = []

    class NewDoc:
        def __init__(self, payload):
            self.payload = payload
            self.flags = types.SimpleNamespace(ignore_permissions=False)

        def insert(self, ignore_permissions=False):
            inserted.append(self)

        def submit(self):
            pass

    frappe.db = types.SimpleNamespace(get_values=lambda *args, **kwargs: [])
    frappe.get_doc = lambda payload: NewDoc(payload)
    monkeypatch.setattr(mod, "_daily_module", lambda: types.SimpleNamespace(_ensure_activity=lambda: None))

    mod._replace_monthly_documents(
        employee="EMP-1",
        period="2026-07",
        year=2026,
        month=7,
        company="Rayher",
        expected_revision=mod._monthly_revision([]),
        work_dates=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)],
        leave_hours_by_date={"2026-07-01": 8.0, "2026-07-02": 4.0},
        rows=[{
            "monthly_entry_id": "",
            "project": "PROJ-1",
            "project_code": "RD14",
            "project_name": "ACONCA 7961",
            "occurrence_days": Decimal("1.00"),
            "calculated_hours": Decimal("8.00"),
            "remark": "",
        }],
    )

    logs = inserted[0].payload["time_logs"]
    assert [(log["from_time"], log["hours"]) for log in logs] == [
        (datetime(2026, 7, 2, 4, 0), 4.0),
        (datetime(2026, 7, 3, 0, 0), 4.0),
    ]



def test_department_managers_outside_rd_can_open_monthly_timesheets(monthly_module):
    # 审查 X3-7（决定 D4）：总经理、财务主管等不是研发人员的部门经理原来打不开工时页。
    mod, frappe = monthly_module
    mod._daily_module = lambda: types.SimpleNamespace(RD_TYPES=("全时研发", "非全时研发", "研发辅助"))
    staff = [
        _rd_employee("EMP-FM", user_id="worker@example.com", personnel_type="非研发"),
        _rd_employee("EMP-RD", user_id="rd@example.com", reports_to="EMP-FM"),
        _rd_employee("EMP-OTHER", user_id="other@example.com"),
    ]
    _install_monthly_scope_frappe(frappe, ["Employee", "Department Manager", "Accounts User"], staff)
    assert mod._monthly_employee_scope("view") is None
    assert mod._monthly_employee_scope("edit") == ["EMP-RD"]
    _install_monthly_scope_frappe(frappe, ["Employee", "Department Manager"], staff)
    assert mod._monthly_employee_scope("view") == ["EMP-RD"]


# ---- 2026-10-12：月度工时按小时填，天数 = 小时 ÷ 8（显示用） ----
def test_a_173_hour_entry_is_stored_as_hours_with_the_days_derived_and_no_day_above_eight_hours(monthly_module):
    mod, _frappe = monthly_module
    row = {
        "project": "PROJ-1", "project_code": "RD14", "project_name": "ACONCA 7961", "remark": "",
        "calculated_hours": Decimal("173.00"), "occurrence_days": mod.days_from_hours(173),
    }
    logs = mod.build_technical_time_logs(
        2026, 10, mod.split_hour_chunks(row["calculated_hours"]), project=row["project"], project_code=row["project_code"],
        project_name=row["project_name"], remark="", occupied_hours={},
    )
    payload = mod.build_timesheet_payload(employee="EMP-1", company="Rayher", period="2026-10", entry_id="e1", row=row, time_logs=logs)
    assert payload["rd_calculated_hours"] == 173.0 and payload["rd_occurrence_days"] == 21.63
    assert sum(Decimal(str(log["hours"])) for log in logs) == Decimal("173")
    assert max(log["hours"] for log in logs) == 8.0 and len(logs) == 22      # 21 个整天 + 5 小时


def test_the_list_row_shows_days_derived_from_the_hours_not_the_stored_days(monthly_module):
    mod, _frappe = monthly_module
    source = {"employee": "E1", "project": "P", "monthly_entry_id": "m1", "occurrence_days": 99, "hours": 173, "employee_name": "甲"}
    row = mod._monthly_view_row(source, "2026-10", "monthly")
    assert row["hours"] == 173.0 and row["occurrence_days"] == 21.63
    merged = mod._merge_monthly_entry_rows(
        [source], [{"employee": "E1", "project": "P", "occurrence_days": 1, "hours": 3, "employee_name": "甲"}], "2026-10")
    assert merged[0]["hours"] == 176.0 and merged[0]["occurrence_days"] == 22.0
