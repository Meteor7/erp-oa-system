import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class RuleError(Exception):
    pass


class DuplicateEntryError(Exception):
    pass


def _install_fake_frappe(monkeypatch):
    frappe = types.ModuleType("frappe")
    frappe.DuplicateEntryError = DuplicateEntryError
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


def _load_foreign_rd_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.allocation_entry", None)
    sys.modules.pop("rayher_hr_payroll.api.foreign_rd_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.foreign_rd_entry")
    return mod, frappe


def _project_info():
    return {
        "RD06": SimpleNamespace(name="RD06", project_name="MUSHI 7546", rd_project_code="RD06", rd_stage="capitalized"),
        "RD15": SimpleNamespace(name="RD15", project_name="DRAKENS 4482", rd_project_code="RD15", rd_stage="expensed"),
    }


def _foreign_row(name, amount, *, direct_project=None, level_2="\u59d4\u6258\u7814\u53d1", level_3="\u5883\u5916", level_4="Sabri\u8d39\u7528"):
    return SimpleNamespace(
        name=name,
        voucher_no=f"V-{name}",
        account_level_1="\u7814\u53d1\u652f\u51fa",
        account_level_2=level_2,
        account_level_3=level_3,
        account_level_4=level_4,
        amount=amount,
        category="other",
        direct_project=direct_project,
        source_row_key=f"KEY-{name}",
    )


def test_foreign_expense_context_splits_import_rows_into_common_and_direct(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [
        _foreign_row("COMMON", 900),
        _foreign_row("DIRECT", 300, direct_project="RD15"),
        _foreign_row("DOMESTIC", 999, level_3="\u5883\u5185"),
    ]

    context = mod._foreign_expense_context_from_rows(rows, _project_info())

    assert context["total_amount"] == 1200.0
    assert context["common_amount"] == 900.0
    assert context["direct_amount"] == 300.0
    assert context["direct_amounts_by_project"] == {"RD15": 300.0}
    assert [row["voucher_no"] for row in context["expense_sources"]] == ["V-COMMON", "V-DIRECT"]
    assert context["expense_sources"][0]["allocation_type"] == "common"
    assert context["expense_sources"][1]["allocation_type"] == "project"
    assert context["expense_sources"][1]["project_code"] == "RD15"
    assert context["expense_sources"][1]["project_name"] == "DRAKENS 4482"


def test_allocate_foreign_rows_uses_hour_ratio_and_project_stage(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "work_date": "2026-06-03", "activity_type": "\u9700\u6c42\u5206\u6790", "hours": 6, "description": "support"},
        {"project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482", "work_date": "2026-06-04", "activity_type": "\u65b9\u6848\u8bbe\u8ba1", "hours": 2, "description": "support"},
    ]

    allocated = mod._allocate_foreign_rows(1000, rows, _project_info())

    assert allocated == [
        {
            "project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546",
            "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316",
            "work_date": "2026-06-03", "activity_type": "\u9700\u6c42\u5206\u6790",
            "hours": 6.0, "ratio": 75.0, "common_allocated_amount": 750.0,
            "direct_allocated_amount": 0.0, "allocated_amount": 750.0, "description": "support",
        },
        {
            "project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482",
            "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316",
            "work_date": "2026-06-04", "activity_type": "\u65b9\u6848\u8bbe\u8ba1",
            "hours": 2.0, "ratio": 25.0, "common_allocated_amount": 250.0,
            "direct_allocated_amount": 0.0, "allocated_amount": 250.0, "description": "support",
        },
    ]


def test_foreign_allocation_combines_common_ratio_and_direct_project_amounts(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "work_date": "2026-06-03", "activity_type": "\u9700\u6c42\u5206\u6790", "hours": 6, "description": "support"},
        {"project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482", "work_date": "2026-06-04", "activity_type": "\u65b9\u6848\u8bbe\u8ba1", "hours": 3, "description": "support"},
    ]

    allocated = mod._allocate_foreign_rows(900, rows, _project_info(), direct_amounts_by_project={"RD15": 300})
    summaries = mod._foreign_project_summaries(allocated, direct_amounts_by_project={"RD15": 300}, project_info=_project_info())

    assert allocated[0]["common_allocated_amount"] == 600.0
    assert allocated[0]["allocated_amount"] == 600.0
    assert allocated[1]["common_allocated_amount"] == 300.0
    assert allocated[1]["direct_allocated_amount"] == 300.0
    assert allocated[1]["allocated_amount"] == 600.0
    assert summaries == [
        {
            "project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546",
            "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316",
            "hours": 6.0, "ratio": 66.67, "common_allocated_amount": 600.0,
            "direct_allocated_amount": 0.0, "allocated_amount": 600.0, "line_count": 1,
        },
        {
            "project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482",
            "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316",
            "hours": 3.0, "ratio": 33.33, "common_allocated_amount": 300.0,
            "direct_allocated_amount": 300.0, "allocated_amount": 600.0, "line_count": 1,
        },
    ]


