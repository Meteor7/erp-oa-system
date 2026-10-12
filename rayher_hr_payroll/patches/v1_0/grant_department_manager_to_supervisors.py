"""有在职直接下属的人都补上“部门主管”角色（决定 2026-10-12：部门主管以有没有下属为准）。

只补不删：已有的角色保留；以后员工档案里新设“汇报给”时由 team_scope.ensure_manager_role 补。
"""
from rayher_hr_payroll.team_scope import grant_manager_role_to_all_supervisors


def execute():
    grant_manager_role_to_all_supervisors()
