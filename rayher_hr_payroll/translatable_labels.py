"""Strings shown in the UI that Frappe's Babel extractors do not emit on their own.

Frappe has no message extractor for module titles (modules.txt / hooks app_title),
Report doctype names, or for strings passed through an *injected* translate callable
(a ``translate: Callable`` parameter, defaulting to identity, bound to ``frappe._``
at the call site -- the reports and controls use this DI pattern for testability, so
the literal is invisible to the extractor). Referencing those strings here via ``_lt``
(lazy translate, a keyword the official ``bench generate-pot-file`` recognises) lets
the standard toolchain extract them into ``locale/main.pot`` so they survive
``update-po-files`` and keep their translations. ``_lt`` is lazy, so importing this
module has no runtime cost and the tuple is intentionally unused.
"""

from __future__ import annotations

from frappe import _lt  # type: ignore[import-not-found]

UNEXTRACTED_LABELS = (
    # Module / app title (Rayher HR Payroll), shown in the Desk module sidebar.
    _lt("Rayher HR Payroll"),
    # Report doctype names (rendered via __(report_name) in Desk; no extractor).
    _lt("RD Allocation Matrix"),
    _lt("RD Timesheet Exceptions"),
    # Report column labels / exception types / messages (report/*.py, injected translate).
    _lt("Exception Type"),
    _lt("Expense Item"),
    _lt("Voucher No"),
    _lt("Message"),
    _lt("Missing Timesheet"),
    _lt("Unclassified R&D Hours"),
    _lt("{0}-{1:02d} has no submitted timesheet hours."),
    _lt("Logged {0} h on R&D projects but rd_personnel_type is '{1}'; excluded from R&D allocation."),
    # Validation messages raised through controls/*.py via injected translate.
    _lt("Year and month filters are required."),
    _lt("Year and month filters must be valid numbers."),
    _lt("Year and month must be valid numbers."),
    _lt("Month must be between 1 and 12."),
    _lt("A submitted RD Expense Import already exists for period {0} ({1}); importing the same period twice would double-count R&D cost."),
    _lt("Statutory holiday overtime cannot be converted into compensatory leave; it must be paid according to policy."),
    _lt("R&D period {0} is locked; timesheet changes require a correction workflow."),
    _lt("Project {0} is not enabled for R&D timesheet entry."),
    _lt("Project {0} needs capitalization start and end dates before R&D timesheet entry."),
    # Script Report *filter* labels (report JSON; Babel does not extract report-JSON
    # filter labels). Values match the base-app catalogue, so registering them keeps
    # our catalogue self-sufficient without overriding these generic words elsewhere.
    _lt("Allocation"),
    _lt("Year"),
    _lt("Month"),
)
