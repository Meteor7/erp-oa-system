# Expense Reimbursement Dynamic Approval Design

Date: 2026-07-23
Branch: `feat/ocr-monthly-timesheet-integration`
Status: user-approved design

## 1. Objective

Extend the existing Frappe expense reimbursement workbench without migrating existing requests to another workflow engine. Frontend, backend, DocTypes, permissions, audit data, and deployed assets must remain synchronized.

The change covers:

1. Derive a missing invoice total from amount-before-tax plus tax.
2. Allow employee submission with a blank expense item, while requiring Finance to classify every line at Finance approval.
3. Add a required employee-entered expense description and optional multiple private attachments per expense line.
4. Add explicit approve, targeted reject, and dynamic add-sign actions.
5. Repair blocked PDF invoice preview without weakening private-file authorization.

Invoice authenticity verification and external OCR APIs remain out of scope.

## 2. Chosen Approach

Enhance the current `OA Approval Request`, expense-line, approval-step, and invoice-preview implementation in place.

This is safer than migrating to Frappe Workflow because live requests already store route instances in `OA Approval Step`, and dynamic before/after add-sign plus targeted rejection is simpler in the existing transaction model. A separate workflow engine would be unnecessary at the current scale.

Existing requests and invoices remain valid. New fields are nullable and migration is idempotent.

## 3. Confirmed Business Rules

### 3.1 Amount derivation

- When `total_amount` is blank and both `amount_before_tax` and `tax_amount` are present, derive `round(amount_before_tax + tax_amount, 2)`.
- The frontend shows the derived value immediately and the backend repeats derivation before persistence and request-total calculation.
- A supplied total is not silently overwritten.
- If all three values are supplied and differ by more than CNY 0.02, confirmation is blocked until corrected or handled by existing invoice review.
- A document with only one valid total, such as a railway ticket, keeps that value as the after-tax total.
- Existing invoice rows with blank total and complete components receive an idempotent backfill.

### 3.2 Expense item ownership

- `expense_item` is optional in employee draft/pending-submission state.
- An employee may suggest a value but is not required to do so.
- At the first active Finance audit node, Finance can select or replace each line value.
- Finance cannot approve until every expense line has a nonblank valid expense item.
- Later nodes see it read-only.
- The backend enforces this rule; frontend visibility is not authorization.

### 3.3 Description and attachments

- Every expense line has a required `expense_description` entered by the employee before submission.
- Supplemental attachments are optional.
- Each line can contain multiple private PDF, JPG, JPEG, or PNG files.
- Each file is at most 10 MB; each line is limited to 10 supplemental files.
- Original invoice files remain separate and retain invoice-preview permissions.
- Draft owners can upload/delete supplemental attachments in a new draft or after rejection to applicant.
- Approvers can view but cannot delete employee attachments.
- Attachment access is granted only through related request and line permission checks.
- Manual no-invoice lines still require a no-invoice reason.

## 4. Workflow State Model

### 4.1 Stable step identity

Approval steps receive a stable `step_key`. Sequence numbers become display/order data rather than identity. Each step also records:

- `origin`: base route or add-sign
- `added_by` and `added_on`
- `add_sign_position`: before or after
- `add_sign_opinion`
- `parent_step_key`

Existing steps receive deterministic migration keys from request name and original index.

### 4.2 Approve

- Only a matched approver for the current active step may approve.
- Finance audit approval also validates all expense items.
- Approval remains idempotent for each actor in `all` mode.
- The route advances atomically.

### 4.3 Targeted rejection

Rejection requires a reason and explicit target. Allowed targets are applicant/pending-submission or any earlier completed step.

- Reject to applicant: request becomes applicant-editable draft; all base and add-sign steps reset and the route instance is retained.
- Reject to an earlier step: target and all later steps reset; earlier completed steps remain complete.
- The target becomes current unless it is the applicant.
- Future, current, missing, unauthorized, or ineligible targets are rejected by backend validation.
- Audit records actor, time, source, target, and reason.

### 4.4 Add-sign

The current approver can add an enabled employee/user before or after the current step. Opinion is required.

- Before: new step becomes current; original approver acts after it completes.
- After: original approver remains current; the new approver follows after approval.
- Added approvers may approve, reject, or add-sign again.
- Self add-sign is forbidden.
- A person cannot be duplicated in the unresolved chain.
- A request allows at most 20 add-sign operations.
- Insertion, reindexing, pointer changes, and audit logging use one request transaction lock.

## 5. Data Model

### 5.1 `OA Approval Expense Line`

Add `expense_description` (`Small Text`, nullable for migration, required at submission). Serialization prefers it and falls back to legacy `description`; new writes keep both coherent during compatibility.

### 5.2 `OA Expense Line Attachment`

Create a DocType/reference record with:

- request link
- immutable expense `line_key`
- private File link/URL
- original filename
- MIME type
- file size
- uploaded by/on

A request/file uniqueness guard prevents duplicate registration. Files remain private and attached to the request.

### 5.3 `OA Approval Step`

