"""Strings shown in the UI that Frappe's Babel extractors do not emit on their own.

Frappe has no message extractor for module titles (modules.txt / hooks app_title)
or for report-JSON filter labels. Referencing such strings here via ``_lt`` (lazy
translate, a keyword the official ``bench generate-pot-file`` recognises) lets the
standard toolchain extract them into ``locale/main.pot`` so they survive
``update-po-files`` and keep their translations. ``_lt`` is lazy, so importing
this module has no runtime cost and the tuple is intentionally unused.
"""

from __future__ import annotations

from frappe import _lt  # type: ignore[import-not-found]

# Module / app title (Rayher HR Payroll), shown in the Desk module sidebar.
UNEXTRACTED_LABELS = (_lt("Rayher HR Payroll"),)
