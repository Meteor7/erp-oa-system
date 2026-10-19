import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import business_documents as documents
from rayher_hr_payroll.rayher_hr_payroll.doctype.oa_business_document import (
    oa_business_document as business_document_controller,
)


class MemoryStore:
    def __init__(self):
        self.files = {}
        self.rows = []
        self.readable = True
        self.writable = True
        self.locks = []
        self.user = "owner@example.com"
        self.parent = SimpleNamespace(name="OA-1", owner="request-owner@example.com", request_type="采购申请", workflow_status="草稿", business_status="", price_submitted_on=None)

    def add_file(self, name, filename, content, private=True, attached_to_doctype=None):
        file_doc = SimpleNamespace(
            name=name,
            file_name=filename,
            file_url=f"/private/files/{filename}" if private else f"/files/{filename}",
            is_private=1 if private else 0,
            attached_to_doctype=attached_to_doctype,
            attached_to_name=None,
            content=content,
            file_size=len(content),
        )
        self.files[name] = file_doc
        return file_doc

    def require_request(self, request, ptype):
        allowed = self.readable if ptype == "read" else self.writable
        if not allowed:
            raise documents.BusinessDocumentError("无权访问父审批单")
        self.parent.name = request
        return self.parent

    def lock_versions(self, request, document_type):
        self.locks.append((request, document_type))
        rows = [
            row for row in self.rows
            if row["request"] == request and row["document_type"] == document_type
        ]
        return sorted(rows, key=lambda row: row["version_no"])

    def get_file(self, file_ref):
        return self.files[file_ref]

    def file_content(self, file_doc):
        return file_doc.content

    def insert(self, values):
        row = dict(values)
        row["name"] = f"DOC-{len(self.rows) + 1}"
        self.rows.append(row)
        return SimpleNamespace(**row)

    def link_file(self, file_doc, document, owner):
        file_doc.attached_to_doctype = "OA Business Document"
        file_doc.attached_to_name = document.name
        file_doc.owner = owner

    def list_documents(self, request):
        return [row for row in self.rows if row["request"] == request]

    def get_document(self, name):
        row = next(row for row in self.rows if row["name"] == name)
        return SimpleNamespace(**row)

    def delete_document(self, document):
        self.rows = [row for row in self.rows if row["name"] != document.name]

    def void_document(self, document, reason):
        row = next(row for row in self.rows if row["name"] == document.name)
        row.update({"status": "已作废", "void_reason": reason, "voided_by": self.user, "voided_on": self.now()})
        return SimpleNamespace(**row)

    def is_administrator(self):
        return False

    def actor(self):
        return self.user

    def now(self):
        return "2026-08-06 10:00:00"


def test_allowed_document_types_match_approved_archive_scope():
    assert documents.DOCUMENT_TYPES == (
        "需求申请", "报价单", "价格审批表", "PR", "PO", "演示员工116", "付款计划",
        "发票", "验收资料", "送货单", "收料单", "入库单", "付款回单", "退款回单", "采购完成报告", "其他补充资料",
    )


def test_doctype_document_type_options_match_runtime_scope():
    doctype_path = (
        Path(__file__).parents[1]
        / "rayher_hr_payroll/doctype/oa_business_document/oa_business_document.json"
    )
    metadata = json.loads(doctype_path.read_text(encoding="utf-8"))
    field = next(row for row in metadata["fields"] if row.get("fieldname") == "document_type")
    assert tuple(field["options"].splitlines()) == documents.DOCUMENT_TYPES


def test_attach_requires_parent_write_and_list_requires_parent_read():
    store = MemoryStore()
    store.add_file("FILE-1", "contract.pdf", b"%PDF-1.7\nbody")
    store.writable = False
    with pytest.raises(documents.BusinessDocumentError, match="父审批单"):
        documents.attach("OA-1", "演示员工116", "FILE-1", store=store)
    store.writable = True
    documents.attach("OA-1", "演示员工116", "FILE-1", store=store)
    store.readable = False
    with pytest.raises(documents.BusinessDocumentError, match="父审批单"):
        documents.list_documents("OA-1", store=store)


