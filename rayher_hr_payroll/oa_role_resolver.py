from __future__ import annotations


ROLE_SPECS = {
    "pmc": {"label": "PMC", "designation": None, "assignment_required": True},
    "hr_manager": {"label": "人事经理", "designation": "人事行政经理"},
    "finance_auditor": {"label": "财务审核", "designation": "出纳"},
    "finance_manager": {"label": "财务主管", "designation": "财务主管"},
    "vice_manager": {"label": "副总经理", "designation": "副总经理"},
    "general_manager": {"label": "总经理", "designation": "总经理"},
    "production_asset_owner": {"label": "生产设备负责人", "designation": "生产主管"},
    "procurement_manager": {"label": "采购经理", "designation": "采购经理"},
}
PMC_EMPLOYEE = "HR-EMP-90017"
PMC_EMPLOYEE_NAME = "演示员工178"
PMC_USER = "person076@staff.example.invalid"
PROCUREMENT_MANAGER_EMPLOYEE = "HR-EMP-90018"
PROCUREMENT_MANAGER_NAME = "演示员工216"
PROCUREMENT_MANAGER_USER = "person033@staff.example.invalid"


class ApprovalRoleResolutionError(ValueError):
    pass


def _get(value, key, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value):
    return str(value or "").strip()


class FrappeRoleStore:
    def get_assignment(self, role_key):
        import frappe

        row = frappe.db.get_value(
            "OA Approval Role Assignment",
            {"role_key": role_key, "enabled": 1},
            ["role_key", "role_label", "employee", "user", "enabled"],
            as_dict=True,
        )
        if row and row.get("employee"):
            row["employee_name"] = frappe.db.get_value("Employee", row["employee"], "employee_name") or ""
        return row

    def employees_for_designation(self, designation):
        import frappe

        return frappe.get_all(
            "Employee",
            filters={"designation": designation, "status": "Active"},
            fields=["name", "employee_name", "user_id", "designation", "status"],
            order_by="name asc",
            limit_page_length=0,
        )

    def is_user_enabled(self, user):
        import frappe

        return bool(frappe.db.get_value("User", user, "enabled"))

    def get_employee(self, employee):
        import frappe

        if not frappe.db.exists("Employee", employee):
            return None
        return frappe.db.get_value(
            "Employee", employee,
            ["name", "employee_name", "status", "user_id"],
            as_dict=True,
        )

    def get_user(self, user):
        import frappe

        if not frappe.db.exists("User", user):
            return None
        return frappe.db.get_value("User", user, ["name", "enabled", "full_name"], as_dict=True)

    def create_user(self, values):
        import frappe

        roles = list(values.get("roles") or [])
        user_values = {key: value for key, value in values.items() if key != "roles"}
        doc = frappe.get_doc({"doctype": "User", **user_values})
        doc.insert(ignore_permissions=True)
        if roles:
            doc.add_roles(*roles)
        return doc

    def bind_employee_user(self, employee, user):
        import frappe

        frappe.db.set_value("Employee", employee, "user_id", user)

    def ensure_user_roles(self, user, roles):
        import frappe

        doc = frappe.get_doc("User", user)
        existing = set(frappe.get_roles(user) or [])
        missing = [role for role in roles if role not in existing]
        if missing:
            doc.add_roles(*missing)

    def ensure_employee_permissions(self, employee, user):
        import frappe

        employee_doc = frappe.get_doc("Employee", employee)
        for allow, value, applicable in (
            ("Employee", employee_doc.name, "Employee"),
            ("Company", employee_doc.company, None),
        ):
            if not value or frappe.db.exists(
                "User Permission", {"user": user, "allow": allow, "for_value": value}
            ):
                continue
            values = {
                "doctype": "User Permission", "user": user,
                "allow": allow, "for_value": value,
            }
            if applicable:
                values.update({"applicable_for": applicable, "apply_to_all_doctypes": 0})
            frappe.get_doc(values).insert(ignore_permissions=True)

    def upsert_assignment(self, role_key, role_label, employee, user):
        import frappe

        name = frappe.db.get_value("OA Approval Role Assignment", {"role_key": role_key}, "name")
        doc = frappe.get_doc("OA Approval Role Assignment", name) if name else frappe.new_doc("OA Approval Role Assignment")
        doc.update({
            "role_key": role_key,
            "role_label": role_label,
            "employee": employee,
            "user": user,
            "enabled": 1,
        })
        doc.save(ignore_permissions=True)
        return doc


def _store(store=None):
    return store or FrappeRoleStore()


def _snapshot(role_key, spec, row, user=None):
    resolved_user = _text(user or _get(row, "user") or _get(row, "user_id")).lower()
    return {
        "role_key": role_key,
        "role_label": _text(_get(row, "role_label")) or spec["label"],
        "user": resolved_user,
        "employee": _text(_get(row, "employee") or _get(row, "name")),
        "employee_name": _text(_get(row, "employee_name")),
    }


