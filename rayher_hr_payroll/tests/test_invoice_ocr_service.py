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


class FakeLatestCommittedCursor:
    def __init__(self, environment):
        self.environment = environment
        self.rows = []
        self.closed = False

    def execute(self, query, values):
        normalized = " ".join(str(query).split())
        request_name = str(values[0])
        self.environment.committed_read_calls.append(
            (normalized, tuple(values))
        )
        if "FOR UPDATE" in normalized.upper():
            raise AssertionError(
                "latest committed batch query must not lock batch rows"
            )
        if self.environment.register_locked_batch_row:
            self.environment.nonblocking_committed_reads += 1
        self.rows = sorted(
            (str(doc.get("name")),)
            for doc in self.environment.docs[service.BATCH_DOCTYPE].values()
            if str(doc.get("request") or "") == request_name
        )

    def fetchall(self):
        return list(self.rows)

    def close(self):
        self.closed = True


class FakeLatestCommittedConnection:
    def __init__(self, environment):
        self.environment = environment
        self.closed = False

    def cursor(self):
        return FakeLatestCommittedCursor(self.environment)

    def close(self):
        self.closed = True
        self.environment.committed_connections_closed += 1


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

    def get_connection(self):
        return FakeLatestCommittedConnection(self.environment)

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
        self.committed_read_calls = []
        self.committed_connections_closed = 0
        self.nonblocking_committed_reads = 0
        self.register_locked_batch_row = ""
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
        defaults = dict(doctype=service.RECORD_DOCTYPE, name=name, owner="alice@example.com", batch="BATCH-1", uploaded_by="alice@example.com", invoice_file="/private/files/invoice.pdf", original_filename="invoice.pdf", mime_type="application/pdf", file_size=9, file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(), recognition_status="待确认", invoice_category="", project_name="", issue_date=None, invoice_number="", amount_before_tax=None, tax_amount=None, total_amount=None, ocr_payload="", field_warnings="[]", duplicate_of="", duplicate_reason="", request="", expense_line_key="", confirmed_by="", confirmed_on=None, processing_started_on=None, processing_claim_id="", processing_error="", retry_count=0)
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
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("203.0.113.136", 8080))],
    )
    frappe_stub_module.local = types.SimpleNamespace(request=None)
    frappe_stub_module.form_dict = types.SimpleNamespace()
    monkeypatch.setattr(service, "can_read_invoice", lambda doc, user=None, **_kwargs: environment.read_allowed and (doc.get("owner") == (user or frappe_stub_module.session.user) or bool(set(environment.roles.get(user or frappe_stub_module.session.user, [])) & {"System Manager", "Accounts User"}) or bool(doc.get("request"))))
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
    assert args == ("http://203.0.113.136:8080/v1/recognize",)
    assert kwargs["headers"] == {"Host": "invoice-ocr:8080"}
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
    env.add_batch()
    file_doc = env.add_file(filename="server.pdf", content=b"%PDF-1.7\nreal")
    result = service.register_file("BATCH-1", file_doc.file_url)
    assert result["recognition_status"] == "排队中"
    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    assert record.original_filename == "server.pdf"
    assert record.mime_type == "application/pdf"
    assert record.file_size == len(b"%PDF-1.7\nreal")
    assert record.file_sha256 == hashlib.sha256(b"%PDF-1.7\nreal").hexdigest()
    assert file_doc.is_private == 1
    assert file_doc.attached_to_doctype == service.RECORD_DOCTYPE
    assert file_doc.attached_to_name == record.name
    assert env.enqueued == []
    env.db.commit()
    assert env.enqueued == [
        (
            "rayher_hr_payroll.invoice_ocr.jobs.recompute_invoice_batch",
            {"batch_name": "BATCH-1", "queue": "short", "enqueue_after_commit": False},
        ),
        (
            "rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice",
            {"invoice_name": record.name, "queue": "long"},
        ),
    ]
    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories[:3] == ["batch", "file", "file-hash"]


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


def test_serialized_money_preserves_ocr_blank_without_hiding_real_zero(env):
    env.add_batch()
    record = env.add_record(
        amount_before_tax=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        ocr_payload=json.dumps({"fields": {
            "amount_before_tax": None,
            "tax_amount": "0.00",
            "total_amount": None,
        }}),
        field_warnings=json.dumps(["required_fields_missing"]),
    )
    result = service._serialize_record(record)
    assert result["amount_before_tax"] is None
    assert result["tax_amount"] == Decimal("0.00")
    assert result["total_amount"] is None
    assert json.loads(result["field_warnings"]) == ["required_fields_missing"]


def test_manual_money_presence_overrides_ocr_presence_and_stays_internal(env):
    env.add_batch()
    record = env.add_record(
        total_amount=Decimal("0.00"),
        ocr_payload=json.dumps({"fields": {"total_amount": None}}),
        field_warnings=json.dumps(["required_fields_missing"]),
    )
    entered = service.update_invoice(record.name, {"total_amount": "0.00"})
    assert entered["total_amount"] == Decimal("0.00")
    assert json.loads(entered["field_warnings"]) == ["required_fields_missing"]
    assert "manual-field-presence:total_amount:present" in json.loads(record.field_warnings)

    cleared = service.update_invoice(record.name, {"total_amount": ""})
    assert cleared["total_amount"] is None
    assert "manual-field-presence:total_amount:blank" in json.loads(record.field_warnings)
    assert all("manual-field-presence:" not in item for item in json.loads(cleared["field_warnings"]))


def test_missing_ocr_total_does_not_create_zero_value_duplicate_key(env):
    env.add_batch()
    env.add_record(
        name="INV-OLD-ZERO",
        recognition_status="\u5df2\u786e\u8ba4",
        invoice_number="000123",
        issue_date="2026-07-14",
        total_amount=Decimal("0.00"),
        ocr_payload=json.dumps({"fields": {"total_amount": "0.00"}}),
    )
    record = env.add_record(
        name="INV-MISSING-TOTAL",
        invoice_number="000123",
        issue_date="2026-07-14",
        total_amount=Decimal("0.00"),
        ocr_payload=json.dumps({"fields": {"total_amount": None}}),
    )
    assert service._business_duplicate(record) == (None, None)


def test_confirm_allows_missing_fields_but_stamps_server_audit(env):
    env.add_batch(); record = env.add_record(invoice_number="", issue_date=None, total_amount=None)
    result = service.confirm_invoice(record.name, {"invoice_category": "电子发票（普通发票）"})
    assert result["recognition_status"] == "已确认" and record.confirmed_by == "alice@example.com" and record.confirmed_on == datetime(2026, 7, 21, 9, 0, 0)


def test_confirm_detects_business_duplicate_under_lock(env):
    env.add_batch()
    prior = env.add_record(
        name="INV-OLD",
        recognition_status="已确认",
        invoice_number="0001",
        issue_date="2026-07-14",
        total_amount=Decimal("35.98"),
    )
    current = env.add_record(
        name="INV-NEW",
        invoice_number="0001",
        issue_date="2026-07-14",
        total_amount=Decimal("35.98"),
    )
    result = service.confirm_invoice(current.name)
    assert result["recognition_status"] == "疑似重复"
    assert result["conflict"]["duplicate_of"] == prior.name
    assert current.duplicate_of == prior.name
    assert any(
        key == service._lock_key("business", "0001|2026-07-14|35.98")
        for key, _kwargs in env.locks
    )


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
    env.add_batch()
    file_doc = env.add_file()
    failed = env.add_record(
        recognition_status="失败",
        processing_error="safe",
        invoice_file=file_doc.file_url,
        file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = failed.name
    service.retry_invoice(failed.name)
    assert failed.recognition_status == "排队中"
    assert failed.processing_error == ""
    assert failed.processing_claim_id == ""
    assert env.enqueued == []
    env.db.commit()
    assert env.enqueued[-1][1] == {"invoice_name": failed.name, "queue": "long"}
    pending = env.add_record(name="INV-P", recognition_status="待确认")
    pending.processing_claim_id = "stale-claim"
    with pytest.raises(ValidationError, match="原因"):
        service.exclude_invoice(pending.name, "")
    service.exclude_invoice(pending.name, "个人消费")
    assert pending.recognition_status == "已排除" and pending.invoice_file
    assert pending.processing_claim_id == ""


def test_link_validates_line_ownership_and_allows_many_invoices_per_line(env):
    env.add_batch()
    request = Doc(
        env,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-1",
            "owner": "alice@example.com",
            "employee": "EMP-ALICE",
            "workflow_status": "草稿",
        },
    )
    env.docs[service.REQUEST_DOCTYPE][request.name] = request
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": "LINE-1",
            "parent": "REQ-1",
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": "KEY-1",
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    one = env.add_record(name="INV-1", recognition_status="已确认")
    two = env.add_record(name="INV-2", recognition_status="已确认")
    service.link_invoice(one.name, request.name, "KEY-1")
    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories[:3] == ["request", "batch", "record"]
    service.link_invoice(two.name, request.name, "KEY-1")
    assert one.expense_line_key == two.expense_line_key == "KEY-1"
    assert one.request == two.request == "REQ-1"
    assert request.invoice_count == 2
    assert request.invoice_status == "已确认"
    with pytest.raises(ValidationError, match="不属于"):
        service.link_invoice(
            env.add_record(name="INV-3", recognition_status="已确认").name,
            request.name,
            "OTHER",
        )


def test_preview_logs_view_and_never_returns_disk_path(env):
    env.add_batch()
    file_doc = env.add_file()
    record = env.add_record(
        invoice_file=file_doc.file_url,
        file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = record.name
    result = service.preview_invoice(record.name)
    assert "file_url" not in result and "full_path" not in result
    assert "/private/files/" not in result["preview_url"]
    assert not env.docs[service.VIEW_LOG_DOCTYPE]


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
    assert record.invoice_number == "000123"
    assert record.total_amount == Decimal("106.00")
    assert json.loads(record.ocr_payload)["source_filename"] == "sidecar-name.pdf"
    assert record.original_filename == "invoice.pdf"
    assert record.file_sha256 == hashlib.sha256(b"%PDF-1.7\n").hexdigest()
    assert record.field_warnings == "[]" and record.processing_error == ""
    assert record.processing_claim_id == ""
    assert env.commits >= 2
    assert (
        service._lock_key("record", record.name),
        {"timeout": 600, "blocking_timeout": 15},
    ) in env.locks


def test_job_business_duplicate_is_marked_under_business_lock(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env, name="INV-NEW")
    env.add_record(
        name="INV-OLD",
        recognition_status="已确认",
        invoice_number="000123",
        issue_date="2026-07-14",
        total_amount=Decimal("106.00"),
    )
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(return_value=payload))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "疑似重复"
    assert record.duplicate_of == "INV-OLD"
    assert any(
        key == service._lock_key("business", "000123|2026-07-14|106.00")
        for key, _kwargs in env.locks
    )


def test_job_failure_is_per_record_sanitized_and_increments_retry(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(side_effect=RuntimeError("SECRET C:\\private\\invoice.pdf")))
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "失败" and record.retry_count == 1
    assert "SECRET" not in record.processing_error and "C:\\private" not in record.processing_error
    assert record.processing_claim_id == ""
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
    expected = {"create_batch", "register_file", "get_batch", "update_invoice", "confirm_invoice", "retry_invoice", "exclude_invoice", "link_invoice", "resolve_duplicate", "get_request_invoices", "preview_invoice", "list_workbench", "unconfirm_invoice"}
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
    source = Path("rayher_hr_payroll/api/invoice_entry.py").read_text(encoding="utf-8")
    assert source.count("@frappe.whitelist") == 15
    assert "@frappe.whitelist\ndef _" not in source
    assert source.count('methods=["POST"]') == 13
    assert source.count('methods=["GET"]') == 0


