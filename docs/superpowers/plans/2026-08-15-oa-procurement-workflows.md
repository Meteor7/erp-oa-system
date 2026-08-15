# OA Procurement Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build executable procurement application, direct purchase, procurement payment, contract delivery, receiving, inspection, write-off, dashboard, and test-data flows on the existing OA approval engine.

**Architecture:** Keep `api/oa_entry.py` as the only approval execution engine. Put procurement state and evidence rules in a focused domain module, personnel-role lookup in a resolver, and current-step ToDo synchronization in an assignment adapter. `workflow_status` remains approval state while `business_status` records procurement execution state.

**Tech Stack:** Frappe/Python, MariaDB, Vue 3, frappe-ui, pytest, Docker bench site `rayher.localhost`.

## Global Constraints

- Start from verified base `2cbf9230` plus approved design commit `b9682441`.
- Preserve the existing leave and expense-payment routes except for approved formal display labels and production-equipment approval.
- Use formal names or role labels; never display 演示员工37、演示员工28 or 演示员工10 as an approval-role label.
- Automatic same-supplier payment merging, Kingdee integration, accounting posting details, and the manual exception route remain suspended.
- Procurement payment always follows 财务审核 → 演示员工21 → 演示员工29 → 财务确认付款.
- Expense/buying payment retains department-based routing.
- Every production behavior follows RED → GREEN → REFACTOR.
- Test data may only create OA approval-center records and linked OA business documents.

---

### Task 1: Procurement schema and domain state definitions

**Files:**
- Modify: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_request/oa_approval_request.json`
- Create: `rayher_hr_payroll/procurement_workflow.py`
- Create: `rayher_hr_payroll/tests/test_procurement_workflow.py`
- Modify: `rayher_hr_payroll/tests/test_approval_center_schema.py`

**Interfaces:**
- Produces: `validate_procurement_submission(doc, evidence)`, `validate_payment_submission(doc, evidence)`, `transition_business_state(doc, action, payload, evidence)`.
- Produces constants for procurement scope, payment stage, arrival, inspection, write-off, and business statuses.

- [ ] **Step 1: Write failing schema and transition tests**

Add literal assertions for conditional required fields, allowed status transitions, arrival quantity bounds, 100% prepayment risk fields, and forbidden direct transitions such as 未到货 → 验收通过.

- [ ] **Step 2: Verify RED**

Run: `/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_procurement_workflow.py rayher_hr_payroll/tests/test_approval_center_schema.py`
Expected: FAIL because the module and schema fields do not exist.

- [ ] **Step 3: Implement minimal domain model**

Add the approved fields from design sections 3 and 7. Implement pure validation and transition functions with a literal transition table. Keep external database lookups out of the pure module.

- [ ] **Step 4: Verify GREEN and commit**

Run the Task 1 tests, then `git diff --check`.
Commit: `feat: define procurement workflow states`

### Task 2: Dynamic approval-role resolution and Zhong Haitao account

**Files:**
- Create: `rayher_hr_payroll/oa_role_resolver.py`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_role_assignment/oa_approval_role_assignment.json`
- Create: `rayher_hr_payroll/rayher_hr_payroll/doctype/oa_approval_role_assignment/oa_approval_role_assignment.py`
- Create: `rayher_hr_payroll/tests/test_oa_role_resolver.py`
- Modify: `rayher_hr_payroll/install.py`

**Interfaces:**
- Produces: `resolve_role(role_key, store=None) -> {role_key, role_label, user, employee, employee_name}`.
- Produces role keys `pmc`, `hr_manager`, `finance_auditor`, `finance_manager`, `vice_manager`, `general_manager`, `production_asset_owner`.

- [ ] **Step 1: Write failing resolver tests**

Cover unique designation lookup, explicit PMC assignment, missing account, inactive employee, duplicate holder, and snapshot output. Expected values use literal employee fixtures.

- [ ] **Step 2: Verify RED**

Run: `/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_role_resolver.py`
Expected: FAIL on missing resolver.

- [ ] **Step 3: Implement resolver and idempotent account bootstrap**

Resolve normal roles from active Employee designation and PMC from the role-assignment record. Add an idempotent installer that creates `person076@staff.example.invalid`, assigns Employee role, binds HR-EMP-90017, and seeds the PMC assignment only when all preconditions match.

- [ ] **Step 4: Verify GREEN and commit**

Run Task 2 tests and existing access-control tests.
Commit: `feat: resolve OA approvers from personnel roles`

### Task 3: Route builders and formal leave labels

**Files:**
- Modify: `rayher_hr_payroll/oa_approval.py`
- Modify: `rayher_hr_payroll/tests/test_oa_approval_routes.py`

**Interfaces:**
- Produces: `build_procurement_route(context)`, `build_direct_purchase_route(context)`, `build_procurement_payment_route(context)` through `build_route`.

- [ ] **Step 1: Write failing route tests**

Cover PMC → supervisor → project owner, non-project omission, top-supervisor skip, duplicate account removal, production-equipment Zhao Peng node, JD route, other-purchase route, fixed procurement-payment route, and unchanged department-based expense-payment branches. Assert formal leave labels.

