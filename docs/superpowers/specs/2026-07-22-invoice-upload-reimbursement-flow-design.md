# Invoice Upload and Reimbursement Flow Design

**Date:** 2026-07-22
**Branch:** `feat/invoice-ocr-reimbursement`

## Goal

Replace the ambiguous “main/sub dashboard + consumption detail” interaction with two first-class workspaces:

1. **上传发票** — batch upload PDF/JPG/JPEG/PNG invoices, run local PaddleOCR, review and confirm seven extracted fields, detect duplicates, inspect the private source file, select invoices, and push them into reimbursement.
2. **费用报销流** — keep the current payment/reimbursement approval kanban, receive invoice data pushed from the upload workspace, support no-invoice manual drafts, display one seven-field row per invoice, and support controlled reversal.

No external OCR or invoice-authenticity API is introduced.

## Approved behavior

- The seven expense-detail fields are: 发票类别、项目名称、开票日期、发票号码、税前金额、税额、合计金额.
- After OCR review is confirmed, the confirmed values are the exact values used for pushdown.
- Selecting multiple invoices creates one reimbursement request; every selected invoice creates one independent expense-detail row.
- The request is created as a draft so the applicant can complete payment information before submitting approval.
- Manual no-invoice reimbursement remains available. It uses the same seven-column detail table and requires a no-invoice reason before submission.
- Existing legacy expense rows and database fields are retained for backward compatibility, but the new UI no longer exposes the old consumption-detail model.
- Invoice confirmation can be withdrawn only before pushdown.
- Pushdown can be withdrawn. If approval has started, the request is first withdrawn to draft, then selected invoice rows are released.
- A submitted, rejected, or completed request can be withdrawn to draft by its applicant or a privileged manager. Paid requests require finance to withdraw payment first.
- Withdrawal never deletes the private invoice file or prior request record. An operation log records actor, time, old state, new state, action, and note.

## Architecture

### Data model

Extend `OA Approval Expense Line` with the seven OCR fields and `source_invoice`. Keep `category`, `amount`, dates, and description for old records and reports. New invoice rows mirror the seven values while compatibility fields are derived from them.

Extend `OA Approval Request.source_type` with `发票下推` and add a read-only JSON operation log. Extend `OA Invoice Record` with a read-only JSON operation log.

### Backend

The invoice workbench lists records within the current user’s row-level scope. Pushdown locks selected invoice records in stable order, re-checks that every record is confirmed and unlinked, creates one draft request, appends one line per record, links each record to its stable line key, updates request invoice summaries, and returns the request.

Unconfirm, unpush, request withdrawal, and payment withdrawal are explicit POST actions with permission and state validation. Updates are transactional; a partial push must roll back.

### Frontend

`ExpenseWorkbench.vue` owns the reimbursement-flow kanban and manual no-invoice form. A focused `InvoiceUploadWorkbench.vue` owns batch upload, polling, review, confirmation, private preview, selection, pushdown, and unpush. Side navigation presents 上传发票 and 费用报销流 without main/sub labels.

The request form no longer contains invoice upload. Its expense table uses only the seven approved fields. Request detail uses the same seven-field layout and provides “查看发票” per row.

## Error handling and safety

- Only confirmed, non-duplicate, non-excluded invoices can be pushed.
- The same invoice cannot be pushed twice, including concurrent requests.
- Cross-batch selections are supported because records, not batches, are linked.
- Uploaded files remain private; preview remains POST-token controlled and audited.
- Existing requests are not migrated destructively. Serializer fallbacks display legacy category/date/description/amount in the new columns.
- Paid data cannot be altered by ordinary applicants.

## Verification

Automated tests cover schema compatibility, seven-field normalization/serialization, workbench scope, transactional pushdown, duplicate/concurrency rejection, unconfirm, unpush, request withdrawal, payment withdrawal, navigation copy, and seven-column rendering. Deployment verification covers upload, OCR, confirmation, push, request display, submission, withdrawal, unpush, and private preview on the live platform.
