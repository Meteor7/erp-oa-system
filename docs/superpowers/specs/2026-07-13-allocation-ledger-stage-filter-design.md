# Allocation Ledger Stage Filter Design

Date: 2026-07-13
Status: Approved direction, pending written-spec review

## Goal

Rename navigation item 08 to "R&D Expense Ledger" and item 09 to "R&D Expense Summary".
Add the same All / Capitalized / Expensed browsing control from item 09 to item 08.
The selected view must have one consistent definition across the frontend, backend report, visible table, totals, and Excel export.

## User Interface

- Item 08 navigation label and page title become "R&D Expense Ledger".
- Item 09 navigation label and page title become "R&D Expense Summary".
- Item 08 adds a segmented view control with values:
  - all: Summary
  - capitalized: Capitalized
  - expensed: Expensed
- The default is all.
- Changing the view reloads the ledger for the current month or year.
- Recalculate and cancel actions keep their current behavior and remain month-only.
- Export uses the currently selected view and includes the selected view label in the filename.

## Backend And Data Flow

The RD Allocation Matrix report accepts a stage filter using the same canonical values already used by the allocation summary API: all, capitalized, and expensed.

For domestic lines, the report filters by RD Cost Allocation Line.project_stage.
For foreign R&D lines, it filters the normalized project_stage after those lines are generated.
The filter is applied before matrix columns, rows, and totals are built. This guarantees that project columns, detail values, total rows, and exported data all represent the selected view.

Invalid or missing stage values normalize to all for backward compatibility.

## Scope Boundaries

This change does not alter allocation calculation, project-stage determination, approval logic, source expense data, or cancellation behavior.
Item 09 keeps its existing summary API and receives only its new display name.

## Testing

- Navigation source tests assert the new labels for items 08 and 09.
- Allocation page tests assert the three view options, default all, report filter parameter, reload behavior, and current-view export naming.
- Report tests assert all, capitalized, and expensed filtering, including project columns and total rows.
- Existing frontend and relevant backend suites must remain green.
- Production build and live asset responses are verified after deployment.


