"""出差申请新增“前台办理”岗位（2026-10-13）：给还没有任命的岗位按职务补建一次（行政专员，只有唯一在职人员才补）。

审批岗位只认岗位任命（决定 D4），所以新岗位上线时要补一条任命，否则出差申请提交不了。
已有任命（包括停用的）不动；找不到唯一在职人员的站点跳过，由系统管理员在岗位任命里设置。
"""
import frappe

from rayher_hr_payroll.oa_role_resolver import seed_missing_assignments


def execute():
    seeded = seed_missing_assignments()
    if seeded:
        print("seeded approval role assignments:", ", ".join(seeded))
    frappe.db.commit()
