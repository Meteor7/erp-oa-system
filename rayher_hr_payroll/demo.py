from __future__ import annotations

from decimal import Decimal
from typing import Any

from rayher_hr_payroll.rd_cost.allocation import allocate_expenses
from rayher_hr_payroll.rd_cost.types import ExpenseItem, ProjectHour

DEMO_PERIOD = "202601"
DEMO_YEAR = 2026
DEMO_MONTH = 1
DEMO_GL_AMOUNT = Decimal("1200.00")


def _get_frappe():
    import frappe  # type: ignore[import-not-found]

    return frappe


def expected_demo_allocation() -> dict[str, Decimal]:
    result = allocate_expenses(
        expenses=[
            ExpenseItem(
                name="DEMO-GL-001",
                amount=DEMO_GL_AMOUNT,
                account_level_3="Power",
                category="direct_input",
            )
        ],
        project_hours=[
            ProjectHour(project="RD-CAP", hours=Decimal("60"), stage="capitalized"),
            ProjectHour(project="RD-EXP", hours=Decimal("40"), stage="expensed"),
        ],
    )
    return {
        "RD-CAP": result.project_amounts["RD-CAP"],
        "RD-EXP": result.project_amounts["RD-EXP"],
        "capitalized_total": result.stage_totals["capitalized"],
        "expensed_total": result.stage_totals["expensed"],
    }


def upsert_doc(doctype: str, name: str, values: dict[str, Any]):
    frappe = _get_frappe()
    if frappe.db.exists(doctype, name):
        doc = frappe.get_doc(doctype, name)
        if getattr(doc, "docstatus", 0) == 0:
            doc.update(values)
            doc.save(ignore_permissions=True)
        return doc

    doc = frappe.get_doc({"doctype": doctype, "name": name, **values})
    doc.insert(ignore_permissions=True, set_name=name)
    return doc


def _company():
    frappe = _get_frappe()
    company = frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw(frappe._("Set a default company before loading QIHENG Demo demo data."))
    return company


def _ensure_department(company: str) -> str:
    frappe = _get_frappe()
    name = frappe.db.get_value("Department", {"department_name": "研发部", "company": company})
    if name:
        return name
    d = frappe.get_doc({"doctype": "Department", "department_name": "研发部", "company": company})
    d.insert(ignore_permissions=True)
    return d.name


def _ensure_master_data(company: str):
    upsert_doc("Gender", "Male", {"gender": "Male"})
    upsert_doc("Activity Type", "Development", {"activity_type": "Development"})
    employee = upsert_doc(
        "Employee",
        "EMP-RD-001",
        {
            "first_name": "Demo",
            "employee_name": "Demo RD Engineer",
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2026-01-01",
            "company": company,
            "department": _ensure_department(company),
            "status": "Active",
            "rd_personnel_type": "全时研发",
            "archive_status": "已归档",
            "id_card_number_cn": "110101199001010031",
            "rd_mock_base": 20000,
            "rd_mock_social": 1650,
            "rd_mock_fund": 2400,
            "rd_mock_tax": 1080,
        },
    )
    upsert_doc(
        "Project",
        "RD-CAP",
        {
            "project_name": "RD-CAP",
            "rd_project_code": "001",
            "rd_project_key": "001 | RD-CAP",
            "status": "Open",
            "company": company,
            "allow_rd_timesheet": 1,
            "project_owner": "Administrator",
            "capitalization_start_date": "2026-01-01",
            "capitalization_end_date": "2026-12-31",
        },
    )
    upsert_doc(
        "Project",
        "RD-EXP",
        {
            "project_name": "RD-EXP",
            "rd_project_code": "002",
            "rd_project_key": "002 | RD-EXP",
            "status": "Open",
            "company": company,
            "allow_rd_timesheet": 1,
            "project_owner": "Administrator",
            "capitalization_start_date": "2025-01-01",
            "capitalization_end_date": "2025-12-31",
        },
    )
    return employee


def _create_timesheet(employee_name: str, company: str):
    frappe = _get_frappe()
    if frappe.db.exists("Timesheet", {"employee": employee_name, "start_date": "2026-01-05", "docstatus": 1}):
        return

    timesheet = frappe.get_doc(
        {
            "doctype": "Timesheet",
            "employee": employee_name,
            "company": company,
            "time_logs": [
                {
                    "activity_type": "Development",
                    "from_time": "2026-01-05 09:00:00",
                    "to_time": "2026-01-05 15:00:00",
                    "hours": 6,
                    "project": "RD-CAP",
                },
                {
                    "activity_type": "Development",
                    "from_time": "2026-01-06 09:00:00",
                    "to_time": "2026-01-06 13:00:00",
                    "hours": 4,
                    "project": "RD-EXP",
                },
            ],
        }
    )
    timesheet.insert(ignore_permissions=True)
    timesheet.submit()


def _create_expense_import():
    frappe = _get_frappe()
    existing = frappe.db.exists("RD Expense Import", {"period": DEMO_PERIOD, "source_file_hash": "demo-202601"})
    if existing:
        return frappe.get_doc("RD Expense Import", existing)

    expense_import = frappe.get_doc(
        {
            "doctype": "RD Expense Import",
            "period": DEMO_PERIOD,
            "year": DEMO_YEAR,
            "month": DEMO_MONTH,
            "source_file_hash": "demo-202601",
            "status": "Imported",
            "items": [
                {
                    "source_row_key": "202601|DEMO-V-001|Power|1",
                    "voucher_no": "DEMO-V-001",
                    "account_level_1": "RD Expense",
                    "account_level_2": "Direct Input",
                    "account_level_3": "Power",
                    "account_level_4": "Electricity",
                    "category": "direct_input",
                    "amount": DEMO_GL_AMOUNT,
                }
            ],
        }
    )
    expense_import.insert(ignore_permissions=True)
    expense_import.submit()
    return expense_import


def _ensure_demo_allowed(force: bool) -> None:
    if force:
        return
    frappe = _get_frappe()
    frappe.throw(frappe._('Pass force=True to create QIHENG Demo demo data on this site.'))


def create_demo_data(force: bool = False):
    _ensure_demo_allowed(force)
    frappe = _get_frappe()
    company = _company()
    employee = _ensure_master_data(company)
    _create_timesheet(employee.name, company)
    expense_import = _create_expense_import()

    # Idempotent under re-run: one submitted allocation per import is enforced by
    # the controller, so reuse an existing submitted demo allocation instead of
    # creating a second one (which would be rejected).
    existing_alloc = frappe.db.exists(
        "RD Cost Allocation", {"expense_import": expense_import.name, "docstatus": 1}
    )
    if existing_alloc:
        return existing_alloc

    allocation = frappe.get_doc(
        {
            "doctype": "RD Cost Allocation",
            "period": DEMO_PERIOD,
            "year": DEMO_YEAR,
            "month": DEMO_MONTH,
            "expense_import": expense_import.name,
            "allocation_basis": "rd_project_hours",
            "calculation_version": "202601-demo-v1",
            "scope": "all",
            "status": "Draft",
        }
    )
    allocation.calculate()
    allocation.insert(ignore_permissions=True)
    allocation.submit()
    return allocation.name