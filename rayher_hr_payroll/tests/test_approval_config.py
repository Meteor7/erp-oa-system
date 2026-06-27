from rayher_hr_payroll.approval_config import NOTIFICATIONS


def _by_name():
    return {n["name"]: n for n in NOTIFICATIONS}


def test_each_request_type_has_submit_and_decision_reminders():
    names = set(_by_name())
    for doctype in ("Leave Application", "Travel Request", "Expense Claim", "Compensatory Leave Request"):
        assert f"{doctype} 提交提醒" in names, doctype
        assert f"{doctype} 结果提醒" in names, doctype


def test_notifications_enabled_with_document_type():
    for n in NOTIFICATIONS:
        assert n["enabled"] == 1
        assert n["document_type"]
        assert n["channel"] in ("Email", "System Notification")


def test_notification_names_unique():
    names = [n["name"] for n in NOTIFICATIONS]
    assert len(names) == len(set(names))


def test_install_calls_ensure_notifications():
    import inspect, rayher_hr_payroll.install as install
    assert "ensure_notifications" in inspect.getsource(install)


def test_notifications_are_not_standard_so_they_can_be_created():
    # is_standard=1 Notifications cannot be created/edited outside developer mode
    # (Frappe raises "Cannot edit Standard Notification"). Code-created ones must be 0.
    for n in NOTIFICATIONS:
        assert n["is_standard"] == 0
