from decimal import Decimal

from rayher_hr_payroll.demo import expected_demo_allocation


def test_expected_demo_allocation_matches_acceptance_numbers():
    assert expected_demo_allocation() == {
        "RD-CAP": Decimal("720.00"),
        "RD-EXP": Decimal("480.00"),
        "capitalized_total": Decimal("720.00"),
        "expensed_total": Decimal("480.00"),
    }