from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest


class ValidationError(Exception):
    pass


_had_frappe = "frappe" in sys.modules
_had_requests = "requests" in sys.modules
frappe_stub_module = types.ModuleType("frappe")
frappe_stub_module.ValidationError = ValidationError
frappe_stub_module.PermissionError = type("PermissionError", (Exception,), {})
frappe_stub_module._ = lambda value: value
frappe_stub_module.session = types.SimpleNamespace(user="alice@example.com")
frappe_stub_module.whitelist = lambda *args, **kwargs: (lambda function: function)
frappe_stub_module.throw = lambda message, exc=ValidationError: (_ for _ in ()).throw(exc(message))
frappe_stub_module.utils = types.ModuleType("frappe.utils")
frappe_stub_module.utils.now_datetime = lambda: datetime(2026, 7, 21, 9, 0, 0)
sys.modules.setdefault("frappe", frappe_stub_module)
sys.modules.setdefault("frappe.utils", frappe_stub_module.utils)
requests_stub_module = types.ModuleType("requests")
requests_stub_module.RequestException = type("RequestException", (Exception,), {})
requests_stub_module.post = Mock()
sys.modules.setdefault("requests", requests_stub_module)

service = importlib.import_module("rayher_hr_payroll.invoice_ocr.service")
client = importlib.import_module("rayher_hr_payroll.invoice_ocr.client")
jobs_module = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
api_module = importlib.import_module("rayher_hr_payroll.api.invoice_entry")
if not _had_frappe:
    sys.modules.pop("frappe", None)
    sys.modules.pop("frappe.utils", None)
if not _had_requests:
    sys.modules.pop("requests", None)


class Doc(dict):
    def __init__(self, environment, values):
        super().__init__(values)
        object.__setattr__(self, "environment", environment)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def __setattr__(self, key, value):
        self[key] = value

    def insert(self, ignore_permissions=False):
        assert ignore_permissions is True
        self.environment.insert(self)
        return self

    def save(self, ignore_permissions=False):
        assert ignore_permissions is True
        self.environment.saved.append(self)
        return self

    def get_full_path(self):
        return self.get("full_path")

    def check_permission(self, *_args, **_kwargs):
        if not self.environment.read_allowed:
            raise ValidationError("denied")


class FakeLock:
    def __init__(self, environment, key, kwargs):
        self.environment = environment
        self.key = key
        self.kwargs = kwargs

    def __enter__(self):
        self.environment.locks.append((self.key, self.kwargs))
        return self

    def __exit__(self, *_args):
        return False


class FakeCache:
    def __init__(self, environment):
        self.environment = environment

    def lock(self, key, **kwargs):
        return FakeLock(self.environment, key, kwargs)


class FakeDB:
    def __init__(self, environment):
        self.environment = environment

    def get_value(self, doctype, filters, fieldname, as_dict=False, **_kwargs):
        if doctype == "File":
            for doc in self.environment.docs[doctype].values():
                if isinstance(filters, dict) and doc.get("file_url") == filters.get("file_url"):
                    return doc.get(fieldname)
        if doctype == service.LINE_DOCTYPE:
            for doc in self.environment.docs[doctype].values():
                if all(doc.get(key) == value for key, value in filters.items()):
                    if isinstance(fieldname, (list, tuple)):
                        result = {key: doc.get(key) for key in fieldname}
                        return result if as_dict else tuple(result.values())
                    return doc.get(fieldname)
        if isinstance(filters, str):
            doc = self.environment.docs.get(doctype, {}).get(filters)
            if not doc:
                return None
            if isinstance(fieldname, (list, tuple)):
                result = {key: doc.get(key) for key in fieldname}
                return result if as_dict else tuple(result.values())
            return doc.get(fieldname)
        return None

    def commit(self):
        self.environment.commits += 1