def test_allocate_foreign_rows_rejects_rows_outside_period_or_over_eight_hours(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)

    with pytest.raises(RuleError):
        mod._allocate_foreign_rows(
            100,
            [{"project": "RD06", "work_date": "2026-07-01", "activity_type": "\u9700\u6c42\u5206\u6790", "hours": 1, "description": "support"}],
            _project_info(),
            year=2026,
            month=6,
        )
    with pytest.raises(RuleError, match="8"):
        mod._allocate_foreign_rows(
            100,
            [{"project": "RD06", "work_date": "2026-06-01", "activity_type": "\u9700\u6c42\u5206\u6790", "hours": 9, "description": "support"}],
            _project_info(),
            year=2026,
            month=6,
        )


def test_combined_project_summaries_add_domestic_and_foreign_totals(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)

    domestic = [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316", "allocated_amount": 100, "basis_hours": 8},
        {"project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482", "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316", "allocated_amount": 40, "basis_hours": 5},
    ]
    foreign = [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316", "allocated_amount": 750, "hours": 30, "ratio": 75},
        {"project": "RD17", "project_code": "RD17", "project_name": "EFEM-12-2LP-EG-A", "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316", "allocated_amount": 250, "hours": 10, "ratio": 25},
    ]

    combined = mod._combined_project_summaries(domestic, foreign)

    assert combined == [
        {
            "project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546",
            "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316",
            "domestic_amount": 100.0, "foreign_amount": 750.0, "total_amount": 850.0,
            "domestic_hours": 8.0, "foreign_hours": 30.0,
        },
        {
            "project": "RD15", "project_code": "RD15", "project_name": "DRAKENS 4482",
            "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316",
            "domestic_amount": 40.0, "foreign_amount": 0.0, "total_amount": 40.0,
            "domestic_hours": 5.0, "foreign_hours": 0.0,
        },
        {
            "project": "RD17", "project_code": "RD17", "project_name": "EFEM-12-2LP-EG-A",
            "project_stage": "expensed", "stage_label": "\u8d39\u7528\u5316",
            "domestic_amount": 0.0, "foreign_amount": 250.0, "total_amount": 250.0,
            "domestic_hours": 0.0, "foreign_hours": 10.0,
        },
    ]


def test_get_foreign_rd_recalculates_from_imported_foreign_expenses(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "_domestic_project_summaries", lambda year, month: [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "project_stage": "capitalized", "stage_label": "\u8d44\u672c\u5316", "allocated_amount": 100, "basis_hours": 8},
    ])
    monkeypatch.setattr(mod, "_foreign_project_info", lambda project_names: _project_info())
    monkeypatch.setattr(mod, "_foreign_expense_context", lambda year, month: {
        "expense_import": "EXP-1",
        "total_amount": 1200.0,
        "common_amount": 900.0,
        "direct_amount": 300.0,
        "direct_amounts_by_project": {"RD15": 300.0},
        "expense_sources": [{"voucher_no": "V-COMMON", "allocation_type": "common"}, {"voucher_no": "V-DIRECT", "allocation_type": "project"}],
    }, raising=False)
    frappe.db.get_value = lambda *args, **kwargs: "FOREIGN-1"

    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name=name, period="2026-06", year=2026, month=6, total_amount=1000, status="Calculated",
        lines=[
            SimpleNamespace(project="RD06", project_code="RD06", project_name="MUSHI 7546", project_stage="capitalized", work_date="2026-06-03", activity_type="\u9700\u6c42\u5206\u6790", hours=6, ratio=0, allocated_amount=0, description="support"),
            SimpleNamespace(project="RD15", project_code="RD15", project_name="DRAKENS 4482", project_stage="expensed", work_date="2026-06-04", activity_type="\u65b9\u6848\u8bbe\u8ba1", hours=3, ratio=0, allocated_amount=0, description="support"),
        ],
    )

    result = mod.get_foreign_rd("2026-06")

    assert captured["roles"] == mod.RD_FOREIGN_FINANCE_ROLES
    assert result["name"] == "FOREIGN-1"
    assert result["expense_import"] == "EXP-1"
    assert result["total_amount"] == 1200.0
    assert result["common_amount"] == 900.0
    assert result["direct_amount"] == 300.0
    assert result["total_hours"] == 9.0
    assert result["expense_sources"][1]["voucher_no"] == "V-DIRECT"
    assert result["lines"][0]["common_allocated_amount"] == 600.0
    assert result["lines"][1]["direct_allocated_amount"] == 300.0
    assert result["foreign_stage_summaries"] == [
        {"stage": "capitalized", "label": "\u8d44\u672c\u5316", "total": 600.0},
        {"stage": "expensed", "label": "\u8d39\u7528\u5316", "total": 600.0},
        {"stage": "unknown", "label": "\u672a\u5224\u5b9a", "total": 0.0},
    ]
    assert result["combined_stage_summaries"][0]["total"] == 700.0
    assert result["combined_project_summaries"][0]["project"] == "RD06"
    assert result["combined_project_summaries"][0]["total_amount"] == 700.0


