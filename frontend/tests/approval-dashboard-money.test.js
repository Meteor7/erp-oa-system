// PMC / 生产主管不见金额（审查 #79 追加）：申请看板的 PO 总额只给能看金额的人。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the approval dashboard shows PO amounts only to people who may see money", () => {
  const page = readFileSync(new URL("../src/pages/ApprovalDashboard.vue", import.meta.url), "utf8");
  assert.match(page, /<template v-if="data\.can_view_financial"> · PO总额 \{\{ money\(row\.po_total_amount\) \}\}<\/template>/);
  assert.doesNotMatch(page, /<div v-else>\{\{ row\.po_status \|\| '-' \}\} · PO总额/);
});
