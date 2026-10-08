import importlib
import sys
import types
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest


class RuleError(Exception):
    pass


def _install_fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.only_for = lambda roles: None
    frappe.get_roles = lambda user=None: ["Accounts User"]

    def throw(message):
        raise RuleError(str(message))

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    frappe.throw = throw
    frappe.whitelist = whitelist
    frappe.db = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    return frappe


def _load_allocation_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.allocation_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.allocation_entry")
    # 财务主管岗位默认没有人；需要的用例自己指定。没有岗位人的普通财务账号不能定版。
    monkeypatch.setattr(mod, "_finance_manager_users", lambda: set())
    return mod, frappe


def _as_user(monkeypatch, mod, frappe, user, roles, finance_managers=()):
    frappe.session = SimpleNamespace(user=user)
    frappe.get_roles = lambda user=None: list(roles)
    monkeypatch.setattr(mod, "_finance_manager_users", lambda: {name.lower() for name in finance_managers})


def test_cancel_allocation_allows_finance_to_cancel_submitted_allocations(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {"canceled": []}

    monkeypatch.setattr(mod, "_can_finalize", lambda: True)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: captured.setdefault("lock_check", args))
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: captured.setdefault("import_lock", (year, month)) or "IMP-1")

    def get_all(doctype, filters=None, pluck=None, **kwargs):
        captured["query"] = (doctype, filters, pluck)
        return ["ALLOC-1", "ALLOC-2"]

    class AllocationDoc:
        def __init__(self, name):
            self.name = name
            self.flags = SimpleNamespace()

        def cancel(self):
            captured["canceled"].append((self.name, getattr(self.flags, "ignore_permissions", False)))

    class CommentDoc:
        def __init__(self, values):
            self.values = values

        def insert(self, ignore_permissions=False):
            captured.setdefault("comments", []).append((self.values, ignore_permissions))
            captured["order"].append(("comment", self.values["reference_name"]))

    def get_doc(doctype, name=None):
        if isinstance(doctype, dict):
            return CommentDoc(doctype)
        assert doctype == "RD Cost Allocation"
        return AllocationDoc(name)

    captured["order"] = []
    original_cancel = AllocationDoc.cancel
    AllocationDoc.cancel = lambda self: (original_cancel(self), captured["order"].append(("cancel", self.name)))
    frappe.get_all = get_all
    frappe.get_doc = get_doc
    frappe.session = SimpleNamespace(user="zhangmeng@example.com")
    frappe.utils = SimpleNamespace(
        get_fullname=lambda user: "演示员工16",
        now_datetime=lambda: datetime(2026, 8, 3, 9, 30, 15),
    )
    frappe.db.savepoint = lambda name: captured.setdefault("savepoint", name)
    frappe.db.rollback = lambda save_point=None: captured.setdefault("rollback", save_point)
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.cancel_allocation("2026-07", "  工时补录了两个人  ")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["lock_check"] == ("2026-07", "lock_allocations", "分摊")
    assert captured["import_lock"] == (2026, 7)
    assert captured["query"] == (
        "RD Cost Allocation",
        {"year": 2026, "month": 7, "docstatus": 1},
        "name",
    )
    assert captured["savepoint"] == "rd_cancel_allocation"
    assert captured["canceled"] == [("ALLOC-1", True), ("ALLOC-2", True)]
    assert captured["committed"] is True
    assert result == {
        "ok": True, "period": "2026-07", "canceled": ["ALLOC-1", "ALLOC-2"], "reason": "工时补录了两个人",
    }
    # 每张被撤销的分摊单都留一条 Info 备注：谁、什么时候、为什么；先撤销再写备注。
    assert captured["comments"] == [
        (
            {
                "doctype": "Comment", "comment_type": "Info",
                "reference_doctype": "RD Cost Allocation", "reference_name": name,
                "content": "撤销定版：工时补录了两个人（演示员工16，2026-08-03 09:30:15）",
            },
            True,
        )
        for name in ("ALLOC-1", "ALLOC-2")
    ]
    assert captured["order"] == [
        ("cancel", "ALLOC-1"), ("comment", "ALLOC-1"), ("cancel", "ALLOC-2"), ("comment", "ALLOC-2"),
    ]


@pytest.mark.parametrize("reason", [None, "", "   ", "x" * 201, "\n\t "])
def test_cancel_allocation_requires_a_reason_of_1_to_200_characters(monkeypatch, reason):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args: (_ for _ in ()).throw(AssertionError("no lock")))
    _forbid_db(frappe)

    with pytest.raises(RuleError, match="请填写撤销原因（200 字以内）。"):
        mod.cancel_allocation("2026-07", reason)
    with pytest.raises(RuleError, match="请填写撤销原因（200 字以内）。"):
        mod.cancel_allocation("2026-07")


def test_cancel_allocation_accepts_a_200_character_reason(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: "IMP-1")
    frappe.get_all = lambda *args, **kwargs: []

    assert mod.cancel_allocation("2026-07", "因" * 200)["reason"] == "因" * 200


def test_cancel_allocation_checks_permission_before_the_reason(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    _forbid_db(frappe)

    with pytest.raises(RuleError, match=CANCEL_DENIED):
        mod.cancel_allocation("2026-07", "")


def test_cancel_allocation_rolls_back_when_writing_the_comment_fails(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    calls = []
    monkeypatch.setattr(mod, "_can_finalize", lambda: True)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: "IMP-1")
    frappe.get_all = lambda *args, **kwargs: ["ALLOC-1"]

    class AllocationDoc:
        flags = SimpleNamespace()

        def cancel(self):
            calls.append("cancel")

    class BrokenComment:
        def insert(self, ignore_permissions=False):
            raise RuleError("comment failed")

    frappe.get_doc = lambda doctype, name=None: BrokenComment() if isinstance(doctype, dict) else AllocationDoc()
    frappe.db.savepoint = lambda name: calls.append(("savepoint", name))
    frappe.db.rollback = lambda save_point=None: calls.append(("rollback", save_point))
    frappe.db.commit = lambda: calls.append("commit")

    with pytest.raises(RuleError, match="comment failed"):
        mod.cancel_allocation("2026-07", "原因")

    assert calls == [("savepoint", "rd_cancel_allocation"), "cancel", ("rollback", "rd_cancel_allocation")]


def test_cancel_allocation_returns_empty_when_period_has_no_submitted_allocation(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "_can_finalize", lambda: True)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: captured.setdefault("lock_check", args))
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: captured.setdefault("import_lock", (year, month)))
    frappe.get_all = lambda *args, **kwargs: []
    frappe.get_doc = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no allocation should be loaded"))

    result = mod.cancel_allocation("2026-07", "测试")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["lock_check"] == ("2026-07", "lock_allocations", "分摊")
    assert result == {"ok": True, "period": "2026-07", "canceled": [], "reason": "测试"}


