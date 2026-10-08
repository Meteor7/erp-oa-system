import importlib
import json
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


def _load_expense_entry(monkeypatch):
    frappe = _install_fake_frappe(monkeypatch)
    sys.modules.pop("rayher_hr_payroll.api._guards", None)
    sys.modules.pop("rayher_hr_payroll.api.expense_entry", None)
    mod = importlib.import_module("rayher_hr_payroll.api.expense_entry")
    return mod, frappe


def test_save_expense_persists_direct_project_and_allows_same_amount_for_different_projects(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: captured.setdefault("roles", roles))
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: [])
    monkeypatch.setattr(mod, "ensure_paths", lambda *args, **kwargs: [])

    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype == "RD Expense Import":
            return None
        return None

    def exists(doctype, name_or_filters=None):
        if doctype == "Project":
            return name_or_filters in {"RD17", "RD16"}
        return False

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["doc"] = arg
            return SimpleNamespace(
                insert=lambda ignore_permissions=False: captured.setdefault("insert", ignore_permissions),
                save=lambda ignore_permissions=False: captured.setdefault("save", ignore_permissions),
            )
        raise AssertionError(arg)

    frappe.db.get_value = get_value
    frappe.db.exists = exists
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    result = mod.save_expense("2026-07", json.dumps([
        {"voucher_no": "V1", "account_level_3": "?????", "category": "depreciation", "amount": 100, "direct_project": "RD17"},
        {"voucher_no": "V1", "account_level_3": "?????", "category": "depreciation", "amount": 100, "direct_project": "RD16"},
        {"voucher_no": "V2", "account_level_3": "????", "category": "direct_input", "amount": 50, "direct_project": ""},
    ]))

    assert result == {"period": "2026-07", "ok": True}
    rows = captured["doc"]["items"]
    assert [row["direct_project"] for row in rows] == ["RD17", "RD16", None]
    assert rows[0]["source_row_key"] != rows[1]["source_row_key"]
    assert captured["insert"] is True
    assert captured["committed"] is True


def test_expense_rows_accept_negative_amounts(monkeypatch):
    mod, _frappe = _load_expense_entry(monkeypatch)

    rows = mod._expense_rows([
        {
            "voucher_no": "CREDIT-1",
            "account_level_1": "\u7814\u53d1\u652f\u51fa",
            "account_level_2": "\u5176\u4ed6\u76f8\u5173\u8d39\u7528",
            "account_level_3": "\u5dee\u65c5\u8d39",
            "amount": -125.50,
            "allocation_type": "common",
        }
    ])

    assert rows[0]["amount"] == -125.50


def test_expense_rows_allow_identical_rows_with_their_own_keys(monkeypatch):
    # 同一个项目一张凭证里买同一样东西几次：完全相同的行也能保存，各自有不同的行键。
    mod, _frappe = _load_expense_entry(monkeypatch)
    row = {
        "voucher_no": "V-1",
        "account_level_1": "研发支出",
        "account_level_2": "直接投入费用",
        "account_level_3": "研发材料",
        "amount": 100,
        "allocation_type": "common",
    }

    rows = mod._expense_rows([dict(row), dict(row)])

    assert len(rows) == 2
    assert rows[0]["source_row_key"] != rows[1]["source_row_key"]


def test_save_expense_persists_four_level_accounts_and_derives_category(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: [])
    monkeypatch.setattr(mod, "ensure_paths", lambda *args, **kwargs: [])
    frappe.db.get_value = lambda doctype, filters, fieldname=None, **kwargs: None
    frappe.db.exists = lambda doctype, name_or_filters=None: True if doctype == "Project" else False
    frappe.db.commit = lambda: None

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: None)
        raise AssertionError(arg)

    frappe.get_doc = get_doc

    mod.save_expense("2026-07", json.dumps([
        {
            "voucher_no": "V5",
            "account_level_1": "研发支出",
            "account_level_2": "人员人工费用",
            "account_level_3": "社会保险费用（单位）",
            "account_level_4": "养老保险",
            "amount": 100,
            "direct_project": "RD16",
        }
    ]))

    row = captured["doc"]["items"][0]
    assert row["account_level_1"] == "研发支出"
    assert row["account_level_2"] == "人员人工费用"
    assert row["account_level_3"] == "社会保险费用（单位）"
    assert row["account_level_4"] == "养老保险"
    assert row["category"] == "personnel"



def test_save_expense_persists_sabri_overseas_commissioned_research_account(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: [])
    monkeypatch.setattr(mod, "ensure_paths", lambda *args, **kwargs: [])
    frappe.db.get_value = lambda doctype, filters, fieldname=None, **kwargs: None
    frappe.db.exists = lambda doctype, name_or_filters=None: False
    frappe.db.commit = lambda: None

    def get_doc(arg, name=None):
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: None)
        raise AssertionError(arg)

    frappe.get_doc = get_doc

    mod.save_expense("2026-07", json.dumps([
        {
            "voucher_no": "V-SABRI",
            "account_level_1": "研发支出",
            "account_level_2": "委托研发",
            "account_level_3": "境外",
            "account_level_4": "Sabri费用",
            "amount": 100,
            "allocation_type": "common",
        }
    ]))

    row = captured["doc"]["items"][0]
    assert row["account_level_1"] == "研发支出"
    assert row["account_level_2"] == "委托研发"
    assert row["account_level_3"] == "境外"
    assert row["account_level_4"] == "Sabri费用"
    assert row["category"] == "other"