Add stable and add-sign metadata from section 4.1. Existing status and action fields remain compatible.

### 5.4 Operation log

Add structured events for amount derivation/backfill, Finance classification, attachment changes, approve, targeted rejection, add-sign, and resubmission. Existing log limits remain.

## 6. API Contract

All writes are authenticated POST endpoints and re-check permissions/current state under a transaction lock.

### 6.1 Existing APIs extended

- `list_requests` returns descriptions, attachment metadata/counts, stable step/add-sign data, capability booleans, and backend-computed rejection targets.
- `save_draft_expense_sources` accepts descriptions and no longer requires employee expense items.
- `submit_request` requires descriptions but permits blank expense items.
- `action_request` keeps current approve compatibility. Reject requires `reject_target` and reason; old reject calls fail safely rather than terminally rejecting.

### 6.2 New APIs

- `save_finance_expense_items(name, lines)`: active Finance audit approver only; line keys only; cannot alter invoice amounts, sources, or employee descriptions.
- `add_sign_request(name, approver, position, opinion)`: current approver only; validates identity, no self/duplicate, and the 20-operation limit.
- `upload_expense_attachment(name, line_key, file_url)`: draft applicant only; validates private File ownership, extension, MIME signature, size, and line membership.
- `delete_expense_attachment(name, attachment)`: draft applicant only; validates request/line/file ownership.
- `preview_expense_attachment(attachment)`: same one-time-token pattern as invoice preview.

The frontend never invents eligible targets or permissions.

## 7. Frontend Design

### 7.1 Pending submission

Each grouped row shows seven invoice fields, optional expense item, required expense description, original invoice preview, and supplemental attachment list/upload. Blank expense item shows `Finance will classify`, not an employee blocker. Missing description is visibly required.

### 7.2 Finance approval

At the active Finance audit node, expense item becomes editable. A dedicated save persists values. Approve remains disabled until backend readiness is true. Other content is read-only.

### 7.3 Approval actions

The action bar renders from backend capabilities: Approve, Reject, Add-sign. Reject dialog shows eligible targets and requires a reason. Add-sign dialog provides people search, before/after, required opinion, and remaining count. The timeline distinguishes base/add-sign steps and shows source, position, opinion, result, and rejection path.

## 8. Invoice Preview Root Cause and Design

Live reproduction on 2026-07-23 established:

- `preview_invoice` returned HTTP 200.
- `serve_invoice_preview` returned HTTP 200.
- Stored files have valid PDF/PNG/JPEG signatures, not a TipRay TSD header.
- Chrome rendered `This page has been blocked by Chrome` in `iframe[title="Invoice PDF preview"]`.
- The iframe had `sandbox` and used a same-page blob URL.

Therefore this is not caused by the TipRay whitelist. The whitelist affects whether a local encrypted upload reaches the server as plaintext; it does not block a valid private PDF after both preview APIs succeed.

Repair:

- keep private authorization and one-time POST tokens;
- render PDF bytes in-app with a locally bundled pinned renderer in worker/canvas, not a sandboxed browser PDF plugin;
- keep images on the blob/image path;
- retain watermarking and release resources on close;
- support page navigation and clear loading/error states;
- use no external API and expose no direct private-file URL.

## 9. Security and Concurrency

- Identities and roles come only from Frappe session state.
- Approver choices resolve to enabled users/employees; no free-text identity is accepted.
- Request, step, line, and attachment relationships are verified server-side.
- Files are validated by content signature, not filename alone.
- Amounts use decimal/cents-safe arithmetic.
- Mutations use current-row request locks.
- Duplicate clicks cannot skip steps.
- Actions cannot use stale current-step keys.
- Logs never include file contents or tokens.

## 10. Error Handling

- Validation identifies exact line/workflow constraints.
- Failed attachment registration cleans an unclaimed temporary upload when safe.
- Stale actions return controlled refresh guidance.
- Preview errors remain in the drawer without backend traces.
- Migration/backfill are idempotent and log only counts.

## 11. Test Strategy

Implementation follows test-driven development.

Backend tests cover amount derivation/mismatch/backfill, employee blank expense items, required descriptions, Finance-only classification/blocking, attachment validation/permissions, targeted rejection, reset preservation, before/after and recursive add-sign, self/duplicate/limit checks, stale/concurrent actions, audit events, and legacy compatibility.

Frontend tests cover draft validation/derivation, role editability, attachment controls, reject/add-sign payloads, capability-driven buttons, timeline rendering, and PDF renderer lifecycle.

Browser verification covers draft, Finance approval, before/after add-sign, both rejection targets, PDF/image preview, attachment permissions, console errors, and overflow behavior.

## 12. Deployment and Rollback

1. Back up database and private files.
2. Run targeted and full backend tests, frontend tests, and production build.
3. Apply DocType migration and idempotent step-key/amount backfill.
4. Deploy backend and exact built assets together.
5. Clear cache and restart required services.
6. Run live browser smoke tests.

Rollback restores the pre-deployment database/private-file backup and prior code/assets together. New nullable fields require no destructive cleanup.
