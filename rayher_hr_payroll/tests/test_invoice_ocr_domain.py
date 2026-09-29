import importlib
import json
import sys
import types
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from rayher_hr_payroll.invoice_ocr.domain import (
    amount_difference,
    business_key,
    legacy_business_key,
    same_invoice,
    submission_blockers,
)

APP_ROOT = Path(__file__).resolve().parents[1]
DOCTYPE_ROOT = APP_ROOT / "rayher_hr_payroll" / "doctype"
INVOICE_DOCTYPE_FOLDERS = {
    "OA Invoice Import Batch": "oa_invoice_import_batch",
    "OA Invoice Record": "oa_invoice_record",
    "OA Invoice View Log": "oa_invoice_view_log",
}


def _employee_permission(doctype):
    folder = INVOICE_DOCTYPE_FOLDERS[doctype]
    path = DOCTYPE_ROOT / folder / f"{folder}.json"
    permissions = json.loads(path.read_text(encoding="utf-8"))["permissions"]
    return next(permission for permission in permissions if permission["role"] == "Employee")


class FakeDB:
    def __init__(self, *, employees=None, users=None, requests=None, batches=None, records=None, steps=None):
        self.employees = employees or {}
        self.users = users or {}
        self.requests = requests or {}
        self.batches = batches or {}
        self.records = records or {}
        self.steps = steps or {}
        self.escaped = []

    def escape(self, value):
        self.escaped.append(value)
        return "'" + str(value).replace("'", "''") + "'"

    def get_value(self, doctype, name_or_filters, fieldname=None, as_dict=False):
        if doctype == "Employee":
            if isinstance(name_or_filters, dict):
                row = next(
                    (item for item in self.employees.values() if item.get("user_id") == name_or_filters.get("user_id")),
                    None,
                )
            else:
                row = self.employees.get(name_or_filters)
        elif doctype == "User":
            row = self.users.get(name_or_filters)
        elif doctype == "OA Approval Request":
            row = self.requests.get(name_or_filters)
        elif doctype == "OA Invoice Import Batch":
            row = self.batches.get(name_or_filters)
        elif doctype == "OA Invoice Record":
            row = self.records.get(name_or_filters)
        elif doctype == "OA Approval Step":
            row = self.steps.get((name_or_filters.get("parent"), int(name_or_filters.get("step_index") or 0)))
        else:
            row = None
        if row is None:
            return None
        if as_dict:
            return dict(row)
        if isinstance(fieldname, (list, tuple)):
            return tuple(row.get(field) for field in fieldname)
        return row.get(fieldname)


