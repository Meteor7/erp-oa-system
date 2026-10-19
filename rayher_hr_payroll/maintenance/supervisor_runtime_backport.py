"""Minimal legacy server adapters for Employee-based supervisor resolution."""


def adapt_organization(source):
    source = "from rayher_hr_payroll.position_access import current_supervisors, executive_names\n" + source
    old = "supervisors = mapping or DIRECT_SUPERVISOR_BY_EMPLOYEE"
    if old not in source:
        raise ValueError("Unexpected organization baseline")
    source = source.replace(old, "supervisors = current_supervisors() if mapping is None else mapping")
    source = source.replace("in TOP_EXECUTIVES", "in executive_names()")
    source = source.replace("演示员工37或演示员工28", "演示员工113经理或总经理")
    compile(source, "oa_organization.py", "exec")
    return source


def adapt_api(source):
    old = "    if employee_name in DIRECT_SUPERVISOR_BY_EMPLOYEE:"
    if source.count(old) != 1:
        raise ValueError("Unexpected supervisor API baseline")
    source = "from rayher_hr_payroll.position_access import current_supervisors\n" + source
    source = source.replace("    DIRECT_SUPERVISOR_BY_EMPLOYEE,\n", "")
    source = source.replace(old, "    if employee_name in current_supervisors():")
    compile(source, "oa_entry.py", "exec")
    return source