def test_register_holds_reservations_for_top_level_auto_commit(env):
    env.add_batch()
    file_doc = env.add_file(content=b"%PDF-concurrent")
    service.register_file("BATCH-1", file_doc.file_url)
    assert env.commits == 0
    assert service._lock_key("batch", "BATCH-1") in env.active_locks
    env.db.commit()
    assert service._lock_key("batch", "BATCH-1") not in env.active_locks


def test_confirm_holds_business_lock_for_top_level_auto_commit(env):
    env.add_batch()
    record = env.add_record(
        invoice_number="0009",
        issue_date="2026-07-14",
        total_amount=Decimal("9.00"),
    )
    service.confirm_invoice(record.name)
    assert record.recognition_status == "已确认"
    assert env.commits == 0
    key = service._lock_key("business", "0009|2026-07-14|9.00")
    assert key in env.active_locks
    env.db.commit()
    assert key not in env.active_locks


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
    env.add_record(
        name="INV-A",
        recognition_status="已确认",
        invoice_number="A-1",
        issue_date="2026-07-14",
        total_amount=Decimal("10.00"),
    )
    prior_b = env.add_record(
        name="INV-B",
        recognition_status="已确认",
        invoice_number="B-1",
        issue_date="2026-07-15",
        total_amount=Decimal("20.00"),
    )
    current = env.add_record(
        name="INV-C",
        recognition_status="疑似重复",
        duplicate_of="INV-A",
        invoice_number="A-1",
        issue_date="2026-07-14",
        total_amount=Decimal("10.00"),
    )
    frappe_stub_module.session.user = "finance@example.com"
    service.resolve_duplicate(current.name, "已核对A票")
    frappe_stub_module.session.user = "alice@example.com"
    service.update_invoice(
        current.name,
        {
            "invoice_number": "B-1",
            "issue_date": "2026-07-15",
            "total_amount": "20.00",
        },
    )
    result = service.confirm_invoice(current.name)
    assert result["recognition_status"] == "疑似重复"
    assert result["conflict"]["duplicate_of"] == prior_b.name
    assert current.duplicate_of == prior_b.name


def test_every_whitelisted_api_rejects_guest_before_delegation(env, monkeypatch):
    api = importlib.import_module("rayher_hr_payroll.api.invoice_entry")
    frappe_stub_module.session.user = "Guest"
    for name in ["create_batch", "register_file", "get_batch", "update_invoice", "confirm_invoice", "retry_invoice", "exclude_invoice", "link_invoice", "resolve_duplicate", "get_request_invoices", "preview_invoice"]:
        monkeypatch.setattr(api.service, name, Mock(return_value={"leaked": True}))
    monkeypatch.setattr(api.service, "list_workbench_invoices", Mock(return_value={"leaked": True}))
    monkeypatch.setattr(api.service, "unconfirm_invoice", Mock(return_value={"leaked": True}))
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
        lambda: api.list_workbench(),
        lambda: api.unconfirm_invoice("INV-1"),
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
    assert env.docs[service.BATCH_DOCTYPE]["BATCH-1"].total_count == 0
    env.db.commit()
    _run_queued_batch_recomputes(env)
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

# --- Task 5 security/concurrency review RED tests ---

def _response_enter(self):
    return self


def _response_exit(self, *_args):
    self.closed = True
    return False


def _response_iter_content(self, chunk_size=64 * 1024):
    for offset in range(0, len(self.content), chunk_size):
        yield self.content[offset : offset + chunk_size]


Response.__enter__ = _response_enter
Response.__exit__ = _response_exit
Response.iter_content = _response_iter_content
Response.close = lambda self: setattr(self, "closed", True)
Response.headers = {}


def _add_request(env, name="REQ-1", *, owner="alice@example.com", employee="EMP-ALICE", status="草稿"):
    doc = Doc(
        env,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": name,
            "owner": owner,
            "employee": employee,
            "workflow_status": status,
        },
    )
    env.docs[service.REQUEST_DOCTYPE][name] = doc
    return doc


def test_employee_knowing_foreign_record_name_cannot_update_or_confirm(env):
    env.roles["bob@example.com"] = ["Employee"]
    env.add_batch(owner="alice@example.com")
    _add_request(env, owner="alice@example.com", employee="EMP-ALICE")
    record = env.add_record(owner="alice@example.com", request="REQ-1")
    frappe_stub_module.session.user = "bob@example.com"
    with pytest.raises(ValidationError, match="无权"):
        service.update_invoice(record.name, {"project_name": "blocked"})
    with pytest.raises(ValidationError, match="无权"):
        service.confirm_invoice(record.name)


def test_accounts_user_cannot_edit_applicant_invoice_fields(env):
    env.add_batch()
    record = env.add_record(owner="alice@example.com")
    frappe_stub_module.session.user = "finance@example.com"
    with pytest.raises(ValidationError, match="无权"):
        service.update_invoice(record.name, {"project_name": "blocked"})


def test_request_owner_or_employee_user_may_edit_but_approver_only_reads(env, monkeypatch):
    env.roles.update(
        {
            "owner@example.com": ["Employee"],
            "applicant@example.com": ["Employee"],
            "manager@example.com": ["Employee", "Department Manager"],
        }
    )
    env.add_batch(owner="uploader@example.com")
    request = _add_request(env, owner="owner@example.com", employee="EMP-APP")
    request.department = "Sales"
    record = env.add_record(owner="uploader@example.com", request=request.name)
    original_get_value = env.db.get_value

    def get_value(doctype, filters, fieldname, as_dict=False, **kwargs):
        if doctype == "Employee" and isinstance(filters, dict) and filters.get("user_id") in {"applicant@example.com", "manager@example.com"}:
            row = {"name": "EMP-APP" if filters.get("user_id") == "applicant@example.com" else "EMP-MGR", "employee_name": "Applicant", "department": "Sales"}
            return row if as_dict else row.get(fieldname)
        return original_get_value(doctype, filters, fieldname, as_dict=as_dict, **kwargs)

    monkeypatch.setattr(env.db, "get_value", get_value)
    frappe_stub_module.session.user = "owner@example.com"
    assert service.update_invoice(record.name, {"project_name": "owner"})["project_name"] == "owner"
    frappe_stub_module.session.user = "applicant@example.com"
    assert service.update_invoice(record.name, {"project_name": "employee"})["project_name"] == "employee"
    frappe_stub_module.session.user = "manager@example.com"
    assert service.get_request_invoices(request.name)
    with pytest.raises(ValidationError, match="无权"):
        service.update_invoice(record.name, {"project_name": "manager"})


def test_link_rejects_foreign_draft_even_when_generic_doctype_write_allows(env):
    env.add_batch()
    record = env.add_record(recognition_status="已确认")
    request = _add_request(env, name="REQ-FOREIGN", owner="bob@example.com", employee="EMP-BOB")
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": "LINE-1",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": "KEY-1",
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    env.permission_allowed = True
    with pytest.raises(ValidationError, match="无权"):
        service.link_invoice(record.name, request.name, "KEY-1")


def test_get_request_invoices_rejects_unrelated_employee(env):
    env.roles["bob@example.com"] = ["Employee"]
    request = _add_request(env, owner="alice@example.com", employee="EMP-ALICE")
    env.add_record(request=request.name)
    frappe_stub_module.session.user = "bob@example.com"
    with pytest.raises(ValidationError, match="无权"):
        service.get_request_invoices(request.name)


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8:8080",
        "http://169.254.169.254/latest",
        "http://224.0.0.1:8080",
        "http://0.0.0.0:8080",
        "http://user:pass@203.0.113.73:8080",
        "http://203.0.113.73:8080/?secret=1",
    ],
)
def test_client_rejects_public_metadata_and_ambiguous_roots(env, monkeypatch, url):
    frappe_stub_module.conf.invoice_ocr_url = url
    post = Mock()
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")
    post.assert_not_called()


def test_client_rejects_hostname_if_any_dns_answer_is_public(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "http://mixed.internal:8080"
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("203.0.113.73", 8080)),
            (2, 1, 6, "", ("8.8.8.8", 8080)),
        ],
    )
    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")


def test_client_streams_closes_disables_redirects_and_limits_content_length(env, monkeypatch):
    response = Response(payload=_valid_payload())
    response.headers = {"Content-Length": str(client.MAX_RESPONSE_BYTES + 1)}
    response.closed = False
    post = Mock(return_value=response)
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="无效结果"):
        client.recognize_document(b"%PDF", "invoice.pdf", "INV-1")
    assert response.closed is True
    assert post.call_args.kwargs["stream"] is True
    assert post.call_args.kwargs["allow_redirects"] is False


def test_client_aborts_oversized_chunked_body_at_max_plus_one(env, monkeypatch):
    response = Response(payload={})
    response.headers = {}
    response.closed = False
    response.iter_content = lambda chunk_size=65536: iter(
        [b"x" * client.MAX_RESPONSE_BYTES, b"x"]
    )
    monkeypatch.setattr(client.requests, "post", Mock(return_value=response))
    with pytest.raises(client.OCRServiceError, match="无效结果"):
        client.recognize_document(b"%PDF", "invoice.pdf", "INV-1")
    assert response.closed is True


def test_client_does_not_follow_redirect_or_resend_multipart(env, monkeypatch):
    response = Response(status=307, raw=b"redirect")
    response.headers = {"Location": "http://169.254.169.254/latest"}
    post = Mock(return_value=response)
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="拒绝|不可用"):
        client.recognize_document(b"SECRET", "invoice.pdf", "INV-1")
    assert post.call_count == 1
    assert post.call_args.kwargs["allow_redirects"] is False


def test_register_api_accepts_only_batch_and_file_url(env):
    import inspect

    signature = inspect.signature(api_module.register_file)
    assert list(signature.parameters) == ["batch", "file_url"]



def test_client_allowlist_never_overrides_public_dns_answer(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "http://public.example:8080"
    frappe_stub_module.conf.invoice_ocr_allowed_hosts = ["public.example"]
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 8080))],
    )
    post = Mock()
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")
    post.assert_not_called()



# Faithful Frappe transaction/Redis/File-controller test double used by hardening tests.
class CallbackQueue:
    def __init__(self):
        self.functions = []

    def add(self, function):
        self.functions.append(function)

    def run(self):
        while self.functions:
            self.functions.pop(0)()

    def reset(self):
        self.functions.clear()


class LockNotOwnedError(Exception):
    pass


class LeaseLock:
    def __init__(self, environment, key, kwargs):
        self.environment = environment
        self.key = key
        self.kwargs = kwargs
        self.token = object()
        self.owned = False

    def acquire(self, blocking=True, blocking_timeout=None):
        active = self.environment.active_locks.get(self.key)
        if active and active["expires_at"] > self.environment.clock:
            return False
        timeout = int(self.kwargs.get("timeout") or 0)
        self.environment.active_locks[self.key] = {
            "token": self.token,
            "expires_at": self.environment.clock + timeout,
        }
        self.environment.locks.append((self.key, self.kwargs))
        self.owned = True
        hook = self.environment.lock_hooks.pop(self.key, None)
        if hook:
            hook()
        return True

    def release(self):
        active = self.environment.active_locks.get(self.key)
        if not self.owned or not active or active["token"] is not self.token:
            raise LockNotOwnedError(self.key)
        del self.environment.active_locks[self.key]
        self.owned = False

    def __enter__(self):
        if not self.acquire(blocking=True, blocking_timeout=self.kwargs.get("blocking_timeout")):
            raise TimeoutError(self.key)
        return self

    def __exit__(self, *_args):
        self.release()
        return False


_original_environment_init = Environment.__init__