@pytest.fixture
def permissions_module(monkeypatch):
    roles = {
        "admin@example.com": ["System Manager"],
        "finance@example.com": ["Accounts User"],
        "executive@example.com": ["Rayher Business Executive"],
        "hr@example.com": ["HR User"],
        "hr-manager@example.com": ["HR Manager"],
        "alice@example.com": ["Employee"],
        "uploader@example.com": ["Employee"],
        "manager@example.com": ["Employee", "Department Manager"],
        "sales-manager@example.com": ["Employee", "Department Manager"],
        "approver@example.com": ["Employee"],
        "creator@example.com": ["Employee"],
        "ordinary-rd@example.com": ["Employee"],
        "stranger@example.com": ["Employee"],
        "log-owner@example.com": ["Employee"],
    }
    db = FakeDB(
        employees={
            "EMP-A": {"name": "EMP-A", "user_id": "alice@example.com", "employee_name": "Alice", "department": "研发部"},
            "EMP-U": {"name": "EMP-U", "user_id": "uploader@example.com", "employee_name": "Uploader", "department": "销售部"},
            "EMP-M": {"name": "EMP-M", "user_id": "manager@example.com", "employee_name": "Manager", "department": "研发部"},
            "EMP-S": {"name": "EMP-S", "user_id": "sales-manager@example.com", "employee_name": "Sales Manager", "department": "销售部"},
            "EMP-C": {"name": "EMP-C", "user_id": "approver@example.com", "employee_name": "Current Approver", "department": "销售部"},
            "EMP-O": {"name": "EMP-O", "user_id": "creator@example.com", "employee_name": "Request Creator", "department": "市场部"},
            "EMP-R": {"name": "EMP-R", "user_id": "ordinary-rd@example.com", "employee_name": "Ordinary RD", "department": "研发部"},
            "EMP-X": {"name": "EMP-X", "user_id": "stranger@example.com", "employee_name": "Stranger", "department": "法务部"},
            "EMP-L": {"name": "EMP-L", "user_id": "log-owner@example.com", "employee_name": "Log Owner", "department": "法务部"},
        },
        users={
            "approver@example.com": {"full_name": "Approver User"},
        },
        requests={
            "REQ-1": {"name": "REQ-1", "owner": "creator@example.com", "employee": "EMP-A", "department": "研发部", "current_step_index": 1, "workflow_status": "待审批"},
        },
        batches={
            "BATCH-1": {"name": "BATCH-1", "doctype": "OA Invoice Import Batch", "owner": "uploader@example.com", "request": "REQ-1"},
            "BATCH-UNLINKED": {"name": "BATCH-UNLINKED", "doctype": "OA Invoice Import Batch", "owner": "uploader@example.com", "request": ""},
        },
        records={
            "INV-1": {"name": "INV-1", "doctype": "OA Invoice Record", "owner": "uploader@example.com", "request": "REQ-1", "batch": "BATCH-1"},
            "INV-BATCH-LINKED": {"name": "INV-BATCH-LINKED", "doctype": "OA Invoice Record", "owner": "stranger@example.com", "request": "", "batch": "BATCH-1"},
            "INV-UNLINKED": {"name": "INV-UNLINKED", "doctype": "OA Invoice Record", "owner": "uploader@example.com", "request": "", "batch": "BATCH-UNLINKED"},
        },
        steps={
            ("REQ-1", 1): {"approvers": json.dumps(["approver@example.com"], ensure_ascii=False)},
        },
    )
    frappe = types.ModuleType("frappe")
    frappe.db = db
    frappe.session = types.SimpleNamespace(user="stranger@example.com")
    frappe.get_roles = lambda user=None: roles.get(user, [])
    monkeypatch.setitem(sys.modules, "frappe", frappe)
    sys.modules.pop("rayher_hr_payroll.invoice_ocr.permissions", None)
    module = importlib.import_module("rayher_hr_payroll.invoice_ocr.permissions")
    return module, frappe


def _frappe_role_allows_read(permission, *, doc_owner, user):
    """Model only Frappe's DocPerm gate, not an invoice authorization rule."""
    if not permission.get("read"):
        return False
    return not permission.get("if_owner") or doc_owner == user


def _frappe_direct_read(permission, *, doc_owner, user, controller_result):
    """Frappe controllers can veto a DocPerm grant but cannot create one."""
    return _frappe_role_allows_read(permission, doc_owner=doc_owner, user=user) and controller_result is not False


def _frappe_query_parts(permission, *, table, user, hook_condition):
    """Frappe ANDs an if-owner match condition with permission-query hooks."""
    conditions = []
    if permission.get("read") and permission.get("if_owner"):
        conditions.append(f"`tab{table}`.`owner` = '{user}'")
    if hook_condition:
        conditions.append(hook_condition)
    return conditions


@pytest.mark.parametrize("doctype", INVOICE_DOCTYPE_FOLDERS)
def test_employee_metadata_provides_base_read_for_row_level_hooks(doctype):
    assert _employee_permission(doctype) == {"role": "Employee", "permlevel": 0, "read": 1}


def test_if_owner_docperm_would_block_a_nonowner_before_hooks_can_authorize(permissions_module):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-1"]
    user = "alice@example.com"
    legacy_if_owner = {"role": "Employee", "permlevel": 0, "read": 1, "if_owner": 1}
    controller_result = permissions.invoice_record_has_permission(record, "read", user)
    query_condition = permissions.invoice_record_query(user)

    assert controller_result is True
    assert _frappe_role_allows_read(legacy_if_owner, doc_owner=record["owner"], user=user) is False
    assert _frappe_direct_read(
        legacy_if_owner, doc_owner=record["owner"], user=user, controller_result=controller_result
    ) is False
    assert _frappe_query_parts(
        legacy_if_owner, table="OA Invoice Record", user=user, hook_condition=query_condition
    ) == ["`tabOA Invoice Record`.`owner` = 'alice@example.com'", query_condition]


