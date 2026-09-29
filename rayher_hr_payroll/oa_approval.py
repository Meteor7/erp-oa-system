from rayher_hr_payroll.attendance_requests import ATTENDANCE_TYPES
from rayher_hr_payroll.oa_role_resolver import ApprovalRoleResolutionError, resolve_role
from rayher_hr_payroll.identity_accounts import account_user
from rayher_hr_payroll.oa_document_types import (
    REQUEST_DIRECT_PURCHASE,
    REQUEST_LEAVE,
    REQUEST_PAYMENT,
    REQUEST_PROCUREMENT,
    REQUEST_PROCUREMENT_PAYMENT,
    REQUEST_REIMBURSEMENT,
    REQUEST_TRAVEL,
)

REQUEST_EXPENSE_PAYMENT = "费用付款申请"

FINANCE_AUDITOR_NAME = "演示员工32"
FINANCE_AUDITOR_USER = "person055@staff.example.invalid"
FINANCE_ACCOUNTANT_NAME = "演示员工19"
FINANCE_ACCOUNTANT_USER = "person065@staff.example.invalid"
ADMIN_APPROVER_NAME = "人事经理"
ADMIN_APPROVER_USER = "person047@staff.example.invalid"
IT_APPROVER_NAME = "演示员工18"
IT_APPROVER_USER = "person068@staff.example.invalid"
PRODUCTION_APPROVER_NAME = "演示员工241"
PRODUCTION_APPROVER_USER = "person074@staff.example.invalid"
PMC_APPROVER_NAME = "演示员工178"
PMC_APPROVER_USER = "person076@staff.example.invalid"
FINANCE_MANAGER_NAME = "演示员工16"
FINANCE_MANAGER_USER = "person072@staff.example.invalid"
VICE_MANAGER_NAME = "演示员工21"
VICE_MANAGER_USER = "person046@staff.example.invalid"
GENERAL_MANAGER_NAME = "演示员工29"
GENERAL_MANAGER_USER = "person060@staff.example.invalid"
PROCUREMENT_MANAGER_NAME = "演示员工216"
PROCUREMENT_MANAGER_USER = "person033@staff.example.invalid"

FINANCE_AUDIT_LABEL = "出纳审核"
SUPERVISOR_LABEL_PREFIX = "直属主管："
ASSET_APPROVAL_LABEL_PREFIX = "固定资产审批："
FINANCE_MANAGER_LABEL = "财务主管：" + FINANCE_MANAGER_NAME
VICE_MANAGER_LABEL = "副总经理：" + VICE_MANAGER_NAME
GENERAL_MANAGER_LABEL = "总经理：" + GENERAL_MANAGER_NAME
FINANCE_HANDLE_LABEL = "出纳确认付款"
CASHIER_LABEL = FINANCE_HANDLE_LABEL

FINANCE_DEPARTMENT = "财务部"
SALES_DEPARTMENT = "销售部"
CUSTOMER_SERVICE_DEPARTMENTS = {"客服部", "客户服务部"}
ADMIN_ASSET = "非电子类固定资产（人事/行政）"
IT_ASSET = "电子类固定资产（IT）"
PRODUCTION_ASSET = "生产设备、生产工具及器具"
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


class _RoleSnapshots(dict):
    def __missing__(self, key):
        try:
            value = resolve_role(key)
        except ApprovalRoleResolutionError as exc:
            raise ApprovalRouteError(str(exc)) from exc
        self[key] = value
        return value


def _roles(roles=None):
    return _RoleSnapshots({key: dict(value) for key, value in (roles or {}).items() if value})


def _role_label(snapshot, *, name_only=False, with_name=False):
    role_label = _clean(snapshot.get("role_label"))
    employee_name = _clean(snapshot.get("employee_name"))
    if name_only:
        return employee_name or role_label
    if with_name and employee_name:
        return f"{role_label}：{employee_name}"
    return role_label or employee_name


def _role_user(snapshot, label):
    user = _clean(snapshot.get("user")).lower()
    if not user:
        raise ApprovalRouteError(f"{label}没有关联可用账号")
    return user


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
    if text == PRODUCTION_ASSET or "生产设备" in text or "生产工具" in text:
        return PRODUCTION_ASSET
    raise ApprovalRouteError(f"不支持的资产类型：{text}")


LEAVE_ADMIN_APPROVER_NAME = "人事经理"
LEAVE_ADMIN_APPROVER_USER = ADMIN_APPROVER_USER
LEAVE_FINANCE_APPROVER_NAME = GENERAL_MANAGER_NAME
LEAVE_FINANCE_APPROVER_USER = GENERAL_MANAGER_USER
LEAVE_OTHER_APPROVER_NAME = VICE_MANAGER_NAME
LEAVE_OTHER_APPROVER_USER = VICE_MANAGER_USER


