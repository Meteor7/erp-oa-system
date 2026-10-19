"""Daily employee-status job.

修复（2026-09-29，模块 7，决定 D5）：删除按 2026-08-22 花名册写死的组织同步
sync_organization_master_data（新建演示员工203、删除演示员工182、按姓名改部门和汇报关系、停用旧部门）。
它只能手工跑，但一跑就会把人事之后在系统里做的调整改回旧表，还会删员工档案。
组织关系以系统里人事维护的数据为准；这里只保留每天的演示员工166状态任务。
"""

from __future__ import annotations


def sync_effective_leaver_statuses(today=None):
    """Apply the dates maintained by HR, preserving rehires and current assignments.

    修复（2026-09-29，模块 7）：
    - 决定 D3：演示员工166日当天还算在职（本人还能交工时、报销、办交接），演示员工166日的第二天起才标演示员工166、停用账号。
    - 复职：演示员工166日期早于入职日期的是上次演示员工166留下的旧日期，不再把人标回演示员工166。
    - 逐人处理：原来一人出错（例如主管名下还有在职下属，ERPNext 不让标演示员工166）整批回滚，
      当天所有人都没处理，以后每天重复失败。现在出错的人记日志，其他人照常处理。
    """
    import frappe

    current_date = str(today or frappe.utils.today())
    rows = frappe.get_all(
        "Employee", filters={"status": "Active", "relieving_date": ["<", current_date]},
        fields=["name"], order_by="name", limit_page_length=0,
    )
    updates = []
    for row in rows:
        savepoint = "leaver_sync"
        frappe.db.savepoint(savepoint)
        try:
            doc = frappe.get_doc("Employee", row.name, for_update=True)
            relieving = str(getattr(doc, "relieving_date", "") or "")
            joining = str(getattr(doc, "date_of_joining", "") or "")
            if doc.status != "Active" or not relieving or relieving >= current_date:
                continue
            if joining and joining > relieving:
                continue
            positions = frappe.get_all(
                "OA Approval Role Assignment", filters={"employee": row.name, "enabled": 1}, pluck="role_label",
            )
            if positions:
                # 修复（2026-09-29，模块 7）：岗位任职人演示员工166当晚账号一停用，所有需要这个岗位审批的单子
                # 都提交不了。先不标演示员工166，记日志提醒人事去岗位任命里交接；交接后下次任务自动处理。
                raise ValueError(f"仍担任岗位 {'、'.join(positions)}，请先完成岗位交接")
            doc.status = "Left"
            # Use save so the linked login is disabled by the normal lifecycle hook.
            doc.save(ignore_permissions=True)
            updates.append({"employee_name": doc.employee_name, "status": doc.status})
        except Exception as exc:  # noqa: BLE001 - one employee must not stop the others
            frappe.db.rollback(save_point=savepoint)
            frappe.log_error(title="演示员工166状态同步失败", message=f"{row.name}: {exc}")
    return updates