@pytest.mark.parametrize(
    "user, query_evidence",
    [
        ("uploader@example.com", "`tabOA Invoice Record`.owner = 'uploader@example.com'"),
        ("alice@example.com", "req.employee = 'EMP-A'"),
        ("creator@example.com", "req.owner = 'creator@example.com'"),
        ("approver@example.com", "JSON_QUOTE('approver@example.com')"),
    ],
)
def test_employee_record_relationships_survive_frappe_direct_and_query_composition(
    permissions_module, user, query_evidence
):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-1"]
    permission = _employee_permission("OA Invoice Record")

    assert frappe.get_roles(user) == ["Employee"]
    assert _frappe_role_allows_read(permission, doc_owner=record["owner"], user=user) is True
    if user != "uploader@example.com":
        assert record["owner"] != user
    controller_result = permissions.invoice_record_has_permission(record, "read", user)
    assert controller_result is True
    assert _frappe_direct_read(
        permission, doc_owner=record["owner"], user=user, controller_result=controller_result
    ) is True

    query_condition = permissions.invoice_record_query(user)
    assert _frappe_query_parts(
        permission, table="OA Invoice Record", user=user, hook_condition=query_condition
    ) == [query_condition]
    assert query_evidence in query_condition


def test_view_log_nonowner_with_source_access_survives_both_frappe_gates(permissions_module):
    permissions, frappe = permissions_module
    user = "alice@example.com"
    log = {
        "doctype": "OA Invoice View Log",
        "owner": "log-owner@example.com",
        "invoice_record": "INV-1",
        "request": "REQ-1",
    }
    permission = _employee_permission("OA Invoice View Log")

    assert _frappe_role_allows_read(permission, doc_owner=log["owner"], user=user) is True
    controller_result = permissions.invoice_view_log_has_permission(log, "read", user)
    assert controller_result is True
    assert _frappe_direct_read(permission, doc_owner=log["owner"], user=user, controller_result=controller_result) is True

    query_condition = permissions.invoice_view_log_query(user)
    assert _frappe_query_parts(
        permission, table="OA Invoice View Log", user=user, hook_condition=query_condition
    ) == [query_condition]
    assert "`tabOA Invoice View Log`.owner" not in query_condition
    assert "source.owner = 'alice@example.com'" in query_condition
    assert "req.employee = 'EMP-A'" in query_condition

    log_owner = "log-owner@example.com"
    assert _frappe_role_allows_read(permission, doc_owner=log["owner"], user=log_owner) is True
    owner_controller_result = permissions.invoice_view_log_has_permission(log, "read", log_owner)
    assert owner_controller_result is False
    assert _frappe_direct_read(
        permission, doc_owner=log["owner"], user=log_owner, controller_result=owner_controller_result
    ) is False

    owner_query_condition = permissions.invoice_view_log_query(log_owner)
    assert _frappe_query_parts(
        permission, table="OA Invoice View Log", user=log_owner, hook_condition=owner_query_condition
    ) == [owner_query_condition]
    assert "`tabOA Invoice View Log`.owner" not in owner_query_condition


def test_unrelated_employee_is_rejected_by_hooks_after_base_read(permissions_module):
    permissions, frappe = permissions_module
    user = "stranger@example.com"
    record = frappe.db.records["INV-1"]
    permission = _employee_permission("OA Invoice Record")

    assert _frappe_role_allows_read(permission, doc_owner=record["owner"], user=user) is True
    controller_result = permissions.invoice_record_has_permission(record, "read", user)
    assert controller_result is False
    assert _frappe_direct_read(
        permission, doc_owner=record["owner"], user=user, controller_result=controller_result
    ) is False

    query_condition = permissions.invoice_record_query(user)
    assert _frappe_query_parts(
        permission, table="OA Invoice Record", user=user, hook_condition=query_condition
    ) == [query_condition]
    assert "`tabOA Invoice Record`.owner = 'stranger@example.com'" in query_condition
    assert "req.owner = 'stranger@example.com'" in query_condition
    assert "req.employee = 'EMP-X'" in query_condition