- [ ] **Step 2: Verify RED**

Run: `/workspace/development/frappe-bench/env/bin/pytest -q rayher_hr_payroll/tests/test_oa_approval_routes.py`
Expected: FAIL for unsupported request types and legacy labels.

- [ ] **Step 3: Implement route builders**

Use role snapshots from Task 2. Deduplicate by normalized user id while preserving route order and role-resolution details.

- [ ] **Step 4: Verify GREEN and commit**

Run route, organization, and diagnostics tests.
Commit: `feat: add procurement approval routes`

### Task 4: Unified save, submit, permissions, and feature gates

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/approval_center.py`
- Modify: `rayher_hr_payroll/oa_feature_gate.py`
- Modify: `rayher_hr_payroll/oa_mutation_guard.py`
- Modify: `rayher_hr_payroll/tests/test_invoice_request_integration.py`
- Modify: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`
- Modify: `rayher_hr_payroll/tests/test_oa_feature_gate.py`
- Modify: `rayher_hr_payroll/tests/test_approval_center_mutation_guard.py`

**Interfaces:**
- Extends `create_request`, `submit_request`, `preview_route`, `_submit_draft`, `_summarize_doc` for three procurement types.
- Keeps server mutation authorization narrow: only named service operations inside `authorized_oa_action`.

- [ ] **Step 1: Write failing integration tests**

Test applicant-only draft submission, actual step generation, project owner snapshot, current approver, duplicate submission rejection, another user’s draft rejection, feature-flag isolation, and mutation-guard denial outside the service context.

- [ ] **Step 2: Verify RED**

Run the named test files. Expected: procurement submission is blocked as draft-only.

- [ ] **Step 3: Implement through the existing engine**

Extend existing route context and `_submit_draft`; do not create a parallel submit function. Enable each feature only after its executable path exists. Preserve operation logs and transaction locks.

- [ ] **Step 4: Verify GREEN and commit**

Run all approval-center, feature-gate, mutation-guard, native-access, and invoice-request integration tests.
Commit: `feat: submit procurement requests through OA engine`

### Task 5: Current approver assignments and idempotent ToDo sync

**Files:**
- Create: `rayher_hr_payroll/oa_assignments.py`
- Create: `rayher_hr_payroll/tests/test_oa_assignments.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`

**Interfaces:**
- Produces: `sync_current_assignments(doc, previous_step=None)` and `close_request_assignments(doc)`.

- [ ] **Step 1: Write failing assignment tests**

Using an in-memory assignment store, test one ToDo per current approver, no duplicates on retry, closure on advance, reassignment on targeted rejection, and closure on completion.

- [ ] **Step 2: Verify RED**

Run Task 5 tests. Expected: missing module.

- [ ] **Step 3: Implement adapter and wire service boundaries**

Use deterministic reference keys based on request name and step key. Call synchronization only after a successful saved state change.

- [ ] **Step 4: Verify GREEN and commit**

Run assignment and request-integration tests.
Commit: `feat: synchronize OA approval assignments`

### Task 6: Contract delivery comparison, reapproval, and five-role copy

**Files:**
- Modify: `rayher_hr_payroll/procurement_workflow.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Create: `rayher_hr_payroll/tests/test_procurement_contract_flow.py`

**Interfaces:**
- Produces API `register_contract_delivery(name, contract_delivery_date, reason=None)`.
- Produces `contract_copy_recipients(snapshot) -> list[dict]`.

- [ ] **Step 1: Write failing contract tests**

Cover on-time direct confirmation, late-delivery reason requirement, PMC → project-owner confirmation, non-project PMC-only confirmation, repeated later change, five-role recipient generation, duplicate user collapse, and history preservation.

- [ ] **Step 2: Verify RED**

Run Task 6 tests. Expected: endpoint and domain functions absent.

- [ ] **Step 3: Implement contract subflow**

Append new approval steps through the same step serialization rules. Store copy recipients as role-aware snapshots and create notifications/ToDos only after confirmation.

- [ ] **Step 4: Verify GREEN and commit**

Run Task 6 plus assignment tests.
Commit: `feat: close contract delivery confirmation loop`

### Task 7: Procurement payment, arrival evidence, inspection, and write-off

**Files:**
- Modify: `rayher_hr_payroll/procurement_workflow.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `rayher_hr_payroll/approval_amount_ledger.py`
- Create: `rayher_hr_payroll/tests/test_procurement_payment_flow.py`
- Modify: `rayher_hr_payroll/tests/test_approval_amount_ledger.py`

**Interfaces:**
- Produces APIs `record_arrival`, `record_inspection`, `record_prepayment_followup`, `writeoff_prepayment`, and `close_procurement`.

- [ ] **Step 1: Write failing payment lifecycle tests**

Cover finance-first prepayment, Li/Wang ordering for every stage, arrival proof requirement, partial/full quantity, acceptance evidence, rejection direction, 100% prepayment overdue derivation, no-tail write-off and close requirements, and immutable source allocation totals.

