from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import PurePosixPath

import frappe

def oa_request_query(user=None):
    from rayher_hr_payroll.oa_access import oa_request_query as query

    return query(user)


def oa_request_has_permission(doc, ptype=None, user=None):
    from rayher_hr_payroll.oa_access import oa_request_has_permission as has_permission

    return has_permission(doc, ptype, user)


DOCUMENT_TYPES = (
    "需求申请",
    "报价单",
    "价格审批表",
    "PR",
    "PO",
    "合同",
    "付款计划",
    "发票",
    "验收资料",
    "送货单",
    "收料单",
    "入库单",
    "付款回单",
    "采购完成报告",
)
MAX_FILE_SIZE = 20 * 1024 * 1024
MAGIC_BY_EXTENSION = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
}
READ_PTYPES = {None, "read", "select", "report", "export", "print", "email"}


class BusinessDocumentError(ValueError):
    pass


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    getter = getattr(value, "get", None)
    if callable(getter):
        result = getter(key)
        return default if result is None else result
    return getattr(value, key, default)


def _name(value):
    return str(value if isinstance(value, str) else _get(value, "name") or "").strip()


def _document_type(value):
    result = str(value or "").strip()
    if result not in DOCUMENT_TYPES:
        raise BusinessDocumentError("资料类型无效")
    return result


def _filename(file_doc):
    raw = str(_get(file_doc, "file_name") or "").replace("\\", "/")
    result = PurePosixPath(raw).name
    if not result or result in {".", ".."} or len(result) > 255:
        raise BusinessDocumentError("文件名无效")
    return result


def _validate_file_metadata(file_doc):
    declared_size = _get(file_doc, "file_size")
    if declared_size is not None:
        try:
            declared_size = int(declared_size)
        except (TypeError, ValueError):
            raise BusinessDocumentError("文件大小无效")
        if declared_size <= 0 or declared_size > MAX_FILE_SIZE:
            raise BusinessDocumentError("文件大小无效")


def _validate_office_archive(extension, content):
    if extension not in {".docx", ".xlsx"}:
        return
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        raise BusinessDocumentError("文件内容与扩展名不匹配")
    required_prefix = "word/" if extension == ".docx" else "xl/"
    if "[Content_Types].xml" not in names or not any(
        name.startswith(required_prefix) for name in names
    ):
        raise BusinessDocumentError("文件内容与扩展名不匹配")


def _validate_file(file_doc, content):
    if not bool(_get(file_doc, "is_private")) or not str(
        _get(file_doc, "file_url") or ""
    ).startswith("/private/files/"):
        raise BusinessDocumentError("只允许归档私有文件")
    if _get(file_doc, "attached_to_doctype") or _get(file_doc, "attached_to_name"):
        raise BusinessDocumentError("文件已关联其他业务记录")
    filename = _filename(file_doc)
    extension = PurePosixPath(filename).suffix.lower()
    signatures = MAGIC_BY_EXTENSION.get(extension)
    if not signatures:
        raise BusinessDocumentError("文件类型不允许")
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, bytes):
        raise BusinessDocumentError("文件内容无效")
    if not content or len(content) > MAX_FILE_SIZE:
        raise BusinessDocumentError("文件大小无效")
    if not any(content.startswith(signature) for signature in signatures):
        raise BusinessDocumentError("文件内容与扩展名不匹配")
    _validate_office_archive(extension, content)
    return filename, content