FINALIZED_MESSAGE = "本月分摊已定版，费用不能修改。请财务主管先撤销定版。"


def _prepare_save(monkeypatch, *, import_status, allocation_exists):
    """save_expense 的公共替身：期间有一张导入单 EXP-OLD，状态和是否已有已提交分摊单由参数决定。"""
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {"canceled": [], "get_doc": [], "ensure_paths": []}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: ["NEW-PATH"])
    monkeypatch.setattr(mod, "ensure_paths", lambda paths, **kwargs: captured["ensure_paths"].append(paths))

    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype != "RD Expense Import":
            return None
        return import_status if fieldname == "status" else "EXP-OLD"

    def exists(doctype, name_or_filters=None):
        if doctype == "RD Cost Allocation":
            return allocation_exists
        return doctype == "Project"

    class OldImport:
        name = "EXP-OLD"
        docstatus = 1 if import_status != "Draft" else 0
        status = import_status
        flags = SimpleNamespace()

        def __init__(self):
            self.items_set = None

        def cancel(self):
            captured["canceled"].append("EXP-OLD")

        def set(self, fieldname, value):
            self.items_set = (fieldname, value)
            captured["draft_items"] = value

        def save(self, ignore_permissions=False):
            captured["draft_saved"] = ignore_permissions

    def get_doc(arg, name=None):
        captured["get_doc"].append((arg, name))
        if arg == "RD Expense Import" and name == "EXP-OLD":
            return OldImport()
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["new_doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: captured.setdefault("insert", ignore_permissions))
        raise AssertionError((arg, name))

    def get_all(*args, **kwargs):
        raise AssertionError("save_expense must not look up or cancel allocations any more")

    frappe.db.get_value = get_value
    frappe.db.exists = exists
    frappe.get_all = get_all
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)
    return mod, captured


def _save_one_row(mod):
    return mod.save_expense("2026-07", json.dumps([
        {"voucher_no": "V3", "account_level_3": "Cost", "category": "direct_input", "amount": 200, "direct_project": "RD17"},
    ]))


def test_save_expense_refuses_when_month_has_a_submitted_allocation(monkeypatch):
    mod, captured = _prepare_save(monkeypatch, import_status="Imported", allocation_exists=True)

    with pytest.raises(RuleError, match=FINALIZED_MESSAGE):
        _save_one_row(mod)

    # 被拒绝时什么都不动：不建新科目、不取消导入单或分摊单、不新建导入单、不提交。
    assert captured["ensure_paths"] == []
    assert captured["get_doc"] == []
    assert captured["canceled"] == []
    assert "committed" not in captured


def test_save_expense_refuses_when_import_is_marked_allocated(monkeypatch):
    # 加锁后当前读：导入单已被并发定版标成 Allocated，即使快照里还看不到分摊单。
    mod, captured = _prepare_save(monkeypatch, import_status="Allocated", allocation_exists=False)

    with pytest.raises(RuleError, match=FINALIZED_MESSAGE):
        _save_one_row(mod)

    assert captured["get_doc"] == []
    assert "committed" not in captured


def test_save_expense_still_replaces_a_submitted_import_that_is_not_allocated(monkeypatch):
    mod, captured = _prepare_save(monkeypatch, import_status="Imported", allocation_exists=False)

    _save_one_row(mod)

    assert captured["canceled"] == ["EXP-OLD"]
    assert captured["new_doc"]["items"][0]["direct_project"] == "RD17"
    assert captured["insert"] is True
    assert captured["committed"] is True
    assert captured["ensure_paths"] == [["NEW-PATH"]]


def test_save_expense_keeps_editing_a_draft_import_in_place(monkeypatch):
    mod, captured = _prepare_save(monkeypatch, import_status="Draft", allocation_exists=False)

    _save_one_row(mod)

    assert captured["canceled"] == []
    assert captured["draft_items"][0]["voucher_no"] == "V3"
    assert captured["draft_saved"] is True
    assert "new_doc" not in captured
    assert captured["committed"] is True


def test_get_expense_returns_direct_project_and_allocation_type(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    frappe.db.get_value = lambda *args, **kwargs: "EXP-1"
    frappe.get_doc = lambda doctype, name: SimpleNamespace(
        name="EXP-1",
        status="Draft",
        items=[
            SimpleNamespace(voucher_no="V1", account_level_3="???", category="direct_input", amount=100, direct_project="RD17"),
            SimpleNamespace(voucher_no="V2", account_level_3="???", category="other", amount=50, direct_project=None),
        ],
    )

    data = mod.get_expense("2026-07")

    assert data["items"][0]["direct_project"] == "RD17"
    assert data["items"][0]["allocation_type"] == "project"
    assert data["items"][1]["direct_project"] is None
    assert data["items"][1]["allocation_type"] == "common"
