"""采购申请列表「我负责的项目」页签：项目负责人 = 我、别人提的、已提交的申请（只读）。

原来页签从 list_requests(view=all) 最近 200 张里再筛，单子多了会比看板「我负责的项目」上的数少（审查 #79-5）。
现在和看板同一份取数：dashboard/projects._load_requests（按项目负责人直接查，不限条数，
每行用列表接口同一个 oa_entry._summarize_doc 整理，价格、供应商看不看得到也一样），
再去掉草稿和自己提的（同 projects._mine / procurementView.ownedRows）。
"""
from types import SimpleNamespace

import frappe

from rayher_hr_payroll.list_read_scope import read_scope
from rayher_hr_payroll.oa_feature_gate import require_request_type_access


@frappe.whitelist(methods=["GET"])
@read_scope
def list_owned_requests(request_type="采购申请"):
    from rayher_hr_payroll.dashboard import projects

    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("请先登录。", frappe.PermissionError)
    request_type = str(request_type or "").strip()
    if request_type not in projects.REQUEST_TYPES:
        frappe.throw("不支持的申请类型。")
    require_request_type_access(request_type)
    employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name") or ""
    ctx = SimpleNamespace(user=user, employee=employee)
    return [row for row in projects._load_requests(ctx, (request_type,))
            if row.get("project_owner") == user and row.get("workflow_status") != "草稿" and not projects._is_own(ctx, row)]