def test_get_allocation_includes_project_and_stage_summaries(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
    )
    frappe.db.get_value = lambda *args, **kwargs: "ALLOC-1"

    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=0, lines=[1, 2, 3]
    )

    def get_all(doctype, filters=None, fields=None, group_by=None, order_by=None, **kwargs):
        if doctype == "RD Cost Allocation Line":
            captured["line_query"] = {"filters": filters, "fields": fields, "group_by": group_by, "order_by": order_by}
            return [
                SimpleNamespace(project="RD06", project_stage="capitalized", allocated_amount=70, basis_hours=10, ratio=20, line_count=2),
                SimpleNamespace(project="RD15", project_stage="expensed", allocated_amount=30, basis_hours=40, ratio=80, line_count=1),
            ]
        if doctype == "Project":
            captured["project_query"] = {"filters": filters, "fields": fields}
            return [
                SimpleNamespace(name="RD06", project_name="MUSHI 7546", rd_project_code="RD06"),
                SimpleNamespace(name="RD15", project_name="DRAKENS 4482", rd_project_code="RD15"),
            ]
        raise AssertionError(doctype)

    frappe.get_all = get_all

    result = mod.get_allocation("2026-06")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["line_query"]["filters"] == {"parent": "ALLOC-1"}
    assert result["stage_summaries"] == [
        {"stage": "capitalized", "label": "\u8d44\u672c\u5316", "total": 70},
        {"stage": "expensed", "label": "\u8d39\u7528\u5316", "total": 30},
        {"stage": "unknown", "label": "\u672a\u5224\u5b9a", "total": 0},
    ]
    assert result["project_summaries"] == [
        {
            "project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546",
            "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316",
            "basis_hours": 10, "ratio": 20, "allocated_amount": 70, "line_count": 2,
        },
        {
            "project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482",
            "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316",
            "basis_hours": 40, "ratio": 80, "allocated_amount": 30, "line_count": 1,
        },
    ]


def test_cancel_allocation_respects_period_allocation_lock(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "_can_finalize", lambda: True)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: (_ for _ in ()).throw(RuleError("locked")))
    frappe.get_all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("locked period should stop before query"))

    with pytest.raises(RuleError, match="locked"):
        mod.cancel_allocation("2026-07", "测试")


def test_get_allocation_year_aggregates_submitted_months(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
    )

    def get_all(doctype, filters=None, fields=None, **kwargs):
        if doctype == "RD Cost Allocation":
            captured["allocation_query"] = {"filters": filters, "fields": fields}
            return [
                SimpleNamespace(name="ALLOC-1", status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=0),
                SimpleNamespace(name="ALLOC-2", status="Submitted", capitalized_total=5, expensed_total=15, unknown_total=1),
            ]
        if doctype == "RD Cost Allocation Line":
            captured["line_query"] = {"filters": filters, "fields": fields, "pluck": kwargs.get("pluck")}
            return ["LINE-1", "LINE-2", "LINE-3"]
        raise AssertionError(doctype)

    frappe.get_all = get_all

    result = mod.get_allocation("2026-06", scope="year")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["allocation_query"]["filters"] == {"year": 2026, "docstatus": 1}
    assert "lines" not in captured["allocation_query"]["fields"]
    assert captured["line_query"]["filters"] == {"parent": ["in", ["ALLOC-1", "ALLOC-2"]]}
    assert result["period"] == "2026"
    assert result["scope"] == "year"
    assert result["allocation_names"] == ["ALLOC-1", "ALLOC-2"]
    assert result["capitalized"] == 75
    assert result["expensed"] == 45
    assert result["unknown"] == 1
    assert result["lines"] == 3
    assert result["stage_summaries"] == [
        {"stage": "capitalized", "label": "\u8d44\u672c\u5316", "total": 75},
        {"stage": "expensed", "label": "\u8d39\u7528\u5316", "total": 45},
        {"stage": "unknown", "label": "\u672a\u5224\u5b9a", "total": 1},
    ]



def test_foreign_stage_totals_propagates_foreign_calculation_failure(monkeypatch):
    mod, _frappe = _load_allocation_entry(monkeypatch)
    api_package = importlib.import_module("rayher_hr_payroll.api")

    def fail(year, month):
        raise RuntimeError("foreign totals failed")

    monkeypatch.setattr(
        api_package,
        "foreign_rd_entry",
        SimpleNamespace(_get_foreign_rd_month=fail),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="foreign totals failed"):
        mod._foreign_stage_totals(2026, 6)


def test_foreign_dashboard_lines_propagates_foreign_calculation_failure(monkeypatch):
    mod, _frappe = _load_allocation_entry(monkeypatch)
    module_name = (
        "rayher_hr_payroll.rayher_hr_payroll.report."
        "rd_allocation_matrix.rd_allocation_matrix"
    )
    report_module = types.ModuleType(module_name)

    def fail(year, month):
        raise RuntimeError("foreign dashboard failed")

    report_module._foreign_matrix_lines_for_month = fail
    monkeypatch.setitem(sys.modules, module_name, report_module)

    with pytest.raises(RuntimeError, match="foreign dashboard failed"):
        mod._foreign_dashboard_lines([(2026, 6)])


def test_get_allocation_returns_foreign_totals_without_domestic_allocation(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: ({
            "capitalized": 12,
            "expensed": 8,
            "unknown": 0,
        }, True),
    )
    frappe.db.get_value = lambda *args, **kwargs: None

    result = mod.get_allocation("2026-06")

    assert result["name"] is None
    assert result["status"] is None
    assert result["period"] == "2026-06"
    assert result["scope"] == "month"
    assert result["capitalized"] == 12
    assert result["expensed"] == 8
    assert result["unknown"] == 0
    assert result["lines"] == 0
    assert result["stage_summaries"] == [
        {"stage": "capitalized", "label": mod.STAGE_LABELS["capitalized"], "total": 12},
        {"stage": "expensed", "label": mod.STAGE_LABELS["expensed"], "total": 8},
        {"stage": "unknown", "label": mod.STAGE_LABELS["unknown"], "total": 0},
    ]
    assert result["project_summaries"] == []


def test_get_allocation_marks_foreign_expense_sources_as_business_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), True),
        raising=False,
    )
    frappe.db.get_value = lambda *args, **kwargs: None

    result = mod.get_allocation("2026-06")

    assert result["name"] is None
    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is True
    assert result["has_data"] is True


def test_get_allocation_marks_empty_month_as_no_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
        raising=False,
    )
    frappe.db.get_value = lambda *args, **kwargs: None

    result = mod.get_allocation("2026-06")

    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is False
    assert result["has_data"] is False


def test_get_allocation_marks_domestic_month_as_data(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (mod._zero_stage_totals(), False),
        raising=False,
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [])
    frappe.db.get_value = lambda *args, **kwargs: "ALLOC-1"
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name,
        status="Submitted",
        capitalized_total=0,
        expensed_total=0,
        unknown_total=0,
        lines=[],
    )

    result = mod.get_allocation("2026-06")

    assert result["has_domestic_data"] is True
    assert result["has_foreign_data"] is False
    assert result["has_data"] is True


def test_year_allocation_keeps_foreign_only_year_visible(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    frappe.get_all = lambda doctype, **kwargs: []
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: (
            {"capitalized": 12, "expensed": 8, "unknown": 0}
            if month == 6 else mod._zero_stage_totals(),
            month == 6,
        ),
        raising=False,
    )

    result = mod._year_allocation("2026-06")

    assert result["scope"] == "year"
    assert result["capitalized"] == 12
    assert result["expensed"] == 8
    assert result["has_domestic_data"] is False
    assert result["has_foreign_data"] is True
    assert result["has_data"] is True


