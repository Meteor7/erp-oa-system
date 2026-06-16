app_name = "rayher_hr_payroll"
app_title = "Rayher HR Payroll"
app_publisher = "Rayher"
app_description = "Rayher HR, R&D timesheet, and R&D cost allocation customizations"
app_email = "admin@example.com"
app_license = "MIT"

required_apps = ["erpnext", "hrms"]
after_install = "rayher_hr_payroll.install.after_install"

doc_events = {
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