REQUEST_LEAVE = "\u8bf7\u5047\u7533\u8bf7"
REQUEST_EXPENSE_PAYMENT = "\u8d39\u7528\u4ed8\u6b3e\u7533\u8bf7"

FINANCE_AUDITOR_NAME = "\u6f14\u793a\u5458\u5de513"
FINANCE_AUDITOR_USER = "person067@legacy.example.invalid"
VICE_MANAGER_NAME = "\u6f14\u793a\u5458\u5de521"
VICE_MANAGER_USER = "person046@business.example.invalid"
GENERAL_MANAGER_NAME = "\u6f14\u793a\u5458\u5de529"
GENERAL_MANAGER_USER = "person060@legacy.example.invalid"
IT_APPROVER_NAME = "\u6f14\u793a\u5458\u5de518"

FINANCE_AUDIT_LABEL = "\u8d22\u52a1\u5ba1\u8ba1\uff1a" + FINANCE_AUDITOR_NAME
FINANCE_HANDLE_LABEL = "\u8d22\u52a1\u529e\u7406\uff1a" + FINANCE_AUDITOR_NAME
FINANCE_MANAGER_LABEL = "\u8d22\u52a1\u4e3b\u7ba1\uff1a" + FINANCE_AUDITOR_NAME
VICE_MANAGER_LABEL = "\u526f\u603b\u7ecf\u7406\uff1a" + VICE_MANAGER_NAME
GENERAL_MANAGER_LABEL = "\u603b\u7ecf\u7406\uff1a" + GENERAL_MANAGER_NAME
CASHIER_LABEL = "\u51fa\u7eb3\u4ed8\u6b3e\uff1a" + FINANCE_AUDITOR_NAME

FINANCE_DEPARTMENT = "\u8d22\u52a1\u90e8"
SALES_DEPARTMENT = "\u9500\u552e\u90e8"
ADMIN_ASSET = "\u884c\u653f\u56fa\u5b9a\u8d44\u4ea7"
IT_ASSET = "IT\u7c7b\u56fa\u5b9a\u8d44\u4ea7"
OTHER_ASSET = "\u5176\u5b83"
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
    if FINANCE_DEPARTMENT in text or "\u8d22\u52a1" in text:
        return "finance"
    if SALES_DEPARTMENT in text or "\u9500\u552e" in text:
        return "sales"
    return "other"


def normalize_asset_category(asset_category):
    text = _clean(asset_category)
    if not text:
        return OTHER_ASSET
    if "IT" in text.upper():
        return IT_ASSET
    if "\u884c\u653f" in text:
        return ADMIN_ASSET
    return OTHER_ASSET


def build_leave_route(supervisor):
    supervisor = _clean(supervisor)
    if not supervisor:
        raise ApprovalRouteError("leave route requires a supervisor")
    return [
        _step(supervisor),
        _step(VICE_MANAGER_NAME, approvers=[VICE_MANAGER_USER]),
        _step(GENERAL_MANAGER_NAME, approvers=[GENERAL_MANAGER_USER]),
    ]


def build_expense_payment_route(department, supervisor, asset_category=OTHER_ASSET):
    dept = classify_department(department)
    asset = normalize_asset_category(asset_category)
    supervisor = _clean(supervisor) or "\u76f4\u5c5e\u4e0a\u7ea7"
    steps = [
        _step(FINANCE_AUDIT_LABEL, approvers=[FINANCE_AUDITOR_USER]),
        _step(supervisor, approvers=[supervisor]),
    ]
    if asset == ADMIN_ASSET:
        steps.append(_step(VICE_MANAGER_NAME, approvers=[VICE_MANAGER_USER]))
    elif asset == IT_ASSET:
        steps.append(_step(IT_APPROVER_NAME, approvers=[IT_APPROVER_NAME]))
    if dept == "sales":
        steps.append(
            _step(
                VICE_MANAGER_NAME + "\u3001" + GENERAL_MANAGER_NAME,
                mode="all",
                approvers=[VICE_MANAGER_USER, GENERAL_MANAGER_USER],
            )
        )
    elif supervisor not in {GENERAL_MANAGER_NAME, GENERAL_MANAGER_USER}:
        steps.append(_step(GENERAL_MANAGER_NAME, approvers=[GENERAL_MANAGER_USER]))
    steps.append(_handle(FINANCE_HANDLE_LABEL, approvers=[FINANCE_AUDITOR_USER]))
    return steps


def build_route(request_type, *, department=None, supervisor=None, asset_category=None):
    if request_type == REQUEST_LEAVE:
        return build_leave_route(supervisor=supervisor)
    if request_type == REQUEST_EXPENSE_PAYMENT:
        return build_expense_payment_route(
            department=department,
            supervisor=supervisor,
            asset_category=asset_category,
        )
    raise ApprovalRouteError("unsupported request type: %s" % request_type)
