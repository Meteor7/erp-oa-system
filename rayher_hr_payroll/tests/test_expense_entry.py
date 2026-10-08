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


def test_save_expense_reopens_allocated_import_by_canceling_allocation_and_creating_replacement(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {"canceled": []}

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: [])
    monkeypatch.setattr(mod, "ensure_paths", lambda *args, **kwargs: [])

    def get_value(doctype, filters, fieldname=None, **kwargs):
        if doctype == "RD Expense Import":
            return "EXP-OLD"
        return None

    def get_all(doctype, filters=None, pluck=None, **kwargs):
        if doctype == "RD Cost Allocation":
            assert filters == {"expense_import": "EXP-OLD", "docstatus": 1}
            assert pluck == "name"
            return ["ALLOC-OLD"]
        return []

    class OldImport:
        name = "EXP-OLD"
        docstatus = 1
        status = "Allocated"
        def cancel(self):
            captured["canceled"].append("EXP-OLD")

    class OldAllocation:
        flags = SimpleNamespace()
        def cancel(self):
            captured["canceled"].append("ALLOC-OLD")

    def get_doc(arg, name=None):
        if arg == "RD Expense Import" and name == "EXP-OLD":
            return OldImport()
        if arg == "RD Cost Allocation" and name == "ALLOC-OLD":
            return OldAllocation()
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["new_doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: captured.setdefault("insert", ignore_permissions))
        raise AssertionError((arg, name))

    frappe.db.get_value = get_value
    frappe.db.exists = lambda doctype, name_or_filters=None: True if doctype == "Project" else False
    frappe.get_all = get_all
    frappe.get_doc = get_doc
    frappe.db.commit = lambda: captured.setdefault("committed", True)

    mod.save_expense("2026-07", json.dumps([
        {"voucher_no": "V3", "account_level_3": "?????", "category": "direct_input", "amount": 200, "direct_project": "RD17"},
    ]))

    assert captured["canceled"] == ["ALLOC-OLD", "EXP-OLD"]
    assert captured["new_doc"]["items"][0]["direct_project"] == "RD17"
    assert captured["insert"] is True
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

def test_save_expense_refetches_import_after_allocation_cancel_updates_timestamp(monkeypatch):
    mod, frappe = _load_expense_entry(monkeypatch)
    captured = {"canceled": [], "import_gets": 0}

    class TimestampMismatchError(Exception):
        pass

    monkeypatch.setattr(mod, "require_rd_access", lambda roles: None)
    monkeypatch.setattr(mod, "ensure_not_locked", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "get_expense", lambda period: {"period": period, "ok": True})
    monkeypatch.setattr(mod, "confirmed_new_paths", lambda *args: [])
    monkeypatch.setattr(mod, "ensure_paths", lambda *args, **kwargs: [])

    frappe.db.get_value = lambda doctype, filters, fieldname=None, **kwargs: "EXP-OLD" if doctype == "RD Expense Import" else None
    frappe.db.exists = lambda doctype, name_or_filters=None: True if doctype == "Project" else False
    frappe.db.commit = lambda: captured.setdefault("committed", True)
    frappe.get_all = lambda doctype, filters=None, pluck=None, **kwargs: ["ALLOC-OLD"] if doctype == "RD Cost Allocation" else []
    frappe.TimestampMismatchError = TimestampMismatchError

    class OldImport:
        name = "EXP-OLD"
        docstatus = 1
        status = "Allocated"
        flags = SimpleNamespace()

        def __init__(self, stale):
            self.stale = stale

        def cancel(self):
            if self.stale:
                raise TimestampMismatchError("stale import object")
            captured["canceled"].append("EXP-OLD")

    class OldAllocation:
        flags = SimpleNamespace()

        def cancel(self):
            captured["canceled"].append("ALLOC-OLD")

    def get_doc(arg, name=None):
        if arg == "RD Expense Import" and name == "EXP-OLD":
            captured["import_gets"] += 1
            return OldImport(stale=captured["import_gets"] == 1)
        if arg == "RD Cost Allocation" and name == "ALLOC-OLD":
            return OldAllocation()
        if isinstance(arg, dict) and arg.get("doctype") == "RD Expense Import":
            captured["new_doc"] = arg
            return SimpleNamespace(insert=lambda ignore_permissions=False: captured.setdefault("insert", ignore_permissions))
        raise AssertionError((arg, name))

    frappe.get_doc = get_doc

    mod.save_expense("2026-07", json.dumps([
        {"voucher_no": "V4", "account_level_3": "Cost", "category": "other", "amount": 300},
    ]))

    assert captured["import_gets"] == 2
    assert captured["canceled"] == ["ALLOC-OLD", "EXP-OLD"]
    assert captured["insert"] is True
    assert captured["committed"] is True
