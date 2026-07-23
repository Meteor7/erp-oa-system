"""Safely derive missing invoice totals from complete money components."""

import json
from decimal import Decimal, InvalidOperation

import frappe

RECORD_DOCTYPE = "OA Invoice Record"


def _has_value(value):
    return value is not None and str(value).strip() != ""


def _derived_value(row):
    try:
        payload = json.loads(row.get("ocr_payload") or "{}")
    except (TypeError, ValueError):
        return None
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict):
        return None
    if _has_value(fields.get("total_amount")):
        return None
    if not _has_value(fields.get("amount_before_tax")) or not _has_value(fields.get("tax_amount")):
        return None
    try:
        return (Decimal(str(row.get("amount_before_tax"))) + Decimal(str(row.get("tax_amount")))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def execute():
    if not frappe.db.table_exists(RECORD_DOCTYPE, cached=False):
        frappe.logger("invoice_ocr").info(
            "derive_missing_invoice_totals skipped: table missing"
        )
        return

    rows = frappe.db.sql(
        """
        SELECT name, amount_before_tax, tax_amount, total_amount, ocr_payload
        FROM `tabOA Invoice Record`
        WHERE amount_before_tax IS NOT NULL
          AND tax_amount IS NOT NULL
          AND (total_amount IS NULL OR total_amount = 0)
        """,
        as_dict=True,
    )
    updated = 0
    for row in rows:
        derived = _derived_value(row)
        if derived is None:
            continue
        current = row.get("total_amount")
        if current not in (None, "", 0, 0.0, Decimal("0")):
            continue
        if Decimal(str(current or 0)).quantize(Decimal("0.01")) == derived:
            continue
        frappe.db.set_value(
            RECORD_DOCTYPE,
            row["name"],
            "total_amount",
            derived,
            update_modified=False,
        )
        updated += 1
    frappe.logger("invoice_ocr").info(
        "derive_missing_invoice_totals scanned=%s updated=%s",
        len(rows),
        updated,
    )