def test_foreign_period_state_uses_real_sources_and_lines_not_empty_draft_name(monkeypatch):
    mod, _frappe = _load_allocation_entry(monkeypatch)
    api_package = importlib.import_module("rayher_hr_payroll.api")
    payloads = iter([
        {
            "name": "FOREIGN-DRAFT",
            "expense_sources": [],
            "lines": [],
            "foreign_stage_summaries": [],
        },
        {
            "name": None,
            "expense_sources": [{"expense_item": "EXP-1", "amount": 0}],
            "lines": [],
            "foreign_stage_summaries": [
                {"stage": "capitalized", "total": 12},
                {"stage": "expensed", "total": 8},
            ],
        },
    ])
    monkeypatch.setattr(
        api_package,
        "foreign_rd_entry",
        SimpleNamespace(_get_foreign_rd_month=lambda year, month: next(payloads)),
        raising=False,
    )

    empty_totals, empty_has_data = mod._foreign_period_state(2026, 6)
    source_totals, source_has_data = mod._foreign_period_state(2026, 7)

    assert empty_totals == mod._zero_stage_totals()
    assert empty_has_data is False
    assert source_totals == {"capitalized": 12.0, "expensed": 8.0, "unknown": 0.0}
    assert source_has_data is True


def test_get_allocation_adds_foreign_stage_totals_to_summary_cards(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(
        mod,
        "_foreign_period_state",
        lambda year, month: ({
            "capitalized": 5,
            "expensed": 7,
            "unknown": 1,
        }, True),
    )
    frappe.db.get_value = lambda *args, **kwargs: "ALLOC-1"
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=0, lines=[]
    )
    frappe.get_all = lambda doctype, **kwargs: []

    result = mod.get_allocation("2026-06")

    assert result["capitalized"] == 75
    assert result["expensed"] == 37
    assert result["unknown"] == 1
    assert result["stage_summaries"] == [
        {"stage": "capitalized", "label": "\u8d44\u672c\u5316", "total": 75},
        {"stage": "expensed", "label": "\u8d39\u7528\u5316", "total": 37},
        {"stage": "unknown", "label": "\u672a\u5224\u5b9a", "total": 1},
    ]


def test_get_allocation_dashboard_builds_second_level_summary_with_grand_total(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "_foreign_dashboard_lines", lambda periods: [], raising=False)
    frappe.db.get_value = lambda *args, **kwargs: "ALLOC-1"

    def get_all(doctype, filters=None, fields=None, order_by=None, limit_page_length=None, **kwargs):
        if doctype == "RD Cost Allocation Line":
            captured["line_query"] = {"filters": filters, "fields": fields, "order_by": order_by}
            return [
                SimpleNamespace(parent="ALLOC-1", voucher_no="118", expense_item_name="source-a", account_level_3="", account_level_4="", project="RD02", project_stage="capitalized", allocated_amount=60),
                SimpleNamespace(parent="ALLOC-1", voucher_no="118", expense_item_name="source-a", account_level_3="", account_level_4="", project="RD03", project_stage="expensed", allocated_amount=40),
                SimpleNamespace(parent="ALLOC-1", voucher_no="119", expense_item_name="source-b", account_level_3="人工费", account_level_4="", project="RD02", project_stage="capitalized", allocated_amount=10),
            ]
        if doctype == "RD Allocation Source Expense":
            captured["snapshot_query"] = {"filters": filters, "fields": fields}
            return [
                SimpleNamespace(parent="ALLOC-1", voucher_no="118", expense_item="source-a", account_level_1="研发费用", account_level_2="其他相关费用", account_level_3="差旅费", account_level_4="住宿费", amount=100, direct_project=None),
                SimpleNamespace(parent="ALLOC-1", voucher_no="119", expense_item="source-b", account_level_1="研发费用", account_level_2="人员人工费用", account_level_3="人工费", account_level_4="", amount=10, direct_project=None),
            ]
        if doctype == "Project":
            return [
                SimpleNamespace(name="RD02", project_name="ADC", rd_project_code="RD02"),
                SimpleNamespace(name="RD03", project_name="Automation platform", rd_project_code="RD03"),
            ]
        raise AssertionError(doctype)

    frappe.get_all = get_all

    result = mod.get_allocation_dashboard("2026-06", scope="month", mode="all")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["line_query"]["filters"] == {"parent": "ALLOC-1"}
    assert result["period"] == "2026-06"
    assert result["scope"] == "month"
    assert result["mode"] == "all"
    assert result["total_amount"] == 110
    assert result["second_level_count"] == 2
    assert result["third_level_count"] == 2
    assert result["project_columns"] == [
        {"project": "RD02", "project_code": "RD02", "project_name": "ADC", "label": "RD02 ADC", "stage": "capitalized", "stage_label": "\u8d44\u672c\u5316"},
        {"project": "RD03", "project_code": "RD03", "project_name": "Automation platform", "label": "RD03 Automation platform", "stage": "expensed", "stage_label": "\u8d39\u7528\u5316"},
    ]

    travel = next(row for row in result["summary_rows"] if row["account_level_3"] == "差旅费" and row["row_type"] == "detail")
    assert travel["account_level_1"] == "研发费用"
    assert travel["account_level_2"] == "其他相关费用"
    assert travel["total"] == 100
    assert travel["projects"] == {"RD02": 60, "RD03": 40}

    other_subtotal = next(row for row in result["summary_rows"] if row["account_level_2"] == "其他相关费用 汇总")
    assert other_subtotal["row_type"] == "subtotal"
    assert other_subtotal["total"] == 100
    assert other_subtotal["projects"] == {"RD02": 60, "RD03": 40}

    grand_total = result["summary_rows"][-1]
    assert grand_total["row_type"] == "grand_total"
    assert grand_total["account_level_1"] == "总计"
    assert grand_total["total"] == 110
    assert grand_total["projects"] == {"RD02": 70, "RD03": 40}
    assert "detail_rows" not in result

    filtered = mod.get_allocation_dashboard("2026-06", scope="month", mode="capitalized")
    assert filtered["mode"] == "capitalized"
    assert filtered["total_amount"] == 70
    filtered_travel = next(row for row in filtered["summary_rows"] if row["account_level_3"] == "差旅费" and row["row_type"] == "detail")
    assert filtered_travel["projects"] == {"RD02": 60}


# ---------------------------------------------------------------------------
# 预览 + 定版（2026-10）：权限、定版、撤销、预览数据、定版检查
# ---------------------------------------------------------------------------
FINALIZE_DENIED = "只有财务主管可以定版本月分摊。"
CANCEL_DENIED = "只有财务主管可以撤销定版。"
ALREADY_FINALIZED = "本月分摊已定版。要重新定版，请先撤销定版。"


def _forbid_db(frappe):
    def boom(*args, **kwargs):
        raise AssertionError("must stop before touching the database")

    frappe.get_all = boom
    frappe.get_doc = boom
    frappe.db.get_value = boom
    frappe.db.savepoint = boom
    frappe.db.commit = boom


