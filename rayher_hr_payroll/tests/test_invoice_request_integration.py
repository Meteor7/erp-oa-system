from __future__ import annotations
import json

import importlib
import sys
import types
from contextlib import contextmanager, nullcontext
from decimal import Decimal
from uuid import UUID

import pytest


class ValidationError(Exception):
    pass


_had_frappe = "frappe" in sys.modules
frappe_stub = types.ModuleType("frappe")
frappe_stub.ValidationError = ValidationError
frappe_stub._ = lambda value: value
frappe_stub.session = types.SimpleNamespace(user="alice@example.com")
frappe_stub.whitelist = lambda *args, **kwargs: (lambda function: function)
frappe_stub.throw = lambda message, exc=ValidationError: (_ for _ in ()).throw(exc(message))
frappe_stub.utils = types.ModuleType("frappe.utils")
frappe_stub.utils.now_datetime = lambda: "2026-07-21 10:00:00"
frappe_stub.get_roles = lambda user=None: ["Employee"]
frappe_stub.local = types.SimpleNamespace(site="test.localhost")
sys.modules["frappe"] = frappe_stub
sys.modules["frappe.utils"] = frappe_stub.utils

service = importlib.import_module("rayher_hr_payroll.invoice_ocr.service")
oa_entry = importlib.import_module("rayher_hr_payroll.api.oa_entry")
backfill_invoice_expense_context = importlib.import_module(
    "rayher_hr_payroll.patches.v1_0.backfill_invoice_expense_context"
)

sys.modules.pop("rayher_hr_payroll.api.oa_entry", None)
sys.modules.pop("rayher_hr_payroll.invoice_ocr.service", None)
invoice_ocr_package = sys.modules.get("rayher_hr_payroll.invoice_ocr")
if getattr(invoice_ocr_package, "permissions", None) is service.invoice_permissions:
    delattr(invoice_ocr_package, "permissions")
sys.modules.pop("rayher_hr_payroll.invoice_ocr.permissions", None)
if not _had_frappe:
    sys.modules.pop("frappe", None)
    sys.modules.pop("frappe.utils", None)


class Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def __setattr__(self, key, value):
        self[key] = value


@pytest.fixture(autouse=True)
def restore_service_frappe(monkeypatch):
    monkeypatch.setitem(sys.modules, "frappe", frappe_stub)
    monkeypatch.setitem(sys.modules, "frappe.utils", frappe_stub.utils)
    monkeypatch.setattr(service, "frappe", frappe_stub)
    monkeypatch.setattr(oa_entry, "frappe", frappe_stub)
    monkeypatch.setattr(oa_entry, "now_datetime", frappe_stub.utils.now_datetime)
    monkeypatch.setattr(oa_entry, "_resolve_approval_roles", lambda *_args, **_kwargs: _procurement_role_snapshots())
    monkeypatch.setattr(oa_entry, "sync_current_assignments", lambda current: None)
    frappe_stub.session.user = "alice@example.com"
    frappe_stub.get_roles = lambda user=None: ["Employee"]
    frappe_stub.local = types.SimpleNamespace(site="test.localhost")
    from rayher_hr_payroll import oa_organization
    supervisors = lambda: {"演示员工150": "演示员工132", "演示员工109": "演示员工155", "演示员工155": "演示员工21"}
    executives = lambda: {"演示员工21", "演示员工29"}
    monkeypatch.setattr(oa_entry, "current_supervisors", supervisors)
    monkeypatch.setattr(oa_organization, "current_supervisors", supervisors)
    monkeypatch.setattr(oa_organization, "executive_names", executives)
    monkeypatch.setattr(oa_entry, "executive_names", executives)
    monkeypatch.setattr(frappe_stub, "model", types.SimpleNamespace(naming=types.SimpleNamespace(make_autoname=lambda _: "MAT-00001")), raising=False)


def _request(*, amount="100.00", reason="", line_key="11111111-1111-4111-8111-111111111111", difference_reason=""):
    return Row(
        doctype=service.REQUEST_DOCTYPE,
        name="REQ-1",
        owner="alice@example.com",
        employee="EMP-1",
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        workflow_status=oa_entry.STATUS_DRAFT,
        no_invoice_reason=reason,
        expense_lines=[
            Row(
                line_key=line_key,
                amount=Decimal(amount),
                invoice_difference_reason=difference_reason,
            )
        ],
    )


def _invoice(status="已确认", *, total="100.00", line_key="11111111-1111-4111-8111-111111111111", **values):
    row = Row(
        name=values.pop("name", "INV-1"),
        recognition_status=status,
        total_amount=Decimal(total) if total is not None else None,
        expense_line_key=line_key,
        invoice_category="电子发票（普通发票）",
        expense_item="交通费",
        project_name="文具印章",
        invoice_number="000123",
        original_filename="禁止进入搜索.pdf",
        ocr_payload="RAW-SECRET",
        request="REQ-1",
        batch="BATCH-1",
    )
    row.update(values)
    return row


def _install_records(monkeypatch, records):
    monkeypatch.setattr(service, "_request_invoice_records", lambda _request_name, **_kwargs: list(records))


def _uuid4(value):
    parsed = UUID(str(value))
    return parsed.version == 4 and str(parsed) == str(value).lower()


def test_normalize_generates_uuid4_and_preserves_difference_reason():
    rows, total = oa_entry._normalize_expense_lines(
        [{"category": "办公费", "amount": "35.98", "invoice_difference_reason": "部分报销"}]
    )
    assert total == 35.98
    assert _uuid4(rows[0]["line_key"])
    assert rows[0]["invoice_difference_reason"] == "部分报销"


def test_normalize_keeps_valid_uuid4_but_replaces_duplicate_and_invalid_client_keys():
    key = "11111111-1111-4111-8111-111111111111"
    rows, _total = oa_entry._normalize_expense_lines(
        [
            {"category": "办公费", "amount": 1, "line_key": key},
            {"category": "差旅费", "amount": 2, "line_key": key},
            {"category": "咨询费", "amount": 3, "line_key": "../../attacker"},
        ]
    )
    assert rows[0]["line_key"] == key
    assert all(_uuid4(row["line_key"]) for row in rows)
    assert len({row["line_key"] for row in rows}) == 3


def test_legacy_consumption_key_is_preserved_and_stable():
    payload = [{"source_consumption": "CD-0001", "category": "办公费", "amount": 10, "line_key": "legacy-line-7"}]
    first, _ = oa_entry._normalize_expense_lines(payload)
    second, _ = oa_entry._normalize_expense_lines(payload)
    assert first[0]["line_key"] == "legacy-line-7"
    assert second[0]["line_key"] == "legacy-line-7"


def test_normalize_rejects_overlong_difference_reason():
    with pytest.raises(ValidationError, match="差异说明"):
        oa_entry._normalize_expense_lines(
            [{"category": "办公费", "amount": 1, "invoice_difference_reason": "x" * 501}]
        )


def test_draft_validation_never_blocks_unfinished_or_missing_invoices(monkeypatch):
    request = _request()
    for records in ([], [_invoice("排队中")], [_invoice("失败")]):
        _install_records(monkeypatch, records)
        service.validate_request_invoices(request, submitting=False)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("排队中", "处理中"),
        ("识别中", "处理中"),
        ("待确认", "未确认"),
        ("疑似重复", "疑似重复"),
        ("失败", "失败"),
        ("未知状态", "状态异常"),
    ],
)
def test_submit_blocks_every_unresolved_invoice_state(monkeypatch, status, message):
    _install_records(monkeypatch, [_invoice(status)])
    with pytest.raises(ValidationError, match=message):
        service.validate_request_invoices(_request(reason="有原因也不能绕过"), submitting=True)


def test_submit_without_effective_invoice_requires_trimmed_reason(monkeypatch):
    for records in ([], [_invoice("已排除")]):
        _install_records(monkeypatch, records)
        with pytest.raises(ValidationError, match="无票原因"):
            service.validate_request_invoices(_request(reason="   "), submitting=True)
        service.validate_request_invoices(_request(reason="纸质票据遗失"), submitting=True)


def test_confirmed_invoice_must_link_to_a_real_expense_line(monkeypatch):
    _install_records(monkeypatch, [_invoice(line_key="")])
    with pytest.raises(ValidationError, match="未关联费用明细"):
        service.validate_request_invoices(_request(), submitting=True)
    _install_records(monkeypatch, [_invoice(line_key="missing-line")])
    with pytest.raises(ValidationError, match="不属于该报销单"):
        service.validate_request_invoices(_request(), submitting=True)


def test_many_confirmed_invoices_on_one_line_sum_with_decimal_tolerance(monkeypatch):
    records = [
        _invoice(total="35.98", name="INV-1"),
        _invoice(total="64.01", name="INV-2"),
    ]
    _install_records(monkeypatch, records)
    service.validate_request_invoices(_request(amount="100.00"), submitting=True)


def test_amount_mismatch_requires_per_line_reason(monkeypatch):
    _install_records(monkeypatch, [_invoice(total="90.00")])
    with pytest.raises(ValidationError, match="金额.*差异说明"):
        service.validate_request_invoices(_request(amount="100.00"), submitting=True)
    service.validate_request_invoices(
        _request(amount="100.00", difference_reason="仅报销其中一部分"),
        submitting=True,
    )


def test_database_zero_for_missing_ocr_total_still_requires_difference_reason(monkeypatch):
    record = _invoice(
        total="0.00",
        ocr_payload=json.dumps({"fields": {"total_amount": None}}),
    )
    _install_records(monkeypatch, [record])
    with pytest.raises(ValidationError, match="\u91d1\u989d\u7f3a\u5931"):
        service.validate_request_invoices(_request(amount="100.00"), submitting=True)
    service.validate_request_invoices(
        _request(amount="100.00", difference_reason="OCR did not read a total"),
        submitting=True,
    )


def test_uninvoiced_line_requires_difference_reason_when_other_lines_have_invoices(monkeypatch):
    request = _request(amount="100.00")
    request.expense_lines.append(
        Row(
            line_key="22222222-2222-4222-8222-222222222222",
            amount=Decimal("20.00"),
            invoice_difference_reason="",
        )
    )
    _install_records(monkeypatch, [_invoice(total="100.00")])
    with pytest.raises(ValidationError, match="未关联发票.*差异说明"):
        service.validate_request_invoices(request, submitting=True)
    request.expense_lines[1].invoice_difference_reason = "该项无票"
    service.validate_request_invoices(request, submitting=True)


def test_summary_counts_nonexcluded_and_searches_confirmed_only(monkeypatch):
    records = [
        _invoice(name="INV-1"),
        _invoice("待确认", name="INV-2", invoice_category="未确认类别", project_name="未确认项目", invoice_number="999999"),
        _invoice("已排除", name="INV-3"),
        _invoice(name="INV-4", invoice_category="电子发票（普通发票）", project_name="文具印章", invoice_number="000123"),
    ]
    _install_records(monkeypatch, records)
    summary = service.request_invoice_summary(_request())
    assert summary["invoice_count"] == 3
    assert "已确认" in summary["invoice_status"] and "待确认" in summary["invoice_status"]
    assert summary["invoice_search_text"] == "电子发票（普通发票）；文具印章；000123"
    assert summary["invoice_categories"] == ["电子发票（普通发票）"]
    assert summary["invoice_project_names"] == ["文具印章"]
    assert summary["invoice_numbers"] == ["000123"]
    assert "未确认" not in summary["invoice_search_text"]
    assert "禁止进入搜索" not in summary["invoice_search_text"]
    assert "RAW-SECRET" not in summary["invoice_search_text"]


def _attach_environment(monkeypatch, *, batch_owner="alice@example.com", batch_request="", record_request=""):
    batch = Row(
        doctype=service.BATCH_DOCTYPE,
        name="BATCH-1",
        owner=batch_owner,
        request=batch_request,
        batch_status="已完成",
    )
    request = _request()
    records = {
        "INV-1": _invoice(name="INV-1", request=record_request, expense_line_key="11111111-1111-4111-8111-111111111111"),
        "INV-2": _invoice(name="INV-2", request=record_request, expense_line_key=""),
    }
    docs = {
        (service.BATCH_DOCTYPE, batch.name): batch,
        (service.REQUEST_DOCTYPE, request.name): request,
        **{(service.RECORD_DOCTYPE, name): record for name, record in records.items()},
    }
    lock_order = []
    saves = []

    @contextmanager
    def transaction_lock(category, *parts, **_kwargs):
        lock_order.append((category, *parts))
        yield object()

    def require_batch(name, owner_only=False, current=False):
        assert owner_only is True and current is True
        current_batch = docs[(service.BATCH_DOCTYPE, name)]
        roles = set(frappe_stub.get_roles(frappe_stub.session.user))
        if current_batch.owner != frappe_stub.session.user and "System Manager" not in roles:
            service._throw("您无权访问该发票批次。")
        return current_batch

    def current_doc(doctype, name):
        return docs[(doctype, name)]

    def record_rows(doctype, *, filters=None, fields=None, **_kwargs):
        if doctype == service.RECORD_DOCTYPE and filters == {"request": request.name}:
            return [record for record in records.values() if record.request == request.name]
        if doctype == service.RECORD_DOCTYPE:
            assert filters == {"batch": "BATCH-1"}
            return [
                Row(name=name, batch="BATCH-1")
                for name in sorted(records)
            ]
        assert doctype == service.BATCH_DOCTYPE
        assert filters == {"request": request.name}
        return (
            [Row(name=batch.name, request=request.name)]
            if batch.request == request.name
            else []
        )

    def permission(request_doc, ptype, current=False):
        assert ptype == "edit"
        if request_doc.owner != frappe_stub.session.user and "System Manager" not in frappe_stub.get_roles():
            service._throw("您无权访问该费用付款/报销单。")

    def committed_batch_names(request_name):
        assert request_name == request.name
        assert lock_order[0] == ("request", request.name)
        return [batch.name] if batch.request == request.name else []

    monkeypatch.setattr(service, "_transaction_lock", transaction_lock)
    monkeypatch.setattr(
        service,
        "_latest_committed_request_batch_names",
        committed_batch_names,
    )
    monkeypatch.setattr(service, "_require_batch", require_batch)
    monkeypatch.setattr(service, "_current_doc", current_doc)
    monkeypatch.setattr(service, "_get_all", record_rows)
    monkeypatch.setattr(service, "_current_rows", record_rows)
    monkeypatch.setattr(service, "_request_permission", permission)
    monkeypatch.setattr(service, "_save", lambda doc: saves.append(doc))
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda _request, **_kwargs: {
            "invoice_count": 2,
            "invoice_status": "已确认",
            "invoice_search_text": "电子发票（普通发票）；文具印章；000123",
        },
    )
    return batch, request, records, lock_order, saves


def test_attach_batch_uses_request_batch_record_lock_order_and_preserves_line_links(monkeypatch):
    batch, request, records, lock_order, saves = _attach_environment(monkeypatch)
    attached_request = service.attach_batch_to_request(batch.name, request)
    assert attached_request is request
    assert lock_order == [
        ("request", "REQ-1"),
        ("batch", "BATCH-1"),
        ("record", "INV-1"),
        ("record", "INV-2"),
    ]
    assert batch.request == request.name
    assert {record.request for record in records.values()} == {request.name}
    assert records["INV-1"].expense_line_key == "11111111-1111-4111-8111-111111111111"
    assert records["INV-2"].expense_line_key == ""
    assert request.invoice_count == 2 and request.invoice_status == "已确认"
    assert batch in saves and request in saves and all(record in saves for record in records.values())


def test_paid_deferred_request_accepts_confirmed_supplement_batch(monkeypatch):
    batch, request, records, lock_order, saves = _attach_environment(monkeypatch)
    request.workflow_status = oa_entry.STATUS_PAID
    request.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    request.invoice_followup_status = oa_entry.INVOICE_FOLLOWUP_PENDING
    request.operation_log = "[]"
    request.amount = Decimal("200.00")
    monkeypatch.setattr(service.invoice_permissions, "can_edit_request", lambda *_args, **_kwargs: True)

    result = service.attach_batch_to_request(batch.name, request)

    assert result is request
    assert request.invoice_followup_status == oa_entry.INVOICE_FOLLOWUP_RECEIVED
    assert json.loads(request.operation_log)[-1]["action"] == "补录发票"
    assert batch.request == request.name
    assert {record.request for record in records.values()} == {request.name}
    assert lock_order[:2] == [("request", request.name), ("batch", batch.name)]
    assert request in saves


def test_supplement_with_an_amount_gap_needs_a_difference_note(monkeypatch):
    batch, request, records, _lock_order, saves = _attach_environment(monkeypatch)
    request.workflow_status = oa_entry.STATUS_PAID
    request.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    request.invoice_followup_status = oa_entry.INVOICE_FOLLOWUP_PENDING
    request.operation_log = "[]"
    request.amount = Decimal("199.97")
    monkeypatch.setattr(service.invoice_permissions, "can_edit_request", lambda *_args, **_kwargs: True)

    with pytest.raises(ValidationError, match="相差超过 0.02 元"):
        service.attach_batch_to_request(batch.name, request)
    assert not batch.request and saves == []

    service.attach_batch_to_request(batch.name, request, "另一张发票下月开具")
    assert request.invoice_difference_note == "另一张发票下月开具"
    assert "另一张发票下月开具" in json.loads(request.operation_log)[-1]["note"]


def test_paid_deferred_request_rejects_unconfirmed_supplement_batch(monkeypatch):
    batch, request, records, _lock_order, saves = _attach_environment(monkeypatch)
    request.workflow_status = oa_entry.STATUS_PAID
    request.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    request.invoice_followup_status = oa_entry.INVOICE_FOLLOWUP_PENDING
    request.operation_log = "[]"
    records["INV-2"].recognition_status = "待确认"
    monkeypatch.setattr(service.invoice_permissions, "can_edit_request", lambda *_args, **_kwargs: True)

    with pytest.raises(ValidationError, match="未确认"):
        service.attach_batch_to_request(batch.name, request)

    assert not batch.request and not any(record.request for record in records.values())
    assert saves == []


def test_attach_batch_rejects_cross_user_without_mutation(monkeypatch):
    batch, request, records, _locks, saves = _attach_environment(
        monkeypatch, batch_owner="mallory@example.com"
    )
    with pytest.raises(ValidationError, match="无权访问该发票批次"):
        service.attach_batch_to_request(batch.name, request)
    assert not batch.request and not any(record.request for record in records.values())
    assert saves == []


@pytest.mark.parametrize(
    ("batch_request", "record_request", "message"),
    [
        ("REQ-OTHER", "", "批次.*其他"),
        ("", "REQ-OTHER", "发票.*其他"),
    ],
)
def test_attach_batch_rejects_cross_request(monkeypatch, batch_request, record_request, message):
    batch, request, records, _locks, _saves = _attach_environment(
        monkeypatch,
        batch_request=batch_request,
        record_request=record_request,
    )
    with pytest.raises(ValidationError, match=message):
        service.attach_batch_to_request(batch.name, request)
    assert batch.request == batch_request
    assert {record.request for record in records.values()} == {record_request}


def test_attach_batch_allows_system_manager_owner_override(monkeypatch):
    batch, request, records, _locks, _saves = _attach_environment(
        monkeypatch, batch_owner="mallory@example.com"
    )
    frappe_stub.get_roles = lambda user=None: ["System Manager"]
    service.attach_batch_to_request(batch.name, request)
    assert batch.request == request.name
    assert {record.request for record in records.values()} == {request.name}


