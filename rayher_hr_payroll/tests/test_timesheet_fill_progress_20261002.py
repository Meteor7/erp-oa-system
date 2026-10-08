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


# ---- 2026-10-08：请假 3 / 5 小时后，上限折成天不是 0.01 的倍数（173 小时 = 21.625 天） ----
CAP_173 = 173 / 8  # 21.625


def test_fill_status_uses_the_hour_rule_for_a_non_half_day_cap(mt):
    mod, _ = mt
    assert mod._fill_status(21.62, CAP_173) == "full"
    assert mod._fill_status(21.5, CAP_173) == "part"
    assert mod._fill_status(21.61, CAP_173) == "part"
    assert mod._fill_status(21.63, CAP_173) == "over"
    assert mod._fill_status(0, CAP_173) == "none"
    # 剩余 < 0.08 小时（0.01 天）算填满；刚好 0.08 小时还能再填 0.01 天
    assert mod._fill_status(19.995, 20) == "full"
    assert mod._fill_status(19.99, 20) == "part"
    # 进度接口给出的 limit_days 已经是向下取整后的最大值，用它判断结果相同
    assert mod._fill_status(21.62, 21.62) == "full"
    assert mod._fill_status(21.63, 21.62) == "over"


def test_max_entry_days_floors_to_a_hundredth_and_never_rounds_up(mt):
    mod, _ = mt
    from decimal import Decimal
    assert mod.max_entry_days(CAP_173) == Decimal("21.62")
    assert mod.max_entry_days(171 / 8) == Decimal("21.37")
    assert mod.max_entry_days(Decimal("21.625")) == Decimal("21.62")
    assert mod.max_entry_days(22) == Decimal("22.00")
    assert mod.max_entry_days(21.624999999999996) == Decimal("21.62")
    assert mod.max_entry_days(0) == Decimal("0.00") and mod.max_entry_days(None) == Decimal("0.00")


def test_fill_progress_reports_the_floored_limit_and_classifies_with_it(mt, monkeypatch):
    mod, _ = mt
    setup(mt, ["Accounts User", "System Manager"], None)
    monkeypatch.setattr(mod, "resolve_monthly_work_limit", lambda year, month, employee=None, **kw: {"day_limit": CAP_173, "hour_limit": 173}, raising=False)
    mod._query_monthly_entries = lambda period, employee=None: [
        {"employee": "E1", "occurrence_days": 21.62, "hours": 172.96, "project": "P", "employee_name": ""},
        {"employee": "E2", "occurrence_days": 21.5, "hours": 172, "project": "P", "employee_name": ""},
        {"employee": "E4", "occurrence_days": 21.63, "hours": 173.04, "project": "P", "employee_name": ""},
    ]
    result = mod.get_fill_progress("2026-10")
    by_id = {row["employee"]: row for row in result["employees"]}
    assert {k: v["status"] for k, v in by_id.items()} == {"E1": "full", "E2": "part", "E3": "none", "E4": "over"}
    assert by_id["E1"]["limit_days"] == 21.62 and by_id["E1"]["limit_hours"] == 173.0
    assert result["summary"]["full"] == 1 and result["summary"]["over"] == 1


def test_prepare_rows_accepts_21_62_and_rejects_21_63_for_a_173_hour_cap(mt):
    from decimal import Decimal
    mod, _ = mt
    resolve = lambda code, name, selected: selected
    row = lambda project, days: {"project": project, "project_code": "C" + project, "project_name": "N" + project, "occurrence_days": days}
    limit = Decimal(str(CAP_173))
    ok = mod.prepare_monthly_rows([row("A", "21"), row("B", "0.62")], 2026, 10, resolve, day_limit=limit)
    assert sum(r["occurrence_days"] for r in ok) == Decimal("21.62")
    assert mod.prepare_monthly_rows([row("A", "21.5")], 2026, 10, resolve, day_limit=limit)
    with pytest.raises(RuleError) as caught:
        mod.prepare_monthly_rows([row("A", "21"), row("B", "0.63")], 2026, 10, resolve, day_limit=limit)
    message = str(caught.value)
    assert "最多 21.62 天" in message and "当前 21.63 天" in message and "173 小时" in message
    # 5 小时请假：171 小时 = 21.375 天，最多 21.37 天
    with pytest.raises(RuleError, match="最多 21.37 天"):
        mod.prepare_monthly_rows([row("A", "21.38")], 2026, 10, resolve, day_limit=Decimal(str(171 / 8)))
    assert mod.prepare_monthly_rows([row("A", "21.37")], 2026, 10, resolve, day_limit=Decimal(str(171 / 8)))