def test_upload_appends_version_and_reparents_private_file():
    store = MemoryStore()
    first_file = store.add_file("FILE-1", "contract.pdf", b"%PDF-1.7\nfirst")
    second_file = store.add_file("FILE-2", "contract-v2.pdf", b"%PDF-1.7\nsecond")
    first = documents.attach("OA-1", "演示员工116", "FILE-1", store=store)
    second = documents.attach("OA-1", "演示员工116", "FILE-2", store=store)
    assert first.version_no == 1
    assert second.version_no == 2
    assert second.supersedes == first.name
    assert second.file_sha256 != first.file_sha256
    assert first_file.attached_to_doctype == "OA Business Document"
    assert first_file.attached_to_name == first.name
    assert first_file.owner == "Administrator"
    assert store.locks == [("OA-1", "演示员工116"), ("OA-1", "演示员工116")]


def test_wrong_upload_can_be_deleted_before_price_submission():
    store = MemoryStore()
    store.add_file("FILE-1", "wrong.pdf", b"%PDF-1.7\nwrong")
    row = documents.attach("OA-1", "价格审批表", "FILE-1", store=store)
    result = documents.remove(row.name, store=store)
    assert result == {"name": row.name, "action": "deleted"}
    assert store.rows == []


def test_document_is_voided_with_reason_after_approval_starts():
    store = MemoryStore()
    store.add_file("FILE-1", "approved.pdf", b"%PDF-1.7\napproved")
    row = documents.attach("OA-1", "价格审批表", "FILE-1", store=store)
    store.parent.workflow_status = "已完成"
    store.parent.business_status = "价格已批准/待补充演示员工116信息"
    store.parent.price_submitted_on = "2026-08-25 12:00:00"
    with pytest.raises(documents.BusinessDocumentError, match="作废原因"):
        documents.remove(row.name, store=store)
    result = documents.remove(row.name, "上传文件错误", store=store)
    assert result["action"] == "voided"
    assert store.rows[0]["status"] == "已作废"
    assert store.rows[0]["void_reason"] == "上传文件错误"


def test_file_must_be_private_unattached_supported_and_magic_must_match():
    cases = [
        ("public", "x.pdf", b"%PDF-1.7", False, None, "私有"),
        ("attached", "x.pdf", b"%PDF-1.7", True, "Other", "已关联"),
        ("extension", "x.exe", b"MZ", True, None, "文件类型"),
        ("spoof", "x.pdf", b"MZ-not-pdf", True, None, "文件内容"),
        ("large", "x.pdf", b"%PDF-" + b"x" * (documents.MAX_FILE_SIZE + 1), True, None, "大小"),
    ]
    for index, (_label, filename, content, private, attached, message) in enumerate(cases):
        store = MemoryStore()
        store.add_file(f"FILE-{index}", filename, content, private, attached)
        with pytest.raises(documents.BusinessDocumentError, match=message):
            documents.attach("OA-1", "演示员工116", f"FILE-{index}", store=store)



def test_declared_oversize_is_rejected_before_reading_file_content():
    store = MemoryStore()
    file_doc = store.add_file("FILE-1", "large.pdf", b"%PDF-1.7")
    file_doc.file_size = documents.MAX_FILE_SIZE + 1
    reads = []
    store.file_content = lambda file_value: reads.append(file_value.name) or file_value.content
    with pytest.raises(documents.BusinessDocumentError, match="大小"):
        documents.attach("OA-1", "演示员工116", "FILE-1", store=store)
    assert reads == []


def test_fake_office_zip_is_rejected():
    store = MemoryStore()
    store.add_file("FILE-1", "fake.xlsx", b"PK\x03\x04not-a-real-office-file")
    with pytest.raises(documents.BusinessDocumentError, match="文件内容"):
        documents.attach("OA-1", "报价单", "FILE-1", store=store)

def test_invalid_document_type_and_duplicate_file_fail_closed():
    store = MemoryStore()
    store.add_file("FILE-1", "contract.pdf", b"%PDF-1.7\nbody")
    with pytest.raises(documents.BusinessDocumentError, match="资料类型"):
        documents.attach("OA-1", "用户随意类型", "FILE-1", store=store)
    documents.attach("OA-1", "演示员工116", "FILE-1", store=store)
    with pytest.raises(documents.BusinessDocumentError, match="已关联"):
        documents.attach("OA-1", "演示员工116", "FILE-1", store=store)


