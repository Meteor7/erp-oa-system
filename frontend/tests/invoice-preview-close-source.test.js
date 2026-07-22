import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const preview = readFileSync(new URL("../src/components/invoice/InvoicePreviewDrawer.vue", import.meta.url), "utf8");
const upload = readFileSync(new URL("../src/components/invoice/InvoiceUploadWorkbench.vue", import.meta.url), "utf8");
const expense = readFileSync(new URL("../src/components/ExpenseWorkbench.vue", import.meta.url), "utf8");

test("invoice preview is explicitly opened and closes to zero dialogs", () => {
  assert.match(preview, /open:\s*\{\s*type:\s*Boolean,\s*default:\s*false\s*\}/);
  assert.ok(preview.includes("v-if=\"open && invoiceName\""));
  assert.ok(upload.includes(":open=\"Boolean(previewRow)\""));
  assert.ok(expense.includes(":open=\"Boolean(previewInvoiceRow)\""));
});
