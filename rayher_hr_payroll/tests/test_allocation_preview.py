"""研发费用分摊预览：只读现算，不写库，calculate() 的提示不弹给用户。"""
import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest


class FakeValidationError(Exception):
    pass


def _load_preview(monkeypatch, *, import_name="IMP-1", message_log=None):
    frappe = types.ModuleType("frappe")
    frappe._ = lambda text: text
    frappe.ValidationError = FakeValidationError
    frappe.local = SimpleNamespace(message_log=message_log if message_log is not None else [])
    frappe.db = SimpleNamespace(
        get_value=lambda doctype, filters, fieldname=None, **kwargs: import_name if doctype == "RD Expense Import" else None,
    )
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.rd_cost.allocation_preview", None)
    return importlib.import_module("rayher_hr_payroll.rd_cost.allocation_preview"), frappe


def _write_forbidden(*args, **kwargs):
    raise AssertionError("a preview must not write")


class FakeAllocation:
    """未入库的分摊单。任何写库操作一碰就报错。"""

    insert = submit = save = db_set = db_insert = cancel = staticmethod(_write_forbidden)

    def __init__(self, values, behaviour):
        self.values = values
        self.behaviour = behaviour
        self.calculated = False
        self.lines = [SimpleNamespace(voucher_no="V1", expense_item_name="差旅费", project="RD06",
                                      project_stage="capitalized", allocated_amount=10,
                                      account_level_3="", account_level_4="")]
        self.expense_snapshots = [SimpleNamespace(voucher_no="V1", expense_item="差旅费", account_level_1="研发费用",
                                                  account_level_2="其他相关费用", account_level_3="差旅费",
                                                  account_level_4="住宿费")]

    def calculate(self):
        self.calculated = True
        self.behaviour(self)


def _install_get_doc(frappe, behaviour, created):
    def get_doc(values):
        doc = FakeAllocation(values, behaviour)
        created.append(doc)
        return doc

    frappe.get_doc = get_doc


def test_build_preview_returns_none_when_the_month_has_no_import(monkeypatch):
    preview, frappe = _load_preview(monkeypatch, import_name=None)
    frappe.get_doc = _write_forbidden

    assert preview.build_preview("2026-07", 2026, 7) is None


