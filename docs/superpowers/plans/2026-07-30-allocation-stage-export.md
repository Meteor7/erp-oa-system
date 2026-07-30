# Allocation Stage Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make annual allocation exports preserve each allocation line's historical capitalized or expensed stage when one project changes stage across months.

**Architecture:** Keep the combined ledger matrix unchanged. At export time, load the report independently for `all`, `capitalized`, and `expensed`, then pass those three datasets to the workbook builder so each sheet is generated from server-filtered rows.

**Tech Stack:** Vue 3, frappe-ui resources, JavaScript ES modules, Node test runner, Vite, Python report tests.

## Global Constraints

- Do not modify project lifecycle, OA, reimbursement, accommodation, or OCR behavior.
- Do not infer historical stage from the current Project document.
- Reuse `RD Allocation Matrix` and its existing finance permission check.
- Preserve the existing workbook sheet names and combined ledger layout.

---

### Task 1: Stage-specific workbook datasets

**Files:**
- Modify: `frontend/src/lib/allocationExport.js`
- Test: `frontend/tests/allocation-export.test.js`

**Interfaces:**
- Consumes: optional `stageMatrices` object with `all`, `capitalized`, and `expensed` entries, each shaped as `{ columns: Array, result: Array }`.
- Produces: `buildAllocationExportSheets()` sheets generated from the matching dataset.

- [ ] **Step 1: Write the failing behavior test**

Add a fixture where RD01 has 100 capitalized in January and 50 expensed in February. Pass independently filtered matrices and assert the combined, capitalized, and expensed sheets contain 150, 100, and 50 respectively.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
& "D:\Tools\Pi\node\node.exe" --test frontend/tests/allocation-export.test.js
```

Expected: the capitalized sheet still contains the February 50 and the expensed sheet omits RD01 because production code ignores `stageMatrices`.

- [ ] **Step 3: Implement minimal dataset selection**

Update `buildAllocationExportSheets()` to select:

```js
const allMatrix = stageMatrices?.all || { columns, result };
const capitalizedMatrix = stageMatrices?.capitalized;
const expensedMatrix = stageMatrices?.expensed;
```

Use the explicit stage dataset when present and retain the current column-filter fallback for compatibility.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the command from Step 2 and require all tests in that file to pass.

### Task 2: Export-time report loading

**Files:**
- Modify: `frontend/src/pages/Allocation.vue`
- Modify: `frontend/tests/allocation-source.test.js`
- Test: `frontend/tests/allocation-view.test.js`

**Interfaces:**
- Consumes: `buildAllocationMatrixFilters({ scope, period, allocation, stage })`.
- Produces: `stageMatrices` passed to `exportAllocationWorkbook()`.

- [ ] **Step 1: Add a failing wiring/contract test**

Require the page export path to submit the report for `all`, `capitalized`, and `expensed` and pass the resulting object as `stageMatrices`.

- [ ] **Step 2: Run the focused frontend tests and verify RED**

```powershell
& "D:\Tools\Pi\node\node.exe" --test frontend/tests/allocation-source.test.js frontend/tests/allocation-view.test.js
```

Expected: failure because the current export path passes only the visible matrix.

- [ ] **Step 3: Implement export-only matrix loading**

Create a dedicated export report resource. In `exportCurrentAllocation()`, load the three stages sequentially with the current scope, period, and allocation, then call:

```js
exportAllocationWorkbook({
  period,
  summary,
  stageMatrices,
})
```

Do not mutate `columns`, `result`, `summary`, or the selected page stage.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2 and require all tests to pass.

### Task 3: Regression, build, and delivery

**Files:**
- Generated: `rayher_hr_payroll/public/frontend/index.html`
- Generated: `rayher_hr_payroll/public/frontend/assets/*.js`
- Generated: `rayher_hr_payroll/www/rayher.html`

**Interfaces:**
- Consumes: tested frontend source.
- Produces: deployable Vite assets in the Frappe app.

- [ ] **Step 1: Run frontend and relevant backend regression**

```powershell
& "D:\Tools\Pi\node\node.exe" --test
python -m pytest rayher_hr_payroll/tests/test_reports.py rayher_hr_payroll/tests/test_allocation_entry.py -q
```

- [ ] **Step 2: Build with Yarn 1.22.22**

Use Pi's Node/Corepack Yarn and the verified workspace dependency directory. Require Vite build success.

- [ ] **Step 3: Verify generated behavior and plaintext**

Check `git diff --check`, verify the built Allocation asset contains the stage-matrix export behavior, and scan every changed file's first 4096 bytes for exact marker `%TSD-Header-###%`.

- [ ] **Step 4: Commit and push**

Create one commit:

```text
fix: preserve allocation stages in annual exports
```

Push it to PR #24's `feat/ocr-monthly-timesheet-integration` branch without force.
