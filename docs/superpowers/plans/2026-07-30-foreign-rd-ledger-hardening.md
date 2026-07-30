# Foreign R&D Ledger Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Prevent foreign R&D costs from disappearing or duplicating while preserving existing domestic allocation behavior.

**Architecture:** Keep the current allocation APIs and document model. Change only three boundaries: monthly response construction, exception propagation, and new-document naming/conflict handling.

**Tech Stack:** Python, Frappe Document API, pytest

## Global Constraints

- Existing Foreign RD Expense document names must not change.
- Existing domestic allocation values and response fields must remain compatible.
- Unexpected foreign aggregation failures must never be returned as financial zeroes.
- Every production change requires a failing regression test first.
- Project files must be written with a trusted shell writer and checked for a plaintext header.

---

### Task 1: Return foreign-only monthly ledger totals

**Files:**
- Modify: rayher_hr_payroll/api/allocation_entry.py
- Test: rayher_hr_payroll/tests/test_allocation_entry.py

**Interfaces:**
- Consumes: _foreign_stage_totals(year: int, month: int) -> dict[str, float]
- Produces: get_allocation(period, scope="month") monthly payload even when no domestic allocation exists

- [ ] **Step 1: Write the failing test**

Add a test where frappe.db.get_value returns None and _foreign_stage_totals returns capitalized 12, expensed 8, unknown 0. Assert get_allocation("2026-06") returns those totals, lines 0, project_summaries [], and name None.

- [ ] **Step 2: Run test to verify it fails**

Run:

~~~powershell
python -m pytest rayher_hr_payroll/tests/test_allocation_entry.py::test_get_allocation_returns_foreign_totals_without_domestic_allocation -q
~~~

Expected: FAIL because the current early return contains only name and scope.

- [ ] **Step 3: Write minimal implementation**

Calculate foreign totals before the domestic-name branch. When name is absent, combine zero domestic totals with foreign totals and return the normal monthly payload shape.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest target and expect PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add rayher_hr_payroll/api/allocation_entry.py rayher_hr_payroll/tests/test_allocation_entry.py
git commit -m "fix: include foreign-only ledger totals"
~~~

### Task 2: Propagate foreign aggregation failures

**Files:**
- Modify: rayher_hr_payroll/api/allocation_entry.py
- Test: rayher_hr_payroll/tests/test_allocation_entry.py

**Interfaces:**
- Consumes: foreign_rd_entry._get_foreign_rd_month and _foreign_matrix_lines_for_month
- Produces: successful empty data for legitimate empty months; raised exceptions for unexpected calculation failures

- [ ] **Step 1: Write failing tests**

Add one test that makes _get_foreign_rd_month raise RuntimeError("foreign totals failed") and asserts _foreign_stage_totals raises it. Add another that makes _foreign_matrix_lines_for_month raise RuntimeError("foreign dashboard failed") and asserts _foreign_dashboard_lines raises it.

- [ ] **Step 2: Run tests to verify they fail**

Run:

~~~powershell
python -m pytest rayher_hr_payroll/tests/test_allocation_entry.py -k "propagates_foreign" -q
~~~

Expected: FAIL because the broad handlers currently return zeros and an empty list.

- [ ] **Step 3: Write minimal implementation**

Remove only the broad try/except blocks that convert unexpected exceptions. Keep the existing normal empty-data behavior supplied by the called foreign functions.

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest selection and expect PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add rayher_hr_payroll/api/allocation_entry.py rayher_hr_payroll/tests/test_allocation_entry.py
git commit -m "fix: surface foreign aggregation failures"
~~~

### Task 3: Prevent duplicate foreign monthly documents

**Files:**
- Modify: rayher_hr_payroll/rayher_hr_payroll/doctype/foreign_rd_expense/foreign_rd_expense.py
- Modify: rayher_hr_payroll/api/foreign_rd_entry.py
- Test: rayher_hr_payroll/tests/test_foreign_rd_entry.py
- Create: rayher_hr_payroll/tests/test_foreign_rd_expense.py

**Interfaces:**
- Produces: ForeignRDExpense.autoname() -> FRD-YYYY-MM for new documents
- Produces: save_foreign_rd duplicate insert -> explicit refresh conflict, without loading and overwriting the winning document

- [ ] **Step 1: Write failing controller test**

Instantiate the controller with period 2026-07, call autoname, and assert name equals FRD-2026-07. Also test slash input normalizes to the same name.

- [ ] **Step 2: Run controller test to verify it fails**

Run:

~~~powershell
python -m pytest rayher_hr_payroll/tests/test_foreign_rd_expense.py -q
~~~

Expected: FAIL because autoname does not exist.

- [ ] **Step 3: Implement deterministic naming**

Add autoname to normalize period fields and assign FRD-{period}. Do not rename existing documents.

- [ ] **Step 4: Write failing API conflict test**

Simulate a new document whose insert raises frappe.DuplicateEntryError. Assert save_foreign_rd raises a clear RuleError containing refresh guidance and never calls save on an existing document.

- [ ] **Step 5: Run API conflict test to verify it fails**

Run:

~~~powershell
python -m pytest rayher_hr_payroll/tests/test_foreign_rd_entry.py -k duplicate -q
~~~

Expected: FAIL because DuplicateEntryError currently escapes without a user-facing conflict message.

- [ ] **Step 6: Implement minimal conflict handling**

Catch only frappe.DuplicateEntryError around the new-document insert and call frappe.throw with a refresh-and-retry message. Do not catch validation, permission, or database errors.

- [ ] **Step 7: Run focused and combined tests**

~~~powershell
python -m pytest rayher_hr_payroll/tests/test_foreign_rd_expense.py rayher_hr_payroll/tests/test_foreign_rd_entry.py rayher_hr_payroll/tests/test_allocation_entry.py -q
~~~

Expected: all tests pass.

- [ ] **Step 8: Commit**

~~~powershell
git add rayher_hr_payroll/api/foreign_rd_entry.py rayher_hr_payroll/rayher_hr_payroll/doctype/foreign_rd_expense/foreign_rd_expense.py rayher_hr_payroll/tests/test_foreign_rd_entry.py rayher_hr_payroll/tests/test_foreign_rd_expense.py
git commit -m "fix: prevent duplicate foreign R&D months"
~~~

### Task 4: Full verification and delivery

**Files:**
- Verify all changed files and issue records

- [ ] **Step 1: Run backend test suite**

~~~powershell
python -m pytest rayher_hr_payroll/tests -q
~~~

- [ ] **Step 2: Run frontend suite**

~~~powershell
npm test --prefix frontend
~~~

- [ ] **Step 3: Inspect repository state**

Run git diff --check, inspect every changed file, and verify file headers do not contain the TipRay TSD marker.

- [ ] **Step 4: Update GitHub tracking**

Add Foreign RD Expense native-interface scope to issue #28. Create one issue for cumulative daily hours and one for OCR pre-decode pixel limits.

- [ ] **Step 5: Complete branch workflow**

Follow superpowers:finishing-a-development-branch and present the integration choices after all verification succeeds.
