app_name = "rayher_hr_payroll"
app_title = "Rayher HR Payroll"
app_publisher = "Rayher"
app_description = "Rayher HR, R&D timesheet, and R&D cost allocation customizations"
app_email = "admin@example.com"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]
before_install = "rayher_hr_payroll.install.before_install"
after_install = "rayher_hr_payroll.install.after_install"
after_migrate = "rayher_hr_payroll.install.after_install"

fixtures = [
    # Ship the DB-stored R&D Query Reports so the SPA's report pages work on a fresh install.
    {"dt": "Report", "filters": [["module", "=", "Rayher HR Payroll"], ["is_standard", "=", "No"]]},
    {"dt": "Workflow", "filters": [["name", "=", "Expense Claim Approval"]]},
    {"dt": "Workspace", "filters": [["name", "in", ["员工工作台", "审批中心"]]]},
]

doc_events = {
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
    },
}

website_route_rules = [
    {"from_route": "/rayher/<path:app_path>", "to_route": "rayher"},
]
