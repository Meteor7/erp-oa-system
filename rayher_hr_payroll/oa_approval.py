REQUEST_LEAVE = "请假申请"
REQUEST_EXPENSE_PAYMENT = "费用付款申请"

FINANCE_AUDITOR_NAME = "演示员工13"
FINANCE_AUDITOR_USER = "person067@legacy.example.invalid"
ADMIN_APPROVER_NAME = "演示员工10"
ADMIN_APPROVER_USER = "person047@legacy.example.invalid"
IT_APPROVER_NAME = "演示员工18"
IT_APPROVER_USER = "person068@legacy.example.invalid"
FINANCE_MANAGER_NAME = "演示员工16"
FINANCE_MANAGER_USER = "person072@legacy.example.invalid"
VICE_MANAGER_NAME = "演示员工21"
VICE_MANAGER_USER = "person046@business.example.invalid"
GENERAL_MANAGER_NAME = "演示员工29"
GENERAL_MANAGER_USER = "person060@legacy.example.invalid"

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


def build_leave_route(supervisor):
    supervisor = _clean(supervisor)
    if not supervisor:
        raise ApprovalRouteError("leave route requires a supervisor")
    return [
        _step(supervisor),
        _step(VICE_MANAGER_NAME, approvers=[VICE_MANAGER_USER]),
        _step(GENERAL_MANAGER_NAME, approvers=[GENERAL_MANAGER_USER]),
    ]


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
):
    if request_type == REQUEST_LEAVE:
        return build_leave_route(supervisor=supervisor)
    if request_type == REQUEST_EXPENSE_PAYMENT:
        return build_expense_payment_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            asset_category=asset_category,
        )
    raise ApprovalRouteError("unsupported request type: %s" % request_type)