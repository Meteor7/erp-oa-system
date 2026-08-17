# OA Approval Critical Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复采购履约尾款闭环、审批数据篡改、付款看板金额、请假不可用和写接口安全问题。

**Architecture:** 来源采购申请保存跨付款阶段共享的履约汇总，付款单保留审批和证据快照。审批变更保护在 DocType validate 层拦截非草稿业务字段修改；付款看板使用付款单维度的金额流水。

**Tech Stack:** Frappe/Python、Vue 3、Node test runner、MariaDB、Docker。

## Global Constraints

- 不实现同供应商自动合并付款。
- 不实现核心金蝶同步。
- 不确定的人工异常审批继续挂起。
- 关键业务字段变化必须退回申请人后重新提交。
- 所有写接口强制 POST。

---

### Task 1: 履约状态跨付款阶段继承

**Files:**
- Modify: `rayher_hr_payroll/approval_center.py`
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`
- Test: `rayher_hr_payroll/tests/test_procurement_payment_flow.py`

**Interfaces:**
- Produces: `_fulfillment_snapshot(source) -> dict`
- Produces: `_sync_procurement_fulfillment_to_source(payment_doc) -> source_doc | None`

- [ ] Add a failing test proving a new tail-payment draft inherits full-arrival and passed-inspection state from its source procurement request.
- [ ] Run the focused test and confirm it fails with inherited fields still set to 未到货/未验收.
- [ ] Copy fulfillment fields from the source in `save_draft`.
- [ ] Add a failing endpoint test proving arrival/inspection on a paid payment synchronizes the source request.
- [ ] Implement source synchronization inside the authorized lifecycle save transaction.
- [ ] Run focused procurement tests and confirm they pass.

### Task 2: Protect approved business content

**Files:**
- Modify: `rayher_hr_payroll/oa_mutation_guard.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_mutation_guard.py`

**Interfaces:**
- Produces: `DRAFT_EDITABLE_BUSINESS_FIELDS: set[str]`

- [ ] Add failing tests for changing supplier, payment stage, expected delivery date, project and business lines while status is active.
- [ ] Confirm the tests fail because changes are currently allowed.
- [ ] Reject changes to those fields whenever the previous document is not 草稿, unless inside `authorized_oa_action`.
- [ ] Confirm draft edits and authorized server actions remain allowed.
- [ ] Run the mutation-guard suite.

### Task 3: Correct payment dashboard money

**Files:**
- Modify: `rayher_hr_payroll/approval_amount_ledger.py`
- Modify: `rayher_hr_payroll/approval_center.py`
- Test: `rayher_hr_payroll/tests/test_approval_amount_ledger.py`
- Test: `rayher_hr_payroll/tests/test_approval_center_dashboard.py`

**Interfaces:**
- Produces: `linked_payment_balance(source, payment) -> dict`
- Consumes ledger events scoped by `linked_request`.

- [ ] Add failing tests for one reserved and three paid payment rows.
- [ ] Confirm current dashboard returns all zero values.
- [ ] Implement payment-scoped reserved and paid totals without duplicating source balances.
- [ ] Set approved amount only for paid/completed payment records and calculate payment remaining amount.
- [ ] Run amount-ledger and dashboard tests.

### Task 4: Open leave flow and secure writes

**Files:**
- Modify: `rayher_hr_payroll/api/oa_entry.py`
- Modify: `frontend/src/pages/ApprovalDashboard.vue`
- Modify: `frontend/src/pages/PreRequestCenter.vue`
- Test: `frontend/tests/approval-center.test.js`
- Test: `frontend/tests/procurement-workflow-ui.test.js`
- Configure: `sites/rayher.localhost/site_config.json`

- [ ] Add source-contract tests requiring POST decorators for all approval-center writes.
- [ ] Confirm draft save and business-document attach currently fail the contract.
- [ ] Restrict the endpoints to POST.
- [ ] Add frontend tests for dashboard loading and organization preflight messaging.
- [ ] Implement loading and preflight UI states.
- [ ] Set `leave_approval_admin_only=0` and verify normal employee access with unchanged employee binding validation.

### Task 5: Docker data repair and verification

**Files:**
- Modify: exact Docker site data only after read-only target validation.

- [ ] Backfill source fulfillment fields from existing paid procurement payments using exact source/payment pairs.
- [ ] Verify target documents and counts before applying updates.
- [ ] Delete OA-2026-00187 only if it remains a no-step draft with no documents, ToDos or ledger rows.
- [ ] Run focused backend tests.
- [ ] Run all frontend tests.
- [ ] Run the production frontend build.
- [ ] Query routes, ToDos, ledger totals, source fulfillment snapshots and site feature config.
- [ ] Review `git diff` and commit the completed fix.

