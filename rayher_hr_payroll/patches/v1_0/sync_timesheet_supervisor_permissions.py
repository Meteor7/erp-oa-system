"""Apply the approved OA supervisor map to R&D timesheet permissions once."""

from rayher_hr_payroll.timesheet_supervisor_sync import (
    synchronize_timesheet_supervisors,
)


def execute():
    return synchronize_timesheet_supervisors(dry_run=False)