def test_business_document_permission_delegates_read_to_parent_and_denies_mutation(monkeypatch):
    doc = SimpleNamespace(request="OA-1")
    calls = []
    monkeypatch.setattr(
        documents,
        "oa_request_has_permission",
        lambda parent, ptype=None, user=None: calls.append((parent, ptype, user)) or False,
    )
    monkeypatch.setattr(documents.frappe, "get_doc", lambda doctype, name: SimpleNamespace(name=name))
    assert documents.business_document_has_permission(doc, "read", "employee@example.com") is False
    assert calls and calls[0][1:] == ("read", "employee@example.com")
    assert documents.business_document_has_permission(doc, "write", "employee@example.com") is False
    assert documents.business_document_has_permission(doc, "delete", "employee@example.com") is False





def test_frappe_store_serializes_versions_on_parent_row(monkeypatch):
    calls = []

    class DB:
        def sql(self, query, values, as_dict=False):
            calls.append((query, values, as_dict))
            return [{"name": "OA-1"}]

    monkeypatch.setattr(documents.frappe, "db", DB())
    monkeypatch.setattr(documents.frappe, "get_all", lambda *args, **kwargs: [])
    assert documents.FrappeBusinessDocumentStore().lock_versions("OA-1", "演示员工116") == []
    assert "FOR UPDATE" in calls[0][0]
    assert calls[0][1] == ("OA-1",)

def test_business_document_hooks_and_query_are_parent_scoped(monkeypatch):
    from rayher_hr_payroll import hooks

    assert hooks.permission_query_conditions["OA Business Document"] == (
        "rayher_hr_payroll.business_documents.business_document_query"
    )
    assert hooks.has_permission["OA Business Document"] == (
        "rayher_hr_payroll.business_documents.business_document_has_permission"
    )
    monkeypatch.setattr(documents, "oa_request_query", lambda user=None: "PARENT_SCOPE")
    query = documents.business_document_query("employee@example.com")
    assert "tabOA Business Document`.request" in query
    assert "PARENT_SCOPE" in query

def test_frappe_store_cannot_claim_another_users_private_file(monkeypatch):
    file_doc = SimpleNamespace(name="FILE-OTHER")
    monkeypatch.setattr(documents.frappe, "session", SimpleNamespace(user="attacker@example.com"))
    monkeypatch.setattr(documents.frappe, "get_doc", lambda doctype, name: file_doc)
    monkeypatch.setattr(documents.frappe, "has_permission", lambda *args, **kwargs: False)
    with pytest.raises(documents.BusinessDocumentError, match="无权使用"):
        documents.FrappeBusinessDocumentStore().get_file("FILE-OTHER")

def test_document_controller_rejects_update_and_delete(monkeypatch):
    class PermissionError(Exception):
        pass

    monkeypatch.setattr(business_document_controller.frappe, "PermissionError", PermissionError)
    monkeypatch.setattr(
        business_document_controller.frappe,
        "throw",
        lambda message, exc=None: (_ for _ in ()).throw((exc or RuntimeError)(message)),
    )
    existing = SimpleNamespace(is_new=lambda: False)
    with pytest.raises(PermissionError, match="只允许追加"):
        business_document_controller.OABusinessDocument.validate(existing)
    with pytest.raises(PermissionError, match="不允许删除"):
        business_document_controller.OABusinessDocument.on_trash(existing)

def test_reading_documents_follows_the_oa_row_scope_when_user_permissions_block(monkeypatch):
    parent = SimpleNamespace(name="OA-9", request_type="出差申请")
    monkeypatch.setattr(documents.frappe, "get_doc", lambda *args, **kwargs: parent)
    monkeypatch.setattr(documents.frappe, "session", SimpleNamespace(user="approver@example.com"), raising=False)
    monkeypatch.setattr(documents.frappe, "has_permission", lambda *args, **kwargs: False)
    store = documents.FrappeBusinessDocumentStore()
    monkeypatch.setattr(documents, "oa_request_has_permission", lambda doc, ptype, user: None)
    assert store.require_request("OA-9", "read") is parent
    monkeypatch.setattr(documents, "oa_request_has_permission", lambda doc, ptype, user: False)
    with pytest.raises(documents.BusinessDocumentError):
        store.require_request("OA-9", "read")
    monkeypatch.setattr(documents, "oa_request_has_permission", lambda doc, ptype, user: None)
    with pytest.raises(documents.BusinessDocumentError):
        store.require_request("OA-9", "write")