def test_save_foreign_rd_reports_concurrent_first_save_without_overwrite(monkeypatch):
    mod, frappe = _load_foreign_rd_entry(monkeypatch)
    captured = {"commit": 0, "save": 0}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args: None)
    monkeypatch.setattr(mod, "_foreign_expense_context", lambda year, month: {
        "expense_import": None,
        "total_amount": 0.0,
        "common_amount": 0.0,
        "direct_amount": 0.0,
        "direct_amounts_by_project": {},
        "expense_sources": [],
    })
    monkeypatch.setattr(mod, "_resolve_projects_from_identity", lambda rows: set())
    monkeypatch.setattr(mod, "_foreign_project_info", lambda names: {})
    monkeypatch.setattr(mod, "_allocate_foreign_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, "_foreign_doc_name", lambda year, month: None)

    class NewDocument:
        def set(self, fieldname, value):
            setattr(self, fieldname, value)

        def append(self, fieldname, value):
            raise AssertionError("no rows should be appended")

        def is_new(self):
            return True

        def insert(self, ignore_permissions=False):
            assert ignore_permissions is True
            raise frappe.DuplicateEntryError("FRD-2026-07")

        def save(self, ignore_permissions=False):
            captured["save"] += 1

    frappe.get_doc = lambda payload: NewDocument()
    frappe.db.commit = lambda: captured.__setitem__("commit", captured["commit"] + 1)

    with pytest.raises(RuleError, match="刷新"):
        mod.save_foreign_rd("2026-07", rows=[])

    assert captured == {"commit": 0, "save": 0}


def test_foreign_rd_allows_the_all_project_account_exception(monkeypatch):
    mod, _frappe = _load_foreign_rd_entry(monkeypatch)
    assert "All Project Access" in mod.RD_FOREIGN_FINANCE_ROLES


def test_monthly_foreign_row_calculates_hours_from_occurrence_days(monkeypatch):
    mod, _frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [{
        "foreign_entity": "QIHENG DEMO OVERSEAS",
        "project": "RD06",
        "project_code": "RD06",
        "project_name": "MUSHI 7546",
        "occurrence_days": 2.5,
        "remark": "monthly input",
    }]

    allocated = mod._allocate_foreign_rows(1000, rows, _project_info(), year=2026, month=6)

    assert allocated[0]["foreign_entity"] == "QIHENG DEMO OVERSEAS"
    assert allocated[0]["occurrence_days"] == 2.5
    assert allocated[0]["hours"] == 20.0
    assert allocated[0]["work_date"] == "2026-06-01"
    assert allocated[0]["ratio"] == 100.0
    assert allocated[0]["allocated_amount"] == 1000.0
    assert allocated[0]["description"] == "monthly input"


def test_legacy_daily_rows_are_grouped_for_monthly_entry(monkeypatch):
    mod, _frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "work_date": "2026-06-03", "activity_type": "analysis", "hours": 8, "description": "a"},
        {"project": "RD06", "project_code": "RD06", "project_name": "MUSHI 7546", "work_date": "2026-06-04", "activity_type": "design", "hours": 4, "description": "b"},
    ]

    monthly = mod._monthly_foreign_rows(rows, 2026, 6)

    assert monthly == [{
        "foreign_entity": "QIHENG DEMO OVERSEAS",
        "project": "RD06",
        "project_code": "RD06",
        "project_name": "MUSHI 7546",
        "work_date": "2026-06-01",
        "activity_type": "analysis",
        "occurrence_days": 1.5,
        "hours": 12.0,
        "description": "a\uFF1Bb",
    }]

def test_legacy_daily_row_with_zero_occurrence_days_preserves_hours(monkeypatch):
    mod, _frappe = _load_foreign_rd_entry(monkeypatch)
    rows = [{
        "foreign_entity": "QIHENG DEMO OVERSEAS",
        "project": "RD02",
        "project_code": "RD02",
        "project_name": "ADC",
        "work_date": "2026-06-01",
        "activity_type": "analysis",
        "occurrence_days": 0,
        "hours": 8,
        "description": "legacy daily input",
    }]

    monthly = mod._monthly_foreign_rows(rows, 2026, 6)

    assert monthly[0]["occurrence_days"] == 1.0
    assert monthly[0]["hours"] == 8.0