class RequestDocument(Row):
    def __init__(self, environment, values):
        super().__init__(values)
        object.__setattr__(self, "environment", environment)

    def set(self, field, value):
        self[field] = list(value) if isinstance(value, list) else value

    def append(self, field, value):
        child = Row(value)
        self.setdefault(field, []).append(child)
        return child

    def insert(self, ignore_permissions=False):
        assert ignore_permissions is True
        if not self.get("name"):
            self.name = "REQ-NEW"
        self.owner = frappe_stub.session.user
        self.environment.pending[self.name] = self
        self.environment.inserted.append(self)
        return self

    def save(self, ignore_permissions=False):
        assert ignore_permissions is True
        self.environment.pending[self.name] = self
        self.environment.saved.append(self)
        return self


class RequestDB:
    def __init__(self, environment):
        self.environment = environment

    def get_value(self, doctype, filters, fieldname, as_dict=False, **_kwargs):
        if doctype == "Employee":
            if as_dict:
                return Row(name="EMP-1", employee_name="Alice", department="研发部", reports_to="")
            return None
        if doctype == "User":
            return "Alice"
        return None

    def exists(self, doctype, filters):
        assert doctype == "Notification Log"
        return False

    def commit(self):
        self.environment.commits += 1
        self.environment.committed.update(self.environment.pending)
        self.environment.pending.clear()

    def rollback(self):
        self.environment.pending.clear()


class RequestEnvironment:
    def __init__(self):
        self.pending = {}
        self.committed = {}
        self.inserted = []
        self.saved = []
        self.commits = 0
        self.current_reads = []
        self.db = RequestDB(self)

    def get_doc(self, doctype_or_values, name=None, for_update=False, **_kwargs):
        if isinstance(doctype_or_values, dict):
            values = dict(doctype_or_values)
            values.setdefault("expense_lines", [])
            values.setdefault("steps", [])
            return RequestDocument(self, values)
        if for_update:
            self.current_reads.append((doctype_or_values, name))
        return self.pending.get(name) or self.committed[name]


def _simple_route(*_args, active=True, **_kwargs):
    return {
        "context": {"employee": "EMP-1", "employee_name": "Alice", "department": "研发部", "supervisor": ""},
        "steps": [
            {
                "step_index": 1,
                "label": "财务审核",
                "mode": "approve",
                "approvers": ["Alice"],
                "status": oa_entry.STATUS_PENDING if active else oa_entry.STATUS_WAIT_FLOW,
                "approved_by": [],
            }
        ],
    }


def _install_request_environment(monkeypatch):
    environment = RequestEnvironment()
    frappe_stub.db = environment.db
    frappe_stub.get_doc = environment.get_doc
    frappe_stub.get_roles = lambda user=None: ["Employee"]
    monkeypatch.setattr(oa_entry, "preview_route", _simple_route)
    monkeypatch.setattr(
        oa_entry,
        "_employee_context",
        lambda user=None: {
            "employee": "EMP-1",
            "employee_name": "Alice",
            "department": "研发部",
            "supervisor": "",
        },
    )
    monkeypatch.setattr(
        oa_entry,
        "_summarize_doc",
        lambda doc, authorized_expense_lines=None: {"name": doc.name, "status": doc.workflow_status},
    )
    return environment


def test_create_draft_attaches_batch_after_insert_without_internal_commit(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    events = []
    monkeypatch.setattr(
        service,
        "attach_batch_to_request",
        lambda batch, doc: (events.append(("attach", batch, doc.name, doc.name in environment.pending)) or doc),
    )
    monkeypatch.setattr(
        service,
        "validate_request_invoices",
        lambda doc, submitting: events.append(("validate", submitting, doc.workflow_status)),
    )
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda _doc: {"invoice_count": 1, "invoice_status": "已确认", "invoice_search_text": "000123"},
    )
    result = oa_entry.create_request(
        oa_entry.REQUEST_EXPENSE_PAYMENT,
        subject="报销",
        submit=0,
        expense_lines=[{"category": "办公费", "amount": "100.00"}],
        invoice_batch=" BATCH-1 ",
        no_invoice_reason="  草稿原因  ",
    )
    doc = environment.pending[result["name"]]
    assert events[0] == ("attach", "BATCH-1", doc.name, True)
    assert ("validate", False, oa_entry.STATUS_DRAFT) in events
    assert doc.no_invoice_reason == "草稿原因"
    assert environment.commits == 0


def test_create_failure_leaves_request_and_batch_in_one_rollback_scope(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    monkeypatch.setattr(
        service,
        "attach_batch_to_request",
        lambda _batch, _doc: (_ for _ in ()).throw(ValidationError("跨用户批次")),
    )
    with pytest.raises(ValidationError, match="跨用户"):
        oa_entry.create_request(
            oa_entry.REQUEST_EXPENSE_PAYMENT,
            submit=0,
            expense_lines=[{"category": "办公费", "amount": "10.00"}],
            invoice_batch="BATCH-OTHER",
        )
    assert environment.commits == 0 and environment.pending
    environment.db.rollback()
    assert environment.pending == {} and environment.committed == {}


@pytest.mark.parametrize(
    ("invoice_batch", "reason", "message"),
    [
        ({"name": "BATCH-1"}, None, "批次.*格式"),
        (None, {"reason": "x"}, "无票原因.*格式"),
        ("x" * 141, None, "批次.*过长"),
        (None, "x" * 1001, "无票原因.*1000"),
    ],
)
def test_create_rejects_untrusted_invoice_fields(monkeypatch, invoice_batch, reason, message):
    _install_request_environment(monkeypatch)
    with pytest.raises(ValidationError, match=message):
        oa_entry.create_request(
            oa_entry.REQUEST_EXPENSE_PAYMENT,
            submit=0,
            expense_lines=[{"category": "办公费", "amount": 1}],
            invoice_batch=invoice_batch,
            no_invoice_reason=reason,
        )


def test_direct_create_submission_validates_before_workflow_transition(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    observed = []

    def reject(doc, submitting):
        observed.append((submitting, doc.workflow_status))
        if submitting:
            raise ValidationError("未确认")

    monkeypatch.setattr(service, "validate_request_invoices", reject)
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda _doc: {"invoice_count": 1, "invoice_status": "已确认", "invoice_search_text": ""},
    )
    with pytest.raises(ValidationError, match="未确认"):
        oa_entry.create_request(
            oa_entry.REQUEST_EXPENSE_PAYMENT,
            submit=1,
            expense_lines=[{"category": "办公费", "issue_date": "2026-09-20", "amount": 1, "project_name": "项目甲", "expense_item": "办公费", "description": "测试费用", "no_invoice_reason": "有原因也不能绕过状态"}],
            no_invoice_reason="有原因也不能绕过状态",
            invoice_handling_mode=oa_entry.INVOICE_MODE_AVAILABLE,
        )
    doc = environment.pending["REQ-NEW"]
    assert observed[-1] == (True, oa_entry.STATUS_DRAFT)
    assert doc.workflow_status == oa_entry.STATUS_DRAFT
    assert environment.commits == 0


def test_invoice_handling_modes_enforce_timing_specific_requirements(monkeypatch):
    summary = {"invoice_count": 0, "invoice_status": "无发票"}
    monkeypatch.setattr(service, "request_invoice_summary", lambda *_args, **_kwargs: summary)
    pending = _request(reason="等待供应商开票")
    pending.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    pending.expected_invoice_date = "2026-09-30"
    oa_entry._validate_invoice_handling_submission(pending)
    assert pending.invoice_followup_status == oa_entry.INVOICE_FOLLOWUP_PENDING
    no_invoice = _request(reason="制度规定无需发票")
    no_invoice.invoice_handling_mode = oa_entry.INVOICE_MODE_NOT_REQUIRED
    oa_entry._validate_invoice_handling_submission(no_invoice)
    assert no_invoice.invoice_followup_status == oa_entry.INVOICE_FOLLOWUP_NOT_REQUIRED


def test_manual_no_invoice_payment_requires_an_approved_purchase_source(monkeypatch):
    monkeypatch.setattr(service, "request_invoice_summary", lambda *_args, **_kwargs: {"invoice_count": 0, "invoice_status": "无发票"})
    request = _request(reason="供应商付款后开票")
    request.source_type = oa_entry.SOURCE_MANUAL
    request.invoice_handling_mode = oa_entry.INVOICE_MODE_PENDING
    request.expected_invoice_date = "2026-09-30"
    with pytest.raises(ValidationError, match="必须关联已批准的购买申请"):
        oa_entry._validate_invoice_handling_submission(request)


def test_invoice_required_procurement_plan_is_checked_at_final_payment(monkeypatch):
    payment = types.SimpleNamespace(
        name="PAY-2", request_type=oa_entry.REQUEST_PROCUREMENT_PAYMENT,
        source_request="PROC-1", source_payment_plan_row="PLAN-2",
    )
    source = types.SimpleNamespace(
        payment_plan=[types.SimpleNamespace(name="PLAN-2", invoice_requirement="付款前提供")]
    )
    monkeypatch.setattr(oa_entry.frappe, "get_doc", lambda *_args, **_kwargs: source, raising=False)
    monkeypatch.setattr(oa_entry, "_request_business_document_types", lambda *_args: set())
    with pytest.raises(ValidationError, match="上传发票后再确认付款"):
        oa_entry._validate_procurement_payment_release(payment)
    monkeypatch.setattr(oa_entry, "_request_business_document_types", lambda *_args: {"发票"})
    oa_entry._validate_procurement_payment_release(payment)


def test_available_invoice_mode_requires_an_effective_invoice(monkeypatch):
    monkeypatch.setattr(service, "request_invoice_summary", lambda *_args, **_kwargs: {"invoice_count": 0, "invoice_status": "无发票"})
    request = _request(reason="")
    request.invoice_handling_mode = oa_entry.INVOICE_MODE_AVAILABLE
    with pytest.raises(ValidationError, match="必须上传并确认发票"):
        oa_entry._validate_invoice_handling_submission(request)


def test_update_leave_draft_persists_owner_edits(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "LEAVE-1",
            "owner": "alice@example.com",
            "employee": "EMP-1",
            "request_type": oa_entry.REQUEST_LEAVE,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "subject": "Old leave",
            "from_date": "2026-08-21",
            "to_date": "2026-08-21",
            "reason": "Old reason",
            "steps": [],
        },
    )
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    result = oa_entry.update_leave_draft(
        doc.name,
        "Updated leave",
        "2026-08-22",
        "2026-08-23",
        "Updated reason",
    )

    assert result["name"] == doc.name
    assert doc.subject == "Updated leave"
    assert doc.from_date == "2026-08-22"
    assert doc.to_date == "2026-08-23"
    assert doc.reason == "Updated reason"
    assert environment.current_reads == [(service.REQUEST_DOCTYPE, doc.name)]


def test_submit_request_uses_request_lock_current_read_and_server_validation(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-1",
            "owner": "alice@example.com",
            "employee": "EMP-1",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "department": "研发部",
            "supervisor": "",
            "asset_category": "其它",
            "expense_lines": [Row(line_key="11111111-1111-4111-8111-111111111111", source_invoice=None, project_name="项目甲", expense_item="办公费", no_invoice_reason="纸质票据遗失", total_amount=1, amount=1, issue_date="2026-09-20", description="测试费用", invoice_difference_reason="")],
            "steps": [],
            "no_invoice_reason": "纸质票据遗失",
            "invoice_handling_mode": oa_entry.INVOICE_MODE_NOT_REQUIRED,
        },
    )
    environment.committed[doc.name] = doc
    locks = []
    validations = []

    @contextmanager
    def request_lock(category, name):
        locks.append((category, name))
        yield object()

    monkeypatch.setattr(service, "_transaction_lock", request_lock)
    monkeypatch.setattr(service, "_request_permission", lambda current_doc, ptype, current=False: None)
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda current_doc: {"invoice_count": 0, "invoice_status": "无发票"},
    )
    result = oa_entry.submit_request("REQ-1")
    assert locks == [("request", "REQ-1")]
    assert environment.current_reads == [(service.REQUEST_DOCTYPE, "REQ-1")]
    assert doc.invoice_followup_status == oa_entry.INVOICE_FOLLOWUP_NOT_REQUIRED
    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert result["status"] == oa_entry.STATUS_PENDING
    assert json.loads(doc.operation_log)[-1]["action"] == "提交申请"
    assert environment.commits == 0


@pytest.mark.parametrize("operation", ["action", "paid"])
def test_existing_request_mutations_use_same_current_request_lock(monkeypatch, operation):
    environment = _install_request_environment(monkeypatch)
    workflow_status = oa_entry.STATUS_PENDING if operation == "action" else oa_entry.STATUS_COMPLETED
    step = Row(
        step_index=1,
        label="财务审核",
        mode="approve",
        approvers='["Alice"]',
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
        action_by="",
        acted_on=None,
        note="",
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-1",
            "owner": "alice@example.com",
            "employee": "EMP-1",
            "employee_name": "Alice",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": workflow_status,
            "department": "研发部",
            "supervisor": "",
            "asset_category": "其它",
            "current_step_index": 1,
            "current_step_label": "财务审核",
            "expense_lines": [],
            "steps": [step],
            "reason": "",
        },
    )
    environment.committed[doc.name] = doc
    locks = []

    @contextmanager
    def request_lock(category, name):
        locks.append((category, name))
        yield object()

    monkeypatch.setattr(service, "_transaction_lock", request_lock)
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"Alice"})
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["Alice"])
    if operation == "action":
        oa_entry.action_request("REQ-1", "approve")
    else:
        frappe_stub.get_roles = lambda user=None: ["Accounts User"]
        oa_entry.mark_paid("REQ-1")
    assert locks == [("request", "REQ-1")]
    assert environment.current_reads == [(service.REQUEST_DOCTYPE, "REQ-1")]
    assert environment.commits == 0
    if operation == "paid":
        assert json.loads(doc.operation_log)[-1]["action"] == "标记已付款"


def test_zero_total_confirmed_invoice_is_linked_but_requires_amount_difference_reason(monkeypatch):
    _install_records(monkeypatch, [_invoice(total="0.00")])
    with pytest.raises(ValidationError, match="金额与发票合计"):
        service.validate_request_invoices(_request(amount="1.00"), submitting=True)
    service.validate_request_invoices(
        _request(amount="1.00", difference_reason="零金额发票仅作凭证"),
        submitting=True,
    )


def test_legacy_consumption_generated_key_survives_reordering():
    first_payload = [
        {"source_consumption": "CD-0001", "category": "办公费", "amount": 10},
        {"source_consumption": "CD-0002", "category": "差旅费", "amount": 20},
    ]
    second_payload = list(reversed(first_payload))
    first, _ = oa_entry._normalize_expense_lines(first_payload)
    second, _ = oa_entry._normalize_expense_lines(second_payload)
    first_keys = {row["source_consumption"]: row["line_key"] for row in first}
    second_keys = {row["source_consumption"]: row["line_key"] for row in second}
    assert first_keys == second_keys


# --- Task 6 independent-review RED tests ---
@pytest.mark.parametrize("requested_submit", [0, 1])
def test_create_continues_with_current_request_returned_by_attach(monkeypatch, requested_submit):
    environment = _install_request_environment(monkeypatch)
    environment.latest_modified = {}
    environment.modification_version = 0
    attached = []
    validated = []

    class TimestampCheckedDocument(RequestDocument):
        def insert(self, ignore_permissions=False):
            super().insert(ignore_permissions=ignore_permissions)
            environment.modification_version += 1
            self.modified = f"v{environment.modification_version}"
            environment.latest_modified[self.name] = self.modified
            return self

        def save(self, ignore_permissions=False):
            if self.modified != environment.latest_modified[self.name]:
                raise ValidationError("TimestampMismatch")
            environment.modification_version += 1
            self.modified = f"v{environment.modification_version}"
            environment.latest_modified[self.name] = self.modified
            return super().save(ignore_permissions=ignore_permissions)

    def get_doc(doctype_or_values, name=None, for_update=False, **_kwargs):
        if isinstance(doctype_or_values, dict):
            values = dict(doctype_or_values)
            values.setdefault("expense_lines", [])
            values.setdefault("steps", [])
            return TimestampCheckedDocument(environment, values)
        return environment.get_doc(doctype_or_values, name, for_update=for_update)

    frappe_stub.get_doc = get_doc

    def attach(_batch, inserted):
        current = TimestampCheckedDocument(environment, dict(inserted))
        environment.pending[current.name] = current
        current.save(ignore_permissions=True)
        attached.append(current)
        return current

    def validate(doc, submitting):
        validated.append((doc, submitting))
        return {"invoice_count": 1, "invoice_status": "\u5df2\u786e\u8ba4"}

    monkeypatch.setattr(service, "attach_batch_to_request", attach)
    monkeypatch.setattr(service, "validate_request_invoices", validate)
    monkeypatch.setattr(service, "request_invoice_summary", lambda *_args, **_kwargs: {"invoice_count": 1, "invoice_status": "已确认"})

    result = oa_entry.create_request(
        oa_entry.REQUEST_EXPENSE_PAYMENT,
        subject="expense",
        submit=requested_submit,
        expense_lines=[{"category": "office", "issue_date": "2026-09-20", "amount": "100.00", "project_name": "项目甲", "expense_item": "办公费", "description": "测试费用", "no_invoice_reason": "测试无票"}],
        invoice_batch="BATCH-1",
        invoice_handling_mode=oa_entry.INVOICE_MODE_AVAILABLE,
    )

    assert environment.pending[result["name"]] is attached[0]
    assert all(doc is attached[0] for doc, _submitting in validated)
    assert environment.saved[-2:] == [attached[0], attached[0]]
    assert attached[0].modified == "v3"
    expected_status = (
        oa_entry.STATUS_PENDING if requested_submit else oa_entry.STATUS_DRAFT
    )
    assert attached[0].workflow_status == expected_status


def test_attach_batch_rejects_request_that_is_no_longer_draft_under_lock(monkeypatch):
    batch, request, records, lock_order, saves = _attach_environment(monkeypatch)
    request.workflow_status = "审批中"
    with pytest.raises(ValidationError, match="状态或权限不允许"):
        service.attach_batch_to_request(batch.name, {"name": request.name})
    assert lock_order[0] == ("request", request.name)
    assert not batch.request and not any(record.request for record in records.values())
    assert saves == []


def test_update_draft_invoice_details_only_changes_reason_fields(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-1",
            "owner": frappe_stub.session.user,
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "no_invoice_reason": "",
            "expense_lines": [
                Row(line_key="11111111-1111-4111-8111-111111111111", amount=Decimal("10.00"), invoice_difference_reason="")
            ],
            "steps": [],
        },
    )
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: {"name": current.name})
    result = oa_entry.update_draft_invoice_details(
        doc.name,
        no_invoice_reason="  无票说明  ",
        expense_line_reasons='{"11111111-1111-4111-8111-111111111111":"  金额差异  "}',
    )
    assert result == {"name": doc.name}
    assert doc.no_invoice_reason == "无票说明"
    assert doc.expense_lines[0].invoice_difference_reason == "金额差异"
    with pytest.raises(ValidationError, match="不属于"):
        oa_entry.update_draft_invoice_details(
            doc.name, expense_line_reasons='{"22222222-2222-4222-8222-222222222222":"未知行"}'
        )
    doc.workflow_status = oa_entry.STATUS_PENDING
    with pytest.raises(ValidationError, match="只有草稿"):
        oa_entry.update_draft_invoice_details(doc.name, no_invoice_reason="不能修改")


# --- Task 8 independent-review executable regression tests ---

def test_attach_batch_rejects_a_different_committed_batch_for_the_same_request(
    monkeypatch,
):
    batch, request, records, lock_order, saves = _attach_environment(monkeypatch)

    def committed_batch_names(request_name):
        assert request_name == request.name
        assert lock_order[0] == ("request", request.name)
        return ["BATCH-OTHER"]

    monkeypatch.setattr(
        service,
        "_latest_committed_request_batch_names",
        committed_batch_names,
    )
    with pytest.raises(
        ValidationError,
        match="\u5df2\u5173\u8054.*\u5176\u4ed6.*\u6279\u6b21",
    ):
        service.attach_batch_to_request(batch.name, request)
    assert not batch.request and not any(record.request for record in records.values())
    assert saves == []


