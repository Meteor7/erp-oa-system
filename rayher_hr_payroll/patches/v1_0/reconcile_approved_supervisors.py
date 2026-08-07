"""Reconcile three approved organization corrections before permission sync."""

from rayher_hr_payroll.approved_supervisor_reconciliation import (
    reconcile_approved_supervisors,
)


def execute():
    return reconcile_approved_supervisors(dry_run=False)
