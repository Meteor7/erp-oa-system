"""Idempotent provisioning for Finance and executive OA accounts."""

from __future__ import annotations

import secrets

import frappe

from rayher_hr_payroll.access_control import BUSINESS_EXECUTIVE_ROLE

RAYHER_DEFAULT_APP = "rayher_hr_payroll"
EXECUTIVE_ROLES = (
    "HR Manager",
    "Accounts User",
    "Department Manager",
    "All Project Access",
    BUSINESS_EXECUTIVE_ROLE,
)

ACCOUNT_SPECS = (
    {
        "user_id": "admin@staff.example.invalid",
        "full_name": "QIHENG DEMO Admin",
        "employee": None,
        "employee_name": None,
        "roles": ("System Manager",),
    },
    {
        "user_id": "person067@staff.example.invalid",
        "full_name": "\u6f14\u793a\u4eba\u5458Hc518b1",
        "employee": "HR-EMP-90008",
        "employee_name": "\u6f14\u793a\u4eba\u5458Hc518b1",
        "roles": ("Employee", "Accounts User"),
    },
    {
        "user_id": "person065@staff.example.invalid",
        "full_name": "\u6f14\u793a\u4eba\u5458H0c8197",
        "employee": "HR-EMP-90016",
        "employee_name": "\u6f14\u793a\u4eba\u5458H0c8197",
        "roles": ("Employee", "Accounts User"),
    },
    {
        "user_id": "person072@staff.example.invalid",
        "full_name": "\u6f14\u793a\u4eba\u5458Hdd56ba",
        "employee": "HR-EMP-90007",
        "employee_name": "\u6f14\u793a\u4eba\u5458Hdd56ba",
        "roles": ("Employee", "Accounts User", "Department Manager"),
    },
    {
        "user_id": "person047@staff.example.invalid",
        "full_name": "演示人员Heaf0f1",
        "employee": "HR-EMP-90011",
        "employee_name": "演示人员Heaf0f1",
        "roles": ("Employee", "HR User", "Department Manager"),
    },
    {
        "user_id": "person068@staff.example.invalid",
        "full_name": "演示人员H75c4e2",
        "employee": "HR-EMP-90012",
        "employee_name": "演示人员H75c4e2",
        "roles": ("Employee", "Department Manager"),
    },
    {
        "user_id": "person046@staff.example.invalid",
        "legacy_user_id": "person046@business.example.invalid",
        "full_name": "\u6f14\u793a\u4eba\u5458Hf4b020",
        "employee": "HR-EMP-90004",
        "employee_name": "\u6f14\u793a\u4eba\u5458Hf4b020",
        "roles": ("Employee",) + EXECUTIVE_ROLES,
    },
    {
        "user_id": "person060@staff.example.invalid",
        "legacy_user_id": "person058@staff.example.invalid",
        "full_name": "\u6f14\u793a\u4eba\u5458H57af9a",
        "employee": "HR-EMP-90003",
        "employee_name": "\u6f14\u793a\u4eba\u5458H57af9a",
        "roles": ("Employee",) + EXECUTIVE_ROLES,
    },
)