def _install_draft_reason_doc(monkeypatch, line_count=1):
    environment = _install_request_environment(monkeypatch)
    lines = [
        Row(
            line_key=f"{index + 1:08d}-1111-4111-8111-{index + 1:012d}",
            amount=Decimal("10.00"),
            invoice_difference_reason="",
        )
        for index in range(line_count)
    ]
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-STRICT",
            "owner": frappe_stub.session.user,
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "no_invoice_reason": "",
            "expense_lines": lines,
            "steps": [],
        },
    )
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: {"name": current.name})
    return environment, doc


@pytest.mark.parametrize("payload", ["{", "[]", '"not-an-object"', "{\"key\": NaN}"])
def test_update_draft_invoice_details_rejects_malformed_or_non_object_json(monkeypatch, payload):
    _install_draft_reason_doc(monkeypatch)
    with pytest.raises(ValidationError, match="JSON"):
        oa_entry.update_draft_invoice_details("REQ-STRICT", expense_line_reasons=payload)


def test_update_draft_invoice_details_rejects_duplicate_raw_and_trimmed_keys(monkeypatch):
    _environment, doc = _install_draft_reason_doc(monkeypatch)
    key = doc.expense_lines[0].line_key
    with pytest.raises(ValidationError, match="\u91cd\u590d"):
        oa_entry.update_draft_invoice_details(
            doc.name,
            expense_line_reasons=f'{{"{key}":"one","{key}":"two"}}',
        )
    with pytest.raises(ValidationError, match="\u91cd\u590d"):
        oa_entry.update_draft_invoice_details(
            doc.name,
            expense_line_reasons={f" {key}": "one", f"{key} ": "two"},
        )


def test_update_draft_invoice_details_rejects_oversized_payload_before_lock(monkeypatch):
    entered = []

    @contextmanager
    def transaction_lock(*_args, **_kwargs):
        entered.append(True)
        yield

    monkeypatch.setattr(service, "_transaction_lock", transaction_lock)
    payload = json.dumps({"line": "x" * (64 * 1024)}, ensure_ascii=False)
    loads = []
    monkeypatch.setattr(oa_entry.json, "loads", lambda *_args, **_kwargs: loads.append(True))
    with pytest.raises(ValidationError, match="64KB"):
        oa_entry.update_draft_invoice_details("REQ-STRICT", expense_line_reasons=payload)
    assert entered == []
    assert loads == []


def test_update_draft_invoice_details_bounds_reason_count_by_request_and_hard_limit(monkeypatch):
    _environment, doc = _install_draft_reason_doc(monkeypatch, line_count=1)
    reasons = {
        doc.expense_lines[0].line_key: "one",
        "22222222-2222-4222-8222-222222222222": "two",
    }
    with pytest.raises(
        ValidationError,
        match="\u6570\u91cf.*\u8d39\u7528\u660e\u7ec6",
    ):
        oa_entry.update_draft_invoice_details(doc.name, expense_line_reasons=reasons)

    _environment, many = _install_draft_reason_doc(monkeypatch, line_count=101)
    too_many = {line.line_key: "reason" for line in many.expense_lines}
    with pytest.raises(ValidationError, match="100"):
        oa_entry.update_draft_invoice_details(many.name, expense_line_reasons=too_many)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"x" * 141: "reason"}, "\u6807\u8bc6.*\u8fc7\u957f"),
        ({"11111111-1111-4111-8111-000000000001": "x" * 501}, "500"),
        ({"11111111-1111-4111-8111-000000000001": {"nested": "bad"}}, "\u683c\u5f0f\u65e0\u6548"),
    ],
)
def test_update_draft_invoice_details_bounds_dict_keys_and_values(monkeypatch, payload, message):
    _install_draft_reason_doc(monkeypatch)
    with pytest.raises(ValidationError, match=message):
        oa_entry.update_draft_invoice_details("REQ-STRICT", expense_line_reasons=payload)



def test_update_draft_invoice_details_uses_current_read_and_permission_before_value_validation(monkeypatch):
    environment, doc = _install_draft_reason_doc(monkeypatch)
    calls = []

    def deny(current_doc, ptype, current=False):
        calls.append((current_doc.name, ptype, current))
        raise ValidationError("permission denied")

    monkeypatch.setattr(service, "_request_permission", deny)
    with pytest.raises(ValidationError, match="permission denied"):
        oa_entry.update_draft_invoice_details(
            doc.name,
            expense_line_reasons={
                doc.expense_lines[0].line_key: {"nested": "invalid"}
            },
        )
    assert environment.current_reads == [(service.REQUEST_DOCTYPE, doc.name)]
    assert calls == [(doc.name, "edit", True)]


def test_normalize_preserves_exact_seven_invoice_fields_and_compatibility_values():
    payload = {
        "source_invoice": "OIR-1",
        "invoice_category": "电子发票（普通发票）",
        "project_name": "文具印章",
        "issue_date": "2026-07-14",
        "invoice_number": "26322000005753891281",
        "amount_before_tax": "35.62",
        "tax_amount": "0.36",
        "total_amount": "35.98",
    }
    rows, total = oa_entry._normalize_expense_lines([payload])
    row = rows[0]
    assert total == 35.98
    assert {key: row[key] for key in (
        "source_invoice", "invoice_category", "project_name", "issue_date",
        "invoice_number", "amount_before_tax", "tax_amount", "total_amount",
    )} == {
        "source_invoice": "OIR-1",
        "invoice_category": "电子发票（普通发票）",
        "project_name": "文具印章",
        "issue_date": "2026-07-14",
        "invoice_number": "26322000005753891281",
        "amount_before_tax": 35.62,
        "tax_amount": 0.36,
        "total_amount": 35.98,
    }
    assert row["category"] == "电子发票（普通发票）"
    assert row["description"] == ""
    assert row["start_date"] == row["end_date"] == "2026-07-14"
    assert row["amount"] == 35.98
    assert UUID(row["line_key"]).version == 5


def test_group_expense_sources_aggregates_named_projects_and_keeps_blank_rows_independent():
    groups = oa_entry._group_expense_sources([
        {"line_key": "a", "project_name": " 项目甲 ", "expense_item": "交通费", "amount_before_tax": 100, "tax_amount": 6, "total_amount": 106},
        {"line_key": "b", "project_name": "项目甲", "expense_item": "交通费", "amount_before_tax": 50, "tax_amount": 3, "total_amount": 53},
        {"line_key": "c", "project_name": "", "expense_item": "", "amount_before_tax": None, "tax_amount": None, "total_amount": 10},
        {"line_key": "d", "project_name": "   ", "expense_item": "", "amount_before_tax": None, "tax_amount": None, "total_amount": 20},
    ])

    assert len(groups) == 3
    assert groups[0]["group_key"] == "project:项目甲"
    assert groups[0]["project_name"] == "项目甲"
    assert groups[0]["amount_before_tax"] == Decimal("150.00")
    assert groups[0]["tax_amount"] == Decimal("9.00")
    assert groups[0]["total_amount"] == Decimal("159.00")
    assert groups[0]["source_line_keys"] == ["a", "b"]
    assert groups[0]["needs_expense_item"] is False
    assert groups[1]["group_key"] != groups[2]["group_key"]
    assert groups[1]["amount_before_tax"] is None
    assert groups[2]["tax_amount"] is None


def test_group_expense_sources_flags_conflicting_expense_items():
    groups = oa_entry._group_expense_sources([
        {"line_key": "a", "project_name": "项目甲", "expense_item": "交通费", "total_amount": 10},
        {"line_key": "b", "project_name": "项目甲", "expense_item": "办公费", "total_amount": 20},
    ])

    assert groups[0]["expense_item"] == ""
    assert groups[0]["expense_items"] == ["交通费", "办公费"]
    assert groups[0]["needs_expense_item"] is True


def test_serialize_expense_line_maps_legacy_values_without_losing_zero_money():
    row = Row(
        source_consumption="OLD-1", line_key="line-1", start_date="2026-01-01",
        end_date="2026-01-01", category="办公费", amount=Decimal("12.00"),
        description="旧说明", attachment_count=0, invoice_status="",
        invoice_difference_reason="", invoice_category="", project_name="",
        issue_date=None, invoice_number="", amount_before_tax=Decimal("0.00"),
        tax_amount=Decimal("0.00"), total_amount=None, source_invoice=None,
        expense_item="办公用品", no_invoice_reason="旧单无发票",
    )
    result = oa_entry._serialize_expense_line(row)
    assert result["invoice_category"] == "办公费"
    assert result["project_name"] == "旧说明"
    assert result["issue_date"] == "2026-01-01"
    assert result["invoice_number"] == ""
    assert result["amount_before_tax"] == Decimal("0.00")
    assert result["tax_amount"] == Decimal("0.00")
    assert result["total_amount"] == Decimal("12.00")
    assert result["expense_item"] == "办公用品"
    assert result["no_invoice_reason"] == "旧单无发票"


def _push_record(name, *, status="已确认", total="35.98", request="", batch="BATCH-1", expense_description=None):
    return Row(
        doctype=service.RECORD_DOCTYPE,
        name=name,
        owner="alice@example.com",
        batch=batch,
        recognition_status=status,
        request=request,
        expense_line_key="",
        invoice_category="电子发票（普通发票）",
        project_name=f"项目-{name}",
        issue_date="2026-07-14",
        invoice_number=f"NO-{name}",
        amount_before_tax=Decimal("35.62"),
        tax_amount=Decimal("0.36"),
        total_amount=Decimal(total),
        expense_description=expense_description or f"费用说明-{name}",
        operation_log="[]",
        save=lambda ignore_permissions=False: None,
    )


def _install_invoice_push_environment(monkeypatch, records):
    environment = _install_request_environment(monkeypatch)
    locks = []

    @contextmanager
    def transaction_lock(category, *parts, **_kwargs):
        locks.append((category, *parts))
        yield object()

    def require_record(name, write=False, current=False):
        assert write is True
        return records[name]

    monkeypatch.setattr(service, "_transaction_lock", transaction_lock)
    monkeypatch.setattr(service, "_require_record", require_record)
    monkeypatch.setattr(service, "_save", lambda doc: doc.save(ignore_permissions=True))
    monkeypatch.setattr(
        service,
        "_apply_request_invoice_summary",
        lambda doc, save=False, current=False: (
            setattr(doc, "invoice_count", len([row for row in records.values() if row.request == doc.name]))
            or setattr(doc, "invoice_status", "已确认")
            or {"invoice_count": doc.invoice_count, "invoice_status": doc.invoice_status}
        ),
    )
    monkeypatch.setattr(
        oa_entry,
        "_summarize_doc",
        lambda doc: {
            "name": doc.name,
            "workflow_status": doc.workflow_status,
            "source_type": doc.source_type,
            "amount": doc.amount,
            "expense_lines": [oa_entry._serialize_expense_line(line) for line in doc.expense_lines],
            "project_groups": oa_entry._group_expense_sources([oa_entry._serialize_expense_line(line) for line in doc.expense_lines]),
            "operation_log": json.loads(doc.operation_log or "[]"),
        },
    )
    return environment, locks


def _draft_source_edit_request(environment, record, *, status=None):
    line_key = "11111111-1111-4111-8111-111111111111"
    record.request = "REQ-EDIT"
    record.expense_line_key = line_key
    request = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-EDIT",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": status or oa_entry.STATUS_DRAFT,
            "employee": "EMP-1",
            "department": "研发部",
            "supervisor": "",
            "asset_category": oa_entry.OTHER_ASSET,
            "subject": "发票报销",
            "source_type": oa_entry.SOURCE_INVOICE_PUSH,
            "amount": 35.98,
            "invoice_count": 1,
            "invoice_status": "已确认",
            "operation_log": "[]",
            "expense_lines": [
                Row(
                    source_invoice=record.name, line_key=line_key,
                    invoice_category=record.invoice_category, project_name=record.project_name,
                    expense_item="", no_invoice_reason="", issue_date=record.issue_date,
                    invoice_number=record.invoice_number, amount_before_tax=record.amount_before_tax,
                    tax_amount=record.tax_amount, total_amount=record.total_amount,
                    amount=record.total_amount, category=record.invoice_category,
                    description=record.expense_description,
                    expense_description=record.expense_description,
                    start_date=record.issue_date,
                    end_date=record.issue_date, attachment_count=1, invoice_status="已确认",
                    invoice_difference_reason="",
                )
            ],
            "steps": [],
        },
    )
    environment.committed[request.name] = request
    return request, line_key


def _source_edit_payload(line_key, **manual_overrides):
    manual = {
        "line_key": "",
        "project_name": "项目甲",
        "expense_account_level_1": "差旅费",
        "expense_account_level_2": "出差补助",
        "issue_date": "2026-07-22",
        "total_amount": "80.00",
        "description": "出差津贴",
    }
    manual.update(manual_overrides)
    return [
        {
            "line_key": line_key,
            "source_invoice": "INV-1",
            "project_name": "被篡改的项目",
            "expense_item": "被篡改的科目",
            "expense_description": "被篡改的说明",
        },
        manual,
    ]


def test_save_draft_expense_sources_updates_invoice_adds_and_deletes_manual_source(monkeypatch):
    records = {"INV-1": _push_record("INV-1", request="REQ-EDIT")}
    environment, locks = _install_invoice_push_environment(monkeypatch, records)
    request, line_key = _draft_source_edit_request(environment, records["INV-1"])
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    result = oa_entry.save_draft_expense_sources(request.name, _source_edit_payload(line_key))

    assert request.amount == pytest.approx(115.98)
    assert len(request.expense_lines) == 2
    manual = next(line for line in request.expense_lines if not line.source_invoice)
    assert _uuid4(manual.line_key)
    assert manual.project_name == "项目甲"
    assert manual.expense_account_level_1 == "差旅费"
    assert manual.expense_account_level_2 == "出差补助"
    assert manual.expense_item == "差旅费 / 出差补助"
    assert manual.description == "出差津贴"
    assert manual.no_invoice_reason == ""
    invoice_line = next(line for line in request.expense_lines if line.source_invoice)
    assert invoice_line.project_name == records["INV-1"].project_name
    assert invoice_line.expense_item == ""
    assert invoice_line.expense_description == records["INV-1"].expense_description
    assert len(result["project_groups"]) == 2
    manual_group = next(group for group in result["project_groups"] if group["project_name"] == "项目甲")
    assert manual_group["manual_source_count"] == 1
    assert manual_group["total_amount"] == Decimal("80.00")
    assert locks[:2] == [("request", request.name), ("record", "INV-1")]
    assert result["operation_log"][-1]["action"] == "编辑报销草稿"

    result = oa_entry.save_draft_expense_sources(
        request.name,
        [{"line_key": line_key, "source_invoice": "INV-1", "project_name": "项目甲", "expense_item": "交通费"}],
    )
    assert len(request.expense_lines) == 1
    assert request.amount == pytest.approx(35.98)
    assert result["project_groups"][0]["manual_source_count"] == 0


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"project_name": ""}, "项目名称"),
        ({"issue_date": ""}, "日期"),
        ({"total_amount": "0"}, "金额"),
        ({"description": ""}, "说明"),
        ({"expense_account_level_1": ""}, "一级费用科目"),
        ({"expense_account_level_2": ""}, "二级费用科目"),
    ],
)
def test_save_draft_expense_sources_validates_manual_required_fields(monkeypatch, override, message):
    records = {"INV-1": _push_record("INV-1", request="REQ-EDIT")}
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    request, line_key = _draft_source_edit_request(environment, records["INV-1"])
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    with pytest.raises(ValidationError, match=message):
        oa_entry.save_draft_expense_sources(request.name, _source_edit_payload(line_key, **override))


@pytest.mark.parametrize("status", [oa_entry.STATUS_PENDING, oa_entry.STATUS_COMPLETED])
def test_save_draft_expense_sources_rejects_non_draft(monkeypatch, status):
    records = {"INV-1": _push_record("INV-1", request="REQ-EDIT")}
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    request, line_key = _draft_source_edit_request(environment, records["INV-1"], status=status)
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    with pytest.raises(ValidationError, match="草稿"):
        oa_entry.save_draft_expense_sources(request.name, _source_edit_payload(line_key)[:1])


def test_save_draft_expense_sources_checks_edit_permission(monkeypatch):
    records = {"INV-1": _push_record("INV-1", request="REQ-EDIT")}
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    request, line_key = _draft_source_edit_request(environment, records["INV-1"])
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: frappe_stub.throw("没有编辑权限"))

    with pytest.raises(ValidationError, match="权限"):
        oa_entry.save_draft_expense_sources(request.name, _source_edit_payload(line_key)[:1])


def test_save_draft_expense_sources_cannot_remove_or_replace_invoice_lines(monkeypatch):
    records = {"INV-1": _push_record("INV-1", request="REQ-EDIT")}
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    request, line_key = _draft_source_edit_request(environment, records["INV-1"])
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    with pytest.raises(ValidationError, match="撤回发票"):
        oa_entry.save_draft_expense_sources(request.name, [])
    with pytest.raises(ValidationError, match="不属于"):
        oa_entry.save_draft_expense_sources(
            request.name,
            [{"line_key": "22222222-2222-4222-8222-222222222222", "source_invoice": "INV-X", "project_name": "项目甲", "expense_item": "交通费"}],
        )


def test_push_confirmed_invoices_creates_one_draft_with_one_exact_line_each(monkeypatch):
    records = {
        "INV-1": _push_record("INV-1", batch="BATCH-A"),
        "INV-2": _push_record("INV-2", total="106.00", batch="BATCH-B"),
    }
    environment, locks = _install_invoice_push_environment(monkeypatch, records)
    result = oa_entry.push_invoices_to_request(
        '["INV-2","INV-1"]',
        payment_info=json.dumps({"subject": "差旅发票报销", "department": "研发部"}, ensure_ascii=False),
    )
    request = environment.pending[result["name"]]
    assert request.workflow_status == oa_entry.STATUS_DRAFT
    assert request.source_type == oa_entry.SOURCE_INVOICE_PUSH
    assert len(request.expense_lines) == 2
    assert {line.source_invoice for line in request.expense_lines} == {"INV-1", "INV-2"}
    assert {line.project_name for line in request.expense_lines} == {"项目-INV-1", "项目-INV-2"}
    assert {line.expense_description for line in request.expense_lines} == {
        "费用说明-INV-1",
        "费用说明-INV-2",
    }
    assert request.amount == 141.98
    assert {record.request for record in records.values()} == {request.name}
    assert all(record.expense_line_key for record in records.values())
    assert locks[:2] == [("record", "INV-1"), ("record", "INV-2")]
    assert result["operation_log"][-1]["action"] == "发票下推"


def test_push_rejects_invoice_without_expense_description(monkeypatch):
    records = {
        "INV-1": _push_record("INV-1", expense_description=" ")
    }
    environment, _locks = _install_invoice_push_environment(
        monkeypatch, records
    )

    with pytest.raises(ValidationError, match="费用说明"):
        oa_entry.push_invoices_to_request(["INV-1"])

    assert environment.pending == {}


@pytest.mark.parametrize(
    ("status", "linked_request", "message"),
    [("待确认", "", "已确认"), ("已确认", "OA-OTHER", "已下推")],
)
def test_push_rejects_unconfirmed_or_already_linked_invoice(monkeypatch, status, linked_request, message):
    records = {"INV-1": _push_record("INV-1", status=status, request=linked_request)}
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    with pytest.raises(ValidationError, match=message):
        oa_entry.push_invoices_to_request(["INV-1"])
    assert environment.pending == {}