class Environment:
    def __init__(self, root):
        self.root = root
        self.docs = {name: {} for name in [service.BATCH_DOCTYPE, service.RECORD_DOCTYPE, "File", service.REQUEST_DOCTYPE, service.LINE_DOCTYPE, service.VIEW_LOG_DOCTYPE]}
        self.counters = {service.BATCH_DOCTYPE: 0, service.RECORD_DOCTYPE: 0, service.VIEW_LOG_DOCTYPE: 0, "File": 0}
        self.saved = []
        self.inserted = []
        self.locks = []
        self.enqueued = []
        self.commits = 0
        self.roles = {"alice@example.com": ["Employee"], "finance@example.com": ["Accounts User"], "admin@example.com": ["System Manager"]}
        self.read_allowed = True
        self.permission_allowed = True
        self.db = FakeDB(self)

    def insert(self, doc):
        doctype = doc["doctype"]
        if not doc.get("name"):
            self.counters[doctype] = self.counters.get(doctype, 0) + 1
            prefix = {service.BATCH_DOCTYPE: "BATCH", service.RECORD_DOCTYPE: "INV", service.VIEW_LOG_DOCTYPE: "LOG", "File": "FILE"}.get(doctype, "DOC")
            doc["name"] = f"{prefix}-{self.counters[doctype]}"
        self.docs.setdefault(doctype, {})[doc["name"]] = doc
        self.inserted.append(doc)

    def get_doc(self, doctype_or_values, name=None):
        if isinstance(doctype_or_values, dict):
            return Doc(self, dict(doctype_or_values))
        try:
            return self.docs[doctype_or_values][name]
        except KeyError:
            raise ValidationError("not found")

    def get_all(self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None, **_kwargs):
        rows = []
        for doc in self.docs.get(doctype, {}).values():
            matched = True
            for key, wanted in (filters or {}).items():
                actual = doc.get(key)
                if isinstance(wanted, (list, tuple)) and wanted and wanted[0] == "!=":
                    matched = actual != wanted[1]
                else:
                    matched = actual == wanted
                if not matched:
                    break
            if matched:
                rows.append({field: doc.get(field) for field in (fields or ["name"])})
        if limit_page_length is not None:
            rows = rows[:limit_page_length]
        return rows

    def cache(self):
        return FakeCache(self)

    def enqueue(self, method, **kwargs):
        self.enqueued.append((method, kwargs))

    def add_batch(self, name="BATCH-1", **values):
        defaults = dict(doctype=service.BATCH_DOCTYPE, name=name, owner="alice@example.com", uploaded_by="alice@example.com", batch_status="待上传", expires_on=datetime(2026, 7, 28), total_count=0, queued_count=0, processing_count=0, pending_confirmation_count=0, confirmed_count=0, duplicate_count=0, failed_count=0, excluded_count=0)
        defaults.update(values)
        doc = Doc(self, defaults); self.docs[service.BATCH_DOCTYPE][name] = doc; return doc

    def add_file(self, filename="invoice.pdf", content=b"%PDF-1.7\n", owner="alice@example.com", is_private=1, attached=True, batch="BATCH-1"):
        path = self.root / filename
        path.write_bytes(content)
        name = f"FILE-{len(self.docs['File']) + 1}"
        doc = Doc(self, dict(doctype="File", name=name, file_name=filename, file_url=f"/private/files/{filename}", file_size=len(content), owner=owner, is_private=is_private, attached_to_doctype=service.BATCH_DOCTYPE if attached else "", attached_to_name=batch if attached else "", full_path=str(path)))
        self.docs["File"][name] = doc
        return doc

    def add_record(self, name="INV-1", **values):
        defaults = dict(doctype=service.RECORD_DOCTYPE, name=name, owner="alice@example.com", batch="BATCH-1", uploaded_by="alice@example.com", invoice_file="/private/files/invoice.pdf", original_filename="invoice.pdf", mime_type="application/pdf", file_size=9, file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(), recognition_status="待确认", invoice_category="", project_name="", issue_date=None, invoice_number="", amount_before_tax=None, tax_amount=None, total_amount=None, ocr_payload="", field_warnings="[]", duplicate_of="", duplicate_reason="", request="", expense_line_key="", confirmed_by="", confirmed_on=None, processing_error="", retry_count=0)
        defaults.update(values)
        doc = Doc(self, defaults); self.docs[service.RECORD_DOCTYPE][name] = doc; return doc


