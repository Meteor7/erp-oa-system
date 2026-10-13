"""出差申请新增“前台办理”岗位（2026-10-13）：只给前台办理这一个岗位按职务补建一次任命（行政专员，只有唯一在职人员才补）。

审批岗位只认岗位任命（决定 D4），所以新岗位上线时要补一条任命，否则出差申请提交不了。
已有任命（包括停用的）不动；找不到唯一在职人员的站点跳过并打印原因，由系统管理员在岗位任命里设置。
修复（2026-10-13）：原来调 seed_missing_assignments，会把所有没任命的岗位都按职务补上，跳过时也不说原因。
"""
import frappe

from rayher_hr_payroll.oa_role_resolver import seed_missing_assignment


def execute():
    seeded, reason = seed_missing_assignment("front_desk")
    if seeded:
        print("seeded approval role assignment: front_desk")
    else:
        print("front_desk approval role assignment not seeded:", reason)
    frappe.db.commit()
