import frappe

# Four-tier role model. 员工=Employee, HR=HR User/HR Manager, 财务=Accounts User
# all reuse stock roles; only "Department Manager" is new — it gates the OA *approval*
# layer: the Expense Claim workflow manager stage and per-document request visibility
# (员工只见自己 / 经理只见指派给自己的, in request_visibility). The R&D 工时/看板 APIs stay
# scoped to the finance/R&D-manage roles (RD_MANAGE_ROLES), not Department Manager.
CUSTOM_ROLES = [
    {"role_name": "Department Manager", "desk_access": 1},
    {"role_name": "Project Owner", "desk_access": 1},
    {"role_name": "All Project Access", "desk_access": 1},
]

# 总控 (Owner) account for Serena: ONE Role Profile bundling the stock roles whose
# union grants see-everything + operate-everything, including Employee PII
# (HR Manager), finance (Accounts User), and config (System Manager). The profile
# is created here; assigning it to her user is a manual one-time step (not done
# here) — never use the Administrator account (Frappe anti-pattern).
ROLE_PROFILES = [
    {
        "role_profile": "总控 Owner",
        "roles": ["System Manager", "HR Manager", "Accounts User", "Department Manager"],
    },
]


def ensure_access_control():
    _ensure_custom_roles()
    _ensure_role_profiles()


def _ensure_custom_roles():
    # Declarative config-as-code: create the role if missing, and reconcile its
    # declared flags (e.g. desk_access) if it already exists with stale values.
    for r in CUSTOM_ROLES:
        name = r["role_name"]
        if frappe.db.exists("Role", name):
            doc = frappe.get_doc("Role", name)
            changed = False
            for field, value in r.items():
                if field == "role_name":
                    continue
                if doc.get(field) != value:
                    doc.set(field, value)
                    changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            doc = frappe.new_doc("Role")
            doc.update(r)
            doc.insert(ignore_permissions=True)


def _ensure_role_profiles():
    # after_migrate == after_install, so this runs on EVERY migrate. Saving a
    # Role Profile triggers RoleProfile.on_update -> update_all_users, which resets
    # every assigned user's roles to exactly the profile's roles. So only rebuild
    # and save when the role set actually differs — otherwise a migrate would
    # silently strip any extra role an admin granted Serena's account.
    for rp in ROLE_PROFILES:
        name = rp["role_profile"]
        desired = list(rp["roles"])
        if frappe.db.exists("Role Profile", name):
            doc = frappe.get_doc("Role Profile", name)
            if {d.role for d in doc.roles} == set(desired):
                continue
            doc.set("roles", [])
        else:
            doc = frappe.new_doc("Role Profile")
            doc.role_profile = name
        for role in desired:
            doc.append("roles", {"role": role})
        doc.save(ignore_permissions=True)
