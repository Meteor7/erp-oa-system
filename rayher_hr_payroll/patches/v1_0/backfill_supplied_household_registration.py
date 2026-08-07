"""Backfill the household values explicitly supplied by HR."""

from rayher_hr_payroll.household_registration_backfill import (
    backfill_household_registration,
)


def execute():
    return backfill_household_registration(dry_run=False)