@pytest.fixture
def env(tmp_path, monkeypatch):
    environment = Environment(tmp_path)
    frappe_stub_module.session.user = "alice@example.com"
    frappe_stub_module.db = environment.db
    frappe_stub_module.get_doc = environment.get_doc
    frappe_stub_module.get_all = environment.get_all
    frappe_stub_module.cache = environment.cache
    frappe_stub_module.enqueue = environment.enqueue
    frappe_stub_module.get_roles = lambda user=None: environment.roles.get(user or frappe_stub_module.session.user, [])
    frappe_stub_module.has_permission = lambda *args, **kwargs: environment.permission_allowed
    frappe_stub_module.conf = types.SimpleNamespace(invoice_ocr_url="http://invoice-ocr:8080")
    frappe_stub_module.local = types.SimpleNamespace(request=None)
    monkeypatch.setattr(service, "can_read_invoice", lambda doc, user=None: environment.read_allowed and (doc.get("owner") == (user or frappe_stub_module.session.user) or bool(set(environment.roles.get(user or frappe_stub_module.session.user, [])) & {"System Manager", "Accounts User"}) or bool(doc.get("request"))))
    return environment


def _valid_payload(record_id="INV-1"):
    return {"record_id": record_id, "source_filename": "invoice.pdf", "file_sha256": "a" * 64, "status": "needs_confirmation", "fields": {"invoice_category": "电子发票（普通发票）", "project_name": "文具；服务", "issue_date": "2026-07-14", "invoice_number": "000123", "amount_before_tax": "100.00", "tax_amount": "6.00", "total_amount": "106.00"}, "field_confidence": {}, "warnings": [], "ocr_lines": [], "processing_ms": 12, "duplicate": {"is_duplicate": False}}


class Response:
    def __init__(self, status=200, payload=None, raw=None):
        self.status_code = status
        self._payload = payload
        self.content = raw if raw is not None else json.dumps(payload or {}).encode()

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_client_uses_internal_multipart_contract_and_timeouts(env, monkeypatch):
    post = Mock(return_value=Response(payload=_valid_payload()))
    monkeypatch.setattr(client.requests, "post", post)
    result = client.recognize_document(b"%PDF-1.7", "invoice.pdf", "INV-1")
    assert result["fields"]["invoice_number"] == "000123"
    args, kwargs = post.call_args
    assert args == ("http://invoice-ocr:8080/v1/recognize",)
    assert kwargs["data"] == {"record_id": "INV-1"}
    assert kwargs["files"]["file"][:2] == ("invoice.pdf", b"%PDF-1.7")
    assert kwargs["timeout"] == (3.05, 120)


@pytest.mark.parametrize("response", [Response(status=500, raw=b"SECRET http://private/path"), Response(payload=ValueError("SECRET"), raw=b"bad"), Response(payload={"status": "needs_confirmation"})])
def test_client_sanitizes_sidecar_failures(env, monkeypatch, response):
    monkeypatch.setattr(client.requests, "post", Mock(return_value=response))
    with pytest.raises(client.OCRServiceError) as caught:
        client.recognize_document(b"SECRET-INVOICE", "invoice.pdf", "INV-1")
    message = str(caught.value)
    assert "SECRET" not in message and "http://" not in message and "path" not in message


