app_name = "rayher_hr_payroll"
app_title = "QIHENG DEMO HR Payroll"
app_publisher = "QIHENG DEMO"
app_description = "QIHENG DEMO HR, R&D timesheet, and R&D cost allocation customizations"
app_email = "admin@example.com"
app_license = "MIT"

# Desk: load the language switcher (navbar dropdown -> i18n.set_language).
app_include_js = "/assets/rayher_hr_payroll/js/language_switcher.js"


add_to_apps_screen = [
    {
        "name": "rayher_hr_payroll",
        "logo": "/assets/rayher_hr_payroll/images/planck-semicon-logo.png",
        "title": "QIHENG DEMO",
        "route": "/planck-semicon",
    }
]

required_apps = ["erpnext", "hrms"]
before_install = "rayher_hr_payroll.install.ensure_link_targets"
before_migrate = "rayher_hr_payroll.install.ensure_link_targets"
after_install = "rayher_hr_payroll.install.after_install"
after_migrate = "rayher_hr_payroll.install.after_migrate"

fixtures = [
    # Ship the DB-stored R&D Query Reports so the SPA's report pages work on a fresh install.
    {"dt": "Report", "filters": [["module", "=", "Rayher HR Payroll"], ["is_standard", "=", "No"]]},
    {"dt": "Workflow", "filters": [["name", "=", "Expense Claim Approval"]]},
    {"dt": "Workspace", "filters": [["name", "in", ["员工工作台", "审批中心"]]]},
]

doc_events = {
    "OA Approval Request": {
        "on_update": "rayher_hr_payroll.api.material_progress.sync_material_progress_for_request",
    },
    "Project": {
        "validate": "rayher_hr_payroll.project_controls.validate_project_stage_lock",
    },
    "Employee": {
        "validate": [
            "rayher_hr_payroll.employee_controls.validate_employee_archive",
            "rayher_hr_payroll.employee_controls.validate_employee_rd_lock",
        ],
        "after_insert": "rayher_hr_payroll.lifecycle_controls.sync_user_for_employee",
        "on_update": "rayher_hr_payroll.lifecycle_controls.sync_user_for_employee",
    },
    "Timesheet": {
        "validate": "rayher_hr_payroll.timesheet_controls.validate_timesheet",
        "before_submit": "rayher_hr_payroll.timesheet_controls.validate_timesheet",
        "on_submit": "rayher_hr_payroll.timesheet_controls.on_submit_timesheet",
        "before_cancel": "rayher_hr_payroll.timesheet_controls.block_locked_timesheet_change",
        "on_trash": "rayher_hr_payroll.timesheet_controls.block_locked_timesheet_change",
    },
    "Compensatory Leave Request": {
        "validate": "rayher_hr_payroll.leave_controls.validate_compensatory_leave_request",
        "on_submit": "rayher_hr_payroll.approval_config.notify_applicant_on_decision",
    },
    "Expense Claim": {
        "on_update": "rayher_hr_payroll.approval_config.notify_applicant_on_decision",
    },
    "Leave Application": {
        "on_update": "rayher_hr_payroll.approval_config.notify_applicant_on_decision",
    },
    "Travel Request": {
        "on_submit": "rayher_hr_payroll.approval_config.notify_applicant_on_decision",
    },
    "Salary Slip": {
        "validate": "rayher_hr_payroll.payroll_bridge.block_locked_salary_slip_change",
        "before_cancel": "rayher_hr_payroll.payroll_bridge.block_locked_salary_slip_change",
        "on_trash": "rayher_hr_payroll.payroll_bridge.block_locked_salary_slip_change",
    },
}

website_route_rules = [
    {"from_route": "/planck-semicon", "to_route": "rayher"},
    {"from_route": "/planck-semicon/<path:app_path>", "to_route": "rayher"},
    {"from_route": "/rayher/<path:app_path>", "to_route": "rayher"},
]

permission_query_conditions = {
    "OA PO Fulfillment Record": "rayher_hr_payroll.procurement_permissions.fulfillment_query",
    "OA Approval Request": "rayher_hr_payroll.oa_access.oa_request_query",
    "OA Business Document": "rayher_hr_payroll.business_documents.business_document_query",
    "Expense Claim": "rayher_hr_payroll.request_visibility.expense_claim_query",
    "Leave Application": "rayher_hr_payroll.request_visibility.leave_application_query",
    "Travel Request": "rayher_hr_payroll.request_visibility.travel_request_query",
    "Compensatory Leave Request": "rayher_hr_payroll.request_visibility.compensatory_leave_query",
    "Salary Slip": "rayher_hr_payroll.request_visibility.salary_slip_query",
    "OA Invoice Import Batch": "rayher_hr_payroll.invoice_ocr.permissions.invoice_batch_query",
    "OA Invoice Record": "rayher_hr_payroll.invoice_ocr.permissions.invoice_record_query",
    "OA Invoice View Log": "rayher_hr_payroll.invoice_ocr.permissions.invoice_view_log_query",
}

has_permission = {
    "OA PO Fulfillment Record": "rayher_hr_payroll.procurement_permissions.fulfillment_has_permission",
    "OA Approval Request": "rayher_hr_payroll.oa_access.oa_request_has_permission",
    "OA Business Document": "rayher_hr_payroll.business_documents.business_document_has_permission",
    "Expense Claim": "rayher_hr_payroll.request_visibility.expense_claim_has_permission",
    "Leave Application": "rayher_hr_payroll.request_visibility.leave_application_has_permission",
    "Travel Request": "rayher_hr_payroll.request_visibility.travel_request_has_permission",
    "Compensatory Leave Request": "rayher_hr_payroll.request_visibility.compensatory_leave_has_permission",
    "Salary Slip": "rayher_hr_payroll.request_visibility.salary_slip_has_permission",
    "OA Invoice Import Batch": "rayher_hr_payroll.invoice_ocr.permissions.invoice_batch_has_permission",
    "OA Invoice Record": "rayher_hr_payroll.invoice_ocr.permissions.invoice_record_has_permission",
    "OA Invoice View Log": "rayher_hr_payroll.invoice_ocr.permissions.invoice_view_log_has_permission",
}

scheduler_events = {
    "daily": [
        "rayher_hr_payroll.maintenance.invoice_ocr_cleanup.cleanup_orphan_invoice_batches",
        "rayher_hr_payroll.organization_master_data.sync_effective_leaver_statuses",
        "rayher_hr_payroll.payment_invoice_reminders.send_payment_invoice_reminders",
        "rayher_hr_payroll.allocation_reminders.remind_finance_manager_to_finalize",
    ],
}

# Synchronize current holders of a position permission template.
doc_events["Role Profile"] = {"on_update": "rayher_hr_payroll.position_handover.on_profile_update"}
