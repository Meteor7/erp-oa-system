# Foreign R&D Monthly Entry and Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace daily overseas R&D entry with monthly occurrence-day entry and add an overseas R&D allocation-rate report matching the domestic report.

**Architecture:** Keep the existing Foreign RD Expense document and allocation flow. Normalize monthly rows to technical first-of-month dates and `occurrence_days * 8` hours, aggregate legacy daily rows on read, and reuse the existing pivot helpers for a separate report page.

**Tech Stack:** Python/Frappe, Vue 3, Node test runner, pytest

## Global Constraints

- Preserve the existing foreign-expense dashboard and automatic recalculation.
- Keep domestic and foreign hour denominators separate.
- Default foreign entity: `QIHENG DEMO OVERSEAS`.
- Preserve unrelated dirty-worktree changes.

---

### Task 1: Monthly foreign hour contract

**Files:**
- Modify: `rayher_hr_payroll/api/foreign_rd_entry.py`
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/foreign_rd_expense_line/foreign_rd_expense_line.json`
- Test: `rayher_hr_payroll/tests/test_foreign_rd_entry.py`

- [ ] Add failing tests proving `2.5` occurrence days become `20` hours and legacy daily lines aggregate by month/entity/project.
- [ ] Run `pytest -q rayher_hr_payroll/tests/test_foreign_rd_entry.py` and confirm the new assertions fail because monthly fields are unsupported.
- [ ] Add `foreign_entity` and `occurrence_days`, default legacy rows to QIHENG DEMO OVERSEAS, and keep the current allocation calculation driven by normalized hours.
- [ ] Run the focused pytest file and confirm it passes.

### Task 2: Monthly entry UI

**Files:**
- Modify: `frontend/src/pages/ForeignRD.vue`
- Modify: `frontend/src/lib/foreignRdImport.js`
- Test: `frontend/tests/foreign-rd-import.test.js`
- Test: `frontend/tests/foreign-rd-source.test.js`

- [ ] Change tests to require subject/project/occurrence-days/hours/remark input and reject the old required date/activity fields.
- [ ] Run the focused Node tests and confirm they fail against the daily UI/parser.
- [ ] Adapt the editor and import parser to monthly rows while leaving the four dashboard cards and save endpoint intact.
- [ ] Run focused Node tests and confirm they pass.

### Task 3: Foreign timesheet report

**Files:**
- Create: `frontend/src/pages/ForeignRDTimesheet.vue`
- Modify: `frontend/src/router.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/lib/access.js`
- Test: `frontend/tests/router-source.test.js`
- Test: `frontend/tests/timesheet-pivot.test.js`

- [ ] Add failing tests for the foreign report route and QIHENG DEMO OVERSEAS project-rate pivot.
- [ ] Run focused Node tests and confirm the route/report are missing.
- [ ] Add the report page by reusing the domestic pivot functions and foreign API lines; add navigation and matching access.
- [ ] Run focused tests, the full frontend test suite, pytest for foreign allocation, and `npm run build`.