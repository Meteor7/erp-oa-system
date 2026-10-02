import importlib
import json
import sys
import types
from datetime import datetime

import pytest


class RuleError(Exception):
    pass


@pytest.fixture
def mt(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.throw = lambda message, *a, **k: (_ for _ in ()).throw(RuleError(str(message)))
    frappe.whitelist = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda fn: fn))
    frappe.utils = types.ModuleType("frappe.utils")
    frappe.utils.getdate = lambda value: value if hasattr(value, "year") else datetime.fromisoformat(str(value)).date()
    frappe.utils.nowdate = lambda: "2026-10-12"
    frappe.utils.get_fullname = lambda user: "周主管"
    frappe.session = types.SimpleNamespace(user="lead@example.com")
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe.utils)
    sys.modules.pop("rayher_hr_payroll.api.monthly_timesheet_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.monthly_timesheet_entry")
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "resolve_monthly_work_limit", lambda year, month, employee=None, **kw: {"day_limit": 20}, raising=False)
    return mod, frappe


EMPS = [
    {"name": "E1", "employee_name": "演示员工181", "department": "研发一部 - RAY", "user_id": "e1@example.com"},
    {"name": "E2", "employee_name": "演示员工149", "department": "研发一部 - RAY", "user_id": "e2@example.com"},
    {"name": "E3", "employee_name": "演示员工185", "department": "研发二部 - RAY", "user_id": "e3@example.com"},
    {"name": "E4", "employee_name": "演示员工119", "department": "研发二部 - RAY", "user_id": "e4@example.com"},
]
USED = {"E1": 20, "E2": 12.5, "E4": 21}


def setup(mt, roles, scope, created=None, reminded=None):
    mod, frappe = mt
    frappe.get_roles = lambda user=None: list(roles)
    mod._monthly_employee_scope = lambda mode, start=None: scope
    mod._employees_for_scope = lambda sc, start=None: [e for e in EMPS if sc is None or e["name"] in sc]
    mod._query_monthly_entries = lambda period, employee=None: [{"employee": k, "occurrence_days": v, "hours": v * 8, "project": "P", "employee_name": ""} for k, v in USED.items()]
    mod._query_legacy_monthly_entries = lambda period, employee=None: []
    log = list(reminded or [])

    def get_all(doctype, filters=None, fields=None, **kw):
        if doctype == "Employee":
            names = (filters or {}).get("name", ["in", [e["name"] for e in EMPS]])[1]
            return [dict(e) for e in EMPS if e["name"] in names]
        if doctype == "Notification Log":
            return list(log)
        return []

    frappe.get_all = get_all
    frappe.db = types.SimpleNamespace(exists=lambda *a, **k: True)
    docs = created if created is not None else []

    class Doc:
        def __init__(self, values):
            self.values = values

        def insert(self, **kw):
            docs.append(self.values)

    frappe.get_doc = lambda values: Doc(values)
    return docs


def test_fill_status_covers_every_state(mt):
    mod, _ = mt
    assert [mod._fill_status(*pair) for pair in [(0, 20), (12.5, 20), (20, 20), (21, 20), (0, 0)]] == ["none", "part", "full", "over", "full"]
    assert mod._department_label("研发一部 - RAY") == "研发一部" and mod._department_label("测试部") == "测试部"


def test_boss_sees_everyone_and_can_remind(mt):
    mod, _ = mt
    setup(mt, ["Accounts User", "System Manager"], None)
    result = mod.get_fill_progress("2026-10")
    assert result["kind"] == "all" and result["can_remind"] is True and result["deadline"] == "2026-10-31"
    assert result["summary"] == {"total": 4, "full": 1, "part": 1, "none": 1, "over": 1, "rate": 25.0}
    assert {row["employee"]: row["status"] for row in result["employees"]} == {"E1": "full", "E2": "part", "E3": "none", "E4": "over"}
    assert result["employees"][0]["department"] == "研发一部" and "user_id" not in result["employees"][0]


def test_department_head_only_sees_the_team_and_finance_cannot_remind(mt):
    mod, _ = mt
    setup(mt, ["Department Manager"], ["E1", "E2"])
    result = mod.get_fill_progress("2026-10")
    assert result["kind"] == "team" and [row["employee"] for row in result["employees"]] == ["E1", "E2"] and result["can_remind"] is True
    setup(mt, ["Accounts User"], None)
    assert mod.get_fill_progress("2026-10")["can_remind"] is False


def test_plain_employee_gets_no_board(mt):
    mod, _ = mt
    setup(mt, ["Employee"], ["E1"])
    result = mod.get_fill_progress("2026-10")
    assert result["kind"] == "self" and result["employees"] == [] and result["can_remind"] is False


def test_reminders_go_only_to_people_who_still_owe_hours_and_only_once_a_day(mt):
    mod, _ = mt
    docs = setup(mt, ["Department Manager"], None)
    mod._require_monthly_employee = lambda employee, mode, start=None: None
    out = mod.remind_timesheet_fill("2026-10", json.dumps(["E1", "E2", "E3"]))
    assert out == {"sent": 2, "skipped_today": 0, "skipped_done": 1}
    assert sorted(d["for_user"] for d in docs) == ["e2@example.com", "e3@example.com"]
    assert docs[0]["link"] == "/planck-semicon/entry" and "[rd-fill:2026-10]" in docs[0]["subject"]
    docs2 = setup(mt, ["Department Manager"], None, reminded=[{"document_name": "E2", "creation": "2026-10-12 09:30:00"}])
    mod._require_monthly_employee = lambda employee, mode, start=None: None
    again = mod.remind_timesheet_fill("2026-10", json.dumps(["E2", "E3"]))
    assert again == {"sent": 1, "skipped_today": 1, "skipped_done": 0} and [d["for_user"] for d in docs2] == ["e3@example.com"]


def test_reminders_are_for_managers_only_and_respect_the_scope(mt):
    mod, _ = mt
    setup(mt, ["Employee"], ["E1"])
    with pytest.raises(RuleError, match="只有部门主管"):
        mod.remind_timesheet_fill("2026-10", json.dumps(["E2"]))
    setup(mt, ["Department Manager"], ["E1", "E2"])
    mod._require_monthly_employee = lambda employee, mode, start=None: (_ for _ in ()).throw(RuleError("您无权查看或登记该员工的工时。")) if employee == "E3" else None
    with pytest.raises(RuleError, match="无权"):
        mod.remind_timesheet_fill("2026-10", json.dumps(["E3"]))
    with pytest.raises(RuleError, match="1 到 500"):
        mod.remind_timesheet_fill("2026-10", "[]")
