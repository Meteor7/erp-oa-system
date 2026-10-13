"""确认本月工资（决定 2026-10-13）：草稿核对完一次确认、确认后锁定；要改先撤回确认；总经理、副总经理只读。"""
import importlib
import json
import sys
import types
from datetime import date
from types import SimpleNamespace

import pytest


class PayrollRuleError(Exception):
    pass


def _load(monkeypatch, positions=()):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.whitelist = lambda *args, **kwargs: args[0] if args and callable(args[0]) else (lambda fn: fn)
    frappe.throw = lambda message: (_ for _ in ()).throw(PayrollRuleError(str(message)))
    frappe.flags = SimpleNamespace(via_payroll_entry=None)
    frappe.session = SimpleNamespace(user="boss@tests-x.example.invalid")
    frappe.parse_json = lambda value: json.loads(value) if isinstance(value, str) else value
    frappe.clear_messages = lambda: None
    frappe.db = SimpleNamespace(savepoints=[], rollbacks=[])
    frappe.db.savepoint = lambda name: frappe.db.savepoints.append(name)
    frappe.db.rollback = lambda save_point=None: frappe.db.rollbacks.append(save_point)
    frappe.get_all = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    utils = types.ModuleType("frappe.utils")
    utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(str(value))
    utils.get_last_day = lambda value: date(value.year, value.month, 31 if value.month in (1, 3, 5, 7, 8, 10, 12) else 30)
    monkeypatch.setitem(sys.modules, "frappe.utils", utils)
    guards = types.ModuleType("rayher_hr_payroll.api._guards")
    guards.calls = []
    guards.require_rd_access = lambda roles: guards.calls.append(tuple(roles))
    guards.parse_period = lambda value: tuple(int(part) for part in str(value).split("-")[:2])
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.api._guards", guards)
    access = types.ModuleType("rayher_hr_payroll.position_access")
    access.position_users = lambda *keys: {"boss@tests-x.example.invalid"} if any(key in positions for key in keys) else set()
    monkeypatch.setitem(sys.modules, "rayher_hr_payroll.position_access", access)
    # hr_read_access 引用的是这里替换的 frappe，所以每次重新导入
    sys.modules.pop("rayher_hr_payroll.hr_read_access", None)
    sys.modules.pop("rayher_hr_payroll.api.hr_payroll_entry", None)
    module = importlib.import_module("rayher_hr_payroll.api.hr_payroll_entry")
    return module, frappe, guards


class Slip:
    def __init__(self, frappe, name, fail=None):
        self.name, self.fail, self.frappe = name, fail, frappe
        self.flags = SimpleNamespace(ignore_permissions=False)
        self.submitted = False
        self.email_flag = None

    def submit(self):
        self.email_flag = self.frappe.flags.via_payroll_entry
        if self.fail:
            raise PayrollRuleError(self.fail)
        self.submitted = True


DRAFTS = [
    {"name": "SAL-1", "employee": "E1", "employee_name": "演示员工128", "hr_spa_managed": 1},
    {"name": "SAL-2", "employee": "E2", "employee_name": "演示员工143", "hr_spa_managed": 0},
    {"name": "SAL-3", "employee": "E3", "employee_name": "演示员工156", "hr_spa_managed": 1},
]


