from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields
from rayher_hr_payroll.rd_cost.document_builder import populate_allocation_document
from rayher_hr_payroll.rd_cost.frappe_adapter import (
    ensure_direct_project_stages,
    get_expense_items,
    get_project_hour_rows,
    get_source_expense_rows,
    project_hours_from_rows,
    total_hours_by_employee,
    personnel_types_by_employee,
)


class RDCostAllocation(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()
        self._check_import_period()
        self._check_period_lock()

    def _check_import_period(self):
        import frappe

        if not self.expense_import or not self.year or not self.month:
            return
        imp = frappe.db.get_value(
            "RD Expense Import", self.expense_import, ["year", "month"], as_dict=True
        )
        if imp and (int(imp.year or 0) != int(self.year) or int(imp.month or 0) != int(self.month)):
            frappe.throw(frappe._("费用导入单的期间与分摊期间不一致，不能分摊。"))

    def before_submit(self):
        import frappe

        # The source import must be submitted (docstatus=1); a draft or cancelled
        # import must never be marked Allocated by on_submit.
        if not self.expense_import:
            frappe.throw(frappe._("未指定费用导入单，不能分摊。"))
        # Lock the import row for this transaction so two concurrent allocation
        # submits for the same import serialize: the second blocks here, then
        # sees the first submitted allocation below and is rejected (closes the
        # check-then-submit race on the one-per-import invariant).
        imp_docstatus = frappe.db.get_value(
            "RD Expense Import", self.expense_import, "docstatus", for_update=True
        )
        if imp_docstatus != 1:
            frappe.throw(frappe._("费用导入单尚未提交或已取消，不能分摊。"))
        # At most one submitted allocation per import: the dashboard number cards
        # sum capitalized/expensed totals across ALL submitted allocations, so a
        # second submitted allocation for the same import would double-count.
        # Locking CURRENT read (for_update), not frappe.db.exists: under MariaDB
        # REPEATABLE READ a plain read uses the txn's snapshot (fixed at the first
        # read, before a concurrent submit committed) and would miss the rival
        # allocation. for_update reads the latest committed row; combined with the
        # import-row lock above it serializes concurrent submits and rejects the 2nd.
        dup = frappe.db.get_value("RD Cost Allocation", {
            "expense_import": self.expense_import,
            "docstatus": 1,
            "name": ["!=", self.name],
        }, "name", for_update=True)
        if dup:
            frappe.throw(frappe._("该费用导入单已有已提交的分摊单（{0}），不能重复分摊。").format(dup))
        # Recompute server-side from the CURRENT import + hour data on submit.
        # read_only on the lines/snapshot tables is only a UI guard; an API
        # client with submit rights could otherwise post forged or stale child
        # rows and lock the import with wrong totals. Recomputing makes a
        # submitted allocation always reflect real source data.
        try:
            self.calculate()
        except ValueError as exc:
            frappe.throw(frappe._("无法计算分摊：{0}").format(str(exc)))
        if not self.get("lines"):
            frappe.throw(frappe._("没有可分摊的数据，不能提交。"))
        # calculate() reset status to "Calculated"; stamp the final workflow state
        # here so the primary submit write already records "Submitted" (the Status
        # list column/filter then distinguishes finalized records from drafts).
        self.status = "Submitted"

    def _check_period_lock(self):
        from rayher_hr_payroll.api._guards import ensure_not_locked

        # Check BOTH new and pre-save period so a locked-period allocation cannot
        # be edited out of the locked period.
        periods = set()
        before = self.get_doc_before_save()
        for src in (self, before):
            if src is not None and src.get("year") and src.get("month"):
                periods.add("%04d%02d" % (int(src.get("year")), int(src.get("month"))))
        for period in periods:
            ensure_not_locked(period, "lock_allocations", "分摊")

    def _normalize_period(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)

    def on_submit(self):
        import frappe

        # Mark the source import Allocated regardless of path (SPA recalc or a
        # direct Desk submit) so it can no longer be silently overwritten.
        if self.expense_import:
            frappe.db.set_value("RD Expense Import", self.expense_import, "status", "Allocated")

    def on_cancel(self):
        import frappe

        self._check_period_lock()
        self.db_set("status", "Cancelled")
        # Re-open the source import only when no other submitted allocation still
        # depends on it (Desk can create several referencing the same import).
        if self.expense_import:
            others = frappe.db.exists("RD Cost Allocation", {
                "expense_import": self.expense_import, "docstatus": 1,
                "name": ["!=", self.name],
            })
            if not others:
                frappe.db.set_value("RD Expense Import", self.expense_import, "status", "Imported")

    def calculate(self):
        expenses = get_expense_items(self.expense_import)
        source_hour_rows = get_project_hour_rows(year=self.year, month=self.month)
        source_expense_rows = get_source_expense_rows(self.expense_import)
        project_hours = project_hours_from_rows(source_hour_rows, year=self.year, month=self.month)
        project_hours = ensure_direct_project_stages(
            project_hours, expenses, year=self.year, month=self.month
        )

        # R&D labour cost: each researcher's submitted Salary Slip gross for the
        # period, allocated across THEIR own project hours and merged with expenses.
        import frappe
        from rayher_hr_payroll.payroll_bridge import period_salaries

        period = "%04d-%02d" % (int(self.year), int(self.month))
        salaries = period_salaries(period)
        total_hours = total_hours_by_employee(year=self.year, month=self.month)
        personnel_types = personnel_types_by_employee()

        skipped = populate_allocation_document(
            self,
            expenses=expenses,
            source_hour_rows=source_hour_rows,
            source_expense_rows=source_expense_rows,
            project_hours=project_hours,
            salaries=salaries,
            total_hours=total_hours,
            personnel_types=personnel_types,
        )
        # Persist an explicit unresolved-skip state so a submitted allocation records the
        # under-counted employees (auditable), not just a transient warning.
        self.labor_skipped = ", ".join(skipped)
        if skipped:
            frappe.msgprint(
                "以下员工本期工时不完整(非全时研发),未纳入研发人工分摊;"
                "请在工时单补录其非研发工时(项目可留空)以提供总工时分母后重新分摊:"
                + ", ".join(skipped)
            )
