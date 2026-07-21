# Monthly R&D Timesheet Entry Design

**Date:** 2026-07-21
**Status:** Approved in conversation and delegated to the main task

## Goal

Replace employee-facing daily R&D time entry with a month-level workflow used by team leaders. A leader selects an employee and accounting month, then records one row per project with occurrence days to two decimal places and an optional remark. Hours are read-only and equal occurrence days multiplied by eight.

The existing ERPNext `Timesheet` and `Timesheet Detail` tables remain the source consumed by cost allocation, period locking, dashboard, and project controls.

## Scope

- The entry page follows the supplied “工时录入（按月）” layout: employee, year/month, project, occurrence days, calculated hours, remark, add row, delete row, and save.
- Only System Manager, HR User, HR Manager, and Department Manager roles may write monthly entries. Employees and finance users retain scoped read access.
- A Department Manager may write only for the manager and direct reports already returned by the existing employee-scope helper.
- The activity type is not shown. The backend uses the existing default R&D activity type `编码开发` so ERPNext validation and audit fields remain populated.
- Existing daily entries are preserved. They are not migrated or silently grouped into editable monthly records.
- Foreign commissioned R&D entry remains daily and is out of scope.

## Approaches Considered

### 1. One ERPNext Timesheet per monthly entry, with generated detail rows — selected

Store monthly metadata on the `Timesheet` parent and create one `Timesheet Detail` for every full or partial occurrence day. Existing consumers continue summing `Timesheet Detail.hours`, while the entry page queries one parent-level record.

This preserves the allocation and lock architecture, gives edit/delete a single transactional aggregate boundary, and prevents fragile grouping by project names or technical dates.

### 2. A new monthly DocType plus mirrored Timesheets

This gives the cleanest domain model but creates two persisted sources that must remain synchronized. It adds reconciliation, lifecycle, permission, migration, and audit complexity without a current business need.

### 3. One long Timesheet Detail row containing all monthly hours

This is the smallest change but misrepresents 32 hours as a continuous time interval, conflicts with ERPNext overlap and daily-duration rules, and makes partial-day validation unreliable. It is rejected.

## Data Model

Add hidden, read-only custom fields to the `Timesheet` parent:

| Field | Type | Rule |
| --- | --- | --- |
| `rd_monthly_entry_id` | Data | Server-generated UUID, unique, immutable |
| `rd_entry_period` | Data | Canonical `YYYY-MM`, immutable for an existing entry |
| `rd_occurrence_days` | Float | Precision 2; positive and no more than the selected month’s calendar-day count |
| `rd_calculated_hours` | Float | Precision 2; exactly `rd_occurrence_days × 8` |
| `rd_system_generated` | Check | `1` for monthly entries; distinguishes technical dates from real dates |

The existing `rd_spa_managed` flag remains set. The monthly entry ID lives on the parent because a single parent owns every generated child row; joining the child rows to the parent provides the grouping key without duplicating metadata.

## Precision Rules

- Days accept at most two decimal places and are calculated with `Decimal`, never binary floating-point arithmetic.
- Hours are quantized to two decimal places after multiplication by eight.
- Examples: `1.25 days = 10.00 hours`; `2.35 days = 18.80 hours`.
- A value such as `2.35` creates two 8-hour details and one 2.80-hour detail.
- The sum of generated detail hours must equal `rd_calculated_hours` before the document is submitted.

## Technical Date Allocation

Technical dates are selected from calendar dates inside the chosen month. Each generated detail begins at `00:00` and ends after at most eight hours. The allocator uses the earliest free dates after considering other monthly entries for the same employee and month.

Technical dates:

- never leave the selected month;
- never overlap another generated detail;
- never exceed eight hours on one date;
- are never displayed as actual work dates in the business entry page or its export;
- are identified by `rd_system_generated = 1` and must not be treated as attendance evidence.

