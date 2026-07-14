from rayher_hr_payroll.oa_approval import build_expense_payment_route, build_leave_route


def labels(steps):
    return [step['label'] for step in steps]


def modes(steps):
    return [step['mode'] for step in steps]


def test_leave_route_matches_oa_sheet():
    steps = build_leave_route(supervisor='\u76f4\u5c5e\u4e0a\u7ea7')

    assert labels(steps) == ['\u76f4\u5c5e\u4e0a\u7ea7', '\u6f14\u793a\u5458\u5de510', '\u6f14\u793a\u5458\u5de537']
    assert modes(steps) == ['approve', 'approve', 'approve']


def test_expense_payment_finance_department_route_with_admin_asset():
    steps = build_expense_payment_route(
        department='\u8d22\u52a1\u90e8', supervisor='\u76f4\u5c5e\u4e0a\u7ea7', asset_category='\u884c\u653f\u56fa\u5b9a\u8d44\u4ea7'
    )

    assert labels(steps) == ['\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513', '\u76f4\u5c5e\u4e0a\u7ea7', '\u6f14\u793a\u5458\u5de510', '\u6f14\u793a\u5458\u5de528', '\u8d22\u52a1\u529e\u7406\uff1a\u6f14\u793a\u5458\u5de513']
    assert modes(steps) == ['approve', 'approve', 'approve', 'approve', 'handle']
    assert steps[0]['approvers'] == ['\u6f14\u793a\u5458\u5de513']
    assert steps[-1]['approvers'] == ['\u6f14\u793a\u5458\u5de513']


def test_expense_payment_sales_department_uses_cosign_for_qingbo_and_wangbo():
    steps = build_expense_payment_route(
        department='\u9500\u552e\u90e8', supervisor='\u76f4\u5c5e\u4e0a\u7ea7', asset_category='IT\u7c7b\u56fa\u5b9a\u8d44\u4ea7'
    )

    assert labels(steps) == ['\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513', '\u76f4\u5c5e\u4e0a\u7ea7', '\u6f14\u793a\u5458\u5de518', '\u6f14\u793a\u5458\u5de537\u3001\u6f14\u793a\u5458\u5de528', '\u8d22\u52a1\u529e\u7406\uff1a\u6f14\u793a\u5458\u5de513']
    assert modes(steps) == ['approve', 'approve', 'approve', 'all', 'handle']
    assert steps[3]['approvers'] == ['\u6f14\u793a\u5458\u5de537', '\u6f14\u793a\u5458\u5de528']


def test_expense_payment_other_department_skips_top_supervisor_and_non_asset_node():
    steps = build_expense_payment_route(
        department='\u7814\u53d1\u90e8', supervisor='\u6f14\u793a\u5458\u5de537', asset_category='\u5176\u5b83'
    )

    assert labels(steps) == ['\u8d22\u52a1\u5ba1\u8ba1\uff1a\u6f14\u793a\u5458\u5de513', '\u6f14\u793a\u5458\u5de537', '\u6f14\u793a\u5458\u5de528', '\u8d22\u52a1\u529e\u7406\uff1a\u6f14\u793a\u5458\u5de513']
    assert modes(steps) == ['approve', 'approve', 'approve', 'handle']
