"""Deprecated entry point for procurement acceptance data.

Use ``rayher_hr_payroll.maintenance.procurement_test_data`` so every record
starts at a real OA and retains its PR/source relationships.
"""
from rayher_hr_payroll.maintenance.procurement_test_data import cleanup, seed


def run():
    return seed()


if __name__ == "__main__":
    print(run())