@pytest.mark.parametrize(
    "user, roles, managers, allowed",
    [
        ("Administrator", ["Administrator"], (), True),
        ("boss@example.com", ["System Manager", "Accounts User"], (), True),
        ("zhangmeng@example.com", ["Accounts User", "Department Manager"], ("ZhangMeng@example.com",), True),
        ("clerk@example.com", ["Accounts User"], ("zhangmeng@example.com",), False),
        ("clerk@example.com", ["Accounts User"], (), False),
        ("", ["Accounts User"], ("",), False),
    ],
)
def test_can_finalize_permission_matrix(monkeypatch, user, roles, managers, allowed):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, user, roles, managers)

    assert mod._can_finalize() is allowed


def test_finalize_allocation_is_refused_for_an_ordinary_finance_user_before_any_database_access(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args: (_ for _ in ()).throw(AssertionError("no lock")))
    _forbid_db(frappe)

    with pytest.raises(RuleError, match=FINALIZE_DENIED):
        mod.finalize_allocation("2026-07")


def test_cancel_allocation_is_refused_for_an_ordinary_finance_user_before_any_database_access(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda *args: (_ for _ in ()).throw(AssertionError("no lock")))
    _forbid_db(frappe)

    with pytest.raises(RuleError, match=CANCEL_DENIED):
        mod.cancel_allocation("2026-07", "测试")


def test_recalc_allocation_is_a_deprecated_alias_with_the_same_permission(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    _forbid_db(frappe)

    with pytest.raises(RuleError, match=FINALIZE_DENIED):
        mod.recalc_allocation("2026-07")

    monkeypatch.setattr(mod, "finalize_allocation", lambda period: {"finalized": period})
    assert mod.recalc_allocation("2026-07") == {"finalized": "2026-07"}


def _prepare_finalize(monkeypatch, *, already_finalized=False, import_name="IMP-1", fail_in_calculate=False):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    calls = []

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: calls.append(("roles", roles)))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: calls.append(("lock_check", args)))
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: calls.append(("import_lock", (year, month))) or import_name)
    monkeypatch.setattr(mod, "period_has_submitted_allocation", lambda year, month: already_finalized)
    monkeypatch.setattr(mod, "get_allocation", lambda period: {"name": "ALLOC-NEW", "period": period})

    class ImportDoc:
        name = "IMP-1"
        docstatus = 0

        def submit(self):
            calls.append("import_submit")

    class AllocationDoc:
        def calculate(self):
            calls.append("calculate")
            if fail_in_calculate:
                raise ValueError("duplicated labour")

        def insert(self, ignore_permissions=False):
            calls.append(("insert", ignore_permissions))

        def submit(self):
            calls.append("allocation_submit")

    monkeypatch.setattr(
        mod, "_new_allocation_doc",
        lambda period, year, month, imp: calls.append(("new_allocation", period, year, month, imp)) or AllocationDoc(),
    )
    frappe.get_doc = lambda doctype, name: ImportDoc() if (doctype, name) == ("RD Expense Import", "IMP-1") else (_ for _ in ()).throw(AssertionError((doctype, name)))
    frappe.get_all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("finalize must not supersede anything"))
    frappe.db.savepoint = lambda name: calls.append(("savepoint", name))
    frappe.db.rollback = lambda save_point=None: calls.append(("rollback", save_point))
    frappe.db.commit = lambda: calls.append("commit")
    return mod, calls


def test_finalize_allocation_submits_the_import_then_creates_and_submits_the_allocation(monkeypatch):
    mod, calls = _prepare_finalize(monkeypatch)

    result = mod.finalize_allocation("2026-07")

    assert result == {"name": "ALLOC-NEW", "period": "2026-07"}
    assert calls == [
        ("roles", mod.RD_FINANCE_ROLES),
        ("lock_check", ("2026-07", "lock_allocations", "分摊")),
        ("import_lock", (2026, 7)),
        ("savepoint", "rd_recalc"),
        "import_submit",
        ("new_allocation", "2026-07", 2026, 7, "IMP-1"),
        "calculate",
        ("insert", True),
        "allocation_submit",
        "commit",
    ]


def test_finalize_allocation_refuses_a_month_that_is_already_finalized(monkeypatch):
    mod, calls = _prepare_finalize(monkeypatch, already_finalized=True)

    with pytest.raises(RuleError, match=ALREADY_FINALIZED):
        mod.finalize_allocation("2026-07")

    assert "commit" not in calls
    assert not any(isinstance(call, tuple) and call[0] in {"savepoint", "new_allocation"} for call in calls)


def test_finalize_allocation_needs_an_expense_import(monkeypatch):
    mod, calls = _prepare_finalize(monkeypatch, import_name=None)

    with pytest.raises(RuleError, match="没有费用导入单"):
        mod.finalize_allocation("2026-07")

    assert "commit" not in calls


def test_finalize_allocation_rolls_back_when_the_calculation_fails(monkeypatch):
    mod, calls = _prepare_finalize(monkeypatch, fail_in_calculate=True)

    with pytest.raises(ValueError, match="duplicated labour"):
        mod.finalize_allocation("2026-07")

    assert ("rollback", "rd_recalc") in calls
    assert "commit" not in calls
    assert "allocation_submit" not in calls


def test_cancel_allocation_runs_for_a_finance_manager_position_holder(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    canceled = []

    class AllocationDoc:
        flags = SimpleNamespace()

        def cancel(self):
            canceled.append("ALLOC-1")

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: None)
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: "IMP-1")
    monkeypatch.setattr(mod, "_add_cancel_comment", lambda name, reason: canceled.append(("comment", name, reason)))
    frappe.get_all = lambda *args, **kwargs: ["ALLOC-1"]
    frappe.get_doc = lambda doctype, name: AllocationDoc()
    frappe.db.savepoint = lambda name: None
    frappe.db.commit = lambda: None

    assert mod.cancel_allocation("2026-07", "数据有误") == {
        "ok": True, "period": "2026-07", "canceled": ["ALLOC-1"], "reason": "数据有误",
    }
    assert canceled == ["ALLOC-1", ("comment", "ALLOC-1", "数据有误")]


def _never_write():
    def boom(*args, **kwargs):
        raise AssertionError("a preview must not write")

    return boom


def _preview_doc(lines=None, totals=(70, 30, 0)):
    if lines is None:
        lines = [
            SimpleNamespace(project="RD06", project_stage="capitalized", allocated_amount=Decimal("40.00"), basis_hours=10, ratio=20),
            SimpleNamespace(project="RD06", project_stage="capitalized", allocated_amount=Decimal("30.00"), basis_hours=10, ratio=20),
            SimpleNamespace(project="RD15", project_stage="expensed", allocated_amount=Decimal("30.00"), basis_hours=40, ratio=80),
        ]
    boom = _never_write()
    return SimpleNamespace(
        name=None, capitalized_total=totals[0], expensed_total=totals[1], unknown_total=totals[2], lines=lines,
        insert=boom, submit=boom, save=boom, db_set=boom, cancel=boom,
    )