@pytest.mark.parametrize(
    "number, issue_date, amount, expected",
    [
        ("2632200005753891281", "2026-07-14", "35.98", "2632200005753891281|2026-07-14|35.98"),
        (" 000123 ", date(2026, 7, 14), Decimal("35.980"), "000123|2026-07-14|35.98"),
        ("000123", datetime(2026, 7, 14, 9, 30), 35.98, "000123|2026-07-14|35.98"),
    ],
)
def test_legacy_business_key_keeps_the_old_format(number, issue_date, amount, expected):
    # 只用来识别 2026-09-28 之前财务已解除的疑似重复。
    assert legacy_business_key(number, issue_date, amount) == expected


@pytest.mark.parametrize(
    "number, code, expected",
    [
        ("26322000057538912810", "", "26322000057538912810"),
        ("26322000057538912810", "044001900111", "26322000057538912810"),
        (" 000123 ", "044001900111", "044001900111-000123"),
        ("\uff10\uff10\uff10\uff11\uff12\uff13", None, "000123"),
        ("ab 12", None, "AB12"),
    ],
)
def test_business_key_is_the_invoice_number(number, code, expected):
    # 决定（2026-09-24）：全电发票只看号码，老版发票看代码+号码；日期、金额不参与。
    assert business_key(number, code) == expected


@pytest.mark.parametrize("number", ["", "   ", None])
def test_business_key_needs_an_invoice_number(number):
    assert business_key(number, "044001900111") is None


def test_same_invoice_compares_codes_only_when_both_are_known():
    assert same_invoice("000123", "A1", "000123", "a1")
    assert not same_invoice("000123", "A1", "000123", "B2")
    assert same_invoice("000123", "", "000123", "B2")
    assert same_invoice("26322000057538912810", "A1", "26322000057538912810", "B2")
    assert not same_invoice("000123", "", "000124", "")
    assert not same_invoice("", "", "", "")


@pytest.mark.parametrize(
    "number, issue_date, amount",
    [
        ("", "2026-07-14", "35.98"),
        ("2632", "", "35.98"),
        ("2632", "2026-07-14", ""),
        ("2632", "2026/07/14", "35.98"),
        ("2632", "2026-02-30", "35.98"),
        ("2632", "2026-07-14", "not-money"),
        ("2632", "2026-07-14", "NaN"),
        ("2632", "2026-07-14", "Infinity"),
    ],
)
def test_legacy_business_key_returns_none_for_missing_or_invalid_parts(number, issue_date, amount):
    assert legacy_business_key(number, issue_date, amount) is None


def test_amount_difference_uses_two_cent_tolerance_and_signed_decimal():
    assert amount_difference("35.62", "0.36", "35.98") is None
    assert amount_difference("10.00", "0.00", "10.02") is None
    assert amount_difference("10.00", "0.00", "10.03") == Decimal("0.03")
    assert amount_difference("10.00", "1.00", "10.97") == Decimal("-0.03")


def test_amount_difference_converts_float_through_text_not_binary_float_math():
    assert amount_difference(0.1, 0.2, 0.3) is None
    assert amount_difference(0.1, 0.2, 0.33) == Decimal("0.03")


@pytest.mark.parametrize(
    "before_tax, tax, total",
    [
        (None, "1", "2"),
        ("1", "", "2"),
        ("1", "1", None),
        ("bad", "1", "2"),
        ("1", "NaN", "2"),
        ("1", "1", "Infinity"),
    ],
)
def test_amount_difference_returns_none_for_missing_or_invalid_values(before_tax, tax, total):
    assert amount_difference(before_tax, tax, total) is None


def test_submission_requires_invoice_or_nonempty_no_invoice_reason():
    assert submission_blockers([], "") == ["未上传发票，请填写无票原因"]
    assert submission_blockers([], "  业务无发票  ") == []


def test_submission_blockers_cover_all_unresolved_states_with_stable_deduplication():
    records = [
        {"recognition_status": "排队中"},
        {"recognition_status": "识别中"},
        {"recognition_status": "待确认"},
        {"recognition_status": "待确认"},
        {"recognition_status": "疑似重复"},
        {"recognition_status": "失败"},
        {"recognition_status": "未来状态"},
        {"recognition_status": "已确认"},
        {"recognition_status": "已排除"},
    ]
    assert submission_blockers(records, "不能绕过") == [
        "发票正在处理中",
        "存在未确认发票",
        "存在疑似重复发票",
        "存在识别失败发票",
        "存在状态异常发票",
    ]

