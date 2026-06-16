from frappe.model.document import Document

from rayher_hr_payroll.period_controls import normalize_period_fields
from rayher_hr_payroll.rd_cost.document_builder import populate_allocation_document
from rayher_hr_payroll.rd_cost.frappe_adapter import (
    ensure_direct_project_stages,
    get_expense_items,
    get_project_hour_rows,
    get_source_expense_rows,
    project_hours_from_rows,
)


class RDCostAllocation(Document):
    def before_insert(self):
        self._normalize_period()

    def validate(self):
        self._normalize_period()

    def _normalize_period(self):
        import frappe

        normalize_period_fields(self, throw=frappe.throw, translate=frappe._)

    def calculate(self):
        expenses = get_expense_items(self.expense_import)
        source_hour_rows = get_project_hour_rows(year=self.year, month=self.month)
        source_expense_rows = get_source_expense_rows(self.expense_import)
        project_hours = project_hours_from_rows(source_hour_rows, year=self.year, month=self.month)
        project_hours = ensure_direct_project_stages(
            project_hours, expenses, year=self.year, month=self.month
        )

        populate_allocation_document(
            self,
            expenses=expenses,
            source_hour_rows=source_hour_rows,
            source_expense_rows=source_expense_rows,
            project_hours=project_hours,
        )
