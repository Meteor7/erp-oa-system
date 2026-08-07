"""Idempotent backfill for household values supplied by HR screenshots.

The supplied values are personal data and are not kept in the repository.
Put them in the site's private folder as ``household_registration_backfill.json``,
a JSON object mapping employee name to household registration. Without that
file the backfill has nothing to apply.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path


DATA_FILE = "household_registration_backfill.json"


def load_expected(path=None):
    if path is None:
        import frappe

        path = frappe.get_site_path("private", DATA_FILE)
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(DATA_FILE + " must contain a JSON object")
    expected = {}
    for name, household in data.items():
        name, household = str(name or "").strip(), str(household or "").strip()
        if name and household:
            expected[name] = household
    return expected


def _text(value):
    return str(value or "").strip()


def build_backfill_plan(
    employees: Iterable[Mapping],
    expected: Mapping[str, str] | None = None,
):
    expected = dict(load_expected() if expected is None else expected)
    by_name = {}
    duplicates = set()
    for source in employees or []:
        row = dict(source)
        name = _text(row.get("employee_name"))
        if not name:
            continue
        if name in by_name:
            duplicates.add(name)
        by_name[name] = row

    updates = []
    unchanged = []
    conflicts = []
    for employee_name, household in expected.items():
        row = by_name.get(employee_name)
        if employee_name in duplicates:
            conflicts.append({"type": "employee_not_unique", "employee_name": employee_name})
        elif not row:
            conflicts.append({"type": "employee_not_found", "employee_name": employee_name})
        else:
            current = _text(row.get("household_registration"))
            item = {
                "employee": row.get("name"),
                "employee_name": employee_name,
                "household_registration": household,
            }
            if not current:
                updates.append(item)
            elif current == household:
                unchanged.append(item)
            else:
                conflicts.append(
                    {
                        **item,
                        "type": "unexpected_existing_value",
                        "current": current,
                    }
                )
    return {"updates": updates, "unchanged": unchanged, "conflicts": conflicts}


def backfill_household_registration(*, dry_run=False):
    import frappe

    rows = frappe.get_all(
        "Employee",
        fields=["name", "employee_name", "household_registration"],
        order_by="employee_name, name",
    )
    plan = build_backfill_plan(rows)
    plan["dry_run"] = bool(dry_run)
    plan["applied"] = 0
    if plan["conflicts"]:
        frappe.throw(
            "户口资料补录遇到未预期数据，未写入任何记录："
            + json.dumps(plan["conflicts"], ensure_ascii=False, sort_keys=True)
        )
    if dry_run:
        return plan
    for item in plan["updates"]:
        frappe.db.set_value(
            "Employee",
            item["employee"],
            "household_registration",
            item["household_registration"],
            update_modified=False,
        )
        plan["applied"] += 1
    return plan
