# OA Procurement Payment Routing and JD Cosign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct procurement-payment stage routing and gates, and make JD purchasing a true parallel cosign.

**Architecture:** Keep the existing OA request/step engine. Extend route construction with an explicit normalized payment stage, derive that stage server-side from payment-plan facts and fulfillment state, enforce evidence gates before route generation, and render approve/handle semantics distinctly. Use the existing mode=all engine for JD cosign.

**Tech Stack:** Frappe/Python, Vue 3, pytest, Vitest, Vite, MariaDB, Docker.

## Global Constraints

- Kingdee integration, automatic same-supplier merge, artificial-exception approver selection, accounting execution details, automatic reminders, and customized dashboards remain out of scope.
- Employee department and dynamic role identities must be resolved server-side.
- New production behavior requires a failing test first.
- Project files are written inside Docker using trusted shell/Python writers because of TipRay encryption.

---

### Task 1: Stage-specific procurement payment routes

**Files:**
- Modify: `rayher_hr_payroll/oa_approval.py`
- Test: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Test: `rayher_hr_payroll/tests/test_procurement_payment_flow.py`

**Interfaces:**
- Consumes: `build_route(..., payment_stage=...)`
- Produces: `build_procurement_payment_route(payment_stage, roles=None)`

- [ ] Replace the test that asserts every stage has the same route with separate prepayment and post-arrival assertions.
- [ ] Run the focused tests and verify they fail because routes are still flattened.
- [ ] Pass normalized payment stage into route construction.
- [ ] Implement prepayment and post-arrival routes.
- [ ] Run focused tests and verify they pass.

### Task 2: Server-side stage derivation and submission gates

**Files:**
- Modify: `rayher_hr_payroll/procurement_workflow.py`
- Modify: `rayher_hr_payroll/approval_center.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_procurement_workflow.py`
- Test: `rayher_hr_payroll/tests/test_procurement_payment_flow.py`

**Interfaces:**
- Produces: `normalize_payment_stage(doc) -> str`
- Produces: `validate_payment_submission(doc, evidence) -> normalized stage`

- [ ] Add failing tests for 100% prepayment normalization, post-arrival full payment, missing arrival/inspection, missing invoice, and forbidden legacy full-payment semantics.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement normalization and evidence gates.
- [ ] Persist the normalized stage before generating steps.
- [ ] Run focused tests and confirm green.

### Task 3: JD parallel cosign

**Files:**
- Modify: `rayher_hr_payroll/oa_approval.py`
- Test: `rayher_hr_payroll/tests/test_oa_approval_routes.py`
- Test: `rayher_hr_payroll/tests/test_oa_approval_engine.py`

**Interfaces:**
- Produces: one `mode="all"` step with HR manager and Li Qinggele approvers.

- [ ] Change the JD route test to assert one parallel step with two approvers.
- [ ] Run it and verify failure against the current serial route.
- [ ] Implement the mode=all step.
- [ ] Verify both approvers are required and rejection remains available.
- [ ] Run focused tests.

### Task 4: Frontend stage and node semantics

**Files:**
- Modify: `frontend/src/pages/PreRequestCenter.vue`
- Modify: `frontend/src/pages/PaymentCenter.vue`
- Test: matching frontend unit tests.

**Interfaces:**
- Consumes server-derived stage and step `mode`.
- Displays approve as “审批”, handle as “办理”.

- [ ] Add failing component tests for removal of the ambiguous full-payment option and separate approve/handle copy.
- [ ] Run tests and confirm failure.
- [ ] Make stage read-only/derived where possible and replace ambiguous labels.
- [ ] Render action buttons and trajectory status by mode.
- [ ] Run frontend tests and build.

### Task 5: Docker data and end-to-end verification

**Files:**
- Modify only isolated OA test records tagged `[OA测试:OA-DEMO-20260816]` or the replacement batch tag.
- Do not modify unrelated modules or formal business records.

- [ ] Enumerate the exact old test records and dependencies.
- [ ] Delete only the verified isolated old procurement-payment test records.
- [ ] Create prepayment, tail-payment, post-arrival-full-payment and JD-cosign test records through the real submit APIs.
- [ ] Verify generated steps, current approvers, evidence gates and business statuses in MariaDB.
- [ ] Run full relevant backend tests, frontend tests and production build.
- [ ] Inspect the live Docker pages and record screenshots.

