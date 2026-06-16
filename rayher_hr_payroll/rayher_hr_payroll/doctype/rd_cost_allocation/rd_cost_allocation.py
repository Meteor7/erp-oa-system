from frappe.model.document import Document

from rayher_hr_payroll.rd_cost.document_builder import populate_allocation_document
from rayher_hr_payroll.rd_cost.frappe_adapter import (
    ensure_direct_project_stages,
    get_expense_items,
    get_project_hour_rows,
    get_project_hours,
    get_source_expense_rows,
)


class RDCostAllocation(Document):
    def calculate(self):
        expenses = get_expense_items(self.expense_import)
        source_hour_rows = get_project_hour_rows(year=self.year, month=self.month)
        source_expense_rows = get_source_expense_rows(self.expense_import)
        project_hours = get_project_hours(year=self.year, month=self.month)
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