def leave_copy_recipients(applicant_user=None, roles=None):
    snapshots = _roles(roles)
    candidates = [
        ("人事经理", snapshots["hr_manager"]),
        (_role_label(snapshots["vice_manager"], name_only=True), snapshots["vice_manager"]),
    ]
    applicant = _clean(applicant_user).lower()
    recipients = []
    seen = set()
    for label, snapshot in candidates:
        user_id = _role_user(snapshot, label)
        if user_id == applicant or user_id in seen:
            continue
        seen.add(user_id)
        recipients.append({"label": label, "user": user_id})
    return recipients


def _append_unique_group(steps, label, approvers, *, mode="approve", applicant_user=None):
    applicant = _clean(applicant_user).lower()
    existing = {
        _clean(value).lower()
        for step in steps
        for value in step["approvers"]
        if _clean(value)
    }
    users = []
    for approver in approvers:
        user_id = _clean(approver).lower()
        if not user_id:
            raise ApprovalRouteError(f"{label}没有关联可用账号")
        if user_id == applicant or user_id in existing or user_id in users:
            continue
        users.append(user_id)
    if users:
        steps.append(_step(label, mode=mode, approvers=users))


def _append_unique_approval(steps, label, approver, *, mode="approve", applicant_user=None):
    _append_unique_group(steps, label, [approver], mode=mode, applicant_user=applicant_user)


def _top_supervisor(name, user, roles=None):
    snapshots = _roles(roles)
    top_values = set()
    for key in ("vice_manager", "general_manager"):
        top_values.add(_clean(snapshots[key].get("user")))
        top_values.add(_clean(snapshots[key].get("employee_name")))
    return _clean(name) in top_values or _clean(user) in top_values


def build_leave_route(
    department,
    supervisor,
    *,
    supervisor_user,
    supervisor_decision=None,
    applicant_user=None,
    roles=None,
):
    department = _clean(department)
    supervisor = _clean(supervisor)
    supervisor_user = _clean(supervisor_user).lower()
    supervisor_decision = _clean(supervisor_decision)
    applicant_user = _clean(applicant_user).lower()
    snapshots = _roles(roles)
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
        _append_unique_approval(steps, SUPERVISOR_LABEL_PREFIX + supervisor, supervisor_user, applicant_user=applicant_user)
    hr = snapshots["hr_manager"]
    _append_unique_approval(steps, "人事经理", _role_user(hr, "人事经理"), applicant_user=applicant_user)
    final_key = "general_manager" if classify_department(department) == "finance" else "vice_manager"
    final = snapshots[final_key]
    _append_unique_approval(
        steps,
        _role_label(final, name_only=True),
        _role_user(final, _role_label(final)),
        applicant_user=applicant_user,
    )
    if not steps:
        raise ApprovalRouteError("请假审批路线不能为空")
    return steps


def _stage_two_steps(supervisor, supervisor_user, supervisor_decision, roles=None):
    name = _clean(supervisor)
    user_id = _clean(supervisor_user)
    decision = _clean(supervisor_decision)
    if decision == "skip" or (not decision and _top_supervisor(name, user_id, roles)):
        return []
    if decision not in {"", "approve"}:
        raise ApprovalRouteError(f"不支持的直属主管决策：{decision}")
    if not name:
        raise ApprovalRouteError("费用报销缺少直属主管解析结果")
    if not user_id:
        raise ApprovalRouteError(f"直属主管 {name} 没有关联可用账号")
    return [_step(SUPERVISOR_LABEL_PREFIX + name, approvers=[user_id])]


def build_expense_payment_route(
    department,
    supervisor,
    asset_category=OTHER_ASSET,
    *,
    supervisor_user=None,
    supervisor_decision=None,
    roles=None,
):
    dept = classify_department(department)
    asset = normalize_asset_category(asset_category)
    snapshots = _roles(roles)
    finance = snapshots["finance_auditor"]
    finance_manager = snapshots["finance_manager"]
    vice = snapshots["vice_manager"]
    general = snapshots["general_manager"]
    steps = [_step("出纳审核", approvers=[_role_user(finance, "出纳")])]
    steps.extend(_stage_two_steps(supervisor, supervisor_user, supervisor_decision, roles))

    if asset == ADMIN_ASSET:
        hr = snapshots["hr_manager"]
        _append_unique_approval(steps, ASSET_APPROVAL_LABEL_PREFIX + "人事经理", _role_user(hr, "人事经理"))
    elif asset == IT_ASSET:
        it = snapshots["it_asset_owner"]
        _append_unique_approval(steps, _role_label(it, with_name=True), _role_user(it, "IT负责人"))
    elif asset == PRODUCTION_ASSET:
        production = snapshots["production_asset_owner"]
        _append_unique_approval(steps, _role_label(production, with_name=True), _role_user(production, "生产设备负责人"))

    _append_unique_approval(steps, _role_label(finance_manager, with_name=True), _role_user(finance_manager, "财务主管"))
    if dept == "finance":
        _append_unique_approval(steps, _role_label(general, with_name=True), _role_user(general, "总经理"))
    elif dept == "sales":
        managers = [
            (_role_label(vice, with_name=True), _role_user(vice, "副总经理")),
            (_role_label(general, with_name=True), _role_user(general, "总经理")),
        ]
        existing = {_clean(value).lower() for step in steps for value in step["approvers"]}
        remaining = [(label, user) for label, user in managers if user not in existing]
        if remaining:
            _append_unique_group(
                steps,
                "、".join(label for label, _user in remaining),
                [user for _label, user in remaining],
                mode="all" if len(remaining) > 1 else "approve",
            )
    else:
        _append_unique_approval(steps, _role_label(vice, with_name=True), _role_user(vice, "副总经理"))
        _append_unique_approval(steps, _role_label(general, with_name=True), _role_user(general, "总经理"))
    steps.append(_handle("出纳确认付款", approvers=[_role_user(finance, "出纳")]))
    return steps


