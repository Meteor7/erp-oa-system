from rayher_hr_payroll.rd_expense_accounts import DEFAULT_PATHS, ensure_paths


def execute():
    ensure_paths(DEFAULT_PATHS, created_from="系统初始化")