@pytest.mark.parametrize("role_user", ["admin@example.com", "finance@example.com", "executive@example.com"])
def test_high_privilege_roles_can_read_invoice_records(permissions_module, role_user):
    permissions, frappe = permissions_module
    assert permissions.can_read_invoice(frappe.db.records["INV-1"], role_user) is True


def test_guest_is_always_denied(permissions_module):
    permissions, frappe = permissions_module
    assert permissions.can_read_invoice(frappe.db.records["INV-1"], "Guest") is False
    assert permissions.invoice_record_query("Guest") == "1=0"


def test_record_owner_request_applicant_and_current_approver_can_read(permissions_module):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-1"]
    for user in ("uploader@example.com", "alice@example.com", "approver@example.com"):
        assert permissions.can_read_invoice(record, user) is True, user
    assert permissions.can_read_invoice(record, "ordinary-rd@example.com") is False
    assert permissions.can_read_invoice(record, "sales-manager@example.com") is False
    assert permissions.can_read_invoice(record, "stranger@example.com") is False


def test_batch_inherits_request_scope_and_unlinked_documents_stay_owner_only(permissions_module):
    permissions, frappe = permissions_module
    linked = frappe.db.batches["BATCH-1"]
    assert permissions.can_read_invoice(linked, "uploader@example.com") is True
    assert permissions.can_read_invoice(linked, "alice@example.com") is True
    assert permissions.can_read_invoice(linked, "manager@example.com") is False
    unlinked_batch = frappe.db.batches["BATCH-UNLINKED"]
    unlinked_record = frappe.db.records["INV-UNLINKED"]
    assert permissions.can_read_invoice(unlinked_batch, "uploader@example.com") is True
    assert permissions.can_read_invoice(unlinked_record, "uploader@example.com") is True
    assert permissions.can_read_invoice(unlinked_batch, "alice@example.com") is False
    assert permissions.can_read_invoice(unlinked_record, "alice@example.com") is False


def test_record_uses_batch_request_when_direct_request_is_not_yet_copied(permissions_module):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-BATCH-LINKED"]
    assert permissions.can_read_invoice(record, "alice@example.com") is True
    assert permissions.can_read_invoice(record, "manager@example.com") is False
    assert permissions.can_read_invoice(record, "sales-manager@example.com") is False


def test_view_log_follows_source_record_and_never_its_own_owner(permissions_module):
    permissions, _ = permissions_module
    log = {
        "doctype": "OA Invoice View Log",
        "owner": "log-owner@example.com",
        "invoice_record": "INV-1",
        "request": "REQ-1",
    }
    assert permissions.can_read_invoice(log, "log-owner@example.com") is False
    assert permissions.can_read_invoice(log, "uploader@example.com") is True
    assert permissions.can_read_invoice(log, "alice@example.com") is True
    assert permissions.can_read_invoice({"doctype": "OA Invoice View Log", "owner": "log-owner@example.com"}, "admin@example.com") is False
    assert "EXISTS (SELECT 1 FROM `tabOA Invoice Record` source" in permissions.invoice_view_log_query("admin@example.com")


def test_has_permission_matches_read_and_defers_nonread_to_doctype_permissions(permissions_module):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-1"]
    assert permissions.invoice_record_has_permission(record, "read", "alice@example.com") is True
    assert permissions.invoice_record_has_permission(record, "read", "stranger@example.com") is False
    assert permissions.invoice_record_has_permission(record, "write", "stranger@example.com") is None
    assert permissions.invoice_record_has_permission(record, "create", "stranger@example.com") is None
    assert permissions.invoice_record_has_permission(record, "delete", "stranger@example.com") is None


def test_business_executive_has_business_wide_invoice_read(permissions_module):
    permissions, _frappe = permissions_module

    assert permissions.invoice_record_query("executive@example.com") == ""
    assert permissions.invoice_batch_query("executive@example.com") == ""
    assert permissions.invoice_view_log_query("executive@example.com") == permissions.invoice_view_log_query("admin@example.com")


