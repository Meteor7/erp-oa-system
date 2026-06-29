"""Chinese supplements for a few upstream ERPNext/HRMS report names.

These Report doctypes ship from the base apps (HR / Payroll modules) and are
surfaced in the Desk workspace *report lists* this deployment uses, but the
upstream Chinese translation does not yet cover them, so they render in English
next to the otherwise-Chinese report list. They are NOT defined by this app.

Because Desk renders those report-card labels client-side via ``__(label)``, the
only translation source that reaches the client is an app's compiled catalogue
(runtime ``Translation`` doctype rows do not), so we register the exact labels
here via ``_lt`` to carry a Chinese string for them. Each is a specific,
multi-word report name -- there is no generic-word collision, so the override is
additive (the base apps provide no zh for these msgids).

The broader, desk-wide English seen in base HR pages (onboarding steps, number
cards, dashboards) is pervasive upstream-translation incompleteness and is out of
scope here; it belongs upstream (HRMS Chinese translation) rather than in this app.
"""

from __future__ import annotations

from frappe import _lt  # type: ignore[import-not-found]

CORE_REPORT_LABELS = (
    _lt("Employee Exits"),
    _lt("Employees Working on a Holiday"),
    _lt("Shift Attendance"),
    _lt("Employee Hours Utilization Based On Timesheet"),
    _lt("Project Profitability"),
    _lt("Appraisal Overview"),
    _lt("Income Tax Computation"),
)
