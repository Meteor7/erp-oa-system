import importlib
import json
import sys
import types
from datetime import date, datetime
from decimal import Decimal

import pytest

from rayher_hr_payroll.invoice_ocr.domain import (
    amount_difference,
    business_key,
    submission_blockers,
)


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
        "hr@example.com": ["HR User"],
        "hr-manager@example.com": ["HR Manager"],
        "alice@example.com": ["Employee"],
        "uploader@example.com": ["Employee"],
        "manager@example.com": ["Employee", "Department Manager"],
        "sales-manager@example.com": ["Employee", "Department Manager"],
        "approver@example.com": ["Employee", "Department Manager"],
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
            "EMP-R": {"name": "EMP-R", "user_id": "ordinary-rd@example.com", "employee_name": "Ordinary RD", "department": "研发部"},
            "EMP-X": {"name": "EMP-X", "user_id": "stranger@example.com", "employee_name": "Stranger", "department": "法务部"},
            "EMP-L": {"name": "EMP-L", "user_id": "log-owner@example.com", "employee_name": "Log Owner", "department": "法务部"},
        },
        users={
            "approver@example.com": {"full_name": "Approver User"},
        },
        requests={
            "REQ-1": {"name": "REQ-1", "owner": "creator@example.com", "employee": "EMP-A", "department": "研发部", "current_step_index": 1},
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
            ("REQ-1", 1): {"approvers": json.dumps(["Current Approver"], ensure_ascii=False)},
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


@pytest.mark.parametrize(
    "number, issue_date, amount, expected",
    [
        ("2632200005753891281", "2026-07-14", "35.98", "2632200005753891281|2026-07-14|35.98"),
        (" 000123 ", date(2026, 7, 14), Decimal("35.980"), "000123|2026-07-14|35.98"),
        ("000123", datetime(2026, 7, 14, 9, 30), 35.98, "000123|2026-07-14|35.98"),
    ],
)
def test_business_key_normalizes_without_losing_invoice_number_text(number, issue_date, amount, expected):
    assert business_key(number, issue_date, amount) == expected


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
def test_business_key_returns_none_for_missing_or_invalid_parts(number, issue_date, amount):
    assert business_key(number, issue_date, amount) is None


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

@pytest.mark.parametrize("role_user", ["admin@example.com", "finance@example.com", "hr@example.com", "hr-manager@example.com"])
def test_high_privilege_roles_can_read_invoice_records(permissions_module, role_user):
    permissions, frappe = permissions_module
    assert permissions.can_read_invoice(frappe.db.records["INV-1"], role_user) is True


def test_guest_is_always_denied(permissions_module):
    permissions, frappe = permissions_module
    assert permissions.can_read_invoice(frappe.db.records["INV-1"], "Guest") is False
    assert permissions.invoice_record_query("Guest") == "1=0"


def test_record_owner_request_applicant_current_approver_and_department_manager_can_read(permissions_module):
    permissions, frappe = permissions_module
    record = frappe.db.records["INV-1"]
    for user in ("uploader@example.com", "alice@example.com", "approver@example.com", "manager@example.com"):
        assert permissions.can_read_invoice(record, user) is True, user
    assert permissions.can_read_invoice(record, "ordinary-rd@example.com") is False
    assert permissions.can_read_invoice(record, "sales-manager@example.com") is False
    assert permissions.can_read_invoice(record, "stranger@example.com") is False


def test_batch_inherits_request_scope_and_unlinked_documents_stay_owner_only(permissions_module):
    permissions, frappe = permissions_module
    linked = frappe.db.batches["BATCH-1"]
    assert permissions.can_read_invoice(linked, "uploader@example.com") is True
    assert permissions.can_read_invoice(linked, "alice@example.com") is True
    assert permissions.can_read_invoice(linked, "manager@example.com") is True
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
    assert permissions.can_read_invoice(record, "manager@example.com") is True
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
    assert "req.department = '研发部'" in manager_sql
    assert {"alice@example.com", "EMP-A", "Alice"}.issubset(set(frappe.db.escaped))


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
