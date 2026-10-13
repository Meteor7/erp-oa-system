"""总经理、副总经理只读查看人事页面（决定 2026-10-13）。

数据看板上总经理、副总经理看得到的人事数字（在职、到期、考勤、薪酬、宿舍……），点进去的页面也要能打开：
和人事一样能看到每个人、每个部门，但只能看，不能改。按岗位任命判断（position_access），不看角色名，
和看板的可见性（dashboard/people.py 的 LEADER_POSITIONS）、考勤中心的范围（attendance_scope）用同一个规则。

只给“读”的接口用 require_hr_read；写接口仍然只认人事角色（require_rd_access），一个都不放开。
"""
from __future__ import annotations

import frappe

LEADER_POSITIONS = ("vice_manager", "general_manager")


def _user(user=None):
    return str(user or getattr(getattr(frappe, "session", None), "user", "") or "").strip().lower()


def is_hr_leader(user=None):
    """当前（或给定）账号是不是总经理 / 副总经理岗位的人。岗位查不出来（没任命、查询出错）就当不是——只会少放行，不会多放行。"""
    current = _user(user)
    if not current or current == "guest":
        return False
    try:
        from rayher_hr_payroll.position_access import position_users

        return current in position_users(*LEADER_POSITIONS)
    except Exception:
        return False


def require_hr_read(roles, require_roles=None):
    """读接口的权限：总经理 / 副总经理直接放行；其他人按原来的角色检查（require_roles，默认 _guards.require_rd_access）。"""
    if is_hr_leader():
        return
    if require_roles is None:
        from rayher_hr_payroll.api._guards import require_rd_access as require_roles
    require_roles(roles)
