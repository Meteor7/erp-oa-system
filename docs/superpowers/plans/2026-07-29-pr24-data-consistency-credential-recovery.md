# PR #24 Data Consistency and Credential Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale monthly timesheet replacement and preserve recoverable credentials when password delivery publication fails.

**Architecture:** Keep the existing Employee row lock and replace-all transaction, adding an opaque snapshot revision checked after the lock and before deletion. Keep the existing password-reset success path, but turn the private `.pending` CSV into a durable recovery journal that is never overwritten or deleted on a failure path.

**Tech Stack:** Frappe 15.111, Python 3.10+, Vue 3, Node test runner, Vite, pytest.

## Global Constraints

- Limit code changes to the two approved P1 findings; issues #25 through #30 remain out of scope.
- Preserve existing monthly validation, replacement, delete, and allocation-lock behavior.
- Preserve password dry-run, known-credential, CSV schema, and successful output behavior.
- Use trusted plaintext writers and explicit Git blob staging because TipRay makes normal worktree diffs unreliable.
- Do not push unless focused backend tests, frontend source tests, and the production frontend build pass.

---

### Task 1: Monthly snapshot revision contract

**Files:**
- Modify: `rayher_hr_payroll/api/monthly_timesheet_entry.py`
- Modify: `rayher_hr_payroll/tests/test_monthly_timesheet_entry.py`

**Interfaces:**
- Produces: `_monthly_revision_from_documents(documents) -> str`
- Changes: `save_monthly_entries(period, employee, rows, expected_revision=None)`
- Changes: `_replace_monthly_documents(..., expected_revision: str)`
- Changes: `list_monthly_entries(...)` adds `revision: str | None`

- [ ] **Step 1: Write failing revision tests**

Add tests with literal expectations that prove an empty snapshot is deterministic, document identity or modification changes the token, a missing token is rejected, and a stale token fails before `_delete_monthly_document` is called.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q`

Expected: failures because revision helpers, response field, and save argument do not exist.

- [ ] **Step 3: Implement the minimal backend contract**

Use SHA-256 over sorted JSON records containing `name`, `rd_monthly_entry_id`, and `modified`. Add `revision` only for a selected employee. Normalize and require `expected_revision`, pass it into replacement, and compare it with the current documents after the Employee lock has been acquired by the caller and before any delete.

Keep the duplicate-ID and subset ownership checks unchanged.

- [ ] **Step 4: Run focused backend tests and verify GREEN**

Run: `python -m pytest rayher_hr_payroll/tests/test_monthly_timesheet_entry.py -q`

Expected: all monthly tests pass.

- [ ] **Step 5: Stage and commit through verified plaintext blobs**

Commit message: `fix: reject stale monthly timesheet replacements`

### Task 2: Frontend revision transport

**Files:**
- Modify: `frontend/src/pages/TimesheetEntry.vue`
- Modify: `frontend/tests/timesheet-entry-source.test.js`
- Refresh: `rayher_hr_payroll/public/frontend/**` through the existing Vite build

**Interfaces:**
- Consumes: list response `revision`
- Produces: save request parameter `expected_revision`

- [ ] **Step 1: Write failing frontend source test**

Assert that TimesheetEntry retains `monthly.data.revision` and submits it as `expected_revision`.

- [ ] **Step 2: Run test and verify RED**

Run: bundled Node `--test frontend/tests/timesheet-entry-source.test.js`

Expected: the new contract assertion fails.

- [ ] **Step 3: Implement minimal frontend transport**

Add a local revision ref, update it when editable monthly data is hydrated, clear it for the all-employees view, and include it in the save payload. Preserve edited rows when a stale-save error is shown.

- [ ] **Step 4: Run frontend test and production build**

Run the source test, then run the existing frontend production build. Verify generated assets contain the new request field.

- [ ] **Step 5: Stage and commit through verified plaintext blobs**

Commit message: `fix: send monthly timesheet snapshot revision`

### Task 3: Durable credential recovery journal

**Files:**
- Modify: `rayher_hr_payroll/maintenance/user_password_delivery.py`
- Modify: `rayher_hr_payroll/tests/test_user_password_delivery.py`

**Interfaces:**
- Keeps: `deliver_enabled_system_user_passwords(known_credentials_path, output_path, dry_run=True)`
- Changes internal contract: `_write_delivery` exclusively creates `<output>.pending`

- [ ] **Step 1: Write failing failure-injection tests**

Build a real temporary private directory with fake Frappe database and password modules. Test password-update failure, commit failure, final `os.replace` failure, pre-existing pending recovery, and successful publication. Assert event ordering, rollback only before commit, pending retention, final bytes, and private mode.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest rayher_hr_payroll/tests/test_user_password_delivery.py -q`

Expected: failures because current code overwrites/deletes pending files and rolls back after commit.

- [ ] **Step 3: Implement minimal journal behavior**

Reject directory output targets. Open pending CSV with exclusive mode `x`. Track a `committed` boolean. Roll back only when commit has not succeeded. Never unlink pending in the exception handler. Publish the already-private pending file after commit without a second chmod.

- [ ] **Step 4: Run credential tests and verify GREEN**

Run the focused credential tests and confirm all failure-injection assertions pass.

- [ ] **Step 5: Stage and commit through verified plaintext blobs**

Commit message: `fix: preserve password delivery recovery journal`

### Task 4: Integrated verification and PR delivery

**Files:**
- Verify only the files and generated assets from Tasks 1 through 3.

- [ ] **Step 1: Run focused backend suites together**

Run both modified pytest modules in one command and confirm zero failures.

- [ ] **Step 2: Run frontend source tests and production build**

Confirm the revision contract and deployable assets are current.

- [ ] **Step 3: Inspect exact staged/committed blob diffs**

Use `git diff <PR-base>...HEAD --` with explicit target paths and `git cat-file`/header checks. Confirm no TipRay header and no files outside the approved scope.

- [ ] **Step 4: Push to the existing PR branch**

Push `HEAD` to `origin/feat/ocr-monthly-timesheet-integration` and verify PR #24 head SHA and changed files.

- [ ] **Step 5: Re-read the two P1 threads**

Confirm the resulting behavior addresses discussion threads `r3672149431` and `r3672149437`. Do not resolve or reply to threads unless explicitly requested.
