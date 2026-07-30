import importlib
import sys
import types
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
    return mod, frappe


def test_cancel_allocation_allows_finance_to_cancel_submitted_allocations(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {"canceled": []}

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

    def get_doc(doctype, name):
        assert doctype == "RD Cost Allocation"
        return AllocationDoc(name)

    frappe.get_all = get_all
    frappe.get_doc = get_doc
    frappe.db.savepoint = lambda name: captured.setdefault("savepoint", name)
    frappe.db.rollback = lambda save_point=None: captured.setdefault("rollback", save_point)
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.cancel_allocation("2026-07")

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
    assert result == {"ok": True, "period": "2026-07", "canceled": ["ALLOC-1", "ALLOC-2"]}


def test_cancel_allocation_returns_empty_when_period_has_no_submitted_allocation(monkeypatch):
    mod, frappe = _load_allocation_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: captured.setdefault("lock_check", args))
    monkeypatch.setattr(mod, "lock_period_import", lambda year, month: captured.setdefault("import_lock", (year, month)))
    frappe.get_all = lambda *args, **kwargs: []
    frappe.get_doc = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no allocation should be loaded"))

    result = mod.cancel_allocation("2026-07")

    assert captured["roles"] == mod.RD_FINANCE_ROLES
    assert captured["lock_check"] == ("2026-07", "lock_allocations", "分摊")
    assert result == {"ok": True, "period": "2026-07", "canceled": []}


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

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: (_ for _ in ()).throw(RuleError("locked")))
    frappe.get_all = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("locked period should stop before query"))

    with pytest.raises(RuleError, match="locked"):
        mod.cancel_allocation("2026-07")


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