def _prepare_month(monkeypatch, *, foreign=None, has_foreign=False, submitted=None, preview=None):
    mod, frappe = _load_allocation_entry(monkeypatch)
    projects = []
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    # 撤销记录的查询有自己的用例；这里的 get_all 只允许查 Project。
    monkeypatch.setattr(mod, "_last_revoke", lambda year, month: None)
    monkeypatch.setattr(mod, "_foreign_period_state", lambda year, month: (foreign or mod._zero_stage_totals(), has_foreign))
    frappe.db.get_value = lambda *args, **kwargs: submitted

    def build_preview(period, year, month):
        if isinstance(preview, Exception):
            raise preview
        return preview

    monkeypatch.setattr(mod, "_build_preview", build_preview)

    def get_all(doctype, **kwargs):
        projects.append(doctype)
        if doctype == "Project":
            return [
                SimpleNamespace(name="RD06", project_name="MUSHI 7546", rd_project_code="RD06"),
                SimpleNamespace(name="RD15", project_name="DRAKENS 4482", rd_project_code="RD15"),
            ]
        raise AssertionError("a preview must not query allocation rows: " + doctype)

    frappe.get_all = get_all
    frappe.get_doc = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("a preview must not load or build documents"))
    frappe.db.commit = _never_write()
    return mod, frappe, projects


def test_get_allocation_returns_a_read_only_preview_when_the_month_is_not_finalized(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=_preview_doc(), warnings=["以下员工未计入：演示员工157"], error=None)
    mod, frappe, queried = _prepare_month(
        monkeypatch, foreign={"capitalized": 5, "expensed": 0, "unknown": 2}, has_foreign=True, preview=preview,
    )
    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])

    result = mod.get_allocation("2026-07")

    assert result["preview"] is True
    assert result["finalized"] is False
    assert result["can_finalize"] is False
    assert result["name"] is None
    assert result["status"] == "预览"
    assert result["period"] == "2026-07"
    assert result["scope"] == "month"
    assert result["has_data"] is True
    assert result["has_domestic_data"] is True
    assert result["has_foreign_data"] is True
    assert result["lines"] == 3
    assert (result["capitalized"], result["expensed"], result["unknown"]) == (75, 30, 2)
    assert result["stage_summaries"] == [
        {"stage": "capitalized", "label": "资本化", "total": 75},
        {"stage": "expensed", "label": "费用化", "total": 30},
        {"stage": "unknown", "label": "未判定", "total": 2},
    ]
    assert result["project_summaries"] == [
        {
            "project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546",
            "project_stage": "capitalized", "stage_label": "资本化",
            "basis_hours": 10, "ratio": 20, "allocated_amount": 70, "line_count": 2,
        },
        {
            "project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482",
            "project_stage": "expensed", "stage_label": "费用化",
            "basis_hours": 40, "ratio": 80, "allocated_amount": 30, "line_count": 1,
        },
    ]
    assert result["preview_warnings"] == ["以下员工未计入：演示员工157"]
    assert "preview_error" not in result
    # 只查了项目名称；没有读分摊明细表，更没有写入（文档上的 insert/submit/save 一碰就报错）。
    assert queried == ["Project"]


def test_get_allocation_preview_tells_a_finance_manager_they_can_finalize(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=_preview_doc(), warnings=[], error=None)
    mod, frappe, _queried = _prepare_month(monkeypatch, preview=preview)
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])

    result = mod.get_allocation("2026-07")

    assert result["preview"] is True
    assert result["can_finalize"] is True
    assert result["preview_warnings"] == []


def test_get_allocation_reports_preview_error_and_zero_domestic_totals(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=None, warnings=["w"], error="本期同时存在「人工费」类导入费用")
    mod, frappe, _queried = _prepare_month(
        monkeypatch, foreign={"capitalized": 12, "expensed": 8, "unknown": 0}, has_foreign=True, preview=preview,
    )

    result = mod.get_allocation("2026-07")

    assert result["preview"] is False
    assert result["finalized"] is False
    assert result["preview_error"] == "本期同时存在「人工费」类导入费用"
    assert result["status"] is None
    assert result["name"] is None
    assert result["has_domestic_data"] is False
    assert result["has_data"] is True
    assert result["lines"] == 0
    assert (result["capitalized"], result["expensed"], result["unknown"]) == (12, 8, 0)
    assert result["project_summaries"] == []


def test_get_allocation_without_an_import_is_neither_preview_nor_finalized(monkeypatch):
    mod, _frappe, _queried = _prepare_month(monkeypatch, preview=None)

    result = mod.get_allocation("2026-07")

    assert result["preview"] is False
    assert result["finalized"] is False
    assert result["can_finalize"] is False
    assert result["has_data"] is False
    assert result["has_domestic_data"] is False
    assert result["status"] is None
    assert "preview_error" not in result


def test_get_allocation_for_a_finalized_month_never_computes_a_preview(monkeypatch):
    mod, frappe, _queried = _prepare_month(
        monkeypatch, submitted="ALLOC-1",
        preview=AssertionError("a finalized month must not be previewed"),
    )
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=0, lines=[1, 2, 3],
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [{"project": "RD06"}])

    result = mod.get_allocation("2026-07")

    assert result["finalized"] is True
    assert result["preview"] is False
    assert result["can_finalize"] is True
    assert result["name"] == "ALLOC-1"
    assert result["status"] == "Submitted"
    assert result["lines"] == 3
    assert result["project_summaries"] == [{"project": "RD06"}]
    assert result["preview_warnings"] == []


def test_get_allocation_finalized_month_says_who_finalized_and_when(monkeypatch):
    mod, frappe, _queried = _prepare_month(
        monkeypatch, submitted="ALLOC-1",
        preview=AssertionError("a finalized month must not be previewed"),
    )
    frappe.utils = SimpleNamespace(get_fullname=lambda user: {"zhangmeng@example.com": "演示员工16"}.get(user, user))
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=0, lines=[1, 2, 3],
        owner="creator@example.com", creation=datetime(2026, 10, 8, 15, 19, 58),
        modified_by="zhangmeng@example.com", modified=datetime(2026, 10, 8, 15, 20, 33, 123456),
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [])
    monkeypatch.setattr(mod, "_last_revoke", lambda year, month: {"by": "a", "by_name": "A", "on": "2026-10-07 09:00:00", "reason": "r"})

    result = mod.get_allocation("2026-10")

    # 提交那一刻（modified_by / modified），不是创建人
    assert result["finalized_by"] == "zhangmeng@example.com"
    assert result["finalized_by_name"] == "演示员工16"
    assert result["finalized_on"] == "2026-10-08 15:20:33"
    # 重新定版后上次撤销的记录仍然带出来（页面只在预览时显示）
    assert result["last_revoke"]["reason"] == "r"


def test_get_allocation_finalized_info_falls_back_to_owner_creation_and_account(monkeypatch):
    mod, frappe, _queried = _prepare_month(monkeypatch, submitted="ALLOC-1")
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=1, expensed_total=0, unknown_total=0, lines=[],
        owner="creator@example.com", creation="2026-10-08 15:19:58.500000", modified_by=None, modified=None,
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [])

    result = mod.get_allocation("2026-10")

    # frappe.utils 不可用 / 没有姓名时显示账号
    assert result["finalized_by"] == "creator@example.com"
    assert result["finalized_by_name"] == "creator@example.com"
    assert result["finalized_on"] == "2026-10-08 15:19:58"