def test_request_and_push_withdrawals_are_reversible_and_audited(monkeypatch):
    records = {"INV-1": _push_record("INV-1", request="REQ-WITHDRAW")}
    environment, locks = _install_invoice_push_environment(monkeypatch, records)
    read_modes = []
    require_record = service._require_record
    def tracked_record(name, write=False, current=False):
        read_modes.append(current)
        return require_record(name, write=write, current=current)
    monkeypatch.setattr(service, "_require_record", tracked_record)
    line_key = "11111111-1111-4111-8111-111111111111"
    records["INV-1"].expense_line_key = line_key
    request = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-WITHDRAW",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "employee": "EMP-1",
            "department": "研发部",
            "supervisor": "",
            "asset_category": oa_entry.OTHER_ASSET,
            "subject": "报销",
            "source_type": oa_entry.SOURCE_INVOICE_PUSH,
            "amount": 35.98,
            "paid_by": "",
            "paid_on": None,
            "operation_log": "[]",
            "expense_lines": [
                Row(
                    source_invoice="INV-1", line_key=line_key, total_amount=35.98,
                    amount=35.98, category="电子发票（普通发票）", project_name="项目-INV-1",
                    description="项目-INV-1", invoice_category="电子发票（普通发票）",
                    issue_date="2026-07-14", invoice_number="NO-INV-1",
                    amount_before_tax=35.62, tax_amount=0.36, start_date="2026-07-14",
                    end_date="2026-07-14", attachment_count=1, invoice_status="已确认",
                    invoice_difference_reason="",
                )
            ],
            "steps": [Row(step_index=1, label="财务审核", mode="approve", approvers="[]", status=oa_entry.STATUS_PENDING, approved_by="[]")],
            "current_step_index": 1,
            "current_step_label": "财务审核",
        },
    )
    environment.committed[request.name] = request
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    result = oa_entry.withdraw_invoice_push(["INV-1"], note="选错发票")
    assert request.workflow_status == oa_entry.STATUS_DRAFT
    assert request.expense_lines == [] and request.amount == 0
    assert records["INV-1"].request == "" and records["INV-1"].expense_line_key == ""
    assert [event["action"] for event in result["operation_log"]][-2:] == ["撤回申请", "撤回发票下推"]
    assert locks[:2] == [("request", request.name), ("record", "INV-1")]
    assert read_modes == [False, True]


def test_withdraw_one_invoice_keeps_other_source_in_same_project_group(monkeypatch):
    records = {
        "INV-1": _push_record("INV-1", request="REQ-GROUP", total="35.98"),
        "INV-2": _push_record("INV-2", request="REQ-GROUP", total="106.00"),
    }
    environment, _locks = _install_invoice_push_environment(monkeypatch, records)
    keys = {
        "INV-1": "11111111-1111-4111-8111-111111111111",
        "INV-2": "22222222-2222-4222-8222-222222222222",
    }
    for name, record in records.items():
        record.expense_line_key = keys[name]
        record.project_name = "项目甲"
    request = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-GROUP",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "employee": "EMP-1",
            "department": "研发部",
            "supervisor": "",
            "asset_category": oa_entry.OTHER_ASSET,
            "source_type": oa_entry.SOURCE_INVOICE_PUSH,
            "amount": 141.98,
            "operation_log": "[]",
            "expense_lines": [
                Row(
                    source_invoice=name, line_key=keys[name], invoice_category=record.invoice_category,
                    project_name="项目甲", expense_item="交通费", no_invoice_reason="",
                    issue_date=record.issue_date, invoice_number=record.invoice_number,
                    amount_before_tax=record.amount_before_tax, tax_amount=record.tax_amount,
                    total_amount=record.total_amount, amount=record.total_amount,
                    category=record.invoice_category, description="项目甲",
                    start_date=record.issue_date, end_date=record.issue_date,
                    attachment_count=1, invoice_status="已确认", invoice_difference_reason="",
                )
                for name, record in records.items()
            ],
            "steps": [],
        },
    )
    environment.committed[request.name] = request
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)

    result = oa_entry.withdraw_invoice_push(["INV-1"], note="只撤回一张")

    assert [line.source_invoice for line in request.expense_lines] == ["INV-2"]
    assert request.amount == pytest.approx(106.00)
    assert len(result["project_groups"]) == 1
    assert result["project_groups"][0]["source_line_keys"] == [keys["INV-2"]]
    assert records["INV-1"].request == ""
    assert records["INV-2"].request == request.name


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ({"line_key": "a", "source_invoice": "INV-1", "project_name": "", "expense_item": "travel", "expense_description": "provided", "total_amount": 10}, "\u9879\u76ee\u540d\u79f0"),
        ({"line_key": "a", "source_invoice": "INV-1", "project_name": "project-a", "expense_item": "", "expense_description": "", "total_amount": 10}, "\u8d39\u7528\u8bf4\u660e"),
    ],
)
def test_validate_expense_project_groups_blocks_incomplete_submission(line, message):
    doc = Row(request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, expense_lines=[Row(line)])
    with pytest.raises(ValidationError, match=message):
        oa_entry._validate_expense_project_groups(doc)


def test_paid_request_requires_finance_payment_withdrawal(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    request = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-PAID",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PAID,
            "paid_by": "finance@example.com",
            "paid_on": "2026-07-21 10:00:00",
            "operation_log": "[]",
            "expense_lines": [],
            "steps": [],
        },
    )
    environment.committed[request.name] = request
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda doc, authorized_expense_lines=None: {"workflow_status": doc.workflow_status, "operation_log": json.loads(doc.operation_log or "[]")})
    with pytest.raises(ValidationError, match="财务"):
        oa_entry.withdraw_request(request.name)
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    result = oa_entry.withdraw_payment(request.name, "付款信息有误")
    assert result["workflow_status"] == oa_entry.STATUS_COMPLETED
    assert request.paid_by == "" and request.paid_on is None
    assert result["operation_log"][-1]["action"] == "撤回付款"


# --- Expense reporting and audit views ---

def _report_request(
    name,
    *,
    owner="alice@example.com",
    employee="EMP-1",
    employee_name="Alice",
    department="研发部",
    workflow_status=None,
    source_type=None,
    creation="2026-07-20 09:00:00",
    expense_lines=None,
    steps=None,
    operation_log=None,
):
    return Row(
        name=name,
        owner=owner,
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        employee=employee,
        employee_name=employee_name,
        department=department,
        supervisor="",
        company="Rayher",
        subject=f"报销-{name}",
        doc_type="非固定资产",
        urgency="一般",
        from_date=None,
        to_date=None,
        amount=sum(Decimal(str(line.get("total_amount", 0))) for line in (expense_lines or [])),
        asset_category=oa_entry.OTHER_ASSET,
        source_type=source_type or oa_entry.SOURCE_MANUAL,
        source_summary="",
        payment_type="付款申请",
        payment_method="银行转账",
        paid_by="finance@example.com" if workflow_status == oa_entry.STATUS_PAID else "",
        paid_on=creation if workflow_status == oa_entry.STATUS_PAID else None,
        reason="",
        workflow_status=workflow_status or oa_entry.STATUS_DRAFT,
        current_step_index=0,
        current_step_label="",
        invoice_count=len([line for line in (expense_lines or []) if line.get("source_invoice")]),
        invoice_status="已确认" if expense_lines else "无发票",
        no_invoice_reason="",
        operation_log=json.dumps(operation_log or [], ensure_ascii=False),
        expense_lines=[Row(line) for line in (expense_lines or [])],
        steps=[Row(step) for step in (steps or [])],
        creation=creation,
        modified=creation,
    )


def test_get_options_exposes_current_applicant_and_canonical_payment_types(monkeypatch):
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Employee"])
    monkeypatch.setattr(
        oa_entry,
        "_employee_context",
        lambda user=None: {"employee": "EMP-1", "employee_name": "Alice", "department": "研发部", "supervisor": "Manager"},
    )

    result = oa_entry.get_options()

    assert result["payment_types"] == ["支付个人", "对公支付"]
    assert "总经办" in result["departments"]
    assert "总经理室" not in result["departments"]
    assert result["current_applicant"] == {
        "employee": "EMP-1",
        "employee_name": "Alice",
        "user": "alice@example.com",
        "department": "研发部",
        "supervisor": "Manager",
    }


def test_summary_exposes_procurement_payment_source_for_draft_hydration(monkeypatch):
    doc = _report_request("PAY-DRAFT")
    doc.request_type = oa_entry.REQUEST_PROCUREMENT_PAYMENT
    doc.source_request = "PROC-SOURCE"
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda _doc: {
            "invoice_count": 0, "invoice_status": "none", "invoice_search_text": "",
            "invoice_categories": [], "invoice_project_names": [], "invoice_numbers": [],
        },
    )

    result = oa_entry._summarize_doc(doc)

    assert result["source_request"] == "PROC-SOURCE"


def test_legacy_personal_payment_type_is_displayed_canonically(monkeypatch):
    doc = _report_request("REQ-LEGACY")
    doc.payment_type = "付款申请"
    doc.department = "总经理室"
    monkeypatch.setattr(
        service,
        "request_invoice_summary",
        lambda _doc: {
            "invoice_count": 0, "invoice_status": "无发票", "invoice_search_text": "",
            "invoice_categories": [], "invoice_project_names": [], "invoice_numbers": [],
        },
    )

    result = oa_entry._summarize_doc(doc)

    assert result["payment_type"] == "支付个人"
    assert result["department"] == "总经办"


def _install_report_requests(monkeypatch, docs):
    def matches(doc, filters):
        for key, expected in (filters or {}).items():
            actual = getattr(doc, key, None)
            if isinstance(expected, list):
                operator, value = expected
                if operator == "in" and actual not in value:
                    return False
                if operator == "!=" and actual == value:
                    return False
                if operator == "between" and not (str(value[0]) <= str(actual) <= str(value[1])):
                    return False
            elif actual != expected:
                return False
        return True

    def get_all(doctype, filters=None, fields=None, order_by=None, limit_page_length=None):
        if doctype == "Employee":
            return [Row(name="EMP-1", employee_name="Alice")]
        assert doctype == "OA Approval Request"
        rows = [doc for doc in docs.values() if matches(doc, filters)]
        rows.sort(key=lambda doc: str(doc.modified), reverse=True)
        return [Row(name=doc.name) for doc in rows[: int(limit_page_length or len(rows))]]

    # Execute the generated WHERE/ORDER/LIMIT in a SQL engine, not a Python
    # implementation of the permission rule. MariaDB syntax is also checked by
    # the live read-only acceptance run.
    import sqlite3
    import re
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.create_function("JSON_VALID", 1, lambda value: 1 if value else 0)
    def json_contains(value, candidate):
        items, wanted = json.loads(value), json.loads(candidate)
        if isinstance(wanted, dict):
            return int(any(isinstance(item, dict) and all(item.get(k) == v for k, v in wanted.items()) for item in items))
        return int(wanted in items)

    connection.create_function("JSON_CONTAINS", 2, json_contains)
    fields = ["name", "request_type", "workflow_status", "owner", "employee", "purchaser_user", "modified", "current_step_index", "copied_to"]
    connection.execute("CREATE TABLE `tabOA Approval Request` (" + ",".join(fields) + ")")
    connection.execute("CREATE TABLE `tabOA Approval Step` (parent,parenttype,parentfield,step_index,approvers,approved_by,action_by)")
    for doc in docs.values():
        connection.execute("INSERT INTO `tabOA Approval Request` VALUES (?,?,?,?,?,?,?,?,?)", [getattr(doc, key, None) for key in fields])
        for step in getattr(doc, "steps", []):
            connection.execute("INSERT INTO `tabOA Approval Step` VALUES (?,?,?,?,?,?,?)", [doc.name, "OA Approval Request", "steps", step.step_index, step.approvers, getattr(step, "approved_by", "[]"), getattr(step, "action_by", "")])
    def sql(query, values=None, as_dict=False):
        query = re.sub(r"%\((\w+)\)s", r":\1", query)
        return [Row(dict(row)) for row in connection.execute(query.replace("%s", "?"), values or {})]
    monkeypatch.setattr(frappe_stub, "db", types.SimpleNamespace(sql=sql, escape=lambda value: "'" + str(value).replace("'", "''") + "'", get_value=lambda *args, **kwargs: "Alice"), raising=False)
    monkeypatch.setattr(frappe_stub, "get_all", get_all, raising=False)
    monkeypatch.setattr(oa_entry, "_load_request", lambda name, current=False: docs[name])
    monkeypatch.setattr(
        oa_entry,
        "_employee_context",
        lambda user=None: {
            "employee": "EMP-1",
            "employee_name": "Alice",
            "department": "研发部",
            "supervisor": "",
        },
    )


def test_list_requests_includes_completed_procurement_for_purchaser(monkeypatch):
    doc = _report_request(
        "PROC-BUYER", owner="bob@example.com", employee="EMP-2", employee_name="Bob"
    )
    doc.request_type = oa_entry.REQUEST_PROCUREMENT
    doc.purchaser_user = "alice@example.com"
    doc.business_status = ""
    doc.workflow_status = oa_entry.STATUS_COMPLETED
    docs = {doc.name: doc}
    _install_report_requests(monkeypatch, docs)
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Employee"])
    monkeypatch.setattr(
        oa_entry, "_summarize_doc",
        lambda item, authorized_expense_lines=None: {"name": item.name},
    )

    result = oa_entry.list_requests(
        view="all", limit=100, request_type=oa_entry.REQUEST_PROCUREMENT
    )

    assert result == [{"name": "PROC-BUYER"}]


def test_list_requests_supports_exact_name_without_bypassing_visibility(monkeypatch):
    docs = {
        "REQ-ALICE": _report_request("REQ-ALICE"),
        "REQ-BOB": _report_request(
            "REQ-BOB", owner="bob@example.com", employee="EMP-2", employee_name="Bob", department="研发部"
        ),
    }
    _install_report_requests(monkeypatch, docs)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda doc, authorized_expense_lines=None: {"name": doc.name})

    result = oa_entry.list_requests(
        view="all", limit=1, request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, name="REQ-ALICE"
    )
    assert result == [{"name": "REQ-ALICE"}]

    result = oa_entry.list_requests(
        view="all", limit=1, request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, name="REQ-BOB"
    )
    assert result == []

    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    result = oa_entry.list_requests(
        view="all", limit=1, request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, name="REQ-BOB"
    )
    # 修复（2026-09-24）：财务不再看别人未提交的草稿；提交后照常能看。
    assert result == []
    docs["REQ-BOB"].workflow_status = oa_entry.STATUS_PENDING
    _install_report_requests(monkeypatch, docs)
    result = oa_entry.list_requests(
        view="all", limit=1, request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, name="REQ-BOB"
    )
    assert result == [{"name": "REQ-BOB"}]


def test_expense_statistics_filters_seven_field_lines_and_scopes_users(monkeypatch):
    lines = [
        {
            "line_key": "line-1",
            "source_invoice": "INV-1",
            "invoice_category": "电子发票（普通发票）",
            "project_name": "文具印章",
            "expense_item": "交通费",
            "issue_date": "2026-07-14",
            "invoice_number": "NO-1",
            "amount_before_tax": Decimal("35.62"),
            "tax_amount": Decimal("0.36"),
            "total_amount": Decimal("35.98"),
            "amount": Decimal("35.98"),
        },
        {
            "line_key": "line-2",
            "source_invoice": "INV-2",
            "invoice_category": "电子发票（普通发票）",
            "project_name": "文具印章",
            "expense_item": "交通费",
            "issue_date": "2026-07-15",
            "invoice_number": "NO-2",
            "amount_before_tax": Decimal("100.00"),
            "tax_amount": Decimal("6.00"),
            "total_amount": Decimal("106.00"),
            "amount": Decimal("106.00"),
        },
    ]
    docs = {
        "REQ-PAID": _report_request(
            "REQ-PAID",
            workflow_status=oa_entry.STATUS_PAID,
            source_type=oa_entry.SOURCE_INVOICE_PUSH,
            expense_lines=lines,
        ),
        "REQ-BOB": _report_request(
            "REQ-BOB",
            owner="bob@example.com",
            employee="EMP-2",
            employee_name="Bob",
            department="研发部",
            expense_lines=[dict(lines[0], source_invoice="INV-BOB")],
        ),
    }
    _install_report_requests(monkeypatch, docs)

    result = oa_entry.get_expense_statistics(
        view="all",
        from_date="2026-07-01",
        to_date="2026-07-31",
        department="研发部",
        employee="EMP-1",
        invoice_category="电子发票（普通发票）",
        project_name="文具印章",
        workflow_status=oa_entry.STATUS_PAID,
        payment_status="已付款",
        source_type=oa_entry.SOURCE_INVOICE_PUSH,
    )
    assert set(result) == {"totals", "rows", "truncated"}
    assert result["truncated"] is False
    assert result["totals"] == {
        "request_count": 1,
        "invoice_count": 2,
        "amount_before_tax": Decimal("135.62"),
        "tax_amount": Decimal("6.36"),
        "total_amount": Decimal("141.98"),
        "paid_amount": Decimal("141.98"),
        "unpaid_amount": Decimal("0"),
    }
    assert {row["request_name"] for row in result["rows"]} == {"REQ-PAID"}
    assert len(result["rows"]) == 1
    assert result["rows"][0]["project_name"] == "文具印章"
    assert result["rows"][0]["expense_item"] == "交通费"
    assert result["rows"][0]["invoice_count"] == 2
    assert result["rows"][0]["total_amount"] == Decimal("141.98")

    scoped = oa_entry.get_expense_statistics(view="all")
    assert {row["request_name"] for row in scoped["rows"]} == {"REQ-PAID"}
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    privileged = oa_entry.get_expense_statistics(view="all")
    assert {row["request_name"] for row in privileged["rows"]} == {"REQ-PAID", "REQ-BOB"}


def test_expense_statistics_includes_manual_no_invoice_lines_and_filters_expense_item(monkeypatch):
    docs = {
        "REQ-MIXED": _report_request(
            "REQ-MIXED",
            expense_lines=[
                {
                    "line_key": "invoice-line",
                    "source_invoice": "INV-1",
                    "invoice_category": "电子发票（普通发票）",
                    "project_name": "项目甲",
                    "expense_item": "交通费",
                    "issue_date": "2026-07-14",
                    "invoice_number": "NO-1",
                    "amount_before_tax": Decimal("35.62"),
                    "tax_amount": Decimal("0.36"),
                    "total_amount": Decimal("35.98"),
                },
                {
                    "line_key": "manual-line",
                    "source_invoice": None,
                    "invoice_category": "",
                    "project_name": "项目乙",
                    "expense_item": "差旅补贴",
                    "issue_date": "2026-07-15",
                    "invoice_number": "",
                    "amount_before_tax": None,
                    "tax_amount": None,
                    "total_amount": Decimal("80.00"),
                    "description": "出差津贴",
                    "no_invoice_reason": "公司制度规定",
                },
            ],
        ),
    }
    _install_report_requests(monkeypatch, docs)
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Accounts User"])

    result = oa_entry.get_expense_statistics(view="all")

    assert [row["project_name"] for row in result["rows"]] == ["项目甲", "项目乙"]
    assert result["totals"]["invoice_count"] == 1
    assert result["totals"]["total_amount"] == Decimal("115.98")

    manual = oa_entry.get_expense_statistics(view="all", expense_item="差旅补贴")

    assert len(manual["rows"]) == 1
    assert manual["rows"][0]["project_name"] == "项目乙"
    assert manual["rows"][0]["expense_item"] == "差旅补贴"
    assert manual["rows"][0]["invoice_count"] == 0
    assert manual["rows"][0]["total_amount"] == Decimal("80.00")


