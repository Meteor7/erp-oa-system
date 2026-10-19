"""Current position holders for routing and access, never personal account allowlists."""
from rayher_hr_payroll.oa_role_resolver import (
    ROLE_SPECS, ApprovalRoleResolutionError, resolve_role,
)


def position_user(key):
    return resolve_role(key)["user"].strip().lower()


def position_users(*keys):
    users = set()
    for key in keys:
        try:
            users.add(position_user(key))
        except ApprovalRoleResolutionError:
            # An unresolved position grants no access.
            continue
    return users


def position_flags(user):
    candidate = str(user or "").strip().lower()
    return {key: candidate in position_users(key) for key in ROLE_SPECS}


class SupervisorMap(dict):
    """在职员工姓名 -> 主管姓名。在职同名的人单独记下，只有真的查到这个名字时才报错。"""

    def __init__(self, data, ambiguous):
        super().__init__(data)
        self.ambiguous = frozenset(ambiguous)

    def _refuse(self, key):
        raise ApprovalRoleResolutionError(
            f"有多名在职员工都叫「{key}」，无法确定主管关系；请人事在员工信息里给姓名加上区分，例如「{key}(研发)」"
        )

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self.ambiguous

    def __getitem__(self, key):
        if key in self.ambiguous:
            self._refuse(key)
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        if key in self.ambiguous:
            self._refuse(key)
        return dict.get(self, key, default)


def current_supervisors():
    """修复（2026-09-29，审查 X3-1，决定 D1）：原来把离职员工也算进来，任何两个人同名就对所有人抛错，
    全公司的请假、报销、采购提交都失败。现在只按在职员工建表；在职同名只影响查到这个名字的人。"""
    import frappe
    rows = frappe.get_all("Employee", fields=["name", "employee_name", "reports_to", "status"],
                          limit_page_length=0)
    names = {row.name: row.employee_name for row in rows}
    result, ambiguous = {}, set()
    for row in rows:
        if (getattr(row, "status", None) or "Active") != "Active":
            continue
        if row.employee_name in result or row.employee_name in ambiguous:
            ambiguous.add(row.employee_name)
            result.pop(row.employee_name, None)
            continue
        result[row.employee_name] = names.get(row.reports_to, "")
    return SupervisorMap(result, ambiguous)


def executive_names():
    """副总经理、总经理的姓名，用来判断某人是不是高管。

    修复（2026-09-29，审查 #10）：原来任一岗位空缺或绑定的人已离职就直接抛错，所有请假、加班、
    调休和其他申请的提交都失败（页面上是 500）。空缺的岗位没有人，自然谁也不是它；需要这个岗位
    审批时，路线生成那一步会给出明确的提示。
    """
    names = set()
    for key in ("vice_manager", "general_manager"):
        try:
            names.add(resolve_role(key)["employee_name"])
        except ApprovalRoleResolutionError:
            continue
    return names
