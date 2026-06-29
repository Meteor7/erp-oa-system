"""Strings shown in the UI that Frappe's Babel extractors do not emit on their own.

Frappe has no message extractor for module titles (modules.txt / hooks app_title),
Report doctype names, or for strings passed through an *injected* translate callable
(a function parameter, so the literal is invisible to the extractor). Referencing
those strings here via ``_lt`` (lazy translate, a keyword the official
``bench generate-pot-file`` recognises) lets the standard toolchain extract them
into ``locale/main.pot`` so they survive ``update-po-files`` and keep their
translations. ``_lt`` is lazy, so importing this module has no runtime cost and the
tuple is intentionally unused.
"""

from __future__ import annotations

from frappe import _lt  # type: ignore[import-not-found]

UNEXTRACTED_LABELS = (
    # Module / app title (Rayher HR Payroll), shown in the Desk module sidebar.
    _lt("Rayher HR Payroll"),
    # Report doctype names (rendered via __(report_name) in Desk; no extractor).
    _lt("RD Allocation Matrix"),
    _lt("RD Timesheet Exceptions"),
    # Report column labels / messages reached through report/*.py via an injected
    # ``translate`` callable parameter, which Babel cannot follow to the literal.
    _lt("Exception Type"),
    _lt("Expense Item"),
    _lt("Missing Timesheet"),
    _lt("Unclassified R&D Hours"),
    _lt("Year and month filters are required."),
    _lt("Year and month filters must be valid numbers."),
    _lt("Month must be between 1 and 12."),
    _lt("{0}-{1:02d} has no submitted timesheet hours."),
    _lt("Logged {0} h on R&D projects but rd_personnel_type is '{1}'; excluded from R&D allocation."),
)