def test_approval_records_merge_steps_and_operation_events_with_permissions(monkeypatch):
    steps = [
        {
            "step_index": 1,
            "label": "财务审核",
            "mode": "approve",
            "approvers": json.dumps(["finance@example.com"]),
            "status": oa_entry.STATUS_APPROVED,
            "approved_by": json.dumps(["finance@example.com"]),
            "action_by": "finance@example.com",
            "acted_on": "2026-07-20 10:00:00",
            "note": "同意",
        },
        {
            "step_index": 2,
            "label": "付款",
            "mode": "handle",
            "approvers": json.dumps(["cashier@example.com"]),
            "status": oa_entry.STATUS_WAIT_HANDLE,
            "approved_by": "[]",
            "action_by": "",
            "acted_on": "",
            "note": "",
        },
    ]
    events = [
        {
            "action": "撤回付款",
            "actor": "finance@example.com",
            "acted_on": "2026-07-21 10:00:00",
            "from_status": oa_entry.STATUS_PAID,
            "to_status": oa_entry.STATUS_COMPLETED,
            "note": "付款信息有误",
        }
    ]
    docs = {
        "REQ-AUDIT": _report_request(
            "REQ-AUDIT",
            workflow_status=oa_entry.STATUS_COMPLETED,
            steps=steps,
            operation_log=events,
        ),
        "REQ-BOB": _report_request(
            "REQ-BOB", owner="bob@example.com", employee="EMP-2", employee_name="Bob", steps=steps
        ),
    }
    _install_report_requests(monkeypatch, docs)

    result = oa_entry.list_expense_approval_records(
        view="all",
        request_keyword="REQ-AUDIT",
        employee="EMP-1",
        department="研发部",
        approver="finance@example.com",
        action="撤回付款",
        workflow_status=oa_entry.STATUS_COMPLETED,
        from_date="2026-07-01",
        to_date="2026-07-31",
    )
    assert set(result) == {"records", "truncated"}
    assert result["truncated"] is False
    assert len(result["records"]) == 1
    record = result["records"][0]
    assert record["request_name"] == "REQ-AUDIT"
    assert record["event_type"] == "操作日志"
    assert record["action"] == "撤回付款"
    assert record["actor"] == "finance@example.com"
    assert record["acted_on"] == "2026-07-21 10:00:00"
    assert record["note"] == "付款信息有误"

    unfiltered = oa_entry.list_expense_approval_records(view="all")
    assert {record["request_name"] for record in unfiltered["records"]} == {"REQ-AUDIT"}
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    privileged = oa_entry.list_expense_approval_records(view="all")
    assert {record["request_name"] for record in privileged["records"]} == {"REQ-AUDIT", "REQ-BOB"}



def test_expense_normalization_derives_blank_total_before_request_sum():
    rows, total = oa_entry._normalize_expense_lines(
        [
            {
                "source_invoice": "INV-DERIVED",
                "project_name": "project-a",
                "amount_before_tax": "690.84",
                "tax_amount": "20.73",
                "total_amount": None,
            }
        ]
    )
    assert Decimal(str(rows[0]["total_amount"])) == Decimal("711.57")
    assert Decimal(str(rows[0]["amount"])) == Decimal("711.57")
    assert Decimal(str(total)) == Decimal("711.57")


def test_employee_submission_allows_blank_expense_item_but_requires_description():
    valid = Row(
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        expense_lines=[
            Row(
                line_key="line-a",
                source_invoice="INV-1",
                project_name="project-a",
                expense_item="",
                expense_description="client visit",
                total_amount=10,
            )
        ],
    )
    oa_entry._validate_expense_project_groups(valid)
    valid.expense_lines[0].expense_description = ""
    valid.expense_lines[0].description = ""
    with pytest.raises(ValidationError, match="\u8d39\u7528\u8bf4\u660e"):
        oa_entry._validate_expense_project_groups(valid)


def test_canonical_manual_expense_does_not_require_legacy_no_invoice_reason(monkeypatch):
    request = Row(
        name="REQ-MANUAL",
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        no_invoice_reason="",
        expense_lines=[
            Row(
                line_key="line-manual",
                source_invoice="",
                project_name="project-a",
                expense_account_level_1="差旅费",
                expense_account_level_2="出差补助",
                expense_description="出差津贴",
                amount=80,
            )
        ],
    )
    monkeypatch.setattr(service, "_request_invoice_records", lambda *_args, **_kwargs: [])

    service.validate_request_invoices(request, submitting=True)


