"""Apply only position resolution changes to older server baselines."""
from pathlib import Path
import re


def adapt_common(name, source):
    p = Path(name)
    s = source
    def add_import(text):
     nonlocal s
     if "from __future__ import annotations" in s:
      s=s.replace("from __future__ import annotations","from __future__ import annotations\n"+text,1)
     else:s=text+"\n"+s
    if name.endswith("oa_role_resolver.py"):
     s=s.replace('    "pmc":', '    "it_asset_owner": {"label": "IT负责人", "designation": "网络工程师"},\n    "pmc":',1)
    elif name.endswith("oa_approval.py"):
     add_import("from rayher_hr_payroll.oa_role_resolver import resolve_role")
     start=s.index("def _fallback_roles():");end=s.index("\ndef _role_label(",start)
     s=s[:start]+'''class _RoleSnapshots(dict):
        def __missing__(self, key):
            value = resolve_role(key)
            self[key] = value
            return value
    
    
    def _roles(roles=None):
        return _RoleSnapshots({key: dict(value) for key, value in (roles or {}).items() if value})
    
    '''+s[end:]
     s=s.replace("top_values = set(TOP_SUPERVISORS)","top_values = set()")
     s=s.replace('_append_unique_approval(steps, ASSET_APPROVAL_LABEL_PREFIX + IT_APPROVER_NAME, IT_APPROVER_USER)', 'it = snapshots["it_asset_owner"]\n        _append_unique_approval(steps, _role_label(it, with_name=True), _role_user(it, "IT负责人"))')
    elif name.endswith("api/procurement_chain.py"):
     s=s.replace("from rayher_hr_payroll.identity_accounts import account_user","from rayher_hr_payroll.position_access import position_user, position_users")
     s=re.sub(r"^from rayher_hr_payroll.oa_approval import PMC_APPROVER_USER.*\n","",s,flags=re.M)
     s=re.sub(r"^(QINGBO_USER|PMC_USERS|PURCHASE_USERS|PRODUCTION_RECEIPT_USERS|CHAIN_USERS) = .*\n","",s,flags=re.M)
     s=s.replace("account_user(QINGBO_USER)",'position_user("vice_manager")')
     s=s.replace("PMC_APPROVER_USER.lower()", 'position_user("pmc")').replace("PROCUREMENT_MANAGER_USER.lower()", 'position_user("procurement_manager")')
     for token,expr in {"PMC_USERS":'position_users("pmc")',"PURCHASE_USERS":'position_users("procurement_manager")',"PRODUCTION_RECEIPT_USERS":'position_users("production_asset_owner")',"CHAIN_USERS":'position_users("pmc", "procurement_manager", "vice_manager")'}.items():
      s=re.sub(r"\b"+token+r"\b",expr,s)
     s=s.replace("演示员工37","副总经理").replace("生产主管演示员工241","生产主管")
    elif name.endswith("api/material_progress.py"):
     s=s.replace("from rayher_hr_payroll.identity_accounts import account_user","from rayher_hr_payroll.position_access import position_user, position_users")
     s=s.replace("from rayher_hr_payroll.oa_approval import PMC_APPROVER_USER, REQUEST_PROCUREMENT, PROCUREMENT_MANAGER_USER","from rayher_hr_payroll.oa_approval import REQUEST_PROCUREMENT")
     s=re.sub(r"^BOARD_USERS = .*\n","",s,flags=re.M)
     s=s.replace("user in BOARD_USERS",'user in position_users("pmc", "procurement_manager", "vice_manager")')
     s=s.replace('PMC_APPROVER_USER, PROCUREMENT_MANAGER_USER, account_user("person046@staff.example.invalid")','position_user("pmc"), position_user("procurement_manager"), position_user("vice_manager")')
     s=s.replace("演示员工37","副总经理")
    elif name.endswith("api/oa_entry.py"):
     add_import("from rayher_hr_payroll.position_access import position_users, current_supervisors, executive_names")
     s=re.sub(r"PROCUREMENT_PRICE_USERS = \{.*?\}\n","",s,flags=re.S,count=1)
     s=s.replace("candidate in PROCUREMENT_PRICE_USERS",'candidate in position_users("pmc", "procurement_manager", "vice_manager")')
     s=s.replace('        elif asset_category == PRODUCTION_ASSET:', '        elif asset_category == IT_ASSET:\n            keys.append("it_asset_owner")\n        elif asset_category == PRODUCTION_ASSET:',1)
     s=re.sub(r'user in \{\n\s*"person033@staff.example.invalid".*?\}', 'user in position_users("procurement_manager", "vice_manager", "general_manager")',s,flags=re.S,count=1)
     s=s.replace("    DIRECT_SUPERVISOR_BY_EMPLOYEE,\n","").replace("    TOP_EXECUTIVES,\n","")
     s=s.replace("DIRECT_SUPERVISOR_BY_EMPLOYEE","current_supervisors()").replace("TOP_EXECUTIVES","executive_names()")
    elif name.endswith("api/dashboard_entry.py"):
     add_import("from rayher_hr_payroll.position_access import position_users")
     s=re.sub(r'user in \{\n\s*"person033@staff.example.invalid".*?\}', 'user in position_users("procurement_manager", "vice_manager", "general_manager")',s,flags=re.S,count=1)
    elif name.endswith("www/rayher.py"):
     add_import("from rayher_hr_payroll.position_access import position_flags")
     s=s.replace('"oa_access": boot_access_flags(frappe.session.user),','"oa_access": boot_access_flags(frappe.session.user),\n        "position_access": position_flags(frappe.session.user),')
    elif name.endswith("oa_organization.py"):
     add_import("from rayher_hr_payroll.position_access import current_supervisors, executive_names")
     s=s.replace("supervisors = mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE","supervisors = current_supervisors() if mapping is None else mapping")
     s=s.replace("in TOP_EXECUTIVES","in executive_names()")
     s=s.replace("演示员工37或演示员工28","副总经理或总经理")
    elif name.endswith("frontend/src/lib/access.js"):
     s=re.sub(r"const PROCUREMENT_PRICE_USERS = new Set\(\[.*?\]\);\n","",s,flags=re.S,count=1)
     s=re.sub(r"const PRODUCTION_RECEIPT_USERS = .*;\n","",s,count=1)
     s=re.sub(r"const MATERIAL_PROGRESS_USERS = .*;\n","",s,count=1)
     helper='''function holdsPosition(...keys) {
      const positions = (typeof window !== 'undefined' && window.position_access) || {};
      return keys.some(key => positions[key] === true);
    }
    
    '''
     s=s.replace("function currentLogin() {",helper+"function currentLogin() {",1)
     s=s.replace("PROCUREMENT_PRICE_USERS.has(currentLogin())","holdsPosition('pmc', 'procurement_manager', 'vice_manager')")
     s=s.replace("PRODUCTION_RECEIPT_USERS.has(currentLogin())","holdsPosition('production_asset_owner')")
     s=s.replace("currentLogin() === 'person076@staff.example.invalid'","holdsPosition('pmc')")
     s=s.replace("['person033@staff.example.invalid', 'admin@staff.example.invalid', 'administrator'].includes(currentLogin())","holdsPosition('procurement_manager')")
     s=s.replace("MATERIAL_PROGRESS_USERS.has(user)","holdsPosition('pmc', 'procurement_manager', 'vice_manager')")
    else:raise ValueError(name)
    if p.suffix==".py":compile(s,str(p),"exec")
    
    return s


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected source shape: " + old[:70])
    return source.replace(old, new, 1)


