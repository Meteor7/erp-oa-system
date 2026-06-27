from rayher_hr_payroll.approval_config import NOTIFICATIONS


def _by_name():
    return {n["name"]: n for n in NOTIFICATIONS}


def test_one_result_reminder_per_request_type():
    names = set(_by_name())
    for doctype in ("Leave Application", "Travel Request", "Expense Claim", "Compensatory Leave Request"):
        assert f"{doctype} 结果提醒" in names, doctype
    assert len(NOTIFICATIONS) == 4


def test_notifications_are_creatable_and_notify_applicant():
    for n in NOTIFICATIONS:
        # is_standard=1 would be rejected outside developer mode:
        assert n["is_standard"] == 0
        # only Email/Slack/System Notification/SMS are valid; bell == System Notification:
        assert n["channel"] == "System Notification"
        assert n["enabled"] == 1
        assert n["document_type"]
        # applicant is the recipient:
        assert n["recipients"] == [{"receiver_by_document_field": "owner"}]


def test_value_change_notifications_reference_real_fields_only():
    by = _by_name()
    # Leave Application has a real `status` field; Expense Claim uses workflow_state.
    assert by["Leave Application 结果提醒"]["event"] == "Value Change"
    assert by["Leave Application 结果提醒"]["value_changed"] == "status"
    assert by["Expense Claim 结果提醒"]["value_changed"] == "workflow_state"
    # Travel Request & Compensatory Leave Request have NO status field -> must fire on Submit,
    # NOT a Value Change on a missing column (which Frappe would auto-disable). value_changed
    # is reconciled to "" (present, empty) so a stale prior value cannot linger in the DB.
    for dt in ("Travel Request", "Compensatory Leave Request"):
        assert by[f"{dt} 结果提醒"]["event"] == "Submit"
        assert by[f"{dt} 结果提醒"]["value_changed"] == ""
    # Expense result reminder only fires on terminal decision states (not on the
    # applicant's own submit or intermediate manager/finance steps):
    cond = by["Expense Claim 结果提醒"]["condition"]
    assert "财务已审" in cond and "已拒绝" in cond


def test_notification_names_unique():
    names = [n["name"] for n in NOTIFICATIONS]
    assert len(names) == len(set(names))


def test_install_calls_ensure_notifications():
    import inspect
    import rayher_hr_payroll.install as install
    assert "ensure_notifications" in inspect.getsource(install)


def test_workflow_masters_cover_states_and_actions():
    from rayher_hr_payroll.approval_config import WORKFLOW_STATES, WORKFLOW_ACTIONS
    assert set(WORKFLOW_STATES) == {"草稿", "待经理审批", "待财务复核", "财务已审", "已拒绝"}
    assert {"提交审批", "经理批准", "财务复核", "驳回", "重新提交"} == set(WORKFLOW_ACTIONS)


def test_install_calls_ensure_workflow_masters():
    import inspect
    import rayher_hr_payroll.install as install
    assert "ensure_workflow_masters" in inspect.getsource(install)