def test_invoice_expense_context_backfill_only_copies_nonblank_linked_descriptions(monkeypatch):
    updates = []
    fake_db = Row(
        table_exists=lambda *_args, **_kwargs: True,
        sql=lambda *_args, **_kwargs: [
            Row(name="INV-1", expense_description="客户拜访"),
            Row(name="INV-2", expense_description="   "),
        ],
        set_value=lambda doctype, name, field, value, **_kwargs: updates.append(
            (doctype, name, field, value)
        ),
    )
    fake_frappe = Row(
        db=fake_db,
        reload_doc=lambda *_args, **_kwargs: None,
        logger=lambda *_args, **_kwargs: Row(info=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(backfill_invoice_expense_context, "frappe", fake_frappe)

    backfill_invoice_expense_context.execute()

    assert updates == [
        ("OA Invoice Record", "INV-1", "expense_description", "客户拜访")
    ]


def test_expense_normalization_keeps_new_and_legacy_description_coherent():
    rows, _total = oa_entry._normalize_expense_lines(
        [
            {
                "source_invoice": "INV-1",
                "project_name": "project-a",
                "expense_item": "",
                "expense_description": "client visit",
                "total_amount": 10,
            }
        ]
    )
    assert rows[0]["expense_description"] == "client visit"
    assert rows[0]["description"] == "client visit"


def test_finance_classification_updates_only_expense_accounts(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    line = Row(
        line_key="11111111-1111-4111-8111-111111111111",
        source_invoice="INV-1",
        project_name="project-a",
        expense_item="",
        expense_description="client visit",
        description="client visit",
        total_amount=10,
        amount=10,
    )
    step = Row(
        step_index=1,
        step_key="step-finance",
        label="\u8d22\u52a1\u5ba1\u6838\uff1afinance",
        mode="approve",
        approvers='["finance@example.com"]',
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-FINANCE",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": 1,
            "current_step_label": step.label,
            "expense_lines": [line],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "finance@example.com"
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["finance@example.com"])

    oa_entry.save_finance_expense_items(
        doc.name,
        [
            {
                "line_key": line.line_key,
                "expense_account_level_1": "差旅费",
                "expense_account_level_2": "住宿费",
            }
        ],
    )
    assert line.expense_account_level_1 == "差旅费"
    assert line.expense_account_level_2 == "住宿费"
    assert line.expense_item == "差旅费 / 住宿费"
    assert line.total_amount == 10
    assert line.expense_description == "client visit"
    with pytest.raises(ValidationError):
        oa_entry.save_finance_expense_items(
            doc.name,
            [
                {
                    "line_key": line.line_key,
                    "expense_account_level_1": "办公费",
                    "expense_account_level_2": "",
                    "total_amount": 999,
                }
            ],
        )


def test_finance_approval_is_blocked_until_all_expense_items_are_classified(monkeypatch):
    line = Row(
        line_key="line-a",
        expense_item="",
        expense_account_level_1="",
        expense_account_level_2="",
        expense_description="client visit",
    )
    step = Row(label="\u8d22\u52a1\u5ba1\u6838\uff1afinance", mode="approve")
    doc = Row(request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, expense_lines=[line])
    with pytest.raises(ValidationError, match="\u8d39\u7528\u79d1\u76ee"):
        oa_entry._validate_finance_classification(doc, step)
    line.expense_account_level_1 = "办公费"
    line.expense_item = "办公费"
    oa_entry._validate_finance_classification(doc, step)


def test_finance_classification_rejects_mismatched_account_levels(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    line = Row(
        line_key="11111111-1111-4111-8111-111111111111",
        project_name="project-a",
        expense_account_level_1="",
        expense_account_level_2="",
        expense_item="",
    )
    step = Row(
        step_index=1,
        label="\u8d22\u52a1\u5ba1\u6838\uff1afinance",
        mode="approve",
        approvers='["finance@example.com"]',
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-FINANCE-INVALID",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": 1,
            "expense_lines": [line],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "finance@example.com"
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["finance@example.com"])

    with pytest.raises(ValidationError, match="不匹配"):
        oa_entry.save_finance_expense_items(
            doc.name,
            [
                {
                    "line_key": line.line_key,
                    "expense_account_level_1": "差旅费",
                    "expense_account_level_2": "餐饮费",
                }
            ],
        )


def test_action_request_enforces_finance_classification_before_approve(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    line = Row(line_key="line-a", project_name="project-a", expense_item="", expense_description="client visit")
    step = Row(
        step_index=1,
        step_key="step-finance",
        label="\u8d22\u52a1\u5ba1\u6838\uff1afinance",
        mode="approve",
        approvers='["finance@example.com"]',
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
        action_by="",
        acted_on=None,
        note="",
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-FINANCE-BLOCK",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": 1,
            "current_step_label": step.label,
            "expense_lines": [line],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "finance@example.com"
    frappe_stub.get_roles = lambda user=None: ["Accounts User"]
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["finance@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"finance@example.com"})
    with pytest.raises(ValidationError, match="\u8d39\u7528\u79d1\u76ee"):
        oa_entry.action_request(doc.name, "approve")
    assert doc.workflow_status == oa_entry.STATUS_PENDING


def test_request_capabilities_are_server_authoritative_for_finance(monkeypatch):
    step = Row(label="\u8d22\u52a1\u5ba1\u6838\uff1afinance", mode="approve")
    doc = Row(
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        workflow_status=oa_entry.STATUS_PENDING,
        expense_lines=[Row(expense_item="")],
    )
    monkeypatch.setattr(oa_entry, "_current_step", lambda _doc: step)
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda _doc, user=None: True)
    monkeypatch.setattr(oa_entry, "_is_finance_user", lambda user=None: True)
    capabilities = oa_entry._request_capabilities(doc)
    assert capabilities == {
        "can_approve": False,
        "can_reject": True,
        "can_add_sign": True,
        "can_add_sign_after": True,
        "can_edit_expense_items": True,
        "classification_ready": False,
        "is_override_actor": False,
        "action_scope": "assigned",
    }



def test_procurement_assignee_can_both_approve_and_reject(monkeypatch):
    step = Row(label="PMC：演示员工178", mode="approve")
    doc = Row(
        request_type=oa_entry.REQUEST_PROCUREMENT,
        workflow_status=oa_entry.STATUS_PENDING,
    )
    monkeypatch.setattr(oa_entry, "_current_step", lambda _doc: step)
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda _doc, user=None: True)
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: False)

    capabilities = oa_entry._request_capabilities(doc, "person076@staff.example.invalid")

    assert capabilities["can_approve"] is True
    assert capabilities["can_reject"] is True
    assert capabilities["action_scope"] == "assigned"


def test_new_route_steps_receive_stable_identity_and_origin():
    environment = RequestEnvironment()
    doc = RequestDocument(environment, {"steps": []})
    oa_entry._append_steps(
        doc,
        [
            {
                "step_index": 1,
                "label": "finance",
                "mode": "approve",
                "approvers": ["finance@example.com"],
                "status": oa_entry.STATUS_PENDING,
            }
        ],
    )
    step = doc.steps[0]
    assert _uuid4(step.step_key)
    assert step.origin == "base"
    serialized = oa_entry._serialize_doc_step(step)
    assert serialized["step_key"] == step.step_key
    assert serialized["origin"] == "base"


def test_supplemental_attachment_content_validation_is_bounded_and_signature_based():
    validator = oa_entry.expense_attachments.validate_attachment_content
    pdf = validator("receipt.pdf", b"%PDF-1.7\nbody")
    jpg = validator("photo.jpg", b"\xff\xd8\xffbody")
    png = validator("scan.png", b"\x89PNG\r\n\x1a\nbody")
    assert pdf["mime_type"] == "application/pdf"
    assert jpg["mime_type"] == "image/jpeg"
    assert png["mime_type"] == "image/png"
    assert len(pdf["sha256"]) == 64
    with pytest.raises(ValidationError):
        validator("receipt.pdf", b"not-a-pdf")
    with pytest.raises(ValidationError):
        validator("receipt.exe", b"MZ")
    with pytest.raises(ValidationError):
        validator("too-large.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024))


def test_supplemental_attachment_capacity_is_ten_per_line():
    oa_entry.expense_attachments.validate_capacity(9)
    with pytest.raises(ValidationError, match="10"):
        oa_entry.expense_attachments.validate_capacity(10)


def test_supplemental_attachment_requires_request_line_membership():
    request = Row(expense_lines=[Row(line_key="line-a")])
    assert oa_entry.expense_attachments.validate_line_membership(request, "line-a").line_key == "line-a"
    with pytest.raises(ValidationError):
        oa_entry.expense_attachments.validate_line_membership(request, "line-b")


def test_supplemental_attachment_requires_private_unclaimed_owner_file(monkeypatch):
    valid = Row(
        owner="alice@example.com",
        is_private=1,
        attached_to_doctype="",
        attached_to_name="",
        file_url="/private/files/receipt.pdf",
    )
    assert oa_entry.expense_attachments.validate_file_registration(valid, "alice@example.com") is valid
    for override in (
        {"is_private": 0},
        {"owner": "mallory@example.com"},
        {"attached_to_doctype": "Other"},
        {"file_url": "/files/public.pdf"},
    ):
        invalid = Row(valid)
        invalid.update(override)
        with pytest.raises(ValidationError):
            oa_entry.expense_attachments.validate_file_registration(invalid, "alice@example.com")


def test_expense_attachment_api_contract_delegates_to_hardened_service(monkeypatch):
    calls = []
    monkeypatch.setattr(oa_entry.expense_attachments, "register_attachment", lambda name, line_key, file_url: calls.append(("register", name, line_key, file_url)) or {"name": "ATT-1"}, raising=False)
    monkeypatch.setattr(oa_entry.expense_attachments, "delete_attachment", lambda name, attachment: calls.append(("delete", name, attachment)) or {"deleted": attachment}, raising=False)
    monkeypatch.setattr(oa_entry.expense_attachments, "preview_attachment", lambda attachment: calls.append(("preview", attachment)) or {"token": "x"}, raising=False)
    assert oa_entry.upload_expense_attachment("REQ-1", "line-a", "/private/files/a.pdf")["name"] == "ATT-1"
    assert oa_entry.delete_expense_attachment("REQ-1", "ATT-1")["deleted"] == "ATT-1"
    assert oa_entry.preview_expense_attachment("ATT-1")["token"] == "x"
    assert calls == [
        ("register", "REQ-1", "line-a", "/private/files/a.pdf"),
        ("delete", "REQ-1", "ATT-1"),
        ("preview", "ATT-1"),
    ]


def test_request_expense_lines_include_supplemental_attachment_metadata(monkeypatch):
    doc = Row(name="REQ-1")
    lines = [
        {
            "line_key": "line-a",
            "source_invoice": "INV-1",
            "attachment_count": 0,
        }
    ]
    monkeypatch.setattr(
        oa_entry.expense_attachments,
        "list_attachments",
        lambda request_name, current=False: [
            {"name": "ATT-1", "expense_line_key": "line-a", "original_filename": "receipt.pdf"}
        ],
    )
    monkeypatch.setattr(
        oa_entry.invoice_supplemental_attachments,
        "list_attachments",
        lambda invoice_name, current=False: [
            {
                "name": "ISA-1",
                "invoice_record": invoice_name,
                "original_filename": "itinerary.pdf",
            }
        ],
    )
    result = oa_entry._with_expense_attachments(doc, lines)
    assert result[0]["attachment_count"] == 2
    assert result[0]["attachments"][0]["name"] == "ATT-1"
    assert result[0]["attachments"][0]["attachment_source"] == "request_line"
    assert result[0]["attachments"][1]["name"] == "ISA-1"
    assert result[0]["attachments"][1]["attachment_source"] == "invoice"
    assert result[0]["supplemental_attachments"][0]["name"] == "ISA-1"


def _dynamic_workflow_doc(steps, current_index):
    environment = RequestEnvironment()
    return RequestDocument(
        environment,
        {
            "name": "REQ-DYNAMIC",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": current_index,
            "current_step_label": steps[current_index - 1].label,
            "steps": steps,
            "expense_lines": [],
            "operation_log": "[]",
        },
    )


def _workflow_step(index, key, label, status, approver, origin="base"):
    return Row(
        step_index=index,
        step_key=key,
        origin=origin,
        parent_step_key="",
        add_sign_position="",
        add_sign_opinion="",
        added_by="",
        added_on=None,
        label=label,
        mode="approve",
        approvers=json.dumps([approver]),
        approved_by=json.dumps([approver]) if status == oa_entry.STATUS_APPROVED else "[]",
        status=status,
        action_by=approver if status == oa_entry.STATUS_APPROVED else "",
        acted_on="2026-07-23 10:00:00" if status == oa_entry.STATUS_APPROVED else None,
        note="",
    )


def test_rejection_targets_include_applicant_and_completed_earlier_steps_only():
    steps = [
        _workflow_step(1, "step-1", "finance", oa_entry.STATUS_APPROVED, "finance@example.com"),
        _workflow_step(2, "step-2", "manager", oa_entry.STATUS_APPROVED, "manager@example.com"),
        _workflow_step(3, "step-3", "director", oa_entry.STATUS_PENDING, "director@example.com"),
        _workflow_step(4, "step-4", "pay", oa_entry.STATUS_WAIT_FLOW, "pay@example.com"),
    ]
    targets = oa_entry._eligible_rejection_targets(_dynamic_workflow_doc(steps, 3))
    assert [target["target"] for target in targets] == ["applicant", "step-1", "step-2"]


def test_reject_to_earlier_step_preserves_prior_history_and_resets_downstream():
    steps = [
        _workflow_step(1, "step-1", "finance", oa_entry.STATUS_APPROVED, "finance@example.com"),
        _workflow_step(2, "step-2", "manager", oa_entry.STATUS_APPROVED, "manager@example.com"),
        _workflow_step(3, "step-3", "director", oa_entry.STATUS_PENDING, "director@example.com"),
    ]
    doc = _dynamic_workflow_doc(steps, 3)
    oa_entry._reject_to_target(doc, steps[2], "step-2", "director@example.com", "needs revision")
    assert steps[0].status == oa_entry.STATUS_APPROVED
    assert steps[0].action_by == "finance@example.com"
    assert steps[1].status == oa_entry.STATUS_PENDING
    assert steps[1].approved_by == "[]"
    assert steps[2].status == oa_entry.STATUS_WAIT_FLOW
    assert doc.current_step_index == 2
    assert doc.workflow_status == oa_entry.STATUS_PENDING


def test_reject_to_applicant_returns_editable_draft_and_resets_all_steps():
    steps = [
        _workflow_step(1, "step-1", "finance", oa_entry.STATUS_APPROVED, "finance@example.com"),
        _workflow_step(2, "step-2", "manager", oa_entry.STATUS_PENDING, "manager@example.com"),
    ]
    doc = _dynamic_workflow_doc(steps, 2)
    oa_entry._reject_to_target(doc, steps[1], "applicant", "manager@example.com", "fix details")
    assert doc.workflow_status == oa_entry.STATUS_DRAFT
    assert doc.current_step_index == 0
    assert all(step.status == oa_entry.STATUS_WAIT_FLOW for step in steps)
    assert all(step.approved_by == "[]" and not step.action_by for step in steps)


def test_add_sign_before_and_after_reindexes_with_stable_parent_identity():
    before_steps = [_workflow_step(1, "base-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com")]
    before_doc = _dynamic_workflow_doc(before_steps, 1)
    inserted = oa_entry._insert_add_sign_step(before_doc, before_steps[0], "user-a@example.com", "before", "review first", "manager@example.com")
    assert inserted.step_index == 1
    assert inserted.parent_step_key == "base-1"
    assert inserted.origin == "add_sign"
    assert before_doc.steps[1].step_index == 2
    assert before_doc.steps[1].status == oa_entry.STATUS_WAIT_FLOW
    assert before_doc.current_step_index == 1

    after_steps = [_workflow_step(1, "base-2", "manager", oa_entry.STATUS_PENDING, "manager@example.com")]
    after_doc = _dynamic_workflow_doc(after_steps, 1)
    inserted_after = oa_entry._insert_add_sign_step(after_doc, after_steps[0], "user-b@example.com", "after", "review next", "manager@example.com")
    assert inserted_after.step_index == 2
    assert after_doc.steps[0].status == oa_entry.STATUS_PENDING
    assert after_doc.current_step_index == 1


def test_add_sign_rejects_self_duplicate_and_more_than_twenty_operations():
    base = _workflow_step(1, "base", "manager", oa_entry.STATUS_PENDING, "manager@example.com")
    doc = _dynamic_workflow_doc([base], 1)
    with pytest.raises(ValidationError):
        oa_entry._insert_add_sign_step(doc, base, "manager@example.com", "after", "self", "manager@example.com")
    duplicate = _workflow_step(2, "added", "added", oa_entry.STATUS_WAIT_FLOW, "user-a@example.com", origin="add_sign")
    duplicate.parent_step_key = "base"
    doc.steps.append(duplicate)
    with pytest.raises(ValidationError):
        oa_entry._insert_add_sign_step(doc, base, "user-a@example.com", "after", "duplicate", "manager@example.com")
    many = [base] + [
        _workflow_step(index + 2, f"added-{index}", "added", oa_entry.STATUS_APPROVED, f"user-{index}@example.com", origin="add_sign")
        for index in range(20)
    ]
    limit_doc = _dynamic_workflow_doc(many, 1)
    with pytest.raises(ValidationError, match="20"):
        oa_entry._insert_add_sign_step(limit_doc, base, "new@example.com", "after", "too many", "manager@example.com")


def test_action_request_requires_target_and_reopens_earlier_step(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    steps = [
        _workflow_step(1, "step-1", "finance", oa_entry.STATUS_APPROVED, "finance@example.com"),
        _workflow_step(2, "step-2", "manager", oa_entry.STATUS_PENDING, "manager@example.com"),
    ]
    doc = _dynamic_workflow_doc(steps, 2)
    doc.doctype = service.REQUEST_DOCTYPE
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["manager@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"manager@example.com"})
    assignment_syncs = []
    monkeypatch.setattr(oa_entry, "sync_current_assignments", lambda current: assignment_syncs.append(current.current_step_index), raising=False)
    with pytest.raises(ValidationError):
        oa_entry.action_request(doc.name, "reject", "fix it")
    result = oa_entry.action_request(doc.name, "reject", "fix it", "step-1")
    assert doc.current_step_index == 1
    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert result["status"] == oa_entry.STATUS_PENDING
    assert assignment_syncs == [1]


def test_add_sign_request_inserts_resolved_enabled_user_under_request_lock(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    steps = [_workflow_step(1, "step-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com")]
    doc = _dynamic_workflow_doc(steps, 1)
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    locks = []

    @contextmanager
    def request_lock(category, name):
        locks.append((category, name))
        yield object()

    monkeypatch.setattr(service, "_transaction_lock", request_lock)
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["manager@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"manager@example.com"})
    monkeypatch.setattr(oa_entry, "_resolve_add_sign_approver", lambda value: "user-a@example.com", raising=False)
    result = oa_entry.add_sign_request(doc.name, "user-a@example.com", "after", "please review")
    assert locks == [("request", doc.name)]
    assert len(doc.steps) == 2
    assert doc.steps[1].origin == "add_sign"
    assert result["status"] == oa_entry.STATUS_PENDING


def test_workflow_metadata_reports_targets_and_add_sign_allowance():
    steps = [
        _workflow_step(1, "base-1", "finance", oa_entry.STATUS_APPROVED, "finance@example.com"),
        _workflow_step(2, "added-1", "added", oa_entry.STATUS_PENDING, "added@example.com", origin="add_sign"),
    ]
    doc = _dynamic_workflow_doc(steps, 2)
    metadata = oa_entry._workflow_metadata(doc)
    assert metadata["rejection_targets"][0]["target"] == "applicant"
    assert metadata["rejection_targets"][1]["target"] == "base-1"
    assert metadata["add_sign_count"] == 1
    assert metadata["add_sign_remaining"] == 19


def test_resolve_route_approver_prefers_enabled_user_and_employee_link(monkeypatch):
    calls = []

    def get_value(doctype, filters, fieldname, **_kwargs):
        calls.append((doctype, filters, fieldname))
        if doctype == "User" and filters == {"full_name": "Supervisor", "enabled": 1}:
            return None
        if doctype == "Employee" and filters == {"employee_name": "Supervisor", "status": "Active"}:
            return "person054@staff.example.invalid"
        if doctype == "User" and filters == {"name": "person054@staff.example.invalid", "enabled": 1}:
            return "person054@staff.example.invalid"
        return None

    monkeypatch.setattr(frappe_stub, "db", types.SimpleNamespace(get_value=get_value), raising=False)

    assert oa_entry._resolve_route_approver("person054@staff.example.invalid") == "person054@staff.example.invalid"
    assert oa_entry._resolve_route_approver("Supervisor") == "person054@staff.example.invalid"
    assert oa_entry._resolve_route_approver("Unknown") == "Unknown"
    assert any(call[0] == "Employee" for call in calls)


def test_serialize_route_steps_resolves_dynamic_supervisor(monkeypatch):
    monkeypatch.setattr(
        oa_entry,
        "_resolve_route_approver",
        lambda value: "person054@staff.example.invalid" if value == "Supervisor" else value,
    )

    rows = oa_entry._serialize_route_steps(
        [{"label": "Supervisor", "mode": "approve", "approvers": ["Supervisor"]}],
        active=True,
    )

    assert rows[0]["approvers"] == ["person054@staff.example.invalid"]


def test_only_explicit_administrator_accounts_are_oa_override_users(monkeypatch):
    monkeypatch.setattr(
        frappe_stub,
        "get_roles",
        lambda user=None: {
            "admin@staff.example.invalid": ["System Manager"],
            "executive@example.com": ["Rayher Business Executive"],
        }.get(user, ["Employee"]),
    )

    assert oa_entry._is_oa_override_user("admin@staff.example.invalid") is True
    assert oa_entry._is_oa_override_user("executive@example.com") is False
    assert oa_entry._is_oa_override_user("Administrator") is True
    assert oa_entry._is_oa_override_user("ordinary@example.com") is False


def test_override_capabilities_expose_finance_classification_and_action_scope(monkeypatch):
    step = Row(label="\u8d22\u52a1\u5ba1\u6838\uff1a\u6f14\u793a\u5458\u5de513", mode="approve", approvers='["person067@staff.example.invalid"]')
    doc = Row(
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        workflow_status=oa_entry.STATUS_PENDING,
        expense_lines=[Row(expense_item="")],
        current_step_index=1,
        steps=[step],
    )
    step.step_index = 1
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: [])
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: True)
    monkeypatch.setattr(oa_entry, "_is_finance_user", lambda user=None: False)

    capabilities = oa_entry._request_capabilities(doc, "admin@staff.example.invalid")

    assert capabilities == {
        "can_approve": False,
        "can_reject": True,
        "can_add_sign": True,
        "can_add_sign_after": True,
        "can_edit_expense_items": True,
        "classification_ready": False,
        "is_override_actor": True,
        "action_scope": "override",
    }


def test_override_completes_all_mode_step_with_real_actor_audit(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    step = Row(
        step_index=1,
        step_key="executive-all",
        label="\u6f14\u793a\u5458\u5de521\u3001\u6f14\u793a\u5458\u5de529",
        mode="all",
        approvers='["person046@business.example.invalid", "person060@staff.example.invalid"]',
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
        action_by="",
        acted_on=None,
        note="",
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-EXEC-OVERRIDE",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": 1,
            "current_step_label": step.label,
            "expense_lines": [Row(expense_item="travel")],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "admin@staff.example.invalid"
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: [])
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: True)
    monkeypatch.setattr(oa_entry, "_with_expense_attachments", lambda _doc, lines: lines)

    oa_entry.action_request(doc.name, "approve", note="business override")

    assert doc.workflow_status == oa_entry.STATUS_COMPLETED
    assert step.action_by == "admin@staff.example.invalid"
    assert json.loads(step.approved_by) == ["admin@staff.example.invalid"]
    assert "person046@business.example.invalid" not in json.loads(step.approved_by)


def test_get_options_exposes_canonical_two_level_expense_accounts(monkeypatch):
    monkeypatch.setattr(
        oa_entry,
        "_employee_context",
        lambda: {"employee": "HR-EMP-90001", "employee_name": "测试员工"},
    )
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Employee"])
    frappe_stub.session.user = "employee@example.com"

    options = oa_entry.get_options()

    assert options["expense_account_tree"][0] == {
        "level_1": "差旅费",
        "level_2": [
            "飞机票",
            "高铁\\火车票",
            "市内交通费",
            "乘车费",
            "住宿费",
            "出差补助",
            "过路/停车费",
            "Philippe",
            "Sabri",
        ],
    }


def test_assigned_executive_counts_as_one_cosigner_instead_of_override(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    step = Row(
        step_index=1,
        step_key="executive-all-assigned",
        label="演示员工21、演示员工29",
        mode="all",
        approvers=json.dumps(["person046@business.example.invalid", "person060@staff.example.invalid"]),
        approved_by="[]",
        status=oa_entry.STATUS_PENDING,
        action_by="",
        acted_on=None,
        note="",
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-EXEC-ASSIGNED",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_PENDING,
            "current_step_index": 1,
            "current_step_label": step.label,
            "expense_lines": [],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "person046@business.example.invalid"
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: ["person046@business.example.invalid"])
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: True)

    oa_entry.action_request(doc.name, "approve", note="first cosigner")

    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert doc.current_step_index == 1
    assert step.status == oa_entry.STATUS_PENDING
    assert json.loads(step.approved_by) == ["person046@business.example.invalid"]



def test_employee_context_resolves_department_supervisor_from_organization(monkeypatch):
    class OrganizationDB:
        def get_value(self, doctype, filters, fieldname, as_dict=False, **_kwargs):
            if doctype == "Employee" and as_dict:
                return Row(
                    name="HR-EMP-SOFTWARE",
                    employee_name="演示员工150",
                    department="研发部 - RAY",
                    reports_to="",
                )
            if doctype == "Employee" and isinstance(filters, dict):
                if filters.get("employee_name") == "演示员工132" and fieldname == "user_id":
                    return "person024@business.example.invalid"
                return None
            if doctype == "User" and isinstance(filters, dict):
                if filters.get("name") == "person024@business.example.invalid" and filters.get("enabled") == 1:
                    return "person024@business.example.invalid"
            return None

    frappe_stub.db = OrganizationDB()

    context = oa_entry._employee_context("software@example.com")

    assert context["employee"] == "HR-EMP-SOFTWARE"
    assert context["supervisor"] == "演示员工132"
    assert context["supervisor_user"] == "person024@business.example.invalid"
    assert context["supervisor_decision"] == "approve"
    assert context["supervisor_path"] == ["演示员工132"]


def test_route_context_ignores_caller_supplied_supervisor_for_mapped_employee(monkeypatch):
    monkeypatch.setattr(
        oa_entry,
        "_employee_context",
        lambda user=None: {
            "employee": "HR-EMP-SOFTWARE",
            "employee_name": "演示员工150",
            "department": "研发部 - RAY",
            "supervisor": "演示员工132",
            "supervisor_user": "person024@business.example.invalid",
            "supervisor_decision": "approve",
            "supervisor_path": ["演示员工132"],
        },
    )

    context = oa_entry._route_context(
        department="伪造部门",
        supervisor="伪造审批人",
        asset_category=oa_entry.OTHER_ASSET,
    )

    assert context["department"] == "研发部 - RAY"
    assert context["supervisor"] == "演示员工132"
    assert context["supervisor_user"] == "person024@business.example.invalid"



def test_preview_route_passes_resolved_supervisor_user_into_route_builder(monkeypatch):
    monkeypatch.setattr(
        oa_entry,
        "_route_context",
        lambda **_kwargs: {
            "employee": "HR-EMP-SOFTWARE",
            "employee_name": "演示员工150",
            "department": "研发部 - RAY",
            "supervisor": "演示员工132",
            "supervisor_user": "person024@business.example.invalid",
            "supervisor_decision": "approve",
            "supervisor_path": ["演示员工132"],
            "asset_category": oa_entry.OTHER_ASSET,
        },
    )

    result = oa_entry.preview_route(oa_entry.REQUEST_EXPENSE_PAYMENT)
    supervisor_step = next(step for step in result["steps"] if step["label"] == "直属主管：演示员工132")

    assert supervisor_step["approvers"] == ["person024@business.example.invalid"]




def test_leave_employee_context_uses_excel_direct_supervisor_with_account(monkeypatch):
    monkeypatch.setattr(
        frappe_stub,
        "get_all",
        lambda doctype, **_kwargs: [{
            "name": "HR-EMP-STAFF",
            "employee_name": "演示员工150",
            "department": "研发软件部 - RAY",
            "reports_to": "HR-EMP-MANAGER",
        }] if doctype == "Employee" else [],
        raising=False,
    )
    monkeypatch.setattr(
        oa_entry,
        "_enabled_employee_user",
        lambda employee_name: "jun@example.com" if employee_name == "演示员工132" else "",
    )

    context = oa_entry._leave_employee_context("staff@example.com")

    assert context["supervisor"] == "演示员工132"
    assert context["supervisor_user"] == "jun@example.com"
    assert context["supervisor_decision"] == "approve"
    assert context["supervisor_path"] == ["演示员工132"]


def test_leave_employee_context_climbs_past_accountless_direct_supervisor(monkeypatch):
    monkeypatch.setattr(
        frappe_stub,
        "get_all",
        lambda doctype, **_kwargs: [{
            "name": "HR-EMP-STAFF",
            "employee_name": "演示员工109",
            "department": "客服部 - SHGL",
            "reports_to": "HR-EMP-MANAGER",
        }] if doctype == "Employee" else [],
        raising=False,
    )
    monkeypatch.setattr(
        oa_entry,
        "_enabled_employee_user",
        lambda employee_name: (
            "demo_executive@example.com" if employee_name == "演示员工21" else ""
        ),
    )

    context = oa_entry._leave_employee_context("staff@example.com")

    assert context["supervisor"] == "演示员工21"
    assert context["supervisor_user"] == "demo_executive@example.com"
    assert context["supervisor_decision"] == "skip"
    assert context["supervisor_path"] == ["演示员工155", "演示员工21"]


def test_leave_employee_context_rejects_duplicate_active_employee_links(monkeypatch):
    monkeypatch.setattr(
        frappe_stub,
        "get_all",
        lambda *_args, **_kwargs: [
            {"name": "HR-EMP-1"},
            {"name": "HR-EMP-2"},
        ],
        raising=False,
    )

    with pytest.raises(oa_entry.ApprovalRouteError, match="多个在职员工"):
        oa_entry._leave_employee_context("duplicate@example.com")


def test_leave_employee_context_skips_only_top_executive_self_approval(monkeypatch):
    monkeypatch.setattr(
        frappe_stub,
        "get_all",
        lambda *_args, **_kwargs: [
            {
                "name": "HR-EMP-QINGBO",
                "employee_name": "演示员工21",
                "department": "总经办 - RAY",
                "reports_to": "",
            }
        ],
        raising=False,
    )

    context = oa_entry._leave_employee_context("person046@staff.example.invalid")

    assert context["supervisor_decision"] == "skip"
    assert context["supervisor_user"] == "person046@staff.example.invalid"

def test_leave_route_ignores_client_department_and_supervisor(monkeypatch):
    monkeypatch.setattr(oa_entry, "_require_leave_accounts", lambda *_args: None)
    monkeypatch.setattr(
        oa_entry,
        "_leave_employee_context",
        lambda user=None: {
            "employee": "HR-EMP-SOFTWARE",
            "employee_name": "演示员工150",
            "applicant_user": "person051@staff.example.invalid",
            "department": "研发部 - RAY",
            "supervisor": "演示员工132",
            "supervisor_user": "person024@staff.example.invalid",
            "supervisor_decision": "approve",
            "supervisor_path": ["演示员工132"],
        },
    )

    context = oa_entry._route_context(
        department="财务部 - FORGED",
        supervisor="伪造审批人",
        asset_category=oa_entry.ADMIN_ASSET,
        request_type=oa_entry.REQUEST_LEAVE,
    )
    route = oa_entry.preview_route(
        oa_entry.REQUEST_LEAVE,
        department="财务部 - FORGED",
        supervisor="伪造审批人",
    )

    assert context["department"] == "研发部 - RAY"
    assert context["supervisor"] == "演示员工132"
    assert [step["label"] for step in route["steps"]] == [
        "直属主管：演示员工132", "人事经理", "演示员工21"
    ]
    assert route["copied_to"] == [
        {"label": "人事经理", "user": "person047@staff.example.invalid"},
        {"label": "演示员工21", "user": "person046@staff.example.invalid"},
    ]


def test_leave_route_fails_closed_for_unlinked_account(monkeypatch):
    monkeypatch.setattr(
        oa_entry,
        "_leave_employee_context",
        lambda user=None: {
            "employee": None,
            "employee_name": "",
            "applicant_user": "person039@staff.example.invalid",
            "department": "",
            "supervisor": "",
            "supervisor_user": "",
            "supervisor_decision": "",
            "supervisor_path": [],
        },
    )

    with pytest.raises(ValidationError, match="未关联在职员工"):
        oa_entry.preview_route(
            oa_entry.REQUEST_LEAVE,
            department="财务部 - FORGED",
            supervisor="伪造审批人",
        )



def test_leave_route_rejects_a_disabled_fixed_account(monkeypatch):
    class UserDB:
        def get_value(self, doctype, filters, fieldname, **_kwargs):
            if doctype == "User" and filters.get("name") != "person035@staff.example.invalid":
                return filters.get("name")
            return None

    monkeypatch.setattr(frappe_stub, "db", UserDB(), raising=False)

    with pytest.raises(oa_entry.ApprovalRouteError, match="未启用或不存在"):
        oa_entry._require_leave_accounts(
            [{"approvers": ["person035@staff.example.invalid"]}], []
        )


def test_leave_submission_creates_non_blocking_copy_notifications(monkeypatch):
    monkeypatch.setattr(frappe_stub, "db", types.SimpleNamespace(exists=lambda *args: False), raising=False)
    inserted = []

    class Notification(dict):
        def insert(self, ignore_permissions=False):
            inserted.append((dict(self), ignore_permissions))
            return self

    monkeypatch.setattr(frappe_stub, "get_doc", lambda values: Notification(values), raising=False)
    doc = Row(
        request_type=oa_entry.REQUEST_LEAVE,
        name="OA-LEAVE-1",
        copied_to=json.dumps([
            {"label": "演示员工10", "user": "person047@staff.example.invalid"},
            {"label": "演示员工37", "user": "person046@staff.example.invalid"},
        ], ensure_ascii=False),
    )

    oa_entry._notify_copied_users(doc)

    assert [row[0]["for_user"] for row in inserted] == [
        "person047@staff.example.invalid",
        "person046@staff.example.invalid",
    ]
    assert all(row[1] is True for row in inserted)



def test_submitting_expense_requires_explicit_asset_category(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-ASSET-REQUIRED",
            "doc_type": "固定资产",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_DRAFT,
            "department": "研发部 - RAY",
            "supervisor": "演示员工132",
            "asset_category": "",
            "expense_lines": [Row(project_name="项目甲", expense_description="打车", total_amount=20)],
            "steps": [],
            "operation_log": "[]",
        },
    )
    monkeypatch.setattr(service, "validate_request_invoices", lambda *_args, **_kwargs: {})

    with pytest.raises(ValidationError, match="资产类型"):
        oa_entry._submit_draft(doc)


def test_final_handle_step_confirms_payment_atomically(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    step = Row(
        step_index=1,
        step_key="confirm-payment",
        label="确认付款：演示员工13",
        mode="handle",
        approvers=json.dumps(["person067@staff.example.invalid"]),
        approved_by="[]",
        status=oa_entry.STATUS_WAIT_HANDLE,
        action_by="",
        acted_on=None,
        note="",
    )
    doc = RequestDocument(
        environment,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-CONFIRM-PAYMENT",
            "owner": "alice@example.com",
            "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
            "workflow_status": oa_entry.STATUS_WAIT_HANDLE,
            "current_step_index": 1,
            "current_step_label": step.label,
            "expense_lines": [],
            "steps": [step],
            "operation_log": "[]",
        },
    )
    environment.committed[doc.name] = doc
    frappe_stub.session.user = "person067@staff.example.invalid"
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: ["person067@staff.example.invalid"])
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda user=None: False)
    assignment_syncs = []
    monkeypatch.setattr(oa_entry, "sync_current_assignments", lambda current: assignment_syncs.append(current.workflow_status), raising=False)

    oa_entry.action_request(doc.name, "approve", note="已核对付款")

    assert doc.workflow_status == oa_entry.STATUS_PAID
    assert doc.current_step_index == 0
    assert step.status == oa_entry.STATUS_HANDLED
    assert doc.paid_by == "person067@staff.example.invalid"
    assert doc.paid_on is not None
    assert json.loads(doc.operation_log)[-1]["action"] == "确认付款"
    assert assignment_syncs == [oa_entry.STATUS_PAID]


def _procurement_role_snapshots():
    def row(role_key, label, user, name):
        return {"role_key": role_key, "role_label": label, "user": user, "employee": "EMP-" + role_key, "employee_name": name}
    return {
        "pmc": row("pmc", "PMC", "person076@staff.example.invalid", "演示员工178"),
        "production_asset_owner": row("production_asset_owner", "生产设备负责人", "person074@staff.example.invalid", "演示员工241"),
        "finance_auditor": row("finance_auditor", "财务审核", "person067@staff.example.invalid", "演示员工13"),
        "vice_manager": row("vice_manager", "副总经理", "person046@staff.example.invalid", "演示员工21"),
        "general_manager": row("general_manager", "总经理", "person060@staff.example.invalid", "演示员工29"),
        "hr_manager": row("hr_manager", "人事经理", "person047@staff.example.invalid", "演示员工10"),
        "finance_manager": row("finance_manager", "财务主管", "person072@staff.example.invalid", "演示员工16"),
    }


def test_procurement_submit_uses_existing_engine_and_builds_real_steps(monkeypatch):
    real_preview_route = oa_entry.preview_route
    environment = _install_request_environment(monkeypatch)
    monkeypatch.setattr(oa_entry, "preview_route", real_preview_route)
    doc = RequestDocument(environment, {
        "doctype": service.REQUEST_DOCTYPE,
        "name": "PROC-1",
        "owner": "alice@example.com",
        "employee": "EMP-1",
        "employee_name": "Alice",
        "request_type": "采购申请",
        "workflow_status": oa_entry.STATUS_DRAFT,
        "business_status": "",
        "department": "研发部",
        "supervisor": "直属领导",
        "asset_nature": "非固定资产",
        "fixed_asset_category": "",
        "asset_category": oa_entry.OTHER_ASSET,
        "procurement_scope": "项目采购",
        "expected_delivery_date": "2026-09-10",
        "project": "PRJ-1",
        "project_owner": "owner@example.com",
        "project_owner_name": "项目主管",
        "business_lines": [Row(item_name="芯片", quantity=2, amount=20, material_code="01.01.01", specification="TEST", brand="TEST", unit="个")],
        "steps": [],
        "operation_log": "[]",
    })
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_employee_context", lambda user=None, employee=None: {
        "employee": "EMP-1", "employee_name": "Alice", "applicant_user": "alice@example.com",
        "department": "研发部", "supervisor": "直属领导", "supervisor_user": "boss@example.com",
        "supervisor_decision": "approve", "supervisor_path": ["直属领导"],
        "upper_supervisor": "演示员工21", "upper_supervisor_user": "vice@example.com",
    })
    monkeypatch.setattr(oa_entry, "_resolve_approval_roles", lambda *_args, **_kwargs: _procurement_role_snapshots())
    assignment_syncs = []
    monkeypatch.setattr(oa_entry, "sync_current_assignments", lambda current: assignment_syncs.append((current.name, current.current_step_label)), raising=False)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: {
        "workflow_status": current.workflow_status,
        "business_status": current.business_status,
        "current_step_label": current.current_step_label,
    })
    result = oa_entry.submit_request("PROC-1")
    assert result["workflow_status"] == oa_entry.STATUS_PENDING
    assert result["business_status"] == "待审批"
    assert result["current_step_label"] == "直属主管：直属领导、项目主管：项目主管（会签）"
    assert [row.label for row in doc.steps] == [
        "直属主管：直属领导、项目主管：项目主管（会签）",
        "PMC：演示员工178",
        "需求终审：副总经理：演示员工21",
    ]
    assert doc.steps[0].mode == "all"
    assert set(json.loads(doc.steps[0].approvers)) == {"boss@example.com", "owner@example.com"}
    assert json.loads(doc.operation_log)[-1]["action"] == "提交申请"
    assert assignment_syncs == [("PROC-1", "直属主管：直属领导、项目主管：项目主管（会签）")]


def test_zero_step_procurement_and_direct_purchase_are_rejected(monkeypatch):
    for request_type in (
        oa_entry.REQUEST_PROCUREMENT,
        oa_entry.REQUEST_DIRECT_PURCHASE,
    ):
        doc = Row(
            request_type=request_type,
            workflow_status=oa_entry.STATUS_DRAFT,
            business_status="",
            current_step_index=0,
            current_step_label="",
            amount=88,
            approved_amount=None,
            copied_to="[]",
            steps=[],
            operation_log="[]",
            asset_category=oa_entry.OTHER_ASSET,
        )
        if request_type == oa_entry.REQUEST_PROCUREMENT:
            doc.business_lines = [Row(item_name="测试物料", quantity=1, material_serial="MAT-TEST", material_code="01.01.01", specification="TEST", brand="TEST", unit="个")]
            doc.procurement_scope = "非项目采购"
            doc.expected_delivery_date = "2026-09-10"
            doc.non_project_allocation_type = "非项目采购"
            doc.project = ""
            doc.project_owner = ""
        monkeypatch.setattr(oa_entry, "_route_context", lambda **_kwargs: {
            "department": "研发部", "supervisor": "演示员工21", "asset_category": oa_entry.OTHER_ASSET,
        })
        monkeypatch.setattr(oa_entry, "preview_route", lambda *_args, **_kwargs: {
            "steps": [], "copied_to": [],
        })
        monkeypatch.setattr(oa_entry, "_append_steps", lambda current, _steps: setattr(current, "steps", []))

        with pytest.raises(ValidationError, match="审批路线不能为空"):
            oa_entry._submit_draft(doc)

        assert doc.workflow_status == oa_entry.STATUS_DRAFT


def test_expense_asset_classification_populates_payment_dashboard_fields():
    assert oa_entry._expense_dashboard_classification(oa_entry.ADMIN_ASSET) == {
        "asset_category": oa_entry.ADMIN_ASSET,
        "asset_nature": "固定资产",
        "fixed_asset_category": "办公家具、工具及器具",
    }
    assert oa_entry._expense_dashboard_classification(oa_entry.IT_ASSET) == {
        "asset_category": oa_entry.IT_ASSET,
        "asset_nature": "固定资产",
        "fixed_asset_category": "电子设备、研发专用设备、仪器仪表",
    }
    assert oa_entry._expense_dashboard_classification(oa_entry.OTHER_ASSET) == {
        "asset_category": oa_entry.OTHER_ASSET,
        "asset_nature": "非固定资产",
        "fixed_asset_category": "",
    }


def test_leave_and_expense_business_statuses_follow_business_lifecycle():
    leave_step = Row(step_index=1)
    leave = Row(
        steps=[leave_step],
        request_type=oa_entry.REQUEST_LEAVE,
        workflow_status=oa_entry.STATUS_PENDING,
        business_status="待审批",
        current_step_index=1,
        current_step_label="人事经理",
    )
    oa_entry._advance_after_step(leave, leave_step)
    assert leave.workflow_status == oa_entry.STATUS_COMPLETED
    assert leave.business_status == "已完成"

    approval = Row(step_index=1)
    payment = Row(step_index=2, label="确认付款：演示员工13", mode="handle", status=oa_entry.STATUS_WAIT_FLOW)
    expense = Row(
        steps=[approval, payment],
        request_type=oa_entry.REQUEST_EXPENSE_PAYMENT,
        workflow_status=oa_entry.STATUS_PENDING,
        business_status="待审批",
        current_step_index=1,
        current_step_label="演示员工29",
    )
    oa_entry._advance_after_step(expense, approval)
    assert expense.workflow_status == oa_entry.STATUS_WAIT_HANDLE
    assert expense.business_status == "待付款"

    expense.amount = 200
    oa_entry._advance_after_step(expense, payment)
    assert expense.workflow_status == oa_entry.STATUS_COMPLETED
    assert expense.approved_amount == 200


def test_direct_purchase_completion_updates_business_status():
    step = Row(step_index=1)
    doc = Row(
        steps=[step],
        request_type=oa_entry.REQUEST_DIRECT_PURCHASE,
        workflow_status=oa_entry.STATUS_PENDING,
        business_status="待审批",
        current_step_index=1,
        current_step_label="直属主管",
        amount=88,
    )

    oa_entry._advance_after_step(doc, step)

    assert doc.workflow_status == oa_entry.STATUS_COMPLETED
    assert doc.business_status == "待付款"
    assert doc.current_step_index == 0


def test_procurement_submit_rejects_other_users_and_duplicate_submission(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(environment, {
        "doctype": service.REQUEST_DOCTYPE, "name": "PROC-2", "owner": "other@example.com",
        "employee": "EMP-OTHER", "request_type": "采购申请", "workflow_status": oa_entry.STATUS_DRAFT,
        "steps": [], "operation_log": "[]",
    })
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValidationError("无权编辑")))
    with pytest.raises(ValidationError, match="无权编辑"):
        oa_entry.submit_request("PROC-2")
    assert doc.workflow_status == oa_entry.STATUS_DRAFT

    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    doc.workflow_status = oa_entry.STATUS_PENDING
    with pytest.raises(ValidationError, match="草稿"):
        oa_entry.submit_request("PROC-2")