def build_procurement_route(
    *, supervisor, supervisor_user, project_owner=None, project_owner_name=None,
    asset_category=OTHER_ASSET, supervisor_decision=None, applicant_user=None, roles=None,
):
    """Build procurement approvals with upstream cosign before PMC.

    The executive demand-final and downstream execution steps remain unchanged; only
    the ordering of supervisor/project-owner/PMC is changed.
    """
    snapshots = _roles(roles)
    steps = []
    decision = _clean(supervisor_decision)
    if decision not in {"", "approve", "skip"}:
        raise ApprovalRouteError(f"不支持的直属主管决策：{decision}")

    # Build the upstream approval pair by account. A person who is both the
    # direct supervisor and project owner must appear once, not as a duplicate
    # self-cosign node.
    parallel = []
    if decision != "skip" and not (not decision and _top_supervisor(supervisor, supervisor_user, roles)):
        if not _clean(supervisor):
            raise ApprovalRouteError("采购申请缺少直属上级")
        parallel.append((SUPERVISOR_LABEL_PREFIX + _clean(supervisor), _clean(supervisor_user).lower()))
    if _clean(project_owner):
        parallel.append(("项目主管：" + (_clean(project_owner_name) or _clean(project_owner)), _clean(project_owner).lower()))
    deduped_parallel = []
    seen_parallel_users = set()
    for label, user in parallel:
        if not user and label.startswith(SUPERVISOR_LABEL_PREFIX):
            # 修复（2026-09-29，审查 X3-12）：直属上级没有启用的账号时原来悄悄去掉主管节点。
            raise ApprovalRouteError(f"直属上级 {_clean(supervisor)} 没有关联可用账号，不能生成采购审批路线")
        if not user or user in seen_parallel_users:
            continue
        seen_parallel_users.add(user)
        deduped_parallel.append((label, user))
    if deduped_parallel:
        if len(deduped_parallel) == 1:
            _append_unique_approval(steps, deduped_parallel[0][0], deduped_parallel[0][1], applicant_user=applicant_user)
        else:
            _append_unique_group(
                steps, "、".join(label for label, _user in deduped_parallel) + "（会签）",
                [user for _label, user in deduped_parallel], mode="all", applicant_user=applicant_user,
            )
    pmc = snapshots["pmc"]
    _append_unique_approval(
        steps, _role_label(pmc, with_name=True), _role_user(pmc, "PMC"),
    )
    vice = snapshots["vice_manager"]
    vice_user = _role_user(vice, "副总经理")
    _append_unique_approval(
        steps, "需求终审：" + _role_label(vice, with_name=True), vice_user,
        applicant_user=applicant_user,
    )
    # Demand approval ends at Qingbo final approval. PR, quoting, and price approval
    # are separate execution documents and must not become OA approval steps.
    return steps


