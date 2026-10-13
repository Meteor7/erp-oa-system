from __future__ import annotations


ROLE_SPECS = {
    "it_asset_owner": {"label": "IT负责人", "designation": "网络工程师"},
    "pmc": {"label": "PMC", "designation": None, "assignment_required": True},
    "hr_manager": {
        "label": "人事经理",
        "designation": "人事行政经理",
        "designations": ("人事行政经理", "人事经理"),
    },
    "finance_auditor": {"label": "出纳", "designation": "出纳"},
    "finance_accountant": {"label": "总账会计", "designation": "总账会计"},
    "finance_manager": {"label": "财务主管", "designation": "财务主管"},
    "vice_manager": {"label": "副总经理", "designation": "副总经理"},
    "general_manager": {"label": "总经理", "designation": "总经理"},
    "production_asset_owner": {"label": "生产设备负责人", "designation": "生产主管"},
    "procurement_manager": {"label": "采购经理", "designation": "采购经理"},
    # 出差申请审批通过后到前台备案、安排行程（2026-10-13）：只认岗位任命，职务“行政专员”只用来给新站点补建任命。
    "front_desk": {"label": "前台办理", "designation": "行政专员"},
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
        if row and not row.get("employee"):
            row["employee_name"] = frappe.db.get_value("User", row["user"], "full_name") or ""
        if row and row.get("employee"):
            employee = self.get_employee(row["employee"])
            if not employee or employee.status != "Active" or employee.user_id != row["user"]:
                raise ApprovalRoleResolutionError("审批岗位绑定的员工状态或账号不匹配")
        return row

    def assignment_exists(self, role_key):
        import frappe

        return bool(frappe.db.exists("OA Approval Role Assignment", {"role_key": role_key}))

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


def _designation_holder(role_key, spec, store):
    """按员工职务找岗位的人。只用于给没有配置的岗位补建配置（seed_missing_assignments）。"""
    rows = []
    for designation in spec.get("designations") or (spec["designation"],):
        if not designation:
            continue
        rows = list(store.employees_for_designation(designation) or [])
        if rows:
            break
    if not rows:
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到在职人员")
    eligible = [
        row for row in rows
        if _text(_get(row, "user_id")) and store.is_user_enabled(_text(_get(row, "user_id")).lower())
    ]
    if len(eligible) > 1:
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}找到多个具备启用账号的在职人员，无法唯一解析")
    if len(eligible) == 1:
        return _snapshot(role_key, spec, eligible[0])
    if len(rows) == 1:
        return _snapshot(role_key, spec, rows[0])
    raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到关联启用账号的在职人员")


def designation_suggestion(role_key, *, store=None):
    """按职务推荐的岗位人选（诊断和补建配置用），不参与审批。"""
    spec = ROLE_SPECS.get(_text(role_key))
    if not spec:
        raise ApprovalRoleResolutionError(f"未知审批角色：{role_key}")
    return _designation_holder(_text(role_key), spec, _store(store))


def seed_missing_assignments(*, store=None):
    """给一条配置都没有的岗位按职务补建一次配置（新装的站点）；已有配置（包括停用的）不动。"""
    store = _store(store)
    seeded = []
    for role_key, spec in ROLE_SPECS.items():
        if store.assignment_exists(role_key):
            continue
        try:
            holder = _designation_holder(role_key, spec, store)
        except ApprovalRoleResolutionError:
            continue
        if not holder["user"] or not store.is_user_enabled(holder["user"]):
            continue
        store.upsert_assignment(role_key, spec["label"], holder["employee"], holder["user"])
        seeded.append(role_key)
    return seeded


def _resolve_role_uncached(role_key, *, store=None):
    role_key = _text(role_key)
    spec = ROLE_SPECS.get(role_key)
    if not spec:
        raise ApprovalRoleResolutionError(f"未知审批角色：{role_key}")
    store = _store(store)
    row = store.get_assignment(role_key)
    # 修复（2026-09-29，审查 R3-55-2，决定 D4）：审批岗位只认岗位任命（只有系统管理员能改）。
    # 原来没有启用的任命时按员工职务找人，人事改一下某人的职务就能让他成为出纳、总经理等审批人。
    # 职务只用于诊断和给新站点补建任命（designation_suggestion / seed_missing_assignments）。
    if not row or not int(_get(row, "enabled") or 0):
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有找到有效配置，请在岗位任命中设置")
    result = _snapshot(role_key, spec, row)
    if not result["user"]:
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}没有关联用户账号")
    if not store.is_user_enabled(result["user"]):
        raise ApprovalRoleResolutionError(f"审批角色{spec['label']}的账号未启用")
    return result


def _bootstrap_position(role_key, store=None):
    store = _store(store)
    resolved = resolve_role(role_key, store=store)
    ensure_roles = getattr(store, "ensure_user_roles", None)
    if callable(ensure_roles):
        ensure_roles(resolved["user"], ["Employee", "Purchase User"])
    ensure_permissions = getattr(store, "ensure_employee_permissions", None)
    if callable(ensure_permissions) and resolved["employee"]:
        ensure_permissions(resolved["employee"], resolved["user"])
    return resolved


def bootstrap_pmc(*, store=None):
    """Ensure permissions for the configured holder; never reinstate a predecessor."""
    return _bootstrap_position("pmc", store)


def bootstrap_procurement_manager(*, store=None):
    return _bootstrap_position("procurement_manager", store)


def resolve_role(role_key, *, store=None):
    from rayher_hr_payroll.list_read_scope import active, reuse
    if store is not None or not active():
        return _resolve_role_uncached(role_key, store=store)
    import frappe
    key = (frappe.local.site, frappe.session.user, _text(role_key))
    return reuse(key, lambda: _resolve_role_uncached(role_key))
