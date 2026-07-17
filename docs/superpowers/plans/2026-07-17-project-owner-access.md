# Project Owner Access Control Implementation Plan

> **For Codex:** Execute with tests, backup, migration, account linking, and live verification.

**Goal:** Limit project management to administrators and linked project owners while granting one project owner an additive all-project scope.

**Architecture:** Frappe roles are the security boundary. Project Owner grants route/API access, All Project Access widens row scope, and existing management roles retain create, assignment, and cancellation privileges. The Vue client mirrors those capabilities without replacing backend checks.

**Implementation:**
1. Add role declarations and unit tests.
2. Filter project API rows by the logged-in project owner.
3. Restrict creation, reassignment, and cancellation to project administrators.
4. Link exact active employee accounts to existing project owner names.
5. Grant Zhang Jun All Project Access as an additive role.
6. Rename the left navigation group to R&D Center.
7. Build, back up, migrate, and verify live behavior.