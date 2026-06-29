_RD_MOCK_FIELDS = (("rd_mock_base", "应发工资"), ("rd_mock_social", "社保"),
                   ("rd_mock_fund", "公积金"), ("rd_mock_tax", "个税"))


def _negative_mock_fields(doc):
    """Pure: labels of mock-salary fields that are negative (empty list if OK)."""
    return [label for f, label in _RD_MOCK_FIELDS if (doc.get(f) or 0) < 0]


def _archive_problems(doc):
    # Salary is no longer an archive prerequisite: real payroll (Salary Slip) is the
    # source of truth (P4), so we do NOT require rd_mock_base>0 to archive.
    """Pure: completeness problems for an 已归档 employee. Empty list when the
    employee is not archived or all required info is present."""
    if (doc.get("archive_status") or "") != "已归档":
        return []
    problems = []
    if len((doc.get("id_card_number_cn") or "").strip()) < 15:
        problems.append("身份证号需≥15位")
    if not doc.get("date_of_joining"):
        problems.append("入职日期必填")
    if not (doc.get("department") or "").strip():
        problems.append("部门必填")
    return problems


def _employee_has_rd_hours(employee, ym):
    """True if the employee has SUBMITTED timesheet hours in period ym (YYYYMM)."""
    import frappe

    return bool(frappe.db.sql(
        """select 1 from `tabTimesheet Detail` tsd
           inner join `tabTimesheet` ts on ts.name = tsd.parent and ts.docstatus = 1
           inner join `tabProject` p on p.name = tsd.project
           where ts.employee = %(e)s and date_format(tsd.from_time, '%%Y%%m') = %(ym)s
             and coalesce(p.allow_rd_timesheet, 0) = 1
           limit 1""",
        {"e": employee, "ym": ym},
    ))


def validate_employee_rd_lock(doc, method=None):
    """Block changing an employee's rd_personnel_type when they logged hours in a
    stage-locked period: rd_personnel_type gates whether those hours enter the
    period's R&D allocation (frappe_adapter.get_project_hour_rows), so changing it
    would alter a locked period's allocation inputs -- the symmetric guard to the
    project allow_rd_timesheet lock in project_controls."""
    import frappe

    if doc.is_new() or not doc.has_value_changed("rd_personnel_type"):
        return
    # rd_personnel_type enters the allocation ONLY as a membership filter
    # (in RD_PERSONNEL_TYPES); a change only alters a locked period's inputs if it
    # crosses the in-set<->out-set boundary. Same-side changes (e.g. 全时研发 ->
    # 研发辅助, or 非研发 -> "") cannot change allocation membership, so skip them.
    rd_set = {"全时研发", "非全时研发", "研发辅助"}
    before = doc.get_doc_before_save()
    old_in = (before.get("rd_personnel_type") if before else None) in rd_set
    new_in = (doc.get("rd_personnel_type") or None) in rd_set
    if old_in == new_in:
        return
    blocked = []
    for lk in frappe.get_all(
        "RD Period Lock",
        filters={"docstatus": 1, "lock_project_stage": 1},
        fields=["period"],
        limit_page_length=0,
    ):
        ym = "".join(c for c in str(lk.period or "") if c.isdigit())[:6]
        if len(ym) == 6 and _employee_has_rd_hours(doc.name, ym):
            blocked.append("%s-%s" % (ym[:4], ym[4:]))
    if blocked:
        frappe.throw(
            frappe._("会改变已锁定期间（{0}）的研发分摊输入，不允许修改该员工的研发人员类型。").format(
                ", ".join(sorted(set(blocked)))
            )
        )


def validate_employee_archive(doc, method=None):
    """When an employee is marked 已归档, enforce information completeness
    (mirrors the HTML isComplete rule)."""
    import frappe

    for label in _negative_mock_fields(doc):
        frappe.throw(frappe._("{0}不能为负").format(frappe._(label)))
    problems = _archive_problems(doc)
    if problems:
        frappe.throw(frappe._("无法归档，信息不完整：") + "；".join(frappe._(p) for p in problems))