- [ ] **Step 2: Verify RED**

Run Task 7 tests. Expected: lifecycle APIs absent.

- [ ] **Step 3: Implement evidence-backed state changes**

Query active OA Business Document versions by approved document types. Reject invalid transitions server-side and append operation events with actor, old/new state, quantity, evidence names, and reason.

- [ ] **Step 4: Verify GREEN and commit**

Run payment, ledger, document, and integration tests.
Commit: `feat: implement procurement payment lifecycle`

### Task 8: Approval-center forms, detail page, and real project selector

**Files:**
- Modify: `frontend/src/pages/PreRequestCenter.vue`
- Modify: `frontend/src/pages/OAApprovals.vue`
- Modify: `frontend/src/router.js`
- Create or modify: `frontend/src/lib/procurementWorkflow.js`
- Add frontend tests under `frontend/src/**/__tests__/`

**Interfaces:**
- Consumes all request and lifecycle endpoints from Tasks 4, 6, and 7.

- [ ] **Step 1: Write failing component tests**

Test Project link options, conditional non-project allocation, purchase-method placement, payment-stage fields, server error normalization, submit visibility, current-approver display, targeted rejection reason, and evidence-gated actions.

- [ ] **Step 2: Verify RED**

Run the project’s frontend test command for the named tests. Expected: required controls absent.

- [ ] **Step 3: Implement form and detail interactions**

Use selectable API-backed options rather than free text. Reuse OA detail step timeline and rejection UI. Ensure raw server HTML never renders as error text.

- [ ] **Step 4: Verify GREEN and commit**

Run frontend tests and `npm run build`.
Commit: `feat: build procurement approval center UI`

### Task 9: Fixed-asset and prepayment-risk payment dashboard

**Files:**
- Modify: `rayher_hr_payroll/approval_center.py`
- Modify: `frontend/src/pages/ApprovalDashboard.vue`
- Modify: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`

**Interfaces:**
- Extends dashboard result with `asset_summary` and `prepayment_risk_summary`, computed from real payment requests.

- [ ] **Step 1: Write failing dashboard tests**

Use literal records for fixed/non-fixed, category totals, pending arrival, pending inspection, rejected inspection, pending write-off, and overdue 100% prepayment.

- [ ] **Step 2: Verify RED**

Run dashboard tests. Expected: summary keys absent.

- [ ] **Step 3: Implement query aggregation and drill-down cards**

Return record names for each card so every total can be opened. Do not create display-only records.

- [ ] **Step 4: Verify GREEN and commit**

Run dashboard tests and frontend build.
Commit: `feat: add fixed asset payment dashboard`

### Task 10: Isolated approval-center test-data seed and cleanup

**Files:**
- Create: `rayher_hr_payroll/maintenance/approval_center_test_data.py`
- Create: `rayher_hr_payroll/tests/test_approval_center_test_data.py`

**Interfaces:**
- Produces `seed(batch_id, dry_run=True)` and `cleanup(batch_id, dry_run=True)`.

- [ ] **Step 1: Write failing seed tests**

Test dry-run output, missing prerequisite refusal, ten required scenarios, correct generated steps and current approvers, OA-only writes, idempotent rerun, and exact batch cleanup.

- [ ] **Step 2: Verify RED**

Run Task 10 tests. Expected: missing module.

- [ ] **Step 3: Implement guarded seed and cleanup**

Reuse existing projects/employees/suppliers and create only OA Approval Request, its child rows, OA Business Document, Assignment/ToDo, and File records tagged with the batch id.

- [ ] **Step 4: Verify GREEN and commit**

Run seed tests and a dry run against `rayher.localhost`.
Commit: `testdata: add isolated OA procurement scenarios`

### Task 11: Docker end-to-end verification and final PDF

**Files:**
- Create: `docs/oa-procurement-e2e-evidence.md`
- Create: final PDF under the workspace delivery directory using the PDF skill.

**Interfaces:**
- Consumes the completed system; produces a reproducible evidence report and verified PDF.

- [ ] **Step 1: Run complete backend and frontend suites**

Run all affected pytest files, then the full app test suite, frontend tests, `npm run build`, `git diff --check`, and Python compilation.

- [ ] **Step 2: Migrate and verify Docker site**

Take a fresh backup, run `bench --site rayher.localhost migrate`, clear caches, and verify schema/role assignments.

- [ ] **Step 3: Run multi-account E2E scenarios**

For each required actor, submit and process real records; query steps, current approvers, ToDos, operation logs, evidence links, business states, and dashboard totals after every action. Clean the E2E batch afterward, then create the user-visible approved test batch.

- [ ] **Step 4: Create and visually verify PDF**

The PDF must include the final flowchart, route table, state transitions, evidence rules, suspended items, and test evidence. Render all pages and inspect them for black boxes, overlap, clipped text, and font problems.

- [ ] **Step 5: Final verification and commit**

Re-run the full verification commands after PDF generation and record exact pass counts.
Commit: `docs: add verified OA procurement workflow evidence`
