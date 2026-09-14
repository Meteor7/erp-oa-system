"""Move accommodation occupancy names off the shared format counter."""

import frappe

DOCTYPE = "Accommodation Occupancy"
SERIES = "OCC-"


def execute():
    # Seed before switching the DocType. Never rewind an existing dedicated series,
    # and never touch the empty-prefix counter used by other format autonames.
    if frappe.db.table_exists(DOCTYPE):
        maximum = frappe.db.sql(
            """SELECT COALESCE(MAX(CAST(SUBSTRING(name, 5) AS UNSIGNED)), 0)
            FROM `tabAccommodation Occupancy`
            WHERE name REGEXP '^OCC-[0-9]+$'"""
        )[0][0]
        frappe.db.sql(
            """INSERT INTO `tabSeries` (name, current) VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE current = GREATEST(COALESCE(current, 0), VALUES(current))""",
            (SERIES, int(maximum)),
        )
    frappe.reload_doc("rayher_hr_payroll", "doctype", "accommodation_occupancy")
