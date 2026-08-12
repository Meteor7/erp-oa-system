# Dynamic Expense Account Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make R&D expense levels 3 and 4 database-driven while keeping levels 1 and 2 fixed, with confirmed Excel discovery.

**Architecture:** Add a path master DocType seeded with the 43 current paths. The frontend loads the catalog and treats unknown level-3/4 paths as pending; save atomically creates confirmed pending paths and the expense import.

**Tech Stack:** Frappe/Python, Vue 3, Node test runner, MariaDB, Docker.

## Global Constraints

- 一级固定为“研发支出”。
- 二级固定为现有六类。
- 三级必填，四级可空。
- 不修改 RD Expense Item 的四级字段结构。
- 本次只部署本地 Docker，不 push。

---

### Task 1: Pure hierarchy behavior

**Files:** `rayher_hr_payroll/rd_expense_accounts.py`, `frontend/src/lib/expenseAccounts.js`, their tests.

- [ ] Write tests for fixed levels, exact dynamic paths, unknown path collection and mixed empty/non-empty fourth-level leaves.
- [ ] Run tests and confirm missing dynamic APIs fail.
- [ ] Implement pure normalization and hierarchy functions.
- [ ] Run tests and confirm they pass.

### Task 2: Persistent catalog and atomic save

**Files:** new catalog DocType and patch; `rayher_hr_payroll/api/expense_entry.py`; backend tests.

- [ ] Write failing tests for rejecting unconfirmed unknown paths and accepting confirmed paths.
- [ ] Implement catalog lookup, idempotent seed, finance catalog endpoint and atomic confirmed-path creation.
- [ ] Run backend tests.

### Task 3: Excel confirmation UI

**Files:** `frontend/src/lib/expensePaste.js`, `frontend/src/pages/ExpenseImport.vue`, parser tests.

- [ ] Write failing parser tests for accepting valid fixed levels with unknown lower paths.
- [ ] Pass loaded catalog into parsing and validation.
- [ ] Display pending paths with an explicit confirmation checkbox and submit them with save.
- [ ] Run frontend tests and build.

### Task 4: Local Docker rollout

- [ ] Review diff and scan modified files for TipRay headers.
- [ ] Run complete backend/frontend verification.
- [ ] Commit locally.
- [ ] Back up the local site, integrate into Docker app repository, build assets and migrate.
- [ ] Seed and verify “年终一次性奖金” locally without a dummy expense.
- [ ] Run API and page smoke checks; do not push.
