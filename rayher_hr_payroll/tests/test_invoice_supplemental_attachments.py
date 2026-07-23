from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from rayher_hr_payroll import invoice_supplemental_attachments as attachments


class ValidationError(Exception):
    pass


class Row(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as error:
            raise AttributeError(key) from error

    def __setattr__(self, key, value):
        self[key] = value

    def save(self, ignore_permissions=False):
        assert ignore_permissions is True
        self["saved"] = True
        return self

    def insert(self, ignore_permissions=False):
        assert ignore_permissions is True
        self["inserted"] = True
        self.setdefault("name", "ISA-1")
        return self


def _raise(message):
    raise ValidationError(str(message))


def test_invoice_attachment_mutability_ends_when_invoice_is_pushed(monkeypatch):
    monkeypatch.setattr(attachments.frappe, "throw", _raise)
    monkeypatch.setattr(attachments.frappe, "_", lambda value: value)

    attachments.validate_record_mutability(
        Row(name="INV-1", request="", recognition_status="已确认")
    )

    with pytest.raises(ValidationError, match="撤回"):
        attachments.validate_record_mutability(
            Row(name="INV-1", request="OA-1", recognition_status="已确认")
        )
    with pytest.raises(ValidationError, match="状态"):
        attachments.validate_record_mutability(
            Row(name="INV-1", request="", recognition_status="失败")
        )


def test_register_attachment_links_private_file_to_invoice_record(monkeypatch):
    monkeypatch.setattr(attachments.frappe, "throw", _raise)
    monkeypatch.setattr(attachments.frappe, "_", lambda value: value)
    record = Row(name="INV-1", request="", recognition_status="已确认")
    file_doc = Row(
        name="FILE-1",
        file_name="receipt.pdf",
        file_url="/private/files/receipt.pdf",
        owner="alice@example.com",
        is_private=1,
        attached_to_doctype="",
        attached_to_name="",
        attached_to_field="",
    )
    created = {}

    monkeypatch.setattr(
        attachments.invoice_service,
        "_transaction_lock",
        lambda *_args, **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_require_record",
        lambda name, write=False, current=False: record,
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_safe_file_url",
        lambda value: value,
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_file_doc",
        lambda file_url, current=False: file_doc,
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_read_limited",
        lambda _file: b"%PDF-1.7\nreceipt",
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_user",
        lambda: "alice@example.com",
    )
    monkeypatch.setattr(
        attachments.invoice_service,
        "_now",
        lambda: "2026-07-23 18:00:00",
    )
    monkeypatch.setattr(
        attachments.expense_attachments,
        "validate_file_registration",
        lambda value: value,
    )
    monkeypatch.setattr(
        attachments.frappe,
        "db",
        SimpleNamespace(
            exists=lambda *_args, **_kwargs: False,
            count=lambda *_args, **_kwargs: 0,
        ),
    )

    def get_doc(values, name=None):
        assert name is None
        created.update(values)
        return Row(values)

    monkeypatch.setattr(attachments.frappe, "get_doc", get_doc)

    result = attachments.register_attachment(
        "INV-1", "/private/files/receipt.pdf"
    )

    assert file_doc.attached_to_doctype == "OA Invoice Record"
    assert file_doc.attached_to_name == "INV-1"
    assert file_doc.attached_to_field == "expense_description"
    assert created["invoice_record"] == "INV-1"
    assert created["file"] == "FILE-1"
    assert result["name"] == "ISA-1"
    assert result["invoice_record"] == "INV-1"


def test_attachment_serializer_exposes_only_review_metadata():
    result = attachments.serialize_attachment(
        Row(
            name="ISA-1",
            invoice_record="INV-1",
            original_filename="receipt.pdf",
            mime_type="application/pdf",
            file_size=123,
            uploaded_by="alice@example.com",
            uploaded_on="2026-07-23 18:00:00",
            file_url="/private/files/secret.pdf",
            file_sha256="secret-hash",
        )
    )

    assert result == {
        "name": "ISA-1",
        "invoice_record": "INV-1",
        "original_filename": "receipt.pdf",
        "mime_type": "application/pdf",
        "file_size": 123,
        "uploaded_by": "alice@example.com",
        "uploaded_on": "2026-07-23 18:00:00",
    }