def _faithful_environment_init(self, root):
    _original_environment_init(self, root)
    self.active_locks = {}
    self.lock_hooks = {}
    self.clock = 0


Environment.__init__ = _faithful_environment_init


def _faithful_cache_lock(self, key, **kwargs):
    return LeaseLock(self.environment, key, kwargs)


FakeCache.lock = _faithful_cache_lock

_original_db_init = FakeDB.__init__


def _faithful_db_init(self, environment):
    _original_db_init(self, environment)
    self.after_commit = CallbackQueue()
    self.after_rollback = CallbackQueue()


FakeDB.__init__ = _faithful_db_init


def _faithful_commit(self):
    self.environment.commits += 1
    self.after_rollback.reset()
    self.after_commit.run()


def _faithful_rollback(self):
    self.after_commit.reset()
    self.after_rollback.run()


FakeDB.commit = _faithful_commit
FakeDB.rollback = _faithful_rollback

_original_enqueue = Environment.enqueue


def _faithful_enqueue(self, method, **kwargs):
    if kwargs.get("enqueue_after_commit"):
        self.db.after_commit.add(lambda: self.enqueued.append((method, kwargs)))
    else:
        _original_enqueue(self, method, **kwargs)


Environment.enqueue = _faithful_enqueue

_original_doc_save = Doc.save


def _file_controller_save(self, ignore_permissions=False):
    if self.get("doctype") == "File":
        form_dict = getattr(frappe_stub_module, "form_dict", None)
        supplied = getattr(form_dict, "file_size", None) if form_dict is not None else None
        if supplied not in (None, ""):
            self.file_size = supplied
    return _original_doc_save(self, ignore_permissions=ignore_permissions)


Doc.save = _file_controller_save


def test_transaction_lock_is_site_prefixed_and_released_only_after_commit(env):
    frappe_stub_module.local.site = "site:one"
    key = service._lock_key("record", "INV:1")
    assert key.startswith("invoice:")
    assert "site:one" not in key and "INV:1" not in key
    with service._transaction_lock("record", "INV:1"):
        assert key in env.active_locks
    assert key in env.active_locks
    env.db.commit()
    assert key not in env.active_locks


def test_transaction_lock_releases_on_rollback_and_expired_lease_can_be_recovered(env):
    frappe_stub_module.local.site = "site-one"
    with service._transaction_lock("record", "INV-1", timeout=600):
        key = service._lock_key("record", "INV-1")
        assert key in env.active_locks
    env.clock = 601
    second = env.cache().lock(key, timeout=600, blocking_timeout=1)
    assert second.acquire(blocking=True, blocking_timeout=1) is True
    env.db.rollback()
    assert service._lock_key("record", "INV-1") not in getattr(frappe_stub_module.local, "invoice_transaction_locks", {})


def test_register_file_reloads_under_file_lock_and_never_reattaches_stale_file(env):
    env.add_batch(name="BATCH-1")
    env.add_batch(name="BATCH-2")
    file_doc = env.add_file(batch="BATCH-1")
    file_key = service._lock_key("file", file_doc.name)

    def concurrent_attach():
        file_doc.attached_to_doctype = service.RECORD_DOCTYPE
        file_doc.attached_to_name = "INV-CONCURRENT"

    env.lock_hooks[file_key] = concurrent_attach
    with pytest.raises(ValidationError, match="其他业务记录"):
        service.register_file("BATCH-2", file_doc.file_url)
    assert file_doc.attached_to_name == "INV-CONCURRENT"
    assert not env.docs[service.RECORD_DOCTYPE]


def test_register_ignores_form_dict_file_size_and_has_no_hidden_commit(env):
    env.add_batch()
    file_doc = env.add_file(content=b"%PDF-real-bytes")
    frappe_stub_module.form_dict = types.SimpleNamespace(file_size=1)
    before = env.commits
    result = service.register_file("BATCH-1", file_doc.file_url)
    assert result["file_size"] == len(b"%PDF-real-bytes")
    assert file_doc.file_size == len(b"%PDF-real-bytes")
    assert env.commits == before
    assert env.enqueued == []
    env.db.commit()
    assert len(env.enqueued) == 2
    assert env.enqueued[0][0].endswith("recompute_invoice_batch")
    assert env.enqueued[1][0].endswith("recognize_invoice")



@pytest.mark.parametrize("operation", ["update", "confirm", "retry", "exclude", "resolve"])
def test_manual_transition_reloads_state_under_one_record_lock(env, operation):
    env.add_batch()
    status = "失败" if operation == "retry" else "疑似重复" if operation == "resolve" else "待确认"
    record = env.add_record(recognition_status=status)
    if operation == "retry":
        file_doc = env.add_file()
        file_doc.attached_to_doctype = service.RECORD_DOCTYPE
        file_doc.attached_to_name = record.name
        record.invoice_file = file_doc.file_url
    if operation == "resolve":
        frappe_stub_module.session.user = "finance@example.com"
    key = service._lock_key("record", record.name)
    env.lock_hooks[key] = lambda: record.__setitem__("recognition_status", "已确认")
    with pytest.raises(ValidationError, match="状态|疑似重复|失败"):
        if operation == "update":
            service.update_invoice(record.name, {"project_name": "stale"})
        elif operation == "confirm":
            service.confirm_invoice(record.name)
        elif operation == "retry":
            service.retry_invoice(record.name)
        elif operation == "exclude":
            service.exclude_invoice(record.name, "reason")
        else:
            service.resolve_duplicate(record.name, "reviewed")
    assert record.recognition_status == "已确认"


def test_confirm_duplicate_returns_structured_conflict_without_hidden_commit(env):
    env.add_batch()
    env.add_record(
        name="INV-OLD",
        recognition_status="已确认",
        invoice_number="0001",
        issue_date="2026-07-14",
        total_amount=Decimal("35.98"),
    )
    record = env.add_record(
        name="INV-NEW",
        invoice_number="0001",
        issue_date="2026-07-14",
        total_amount=Decimal("35.98"),
    )
    before = env.commits
    result = service.confirm_invoice(record.name)
    assert result["recognition_status"] == "疑似重复"
    assert result["conflict"]["code"] == "duplicate"
    assert result["conflict"]["duplicate_of"] == "INV-OLD"
    assert env.commits == before
    assert service._lock_key("record", record.name) in env.active_locks
    env.db.commit()


def test_duplicate_override_uses_full_sha256_marker(env):
    key = "0001|2026-07-14|35.98"
    prefix = service._resolution_prefix(key)
    assert hashlib.sha256(key.encode("utf-8")).hexdigest() in prefix
    assert prefix.startswith("duplicate-override:v1:")


@pytest.mark.parametrize(
    "values",
    [
        {"project_name": ["not", "scalar"]},
        {"project_name": {"nested": "not scalar"}},
        {"project_name": "x" * (32 * 1024 + 1)},
    ],
)
def test_dict_payload_is_bounded_and_scalar_only(env, values):
    env.add_batch()
    record = env.add_record()
    with pytest.raises(ValidationError, match="格式|过长"):
        service.update_invoice(record.name, values)


