"""审批岗位改为只认岗位任命（2026-09-29，决定 D4）：给还没有任何任命的岗位按职务补建一次。

已有任命（包括停用的）不动；按职务找不到唯一在职人员的岗位跳过，由系统演示员工170在岗位任命里设置。
"""
import frappe

from rayher_hr_payroll.oa_role_resolver import seed_missing_assignments


def execute():
    seeded = seed_missing_assignments()
    if seeded:
        print("seeded approval role assignments:", ", ".join(seeded))
    frappe.db.commit()
