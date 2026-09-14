"""Minimal runtime backport for the older staging/production source baselines."""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected legacy source shape: " + old[:70])
    return source.replace(old, new, 1)


def adapt_approval(source):
    source = "from rayher_hr_payroll.identity_accounts import account_user\nfrom rayher_hr_payroll.oa_role_resolver import resolve_role\n" + source
    source = replace_once(source, "    approvers = list(approvers or [label])",
                          "    approvers = [account_user(value) for value in (approvers or [label])]")
    helper = '''
def _position_step(role_key, mode="approve", prefix=""):
    snapshot = resolve_role(role_key)
    label = prefix + snapshot["role_label"]
    if snapshot.get("employee_name"):
        label += "：" + snapshot["employee_name"]
    return _step(label, mode=mode, approvers=[snapshot["user"]])


'''
    source = replace_once(source, "def _handle(", helper + "def _handle(")
    source = replace_once(source, "steps = [_step(FINANCE_AUDIT_LABEL, approvers=[FINANCE_AUDITOR_USER])]",
                          'steps = [_position_step("finance_auditor", prefix="审核：")]')
    source = replace_once(source, '''            _step(
                ASSET_APPROVAL_LABEL_PREFIX + ADMIN_APPROVER_NAME,
                approvers=[ADMIN_APPROVER_USER],
            )''', '''            _position_step("hr_manager", prefix=ASSET_APPROVAL_LABEL_PREFIX)''')
    source = replace_once(source, "steps.append(_handle(FINANCE_HANDLE_LABEL, approvers=[FINANCE_AUDITOR_USER]))",
                          'steps.append(_position_step("finance_auditor", mode="handle", prefix="确认付款："))')
    return source


def adapt_bootstrap(source):
    source = replace_once(source, "from __future__ import annotations",
                          "from __future__ import annotations\\nfrom rayher_hr_payroll.identity_accounts import account_user")
    start = source.index("def plan_business_accounts():")
    end = source.index("\n\ndef ", start + 1)
    body = source[start:end].replace("ACCOUNT_SPECS", "specs")
    body = body.replace("def plan_business_accounts():",
        'def plan_business_accounts():\n    specs = [{**row, "user_id": account_user(row["user_id"])} for row in ACCOUNT_SPECS]')
    return source[:start] + body + source[end:]


def adapt_access(source):
    return source.replace("'person046@staff.example.invalid'",
                          "'person046@staff.example.invalid', 'person030@staff.example.invalid'")


def adapt_procurement(source):
    source = replace_once(source, "from __future__ import annotations",
                          "from __future__ import annotations\\nfrom rayher_hr_payroll.identity_accounts import account_user")
    source = replace_once(source, "CHAIN_USERS = PMC_USERS | PURCHASE_USERS | {QINGBO_USER}",
                          'CHAIN_USERS = PMC_USERS | PURCHASE_USERS | {QINGBO_USER, "person030@staff.example.invalid"}')
    source = source.replace("PURCHASE_USERS | {QINGBO_USER} and", "PURCHASE_USERS | {account_user(QINGBO_USER)} and")
    source = source.replace("PROCUREMENT_MANAGER_USER.lower(), QINGBO_USER}", "PROCUREMENT_MANAGER_USER.lower(), account_user(QINGBO_USER)}")
    source = source.replace("_user() == QINGBO_USER", "_user() == account_user(QINGBO_USER)")
    return source
