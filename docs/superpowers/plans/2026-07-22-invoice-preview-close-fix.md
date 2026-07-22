# Invoice Preview Close Fix Implementation Plan 
 
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. 
 
**Goal:** Make the invoice preview drawer render once and close completely. 
 
**Architecture:** Parent workbenches own the selected invoice and derive an explicit Boolean open state. The drawer also refuses to render without a valid invoice name. 
 
**Tech Stack:** Vue 3, Node test runner, Vite, Frappe Docker deployment 
 
## Global Constraints 
 
- No database or invoice data changes. 
- Commit only to feat/invoice-ocr-reimbursement. 
- Deploy frontend assets after tests and build succeed. 
 
--- 

### Task 1: Lock the drawer lifecycle contract 
 
**Files:** 
- Modify: frontend/tests/invoice-ocr-source.test.js 
- Modify: frontend/src/components/invoice/InvoicePreviewDrawer.vue 
- Modify: frontend/src/components/invoice/InvoiceUploadWorkbench.vue 
- Modify: frontend/src/components/ExpenseWorkbench.vue 
 
**Interfaces:** 
- Consumes: selected invoice refs previewRow and previewInvoiceRow. 
- Produces: one visible dialog while selected and zero dialogs after close. 
 
- [ ] **Step 1: Write the failing test** 
 
Assert that the drawer defaults open to false, requires invoiceName in its render guard, and both parents bind open to Boolean of their selected invoice. 
 
- [ ] **Step 2: Run the focused test and verify RED** 

Run the invoice OCR source test. Expected failure: current drawer defaults open to true and parents do not bind open. 
 
- [ ] **Step 3: Implement the minimal lifecycle fix** 
 
Set default open to false, render with open and invoiceName, and add explicit open bindings in both parents. 
 
- [ ] **Step 4: Verify GREEN and regression safety** 
 
Run the focused test, all frontend tests, and the Vite production build. Expected: zero failures and successful build. 
 
- [ ] **Step 5: Deploy and verify live behavior** 
 
Build inside the Frappe container, clear cache, restart the service, open one invoice, confirm exactly one dialog, click Close, and confirm zero dialogs. 
 
- [ ] **Step 6: Commit** 
 
Commit message: fix: close invoice preview drawer