def adapt_legacy_approval(source):
    source = once(source, 'def _position_step(role_key, mode="approve", prefix=""):',
                  'def _position_step(role_key, mode="approve", prefix="", name_only=False):')
    source = once(source, '    label = prefix + snapshot["role_label"]',
                  '    label = prefix + (snapshot["employee_name"] if name_only else snapshot["role_label"])')
    source = once(source, '    if snapshot.get("employee_name"):',
                  '    if snapshot.get("employee_name") and not name_only:')
    source = once(source, '_step(VICE_MANAGER_NAME, approvers=[VICE_MANAGER_USER])',
                  '_position_step("vice_manager", name_only=True)')
    source = once(source, '_step(GENERAL_MANAGER_NAME, approvers=[GENERAL_MANAGER_USER])',
                  '_position_step("general_manager", name_only=True)')
    source = source.replace('_step(GENERAL_MANAGER_LABEL, approvers=[GENERAL_MANAGER_USER])',
                            '_position_step("general_manager")')
    source = source.replace('_step(VICE_MANAGER_LABEL, approvers=[VICE_MANAGER_USER])',
                            '_position_step("vice_manager")')
    source = once(source, '_step(FINANCE_MANAGER_LABEL, approvers=[FINANCE_MANAGER_USER])',
                  '_position_step("finance_manager")')
    source = once(source, '''            _step(
                ASSET_APPROVAL_LABEL_PREFIX + IT_APPROVER_NAME,
                approvers=[IT_APPROVER_USER],
            )''', '''            _position_step("it_asset_owner", prefix=ASSET_APPROVAL_LABEL_PREFIX)''')
    source = once(source, 'VICE_MANAGER_LABEL + "、" + GENERAL_MANAGER_LABEL,',
                  'resolve_role("vice_manager")["role_label"] + "、" + resolve_role("general_manager")["role_label"],')
    source = once(source, 'approvers=[VICE_MANAGER_USER, GENERAL_MANAGER_USER],',
                  'approvers=[resolve_role("vice_manager")["user"], resolve_role("general_manager")["user"]],')
    source = once(source, 'name in TOP_SUPERVISORS',
                  'name in {value for key in ("vice_manager", "general_manager") for value in (resolve_role(key)["employee_name"], resolve_role(key)["user"])}')
    compile(source, "legacy_oa_approval.py", "exec")
    return source