def test_client_rejects_invalid_config_without_network(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "file:///private/ocr"
    post = Mock()
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")
    post.assert_not_called()


def test_create_batch_uses_only_server_owned_audit_and_random_token(env):
    first = service.create_batch(); second = service.create_batch()
    assert first["batch_status"] == "待上传"
    assert first["temporary_token"] != second["temporary_token"]
    assert len(first["temporary_token"]) >= 32
    doc = env.docs[service.BATCH_DOCTYPE][first["name"]]
    assert doc.owner == doc.uploaded_by == "alice@example.com"
    assert doc.expires_on == datetime(2026, 7, 28, 9, 0, 0)


def test_register_file_uses_real_server_metadata_forces_private_and_queues_after_commit(env):
    env.add_batch(); file_doc = env.add_file(filename="server.pdf", content=b"%PDF-1.7\nreal")
    result = service.register_file("BATCH-1", file_doc.file_url, original_filename="spoof.png", mime_type="image/png", file_size=1)
    assert result["recognition_status"] == "排队中"
    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    assert record.original_filename == "server.pdf" and record.mime_type == "application/pdf" and record.file_size == len(b"%PDF-1.7\nreal")
    assert record.file_sha256 == hashlib.sha256(b"%PDF-1.7\nreal").hexdigest()
    assert file_doc.is_private == 1 and file_doc.attached_to_doctype == service.RECORD_DOCTYPE and file_doc.attached_to_name == record.name
    assert env.enqueued == [("rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice", {"invoice_name": record.name, "queue": "long", "enqueue_after_commit": True})]
    assert env.locks[0][0] == "invoice:batch:BATCH-1"
    assert any(key == f"invoice:file:{record.file_sha256}" for key, _kwargs in env.locks)


@pytest.mark.parametrize("url", ["/files/public.pdf", "/private/files/../secret.pdf", "/private/files/a.pdf?x=1", "/private/files/%2Fsecret.pdf"])
def test_register_rejects_malicious_or_nonprivate_url(env, url):
    env.add_batch()
    with pytest.raises(ValidationError):
        service.register_file("BATCH-1", url)


def test_register_rejects_nonprivate_nonowner_and_false_signature(env):
    env.add_batch(); public = env.add_file(filename="public.pdf", is_private=0)
    with pytest.raises(ValidationError, match="私有"):
        service.register_file("BATCH-1", public.file_url)
    other = env.add_file(filename="other.pdf", owner="other@example.com")
    with pytest.raises(ValidationError, match="本人"):
        service.register_file("BATCH-1", other.file_url)
    fake = env.add_file(filename="fake.pdf", content=b"not a pdf")
    with pytest.raises(ValidationError, match="扩展名"):
        service.register_file("BATCH-1", fake.file_url)


def test_register_hard_limits_real_file_even_when_declared_size_is_forged(env):
    env.add_batch(); oversized = env.add_file(filename="large.pdf", content=b"%PDF-" + b"x" * (service.MAX_FILE_BYTES + 1))
    oversized.file_size = 1
    with pytest.raises(ValidationError, match="10 MB"):
        service.register_file("BATCH-1", oversized.file_url)


def test_register_exact_duplicate_across_batch_is_suspected_and_not_queued(env):
    env.add_batch(); file_doc = env.add_file(content=b"%PDF-duplicate")
    prior = env.add_record(name="INV-OLD", file_sha256=hashlib.sha256(b"%PDF-duplicate").hexdigest(), recognition_status="已确认")
    result = service.register_file("BATCH-1", file_doc.file_url)
    assert result["recognition_status"] == "疑似重复" and result["is_duplicate"] is True
    current = env.docs[service.RECORD_DOCTYPE][result["name"]]
    assert current.duplicate_of == prior.name and env.enqueued == []


def test_twentieth_file_allowed_and_twenty_first_rejected(env):
    env.add_batch()
    for index in range(20): env.add_record(name=f"INV-{index}", batch="BATCH-1")
    file_doc = env.add_file(filename="next.pdf")
    with pytest.raises(ValidationError, match="最多上传 20"):
        service.register_file("BATCH-1", file_doc.file_url)


@pytest.mark.parametrize("statuses,expected", [([], "待上传"), (["排队中", "失败"], "处理中"), (["待确认", "疑似重复"], "待确认"), (["失败"], "失败"), (["失败", "已确认"], "部分失败"), (["已确认", "已排除"], "已完成")])
def test_batch_aggregation_precedence_and_counts(env, statuses, expected):
    batch = env.add_batch()
    for index, status in enumerate(statuses): env.add_record(name=f"INV-{index}", recognition_status=status)
    service.recompute_batch(batch.name)
    assert batch.batch_status == expected and batch.total_count == len(statuses)
    assert batch.failed_count == statuses.count("失败") and batch.duplicate_count == statuses.count("疑似重复")


def test_confirm_rejects_client_controlled_duplicate_state_without_loading_record(env):
    with pytest.raises(ValidationError, match="重复状态只能由服务端更新"):
        service.confirm_invoice("INV-404", {"recognition_status": "已确认", "duplicate_of": ""})


def test_update_only_seven_fields_and_normalizes_money_date(env):
    env.add_batch(); record = env.add_record()
    result = service.update_invoice(record.name, {"invoice_number": " 000123 ", "issue_date": "2026-07-14", "total_amount": "35.980"})
    assert result["invoice_number"] == "000123" and result["issue_date"] == "2026-07-14" and record.total_amount == Decimal("35.98")
    with pytest.raises(ValidationError, match="只能修改"):
        service.update_invoice(record.name, {"owner": "attacker@example.com"})


def test_confirm_allows_missing_fields_but_stamps_server_audit(env):
    env.add_batch(); record = env.add_record(invoice_number="", issue_date=None, total_amount=None)
    result = service.confirm_invoice(record.name, {"invoice_category": "电子发票（普通发票）"})
    assert result["recognition_status"] == "已确认" and record.confirmed_by == "alice@example.com" and record.confirmed_on == datetime(2026, 7, 21, 9, 0, 0)


def test_confirm_detects_business_duplicate_under_lock(env):
    env.add_batch(); prior = env.add_record(name="INV-OLD", recognition_status="已确认", invoice_number="0001", issue_date="2026-07-14", total_amount=Decimal("35.98"))
    current = env.add_record(name="INV-NEW", invoice_number="0001", issue_date="2026-07-14", total_amount=Decimal("35.98"))
    with pytest.raises(ValidationError, match="疑似重复"):
        service.confirm_invoice(current.name)
    assert current.recognition_status == "疑似重复" and current.duplicate_of == prior.name
    assert env.locks[-1][0] == "invoice:business:0001|2026-07-14|35.98"


def test_resolve_duplicate_requires_finance_and_reason_and_preserves_reference(env):
    env.add_batch(); record = env.add_record(recognition_status="疑似重复", duplicate_of="INV-OLD", duplicate_reason="same")
    with pytest.raises(ValidationError, match="仅财务"):
        service.resolve_duplicate(record.name, "checked")
    frappe_stub_module.session.user = "finance@example.com"
    with pytest.raises(ValidationError, match="原因"):
        service.resolve_duplicate(record.name, "")
    result = service.resolve_duplicate(record.name, "核对原票无误")
    assert result["recognition_status"] == "待确认" and record.duplicate_of == "INV-OLD" and "核对原票无误" in record.duplicate_reason


def test_retry_and_exclude_have_explicit_state_rules(env):
    env.add_batch(); file_doc = env.add_file(); failed = env.add_record(recognition_status="失败", processing_error="safe", invoice_file=file_doc.file_url, file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest())
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE; file_doc.attached_to_name = failed.name
    service.retry_invoice(failed.name)
    assert failed.recognition_status == "排队中" and failed.processing_error == "" and env.enqueued[-1][1]["enqueue_after_commit"] is True
    pending = env.add_record(name="INV-P", recognition_status="待确认")
    with pytest.raises(ValidationError, match="原因"): service.exclude_invoice(pending.name, "")
    service.exclude_invoice(pending.name, "个人消费")
    assert pending.recognition_status == "已排除" and pending.invoice_file


def test_link_validates_line_ownership_and_allows_many_invoices_per_line(env):
    env.add_batch(); request = Doc(env, dict(doctype=service.REQUEST_DOCTYPE, name="REQ-1", workflow_status="草稿")); env.docs[service.REQUEST_DOCTYPE][request.name] = request
    line = Doc(env, dict(doctype=service.LINE_DOCTYPE, name="LINE-1", parent="REQ-1", parenttype=service.REQUEST_DOCTYPE, parentfield="expense_lines", line_key="KEY-1")); env.docs[service.LINE_DOCTYPE][line.name] = line
    one = env.add_record(name="INV-1", recognition_status="已确认"); two = env.add_record(name="INV-2", recognition_status="已确认")
    service.link_invoice(one.name, request.name, "KEY-1"); service.link_invoice(two.name, request.name, "KEY-1")
    assert one.expense_line_key == two.expense_line_key == "KEY-1" and one.request == two.request == "REQ-1"
    with pytest.raises(ValidationError, match="不属于"):
        service.link_invoice(env.add_record(name="INV-3", recognition_status="已确认").name, request.name, "OTHER")


def test_preview_logs_view_and_never_returns_disk_path(env):
    env.add_batch(); file_doc = env.add_file(); record = env.add_record(invoice_file=file_doc.file_url, file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest())
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE; file_doc.attached_to_name = record.name
    result = service.preview_invoice(record.name)
    assert result["file_url"] == "/private/files/invoice.pdf" and "full_path" not in result and "download" not in result
    log = env.inserted[-1]
    assert log.doctype == service.VIEW_LOG_DOCTYPE and log.invoice_record == record.name and log.action == "查看"


def test_guest_is_rejected_before_any_insert(env):
    frappe_stub_module.session.user = "Guest"
    with pytest.raises(ValidationError, match="登录"):
        service.create_batch()
    assert env.inserted == []


def _queued_record_with_file(env, *, name="INV-JOB", content=b"%PDF-1.7\n"):
    env.add_batch()
    file_doc = env.add_file(content=content)
    record = env.add_record(
        name=name,
        recognition_status="排队中",
        invoice_file=file_doc.file_url,
        original_filename=file_doc.file_name,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = record.name
    return record, file_doc


def test_job_saves_complete_payload_and_seven_candidates_without_trusting_source(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    payload["source_filename"] = "sidecar-name.pdf"
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(return_value=payload))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "待确认"
    assert record.invoice_category == "电子发票（普通发票）"
    assert record.project_name == "文具；服务"
    assert record.invoice_number == "000123" and record.total_amount == Decimal("106.00")
    assert json.loads(record.ocr_payload)["source_filename"] == "sidecar-name.pdf"
    assert record.original_filename == "invoice.pdf" and record.file_sha256 == hashlib.sha256(b"%PDF-1.7\n").hexdigest()
    assert record.field_warnings == "[]" and record.processing_error == ""
    assert env.commits >= 2 and (f"invoice:record:{record.name}", {"timeout": 60, "blocking_timeout": 15}) in env.locks


def test_job_business_duplicate_is_marked_under_business_lock(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env, name="INV-NEW")
    env.add_record(name="INV-OLD", recognition_status="已确认", invoice_number="000123", issue_date="2026-07-14", total_amount=Decimal("106.00"))
    payload = _valid_payload(record.name); payload["file_sha256"] = record.file_sha256
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(return_value=payload))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "疑似重复" and record.duplicate_of == "INV-OLD"
    assert any(key == "invoice:business:000123|2026-07-14|106.00" for key, _kwargs in env.locks)


def test_job_failure_is_per_record_sanitized_and_increments_retry(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(side_effect=RuntimeError("SECRET C:\\private\\invoice.pdf")))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "失败" and record.retry_count == 1
    assert "SECRET" not in record.processing_error and "C:\\private" not in record.processing_error
    assert env.docs[service.BATCH_DOCTYPE]["BATCH-1"].batch_status == "失败"


def test_job_is_idempotent_for_terminal_record(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    env.add_batch(); record = env.add_record(recognition_status="已确认")
    recognize = Mock(); monkeypatch.setattr(jobs.client, "recognize_document", recognize)
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "已确认"
    recognize.assert_not_called()

def test_whitelisted_api_has_explicit_bounded_signatures_and_delegates(env, monkeypatch):
    import inspect
    api = importlib.import_module("rayher_hr_payroll.api.invoice_entry")
    expected = {"create_batch", "register_file", "get_batch", "update_invoice", "confirm_invoice", "retry_invoice", "exclude_invoice", "link_invoice", "resolve_duplicate", "get_request_invoices", "preview_invoice"}
    for name in expected:
        function = getattr(api, name)
        assert all(parameter.kind not in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL} for parameter in inspect.signature(function).parameters.values())
    delegated = Mock(return_value={"ok": True})
    monkeypatch.setattr(api.service, "get_batch", delegated)
    assert api.get_batch("BATCH-1") == {"ok": True}
    delegated.assert_called_once_with("BATCH-1")
    with pytest.raises(ValidationError, match="标识"):
        api.get_batch("x" * 141)


def test_api_source_whitelists_only_public_endpoints():
    from pathlib import Path
    source = Path("rayher_hr_payroll/api/invoice_entry.py").read_text(encoding="utf-8")
    assert source.count("@frappe.whitelist") == 11
    assert "@frappe.whitelist\ndef _" not in source
    assert source.count('methods=["POST"]') == 9

def test_register_commits_record_visibility_before_releasing_duplicate_lock(env):
    env.add_batch(); file_doc = env.add_file(content=b"%PDF-concurrent")
    service.register_file("BATCH-1", file_doc.file_url)
    assert env.commits == 1


def test_confirm_commits_inside_business_lock_to_close_concurrent_confirm_race(env):
    env.add_batch(); record = env.add_record(invoice_number="0009", issue_date="2026-07-14", total_amount=Decimal("9.00"))
    service.confirm_invoice(record.name)
    assert record.recognition_status == "已确认"
    assert env.commits == 1
    assert any(key == "invoice:business:0009|2026-07-14|9.00" for key, _kwargs in env.locks)


def test_get_batch_hides_temporary_token_from_nonowner_request_reader(env):
    batch = env.add_batch(owner="other@example.com", request="REQ-1", temporary_token="SECRET-TOKEN")
    result = service.get_batch(batch.name)
    assert "temporary_token" not in result

def test_job_record_state_survives_batch_aggregation_failure(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    payload = _valid_payload(record.name); payload["file_sha256"] = record.file_sha256
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(return_value=payload))
    monkeypatch.setattr(jobs.service, "recompute_batch", Mock(side_effect=RuntimeError("SECRET batch failure")))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "待确认"
    assert env.commits >= 2

def test_duplicate_resolution_is_bound_to_reviewed_business_key(env):
    env.add_batch()
    env.add_record(name="INV-A", recognition_status="已确认", invoice_number="A-1", issue_date="2026-07-14", total_amount=Decimal("10.00"))
    prior_b = env.add_record(name="INV-B", recognition_status="已确认", invoice_number="B-1", issue_date="2026-07-15", total_amount=Decimal("20.00"))
    current = env.add_record(name="INV-C", recognition_status="疑似重复", duplicate_of="INV-A", invoice_number="A-1", issue_date="2026-07-14", total_amount=Decimal("10.00"))
    frappe_stub_module.session.user = "finance@example.com"
    service.resolve_duplicate(current.name, "已核对A票")
    frappe_stub_module.session.user = "alice@example.com"
    service.update_invoice(current.name, {"invoice_number": "B-1", "issue_date": "2026-07-15", "total_amount": "20.00"})
    with pytest.raises(ValidationError, match="疑似重复"):
        service.confirm_invoice(current.name)
    assert current.recognition_status == "疑似重复" and current.duplicate_of == prior_b.name

def test_every_whitelisted_api_rejects_guest_before_delegation(env, monkeypatch):
    api = importlib.import_module("rayher_hr_payroll.api.invoice_entry")
    frappe_stub_module.session.user = "Guest"
    for name in ["create_batch", "register_file", "get_batch", "update_invoice", "confirm_invoice", "retry_invoice", "exclude_invoice", "link_invoice", "resolve_duplicate", "get_request_invoices", "preview_invoice"]:
        monkeypatch.setattr(api.service, name, Mock(return_value={"leaked": True}))
    calls = [
        lambda: api.create_batch(),
        lambda: api.register_file("BATCH-1", "/private/files/a.pdf"),
        lambda: api.get_batch("BATCH-1"),
        lambda: api.update_invoice("INV-1", {}),
        lambda: api.confirm_invoice("INV-1", {}),
        lambda: api.retry_invoice("INV-1"),
        lambda: api.exclude_invoice("INV-1", "reason"),
        lambda: api.link_invoice("INV-1", "REQ-1", "LINE-1"),
        lambda: api.resolve_duplicate("INV-1", "reason"),
        lambda: api.get_request_invoices("REQ-1"),
        lambda: api.preview_invoice("INV-1"),
    ]
    for function in calls:
        with pytest.raises(ValidationError, match="登录"):
            function()

def test_client_sanitizes_transport_exception(env, monkeypatch):
    monkeypatch.setattr(client.requests, "post", Mock(side_effect=client.requests.RequestException("SECRET http://ocr/private")))
    with pytest.raises(client.OCRServiceError) as caught:
        client.recognize_document(b"SECRET-INVOICE", "invoice.pdf", "INV-1")
    assert "SECRET" not in str(caught.value) and "http://" not in str(caught.value)


def test_exact_ten_megabytes_and_twentieth_record_are_allowed(env):
    env.add_batch()
    for index in range(19):
        env.add_record(name=f"INV-EXISTING-{index}")
    content = b"%PDF-" + b"x" * (service.MAX_FILE_BYTES - 5)
    file_doc = env.add_file(filename="boundary.pdf", content=content)
    result = service.register_file("BATCH-1", file_doc.file_url)
    assert result["file_size"] == service.MAX_FILE_BYTES
    assert env.docs[service.BATCH_DOCTYPE]["BATCH-1"].total_count == 20


def test_cancelled_and_expired_unlinked_batches_reject_registration(env):
    cancelled = env.add_batch(name="BATCH-C", batch_status="已取消")
    expired = env.add_batch(name="BATCH-E", expires_on=datetime(2026, 7, 20))
    for batch in (cancelled, expired):
        with pytest.raises(ValidationError):
            service.register_file(batch.name, "/private/files/a.pdf")


def test_job_rejects_sidecar_hash_tampering_without_overwriting_server_hash(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    original_hash = record.file_sha256
    payload = _valid_payload(record.name)
    payload["file_sha256"] = "f" * 64
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(return_value=payload))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "失败"
    assert record.file_sha256 == original_hash