def resolve_role(role_key, *, store=None):
    role_key = _text(role_key)
    spec = ROLE_SPECS.get(role_key)
    if not spec:
        raise ApprovalRoleResolutionError(f"未知审批角色：{role_key}")
    store = _store(store)
    if spec.get("assignment_required"):
        row = store.get_assignment(role_key)
        if not row or not int(_get(row, "enabled") or 0):
            raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到有效配置")
        result = _snapshot(role_key, spec, row)
    else:
        rows = list(store.employees_for_designation(spec["designation"]) or [])
        if not rows:
            raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到在职人员")
        eligible = [
            row for row in rows
            if _text(_get(row, "user_id")) and store.is_user_enabled(_text(_get(row, "user_id")).lower())
        ]
        if len(eligible) > 1:
            raise ApprovalRoleResolutionError(f"审批角色{spec['label']}找到多个具备启用账号的在职人员，无法唯一解析")
        if len(eligible) == 1:
            result = _snapshot(role_key, spec, eligible[0])
        elif len(rows) == 1:
            result = _snapshot(role_key, spec, rows[0])
        else:
            raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到关联启用账号的在职人员")
    if not result["user"]:
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有关联用户账号")
    if not store.is_user_enabled(result["user"]):
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}的账号未启用")
    return result


def bootstrap_pmc(*, store=None):
    store = _store(store)
    employee = store.get_employee(PMC_EMPLOYEE)
    if not employee:
        raise ApprovalRoleResolutionError(f"PMC员工{PMC_EMPLOYEE}不存在")
    if _text(_get(employee, "employee_name")) != PMC_EMPLOYEE_NAME:
        raise ApprovalRoleResolutionError(f"PMC员工{PMC_EMPLOYEE}必须是演示员工178")
    if _text(_get(employee, "status")) != "Active":
        raise ApprovalRoleResolutionError("PMC员工演示员工178不是在职状态")
    existing_employee_user = _text(_get(employee, "user_id")).lower()
    if existing_employee_user and existing_employee_user != PMC_USER:
        raise ApprovalRoleResolutionError(f"演示员工178已绑定其他账号：{existing_employee_user}")
    user = store.get_user(PMC_USER)
    if user and not int(_get(user, "enabled") or 0):
        raise ApprovalRoleResolutionError("演示员工178账号已存在但未启用")
    if not user:
        store.create_user({
            "email": PMC_USER,
            "first_name": PMC_EMPLOYEE_NAME,
            "enabled": 1,
            "send_welcome_email": 0,
            "roles": ["Employee"],
        })
    if not existing_employee_user:
        store.bind_employee_user(PMC_EMPLOYEE, PMC_USER)
    existing_assignment = store.get_assignment("pmc")
    if not existing_assignment or _text(_get(existing_assignment, "user")).lower() != PMC_USER:
        store.upsert_assignment("pmc", "PMC", PMC_EMPLOYEE, PMC_USER)
    return {
        "role_key": "pmc",
        "role_label": "PMC",
        "user": PMC_USER,
        "employee": PMC_EMPLOYEE,
        "employee_name": PMC_EMPLOYEE_NAME,
    }


def bootstrap_procurement_manager(*, store=None):
    """Ensure the active procurement manager has an operational account.

    Existing enabled account links are resolved by designation, so personnel
    changes do not require code changes. The named fallback provisions the
    current incumbent only when the designation has no usable account yet.
    """
    store = _store(store)
    try:
        resolved = resolve_role("procurement_manager", store=store)
    except ApprovalRoleResolutionError as resolution_error:
        employee = store.get_employee(PROCUREMENT_MANAGER_EMPLOYEE)
        if (
            not employee
            or _text(_get(employee, "employee_name")) != PROCUREMENT_MANAGER_NAME
            or _text(_get(employee, "status")) != "Active"
        ):
            raise resolution_error
        existing_employee_user = _text(_get(employee, "user_id")).lower()
        if existing_employee_user and existing_employee_user != PROCUREMENT_MANAGER_USER:
            raise ApprovalRoleResolutionError(
                f"演示员工216已绑定其他账号：{existing_employee_user}"
            )
        user = store.get_user(PROCUREMENT_MANAGER_USER)
        if user and not int(_get(user, "enabled") or 0):
            raise ApprovalRoleResolutionError("演示员工216账号已存在但未启用")
        if not user:
            store.create_user({
                "email": PROCUREMENT_MANAGER_USER,
                "first_name": PROCUREMENT_MANAGER_NAME,
                "enabled": 1,
                "send_welcome_email": 0,
                "roles": ["Employee", "Purchase User"],
            })
        if not existing_employee_user:
            store.bind_employee_user(PROCUREMENT_MANAGER_EMPLOYEE, PROCUREMENT_MANAGER_USER)
        resolved = resolve_role("procurement_manager", store=store)

    ensure_roles = getattr(store, "ensure_user_roles", None)
    if callable(ensure_roles):
        ensure_roles(resolved["user"], ["Employee", "Purchase User"])
    ensure_permissions = getattr(store, "ensure_employee_permissions", None)
    if callable(ensure_permissions):
        ensure_permissions(resolved["employee"], resolved["user"])
    return resolved