class FrappeBusinessDocumentStore:
    def require_request(self, request, ptype):
        name = _name(request)
        if not name:
            raise BusinessDocumentError("父审批单不存在")
        doc = frappe.get_doc("OA Approval Request", name)
        user = frappe.session.user
        allowed = frappe.has_permission(
            "OA Approval Request", ptype=ptype, doc=doc, user=user
        )
        if not allowed and ptype == "write" and getattr(doc, "request_type", None) in {
            "采购申请", "购买申请", "采购付款",
        }:
            employee = frappe.db.get_value(
                "Employee", {"user_id": user, "status": "Active"}, "name"
            )
            roles = set(frappe.get_roles(user) or [])
            allowed = (
                getattr(doc, "owner", None) == user
                or (employee and getattr(doc, "employee", None) == employee)
                or bool(roles & {"System Manager", "Purchase User", "Purchase Manager", "Accounts User"})
            )
        if not allowed:
            raise BusinessDocumentError("无权访问父审批单")
        return doc

    def lock_versions(self, request, document_type):
        rows = frappe.db.sql(
            """SELECT name FROM `tabOA Approval Request`
                WHERE name = %s FOR UPDATE""",
            (request,),
            as_dict=True,
        )
        if len(rows) != 1:
            raise BusinessDocumentError("父审批单不存在")
        return frappe.get_all(
            "OA Business Document",
            filters={"request": request, "document_type": document_type},
            fields=["name", "version_no", "file_sha256"],
            order_by="version_no asc, name asc",
        )

    def get_file(self, file_ref):
        name = _name(file_ref)
        if not name:
            raise BusinessDocumentError("文件不存在")
        if isinstance(file_ref, str) and file_ref.startswith("/private/files/"):
            name = frappe.db.get_value("File", {"file_url": file_ref}, "name")
        if not name:
            raise BusinessDocumentError("文件不存在")
        file_doc = frappe.get_doc("File", name)
        if not frappe.has_permission(
            "File", ptype="read", doc=file_doc, user=frappe.session.user
        ):
            raise BusinessDocumentError("无权使用该私有文件")
        return file_doc

    def file_content(self, file_doc):
        return file_doc.get_content()

    def insert(self, values):
        return frappe.get_doc({"doctype": "OA Business Document", **values}).insert(
            ignore_permissions=True
        )

    def link_file(self, file_doc, document, owner):
        frappe.db.set_value(
            "File",
            file_doc.name,
            {
                "attached_to_doctype": "OA Business Document",
                "attached_to_name": document.name,
                "attached_to_field": "file",
                "owner": owner,
            },
            update_modified=False,
        )

    def list_documents(self, request):
        return frappe.get_all(
            "OA Business Document",
            filters={"request": request},
            fields=[
                "name", "request", "document_type", "version_no", "file",
                "file_sha256", "original_filename", "uploaded_by", "uploaded_on",
                "supersedes",
            ],
            order_by="document_type asc, version_no desc, name desc",
        )

    def actor(self):
        return frappe.session.user

    def now(self):
        return frappe.utils.now_datetime()


def _store(store):
    return store or FrappeBusinessDocumentStore()


def attach(request, document_type, file_ref, *, store=None):
    store = _store(store)
    document_type = _document_type(document_type)
    parent = store.require_request(request, "write")
    request_name = _name(parent)
    versions = list(store.lock_versions(request_name, document_type))
    previous = max(versions, key=lambda row: int(_get(row, "version_no") or 0), default=None)
    file_doc = store.get_file(file_ref)
    _validate_file_metadata(file_doc)
    filename, content = _validate_file(file_doc, store.file_content(file_doc))
    version_no = int(_get(previous, "version_no") or 0) + 1
    result = store.insert({
        "request": request_name,
        "document_type": document_type,
        "version_no": version_no,
        "file": _get(file_doc, "file_url"),
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "original_filename": filename,
        "uploaded_by": store.actor(),
        "uploaded_on": store.now(),
        "supersedes": _name(previous) or None,
    })
    store.link_file(file_doc, result, "Administrator")
    return result


def list_documents(request, *, store=None):
    store = _store(store)
    parent = store.require_request(request, "read")
    return store.list_documents(_name(parent))


def business_document_query(user=None):
    user = user or frappe.session.user
    if not user or user == "Guest":
        return "1=0"
    parent_scope = oa_request_query(user)
    return (
        "EXISTS (SELECT 1 FROM `tabOA Approval Request` "
        "WHERE `tabOA Approval Request`.name = `tabOA Business Document`.request "
        f"AND ({parent_scope}))"
    )


def business_document_has_permission(doc, ptype=None, user=None):
    user = user or frappe.session.user
    if not user or user == "Guest":
        return False
    if ptype not in READ_PTYPES:
        return False
    request = _get(doc, "request")
    if not request:
        return False
    try:
        parent = frappe.get_doc("OA Approval Request", request)
    except frappe.DoesNotExistError:
        return False
    return oa_request_has_permission(parent, "read", user)