def build_direct_purchase_route(
    *, purchase_method, supervisor, supervisor_user, supervisor_decision=None,
    applicant_user=None, upper_supervisor=None, upper_supervisor_user=None, roles=None,
):
    method = _clean(purchase_method)
    snapshots = _roles(roles)
    if method == "京东购买":
        hr = snapshots["hr_manager"]
        vice = snapshots["vice_manager"]
        approvers = []
        for label, user_id in (
            ("人事经理", _role_user(hr, "人事经理")),
            (_role_label(vice, name_only=True), _role_user(vice, "副总经理")),
        ):
            if user_id != _clean(applicant_user).lower() and user_id not in approvers:
                approvers.append(user_id)
        if not approvers:
            raise ApprovalRouteError("京东购买会签路线不能为空")
        return [_step(
            "京东购买会签：人事经理、" + _role_label(vice, name_only=True),
            mode="all",
            approvers=approvers,
        )]
    if method == "其他购买":
        name = _clean(supervisor)
        user_id = _clean(supervisor_user).lower()
        decision = _clean(supervisor_decision)
        if decision not in {"", "approve", "skip"}:
            raise ApprovalRouteError(f"不支持的直属主管决策：{decision}")
        steps = []
        if decision != "skip":
            if not name:
                raise ApprovalRouteError("其他购买缺少直属部门主管")
            if not user_id:
                raise ApprovalRouteError(f"直属部门主管 {name} 没有关联可用账号")
            _append_unique_approval(
                steps,
                "直属部门主管：" + name,
                user_id,
                applicant_user=applicant_user,
            )

        vice = snapshots["vice_manager"]
        vice_name = _clean(vice.get("employee_name")) or _clean(vice.get("role_label")) or "演示员工21"
        vice_user = _role_user(vice, "副总经理")
        if _top_supervisor("", applicant_user, snapshots):
            raise ApprovalRouteError("公司高管本人不适用员工其他购买审批流程")
        _append_unique_approval(
            steps,
            "副总经理：" + vice_name,
            vice_user,
            applicant_user=applicant_user,
        )
        if not steps:
            raise ApprovalRouteError("高管本人不适用员工其他购买审批流程")
        return steps
    raise ApprovalRouteError("购买申请必须选择京东购买或其他购买")


def build_procurement_payment_route(*, payment_stage, roles=None):
    stage = _clean(payment_stage)
    if stage not in {"预付款", "到货款", "尾款", "到货后全额付款"}:
        raise ApprovalRouteError(f"采购付款阶段无效：{stage}")
    snapshots = _roles(roles)
    vice = snapshots["vice_manager"]
    accountant = snapshots["finance_accountant"]
    finance_manager = snapshots["finance_manager"]
    finance = snapshots["finance_auditor"]
    general = snapshots["general_manager"]
    finance_user = _role_user(finance, "出纳")
    general_user = _role_user(general, "总经理")
    return [
        _step(
            _role_label(vice, name_only=True),
            approvers=[_role_user(vice, "副总经理")],
        ),
        _step(
            _role_label(accountant, with_name=True),
            approvers=[_role_user(accountant, "总账会计")],
        ),
        _step(
            _role_label(finance_manager, with_name=True),
            approvers=[_role_user(finance_manager, "财务主管")],
        ),
        _step(
            _role_label(finance, with_name=True),
            approvers=[finance_user],
        ),
        _handle(
            "总经理付款：" + _role_label(general, name_only=True),
            approvers=[general_user],
        ),
    ]


def build_route(
    request_type,
    *,
    department=None,
    supervisor=None,
    asset_category=None,
    supervisor_user=None,
    supervisor_decision=None,
    applicant_user=None,
    project_owner=None,
    project_owner_name=None,
    purchase_method=None,
    payment_stage=None,
    upper_supervisor=None,
    upper_supervisor_user=None,
    roles=None,
):
    if request_type in ATTENDANCE_TYPES:
        return build_leave_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            applicant_user=applicant_user,
            roles=roles,
        )
    if request_type == REQUEST_PROCUREMENT:
        return build_procurement_route(
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            applicant_user=applicant_user,
            project_owner=project_owner,
            project_owner_name=project_owner_name,
            asset_category=asset_category,
            roles=roles,
        )
    if request_type == REQUEST_DIRECT_PURCHASE:
        return build_direct_purchase_route(
            purchase_method=purchase_method,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            applicant_user=applicant_user,
            upper_supervisor=upper_supervisor,
            upper_supervisor_user=upper_supervisor_user,
            roles=roles,
        )
    if request_type == REQUEST_TRAVEL:
        # 出差申请与购买申请的"其他购买"路线相同：直属主管 → 副总经理。
        return build_direct_purchase_route(
            purchase_method="其他购买",
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            applicant_user=applicant_user,
            upper_supervisor=upper_supervisor,
            upper_supervisor_user=upper_supervisor_user,
            roles=roles,
        )
    if request_type in {REQUEST_REIMBURSEMENT, REQUEST_PAYMENT}:
        # 报销单、付款单沿用现有费用付款申请的审批路线。
        return build_expense_payment_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            asset_category=asset_category,
            roles=roles,
        )
    if request_type == REQUEST_PROCUREMENT_PAYMENT:
        return build_procurement_payment_route(payment_stage=payment_stage, roles=roles)
    if request_type == REQUEST_EXPENSE_PAYMENT:
        return build_expense_payment_route(
            department=department,
            supervisor=supervisor,
            supervisor_user=supervisor_user,
            supervisor_decision=supervisor_decision,
            asset_category=asset_category,
            roles=roles,
        )
    raise ApprovalRouteError("unsupported request type: %s" % request_type)