def test_procurement_payment_submit_reserves_source_amount_in_same_request_transaction(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(environment, {
        "doctype": service.REQUEST_DOCTYPE, "name": "PAY-PROC-SUBMIT", "owner": "alice@example.com",
        "employee": "EMP-1", "request_type": oa_entry.REQUEST_PROCUREMENT_PAYMENT,
        "workflow_status": oa_entry.STATUS_DRAFT, "business_status": "", "department": "研发部",
        "supervisor": "直属领导", "asset_category": oa_entry.OTHER_ASSET,
        "source_request": "PROC-SOURCE-1", "supplier": "SUP-1", "payment_stage": "预付款",
        "prepayment_percentage": 30, "has_balance_payment": 1, "approved_amount_snapshot": 100,
        "amount": 30, "currency": "CNY", "business_lines": [Row(item_name="芯片", quantity=1, amount=30)],
        "steps": [], "operation_log": "[]",
    })
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        oa_entry.approval_amount_ledger,
        "source_balance",
        lambda *_args, **_kwargs: {
            "approved_amount": Decimal("100"),
            "reserved_amount": Decimal("0"),
            "paid_amount": Decimal("0"),
            "available_amount": Decimal("100"),
        },
    )
    monkeypatch.setattr(oa_entry, "validate_payment_submission", lambda *_args, **_kwargs: "预付款")
    monkeypatch.setattr(oa_entry, "_request_business_document_types", lambda *_args, **_kwargs: {"合同", "付款计划"})
    reserved = []
    monkeypatch.setattr(oa_entry, "_reserve_procurement_payment", lambda current: reserved.append((current.source_request, current.name)))

    oa_entry.submit_request(doc.name)

    assert reserved == [("PROC-SOURCE-1", "PAY-PROC-SUBMIT")]
    assert doc.workflow_status == oa_entry.STATUS_PENDING


def test_procurement_payment_final_handle_posts_ledger_and_enters_arrival_lifecycle(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    step = Row(
        step_index=1, step_key="proc-payment-handle", origin="base", label="财务确认付款：演示员工13",
        mode="handle", approvers=json.dumps(["finance@example.com"]), approved_by="[]",
        status=oa_entry.STATUS_WAIT_HANDLE, action_by="", acted_on=None, note="",
    )
    doc = RequestDocument(environment, {
        "doctype": service.REQUEST_DOCTYPE, "name": "PAY-PROC-HANDLE", "owner": "alice@example.com",
        "request_type": oa_entry.REQUEST_PROCUREMENT_PAYMENT, "workflow_status": oa_entry.STATUS_WAIT_HANDLE,
        "business_status": "待审批", "current_step_index": 1, "current_step_label": step.label,
        "source_request": "PROC-SOURCE-1", "payment_stage": "预付款", "prepayment_percentage": 100,
        "arrival_status": "", "inspection_status": "", "prepayment_writeoff_status": "无需核销",
        "expense_lines": [], "steps": [step], "operation_log": "[]",
    })
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda *_args, **_kwargs: ["finance@example.com"])
    monkeypatch.setattr(oa_entry, "_is_oa_override_user", lambda *_args, **_kwargs: False)
    paid = []
    monkeypatch.setattr(oa_entry, "_mark_procurement_payment_paid", lambda current: paid.append(current.name))

    oa_entry.action_request(doc.name, "approve", "已付款")

    assert paid == ["PAY-PROC-HANDLE"]
    assert doc.workflow_status == oa_entry.STATUS_PAID
    assert doc.business_status == "待到货"
    assert doc.prepayment_writeoff_status == "待核销"

def test_my_approval_summary_limits_executives_but_keeps_admin_global_queue(monkeypatch):
    step = Row(step_index=1, label="PMC：演示员工178", approvers='["person076@staff.example.invalid"]')
    doc = Row(name="OA-OTHER", request_type=oa_entry.REQUEST_PROCUREMENT, workflow_status=oa_entry.STATUS_PENDING, current_step_index=1, steps=[step])
    monkeypatch.setattr(frappe_stub, "get_all", lambda *_args, **_kwargs: [{"name": doc.name}], raising=False)
    monkeypatch.setattr(oa_entry, "_load_request", lambda _name: doc)
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda _doc, user=None: True)
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: [])

    frappe_stub.session.user = "executive@example.com"
    frappe_stub.get_roles = lambda user=None: [oa_entry.BUSINESS_EXECUTIVE_ROLE]
    assert oa_entry.get_my_approval_summary()["total"] == 0

    frappe_stub.session.user = "Administrator"
    frappe_stub.get_roles = lambda user=None: ["System Manager"]
    assert oa_entry.get_my_approval_summary()["total"] == 1


def test_procurement_quote_snapshot_is_json_serializable():
    doc = types.SimpleNamespace(
        supplier="供应商",
        amount=Decimal("250.00"),
        business_lines=[Row(
            item_name="耗材", specification="TEST", quantity=Decimal("2.0000"),
            unit="个", unit_price=Decimal("125.00"), amount=Decimal("250.00"), remarks="",
        )],
    )

    snapshot = oa_entry._quote_snapshot(doc)

    assert json.loads(json.dumps(snapshot, ensure_ascii=False))["business_lines"][0] == {
        "item_name": "耗材", "specification": "TEST", "quantity": 2.0, "unit": "个",
        "unit_price": 125.0, "amount": 250.0, "remarks": "",
        "material_code": "", "material_serial": "", "category_code": "", "category_path": "",
        "product_desc": "", "brand": "", "product_name": "", "product_desc_en": "", "brand_en": "", "material_attr": "外购",
    }

def test_rejection_notification_stamp_uses_actual_operation_time():
    assert oa_entry._event_stamp({"acted_on": "2026-08-24 17:29:37.281533"}) == "2026-08-24 17:29:37.281533"
    assert oa_entry._event_stamp({"timestamp": "new", "acted_on": "old"}) == "new"


def test_pending_sql_finds_old_assigned_requests_before_pagination(monkeypatch):
    docs = {}
    for index in range(120):
        doc = _report_request(f"REQ-{index:03d}", owner="bob@example.com", employee="EMP-2")
        doc.workflow_status = oa_entry.STATUS_PENDING
        doc.current_step_index = 1
        doc.modified = f"2026-09-{index:03d}"
        doc.steps = [Row(step_index=1, approvers=json.dumps(["alice@example.com" if index < 3 else "bob@example.com"]), approved_by="[]")]
        docs[doc.name] = doc
    _install_report_requests(monkeypatch, docs)
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda doc: {"name": doc.name})
    first = oa_entry.list_requests(view="pending", limit=2)
    second = oa_entry.list_requests(view="pending", limit=2, offset=2)
    assert [row["name"] for row in first + second] == ["REQ-002", "REQ-001", "REQ-000"]


def test_non_fixed_expense_clears_contradictory_fixed_category():
    result = oa_entry._expense_classification("非固定资产", oa_entry.IT_ASSET, submitting=True)
    assert result["asset_nature"] == "非固定资产"
    assert result["asset_category"] == oa_entry.OTHER_ASSET
    assert result["fixed_asset_category"] == ""


def test_incomplete_draft_preserves_zero_amount_line():
    rows, amount = oa_entry._normalize_expense_lines([{"project_name": "待补资料", "amount": 0}], keep_incomplete=True)
    assert len(rows) == 1 and rows[0]["project_name"] == "待补资料" and amount == 0
    with pytest.raises(ValidationError):
        oa_entry._normalize_expense_lines([{"amount": -1}], keep_incomplete=True)


def test_signed_cosigner_is_not_pending_but_can_still_read(monkeypatch):
    doc = _report_request("REQ-SIGNED", owner="bob@example.com", employee="EMP-2")
    doc.workflow_status = oa_entry.STATUS_PENDING
    doc.current_step_index = 1
    doc.steps = [Row(step_index=1, approvers=json.dumps(["alice@example.com", "bob@example.com"]), approved_by=json.dumps(["alice@example.com"]))]
    _install_report_requests(monkeypatch, {doc.name: doc})
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda doc: {"name": doc.name})
    assert oa_entry.list_requests(view="pending") == []
    assert oa_entry.list_requests(view="all") == [{"name": doc.name}]


def test_resume_manual_draft_preserves_identity_and_incomplete_fields(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(environment, {"doctype": service.REQUEST_DOCTYPE, "name": "REQ-DRAFT", "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT,
        "workflow_status": oa_entry.STATUS_DRAFT, "owner": "alice@example.com", "employee": "EMP-1", "expense_lines": [], "steps": []})
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *args, **kwargs: nullcontext())
    permissions = []
    monkeypatch.setattr(service, "_request_permission", lambda document, action, **kwargs: permissions.append((document.name, action)))
    oa_entry.update_manual_expense_draft(doc.name, {"subject": "继续补填", "doc_type": "固定资产", "expense_lines": [{"project_name": "项目甲", "amount": 0}]})
    assert permissions == [("REQ-DRAFT", "edit")]
    assert doc.name == "REQ-DRAFT" and doc.owner == "alice@example.com" and doc.employee == "EMP-1"
    assert doc.subject == "继续补填" and doc.asset_category == "" and doc.expense_lines[0].amount == 0
    with pytest.raises(ValidationError, match="资产类型"):
        oa_entry._submit_draft(doc)
    doc.workflow_status = oa_entry.STATUS_PENDING
    with pytest.raises(ValidationError, match="草稿"):
        oa_entry.update_manual_expense_draft(doc.name, {})


