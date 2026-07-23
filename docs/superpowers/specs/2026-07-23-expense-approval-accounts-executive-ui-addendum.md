# Expense Approval Accounts, Executive Access, and Detail UI Addendum

Date: 2026-07-23
Branch: `feat/ocr-monthly-timesheet-integration`
Status: approved for implementation

## 1. Objective

Complete the existing invoice reimbursement workflow by fixing real account-to-approver identity, granting approved business-wide authority without system-administration authority, migrating active approval steps safely, and rebuilding the reimbursement detail dialog into a clear approval workbench.

This addendum extends the approved dynamic expense approval design. It does not replace OCR, invoice, reimbursement, reporting, or audit data.

## 2. Approved permission model

The user selected business-highest access, not Frappe `System Manager` access.

Create a custom `Rayher Business Executive` role. Users with this role can view all Rayher business modules and requests, process any active OA approval node, classify expense items when acting at the Finance node, reject to an eligible earlier node, and add signers. They cannot change Frappe permissions, install apps, administer the server, or gain delete/cancel rights reserved for `System Manager`.

Assign the role to:

- Vice General Manager Li Qinggele through the existing `person046@business.example.invalid` account.
- General Manager Wang Bo through a new internal `person058@legacy.example.invalid` account.

Li Qinggele receives Employee, HR Manager, Accounts User, Department Manager, All Project Access, and Rayher Business Executive. Wang Bo receives the same business role bundle except Employee until a verified Employee record exists. Neither executive receives System Manager.

`admin@legacy-business.example.invalid` already has the existing `总控 Owner` role profile, including System Manager. The OA override check recognizes that existing System Manager role instead of trying to add a custom role that the Role Profile would immediately remove.

The framework `Administrator` account remains an emergency system account and also receives an OA action override in code, without changing its stored roles.

## 3. Finance accounts

Provision and link enabled System User accounts for all active Finance employees:

- Ye Liwei / `HR-EMP-90008` -> `person067@legacy.example.invalid`
- Yan Luying / `HR-EMP-90016` -> `person065@legacy.example.invalid`
- Zhang Meng / `HR-EMP-90007` -> `person072@legacy.example.invalid`

All three receive Employee and Accounts User. Zhang Meng also receives Department Manager. Existing employee data remains unchanged except the `user_id` link. Existing users are never overwritten.

New accounts receive cryptographically random temporary passwords during the explicit deployment command. Passwords are not stored in Git or source files. Existing account passwords are not changed.

There is currently no Employee record named Wang Bo. The new Wang Bo User is therefore created without inventing an Employee record. The executive role makes the account usable in the platform and approval flow. HR can link a verified Employee record later without changing the account name.

## 4. Approval identity and route rules

Future routes use stable User IDs in `approvers`; display labels continue to show Chinese names.

The canonical people are:

- Finance audit and Finance handling: Ye Liwei / `person067@legacy.example.invalid`
- Vice General Manager: Li Qinggele / `person046@business.example.invalid`
- General Manager: Wang Bo / `person058@legacy.example.invalid`

New leave routes are supervisor -> Vice General Manager -> General Manager.

New expense routes are Finance audit -> direct supervisor -> optional asset specialist -> executive approval -> Finance handling. Sales executive approval is an all-sign step for Li Qinggele and Wang Bo; other departments require Wang Bo unless already represented by the supervisor.

Department supervisors supplied as employee names are resolved to linked User IDs when possible. Unresolved names remain visible and are reported by diagnostics instead of creating guessed users.

## 5. Active-request migration

Only unresolved steps on active requests are migrated. Completed steps, approved-by history, operation logs, invoice links, expense lines, amounts, attachments, and paid requests are untouched.

Legacy identity mapping:

- Ye Liwei -> `person067@legacy.example.invalid`
- Ren Feifan vice-manager nodes -> Li Qinggele account
- Qing Bo general-manager nodes -> Wang Bo account
- Wang Bo nodes -> Wang Bo account
- Legacy joint `Qing Bo, Wang Bo` nodes -> joint Li Qinggele and Wang Bo accounts

Labels on unresolved steps are updated to the current names. The migration is idempotent and produces counts plus an unresolved-identity report before it commits.

## 6. Administrator and executive override behavior

A matched assigned approver remains the normal path. A Rayher Business Executive or framework Administrator may act on any current active step as an audited override.

- The actual session User is stored as `action_by` and in the operation log.
- An override completes the current step even when the step is `all` mode; it does not impersonate or write fake approvals for the assigned users.
- Override users may edit expense items only while the active node is Finance audit.
- Required expense classification and all existing validation still apply.
- An override cannot act on completed, paid, rejected, or stale steps.

## 7. Reimbursement detail workbench UI

Replace the 1500-pixel table dialog with one responsive workbench surface inside the existing design system.

- Sticky header: request number, subject, source, status, and close action.
- Summary strip: company, applicant, department, current node, total amount, and invoice count.
- Main content: one expense group per readable section. Each section shows project name, invoice category, issue date, invoice number, pre-tax amount, tax, total, expense description, invoice preview, and supplemental attachments without horizontal page scrolling.
- Finance classification: a highlighted, full-width expense-item control at the top of each group when editable; a clear read-only value otherwise.
- Workflow rail: compact approval timeline with current, completed, rejected, and add-sign states.
- Sticky footer: note input on the left; Close, Save classification, Add sign, Targeted reject, and Approve/Complete on the right. Buttons render only from backend capability flags.
- Desktop target: 1366x768 and larger. At narrower widths the summary and expense fields stack; no primary action or amount is clipped.

This is a targeted redesign inside the current Rayher UI, so it reuses existing colors, typography, button components, icons, spacing, and modal conventions instead of introducing a separate visual brand.

## 8. Backend/frontend contract

`list_requests` and request summaries return:

- `can_approve`, `can_reject`, `can_add_sign`, `can_edit_expense_items`
- `is_override_actor` and a display-safe `action_scope`
- current step identity, classification readiness, rejection targets, add-sign remaining count
- the stable User IDs and display labels required by the timeline

The frontend never infers authorization from visible roles or names. Every write endpoint rechecks the current request, active step, session identity, classification state, and transaction lock.

## 9. Verification and rollback

Tests cover role provisioning, employee linking, no System Manager on executives, future route IDs, active-step migration, exact override behavior, Finance classification visibility, all-mode override completion, and the responsive action workbench.

Before live mutation, create a database/private-files backup and run the migration in dry-run mode. Deploy backend, migration, and exact frontend build together. Browser acceptance must use admin, Finance, and at least one executive account and verify classification, approval, targeted rejection, add-sign, invoice preview, dialog close, and no horizontal overflow.

Rollback restores the pre-change database backup and prior code/assets together. Account provisioning and active-step migration are additive/idempotent; no business document is deleted.
