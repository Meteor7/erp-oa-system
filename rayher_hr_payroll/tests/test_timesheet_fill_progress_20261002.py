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
    assert [mod._fill_status(*pair) for pair in [(0, 160), (100, 160), (160, 160), (168, 160), (0, 0)]] == ["none", "part", "full", "over", "full"]   # 小时
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


# ---- 2026-10-09：演示员工21（研发辅助）暂时不用填研发工时，按特例处理，类型不变 ----
def test_the_exempt_account_is_left_out_of_the_timesheet_list_and_cannot_be_filled_for(mt, monkeypatch):
    mod, frappe = mt
    monkeypatch.setattr(mod, "_daily_module", lambda: types.SimpleNamespace(RD_TYPES=("全时研发", "非全时研发", "研发辅助")))
    assert mod.TIMESHEET_EXEMPT_USERS == frozenset({"person046@staff.example.invalid"})
    staff = [
        {"name": "E1", "employee_name": "演示员工181", "user_id": "e1@example.com", "status": "Active"},
        {"name": "E9", "employee_name": "演示员工21", "user_id": "person046@staff.example.invalid", "status": "Active"},
        {"name": "E8", "employee_name": "没有账号", "user_id": None, "status": "Active"},
    ]
    frappe.get_all = lambda doctype, filters=None, fields=None, order_by=None, **kw: [
        dict(row) for row in staff if not isinstance((filters or {}).get("name"), str) or row["name"] == filters["name"]
    ]
    assert [row["name"] for row in mod._eligible_employee_rows()] == ["E1", "E8"]
    assert [row["name"] for row in mod._eligible_employee_rows(datetime(2026, 10, 1).date())] == ["E1", "E8"]
    # 登记工时时也一样：不在名单里就不能为他登记
    monkeypatch.setattr(mod, "_monthly_employee_scope", lambda mode, start=None: None)
    mod._require_monthly_employee("E1", "edit")
    with pytest.raises(RuleError, match="只能为在职研发员工"):
        mod._require_monthly_employee("E9", "edit")


# ---- 2026-10-12：月度工时按小时填，天数 = 小时 ÷ 8 只用来显示；请假 3 / 5 小时后的上限（173 小时）是精确的 ----
CAP_173_HOURS = 173


def test_fill_status_compares_hours_exactly(mt):
    mod, _ = mt
    assert mod._fill_status(173, CAP_173_HOURS) == "full"
    assert mod._fill_status(172.5, CAP_173_HOURS) == "part"
    assert mod._fill_status(172.99, CAP_173_HOURS) == "part"        # 不再有"零头容差"：差 0.01 小时也是没填满
    assert mod._fill_status(173.01, CAP_173_HOURS) == "over"
    assert mod._fill_status(0, CAP_173_HOURS) == "none"
    assert mod._fill_status(0, 0) == "full"


def test_days_are_derived_from_hours_and_rounded_only_for_display(mt):
    mod, _ = mt
    from decimal import Decimal
    assert mod.days_from_hours(173) == Decimal("21.63")             # 21.625
    assert mod.days_from_hours("172") == Decimal("21.50")
    assert mod.days_from_hours(0) == Decimal("0.00") and mod.days_from_hours(None) == Decimal("0.00")
    assert mod.display_days(160) == 20.0 and mod.display_days(3) == 0.38
    assert mod.split_hour_chunks(Decimal("173")) == [Decimal("8.00")] * 21 + [Decimal("5.00")]
    assert mod.split_hour_chunks(Decimal("16")) == [Decimal("8.00"), Decimal("8.00")]
    assert mod.split_hour_chunks(Decimal("2.5")) == [Decimal("2.50")] and mod.split_hour_chunks(0) == []


def test_fill_progress_classifies_by_hours_and_shows_days_derived_from_them(mt, monkeypatch):
    mod, _ = mt
    setup(mt, ["Accounts User", "System Manager"], None)
    monkeypatch.setattr(mod, "resolve_monthly_work_limit", lambda year, month, employee=None, **kw: {"day_limit": 21.625, "hour_limit": 173}, raising=False)
    mod._query_monthly_entries = lambda period, employee=None: [
        {"employee": "E1", "hours": 173, "project": "P", "employee_name": ""},
        {"employee": "E2", "hours": 172, "project": "P", "employee_name": ""},
        {"employee": "E4", "hours": 173.5, "project": "P", "employee_name": ""},
    ]
    result = mod.get_fill_progress("2026-10")
    by_id = {row["employee"]: row for row in result["employees"]}
    assert {k: v["status"] for k, v in by_id.items()} == {"E1": "full", "E2": "part", "E3": "none", "E4": "over"}
    assert by_id["E1"]["limit_hours"] == 173.0 and by_id["E1"]["used_hours"] == 173.0
    assert by_id["E1"]["limit_days"] == 21.63 and by_id["E1"]["used_days"] == 21.63 and by_id["E2"]["used_days"] == 21.5
    assert result["summary"]["full"] == 1 and result["summary"]["over"] == 1


def test_the_hour_cap_is_exact_for_a_173_hour_month(mt):
    from decimal import Decimal
    mod, _ = mt
    resolve = lambda code, name, selected: selected
    row = lambda project, hours: {"project": project, "project_code": "C" + project, "project_name": "N" + project, "hours": hours}
    ok = mod.prepare_monthly_rows([row("A", "100"), row("B", "73")], 2026, 10, resolve, hour_limit=173)
    assert sum(r["calculated_hours"] for r in ok) == Decimal("173.00")
    assert [r["occurrence_days"] for r in ok] == [Decimal("12.50"), Decimal("9.13")]       # 73 / 8 = 9.125 -> 9.13（只是显示）
    with pytest.raises(RuleError) as caught:
        mod.prepare_monthly_rows([row("A", "100"), row("B", "73.5")], 2026, 10, resolve, hour_limit=173)
    message = str(caught.value)
    assert "当前 173.5 小时" in message and "最多 173 小时" in message and "约 21.63 天" in message
    # 5 小时请假：171 小时
    with pytest.raises(RuleError, match="最多 171 小时"):
        mod.prepare_monthly_rows([row("A", "171.5")], 2026, 10, resolve, hour_limit=171)
    assert mod.prepare_monthly_rows([row("A", "171")], 2026, 10, resolve, hour_limit=171)
    # 一行最多两位小数；hours 优先于老的 occurrence_days
    with pytest.raises(RuleError, match="最多保留两位小数"):
        mod.prepare_monthly_rows([row("A", "1.005")], 2026, 10, resolve, hour_limit=171)
    both = mod.prepare_monthly_rows([{**row("A", "10"), "occurrence_days": "3"}], 2026, 10, resolve, hour_limit=171)
    assert both[0]["calculated_hours"] == Decimal("10.00") and both[0]["occurrence_days"] == Decimal("1.25")


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "1.001"])
def test_invalid_hours_are_rejected(mt, value):
    mod, _ = mt
    with pytest.raises(RuleError):
        mod.parse_occurrence_hours(value, 2026, 10)


def test_hours_cannot_exceed_calendar_days_times_eight(mt):
    from decimal import Decimal
    mod, _ = mt
    assert mod.parse_occurrence_hours("248", 2026, 10) == Decimal("248.00")
    with pytest.raises(RuleError, match="自然日"):
        mod.parse_occurrence_hours("248.01", 2026, 10)
    assert mod.parse_occurrence_hours("224", 2026, 2) == Decimal("224.00")
    with pytest.raises(RuleError):
        mod.parse_occurrence_hours("224.5", 2026, 2)