The monthly maximum is the number of calendar days in the selected month. This matches the screenshot’s June maximum of 30 while allowing July to use 31 and February to use 28 or 29.

## Save, Edit, and Delete

Create a dedicated monthly API instead of changing the raw `list_rd_hours` contract used by the R&D timesheet pivot report:

- `list_monthly_entries(period, employee=None)` returns one row per monthly Timesheet parent.
- `save_monthly_entry(...)` creates a new entry or replaces the entry identified by `monthly_entry_id`.
- `delete_monthly_entry(monthly_entry_id)` deletes exactly one monthly aggregate.
- `bulk_save_monthly_entries(period, employee, rows)` saves the screenshot-style table atomically.

All mutations:

1. enforce role and employee visibility;
2. acquire the existing period/import lock and an employee row lock;
3. reject submitted cost-allocation periods;
4. reject a month containing any non-monthly Timesheet row for that employee;
5. reject a duplicate employee/period/project monthly record;
6. validate the employee’s total occurrence days against the month limit;
7. cancel and delete the old parent only inside the same transaction that creates the replacement;
8. roll back the complete mutation when any generated row or submission fails.

The client-generated table may contain multiple projects. The bulk endpoint validates the final state before changing any document, so row order cannot cause a temporary limit failure and a failed later row cannot leave earlier rows committed.

## Read Models and Reports

- The monthly entry page and Excel export use only month, employee, project, occurrence days, calculated hours, and remark.
- `list_rd_hours` continues returning detail rows for the pivot report. The pivot uses the technical date only to determine the month and never displays it.
- The entry-page summary uses `rd_occurrence_days`, not distinct technical dates, for filled days and standard hours.
- Cost allocation, dashboard totals, period locks, project locks, and missing-month reports continue reading submitted detail hours by month.
- Any future daily attendance or missing-day report must exclude parents where `rd_system_generated = 1`.

## Legacy Data and Mode Isolation

Existing daily records remain queryable by the existing report and cost-allocation paths. On the monthly entry page they appear only as a clear read-only legacy warning/summary; they cannot be edited through monthly APIs.

If an employee has any daily Timesheet detail in a month, the backend rejects monthly writes for that employee/month. Likewise, once monthly records exist, daily SPA writes for that employee/month are rejected. This rule is enforced server-side, not only in the page.

## Critical Review Findings

- A parent-level monthly ID is safer than copying IDs onto child rows because the parent is already the aggregate and transaction boundary.
- A dedicated monthly API prevents the existing pivot and foreign R&D pages from being accidentally changed by a new grouped response shape.
- The generated-date algorithm must allocate across all projects for one employee, not restart at the first day for every project.
- Duplicate prevention must use resolved Project identity, not editable code/name text.
- Decimal days require exact arithmetic and an equality invariant between monthly hours and child-row hours.
- Existing employee write access conflicts with the confirmed team-leader workflow and must be removed while retaining employee view access.
- The currently dirty main checkout belongs to another task; implementation must remain in the isolated `feat/monthly-timesheet-entry` worktree.

## Verification

Automated tests must cover:

- `4.00` days creates four 8-hour details and lists one 32-hour monthly row;
- `2.35` days creates `8 + 8 + 2.80` hours with exact totals;
- values with more than two decimals, zero/negative days, and days above the calendar-month limit are rejected;
- multiple project rows allocate non-overlapping technical dates;
- changing `4.00` to `3.00` leaves only 24 hours with no duplicate parent or detail;
- delete removes every child row for the monthly ID;
- a failed replacement rolls back the old entry and all new rows;
- duplicate projects, concurrent double saves, daily/monthly mixing, locked periods, and submitted allocations are rejected;
- permissions allow authorized managers for visible employees and reject employee self-write and unrelated employees;
- entry list/export never expose technical dates;
- allocation input totals and project ratios remain identical to the calculated monthly hours;
- the existing backend timesheet tests, frontend pivot tests, complete frontend tests, and production build remain green.
