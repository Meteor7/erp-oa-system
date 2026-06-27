import frappe

# Four-tier role model. 员工=Employee, HR=HR User/HR Manager, 财务=Accounts User
# all reuse stock roles; only "Department Manager" is new — it scopes 本部门
# visibility for 工时/看板/审批 (range enforced later via User Permission).
CUSTOM_ROLES = [
    {"role_name": "Department Manager", "desk_access": 1},
]

# 总控 (Owner) account for Serena: ONE Role Profile bundling the stock roles whose
# union grants see-everything + operate-everything, including Employee PII
# (HR Manager), finance (Accounts User), and config (System Manager). Assigned to
# her normal user — NEVER the Administrator account (Frappe anti-pattern).
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
    for r in CUSTOM_ROLES:
        if not frappe.db.exists("Role", r["role_name"]):
            doc = frappe.new_doc("Role")
            doc.update(r)
            doc.insert(ignore_permissions=True)


def _ensure_role_profiles():
    for rp in ROLE_PROFILES:
        name = rp["role_profile"]
        if frappe.db.exists("Role Profile", name):
            doc = frappe.get_doc("Role Profile", name)
            doc.set("roles", [])
        else:
            doc = frappe.new_doc("Role Profile")
            doc.role_profile = name
        for role in rp["roles"]:
            doc.append("roles", {"role": role})
        doc.save(ignore_permissions=True)