def test_retry_recovers_only_timed_out_processing_claim(env):
    env.add_batch()
    file_doc = env.add_file()
    stale = env.add_record(
        name="INV-STALE",
        recognition_status="识别中",
        processing_started_on=datetime(2026, 7, 21, 8, 0, 0),
        invoice_file=file_doc.file_url,
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = stale.name
    result = service.retry_invoice(stale.name)
    assert result["recognition_status"] == "排队中"
    assert result["processing_started_on"] is None
    env.db.commit()
    fresh = env.add_record(
        name="INV-FRESH",
        recognition_status="识别中",
        processing_started_on=datetime(2026, 7, 21, 8, 59, 0),
    )
    with pytest.raises(ValidationError, match="超时|失败"):
        service.retry_invoice(fresh.name)



_original_faithful_enqueue = Environment.enqueue


def _enqueue_with_failure(self, method, **kwargs):
    if getattr(self, "raise_enqueue", False) and not kwargs.get("enqueue_after_commit"):
        raise RuntimeError("queue unavailable SECRET")
    return _original_faithful_enqueue(self, method, **kwargs)


Environment.enqueue = _enqueue_with_failure



def test_enqueue_after_commit_failure_marks_record_recoverably_failed(env):
    env.add_batch()
    file_doc = env.add_file()
    env.raise_enqueue = True
    result = service.register_file("BATCH-1", file_doc.file_url)
    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    assert record.recognition_status == "排队中"
    env.db.commit()
    assert record.recognition_status == "失败"
    assert record.processing_error == service.ENQUEUE_FAILURE_MESSAGE
    assert env.commits >= 2


def test_enqueue_dispatch_runs_only_after_commit_and_uses_no_nested_after_commit(env):
    env.add_batch()
    file_doc = env.add_file()
    result = service.register_file("BATCH-1", file_doc.file_url)
    assert env.enqueued == []
    env.db.commit()
    assert env.enqueued == [
        (
            "rayher_hr_payroll.invoice_ocr.jobs.recompute_invoice_batch",
            {"batch_name": "BATCH-1", "queue": "short", "enqueue_after_commit": False},
        ),
        (
            "rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice",
            {"invoice_name": result["name"], "queue": "long"},
        ),
    ]


def test_job_claim_timestamp_and_record_lease_cover_network_call(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    observed = {}

    def recognize(*_args):
        observed["status"] = record.recognition_status
        observed["started"] = record.processing_started_on
        key = service._lock_key("record", record.name)
        observed["lease"] = env.active_locks[key]
        return payload

    monkeypatch.setattr(jobs.client, "recognize_document", recognize)
    result = jobs.recognize_invoice(record.name)
    assert observed["status"] == "识别中"
    assert observed["started"] == datetime(2026, 7, 21, 9, 0, 0)
    assert observed["lease"]["expires_at"] >= 600
    assert result["recognition_status"] == "待确认"
    assert record.processing_started_on is None


def test_worker_kill_leaves_recoverable_claim_and_retry_requeues_when_stale(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    monkeypatch.setattr(jobs.client, "recognize_document", Mock(side_effect=SystemExit("worker killed")))
    with pytest.raises(SystemExit):
        jobs.recognize_invoice(record.name)
    assert record.recognition_status == "识别中"
    assert record.processing_started_on == datetime(2026, 7, 21, 9, 0, 0)
    record.processing_started_on = datetime(2026, 7, 21, 8, 0, 0)
    result = service.retry_invoice(record.name)
    assert result["recognition_status"] == "排队中"


def test_expired_job_lease_release_never_overwrites_business_result(env, monkeypatch):
    jobs = importlib.import_module("rayher_hr_payroll.invoice_ocr.jobs")
    record, _file = _queued_record_with_file(env)
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256

    def recognize(*_args):
        key = service._lock_key("record", record.name)
        env.active_locks[key]["token"] = object()
        return payload

    monkeypatch.setattr(jobs.client, "recognize_document", recognize)
    result = jobs.recognize_invoice(record.name)
    assert result["recognition_status"] == "待确认"



def test_link_holds_request_batch_record_in_order_and_reloads_submitted_request(env):
    env.add_batch()
    record = env.add_record(recognition_status="已确认")
    request = _add_request(env)
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": "LINE-1",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": "KEY-1",
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    env.lock_hooks[service._lock_key("request", request.name)] = lambda: request.__setitem__(
        "workflow_status", "待审批"
    )
    with pytest.raises(ValidationError, match="提交后"):
        service.link_invoice(record.name, request.name, "KEY-1")
    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories[:3] == ["request", "batch", "record"]
    assert not record.request


def test_link_rechecks_record_and_batch_relationships_inside_locks(env):
    batch = env.add_batch()
    record = env.add_record(recognition_status="已确认")
    request = _add_request(env)
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": "LINE-1",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": "KEY-1",
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    env.lock_hooks[service._lock_key("batch", batch.name)] = lambda: batch.__setitem__(
        "request", "REQ-OTHER"
    )
    with pytest.raises(ValidationError, match="不能关联多张"):
        service.link_invoice(record.name, request.name, "KEY-1")
    assert not record.request


def test_recompute_batch_owns_site_scoped_batch_lock_until_commit(env):
    batch = env.add_batch()
    env.add_record(recognition_status="已确认")
    service.recompute_batch(batch.name)
    key = service._lock_key("batch", batch.name)
    assert key in env.active_locks
    assert batch.confirmed_count == 1
    env.db.commit()
    assert key not in env.active_locks


def test_batch_recompute_observes_record_change_before_locked_query(env):
    batch = env.add_batch()
    first = env.add_record(name="INV-1", recognition_status="待确认")
    second = env.add_record(name="INV-2", recognition_status="待确认")
    key = service._lock_key("batch", batch.name)
    env.lock_hooks[key] = lambda: second.__setitem__("recognition_status", "已确认")
    result = service.confirm_invoice(first.name)
    assert result["recognition_status"] == "已确认"
    assert batch.confirmed_count == 0
    env.db.commit()
    _run_queued_batch_recomputes(env)
    assert batch.confirmed_count == 2
    assert batch.pending_confirmation_count == 0



def test_enqueue_failure_recovery_never_overwrites_newer_nonqueued_state(env):
    env.add_batch()
    file_doc = env.add_file()
    env.raise_enqueue = True
    result = service.register_file("BATCH-1", file_doc.file_url)
    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    record.recognition_status = "已排除"
    env.db.commit()
    assert record.recognition_status == "已排除"
    assert record.get("processing_error") != service.ENQUEUE_FAILURE_MESSAGE



class ResponseDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


_previous_environment_init_for_cache = Environment.__init__


def _cache_environment_init(self, root):
    _previous_environment_init_for_cache(self, root)
    self.cache_values = {}


Environment.__init__ = _cache_environment_init


def _cache_set_value(self, key, value, expires_in_sec=None, **_kwargs):
    self.environment.cache_values[key] = {
        "value": value,
        "expires_at": self.environment.clock + int(expires_in_sec or 0),
    }


def _cache_get_value(self, key, **_kwargs):
    item = self.environment.cache_values.get(key)
    if not item:
        return None
    if item["expires_at"] and item["expires_at"] <= self.environment.clock:
        self.environment.cache_values.pop(key, None)
        return None
    return item["value"]


def _cache_delete_value(self, key, **_kwargs):
    self.environment.cache_values.pop(key, None)


FakeCache.set_value = _cache_set_value
FakeCache.get_value = _cache_get_value
FakeCache.delete_value = _cache_delete_value


def _preview_record(env):
    env.add_batch()
    file_doc = env.add_file()
    record = env.add_record(
        invoice_file=file_doc.file_url,
        file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = record.name
    return record, file_doc


def test_preview_issues_only_controlled_short_lived_url_without_view_log(env):
    record, _file = _preview_record(env)
    result = service.preview_invoice(record.name)
    assert result["preview_url"] == (
        "/api/method/rayher_hr_payroll.api.invoice_entry.serve_invoice_preview"
    )
    assert result["preview_method"] == "POST"
    assert "/private/files/" not in json.dumps(result)
    assert "file_url" not in result and "full_path" not in result
    assert result["mime_type"] == "application/pdf"
    assert not env.docs[service.VIEW_LOG_DOCTYPE]


def test_preview_serve_is_one_time_user_bound_inline_and_logs_actual_view(env):
    record, _file = _preview_record(env)
    issued = service.preview_invoice(record.name)
    token = issued["token"]
    frappe_stub_module.local.response = ResponseDict()
    service.serve_invoice_preview(token)
    response = frappe_stub_module.local.response
    assert response.type == "download"
    assert response.display_content_as == "inline"
    assert response.content_type == "application/pdf"
    assert response.filecontent == b"%PDF-1.7\n"
    assert response.filename == "invoice.pdf"
    log = env.inserted[-1]
    assert log.doctype == service.VIEW_LOG_DOCTYPE
    assert log.invoice_record == record.name and log.action == "查看"
    env.db.commit()
    with pytest.raises(ValidationError, match="失效|过期"):
        service.serve_invoice_preview(token)


def test_preview_token_rejects_cross_user_but_remains_for_owner(env):
    record, _file = _preview_record(env)
    token = service.preview_invoice(record.name)["token"]
    env.roles["bob@example.com"] = ["Employee"]
    frappe_stub_module.session.user = "bob@example.com"
    with pytest.raises(ValidationError, match="无权"):
        service.serve_invoice_preview(token)
    frappe_stub_module.session.user = "alice@example.com"
    frappe_stub_module.local.response = ResponseDict()
    service.serve_invoice_preview(token)
    assert frappe_stub_module.local.response.type == "download"


def test_preview_token_expiry_and_guest_are_rejected(env):
    record, _file = _preview_record(env)
    token = service.preview_invoice(record.name)["token"]
    env.clock = service.PREVIEW_TOKEN_TTL_SECONDS + 1
    with pytest.raises(ValidationError, match="失效|过期"):
        service.serve_invoice_preview(token)
    frappe_stub_module.session.user = "Guest"
    with pytest.raises(ValidationError, match="登录"):
        service.serve_invoice_preview("x" * 43)


def test_preview_serve_api_is_explicit_post_and_bounded(env, monkeypatch):
    import inspect

    assert list(inspect.signature(api_module.serve_invoice_preview).parameters) == ["token"]
    delegated = Mock()
    monkeypatch.setattr(api_module.service, "serve_invoice_preview", delegated)
    api_module.serve_invoice_preview("x" * 43)
    delegated.assert_called_once_with("x" * 43)
    source = Path("rayher_hr_payroll/api/invoice_entry.py").read_text(encoding="utf-8")
    assert source.count("@frappe.whitelist") == 15
    assert 'methods=["POST"]' in source
    assert 'methods=["GET"]' not in source



class TransactionalStore:
    """Small MVCC-like double: transactions never share mutable document objects."""

    def __init__(self, documents):
        self.committed = {key: dict(value) for key, value in documents.items()}
        self.pending = {}

    def load(self, transaction, key):
        source = self.pending.get(transaction, {}).get(key, self.committed[key])
        return dict(source)

    def save(self, transaction, key, document):
        self.pending.setdefault(transaction, {})[key] = dict(document)

    def read_committed(self, key):
        return dict(self.committed[key])

    def commit(self, transaction):
        for key, document in self.pending.pop(transaction, {}).items():
            self.committed[key] = dict(document)

    def rollback(self, transaction):
        self.pending.pop(transaction, None)


def test_transaction_double_hides_mutation_and_save_until_commit():
    store = TransactionalStore({"INV-1": {"status": "待确认"}})
    first = store.load("tx-a", "INV-1")
    first["status"] = "已确认"
    assert store.load("tx-b", "INV-1")["status"] == "待确认"
    store.save("tx-a", "INV-1", first)
    assert store.load("tx-a", "INV-1")["status"] == "已确认"
    assert store.load("tx-b", "INV-1")["status"] == "待确认"
    store.commit("tx-a")
    assert store.load("tx-c", "INV-1")["status"] == "已确认"


def test_after_commit_and_after_rollback_callbacks_have_real_order(env):
    events = []
    env.db.after_commit.add(lambda: events.append("commit-1"))
    env.db.after_commit.add(lambda: events.append("commit-2"))
    env.db.after_rollback.add(lambda: events.append("rollback"))
    env.db.commit()
    assert events == ["commit-1", "commit-2"]
    env.db.after_commit.add(lambda: events.append("must-not-run"))
    env.db.after_rollback.add(lambda: events.append("rollback-2"))
    env.db.rollback()
    assert events == ["commit-1", "commit-2", "rollback-2"]


def test_lease_double_is_mutually_exclusive_until_expiry(env):
    key = service._lock_key("record", "INV-1")
    first = env.cache().lock(key, timeout=600, blocking_timeout=1)
    second = env.cache().lock(key, timeout=600, blocking_timeout=1)
    assert first.acquire(blocking=True, blocking_timeout=1) is True
    assert second.acquire(blocking=True, blocking_timeout=1) is False
    env.clock = 601
    assert second.acquire(blocking=True, blocking_timeout=1) is True


def test_service_authorization_never_uses_generic_oa_doctype_write_permission():
    source = Path("rayher_hr_payroll/invoice_ocr/service.py").read_text(encoding="utf-8")
    assert "frappe.has_permission" not in source
    assert "invoice_permissions.can_edit_request" in source
    assert "invoice_permissions.can_read_request" in source


@pytest.mark.parametrize("address", ["192.0.0.1", "198.18.0.1", "203.0.113.10", "fc00::1"])
def test_client_rejects_non_rfc1918_non_loopback_special_ranges(env, monkeypatch, address):
    frappe_stub_module.conf.invoice_ocr_url = f"http://[{address}]:8080" if ":" in address else f"http://{address}:8080"
    post = Mock()
    monkeypatch.setattr(client.requests, "post", post)
    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")
    post.assert_not_called()

@pytest.mark.parametrize("address", ["127.0.0.1", "203.0.113.73", "203.0.113.154", "203.0.113.11"])
def test_client_keeps_loopback_and_exact_rfc1918_addresses_available(address):
    assert client._safe_internal_address(address) is True

# --- Task 5 round-two MVCC/current-read RED test infrastructure ---
_previous_mvcc_environment_init = Environment.__init__


def _mvcc_environment_init(self, root):
    _previous_mvcc_environment_init(self, root)
    self.mvcc_snapshot = None
    self.current_read_calls = []


Environment.__init__ = _mvcc_environment_init


def _begin_mvcc_snapshot(self):
    self.mvcc_snapshot = {
        doctype: {name: dict(doc) for name, doc in documents.items()}
        for doctype, documents in self.docs.items()
    }


Environment.begin_mvcc_snapshot = _begin_mvcc_snapshot


def _mvcc_documents(environment, doctype, for_update):
    if for_update or environment.mvcc_snapshot is None:
        return environment.docs.get(doctype, {})
    return environment.mvcc_snapshot.get(doctype, {})


def _mvcc_get_doc(self, doctype_or_values, name=None, for_update=False, **_kwargs):
    if isinstance(doctype_or_values, dict):
        return Doc(self, dict(doctype_or_values))
    if for_update:
        self.current_read_calls.append(("get_doc", doctype_or_values, name))
    documents = _mvcc_documents(self, doctype_or_values, for_update)
    try:
        document = documents[name]
    except KeyError as error:
        raise ValidationError("not found") from error
    if for_update or self.mvcc_snapshot is None:
        return document
    return Doc(self, dict(document))


Environment.get_doc = _mvcc_get_doc


def _matches_filters(document, filters):
    if isinstance(filters, str):
        return document.get("name") == filters
    for key, wanted in (filters or {}).items():
        actual = document.get(key)
        if isinstance(wanted, (list, tuple)) and wanted and wanted[0] == "!=":
            matched = actual != wanted[1]
        else:
            matched = actual == wanted
        if not matched:
            return False
    return True


def _project_db_row(document, fieldname, as_dict):
    if fieldname == "*":
        return dict(document)
    fields = list(fieldname) if isinstance(fieldname, (list, tuple)) else [fieldname]
    values = {field: document.get(field) for field in fields}
    if as_dict:
        return values
    if len(fields) == 1:
        return values[fields[0]]
    return tuple(values.values())


def _mvcc_db_get_value(
    self,
    doctype,
    filters=None,
    fieldname="name",
    as_dict=False,
    for_update=False,
    **_kwargs,
):
    if for_update:
        self.environment.current_read_calls.append(("get_value", doctype, filters))
    documents = _mvcc_documents(self.environment, doctype, for_update)
    for document in documents.values():
        if _matches_filters(document, filters):
            return _project_db_row(document, fieldname, as_dict)
    return None


def _mvcc_db_get_values(
    self,
    doctype,
    filters=None,
    fieldname="name",
    as_dict=False,
    for_update=False,
    order_by=None,
    limit=None,
    limit_page_length=None,
    **_kwargs,
):
    if for_update:
        self.environment.current_read_calls.append(("get_values", doctype, filters))
    documents = _mvcc_documents(self.environment, doctype, for_update)
    rows = [
        _project_db_row(document, fieldname, as_dict)
        for document in documents.values()
        if _matches_filters(document, filters)
    ]
    row_limit = limit if limit is not None else limit_page_length
    return rows if row_limit is None else rows[:row_limit]


FakeDB.get_value = _mvcc_db_get_value
FakeDB.get_values = _mvcc_db_get_values


def _mvcc_get_all(self, doctype, filters=None, fields=None, order_by=None, limit_page_length=None, **_kwargs):
    documents = _mvcc_documents(self, doctype, False)
    rows = [
        {field: document.get(field) for field in (fields or ["name"])}
        for document in documents.values()
        if _matches_filters(document, filters)
    ]
    return rows if limit_page_length is None else rows[:limit_page_length]


Environment.get_all = _mvcc_get_all


def test_manual_state_transition_uses_for_update_current_read(env):
    env.add_batch()
    record = env.add_record(recognition_status="待确认")
    env.begin_mvcc_snapshot()
    record.recognition_status = "已确认"

    with pytest.raises(ValidationError, match="状态"):
        service.update_invoice(record.name, {"project_name": "must-not-write-stale"})

    assert ("get_doc", service.RECORD_DOCTYPE, record.name) in env.current_read_calls
    assert record.project_name == ""


def test_confirm_duplicate_query_is_current_read_under_business_lock(env):
    env.add_batch()
    current = env.add_record(
        name="INV-CURRENT",
        recognition_status="待确认",
        invoice_number="A-100",
        issue_date="2026-07-20",
        total_amount=Decimal("100.00"),
    )
    env.begin_mvcc_snapshot()
    env.add_record(
        name="INV-COMMITTED-LATER",
        recognition_status="已确认",
        invoice_number="A-100",
        issue_date="2026-07-20",
        total_amount=Decimal("100.00"),
    )

    result = service.confirm_invoice(current.name)

    assert result["recognition_status"] == "疑似重复"
    assert result["conflict"]["duplicate_of"] == "INV-COMMITTED-LATER"
    assert any(call[:2] == ("get_values", service.RECORD_DOCTYPE) for call in env.current_read_calls)


def test_link_acquires_all_redis_locks_then_current_reads_submitted_request(env):
    batch = env.add_batch()
    record = env.add_record(recognition_status="已确认")
    request = _add_request(env)
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": "LINE-MVCC",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": "KEY-MVCC",
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    env.begin_mvcc_snapshot()
    request.workflow_status = "待审批"

    with pytest.raises(ValidationError, match="提交后"):
        service.link_invoice(record.name, request.name, line.line_key)

    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories[:3] == ["request", "batch", "record"]
    assert ("get_doc", service.RECORD_DOCTYPE, record.name) in env.current_read_calls
    assert ("get_doc", service.BATCH_DOCTYPE, batch.name) in env.current_read_calls
    assert ("get_doc", service.REQUEST_DOCTYPE, request.name) in env.current_read_calls
    assert record.request == ""

    request.workflow_status = "草稿"
    env.docs[service.LINE_DOCTYPE].pop(line.name)
    with pytest.raises(ValidationError, match="不属于"):
        service.link_invoice(record.name, request.name, line.line_key)
    assert any(call[:2] == ("get_value", service.LINE_DOCTYPE) for call in env.current_read_calls)


def test_register_file_decisions_use_current_batch_file_count_and_sha_reads(env):
    batch = env.add_batch()
    file_doc = env.add_file(attached=True, batch=batch.name)
    for index in range(19):
        env.add_record(name=f"INV-EXISTING-{index}")
    env.begin_mvcc_snapshot()
    env.add_record(name="INV-TWENTIETH-COMMITTED")

    with pytest.raises(ValidationError, match="最多上传 20"):
        service.register_file(batch.name, file_doc.file_url)

    assert ("get_doc", service.BATCH_DOCTYPE, batch.name) in env.current_read_calls
    assert ("get_doc", "File", file_doc.name) in env.current_read_calls
    assert any(call[:2] == ("get_values", service.RECORD_DOCTYPE) for call in env.current_read_calls)
    assert len(env.docs[service.RECORD_DOCTYPE]) == 20


def test_web_terminal_state_defers_batch_aggregate_until_record_commit(env):
    batch = env.add_batch()
    record = env.add_record(recognition_status="待确认")

    result = service.confirm_invoice(record.name)

    assert result["recognition_status"] == "已确认"
    assert batch.confirmed_count == 0
    assert not any(call[:2] == ("get_values", service.RECORD_DOCTYPE) for call in env.current_read_calls)
    env.db.commit()
    _run_queued_batch_recomputes(env)
    assert batch.confirmed_count == 1
    assert batch.pending_confirmation_count == 0
    assert env.commits >= 2
    assert any(call[:2] == ("get_values", service.RECORD_DOCTYPE) for call in env.current_read_calls)


def test_two_record_after_commit_aggregates_converge_to_final_counts(env):
    batch = env.add_batch()
    first = env.add_record(name="INV-FIRST", recognition_status="待确认")
    second = env.add_record(name="INV-SECOND", recognition_status="待确认")

    service.confirm_invoice(first.name)
    service.exclude_invoice(second.name, "不报销")
    assert batch.confirmed_count == 0 and batch.excluded_count == 0

    env.db.commit()
    _run_queued_batch_recomputes(env)

    assert batch.total_count == 2
    assert batch.confirmed_count == 1
    assert batch.excluded_count == 1
    assert batch.batch_status == "已完成"


def test_worker_claim_uses_current_record_read_after_mvcc_snapshot(env, monkeypatch):
    record, _file = _queued_record_with_file(env)
    env.begin_mvcc_snapshot()
    record.recognition_status = "已排除"
    recognize = Mock(side_effect=AssertionError("OCR must not run for current nonqueued state"))
    monkeypatch.setattr(jobs_module.client, "recognize_document", recognize)

    result = jobs_module.recognize_invoice(record.name)

    assert result["recognition_status"] == "已排除"
    assert ("get_doc", service.RECORD_DOCTYPE, record.name) in env.current_read_calls
    recognize.assert_not_called()


def test_after_commit_aggregate_only_enqueues_independent_job(env, monkeypatch):
    batch = env.add_batch()
    record = env.add_record(recognition_status="待确认")
    service.confirm_invoice(record.name)
    recompute = Mock(side_effect=RuntimeError("database busy"))
    monkeypatch.setattr(service, "recompute_batch", recompute)

    env.db.commit()

    assert (
        "rayher_hr_payroll.invoice_ocr.jobs.recompute_invoice_batch",
        {
            "batch_name": batch.name,
            "queue": "short",
            "enqueue_after_commit": False,
        },
    ) in env.enqueued
    recompute.assert_not_called()


def test_recompute_batch_retry_job_runs_independent_current_transaction(env):
    batch = env.add_batch()
    env.add_record(name="INV-RETRY-AGG", recognition_status="已确认")

    jobs_module.recompute_invoice_batch(batch.name)

    assert batch.total_count == 1
    assert batch.confirmed_count == 1
    assert env.commits >= 1
    assert ("get_doc", service.BATCH_DOCTYPE, batch.name) in env.current_read_calls

# --- Task 5 round-two preview and DNS pinning RED tests ---
class DelegatingSession:
    def __init__(self):
        self.trust_env = True
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def close(self):
        self.closed = True

    def post(self, *args, **kwargs):
        return requests_stub_module.post(*args, **kwargs)


requests_stub_module.Session = DelegatingSession


class RecordingSession:
    def __init__(self, response):
        self.trust_env = True
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_client_http_hostname_is_resolved_once_pinned_and_proxy_free(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "http://ocr.internal:8080"
    payload = _valid_payload()
    response = Response(payload=payload)
    session = RecordingSession(response)
    monkeypatch.setattr(client.requests, "Session", lambda: session)
    monkeypatch.setattr(
        client.requests,
        "post",
        Mock(side_effect=AssertionError("module-level requests.post must not be used")),
    )
    dns_calls = []

    def two_phase_dns(*_args, **_kwargs):
        dns_calls.append(True)
        address = "203.0.113.177" if len(dns_calls) == 1 else "8.8.8.8"
        return [(2, 1, 6, "", (address, 8080))]

    monkeypatch.setattr(client.socket, "getaddrinfo", two_phase_dns)

    result = client.recognize_document(b"%PDF", "invoice.pdf", "INV-1")

    assert result["record_id"] == "INV-1"
    assert len(dns_calls) == 1
    assert session.trust_env is False
    assert session.calls[0][0] == ("http://203.0.113.177:8080/v1/recognize",)
    assert session.calls[0][1]["headers"] == {"Host": "ocr.internal:8080"}


def test_client_default_docker_hostname_public_dns_is_rejected(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "http://invoice-ocr:8080"
    monkeypatch.setattr(
        client.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 8080))],
    )
    session_factory = Mock()
    monkeypatch.setattr(client.requests, "Session", session_factory)

    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")

    session_factory.assert_not_called()


def test_client_https_dns_hostname_is_explicitly_rejected(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "https://ocr.internal:8443"
    dns = Mock(return_value=[(2, 1, 6, "", ("203.0.113.177", 8443))])
    monkeypatch.setattr(client.socket, "getaddrinfo", dns)
    session_factory = Mock()
    monkeypatch.setattr(client.requests, "Session", session_factory)

    with pytest.raises(client.OCRServiceError, match="配置无效"):
        client.recognize_document(b"x", "a.pdf", "INV-1")

    dns.assert_not_called()
    session_factory.assert_not_called()


def test_client_https_private_literal_keeps_tls_verification_and_no_proxy(env, monkeypatch):
    frappe_stub_module.conf.invoice_ocr_url = "https://203.0.113.177:8443"
    response = Response(payload=_valid_payload())
    session = RecordingSession(response)
    monkeypatch.setattr(client.requests, "Session", lambda: session)

    client.recognize_document(b"%PDF", "invoice.pdf", "INV-1")

    assert session.trust_env is False
    assert session.calls[0][0] == ("https://203.0.113.177:8443/v1/recognize",)
    assert "verify" not in session.calls[0][1]
    assert "headers" not in session.calls[0][1]


def test_preview_contract_is_post_blob_without_token_in_url(env):
    record, _file = _preview_record(env)

    result = service.preview_invoice(record.name)

    assert result["preview_method"] == "POST"
    assert result["preview_url"].endswith("serve_invoice_preview")
    assert "?" not in result["preview_url"] and result["token"] not in result["preview_url"]
    api_source = Path("rayher_hr_payroll/api/invoice_entry.py").read_text(encoding="utf-8")
    serve_block = api_source[api_source.index("def serve_invoice_preview") - 50 :]
    assert 'methods=["POST"]' in serve_block
    assert 'methods=["GET"]' not in serve_block


def test_preview_serve_uses_frappe_v15_as_raw_inline_fields(env):
    record, _file = _preview_record(env)
    token = service.preview_invoice(record.name)["token"]
    frappe_stub_module.local.response = ResponseDict()

    service.serve_invoice_preview(token)

    response = frappe_stub_module.local.response
    assert response.type == "download"
    assert response.content_type == "application/pdf"
    assert response.display_content_as == "inline"
    assert response.filename == "invoice.pdf"
    assert response.filecontent.startswith(b"%PDF-")


def test_preview_token_and_log_are_consistent_across_commit_and_rollback(env):
    record, _file = _preview_record(env)
    token = service.preview_invoice(record.name)["token"]
    cache_key = service._preview_cache_key(token)
    original = env.cache_values[cache_key]["value"]
    frappe_stub_module.local.response = ResponseDict()

    service.serve_invoice_preview(token)

    lock_key = service._lock_key("preview-consume", token)
    assert lock_key in env.active_locks
    assert cache_key in env.cache_values
    env.db.rollback()
    assert env.cache_values[cache_key]["value"] == original
    assert lock_key not in env.active_locks

    frappe_stub_module.local.response = ResponseDict()
    service.serve_invoice_preview(token)
    env.db.commit()
    assert cache_key not in env.cache_values
    assert lock_key not in env.active_locks
    with pytest.raises(ValidationError, match="失效|过期"):
        service.serve_invoice_preview(token)

# --- Task 5 final-review fencing/current-read RED tests ---

def _add_authorization_identity(env):
    env.docs.setdefault("Employee", {})["EMP-ALICE"] = Doc(
        env,
        {
            "doctype": "Employee",
            "name": "EMP-ALICE",
            "user_id": "alice@example.com",
            "employee_name": "Alice",
            "department": "R&D",
        },
    )
    env.docs.setdefault("User", {})["alice@example.com"] = Doc(
        env,
        {"doctype": "User", "name": "alice@example.com", "full_name": "Alice User"},
    )


def _authorization_request(env, *, owner="other@example.com", employee="EMP-OTHER"):
    request = Doc(
        env,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-AUTH",
            "owner": owner,
            "employee": employee,
            "department": "Other",
            "current_step_index": 1,
            "workflow_status": "\u8349\u7a3f",
        },
    )
    env.docs[service.REQUEST_DOCTYPE][request.name] = request
    return request


@pytest.mark.parametrize("grant", ["batch_owner", "request_owner", "request_applicant"])
def test_write_authorization_rechecks_current_batch_and_request_grants(env, grant):
    _add_authorization_identity(env)
    request = _authorization_request(env)
    batch = env.add_batch(owner="other@example.com", request=request.name)
    record = env.add_record(
        owner="other@example.com",
        batch=batch.name,
        request=request.name,
        recognition_status="\u5f85\u786e\u8ba4",
    )
    if grant == "batch_owner":
        batch.owner = "alice@example.com"
    elif grant == "request_owner":
        request.owner = "alice@example.com"
    else:
        request.employee = "EMP-ALICE"

    env.begin_mvcc_snapshot()
    batch.owner = "other@example.com"
    request.owner = "other@example.com"
    request.employee = "EMP-OTHER"

    with pytest.raises(ValidationError, match="\u65e0\u6743"):
        service.update_invoice(record.name, {"project_name": "must-not-write"})

    assert record.project_name == ""
    assert ("get_doc", service.BATCH_DOCTYPE, batch.name) in env.current_read_calls
    if grant != "batch_owner":
        assert any(
            call[:2] == ("get_value", service.REQUEST_DOCTYPE)
            for call in env.current_read_calls
        )


def test_preview_rechecks_current_effective_batch_request_and_approver(env, monkeypatch):
    _add_authorization_identity(env)
    request = _authorization_request(env)
    batch = env.add_batch(owner="other@example.com", request=request.name)
    record, _file = _queued_record_with_file(env, name="INV-PREVIEW-CURRENT")
    batch = env.docs[service.BATCH_DOCTYPE][record.batch]
    batch.owner = "other@example.com"
    batch.request = request.name
    record.owner = "other@example.com"
    record.batch = batch.name
    record.request = ""
    step = Doc(
        env,
        {
            "doctype": "OA Approval Step",
            "name": "STEP-AUTH",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "steps",
            "step_index": 1,
            "approvers": json.dumps(["alice@example.com"]),
        },
    )
    env.docs.setdefault("OA Approval Step", {})[step.name] = step
    monkeypatch.setattr(service, "can_read_invoice", service.invoice_permissions.can_read_invoice)

    env.begin_mvcc_snapshot()
    step.approvers = "[]"

    with pytest.raises(ValidationError, match="\u65e0\u6743"):
        service.preview_invoice(record.name)

    assert ("get_doc", service.RECORD_DOCTYPE, record.name) in env.current_read_calls
    assert any(
        call[:2] == ("get_value", service.BATCH_DOCTYPE)
        for call in env.current_read_calls
    )
    assert any(
        call[:2] == ("get_value", service.REQUEST_DOCTYPE)
        for call in env.current_read_calls
    )
    assert any(
        call[:2] == ("get_value", "OA Approval Step")
        for call in env.current_read_calls
    )


def test_after_commit_aggregate_enqueue_failure_does_not_cancel_ocr_callback(env, monkeypatch):
    env.add_batch()
    file_doc = env.add_file()
    events = []
    original_rollback = env.db.rollback

    def rollback():
        events.append("rollback")
        return original_rollback()

    def selective_enqueue(method, **kwargs):
        if method.endswith("recompute_invoice_batch"):
            events.append("aggregate-enqueue-failed")
            raise RuntimeError("queue unavailable")
        events.append((method, kwargs))

    monkeypatch.setattr(env.db, "rollback", rollback)
    monkeypatch.setattr(frappe_stub_module, "enqueue", selective_enqueue)
    monkeypatch.setattr(
        service,
        "recompute_batch",
        Mock(side_effect=RuntimeError("aggregate must not execute in after_commit")),
    )

    result = service.register_file("BATCH-1", file_doc.file_url)
    env.db.commit()

    assert "rollback" not in events
    assert "aggregate-enqueue-failed" in events
    assert (
        "rayher_hr_payroll.invoice_ocr.jobs.recognize_invoice",
        {"invoice_name": result["name"], "queue": "long"},
    ) in events
    assert env.db.after_commit.functions == []


def test_transaction_lock_exception_remains_held_until_real_rollback(env):
    key = service._lock_key("record", "INV-EXCEPTION")

    with pytest.raises(RuntimeError, match="abort request"):
        with service._transaction_lock("record", "INV-EXCEPTION"):
            raise RuntimeError("abort request")

    assert key in env.active_locks
    assert key in getattr(frappe_stub_module.local, "invoice_transaction_locks", {})
    env.db.rollback()
    assert key not in env.active_locks
    assert key not in getattr(frappe_stub_module.local, "invoice_transaction_locks", {})


@pytest.mark.parametrize("old_outcome", ["success", "failure"])
def test_expired_old_worker_cannot_overwrite_new_processing_claim(env, monkeypatch, old_outcome):
    record, _file = _queued_record_with_file(env, name=f"INV-FENCE-{old_outcome}")
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    observed = {}

    def interleaved_recognize(*_args):
        observed["old_claim"] = record.processing_claim_id
        assert observed["old_claim"]
        env.clock = 901
        record.processing_started_on = datetime(2026, 7, 21, 8, 0, 0)
        service.retry_invoice(record.name)
        env.db.commit()
        record.recognition_status = "\u8bc6\u522b\u4e2d"
        record.processing_started_on = datetime(2026, 7, 21, 9, 1, 0)
        record.processing_claim_id = "new-worker-claim"
        record.project_name = "new worker value"
        record.processing_error = "new worker owns this state"
        if old_outcome == "failure":
            raise RuntimeError("old worker failed late")
        return payload

    monkeypatch.setattr(jobs_module.client, "recognize_document", interleaved_recognize)
    result = jobs_module.recognize_invoice(record.name)

    assert result["recognition_status"] == "\u8bc6\u522b\u4e2d"
    assert record.processing_claim_id == "new-worker-claim"
    assert record.project_name == "new worker value"
    assert record.processing_error == "new worker owns this state"
    assert record.retry_count == 0


def test_file_and_enqueue_recovery_decisions_use_current_reads(env, monkeypatch):
    env.add_batch()
    file_doc = env.add_file()
    record = env.add_record(
        recognition_status="\u5931\u8d25",
        invoice_file=file_doc.file_url,
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = record.name

    service.retry_invoice(record.name)
    assert any(
        call[:2] == ("get_value", "File") for call in env.current_read_calls
    )
    assert ("get_doc", "File", file_doc.name) in env.current_read_calls

    env.current_read_calls.clear()
    record.recognition_status = "\u6392\u961f\u4e2d"
    env.begin_mvcc_snapshot()
    record.recognition_status = "\u5df2\u786e\u8ba4"
    service._mark_enqueue_failure(record.name)
    assert ("get_doc", service.RECORD_DOCTYPE, record.name) in env.current_read_calls
    assert record.recognition_status == "\u5df2\u786e\u8ba4"


def test_worker_current_reads_file_inside_file_lock(env, monkeypatch):
    record, file_doc = _queued_record_with_file(env, name="INV-FILE-CURRENT")
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    monkeypatch.setattr(jobs_module.client, "recognize_document", Mock(return_value=payload))

    jobs_module.recognize_invoice(record.name)

    assert any(call[:2] == ("get_value", "File") for call in env.current_read_calls)
    assert ("get_doc", "File", file_doc.name) in env.current_read_calls
    assert any(
        key == service._lock_key("file", file_doc.name) for key, _kwargs in env.locks
    )


def _recording_session_enter(self):
    self.closed = False
    return self


def _recording_session_close(self):
    self.closed = True


RecordingSession.__enter__ = _recording_session_enter
RecordingSession.__exit__ = lambda self, *_args: (_recording_session_close(self), False)[1]
RecordingSession.close = _recording_session_close


def test_client_closes_session_context_after_streamed_response(env, monkeypatch):
    response = Response(payload=_valid_payload())
    session = RecordingSession(response)
    monkeypatch.setattr(client.requests, "Session", lambda: session)

    client.recognize_document(b"%PDF", "invoice.pdf", "INV-1")

    assert session.closed is True


def _run_queued_batch_recomputes(env):
    seen = set()
    for method, kwargs in list(env.enqueued):
        if not method.endswith("recompute_invoice_batch"):
            continue
        batch_name = kwargs["batch_name"]
        if batch_name in seen:
            continue
        seen.add(batch_name)
        jobs_module.recompute_invoice_batch(batch_name)


def _current_permission_doctypes(calls):
    ordered = []
    for call in calls:
        if call[0] != "get_value":
            continue
        if call[1] in {
            service.REQUEST_DOCTYPE,
            "Employee",
            "User",
            "OA Approval Step",
        }:
            ordered.append(call[1])
    return ordered


def test_shared_request_preview_and_edit_use_one_current_permission_lock_order(env, monkeypatch):
    _add_authorization_identity(env)
    request = _authorization_request(env, employee="EMP-ALICE")
    step = Doc(
        env,
        {
            "doctype": "OA Approval Step",
            "name": "STEP-LOCK-ORDER",
            "parent": request.name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "steps",
            "step_index": 1,
            "approvers": "[]",
        },
    )
    env.docs.setdefault("OA Approval Step", {})[step.name] = step
    batch = env.add_batch(owner="other@example.com", request=request.name)
    file_doc = env.add_file(filename="permission-order.pdf", batch=batch.name)
    preview_record = env.add_record(
        name="INV-ORDER-PREVIEW",
        owner="other@example.com",
        batch=batch.name,
        request=request.name,
        invoice_file=file_doc.file_url,
        original_filename=file_doc.file_name,
        file_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
        recognition_status="\u5f85\u786e\u8ba4",
    )
    file_doc.attached_to_doctype = service.RECORD_DOCTYPE
    file_doc.attached_to_name = preview_record.name
    edit_record = env.add_record(
        name="INV-ORDER-EDIT",
        owner="other@example.com",
        batch=batch.name,
        request=request.name,
        recognition_status="\u5f85\u786e\u8ba4",
    )
    monkeypatch.setattr(service, "can_read_invoice", service.invoice_permissions.can_read_invoice)

    env.current_read_calls.clear()
    service.preview_invoice(preview_record.name)
    preview_order = _current_permission_doctypes(env.current_read_calls)

    env.current_read_calls.clear()
    service.update_invoice(edit_record.name, {"project_name": "lock-order"})
    edit_order = _current_permission_doctypes(env.current_read_calls)
    env.db.commit()

    expected = [
        service.REQUEST_DOCTYPE,
        "Employee",
        "User",
        "OA Approval Step",
    ]
    assert (preview_order, edit_order) == (expected, expected)

    # An unlinked current owner is decided from the already-current Record and
    # must not acquire identity locks before a later Request lookup.
    edit_record.owner = "alice@example.com"
    edit_record.request = ""
    batch.request = ""
    env.current_read_calls.clear()
    service._require_record(edit_record.name, current=True)
    assert _current_permission_doctypes(env.current_read_calls) == []


# --- Task 6 independent-review RED tests ---
def test_register_linked_batch_locks_current_draft_request_and_inherits_request(env):
    request = _add_request(env, status="\u8349\u7a3f")
    batch = env.add_batch(request=request.name)
    file_doc = env.add_file(filename="linked.pdf", batch=batch.name)

    result = service.register_file(batch.name, file_doc.file_url)

    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories[:4] == ["request", "batch", "file", "file-hash"]
    assert ("get_doc", service.REQUEST_DOCTYPE, request.name) in env.current_read_calls
    assert record.request == request.name


def test_register_linked_batch_rejects_current_submitted_request_without_mutation(env):
    request = _add_request(env, status="\u8349\u7a3f")
    batch = env.add_batch(request=request.name)
    file_doc = env.add_file(filename="submitted.pdf", batch=batch.name)
    env.begin_mvcc_snapshot()
    request.workflow_status = "\u5f85\u8d22\u52a1\u5ba1\u6838"

    with pytest.raises(ValidationError, match="\u63d0\u4ea4\u540e\u4e0d\u80fd"):
        service.register_file(batch.name, file_doc.file_url)

    assert env.docs[service.RECORD_DOCTYPE] == {}
    assert file_doc.attached_to_doctype == service.BATCH_DOCTYPE
    assert file_doc.attached_to_name == batch.name
    assert ("get_doc", service.REQUEST_DOCTYPE, request.name) in env.current_read_calls


def test_independent_batch_aggregate_refreshes_linked_request_summary(env):
    request = _add_request(env, status="\u8349\u7a3f")
    request.invoice_count = 0
    request.invoice_status = "\u5f85\u786e\u8ba4"
    batch = env.add_batch(request=request.name)
    record = env.add_record(
        batch=batch.name,
        request=request.name,
        recognition_status="\u5f85\u786e\u8ba4",
        invoice_category="\u7535\u5b50\u53d1\u7968\uff08\u666e\u901a\u53d1\u7968\uff09",
        project_name="\u6587\u5177\u5370\u7ae0",
        invoice_number="000123",
    )

    service.confirm_invoice(record.name)
    env.db.commit()
    _run_queued_batch_recomputes(env)

    assert request.invoice_count == 1
    assert request.invoice_status == "\u5df2\u786e\u8ba4"
    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert "batch" in categories and "request" in categories
    assert categories.index("batch") < categories.index("request")
    assert ("get_doc", service.REQUEST_DOCTYPE, request.name) in env.current_read_calls


def test_async_recognition_refreshes_linked_request_summary(env, monkeypatch):
    request = _add_request(env, status="\u8349\u7a3f")
    request.invoice_count = 0
    request.invoice_status = "\u6392\u961f\u4e2d"
    record, _file = _queued_record_with_file(env, name="INV-ASYNC-SUMMARY")
    batch = env.docs[service.BATCH_DOCTYPE][record.batch]
    batch.request = request.name
    record.request = request.name
    payload = _valid_payload(record.name)
    payload["file_sha256"] = record.file_sha256
    monkeypatch.setattr(
        jobs_module.client,
        "recognize_document",
        Mock(return_value=payload),
    )

    result = jobs_module.recognize_invoice(record.name)

    assert result["recognition_status"] == "\u5f85\u786e\u8ba4"
    assert request.invoice_count == 1
    assert request.invoice_status == "\u5f85\u786e\u8ba4"


# --- Task 6 aggregate deadlock RED tests ---
def test_two_batch_workers_release_each_batch_before_shared_request_phase(env, monkeypatch):
    request = _add_request(env, status="\u8349\u7a3f")
    batches = {
        name: env.add_batch(name=name, request=request.name)
        for name in ("BATCH-A", "BATCH-B")
    }
    events = []
    original_commit = env.db.commit

    def commit():
        events.append("commit")
        original_commit()

    def recompute_batch(batch_name):
        with service._transaction_lock("batch", batch_name):
            events.append(("batch", batch_name))
            return batches[batch_name]

    def recompute_request_summary(request_name):
        held_categories = {
            key.split(":")[2] for key in env.active_locks
        }
        events.append(("request-entry", request_name, held_categories))
        assert "batch" not in held_categories
        with service._transaction_lock("request", request_name):
            events.append(("request", request_name))
        return request

    monkeypatch.setattr(env.db, "commit", commit)
    monkeypatch.setattr(service, "recompute_batch", recompute_batch)
    monkeypatch.setattr(
        service,
        "recompute_request_summary",
        recompute_request_summary,
        raising=False,
    )

    for batch_name in batches:
        jobs_module.recompute_invoice_batch(batch_name)

    assert events == [
        ("batch", "BATCH-A"),
        "commit",
        ("request-entry", request.name, set()),
        ("request", request.name),
        "commit",
        ("batch", "BATCH-B"),
        "commit",
        ("request-entry", request.name, set()),
        ("request", request.name),
        "commit",
    ]


def test_batch_recompute_never_locks_or_refreshes_linked_request(env):
    request = _add_request(env, status="\u8349\u7a3f")
    request.invoice_count = 0
    request.invoice_status = "\u65e0\u53d1\u7968"
    first = env.add_batch(name="BATCH-A", request=request.name)
    env.add_batch(name="BATCH-B", request=request.name)
    env.add_record(
        name="INV-A",
        batch=first.name,
        request=request.name,
        recognition_status="\u5df2\u786e\u8ba4",
    )
    env.add_record(
        name="INV-B",
        batch="BATCH-B",
        request=request.name,
        recognition_status="\u5df2\u786e\u8ba4",
    )

    service.recompute_batch(first.name)

    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories == ["batch"]
    assert request.invoice_count == 0
    assert request.invoice_status == "\u65e0\u53d1\u7968"
    assert not any(
        call[:2] == ("get_doc", service.REQUEST_DOCTYPE)
        for call in env.current_read_calls
    )


def test_request_summary_phase_locks_only_request_and_uses_nonlocking_collection_reads(env):
    request = _add_request(env, status="\u8349\u7a3f")
    request.invoice_count = 0
    request.invoice_status = "\u65e0\u53d1\u7968"
    batch = env.add_batch(name="BATCH-A", request=request.name)
    env.add_record(
        name="INV-A",
        batch=batch.name,
        request=request.name,
        recognition_status="\u5df2\u786e\u8ba4",
    )
    recompute_request_summary = getattr(
        service, "recompute_request_summary", None
    )
    assert callable(recompute_request_summary)

    recompute_request_summary(request.name)

    categories = [key.split(":")[2] for key, _kwargs in env.locks]
    assert categories == ["request"]
    assert request.invoice_count == 1
    assert request.invoice_status == "\u5df2\u786e\u8ba4"
    assert ("get_doc", service.REQUEST_DOCTYPE, request.name) in env.current_read_calls
    assert not any(
        call[0] == "get_values"
        and call[1] in {service.BATCH_DOCTYPE, service.RECORD_DOCTYPE}
        for call in env.current_read_calls
    )


def test_request_summary_failure_rolls_back_only_after_batch_commit(env, monkeypatch):
    request = _add_request(env, status="\u8349\u7a3f")
    batch = env.add_batch(name="BATCH-A", request=request.name)
    events = []
    original_commit = env.db.commit
    original_rollback = env.db.rollback

    def commit():
        events.append("commit")
        original_commit()

    def rollback():
        events.append("rollback")
        original_rollback()

    monkeypatch.setattr(env.db, "commit", commit)
    monkeypatch.setattr(env.db, "rollback", rollback)
    monkeypatch.setattr(
        service,
        "recompute_batch",
        lambda name: (events.append(("batch", name)) or batch),
    )
    monkeypatch.setattr(
        service,
        "recompute_request_summary",
        lambda name: (
            events.append(("request", name))
            or (_ for _ in ()).throw(RuntimeError("request summary failed"))
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="request summary failed"):
        jobs_module.recompute_invoice_batch(batch.name)

    assert events == [
        ("batch", batch.name),
        "commit",
        ("request", request.name),
        "rollback",
    ]
    assert env.commits == 1

def test_link_allows_same_draft_rebind_and_unlink_but_keeps_request_and_file(env):
    batch = env.add_batch()
    request = Doc(
        env,
        {
            "doctype": service.REQUEST_DOCTYPE,
            "name": "REQ-REBIND",
            "owner": "alice@example.com",
            "employee": "EMP-ALICE",
            "workflow_status": "\u8349\u7a3f",
        },
    )
    env.docs[service.REQUEST_DOCTYPE][request.name] = request
    for index, key in enumerate(("KEY-1", "KEY-2"), start=1):
        line = Doc(
            env,
            {
                "doctype": service.LINE_DOCTYPE,
                "name": f"LINE-{index}",
                "parent": request.name,
                "parenttype": service.REQUEST_DOCTYPE,
                "parentfield": "expense_lines",
                "line_key": key,
            },
        )
        env.docs[service.LINE_DOCTYPE][line.name] = line
    batch.request = request.name
    record = env.add_record(
        name="INV-REBIND",
        recognition_status="\u5df2\u786e\u8ba4",
        request=request.name,
        expense_line_key="KEY-1",
        invoice_file="/private/files/original.pdf",
    )

    service.link_invoice(record.name, request.name, "KEY-2")
    assert record.expense_line_key == "KEY-2"
    service.link_invoice(record.name, request.name, "")
    assert record.request == request.name
    assert record.expense_line_key == ""
    assert record.invoice_file == "/private/files/original.pdf"
    assert request.invoice_count == 1
    assert request.invoice_status == "\u5df2\u786e\u8ba4"

    request.workflow_status = "\u5f85\u5ba1\u6279"
    with pytest.raises(ValidationError, match="\u63d0\u4ea4\u540e"):
        service.link_invoice(record.name, request.name, "KEY-1")


def test_link_still_rejects_cross_request_rebind(env):
    batch = env.add_batch()
    first = Doc(env, {
        "doctype": service.REQUEST_DOCTYPE,
        "name": "REQ-FIRST",
        "owner": "alice@example.com",
        "employee": "EMP-ALICE",
        "workflow_status": "\u8349\u7a3f",
    })
    second = Doc(env, {
        "doctype": service.REQUEST_DOCTYPE,
        "name": "REQ-SECOND",
        "owner": "alice@example.com",
        "employee": "EMP-ALICE",
        "workflow_status": "\u8349\u7a3f",
    })
    env.docs[service.REQUEST_DOCTYPE][first.name] = first
    env.docs[service.REQUEST_DOCTYPE][second.name] = second
    line = Doc(env, {
        "doctype": service.LINE_DOCTYPE,
        "name": "LINE-SECOND",
        "parent": second.name,
        "parenttype": service.REQUEST_DOCTYPE,
        "parentfield": "expense_lines",
        "line_key": "KEY-SECOND",
    })
    env.docs[service.LINE_DOCTYPE][line.name] = line
    batch.request = first.name
    record = env.add_record(
        name="INV-CROSS-REBIND",
        recognition_status="\u5df2\u786e\u8ba4",
        request=first.name,
        expense_line_key="",
    )

    with pytest.raises(ValidationError, match="\u5176\u4ed6"):
        service.link_invoice(record.name, second.name, "KEY-SECOND")
    assert record.request == first.name
    assert record.expense_line_key == ""


def test_link_api_accepts_blank_line_key_for_draft_unlink(env, monkeypatch):
    api = importlib.import_module("rayher_hr_payroll.api.invoice_entry")
    delegated = Mock(return_value={"name": "INV-1", "expense_line_key": ""})
    monkeypatch.setattr(api.service, "link_invoice", delegated)

    result = api.link_invoice("INV-1", "REQ-1", "")

    assert result["expense_line_key"] == ""
    delegated.assert_called_once_with("INV-1", "REQ-1", "")


# --- Task 8 single-batch and request collection regression tests ---

def _task8_add_expense_line(env, request_name, key):
    line = Doc(
        env,
        {
            "doctype": service.LINE_DOCTYPE,
            "name": f"LINE-{key}",
            "parent": request_name,
            "parenttype": service.REQUEST_DOCTYPE,
            "parentfield": "expense_lines",
            "line_key": key,
        },
    )
    env.docs[service.LINE_DOCTYPE][line.name] = line
    return line


def test_link_rejects_second_request_batch_with_nonlocking_committed_read(
    env, monkeypatch
):
    request = _add_request(env, name="REQ-SINGLE-BATCH")
    first_batch = env.add_batch(name="BATCH-FIRST", request="")
    second_batch = env.add_batch(name="BATCH-SECOND", request="")
    line = _task8_add_expense_line(env, request.name, "KEY-SECOND")
    record = env.add_record(
        name="INV-SECOND",
        batch=second_batch.name,
        recognition_status="\u5df2\u786e\u8ba4",
        request="",
        expense_line_key="",
    )
    env.begin_mvcc_snapshot()
    first_batch.request = request.name
    env.register_locked_batch_row = first_batch.name
    saved_before = list(env.saved)
    original_get_values = env.db.get_values

    def reject_cross_batch_lock(
        doctype, filters=None, fieldname=None, for_update=False, **kwargs
    ):
        if (
            doctype == service.BATCH_DOCTYPE
            and filters == {"request": request.name}
            and for_update
        ):
            raise AssertionError("would wait for register-held batch row")
        return original_get_values(
            doctype,
            filters=filters,
            fieldname=fieldname,
            for_update=for_update,
            **kwargs,
        )

    monkeypatch.setattr(env.db, "get_values", reject_cross_batch_lock)
    with pytest.raises(ValidationError, match="\u5df2\u5173\u8054.*\u5176\u4ed6"):
        service.link_invoice(record.name, request.name, line.line_key)

    assert env.committed_read_calls
    query, values = env.committed_read_calls[-1]
    assert "FOR UPDATE" not in query.upper()
    assert values == (request.name,)
    assert env.nonblocking_committed_reads == 1
    assert env.committed_connections_closed == 1
    assert record.request == ""
    assert record.expense_line_key == ""
    assert second_batch.request == ""
    assert env.saved == saved_before


def test_attach_rejects_second_batch_without_waiting_for_register_row(
    env, monkeypatch
):
    request = _add_request(env, name="REQ-ATTACH-SINGLE-BATCH")
    held_batch = env.add_batch(name="BATCH-REGISTER-HELD", request=request.name)
    target_batch = env.add_batch(name="BATCH-ATTACH-TARGET", request="")
    record = env.add_record(
        name="INV-ATTACH-TARGET",
        batch=target_batch.name,
        request="",
    )
    env.register_locked_batch_row = held_batch.name
    saved_before = list(env.saved)
    original_get_values = env.db.get_values

    def reject_cross_batch_lock(
        doctype, filters=None, fieldname=None, for_update=False, **kwargs
    ):
        if (
            doctype == service.BATCH_DOCTYPE
            and filters == {"request": request.name}
            and for_update
        ):
            raise AssertionError("would wait for register-held batch row")
        return original_get_values(
            doctype,
            filters=filters,
            fieldname=fieldname,
            for_update=for_update,
            **kwargs,
        )

    monkeypatch.setattr(env.db, "get_values", reject_cross_batch_lock)
    with pytest.raises(ValidationError, match="\u5df2\u5173\u8054.*\u5176\u4ed6"):
        service.attach_batch_to_request(target_batch.name, request)

    query, values = env.committed_read_calls[-1]
    assert "FOR UPDATE" not in query.upper()
    assert values == (request.name,)
    assert env.nonblocking_committed_reads == 1
    assert env.committed_connections_closed == 1
    assert target_batch.request == ""
    assert record.request == ""
    assert env.saved == saved_before


def test_get_request_invoices_includes_batch_only_records_dedupes_and_orders(env):
    request = _add_request(env, name="REQ-HISTORICAL-BATCHES")
    first_batch = env.add_batch(name="BATCH-A", request=request.name)
    second_batch = env.add_batch(name="BATCH-B", request=request.name)
    env.add_record(
        name="INV-Z",
        batch=first_batch.name,
        request="",
        recognition_status="\u5df2\u786e\u8ba4",
    )
    env.add_record(
        name="INV-A",
        batch=first_batch.name,
        request=request.name,
        recognition_status="\u5df2\u786e\u8ba4",
    )
    env.add_record(
        name="INV-M",
        batch=second_batch.name,
        request="",
        recognition_status="\u5df2\u786e\u8ba4",
    )

    result = service.get_request_invoices(request.name)

    assert [row["name"] for row in result] == ["INV-A", "INV-M", "INV-Z"]
    assert [row["name"] for row in result].count("INV-A") == 1
    assert {row["batch"] for row in result} == {
        first_batch.name,
        second_batch.name,
    }


def test_get_request_invoices_checks_request_permission_before_collection_query(env, monkeypatch):
    env.roles["bob@example.com"] = ["Employee"]
    request = _add_request(
        env,
        name="REQ-PERMISSION-FIRST",
        owner="alice@example.com",
        employee="EMP-ALICE",
    )
    calls = []
    original = service._request_invoice_records

    def tracked(request_name, **kwargs):
        calls.append((request_name, kwargs))
        return original(request_name, **kwargs)

    monkeypatch.setattr(service, "_request_invoice_records", tracked)
    frappe_stub_module.session.user = "bob@example.com"

    with pytest.raises(ValidationError, match="\u65e0\u6743"):
        service.get_request_invoices(request.name)

    assert calls == []


# --- Real Frappe File auto-relink regression ---

def test_register_reloads_file_after_insert_auto_relink_without_stale_save(
    env, monkeypatch
):
    env.add_batch(name="BATCH-AUTO-RELINK")
    stale_file = env.add_file(
        filename="auto-relink.pdf",
        content=b"%PDF-auto-relink",
        batch="BATCH-AUTO-RELINK",
    )
    stale_file.modified = "2026-07-21 10:00:00.000001"
    original_insert = Doc.insert
    original_save = Doc.save
    fresh_holder = {}

    class TimestampMismatchError(Exception):
        pass

    def insert_with_frappe_relink(self, ignore_permissions=False):
        result = original_insert(
            self, ignore_permissions=ignore_permissions
        )
        if self.get("doctype") == service.RECORD_DOCTYPE:
            fresh_file = Doc(env, dict(stale_file))
            fresh_file.modified = "2026-07-21 10:00:00.000002"
            fresh_file.attached_to_doctype = service.RECORD_DOCTYPE
            fresh_file.attached_to_name = self.name
            fresh_file.attached_to_field = "invoice_file"
            env.docs["File"][stale_file.name] = fresh_file
            fresh_holder["file"] = fresh_file
        return result

    def reject_stale_file_save(self, ignore_permissions=False):
        if self.get("doctype") == "File":
            current = env.docs["File"][self.name]
            if self.get("modified") != current.get("modified"):
                raise TimestampMismatchError(self.name)
        return original_save(
            self, ignore_permissions=ignore_permissions
        )

    monkeypatch.setattr(Doc, "insert", insert_with_frappe_relink)
    monkeypatch.setattr(Doc, "save", reject_stale_file_save)

    result = service.register_file(
        "BATCH-AUTO-RELINK", stale_file.file_url
    )

    record = env.docs[service.RECORD_DOCTYPE][result["name"]]
    fresh_file = fresh_holder["file"]
    assert fresh_file is env.docs["File"][stale_file.name]
    assert fresh_file.attached_to_doctype == service.RECORD_DOCTYPE
    assert fresh_file.attached_to_name == record.name
    assert fresh_file.attached_to_field == "invoice_file"
    assert stale_file.attached_to_doctype == service.BATCH_DOCTYPE
    assert stale_file not in env.saved
    assert fresh_file not in env.saved
    assert env.current_read_calls.count(
        ("get_doc", "File", stale_file.name)
    ) >= 2


def test_workbench_listing_scopes_owner_and_bounds_filters(env):
    env.add_batch()
    env.add_record(name="INV-OWN-CONFIRMED", recognition_status="已确认")
    env.add_record(name="INV-OWN-PENDING", recognition_status="待确认")
    env.add_record(name="INV-OTHER", owner="other@example.com", uploaded_by="other@example.com", recognition_status="已确认")
    rows = service.list_workbench_invoices()
    assert {row["name"] for row in rows} == {"INV-OWN-CONFIRMED", "INV-OWN-PENDING"}
    assert all("ocr_payload" not in row for row in rows)
    confirmed = service.list_workbench_invoices(status="已确认")
    assert [row["name"] for row in confirmed] == ["INV-OWN-CONFIRMED"]
    frappe_stub_module.session.user = "finance@example.com"
    assert {row["name"] for row in service.list_workbench_invoices(view="all")} == {
        "INV-OWN-CONFIRMED", "INV-OWN-PENDING", "INV-OTHER",
    }
    with pytest.raises(ValidationError, match="状态"):
        service.list_workbench_invoices(status="伪造状态")
    with pytest.raises(ValidationError, match="数量"):
        service.list_workbench_invoices(limit=301)


def test_unconfirm_invoice_requires_unlinked_confirmed_record_and_audits(env):
    env.add_batch()
    record = env.add_record(
        recognition_status="已确认",
        confirmed_by="alice@example.com",
        confirmed_on=datetime(2026, 7, 21, 9, 0, 0),
        operation_log="[]",
    )
    result = service.unconfirm_invoice(record.name, "识别内容需要重核")
    assert result["recognition_status"] == "待确认"
    assert record.confirmed_by == "" and record.confirmed_on is None
    event = json.loads(record.operation_log)[-1]
    assert event["action"] == "撤回确认"
    assert event["from_status"] == "已确认" and event["to_status"] == "待确认"
    assert event["note"] == "识别内容需要重核"
    record.recognition_status = "已确认"
    record.request = "OA-1"
    with pytest.raises(ValidationError, match="下推"):
        service.unconfirm_invoice(record.name)
