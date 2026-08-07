from rayher_hr_payroll.oa_document_types import REQUEST_LEAVE
REQUEST_EXPENSE_PAYMENT = "费用付款申请"

FINANCE_AUDITOR_NAME = "演示员工13"
FINANCE_AUDITOR_USER = "person067@staff.example.invalid"
ADMIN_APPROVER_NAME = "演示员工10"
ADMIN_APPROVER_USER = "person047@staff.example.invalid"
IT_APPROVER_NAME = "演示员工18"
IT_APPROVER_USER = "person068@staff.example.invalid"
FINANCE_MANAGER_NAME = "演示员工16"
FINANCE_MANAGER_USER = "person072@staff.example.invalid"
VICE_MANAGER_NAME = "演示员工21"
VICE_MANAGER_USER = "person046@staff.example.invalid"
GENERAL_MANAGER_NAME = "演示员工29"
GENERAL_MANAGER_USER = "person060@staff.example.invalid"

FINANCE_AUDIT_LABEL = "财务审核：" + FINANCE_AUDITOR_NAME
SUPERVISOR_LABEL_PREFIX = "直属主管："
ASSET_APPROVAL_LABEL_PREFIX = "固定资产审批："
FINANCE_MANAGER_LABEL = "财务主管：" + FINANCE_MANAGER_NAME
VICE_MANAGER_LABEL = "副总经理：" + VICE_MANAGER_NAME
GENERAL_MANAGER_LABEL = "总经理：" + GENERAL_MANAGER_NAME
FINANCE_HANDLE_LABEL = "确认付款：" + FINANCE_AUDITOR_NAME
CASHIER_LABEL = FINANCE_HANDLE_LABEL

FINANCE_DEPARTMENT = "财务部"
SALES_DEPARTMENT = "销售部"
CUSTOMER_SERVICE_DEPARTMENTS = {"客服部", "客户服务部"}
ADMIN_ASSET = "非电子类固定资产（人事/行政）"
IT_ASSET = "电子类固定资产（IT）"
OTHER_ASSET = "其他"
TOP_SUPERVISORS = {
    VICE_MANAGER_NAME,
    VICE_MANAGER_USER,
    GENERAL_MANAGER_NAME,
    GENERAL_MANAGER_USER,
}


class ApprovalRouteError(ValueError):
    pass


def _step(label, mode="approve", approvers=None):
    approvers = list(approvers or [label])
    return {"label": label, "mode": mode, "approvers": approvers}


def _handle(label, approvers=None):
    return _step(label, mode="handle", approvers=approvers or [label])


def _clean(value):
    return str(value or "").strip()


def classify_department(department):
    text = _clean(department)
    if FINANCE_DEPARTMENT in text or "财务" in text:
        return "finance"
    if SALES_DEPARTMENT in text or "销售" in text or any(name in text for name in CUSTOMER_SERVICE_DEPARTMENTS):
        return "sales"
    return "other"


def normalize_asset_category(asset_category):
    text = _clean(asset_category)
    if not text or text in {OTHER_ASSET, "其它"}:
        return OTHER_ASSET
    if text == ADMIN_ASSET or "非电子" in text or "行政" in text or "人事" in text:
        return ADMIN_ASSET
    if text == IT_ASSET or "IT" in text.upper() or text.startswith("电子类固定资产"):
        return IT_ASSET
    raise ApprovalRouteError(f"不支持的资产类型：{text}")


LEAVE_ADMIN_APPROVER_NAME = "演示员工10"
LEAVE_ADMIN_APPROVER_USER = ADMIN_APPROVER_USER
LEAVE_FINANCE_APPROVER_NAME = "演示员工28"
LEAVE_FINANCE_APPROVER_USER = GENERAL_MANAGER_USER
LEAVE_OTHER_APPROVER_NAME = "演示员工37"
LEAVE_OTHER_APPROVER_USER = VICE_MANAGER_USER
LEAVE_COPY_RECIPIENTS = (
    (LEAVE_ADMIN_APPROVER_NAME, LEAVE_ADMIN_APPROVER_USER),
    (LEAVE_OTHER_APPROVER_NAME, LEAVE_OTHER_APPROVER_USER),
)


def leave_copy_recipients(applicant_user=None):
    applicant = _clean(applicant_user).lower()
    recipients = []
    seen = set()
    for label, user in LEAVE_COPY_RECIPIENTS:
        user_id = _clean(user).lower()
        if not user_id or user_id == applicant or user_id in seen:
            continue
        seen.add(user_id)
        recipients.append({"label": label, "user": user_id})
    return recipients


def _append_leave_step(steps, label, approver, applicant_user=None):
    user_id = _clean(approver).lower()
    if not user_id:
        raise ApprovalRouteError(f"请假审批人 {label} 没有关联可用账号")
    if user_id == _clean(applicant_user).lower():
        return
    if any(user_id in {_clean(value).lower() for value in step["approvers"]} for step in steps):
        return
    steps.append(_step(label, approvers=[user_id]))


