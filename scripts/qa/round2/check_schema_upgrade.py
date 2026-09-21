"""Destructive only to derived test columns; guard rejects business databases."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_transaction_locks import connect
import frappe

connect()
try:
    assert frappe.conf.db_name == "review_audit"
    columns = [("RD Expense Import", "active_period_key"), ("Accommodation Occupancy", "active_employee_key"), ("Accommodation Occupancy", "active_room_key")]
    for table, field in columns:
        frappe.db.sql(f"ALTER TABLE `tab{table}` DROP COLUMN `{field}`")
    from rayher_hr_payroll.patches.v1_0.backfill_active_uniqueness_keys import execute
    execute()
    for table, field in columns:
        assert frappe.db.has_column(table, field)
        assert frappe.db.sql(f"SHOW INDEX FROM `tab{table}` WHERE Column_name = %s AND Non_unique = 0", (field,))
    frappe.db.commit()
    print("UPGRADE_FROM_OLD_SCHEMA_PASSED")
finally:
    frappe.destroy()
