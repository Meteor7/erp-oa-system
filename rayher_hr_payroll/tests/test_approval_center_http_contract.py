import pytest


def test_approval_center_writes_are_post_only():
    frappe = pytest.importorskip("frappe")
    from rayher_hr_payroll.api.oa_entry import (
        attach_approval_business_document,
        save_approval_center_draft,
    )

    assert frappe.allowed_http_methods_for_whitelisted_func[save_approval_center_draft] == ["POST"]
    assert frappe.allowed_http_methods_for_whitelisted_func[attach_approval_business_document] == ["POST"]
