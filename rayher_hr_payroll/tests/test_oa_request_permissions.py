from rayher_hr_payroll.invoice_ocr import permissions


def test_procurement_owner_edit_permission_uses_procurement_feature_gate(monkeypatch):
    checked = []
    request = {
        "name": "PROC-1",
        "request_type": "采购申请",
        "owner": "alice@example.com",
        "employee": "EMP-1",
    }
    monkeypatch.setattr(
        permissions,
        "can_access_request_type",
        lambda request_type, user: checked.append((request_type, user)) or True,
    )
    monkeypatch.setattr(permissions, "_roles", lambda user: set())
    monkeypatch.setattr(
        permissions,
        "_request_access_context",
        lambda request_doc, user, current=False: (request, {"employee": "EMP-1"}, []),
    )

    assert permissions.can_edit_request(request, "alice@example.com", current=True) is True
    assert checked == [("采购申请", "alice@example.com")]
