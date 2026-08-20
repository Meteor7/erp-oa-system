"""Provision and bind the procurement manager used by OA procurement."""

from rayher_hr_payroll.oa_role_resolver import bootstrap_procurement_manager


def execute():
    bootstrap_procurement_manager()
