// 看板数字和点进去看到的对齐（财务 / 费用，决定 2026-10-13）：付款看板、发票夹这一侧。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { agingColumns, agingTiles, cashierSplit } from "../src/lib/expenseBoards.js";
import { FINANCE_FILTER_TABS, financeFilterTab, folderTabsFromCounts, tabStatuses } from "../src/lib/invoiceFolderView.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("付款看板的等待分段和数据看板一样：今天 / 1–3 天 / 超过 3 天（正好 3 天不算超过）", () => {
  const queue = [0, 1, 3, 4, 10].map((days) => ({ waited_days: days, amount: 10 }));
  assert.deepEqual(agingColumns(queue).map((column) => [column.label, column.value]), [["今天", 1], ["1–3 天", 2], ["超过 3 天", 2]]);
  assert.deepEqual(agingTiles([]).map((tile) => tile.label), ["今天", "1–3 天", "超过 3 天"]);
});

test("演示员工110待付款的标题只算待付款，待核验单独列在后面（和数据看板的演示员工110待付款一致）", () => {
  const rows = [{ name: "A", status: "待付款" }, { name: "V", status: "待核验" }, { name: "B", status: "待付款" }];
  const split = cashierSplit(rows);
  assert.deepEqual(split.toPay.map((row) => row.name), ["A", "B"]);
  assert.deepEqual(split.verifying.map((row) => row.name), ["V"]);
  assert.deepEqual(cashierSplit(), { toPay: [], verifying: [] });
  const page = read("../src/pages/PaymentBoard.vue");
  assert.match(page, /cashierSplit\(data\.value\.cashier_queue \|\| \[\]\)/);
  assert.match(page, /const queue = computed\(\(\) => split\.value\.toPay\)/);
  assert.match(page, /\{\{ queue\.length \}\} 张 · ¥ \{\{ money\(summary\.to_pay_amount\) \}\}/);
  assert.match(page, /v-for="row in tableRows"/);
  assert.match(page, /另有已付款待核验发票 \{\{ verifying\.length \}\} 张/);
});

test("发票夹：财务从看板点进来能按单个状态筛（待确认 / 识别失败），张数和看板一样", () => {
  assert.deepEqual(tabStatuses("confirm"), ["待确认"]);
  assert.deepEqual(tabStatuses("failed"), ["识别失败"]);
  assert.equal(financeFilterTab("confirm", true), "confirm");
  assert.equal(financeFilterTab(["failed"], true), "failed");
  assert.equal(financeFilterTab("confirm", false), "", "员工没有这两个筛选");
  assert.equal(financeFilterTab("allinv", true), "");
  const counts = { 待确认: 14, 识别失败: 2, 疑似重复: 1, 可用: 5 };
  // 平时财务只有三个页签；带着筛选进来时临时多一个，数量只算那一个状态
  assert.deepEqual(folderTabsFromCounts(counts, true).map((tab) => tab.key), ["dup", "allinv", "mine"]);
  const tabs = folderTabsFromCounts(counts, true, null, "confirm");
  assert.deepEqual(tabs.at(-1), { key: "confirm", label: FINANCE_FILTER_TABS.confirm, count: 14 });
  assert.equal(folderTabsFromCounts(counts, true, null, "failed").at(-1).count, 2);
  assert.equal(folderTabsFromCounts(counts, false, null, "confirm").some((tab) => tab.key === "confirm"), false);
  const page = read("../src/pages/InvoiceFolder.vue");
  assert.match(page, /if \(financeFilterTab\(route\.query\.tab, finance\)\) tab\.value = financeFilterTab\(route\.query\.tab, finance\);/);
  assert.match(page, /financeFilterTab\(nextTab, finance\) \|\| normalizeFolderTab\(nextTab, finance\)/);
  assert.match(page, /folderTabsFromCounts\(countsAll\.value \|\| counts\.value, finance, countsMine\.value, tab\.value\)/);
  // 筛选页签和“全部发票”一样是只读的财务视图
  assert.match(page, /const ownView = computed\(\(\) => !finance \|\| tab\.value === 'mine'\)/);
});