def test_get_allocation_preview_and_empty_month_have_no_finalized_info_but_carry_last_revoke(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=_preview_doc(), warnings=[], error=None)
    mod, _frappe, _queried = _prepare_month(monkeypatch, preview=preview)
    revoke = {"by": "zhangmeng@example.com", "by_name": "演示员工16", "on": "2026-10-08 15:20:33", "reason": "补录一笔费用"}
    monkeypatch.setattr(mod, "_last_revoke", lambda year, month: revoke if (year, month) == (2026, 10) else None)

    result = mod.get_allocation("2026-10")

    assert result["preview"] is True
    assert (result["finalized_by"], result["finalized_by_name"], result["finalized_on"]) == (None, None, None)
    assert result["last_revoke"] == revoke
    assert mod.get_allocation("2026-09")["last_revoke"] is None

    empty_mod, _f, _q = _prepare_month(monkeypatch, preview=None)
    empty = empty_mod.get_allocation("2026-10")
    assert empty["last_revoke"] is None
    assert empty["finalized_by"] is None


def test_get_allocation_year_scope_has_no_finalized_info_or_last_revoke(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_foreign_period_state", lambda year, month: (mod._zero_stage_totals(), False))
    frappe.get_all = lambda doctype, **kwargs: []

    result = mod.get_allocation("2026-07", scope="year")

    assert "last_revoke" not in result
    assert "finalized_by" not in result


@pytest.mark.parametrize("content,expected", [
    (
        "撤销定版：补录一笔费用（演示员工16，2026-10-08 15:20:33）",
        {"reason": "补录一笔费用", "by_name": "演示员工16", "on": "2026-10-08 15:20:33"},
    ),
    (
        # 原因里自己带括号、逗号：只认最后一组「（姓名，时间）」
        "撤销定版：6 月（含补录）有一笔费用，项目录错了（zhangmeng@example.com，2026-10-08 15:20:33）",
        {"reason": "6 月（含补录）有一笔费用，项目录错了", "by_name": "zhangmeng@example.com", "on": "2026-10-08 15:20:33"},
    ),
    (
        # 半角冒号、括号、逗号也认
        "撤销定版: wrong project (Zhang Meng, 2026-10-08 15:20:33)",
        {"reason": "wrong project", "by_name": "Zhang Meng", "on": "2026-10-08 15:20:33"},
    ),
    (
        "撤销定版：第一行\n第二行（演示员工16，2026-10-08 15:20:33）\n",
        {"reason": "第一行\n第二行", "by_name": "演示员工16", "on": "2026-10-08 15:20:33"},
    ),
    (
        # 没有姓名和时间尾巴：整段当原因
        "撤销定版：只有原因",
        {"reason": "只有原因", "by_name": "", "on": ""},
    ),
    ("撤销定版：", {"reason": "", "by_name": "", "on": ""}),
    (None, {"reason": "", "by_name": "", "on": ""}),
])
def test_parse_revoke_comment_is_tolerant(monkeypatch, content, expected):
    mod, _frappe = _load_allocation_entry(monkeypatch)

    assert mod._parse_revoke_comment(content) == expected


def test_parse_revoke_comment_reads_what_cancel_allocation_writes(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    frappe.session = SimpleNamespace(user="zhangmeng@example.com")
    frappe.utils = SimpleNamespace(get_fullname=lambda user: "演示员工16", now_datetime=lambda: datetime(2026, 10, 8, 15, 20, 33))

    text = mod._cancel_comment_text("发现（6 月）一笔费用录错了项目，改完重新定版")

    assert mod._parse_revoke_comment(text) == {
        "reason": "发现（6 月）一笔费用录错了项目，改完重新定版", "by_name": "演示员工16", "on": "2026-10-08 15:20:33",
    }


def _revoke_frappe(frappe, *, cancelled, comments, calls=None):
    calls = calls if calls is not None else []

    def get_all(doctype, **kwargs):
        calls.append((doctype, kwargs))
        if doctype == "RD Cost Allocation":
            return list(cancelled)
        assert doctype == "Comment"
        return list(comments)

    frappe.get_all = get_all
    frappe.utils = SimpleNamespace(get_fullname=lambda user: {"zhangmeng@example.com": "演示员工16"}.get(user, user))
    return calls


def test_last_revoke_is_none_without_cancelled_allocations(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    calls = _revoke_frappe(frappe, cancelled=[], comments=[{"content": "撤销定版：x（A，2026-10-08 15:20:33）"}])

    assert mod._last_revoke(2026, 10) is None
    # 没有已取消的分摊单就不再查备注
    assert [doctype for doctype, _kwargs in calls] == ["RD Cost Allocation"]
    assert calls[0][1]["filters"] == {"year": 2026, "month": 10, "docstatus": 2}


def test_last_revoke_is_none_when_cancelled_allocations_have_no_revoke_comment(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    calls = _revoke_frappe(frappe, cancelled=["ALLOC-1", "ALLOC-2"], comments=[])

    assert mod._last_revoke(2026, 10) is None
    comment_filters = calls[1][1]["filters"]
    assert comment_filters == {
        "reference_doctype": "RD Cost Allocation",
        "reference_name": ["in", ["ALLOC-1", "ALLOC-2"]],
        "comment_type": "Info",
        "content": ["like", "撤销定版%"],
    }
    # 最新的一条
    assert calls[1][1]["order_by"] == "creation desc"
    assert calls[1][1]["limit_page_length"] == 1


def test_last_revoke_uses_the_comment_owner_and_creation_and_parses_the_reason(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _revoke_frappe(frappe, cancelled=["ALLOC-1"], comments=[{
        "content": "撤销定版：补录一笔费用（演示员工16，2026-10-08 15:20:30）",
        "owner": "zhangmeng@example.com",
        "creation": datetime(2026, 10, 8, 15, 20, 31, 456000),
    }])

    assert mod._last_revoke(2026, 10) == {
        "by": "zhangmeng@example.com", "by_name": "演示员工16", "on": "2026-10-08 15:20:31", "reason": "补录一笔费用",
    }


def test_last_revoke_falls_back_to_the_text_when_the_comment_has_no_owner_or_creation(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _revoke_frappe(frappe, cancelled=["ALLOC-1"], comments=[{
        "content": "撤销定版：补录一笔费用（演示员工16，2026-10-08 15:20:30）", "owner": None, "creation": None,
    }])

    assert mod._last_revoke(2026, 10) == {
        "by": None, "by_name": "演示员工16", "on": "2026-10-08 15:20:30", "reason": "补录一笔费用",
    }


def test_last_revoke_with_an_unparseable_comment_keeps_the_text_as_the_reason(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    _revoke_frappe(frappe, cancelled=["ALLOC-1"], comments=[{
        "content": "撤销定版：手工备注", "owner": "zhangmeng@example.com", "creation": "2026-10-08 15:20:31.000000",
    }])

    assert mod._last_revoke(2026, 10) == {
        "by": "zhangmeng@example.com", "by_name": "演示员工16", "on": "2026-10-08 15:20:31", "reason": "手工备注",
    }


def test_last_revoke_never_breaks_the_page_when_the_lookup_fails(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    frappe.get_all = boom

    assert mod._last_revoke(2026, 10) is None


def test_get_allocation_year_scope_tells_whether_the_user_can_finalize(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_foreign_period_state", lambda year, month: (mod._zero_stage_totals(), False))
    frappe.get_all = lambda doctype, **kwargs: []
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])

    assert mod.get_allocation("2026-07", scope="year")["can_finalize"] is True

    _as_user(monkeypatch, mod, frappe, "clerk@example.com", ["Accounts User"])
    year = mod.get_allocation("2026-07", scope="year")
    assert year["can_finalize"] is False
    assert year["scope"] == "year"


def test_aggregate_line_rows_matches_the_sql_grouping(monkeypatch):
    mod, _frappe = _load_allocation_entry(monkeypatch)

    rows = mod._aggregate_line_rows([
        {"project": "RD15", "project_stage": "expensed", "allocated_amount": 5, "basis_hours": 2, "ratio": 10},
        {"project": "RD06", "project_stage": "capitalized", "allocated_amount": 1, "basis_hours": 7, "ratio": 3},
        {"project": "RD06", "project_stage": "capitalized", "allocated_amount": 2, "basis_hours": 9, "ratio": 1},
        {"project": "RD06", "project_stage": "expensed", "allocated_amount": 4, "basis_hours": 1, "ratio": 1},
        {"project": "RD15", "project_stage": None, "allocated_amount": None, "basis_hours": None, "ratio": None},
    ])

    assert rows == [
        {"project": "RD06", "project_stage": "capitalized", "allocated_amount": 3.0, "basis_hours": 9.0, "ratio": 3.0, "line_count": 2},
        {"project": "RD06", "project_stage": "expensed", "allocated_amount": 4.0, "basis_hours": 1.0, "ratio": 1.0, "line_count": 1},
        {"project": "RD15", "project_stage": "expensed", "allocated_amount": 5.0, "basis_hours": 2.0, "ratio": 10.0, "line_count": 1},
        {"project": "RD15", "project_stage": "unknown", "allocated_amount": 0.0, "basis_hours": 0.0, "ratio": 0.0, "line_count": 1},
    ]


def _install_check_sources(monkeypatch, *, fill_rows, unallocated=0):
    api_package = importlib.import_module("rayher_hr_payroll.api")
    monkeypatch.setattr(
        api_package, "monthly_timesheet_entry",
        SimpleNamespace(_fill_rows=lambda year, month, scope: (
            calls_for_scope.append(scope) or [{"status": status} for status in fill_rows]
        )),
        raising=False,
    )
    monkeypatch.setattr(
        api_package, "foreign_rd_entry",
        SimpleNamespace(_get_foreign_rd_month=lambda year, month: {"unallocated_common_amount": unallocated}),
        raising=False,
    )


calls_for_scope = []


def test_get_finalize_check_returns_the_checklist_for_a_preview(monkeypatch):
    del calls_for_scope[:]
    doc = _preview_doc(totals=(70, 30, 20), lines=[
        SimpleNamespace(project="RD06", project_stage="capitalized", allocated_amount=70, basis_hours=1, ratio=1),
        SimpleNamespace(project="RD15", project_stage="expensed", allocated_amount=30, basis_hours=1, ratio=1),
        SimpleNamespace(project="RD15", project_stage="unknown", allocated_amount=20.5, basis_hours=1, ratio=1),
    ])
    preview = SimpleNamespace(import_name="IMP-1", doc=doc, warnings=["w1", "w2"], error=None)
    mod, frappe, _queried = _prepare_month(
        monkeypatch, foreign={"capitalized": 0, "expensed": 0, "unknown": 5}, has_foreign=True, preview=preview,
    )
    _as_user(monkeypatch, mod, frappe, "zhangmeng@example.com", ["Accounts User"], ["zhangmeng@example.com"])
    _install_check_sources(
        monkeypatch, fill_rows=["none", "none", "part", "over", "full", "full"], unallocated=12.5,
    )

    result = mod.get_finalize_check("2026-07")

    assert result == {
        "period": "2026-07",
        "can_finalize": True,
        "preview": True,
        "finalized": False,
        "unfilled_people": 2,
        "underfilled_people": 1,
        "over_limit_people": 1,
        "unknown_amount": 25.0,
        "unallocated_foreign_common_amount": 12.5,
        "reconcile_diff": 0.5,
        "warnings": ["w1", "w2"],
    }
    # 全部研发人员（scope=None），不受当前账号部门范围限制。
    assert calls_for_scope == [None]


def test_get_finalize_check_warns_when_there_is_no_import_or_the_preview_failed(monkeypatch):
    del calls_for_scope[:]
    mod, _frappe, _queried = _prepare_month(monkeypatch, preview=None)
    _install_check_sources(monkeypatch, fill_rows=[])

    no_import = mod.get_finalize_check("2026-07")

    assert no_import["preview"] is False
    assert no_import["warnings"] == ["本月还没有费用导入单，无法定版。"]
    assert no_import["reconcile_diff"] == 0

    failed = SimpleNamespace(import_name="IMP-1", doc=None, warnings=["w"], error="重复科目")
    mod, _frappe, _queried = _prepare_month(monkeypatch, preview=failed)
    _install_check_sources(monkeypatch, fill_rows=[])

    result = mod.get_finalize_check("2026-07")

    assert result["preview"] is False
    assert result["preview_error"] == "重复科目"
    assert result["warnings"] == ["w", "重复科目"]


def test_get_finalize_check_warns_when_the_preview_has_nothing_to_allocate(monkeypatch):
    del calls_for_scope[:]
    preview = SimpleNamespace(import_name="IMP-1", doc=_preview_doc(lines=[], totals=(0, 0, 0)), warnings=[], error=None)
    mod, _frappe, _queried = _prepare_month(monkeypatch, preview=preview)
    _install_check_sources(monkeypatch, fill_rows=[])

    result = mod.get_finalize_check("2026-07")

    assert result["preview"] is True
    assert result["warnings"] == ["没有可分摊的数据，不能定版。"]


def test_get_finalize_check_on_a_finalized_month_reads_the_submitted_allocation(monkeypatch):
    del calls_for_scope[:]
    mod, frappe, _queried = _prepare_month(
        monkeypatch, submitted="ALLOC-1", foreign={"capitalized": 0, "expensed": 0, "unknown": 1}, has_foreign=True,
        preview=AssertionError("a finalized month must not be previewed"),
    )
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, status="Submitted", capitalized_total=70, expensed_total=30, unknown_total=4,
        lines=[SimpleNamespace(allocated_amount=104)],
    )
    monkeypatch.setattr(mod, "_project_summaries", lambda name: [])
    _install_check_sources(monkeypatch, fill_rows=["full"])

    result = mod.get_finalize_check("2026-07")

    assert result["finalized"] is True
    assert result["preview"] is False
    assert result["unknown_amount"] == 5.0
    assert result["reconcile_diff"] == 0
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# 研发费用汇总页：没有定版的月份用预览顶上（只读）
# ---------------------------------------------------------------------------
def _dashboard_preview_doc(amounts=((60, "capitalized", "RD02"), (40, "expensed", "RD03"))):
    boom = _never_write()
    lines = [
        SimpleNamespace(
            voucher_no="118", expense_item_name="source-a", account_level_3="", account_level_4="",
            project=project, project_stage=stage, allocated_amount=Decimal(str(amount)),
        )
        for amount, stage, project in amounts
    ]
    snapshots = [
        SimpleNamespace(
            voucher_no="118", expense_item="source-a", account_level_1="研发费用", account_level_2="其他相关费用",
            account_level_3="差旅费", account_level_4="住宿费", amount=Decimal("100.00"), direct_project=None,
        ),
    ]
    return SimpleNamespace(
        name=None, lines=lines, expense_snapshots=snapshots,
        insert=boom, submit=boom, save=boom, db_set=boom, cancel=boom,
    )


def _prepare_dashboard(monkeypatch, *, finalized=None, previews=None, imports=(), allocations=()):
    """finalized: 月度 get_value 的返回；previews: {(year, month): preview 对象或异常}；allocations: 年度已提交的分摊单行。"""
    mod, frappe = _load_allocation_entry(monkeypatch)
    queried = []
    built = []
    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "_foreign_dashboard_lines", lambda periods: [])
    frappe.db.get_value = lambda *args, **kwargs: finalized

    def build_preview(period, year, month):
        built.append(period)
        result = (previews or {}).get((year, month))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(mod, "_build_preview", build_preview)

    def get_all(doctype, filters=None, **kwargs):
        queried.append(doctype)
        if doctype == "RD Cost Allocation":
            return list(allocations)
        if doctype == "RD Expense Import":
            return [SimpleNamespace(year=2026, month=month) for month in imports]
        if doctype == "RD Cost Allocation Line":
            return [SimpleNamespace(
                parent="ALLOC-1", voucher_no="118", expense_item_name="source-a", account_level_3="", account_level_4="",
                project="RD02", project_stage="capitalized", allocated_amount=10,
            )] if finalized or allocations else []
        if doctype == "RD Allocation Source Expense":
            return []
        if doctype == "Project":
            return [SimpleNamespace(name=name, project_name=name + " name", rd_project_code=name) for name in ("RD02", "RD03")]
        raise AssertionError(doctype)

    frappe.get_all = get_all
    frappe.get_doc = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("a preview must not load or build documents"))
    frappe.db.commit = _never_write()
    return mod, built, queried


def test_dashboard_month_without_a_finalized_allocation_is_built_from_the_preview(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=_dashboard_preview_doc(), warnings=[], error=None)
    mod, built, queried = _prepare_dashboard(monkeypatch, previews={(2026, 6): preview})

    result = mod.get_allocation_dashboard("2026-06", scope="month", mode="all")

    assert built == ["2026-06"]
    assert result["preview"] is True
    assert result["finalized"] is False
    assert result["allocation_names"] == []
    assert "preview_error" not in result
    assert result["total_amount"] == 100
    assert result["project_count"] == 2
    travel = next(row for row in result["summary_rows"] if row["account_level_3"] == "差旅费" and row["row_type"] == "detail")
    assert travel["account_level_2"] == "其他相关费用"
    assert travel["total"] == 100
    assert travel["projects"] == {"RD02": 60, "RD03": 40}
    assert result["summary_rows"][-1]["row_type"] == "grand_total"
    assert [item["total"] for item in result["stage_summaries"]] == [60, 40, 0]
    # 只读：没有读分摊明细表（数据库里没有这个月的分摊单）。
    assert "RD Cost Allocation Line" not in queried

    filtered = mod.get_allocation_dashboard("2026-06", scope="month", mode="capitalized")
    assert filtered["preview"] is True
    assert filtered["total_amount"] == 60


def test_dashboard_month_preview_failure_is_reported_not_raised(monkeypatch):
    preview = SimpleNamespace(import_name="IMP-1", doc=None, warnings=[], error="本月还没有研发工时，费用没法分摊。请先在「研发工时填报」填工时。")
    mod, built, _queried = _prepare_dashboard(monkeypatch, previews={(2026, 6): preview})

    result = mod.get_allocation_dashboard("2026-06", scope="month")

    assert result["preview"] is False
    assert result["finalized"] is False
    assert result["preview_error"] == preview.error
    assert result["total_amount"] == 0
    assert result["summary_rows"] == []


def test_dashboard_month_without_an_import_is_neither_preview_nor_finalized(monkeypatch):
    mod, built, _queried = _prepare_dashboard(monkeypatch, previews={})

    result = mod.get_allocation_dashboard("2026-06")

    assert built == ["2026-06"]
    assert result["preview"] is False
    assert result["finalized"] is False
    assert "preview_error" not in result
    assert result["total_amount"] == 0


def test_dashboard_finalized_month_never_computes_a_preview(monkeypatch):
    mod, built, queried = _prepare_dashboard(
        monkeypatch, finalized="ALLOC-1", previews={(2026, 6): AssertionError("must not preview a finalized month")},
    )

    result = mod.get_allocation_dashboard("2026-06")

    assert built == []
    assert result["finalized"] is True
    assert result["preview"] is False
    assert result["allocation_names"] == ["ALLOC-1"]
    assert result["total_amount"] == 10
    assert "RD Expense Import" not in queried


def test_dashboard_year_adds_previews_only_for_imported_months_without_a_finalized_allocation(monkeypatch):
    good = SimpleNamespace(import_name="IMP", doc=_dashboard_preview_doc(), warnings=[], error=None)
    other = SimpleNamespace(import_name="IMP", doc=_dashboard_preview_doc(amounts=((5, "unknown", "RD02"),)), warnings=[], error=None)
    broken = SimpleNamespace(import_name="IMP", doc=None, warnings=[], error="本月还没有研发工时，费用没法分摊。请先在「研发工时填报」填工时。")
    mod, built, _queried = _prepare_dashboard(
        monkeypatch,
        allocations=[SimpleNamespace(name="ALLOC-1", year=2026, month=1), SimpleNamespace(name="ALLOC-2", year=2026, month=2)],
        imports=[1, 2, 3, 5, 7],
        previews={(2026, 3): good, (2026, 5): other, (2026, 7): broken},
    )

    result = mod.get_allocation_dashboard("2026-06", scope="year")

    # 1、2 月已定版不再预览；4、6、8–12 月没有费用导入不算；其余按月份顺序现算。
    assert built == ["2026-03", "2026-05", "2026-07"]
    assert result["scope"] == "year"
    assert result["allocation_names"] == ["ALLOC-1", "ALLOC-2"]
    assert result["finalized_months"] == ["2026-01", "2026-02"]
    assert result["preview_months"] == ["2026-03", "2026-05"]
    assert result["has_preview"] is True
    assert result["preview_errors"] == [{"period": "2026-07", "error": broken.error}]
    assert result["total_amount"] == 10 + 100 + 5
    assert "preview" not in result and "finalized" not in result


def test_dashboard_year_without_previews_keeps_the_old_shape_plus_month_lists(monkeypatch):
    mod, built, _queried = _prepare_dashboard(
        monkeypatch, allocations=[SimpleNamespace(name="ALLOC-1", year=2026, month=4)], imports=[4],
    )

    result = mod.get_allocation_dashboard("2026-06", scope="year")

    assert built == []
    assert result["finalized_months"] == ["2026-04"]
    assert result["preview_months"] == []
    assert result["has_preview"] is False
    assert "preview_errors" not in result


def test_dashboard_year_with_nothing_imported_is_empty(monkeypatch):
    mod, built, _queried = _prepare_dashboard(monkeypatch)

    result = mod.get_allocation_dashboard("2026-06", scope="year")

    assert built == []
    assert result["finalized_months"] == []
    assert result["preview_months"] == []
    assert result["has_preview"] is False
    assert result["total_amount"] == 0