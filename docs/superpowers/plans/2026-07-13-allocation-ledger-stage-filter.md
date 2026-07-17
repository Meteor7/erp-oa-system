# Allocation Ledger Stage Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Rename items 08 and 09 and add a backend-backed All / Capitalized / Expensed ledger view to item 08.

**Architecture:** Item 08 sends a canonical stage filter to the existing RD Allocation Matrix report. The report normalizes and filters combined domestic and foreign lines before building columns, rows, and totals; the frontend renders and exports only that returned view.

**Tech Stack:** Vue 3, frappe-ui, Frappe Script Report, Python, Node test runner, pytest.

## Global Constraints

- Keep allocation calculation, cancellation, and approval behavior unchanged.
- Use canonical stage values all, capitalized, and expensed.
- Default to all and normalize invalid backend input to all.
- Preserve month and year support.
- Write project files through a trusted command-shell writer and verify plaintext headers.

---

### Task 1: Add Failing Navigation And Ledger View Tests

**Files:**
- Modify: frontend/tests/app-shell-source.test.js
- Modify: frontend/tests/allocation-source.test.js
- Modify: frontend/tests/allocation-dashboard-source.test.js
- Modify: rayher_hr_payroll/tests/test_reports.py

**Interfaces:**
- Consumes: existing Vue source and RD Allocation Matrix module
- Produces: assertions for new labels, allocationMode, stage report filter, watcher, and filter_allocation_lines_by_stage

- [ ] Add source assertions for the 08 and 09 labels and page titles.
- [ ] Add source assertions for modeOptions, default all, stage: allocationMode.value, and watch(allocationMode, loadMatrix).
- [ ] Add a Python test that all returns every line, capitalized returns capitalized lines, expensed returns expensed lines, and invalid input returns every line.
- [ ] Run the focused Node and pytest commands and confirm failures are caused by missing behavior.

### Task 2: Implement The Shared Stage View

**Files:**
- Modify: frontend/src/App.vue
- Modify: frontend/src/pages/Allocation.vue
- Modify: frontend/src/pages/AllocationDashboard.vue
- Modify: rayher_hr_payroll/rayher_hr_payroll/report/rd_allocation_matrix/rd_allocation_matrix.py

**Interfaces:**
- Consumes: filters.stage from the report request
- Produces: filter_allocation_lines_by_stage(lines, stage) and a filtered matrix

- [ ] Rename the navigation labels and both page titles.
- [ ] Add the segmented control and allocationMode state to item 08.
- [ ] Add stage to matrixFilters and reload the matrix when allocationMode changes.
- [ ] Filter summary cards and export summary to the selected view and add the view label to the export period.
- [ ] Implement filter_allocation_lines_by_stage and apply it after domestic and foreign lines are combined, before build_allocation_matrix.
- [ ] Run focused tests until green.

### Task 3: Build, Deploy, And Verify

**Files:**
- Build output: rayher_hr_payroll/public/frontend
- Deploy source: RD Allocation Matrix report module

**Interfaces:**
- Consumes: tested source
- Produces: live static assets and backend report behavior on rayher.localhost

- [ ] Run all frontend tests and relevant backend report tests.
- [ ] Build the frontend.
- [ ] Verify generated files do not contain the TipRay TSD header.
- [ ] Transfer the build and backend report file to rayher-bench through Base64 decoding.
- [ ] Clear caches and restart honcho.
- [ ] Verify login, route redirect, live assets, and backend stage filtering.
