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
    monkeypatch.setattr(service, "frappe", frappe_stub)
    monkeypatch.setattr(oa_entry, "frappe", frappe_stub)
    monkeypatch.setattr(oa_entry, "now_datetime", frappe_stub.utils.now_datetime)
    frappe_stub.session.user = "alice@example.com"
    frappe_stub.get_roles = lambda user=None: ["Employee"]
    frappe_stub.local = types.SimpleNamespace(site="test.localhost")


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
        assert lock_order[-1] == ("request", request.name)
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


def test_attach_batch_uses_record_batch_request_lock_order_and_preserves_line_links(monkeypatch):
    batch, request, records, lock_order, saves = _attach_environment(monkeypatch)
    attached_request = service.attach_batch_to_request(batch.name, request)
    assert attached_request is request
    assert lock_order == [
        ("record", "INV-1"),
        ("record", "INV-2"),
        ("batch", "BATCH-1"),
        ("request", "REQ-1"),
    ]
    assert batch.request == request.name
    assert {record.request for record in records.values()} == {request.name}
    assert records["INV-1"].expense_line_key == "11111111-1111-4111-8111-111111111111"
    assert records["INV-2"].expense_line_key == ""
    assert request.invoice_count == 2 and request.invoice_status == "已确认"
    assert batch in saves and request in saves and all(record in saves for record in records.values())


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
        lambda doc: {"name": doc.name, "status": doc.workflow_status},
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
        lambda _doc: {"invoice_count": 0, "invoice_status": "无发票", "invoice_search_text": ""},
    )
    with pytest.raises(ValidationError, match="未确认"):
        oa_entry.create_request(
            oa_entry.REQUEST_EXPENSE_PAYMENT,
            submit=1,
            expense_lines=[{"category": "办公费", "amount": 1}],
            no_invoice_reason="有原因也不能绕过状态",
        )
    doc = environment.pending["REQ-NEW"]
    assert observed[-1] == (True, oa_entry.STATUS_DRAFT)
    assert doc.workflow_status == oa_entry.STATUS_DRAFT
    assert environment.commits == 0


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
            "expense_lines": [Row(line_key="11111111-1111-4111-8111-111111111111", amount=1, invoice_difference_reason="")],
            "steps": [],
            "no_invoice_reason": "纸质票据遗失",
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
        "validate_request_invoices",
        lambda current_doc, submitting: validations.append(
            (current_doc.name, submitting, current_doc.workflow_status)
        ),
    )
    result = oa_entry.submit_request("REQ-1")
    assert locks == [("request", "REQ-1")]
    assert environment.current_reads == [(service.REQUEST_DOCTYPE, "REQ-1")]
    assert validations[-1] == ("REQ-1", True, oa_entry.STATUS_DRAFT)
    assert doc.workflow_status == oa_entry.STATUS_PENDING
    assert result["status"] == oa_entry.STATUS_PENDING
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

    result = oa_entry.create_request(
        oa_entry.REQUEST_EXPENSE_PAYMENT,
        subject="expense",
        submit=requested_submit,
        expense_lines=[{"category": "office", "amount": "100.00"}],
        invoice_batch="BATCH-1",
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
    with pytest.raises(ValidationError, match="只有草稿"):
        service.attach_batch_to_request(batch.name, {"name": request.name})
    assert lock_order[-1] == ("request", request.name)
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
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current: {"name": current.name})
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
        assert lock_order[-1] == ("request", request.name)
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
    monkeypatch.setattr(oa_entry, "_summarize_doc", lambda current: {"name": current.name})
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
