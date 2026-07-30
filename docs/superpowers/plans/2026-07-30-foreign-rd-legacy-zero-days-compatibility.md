# Foreign Legacy Timesheet Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore pre-monthly foreign R&D rows whose new occurrence-days field defaulted to zero, without rewriting or losing their original hours.

**Architecture:** Fix the normalization boundary in `_monthly_foreign_rows`. Positive occurrence days remain authoritative for monthly rows; zero or empty occurrence days with positive hours are treated as legacy daily rows and converted to days using hours divided by eight before subject-project aggregation.

**Tech Stack:** Python, Frappe, pytest, Vue frontend regression suite.

## Global Constraints

- Foreign and domestic allocation ratios remain independent.
- Final company expense summaries continue combining domestic and foreign amounts.
- Historical daily rows are not mutated during reads.
- One occurrence day equals eight hours.

---

### Task 1: Reproduce the zero-day legacy regression

**Files:**
- Modify: `rayher_hr_payroll/tests/test_foreign_rd_entry.py`

**Interfaces:**
- Consumes: `_monthly_foreign_rows(rows, year, month)`.
- Produces: regression coverage for rows with `occurrence_days=0` and positive `hours`.

- [ ] **Step 1: Add the failing test**

Add a row shaped like the real June data: project `RD02`, `work_date=2026-06-01`, `hours=8`, `occurrence_days=0`, and assert the normalized result has `occurrence_days == 1.0` and `hours == 8.0`.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest -q rayher_hr_payroll/tests/test_foreign_rd_entry.py -k zero_occurrence_days
```

Expected: FAIL because current normalization returns zero days and zero hours.

### Task 2: Implement the compatibility rule

**Files:**
- Modify: `rayher_hr_payroll/api/foreign_rd_entry.py`
- Test: `rayher_hr_payroll/tests/test_foreign_rd_entry.py`

**Interfaces:**
- Produces: `_monthly_foreign_rows` output that preserves legacy hours and derives days.

- [ ] **Step 1: Implement the minimal branch**

In `_monthly_foreign_rows`, treat occurrence days as authoritative only when the numeric value is greater than zero. Otherwise, when hours are positive, keep hours and derive `occurrence_days = hours / MAX_DAILY_HOURS`.

- [ ] **Step 2: Verify GREEN**

Run the focused regression test, then:

```bash
python -m pytest -q rayher_hr_payroll/tests/test_foreign_rd_entry.py rayher_hr_payroll/tests/test_foreign_rd_expense.py rayher_hr_payroll/tests/test_allocation_entry.py
node --test frontend/tests/*.test.js
```

Expected: all pass.

- [ ] **Step 3: Commit**

Commit the test and production fix with message `fix: restore legacy foreign rd hours`.

### Task 3: Publish and verify June 2026

**Files:**
- Generated build files only if the frontend build changes them.

- [ ] **Step 1: Push PR24**

Push the new commit to `feat/ocr-monthly-timesheet-integration`.

- [ ] **Step 2: Sync local worktree and Docker**

Fast-forward both to the pushed commit while preserving existing uncommitted changes with recoverable stashes.

- [ ] **Step 3: Rebuild and migrate Docker**

Run the frontend build and `bench --site all migrate`.

- [ ] **Step 4: Verify actual June response and UI**

Call `get_foreign_rd(period="2026-06", scope="month")` and confirm total hours are 168. Open the foreign entry and report pages for June and confirm rows and allocation rates render without console errors.