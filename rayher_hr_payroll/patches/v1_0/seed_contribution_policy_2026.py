"""社保公积金政策改成可配置（2026-10-14）：把原来写死在代码里的“示例总部-2026”写进“社保公积金政策”。

已经有 Rayher 2026 的记录就不动；没有 Rayher 这家公司的站点跳过。示例研发中心等其他公司的政策由人事在“社保公积金政策”里新建。
"""
import frappe

from rayher_hr_payroll.hr_contributions import BUILTIN_POLICIES, POLICY_RATE_FIELDS


def execute():
    frappe.reload_doc("rayher_hr_payroll", "doctype", "contribution_policy")
    for (company, year), policy in BUILTIN_POLICIES.items():
        if not frappe.db.exists("Company", company):
            print("contribution policy not seeded, no company:", company)
            continue
        if frappe.db.exists("Contribution Policy", {"company": company, "year": year}):
            continue
        doc = frappe.new_doc("Contribution Policy")
        doc.update({"company": company, "year": year, "version": policy["version"], "enabled": 1,
                    **{key: float(policy[key]) for key in POLICY_RATE_FIELDS},
                    "remark": "原来写在代码里的政策，2026-10-14 迁到这里"})
        doc.insert(ignore_permissions=True)
        print("seeded contribution policy:", doc.name)
    frappe.db.commit()