def test_resuming_manual_draft_does_not_insert_another_document(monkeypatch):
    from contextlib import nullcontext
    env = _install_request_environment(monkeypatch)
    doc = RequestDocument(env, {"doctype": service.REQUEST_DOCTYPE, "name": "REQ-ORIGINAL",
        "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT, "workflow_status": oa_entry.STATUS_DRAFT,
        "owner": "alice@example.com", "employee": "EMP-1", "expense_lines": [], "steps": []})
    env.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(service, "_request_permission", lambda *a, **kw: None)
    oa_entry.update_manual_expense_draft(doc.name, {"subject": "resume", "doc_type": "非固定资产", "expense_lines": []})
    assert env.inserted == []
    assert [d.name for d in env.saved] == ["REQ-ORIGINAL"]


@pytest.mark.parametrize("action", ["approve", "reject", "add_sign"])
def test_signed_cosigner_cannot_act_again(monkeypatch, action):
    from contextlib import nullcontext
    env = _install_request_environment(monkeypatch)
    steps = [_workflow_step(1, "step-1", "first", oa_entry.STATUS_APPROVED, "finance@example.com"),
             _workflow_step(2, "step-2", "cosign", oa_entry.STATUS_PENDING, "alice@example.com")]
    steps[1].mode = "all"
    steps[1].approvers = json.dumps(["alice@example.com", "bob@example.com"])
    steps[1].approved_by = json.dumps(["alice@example.com"])
    doc = _dynamic_workflow_doc(steps, 2)
    doc.doctype = service.REQUEST_DOCTYPE
    object.__setattr__(doc, "environment", env)
    env.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"alice@example.com"})
    with pytest.raises(Exception, match="当前节点|Only the current approver"):
        if action == "add_sign":
            oa_entry.add_sign_request(doc.name, "carol@example.com", "after", "opinion")
        else:
            oa_entry.action_request(doc.name, action, "repeat", "step-1")
    assert env.saved == []
    assert doc.current_step_index == 2


def test_real_cashier_route_requires_classification(monkeypatch):
    from rayher_hr_payroll.oa_approval import build_expense_payment_route
    route = build_expense_payment_route("研发部", "", supervisor_decision="skip", roles=_procurement_role_snapshots())
    first = Row(route[0]); first.step_index = 1
    first.approvers = json.dumps(first.approvers); first.approved_by = "[]"
    doc = _request()
    doc.expense_lines[0].expense_account_level_1 = ""
    doc.expense_lines[0].expense_account_level_2 = ""
    doc.workflow_status = oa_entry.STATUS_PENDING; doc.current_step_index = 1; doc.steps = [first]
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Accounts User"])
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda step, user=None: ["alice@example.com"])
    caps = oa_entry._request_capabilities(doc)
    assert caps["can_edit_expense_items"] is True
    assert caps["can_approve"] is False
    with pytest.raises(Exception, match="费用科目"):
        oa_entry._validate_finance_classification(doc, first)


@pytest.mark.parametrize("spoof_field", ["full_name", "employee_name", "employee"])
def test_editable_identity_cannot_impersonate_approver(monkeypatch, spoof_field):
    victim = "finance@example.com"
    monkeypatch.setattr(frappe_stub, "db", types.SimpleNamespace(get_value=lambda *a, **k: victim), raising=False)
    monkeypatch.setattr(oa_entry, "_employee_context", lambda user=None: {
        "employee": victim if spoof_field == "employee" else "EMP-1",
        "employee_name": victim if spoof_field == "employee_name" else "Alice",
    })
    step = Row(step_index=1, approvers=json.dumps([victim]), approved_by="[]")
    doc = Row(workflow_status=oa_entry.STATUS_PENDING, current_step_index=1, steps=[step])
    assert oa_entry._actor_names() == {"alice@example.com"}
    assert oa_entry._matched_approvers(step) == []
    assert oa_entry._can_act_on_current_step(doc) is False
    assert oa_entry._can_act_on_current_step(doc, victim) is True


@pytest.mark.parametrize("label", ["forged", "x" * 200])
def test_draft_discards_client_derived_expense_item(label):
    rows, total = oa_entry._normalize_expense_lines([{
        "expense_account_level_1": "差旅费", "expense_account_level_2": "住宿费",
        "expense_item": label, "category": label, "amount": 10,
    }], keep_incomplete=True)
    assert rows[0]["expense_item"] == "差旅费 / 住宿费"
    assert rows[0]["category"] == "差旅费 / 住宿费"
    assert total == 10


def test_partial_draft_keeps_valid_parent_but_no_derived_label():
    rows, _ = oa_entry._normalize_expense_lines([{
        "expense_account_level_1": "差旅费", "expense_item": "forged", "amount": 0,
    }], keep_incomplete=True)
    assert rows[0]["expense_account_level_1"] == "差旅费"
    assert rows[0]["expense_item"] == ""
    with pytest.raises(ValidationError):
        oa_entry._normalize_expense_lines([{
            "expense_account_level_1": "fake", "amount": 0,
        }], keep_incomplete=True)


def test_submit_rewrites_legacy_draft_classification(monkeypatch):
    environment = _install_request_environment(monkeypatch)
    doc = RequestDocument(environment, {
        "doctype": service.REQUEST_DOCTYPE, "name": "REQ-LEGACY-DRAFT",
        "request_type": oa_entry.REQUEST_EXPENSE_PAYMENT, "workflow_status": oa_entry.STATUS_DRAFT,
        "doc_type": "非固定资产", "employee": "EMP-1", "operation_log": "[]", "steps": [],
        "expense_lines": [Row(issue_date="2026-09-21", amount=10,
            expense_account_level_1="差旅费", expense_account_level_2="住宿费",
            expense_item="forged", category="forged", project_name="项目甲")],
    })
    # These checks concern project/invoice fixtures, not the account normalization
    # being exercised. Runtime integration separately covers the full submit API.
    monkeypatch.setattr(oa_entry, "_validate_expense_project_groups", lambda doc: None)
    monkeypatch.setattr(oa_entry, "_validate_invoice_handling_submission", lambda doc: None)
    monkeypatch.setattr(oa_entry, "_route_context", lambda **kwargs: {
        "department": "研发部", "supervisor": "", "asset_category": oa_entry.OTHER_ASSET,
    })
    oa_entry._submit_draft(doc)
    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert doc.expense_lines[0].expense_item == "差旅费 / 住宿费"
    assert doc.expense_lines[0].category == "差旅费 / 住宿费"


def test_route_resolution_does_not_use_self_editable_user_full_name(monkeypatch):
    calls = []
    def get_value(doctype, filters, field, **kwargs):
        calls.append((doctype, filters, field))
        if doctype == "User" and filters.get("full_name"):
            return "attacker@example.com"
        if doctype == "Employee" and filters.get("employee_name") == "Supervisor":
            return "supervisor@example.com"
        if doctype == "User" and filters.get("name") == "supervisor@example.com":
            return "supervisor@example.com"
        return None
    monkeypatch.setattr(frappe_stub, "db", types.SimpleNamespace(get_value=get_value), raising=False)
    assert oa_entry._resolve_route_approver("Supervisor") == "supervisor@example.com"
    assert not any(dt == "User" and "full_name" in filters for dt, filters, field in calls)


def test_expense_reports_cannot_be_widened_by_the_employee_filter(monkeypatch):
    """修复（2026-09-24，审查 P0-1 / R3-57-2）：员工和 HR 传 employee=别人 也只能看到本人；财务照常。"""
    line = {
        "line_key": "line-1", "source_invoice": "", "invoice_category": "", "project_name": "文具",
        "expense_item": "交通费", "issue_date": "2026-07-14", "invoice_number": "",
        "amount_before_tax": Decimal("10.00"), "tax_amount": Decimal("0"), "total_amount": Decimal("10.00"),
        "amount": Decimal("10.00"),
    }
    step = {
        "step_index": 1, "label": "财务审核", "mode": "approve", "approvers": json.dumps(["finance@example.com"]),
        "status": oa_entry.STATUS_APPROVED, "approved_by": json.dumps(["finance@example.com"]),
        "action_by": "finance@example.com", "acted_on": "2026-07-20 10:00:00", "note": "同意",
    }
    docs = {
        "REQ-MINE": _report_request("REQ-MINE", workflow_status=oa_entry.STATUS_COMPLETED, expense_lines=[line], steps=[step]),
        "REQ-BOB": _report_request("REQ-BOB", owner="bob@example.com", employee="EMP-2", employee_name="Bob",
                                   workflow_status=oa_entry.STATUS_COMPLETED, expense_lines=[line], steps=[step]),
    }
    _install_report_requests(monkeypatch, docs)
    for roles in (["Employee"], ["Employee", "HR Manager"], ["HR User"]):
        monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None, roles=roles: roles)
        for view in ("mine", "all"):
            stats = oa_entry.get_expense_statistics(view=view, employee="EMP-2")
            records = oa_entry.list_expense_approval_records(view=view, employee="EMP-2")
            assert {row["request_name"] for row in stats["rows"]} <= {"REQ-MINE"}, (roles, view)
            assert {row["request_name"] for row in records["records"]} <= {"REQ-MINE"}, (roles, view)
    monkeypatch.setattr(frappe_stub, "get_roles", lambda user=None: ["Accounts User"])
    stats = oa_entry.get_expense_statistics(view="all", employee="EMP-2")
    records = oa_entry.list_expense_approval_records(view="all", employee="EMP-2")
    assert {row["request_name"] for row in stats["rows"]} == {"REQ-BOB"}
    assert {row["request_name"] for row in records["records"]} == {"REQ-BOB"}



def _handle_step(index, key, label, status, approver):
    step = _workflow_step(index, key, label, status, approver)
    step.mode = "handle"
    return step


def test_payment_step_allows_add_sign_before_only_and_the_new_step_is_pending():
    # 决定 D6：付款节点只能前加签；前加签的节点是审批节点，状态为待审批。
    base = _handle_step(1, "pay", "出纳确认付款", oa_entry.STATUS_WAIT_HANDLE, "cashier@example.com")
    doc = _dynamic_workflow_doc([base], 1)
    with pytest.raises(ValidationError, match="前面加签"):
        oa_entry._insert_add_sign_step(doc, base, "user-a@example.com", "after", "check", "cashier@example.com")
    inserted = oa_entry._insert_add_sign_step(doc, base, "user-a@example.com", "before", "check", "cashier@example.com")
    assert inserted.status == oa_entry.STATUS_PENDING
    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert doc.steps[1].step_key == "pay" and doc.steps[1].status == oa_entry.STATUS_WAIT_FLOW


def test_contract_delivery_step_cannot_add_sign():
    # 审查 E1（决定 D9）。
    base = _workflow_step(1, "delivery", "合同交期确认", oa_entry.STATUS_PENDING, "pmc@example.com", origin="contract_delivery")
    doc = _dynamic_workflow_doc([base], 1)
    with pytest.raises(ValidationError, match="合同交期"):
        oa_entry._insert_add_sign_step(doc, base, "user-a@example.com", "before", "check", "pmc@example.com")
    assert oa_entry._is_contract_delivery_step(base) is True


def test_payment_is_refused_while_an_old_after_sign_step_is_open(monkeypatch):
    # 审查 X1-5：旧数据里付款节点后面挂着加签节点时，不能直接置为已付款。
    environment = _install_request_environment(monkeypatch)
    pay = _handle_step(1, "pay", "出纳确认付款", oa_entry.STATUS_WAIT_HANDLE, "cashier@example.com")
    orphan = _workflow_step(2, "added", "加签：x", oa_entry.STATUS_WAIT_FLOW, "x@example.com", origin="add_sign")
    doc = _dynamic_workflow_doc([pay, orphan], 1)
    doc.workflow_status = oa_entry.STATUS_WAIT_HANDLE
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["cashier@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"cashier@example.com"})
    with pytest.raises(ValidationError, match="加签"):
        oa_entry.action_request(doc.name, "approve", "paid")
    assert pay.status == oa_entry.STATUS_WAIT_HANDLE


def test_add_sign_refuses_the_applicant_and_keeps_the_callers_expense_summary(monkeypatch):
    # 审查 #6：不能把申请人加为审批人；审查 #4：费用明细在改节点之前取好。
    environment = _install_request_environment(monkeypatch)
    steps = [_workflow_step(1, "step-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com")]
    doc = _dynamic_workflow_doc(steps, 1)
    object.__setattr__(doc, "owner", "alice@example.com")
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["manager@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"manager@example.com"})
    monkeypatch.setattr(oa_entry, "_resolve_add_sign_approver", lambda value: value, raising=False)
    with pytest.raises(ValidationError, match="申请人"):
        oa_entry.add_sign_request(doc.name, "alice@example.com", "before", "please review")

    order = []
    monkeypatch.setattr(oa_entry, "_with_expense_attachments", lambda current, lines: order.append("lines") or ["LINES"])
    original_insert = oa_entry._insert_add_sign_step
    monkeypatch.setattr(oa_entry, "_insert_add_sign_step", lambda *args: order.append("insert") or original_insert(*args))
    summaries = []
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current, authorized_expense_lines=None: summaries.append(authorized_expense_lines) or {})
    oa_entry.add_sign_request(doc.name, "user-a@example.com", "before", "please review")
    assert order == ["lines", "insert"]
    assert summaries == [["LINES"]]


def test_approval_people_lookup_is_for_the_current_approver_and_active_staff(monkeypatch):
    # 审查 #7（决定 D8）。
    environment = _install_request_environment(monkeypatch)
    steps = [_workflow_step(1, "step-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com")]
    doc = _dynamic_workflow_doc(steps, 1)
    object.__setattr__(doc, "owner", "alice@example.com")
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    with pytest.raises(ValidationError):
        oa_entry.list_approval_people("a")
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda current, user=None: False)
    with pytest.raises(ValidationError):
        oa_entry.list_approval_people("a", name=doc.name)
    monkeypatch.setattr(oa_entry, "_can_act_on_current_step", lambda current, user=None: True)
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"manager@example.com"})
    calls = []

    def get_all(doctype, filters=None, **kwargs):
        calls.append((doctype, filters))
        if doctype == "Employee":
            return ["alice@example.com", "bob@example.com", "manager@example.com"]
        return [{"name": name, "full_name": name} for name in filters["name"][1]]

    monkeypatch.setattr(frappe_stub, "get_all", get_all, raising=False)
    people = oa_entry.list_approval_people("", name=doc.name)
    assert [row["user"] for row in people] == ["bob@example.com"]
    assert calls[0] == ("Employee", {"status": "Active", "user_id": ["is", "set"]})



def test_approval_refuses_a_step_the_page_did_not_show(monkeypatch):
    # 审查 #10（决定 D10）：双击或旧页面不能把下一步也批掉。
    environment = _install_request_environment(monkeypatch)
    steps = [
        _workflow_step(1, "step-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com"),
        _workflow_step(2, "step-2", "director", oa_entry.STATUS_WAIT_FLOW, "manager@example.com"),
    ]
    doc = _dynamic_workflow_doc(steps, 1)
    object.__setattr__(doc, "environment", environment)
    environment.committed[doc.name] = doc
    monkeypatch.setattr(service, "_transaction_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda current_step, user=None: ["manager@example.com"])
    monkeypatch.setattr(oa_entry, "_actor_names", lambda user=None: {"manager@example.com"})
    oa_entry.action_request(doc.name, "approve", "ok", expected_step_key="step-1")
    assert doc.current_step_index == 2
    with pytest.raises(ValidationError, match="已经变化"):
        oa_entry.action_request(doc.name, "approve", "double click", expected_step_key="step-1")
    assert steps[1].status == oa_entry.STATUS_PENDING
    with pytest.raises(ValidationError, match="已经变化"):
        oa_entry.add_sign_request(doc.name, "x@example.com", "before", "late", expected_step_key="step-1")


def test_web_requests_must_name_the_step_but_server_code_need_not(monkeypatch):
    from types import SimpleNamespace

    step = _workflow_step(1, "step-1", "manager", oa_entry.STATUS_PENDING, "manager@example.com")
    doc = _dynamic_workflow_doc([step], 1)
    monkeypatch.setattr(frappe_stub, "local", SimpleNamespace(request=None), raising=False)
    oa_entry._require_expected_step(doc, step, None)
    monkeypatch.setattr(frappe_stub, "local", SimpleNamespace(request=object()), raising=False)
    with pytest.raises(ValidationError, match="页面版本过旧"):
        oa_entry._require_expected_step(doc, step, "")
    oa_entry._require_expected_step(doc, step, "step-1")



def test_approval_summary_counts_new_claim_types_and_follows_feature_gates(monkeypatch):
    # 审查 E3：报销单、付款单、出差原来不计入待办；审查 #8：关闭的类型不统计。
    docs = {
        "C-1": Row(name="C-1", request_type=oa_entry.REQUEST_REIMBURSEMENT, workflow_status=oa_entry.STATUS_PENDING, current_step_index=1, steps=[]),
        "T-1": Row(name="T-1", request_type=oa_entry.REQUEST_TRAVEL, workflow_status=oa_entry.STATUS_PENDING, current_step_index=1, steps=[]),
    }
    seen = []
    monkeypatch.setattr(frappe_stub, "get_all", lambda *_args, **kwargs: seen.append(kwargs["filters"]) or [{"name": name} for name in docs], raising=False)
    monkeypatch.setattr(oa_entry, "_load_request", lambda name: docs[name])
    monkeypatch.setattr(oa_entry, "_current_step", lambda doc: Row(step_index=1))
    monkeypatch.setattr(oa_entry, "_matched_approvers", lambda _step, user=None: ["me@example.com"])
    monkeypatch.setattr(oa_entry, "visible_request_types", lambda types, user=None: [t for t in types if t != oa_entry.REQUEST_TRAVEL])
    frappe_stub.session.user = "me@example.com"
    frappe_stub.get_roles = lambda user=None: ["Employee"]

    result = oa_entry.get_my_approval_summary()

    counts = {row["key"]: row["count"] for row in result["categories"]}
    assert counts["reimbursement"] == 1 and "travel" not in counts
    assert result["total"] == 1
    assert oa_entry.REQUEST_TRAVEL not in seen[0]["request_type"][1]



def test_submitting_without_an_active_employee_is_refused(monkeypatch):
    # 审查 X3-12（决定 D5）：没有在职员工档案的账号不能提交；内部重算（驳回退回草稿）不受影响。
    monkeypatch.setattr(oa_entry, "_employee_context", lambda user=None, employee=None: {
        "employee": None, "employee_name": "", "applicant_user": "admin@example.com", "department": "",
        "supervisor": "", "supervisor_user": "", "supervisor_decision": "", "supervisor_path": [],
        "upper_supervisor": "", "upper_supervisor_user": "",
    })
    with pytest.raises(ValidationError, match="在职员工档案"):
        oa_entry._route_context("财务部", "副总", request_type=oa_entry.REQUEST_EXPENSE_PAYMENT, require_employee=True)
    ctx = oa_entry._route_context("财务部", "副总", request_type=oa_entry.REQUEST_EXPENSE_PAYMENT)
    assert ctx["supervisor"] == "副总"



def test_approval_note_is_length_limited(monkeypatch):
    # 审查 E5：通过时的意见原来没有长度限制。
    with pytest.raises(ValidationError):
        oa_entry.action_request("REQ-X", "approve", "x" * 1001)