def build_leave_route(
    department,
    supervisor,
    *,
    supervisor_user,
    supervisor_decision=None,
    applicant_user=None,
):
    department = _clean(department)
    supervisor = _clean(supervisor)
    supervisor_user = _clean(supervisor_user).lower()
    supervisor_decision = _clean(supervisor_decision)
    applicant_user = _clean(applicant_user).lower()
    if not department:
        raise ApprovalRouteError("请假申请缺少申请人所属部门")
    if supervisor_decision not in {"", "approve", "skip"}:
        raise ApprovalRouteError(f"不支持的直属主管决策：{supervisor_decision}")
    if supervisor_decision != "skip":
        if not supervisor:
            raise ApprovalRouteError("请假申请缺少直属上级")
        if not supervisor_user:
            raise ApprovalRouteError(f"直属上级 {supervisor} 没有关联可用账号")
        if applicant_user and supervisor_user == applicant_user:
            raise ApprovalRouteError("申请人不能成为自己的直属上级审批人")

    steps = []
    if supervisor_decision != "skip":
        _append_leave_step(
            steps,
            SUPERVISOR_LABEL_PREFIX + supervisor,
            supervisor_user,
            applicant_user,
        )
    _append_leave_step(
        steps,
        LEAVE_ADMIN_APPROVER_NAME,
        LEAVE_ADMIN_APPROVER_USER,
        applicant_user,
    )
    if classify_department(department) == "finance":
        _append_leave_step(
            steps,
            LEAVE_FINANCE_APPROVER_NAME,
            LEAVE_FINANCE_APPROVER_USER,
            applicant_user,
        )
    else:
        _append_leave_step(
            steps,
            LEAVE_OTHER_APPROVER_NAME,
            LEAVE_OTHER_APPROVER_USER,
            applicant_user,
        )
    if not steps:
        raise ApprovalRouteError("请假审批路线不能为空")
    return steps


def _stage_two_steps(supervisor, supervisor_user, supervisor_decision):
    name = _clean(supervisor)
    user_id = _clean(supervisor_user)
    decision = _clean(supervisor_decision)
    if decision == "skip" or (not decision and name in TOP_SUPERVISORS):
        return []
    if decision not in {"", "approve"}:
        raise ApprovalRouteError(f"不支持的直属主管决策：{decision}")
    if not name:
        raise ApprovalRouteError("费用报销缺少直属主管解析结果")
    if decision == "approve" and not user_id:
        raise ApprovalRouteError(f"直属主管 {name} 没有关联可用账号")
    return [
        _step(
            SUPERVISOR_LABEL_PREFIX + name,
            approvers=[user_id or name],
        )
    ]


def build_expense_payment_route(
    department,
    supervisor,
    asset_category=OTHER_ASSET,
    *,
    supervisor_user=None,
    supervisor_decision=None,
):
    dept = classify_department(department)
    asset = normalize_asset_category(asset_category)
    steps = [_step(FINANCE_AUDIT_LABEL, approvers=[FINANCE_AUDITOR_USER])]
    steps.extend(_stage_two_steps(supervisor, supervisor_user, supervisor_decision))

    if asset == ADMIN_ASSET:
        steps.append(
            _step(
                ASSET_APPROVAL_LABEL_PREFIX + ADMIN_APPROVER_NAME,
                approvers=[ADMIN_APPROVER_USER],
            )
        )
    elif asset == IT_ASSET:
        steps.append(
            _step(
                ASSET_APPROVAL_LABEL_PREFIX + IT_APPROVER_NAME,
                approvers=[IT_APPROVER_USER],
            )
        )

    steps.append(_step(FINANCE_MANAGER_LABEL, approvers=[FINANCE_MANAGER_USER]))
    if dept == "finance":
        steps.append(_step(GENERAL_MANAGER_LABEL, approvers=[GENERAL_MANAGER_USER]))
    elif dept == "sales":
        steps.append(
            _step(
                VICE_MANAGER_LABEL + "、" + GENERAL_MANAGER_LABEL,
                mode="all",
                approvers=[VICE_MANAGER_USER, GENERAL_MANAGER_USER],
            )
        )
    else:
        steps.extend(
            [
                _step(VICE_MANAGER_LABEL, approvers=[VICE_MANAGER_USER]),
                _step(GENERAL_MANAGER_LABEL, approvers=[GENERAL_MANAGER_USER]),
            ]
        )
    steps.append(_handle(FINANCE_HANDLE_LABEL, approvers=[FINANCE_AUDITOR_USER]))
    return steps


def build_route(
    request_type,
    *,
    department=None,
    supervisor=None,
    asset_category=None,
    supervisor_user=None,
    supervisor_decision=None,
    applicant_user=None,
):
    if request_type == REQUEST_LEAVE:
        return build_leave_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            applicant_user=applicant_user,
        )
    if request_type == REQUEST_EXPENSE_PAYMENT:
        return build_expense_payment_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            asset_category=asset_category,
        )
    raise ApprovalRouteError("unsupported request type: %s" % request_type)