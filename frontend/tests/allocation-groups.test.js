import assert from "node:assert/strict";
import test from "node:test";

import {
  groupAllocationRows,
  projectAmountTotals,
  rankProjects,
  stageLabel,
} from "../src/lib/allocationGroups.js";
import { allocationReconcileDifference } from "../src/lib/allocationExport.js";

const columns = [
  { fieldname: "period", label: "日期", fieldtype: "Data" },
  { fieldname: "voucher_no", label: "Voucher No", fieldtype: "Data" },
  { fieldname: "account_level_3", label: "3级费用科目", fieldtype: "Data" },
  { fieldname: "account_level_4", label: "4级费用科目", fieldtype: "Data" },
  { fieldname: "project_1", label: "RD01", fieldtype: "Currency", project: "RD01", project_stage: "capitalized" },
  { fieldname: "project_2", label: "RD02", fieldtype: "Currency", project: "RD02", project_stage: "expensed" },
  { fieldname: "row_total", label: "汇总", fieldtype: "Currency" },
];

const result = [
  { period: "2026-06", voucher_no: "1", account_level_3: "工资", account_level_4: "基本工资", project_1: 10, project_2: 20, row_total: 30 },
  { period: "2026-06", voucher_no: "2", account_level_3: "社保", account_level_4: "养老", project_1: 1.25, project_2: 0, row_total: 1.25 },
  { period: "2026-06", voucher_no: "3", account_level_3: "工资", account_level_4: "奖金", project_1: 5, project_2: 5, row_total: 10 },
  { _is_total: 1, account_level_3: "项目汇总", project_1: 16.25, project_2: 25, row_total: 41.25 },
];

test("matrix rows are grouped by level-3 account in first-seen order with subtotals", () => {
  const view = groupAllocationRows({ columns, result });
  assert.equal(view.grouped, true);
  assert.deepEqual(view.groups.map((group) => group.label), ["工资", "社保"]);
  assert.equal(view.groups[0].rows.length, 2);
  assert.deepEqual(view.groups[0].totals, { project_1: 15, project_2: 25, row_total: 40 });
  assert.deepEqual(view.groups[1].totals, { project_1: 1.25, project_2: 0, row_total: 1.25 });
  assert.equal(view.totalRow, result[3]);
  assert.deepEqual(view.moneyKeys, ["project_1", "project_2", "row_total"]);
});

test("the report's own total row is never put into a group", () => {
  const view = groupAllocationRows({ columns, result });
  const grouped = view.groups.flatMap((group) => group.rows);
  assert.equal(grouped.includes(result[3]), false);
  assert.equal(grouped.length, 3);
});

test("without a level-3 column the rows stay flat in one header-less group", () => {
  const flatColumns = columns.filter((column) => column.fieldname !== "account_level_3");
  const view = groupAllocationRows({ columns: flatColumns, result });
  assert.equal(view.grouped, false);
  assert.equal(view.groups.length, 1);
  assert.equal(view.groups[0].rows.length, 3);
});

test("empty matrix produces no groups and no total row", () => {
  const view = groupAllocationRows({ columns, result: [] });
  assert.deepEqual(view.groups, []);
  assert.equal(view.totalRow, null);
  assert.deepEqual(groupAllocationRows(), { grouped: false, groups: [], totalRow: null, moneyKeys: [] });
});

test("rows without a level-3 name fall into one unnamed group", () => {
  const view = groupAllocationRows({
    columns,
    result: [{ account_level_3: "", project_1: 2 }, { project_1: 3 }],
  });
  assert.equal(view.groups.length, 1);
  assert.equal(view.groups[0].label, "");
  assert.equal(view.groups[0].totals.project_1, 5);
});

test("stage labels are Chinese and unknown stages are blank", () => {
  assert.equal(stageLabel("capitalized"), "资本化");
  assert.equal(stageLabel("expensed"), "费用化");
  assert.equal(stageLabel("unknown"), "未判定");
  assert.equal(stageLabel(undefined), "");
});

test("reconcile difference is stage totals minus the matrix detail total", () => {
  const detail = [
    { project_1: 10, project_2: 20 },
    { _is_total: 1, project_1: 10, project_2: 20 },
  ];
  assert.equal(allocationReconcileDifference({ summary: { capitalized: 100, expensed: 200, unknown: 0 }, columns, result: detail }), 270);
  assert.equal(allocationReconcileDifference({ summary: { capitalized: 10, expensed: 20, unknown: 0 }, columns, result: detail }), 0);
  assert.equal(allocationReconcileDifference({ summary: { capitalized: 10, expensed: 20, unknown: 1.234 }, columns, result: detail }), 1.23);
});

test("reconcile difference is null when there is no matrix detail to reconcile", () => {
  assert.equal(allocationReconcileDifference({ summary: { capitalized: 1 }, columns, result: [] }), null);
  assert.equal(allocationReconcileDifference({ summary: { capitalized: 1 }, columns }), null);
});

const dashboardColumns = Array.from({ length: 10 }, (_, i) => ({
  project: `P${i + 1}`,
  project_code: `RD${String(i + 1).padStart(2, "0")}`,
  project_name: `项目${i + 1}`,
}));
const dashboardRows = [
  { row_type: "detail", account_level_2: "A", account_level_3: "x", projects: { P1: 1, P2: 2 }, total: 3 },
  { row_type: "subtotal", account_level_2: "A", projects: { P1: 1, P2: 2 }, total: 3 },
  {
    row_type: "grand_total",
    account_level_1: "合计",
    projects: Object.fromEntries(dashboardColumns.map((column, i) => [column.project, (i + 1) * 100])),
    total: 5500,
  },
];

test("project amounts come from the grand total row, falling back to the detail rows", () => {
  assert.equal(projectAmountTotals(dashboardRows).P10, 1000);
  assert.deepEqual(projectAmountTotals(dashboardRows.slice(0, 2)), { P1: 1, P2: 2 });
  assert.deepEqual(projectAmountTotals([]), {});
});

test("ranking keeps the top 8 by amount and merges the rest into 其他", () => {
  const ranking = rankProjects({ rows: dashboardRows, projectColumns: dashboardColumns, topN: 8 });
  assert.equal(ranking.total, 5500);
  assert.equal(ranking.items.length, 9);
  assert.deepEqual(ranking.items.slice(0, 3).map((item) => item.code), ["RD10", "RD09", "RD08"]);
  const other = ranking.items.at(-1);
  assert.equal(other.code, "其他");
  assert.equal(other.isOther, true);
  assert.equal(other.value, 300);
  assert.equal(other.name, "2 个项目");
  assert.equal(ranking.items[0].width, 100);
  assert.ok(Math.abs(ranking.items[0].share - 1000 / 5500) < 1e-9);
  assert.ok(Math.abs(ranking.items.reduce((sum, item) => sum + item.share, 0) - 1) < 1e-9);
});

test("ranking has no 其他 entry when the projects fit and skips zero-amount projects", () => {
  const ranking = rankProjects({
    rows: [{ row_type: "grand_total", projects: { P1: 5, P2: 0, P3: 15 } }],
    projectColumns: dashboardColumns.slice(0, 3),
    topN: 8,
  });
  assert.deepEqual(ranking.items.map((item) => item.code), ["RD03", "RD01"]);
  assert.equal(ranking.items.some((item) => item.isOther), false);
});

test("ranking of an empty dashboard is empty", () => {
  assert.deepEqual(rankProjects({ rows: [], projectColumns: [] }), { total: 0, items: [] });
  assert.deepEqual(rankProjects(), { total: 0, items: [] });
});