def test_confirm_submits_this_pages_drafts_without_emailing_and_skips_the_rest(monkeypatch):
    module, frappe, guards = _load(monkeypatch)
    captured = {}

    def get_all(doctype, filters=None, fields=None, order_by=None, **kwargs):
        captured.update(filters)
        return [dict(row) for row in DRAFTS]

    docs = {"SAL-1": Slip(frappe, "SAL-1"), "SAL-3": Slip(frappe, "SAL-3", fail="本期研发分摊已定版")}
    frappe.get_all = get_all
    frappe.get_doc = lambda doctype, name: docs[name]
    result = module.confirm_payroll("2026-10")

    assert captured == {"start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31), "docstatus": 0}
    assert guards.calls == [module.ROLES], "确认只有人事角色能做"
    assert result["confirmed"] == 1 and docs["SAL-1"].submitted and docs["SAL-1"].flags.ignore_permissions
    assert result["skipped"] == [
        {"employee": "E2", "employee_name": "演示员工143", "reason": "别处生成的工资条，不在这里确认"},
        {"employee": "E3", "employee_name": "演示员工156", "reason": "本期研发分摊已定版"},
    ]
    # 确认不顺带给员工发工资条邮件；确认完把开关还原
    assert docs["SAL-1"].email_flag is True and frappe.flags.via_payroll_entry is None
    # 失败的那张退回到它自己的保存点，不影响已确认的
    assert frappe.db.rollbacks == ["confirm_payroll"] and len(frappe.db.savepoints) == 2


def test_confirm_can_be_limited_to_chosen_people(monkeypatch):
    module, frappe, _ = _load(monkeypatch)
    frappe.get_all = lambda *args, **kwargs: [dict(row) for row in DRAFTS]
    docs = {"SAL-1": Slip(frappe, "SAL-1"), "SAL-3": Slip(frappe, "SAL-3")}
    frappe.get_doc = lambda doctype, name: docs[name]
    result = module.confirm_payroll("2026-10", employees=json.dumps(["E3"]))
    assert result["confirmed"] == 1 and docs["SAL-3"].submitted and not docs["SAL-1"].submitted
    assert result["skipped"] == []


class Confirmed:
    def __init__(self, managed=1):
        self.name, self.hr_spa_managed, self.docstatus = "SAL-9", managed, 1
        self.flags = SimpleNamespace(ignore_permissions=False)
        self.events = []

    def cancel(self):
        self.events.append("cancel")
        self.docstatus = 2

    def add_comment(self, kind, text):
        self.events.append((kind, text))


def test_withdraw_cancels_the_confirmed_slip_and_opens_a_draft_copy(monkeypatch):
    module, frappe, guards = _load(monkeypatch)
    slip = Confirmed()
    lookups = []
    frappe.db.get_value = lambda doctype, filters, field=None: lookups.append(filters) or "SAL-9"
    frappe.get_doc = lambda doctype, name: slip
    inserted = {}

    class Copy:
        name = "SAL-9-1"
        def insert(self, ignore_permissions=False):
            inserted.update({"docstatus": self.docstatus, "amended_from": self.amended_from, "perm": ignore_permissions})

    frappe.copy_doc = lambda doc: Copy()
    result = module.withdraw_payroll_confirmation("E9", "2026-10", "个税填错了")

    assert lookups == [{"employee": "E9", "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31), "docstatus": 1}]
    assert slip.events == ["cancel", ("Comment", "撤回确认：个税填错了")]
    assert inserted == {"docstatus": 0, "amended_from": "SAL-9", "perm": True}
    assert result == {"name": "SAL-9-1", "cancelled": "SAL-9"}
    assert guards.calls == [module.ROLES]


@pytest.mark.parametrize("reason, slip_name, managed, message", [
    ("", "SAL-9", 1, "请写撤回原因"),
    ("x" * 501, "SAL-9", 1, "不能超过 500"),
    ("改个税", None, 1, "没有已确认的工资条"),
    ("改个税", "SAL-9", 0, "别处生成的"),
])
def test_withdraw_needs_a_reason_and_this_pages_confirmed_slip(monkeypatch, reason, slip_name, managed, message):
    module, frappe, _ = _load(monkeypatch)
    frappe.db.get_value = lambda *args, **kwargs: slip_name
    frappe.get_doc = lambda doctype, name: Confirmed(managed)
    with pytest.raises(PayrollRuleError, match=message):
        module.withdraw_payroll_confirmation("E9", "2026-10", reason)


@pytest.mark.parametrize("positions, role_checked", [(("general_manager",), False), (("vice_manager",), False), (("hr_manager",), True), ((), True)])
def test_general_and_vice_manager_can_read_payroll_but_not_change_it(monkeypatch, positions, role_checked):
    module, frappe, guards = _load(monkeypatch, positions)
    module._require_read()
    assert bool(guards.calls) is role_checked
    # 改动类的接口仍然只认人事角色
    guards.calls.clear()
    frappe.get_all = lambda *args, **kwargs: []
    module.confirm_payroll("2026-10")
    assert guards.calls == [module.ROLES]


def test_a_new_draft_is_numbered_after_its_employee(monkeypatch):
    """新草稿的编号带员工号（Sal Slip/HR-EMP-1/…），不是 Sal Slip/None/…。"""
    module, frappe, _ = _load(monkeypatch)
    monkeypatch.setattr(module, "_employee", lambda employee: {"name": employee, "company": "Rayher", "employee_name": "演示员工128"})
    monkeypatch.setattr(module, "_social_record", lambda *args: {"employee_total": 100})
    monkeypatch.setattr(module, "_monthly_record", lambda *args: {"employee_amount": 50})
    monkeypatch.setattr(module, "_working_days", lambda *args: (22.0, 22.0, "hrms"))
    monkeypatch.setattr(module, "_accommodation", lambda *args: 0)
    monkeypatch.setattr(module, "_slip", lambda *args: None)
    monkeypatch.setattr(module, "ensure_payroll_masters", lambda company: {"salary_structure": "标准月薪 - Rayher"})

    class NewSlip:
        default_series = "Sal Slip/None/.#####"
        name = "NEW"
        def update(self, values): self.__dict__.update(values)
        def set(self, table, rows): setattr(self, table, list(rows))
        def append(self, table, row): getattr(self, table).append(row)
        def insert(self, ignore_permissions=False): self.inserted_series = self.default_series

    slip = NewSlip()
    frappe.new_doc = lambda doctype: slip
    module.save_payroll_draft("HR-EMP-1", "2026-10", base_salary=8000)
    assert slip.inserted_series == "Sal Slip/HR-EMP-1/.#####"