def build_account_plan(specs, *, existing_users, employees, roles_by_user, employee_by_user):
    """Return a deterministic, write-free provisioning plan."""
    existing_users = {str(user).lower() for user in (existing_users or set())}
    result = []
    for source in specs:
        spec = dict(source)
        user_id = str(spec["user_id"]).strip().lower()
        legacy_user_id = str(spec.get("legacy_user_id") or "").strip().lower()
        target_exists = user_id in existing_users
        legacy_exists = bool(
            legacy_user_id
            and legacy_user_id != user_id
            and legacy_user_id in existing_users
        )
        rename_user = legacy_exists and not target_exists
        effective_user_id = legacy_user_id if rename_user else user_id
        employee_id = spec.get("employee")
        employee = (employees or {}).get(employee_id) if employee_id else None
        conflicts = []
        if target_exists and legacy_exists:
            conflicts.append(
                f"both {user_id} and legacy account {legacy_user_id} exist"
            )
        link_employee = False
        if employee_id:
            if not employee:
                conflicts.append(f"{employee_id} does not exist")
            else:
                expected_name = str(spec.get("employee_name") or "").strip()
                actual_name = str(employee.get("employee_name") or "").strip()
                if expected_name and actual_name != expected_name:
                    conflicts.append(f"{employee_id} employee name does not match {expected_name}")
                if str(employee.get("status") or "") != "Active":
                    conflicts.append(f"{employee_id} is not active")
                linked_user = str(employee.get("user_id") or "").strip().lower()
                allowed_linked_users = {user_id}
                if rename_user:
                    allowed_linked_users.add(legacy_user_id)
                if linked_user and linked_user not in allowed_linked_users:
                    conflicts.append(f"{employee_id} is already linked to {linked_user}")
                else:
                    link_employee = linked_user != user_id
            for linked_user_id in dict.fromkeys((user_id, effective_user_id)):
                reverse_link = str(
                    (employee_by_user or {}).get(linked_user_id) or ""
                ).strip()
                if reverse_link and reverse_link != employee_id:
                    conflicts.append(
                        f"{linked_user_id} is already linked to {reverse_link}"
                    )

        current_roles = set((roles_by_user or {}).get(effective_user_id) or set())
        desired_roles = list(dict.fromkeys(spec.get("roles") or ()))
        result.append(
            {
                **spec,
                "user_id": user_id,
                "legacy_user_id": legacy_user_id or None,
                "roles": desired_roles,
                "create_user": not target_exists and not rename_user,
                "rename_user": bool(rename_user),
                "link_employee": bool(link_employee),
                "roles_to_add": [role for role in desired_roles if role not in current_roles],
                "conflicts": conflicts,
            }
        )
    return result


def plan_business_accounts():
    user_ids = list(
        dict.fromkeys(
            user_id
            for row in ACCOUNT_SPECS
            for user_id in (row["user_id"], row.get("legacy_user_id"))
            if user_id
        )
    )
    existing_users = set(
        frappe.get_all("User", filters={"name": ["in", user_ids]}, pluck="name")
    )
    employees = {}
    for spec in ACCOUNT_SPECS:
        employee_id = spec.get("employee")
        if not employee_id:
            continue
        row = frappe.db.get_value(
            "Employee",
            employee_id,
            ["employee_name", "status", "user_id"],
            as_dict=True,
        )
        if row:
            employees[employee_id] = dict(row)
    roles_by_user = {
        user_id: set(frappe.get_roles(user_id))
        for user_id in existing_users
    }
    employee_by_user = {
        user_id: frappe.db.get_value("Employee", {"user_id": user_id}, "name")
        for user_id in user_ids
    }
    return build_account_plan(
        ACCOUNT_SPECS,
        existing_users=existing_users,
        employees=employees,
        roles_by_user=roles_by_user,
        employee_by_user=employee_by_user,
    )


def _create_user(item):
    temporary_password = secrets.token_urlsafe(18)
    user = frappe.new_doc("User")
    user.email = item["user_id"]
    user.first_name = item["full_name"]
    user.enabled = 1
    user.user_type = "System User"
    user.send_welcome_email = 0
    user.default_app = RAYHER_DEFAULT_APP
    user.new_password = temporary_password
    user.flags.ignore_permissions = True
    user.insert(ignore_permissions=True)
    return temporary_password


def ensure_business_accounts(dry_run=True):
    plan = plan_business_accounts()
    result = {
        "dry_run": bool(dry_run),
        "count": len(plan),
        "accounts": plan,
        "created_credentials": [],
    }
    if dry_run:
        return result

    conflicts = [
        f"{item['user_id']}: {message}"
        for item in plan
        for message in item.get("conflicts", [])
    ]
    if conflicts:
        frappe.throw("Account preflight failed: " + "; ".join(conflicts))

    try:
        for item in plan:
            if item.get("rename_user"):
                frappe.rename_doc(
                    "User",
                    item["legacy_user_id"],
                    item["user_id"],
                    force=True,
                )
                user = frappe.get_doc("User", item["user_id"])
                user.email = item["user_id"]
                user.first_name = item["full_name"]
                user.middle_name = None
                user.last_name = None
                user.save(ignore_permissions=True)
            if item["create_user"]:
                password = _create_user(item)
                result["created_credentials"].append(
                    {"user_id": item["user_id"], "temporary_password": password}
                )
            if item.get("link_employee"):
                employee = frappe.get_doc("Employee", item["employee"])
                employee.db_set("user_id", item["user_id"])
            if item.get("roles_to_add"):
                frappe.get_doc("User", item["user_id"]).add_roles(*item["roles_to_add"])
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return result