def test_query_conditions_are_role_aware_and_escape_every_dynamic_identity(permissions_module):
    permissions, frappe = permissions_module
    assert permissions.invoice_record_query("finance@example.com") == ""
    sql = permissions.invoice_record_query("alice@example.com")
    assert "`tabOA Invoice Record`.owner" in sql
    assert "`tabOA Approval Request`" in sql
    assert "`tabOA Approval Step`" in sql
    assert "JSON_CONTAINS" in sql
    assert "req.employee = 'EMP-A'" in sql
    assert "req.department = '研发部'" not in sql
    manager_sql = permissions.invoice_record_query("manager@example.com")
    assert "req.department = '研发部'" not in manager_sql
    assert {"alice@example.com", "EMP-A"}.issubset(set(frappe.db.escaped))
    assert "Alice" not in frappe.db.escaped


def test_query_condition_escapes_quote_in_user_and_does_not_emit_log_owner_clause(permissions_module):
    permissions, frappe = permissions_module
    malicious = "bad' OR 1=1 --"
    sql = permissions.invoice_record_query(malicious)
    assert "owner = 'bad'' OR 1=1 --'" in sql
    assert malicious in frappe.db.escaped
    log_sql = permissions.invoice_view_log_query("alice@example.com")
    assert "`tabOA Invoice View Log`.owner" not in log_sql
    assert "source.owner = 'alice@example.com'" in log_sql


def test_hooks_register_query_and_direct_permission_for_all_invoice_doctypes():
    import rayher_hr_payroll.hooks as hooks

    expected_query = {
        "OA Invoice Import Batch": "rayher_hr_payroll.invoice_ocr.permissions.invoice_batch_query",
        "OA Invoice Record": "rayher_hr_payroll.invoice_ocr.permissions.invoice_record_query",
        "OA Invoice View Log": "rayher_hr_payroll.invoice_ocr.permissions.invoice_view_log_query",
    }
    expected_direct = {
        "OA Invoice Import Batch": "rayher_hr_payroll.invoice_ocr.permissions.invoice_batch_has_permission",
        "OA Invoice Record": "rayher_hr_payroll.invoice_ocr.permissions.invoice_record_has_permission",
        "OA Invoice View Log": "rayher_hr_payroll.invoice_ocr.permissions.invoice_view_log_has_permission",
    }
    for doctype, path in expected_query.items():
        assert hooks.permission_query_conditions.get(doctype) == path
    for doctype, path in expected_direct.items():
        assert hooks.has_permission.get(doctype) == path


def test_restricted_gate_blocks_invoice_query_and_read(permissions_module, monkeypatch):
    permissions, frappe = permissions_module
    monkeypatch.setattr(
        permissions,
        "can_access_request_type",
        lambda request_type, user=None: user == "Administrator",
    )
    record = frappe.db.records["INV-1"]
    assert permissions.invoice_record_query("employee@example.com") == "1=0"
    assert permissions.can_read_invoice(record, "employee@example.com") is False
    assert permissions.invoice_record_query("Administrator") == ""

@pytest.mark.parametrize("user", ["hr@example.com", "hr-manager@example.com", "manager@example.com"])
def test_unassigned_role_does_not_grant_invoice_access(permissions_module, user):
    permissions, frappe = permissions_module
    assert not permissions.can_read_invoice(frappe.db.records["INV-1"], user)
    assert permissions.invoice_record_query(user)

@pytest.mark.parametrize("status", ["草稿", "已撤回", "已完成"])
def test_inactive_node_does_not_grant_invoice_access(permissions_module, status):
    permissions, frappe = permissions_module
    frappe.db.requests["REQ-1"]["workflow_status"] = status
    assert not permissions.can_read_invoice(frappe.db.records["INV-1"], "approver@example.com")
    assert permissions.can_read_invoice(frappe.db.records["INV-1"], "alice@example.com")


def test_spoofed_names_do_not_grant_invoice_or_view_log_access(permissions_module):
    permissions, frappe = permissions_module
    frappe.db.users["ordinary-rd@example.com"] = {"full_name": "approver@example.com"}
    frappe.db.employees["EMP-R"]["employee_name"] = "approver@example.com"
    assert permissions._identity("ordinary-rd@example.com")["actors"] == {"ordinary-rd@example.com"}
    assert not permissions.can_read_invoice(frappe.db.records["INV-1"], "ordinary-rd@example.com")
    assert not permissions.can_read_invoice({"doctype": "OA Invoice View Log", "invoice_record": "INV-1"}, "ordinary-rd@example.com")
    assert "approver@example.com" not in permissions.invoice_record_query("ordinary-rd@example.com")