def test_build_preview_calculates_an_unsaved_allocation_with_the_finalize_arguments(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []
    _install_get_doc(frappe, lambda doc: None, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.import_name == "IMP-1"
    assert result.error is None
    assert result.warnings == []
    assert result.doc is created[0] and created[0].calculated is True
    assert created[0].values == {
        "doctype": "RD Cost Allocation", "period": "2026-07", "year": 2026, "month": 7,
        "expense_import": "IMP-1", "allocation_basis": "rd_project_hours", "scope": "all",
        "calculation_version": "v1",
    }
    # 定版用的是同一个构造函数
    assert preview.new_allocation_doc("2026-07", 2026, 7, "IMP-1").values == created[0].values


def test_build_preview_captures_calculate_messages_and_restores_the_message_log(monkeypatch):
    earlier = [json.dumps({"message": "earlier request message"})]
    preview, frappe = _load_preview(monkeypatch, message_log=list(earlier))
    created = []

    def behaviour(doc):
        frappe.local.message_log.append(json.dumps({"message": "以下员工本期工时不完整：<b>演示员工129</b>", "title": "提示"}))
        frappe.local.message_log.append("plain text warning")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.warnings == ["以下员工本期工时不完整：演示员工129", "plain text warning"]
    assert frappe.local.message_log == earlier


def test_build_preview_wraps_business_errors_and_drops_their_messages(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []

    def behaviour(doc):
        frappe.local.message_log.append(json.dumps({"message": "throw popup"}))
        raise FakeValidationError("费用导入有问题")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.doc is None
    assert result.error == "费用导入有问题"
    assert result.warnings == ["throw popup"]
    assert frappe.local.message_log == []


def test_build_preview_wraps_value_errors_from_the_labour_conflict_check(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []

    def behaviour(doc):
        raise ValueError("本期同时存在「人工费」类导入费用与工资单")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.doc is None
    assert result.error == "本期同时存在「人工费」类导入费用与工资单"


def test_build_preview_turns_unexpected_failures_into_a_labelled_error(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []

    def behaviour(doc):
        raise KeyError("employee")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.doc is None
    assert result.error.startswith("预览计算失败：KeyError")


def test_preview_report_lines_use_the_database_row_shape_and_fill_accounts_from_the_snapshot(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    doc = SimpleNamespace(
        lines=[
            SimpleNamespace(voucher_no="V1", expense_item_name="住宿费", project="RD06", project_stage="capitalized",
                            allocated_amount=10, account_level_3="", account_level_4=""),
            SimpleNamespace(voucher_no="工资单:E1", expense_item_name="人工费-E1", project="RD06", project_stage="expensed",
                            allocated_amount=5, account_level_3="人工费", account_level_4="E1"),
        ],
        expense_snapshots=[
            SimpleNamespace(voucher_no="V1", expense_item="住宿费", account_level_1="研发费用", account_level_2="其他相关费用",
                            account_level_3="差旅费", account_level_4="住宿费"),
        ],
    )

    rows = preview.preview_report_lines(doc, "2026-07")

    assert rows == [
        {
            "parent": "PREVIEW", "voucher_no": "V1", "expense_item_name": "住宿费",
            "account_level_3": "差旅费", "account_level_4": "住宿费",
            "project": "RD06", "project_stage": "capitalized", "allocated_amount": 10, "period": "2026-07",
        },
        {
            "parent": "PREVIEW", "voucher_no": "工资单:E1", "expense_item_name": "人工费-E1",
            "account_level_3": "人工费", "account_level_4": "E1",
            "project": "RD06", "project_stage": "expensed", "allocated_amount": 5, "period": "2026-07",
        },
    ]


# ---------------------------------------------------------------------------
# 英文错误翻成中文（2026-10）
# ---------------------------------------------------------------------------
NO_HOURS = "本月还没有研发工时，费用没法分摊。请先在「研发工时填报」填工时。"


def test_build_preview_translates_the_no_hours_error(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []

    def behaviour(doc):
        raise ValueError("project_hours total must be greater than zero")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.doc is None
    assert result.error == NO_HOURS


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("project_hours total must be greater than zero", NO_HOURS),
        (
            "direct_project 'RD09' is not present in project_hours; its capitalization stage cannot be determined",
            "费用导入里有直接计入项目「RD09」的费用，但这个项目本月没有研发工时记录，没法判定它是资本化还是费用化。"
            "请先在「研发工时填报」登记该项目的工时，或检查费用导入里的项目。",
        ),
        (
            "allocation totals do not reconcile: allocated 99.99, expected 100.00",
            "分摊结果和费用合计对不上（分摊 99.99，费用 100.00）。请检查费用导入的金额，仍然不行请联系管理员。",
        ),
        (
            "Duplicate GL source row in import: V1|差旅费|100",
            "费用导入单里有重复的总账行（V1|差旅费|100）。请到「研发费用导入」删除重复的行后再试。",
        ),
        ("本期同时存在「人工费」类导入费用与工资单", "本期同时存在「人工费」类导入费用与工资单"),
        ("some other english failure", "预览计算失败：some other english failure"),
        ("", "预览计算失败：未知错误"),
        (None, "预览计算失败：未知错误"),
    ],
)
def test_friendly_error_maps_known_allocator_messages(monkeypatch, raw, expected):
    preview, _frappe = _load_preview(monkeypatch)

    assert preview.friendly_error(raw) == expected


def test_build_preview_translates_frappe_validation_errors_from_duplicate_rows(monkeypatch):
    preview, frappe = _load_preview(monkeypatch)
    created = []

    def behaviour(doc):
        raise FakeValidationError("Duplicate GL source row in import: ABC")

    _install_get_doc(frappe, behaviour, created)

    result = preview.build_preview("2026-07", 2026, 7)

    assert result.error == "费用导入单里有重复的总账行（ABC）。请到「研发费用导入」删除重复的行后再试。"