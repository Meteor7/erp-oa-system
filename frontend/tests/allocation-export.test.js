import assert from "node:assert/strict";
import test from "node:test";

import {
  allocationExportFilename,
  allocationExportLabel,
  buildAllocationExportSheets,
  buildAllocationInfoRows,
  exportTimestamp,
} from "../src/lib/allocationExport.js";

const columns = [
  { fieldname: "period", label: "\u65e5\u671f" },
  { fieldname: "voucher_no", label: "\u51ed\u8bc1\u7f16\u53f7" },
  { fieldname: "account_level_3", label: "3\u7ea7\u8d39\u7528\u79d1\u76ee" },
  { fieldname: "account_level_4", label: "4\u7ea7\u8d39\u7528\u79d1\u76ee" },
  { fieldname: "project_1", label: "RD06", fieldtype: "Currency", project_stage: "capitalized" },
  { fieldname: "project_2", label: "RD15", fieldtype: "Currency", project_stage: "expensed" },
];

const result = [
  { period: "2026-06", voucher_no: "118", account_level_3: "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09", account_level_4: "\u517b\u8001\u4fdd\u9669", project_1: 10, project_2: 20 },
  { _is_total: 1, period: "", voucher_no: "", account_level_3: "\u9879\u76ee\u6c47\u603b", account_level_4: "", project_1: 10, project_2: 20 },
];

test("builds allocation export sheets for totals, full matrix, and stage matrices", () => {
  const sheets = buildAllocationExportSheets({
    period: "2026-06",
    summary: { capitalized: 100, expensed: 200, unknown: 0 },
    columns,
    result,
  });

  assert.deepEqual(sheets.stageTotals, [
    ["\u4f1a\u8ba1\u671f\u95f4", "\u7c7b\u578b", "\u91d1\u989d"],
    ["2026-06", "\u8d44\u672c\u5316\u5408\u8ba1", 100],
    ["2026-06", "\u8d39\u7528\u5316\u5408\u8ba1", 200],
    ["2026-06", "\u8d44\u672c\u548c\u8d39\u7528\u5408\u8ba1", 300],
    ["2026-06", "\u672a\u5224\u5b9a\u5408\u8ba1", 0],
    // 阶段合计 300，明细只有 30：多出一行未对账差额（审查 X2-11-A）。
    ["2026-06", "\u672a\u5bf9\u8d26\u5dee\u989d\uff08\u9636\u6bb5\u5408\u8ba1\u2212\u5206\u644a\u660e\u7ec6\uff09", 270],
  ]);
  assert.equal("projectSummary" in sheets, false);
  assert.deepEqual(sheets.matrix, [
    ["\u65e5\u671f", "\u51ed\u8bc1\u7f16\u53f7", "3\u7ea7\u8d39\u7528\u79d1\u76ee", "4\u7ea7\u8d39\u7528\u79d1\u76ee", "RD06", "RD15"],
    ["2026-06", "118", "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09", "\u517b\u8001\u4fdd\u9669", 10, 20],
    ["", "", "\u9879\u76ee\u6c47\u603b", "", 10, 20],
  ]);
  assert.deepEqual(sheets.capitalizedMatrix, [
    ["\u65e5\u671f", "\u51ed\u8bc1\u7f16\u53f7", "3\u7ea7\u8d39\u7528\u79d1\u76ee", "4\u7ea7\u8d39\u7528\u79d1\u76ee", "RD06"],
    ["2026-06", "118", "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09", "\u517b\u8001\u4fdd\u9669", 10],
    ["", "", "\u9879\u76ee\u6c47\u603b", "", 10],
  ]);
  assert.deepEqual(sheets.expensedMatrix, [
    ["\u65e5\u671f", "\u51ed\u8bc1\u7f16\u53f7", "3\u7ea7\u8d39\u7528\u79d1\u76ee", "4\u7ea7\u8d39\u7528\u79d1\u76ee", "RD15"],
    ["2026-06", "118", "\u793e\u4f1a\u4fdd\u9669\u8d39\u7528\uff08\u5355\u4f4d\uff09", "\u517b\u8001\u4fdd\u9669", 20],
    ["", "", "\u9879\u76ee\u6c47\u603b", "", 20],
  ]);
});

test("allocation export filename includes selected period or year label", () => {
  assert.equal(allocationExportFilename("2026-06"), "\u7814\u53d1\u8d39\u7528\u53f0\u8d26-2026-06.xlsx");
  assert.equal(allocationExportFilename("2026\u5e74"), "\u7814\u53d1\u8d39\u7528\u53f0\u8d26-2026\u5e74.xlsx");
});

test("stage export recalculates each row total from the visible project columns", () => {
  const columnsWithTotal = [
    ...columns,
    { fieldname: "row_total", label: "\u6c47\u603b", fieldtype: "Currency" },
  ];
  const resultWithTotal = result.map((row) => ({ ...row, row_total: Number(row.project_1 || 0) + Number(row.project_2 || 0) }));

  const sheets = buildAllocationExportSheets({ columns: columnsWithTotal, result: resultWithTotal });

  assert.deepEqual(sheets.capitalizedMatrix[0].slice(-2), ["RD06", "\u6c47\u603b"]);
  assert.equal(sheets.capitalizedMatrix[1].at(-1), 10);
  assert.deepEqual(sheets.expensedMatrix[0].slice(-2), ["RD15", "\u6c47\u603b"]);
  assert.equal(sheets.expensedMatrix[1].at(-1), 20);
});

test("annual stage sheets use independently filtered matrices when one project changes stage", () => {
  const combinedColumns = [
    { fieldname: "period", label: "\u65e5\u671f" },
    { fieldname: "project_1", label: "RD01", fieldtype: "Currency", project: "RD01", project_stage: "capitalized" },
    { fieldname: "row_total", label: "\u6c47\u603b", fieldtype: "Currency" },
  ];
  const combinedResult = [
    { period: "2026-01", project_1: 100, row_total: 100 },
    { period: "2026-02", project_1: 50, row_total: 50 },
  ];
  const capitalizedResult = [
    { period: "2026-01", project_1: 100, row_total: 100 },
  ];
  const expensedColumns = [
    { fieldname: "period", label: "\u65e5\u671f" },
    { fieldname: "project_1", label: "RD01", fieldtype: "Currency", project: "RD01", project_stage: "expensed" },
    { fieldname: "row_total", label: "\u6c47\u603b", fieldtype: "Currency" },
  ];
  const expensedResult = [
    { period: "2026-02", project_1: 50, row_total: 50 },
  ];

  const sheets = buildAllocationExportSheets({
    period: "2026\u5e74",
    summary: { capitalized: 100, expensed: 50, unknown: 0 },
    columns: combinedColumns,
    result: combinedResult,
    stageMatrices: {
      all: { columns: combinedColumns, result: combinedResult },
      capitalized: { columns: combinedColumns, result: capitalizedResult },
      expensed: { columns: expensedColumns, result: expensedResult },
    },
  });

  assert.deepEqual(sheets.matrix, [
    ["\u65e5\u671f", "RD01", "\u6c47\u603b"],
    ["2026-01", 100, 100],
    ["2026-02", 50, 50],
  ]);
  assert.deepEqual(sheets.capitalizedMatrix, [
    ["\u65e5\u671f", "RD01", "\u6c47\u603b"],
    ["2026-01", 100, 100],
  ]);
  assert.deepEqual(sheets.expensedMatrix, [
    ["\u65e5\u671f", "RD01", "\u6c47\u603b"],
    ["2026-02", 50, 50],
  ]);
});


test("stage totals that match the matrix add no reconciliation row", () => {
  const sheets = buildAllocationExportSheets({
    period: "2026-06",
    summary: { capitalized: 10, expensed: 20, unknown: 0 },
    columns,
    result,
  });
  assert.equal(sheets.stageTotals.length, 5);
});

// ---- 项目名称列头、定版/预览标记、导出信息（2026-10） ----

const namedColumns = [
  { fieldname: "period", label: "日期" },
  { fieldname: "voucher_no", label: "凭证号" },
  { fieldname: "account_level_3", label: "3级费用科目" },
  { fieldname: "account_level_4", label: "4级费用科目" },
  { fieldname: "project_1", label: "RD13", fieldtype: "Currency", project: "RD13", project_code: "RD13", project_name: "KIBO 5895H", project_stage: "expensed" },
  { fieldname: "project_2", label: "RD15", fieldtype: "Currency", project: "RD15", project_code: "RD15", project_name: "RD15", project_stage: "capitalized" },
  { fieldname: "project_3", label: "未分摊境外公共费用", fieldtype: "Currency", project: "未分摊境外公共费用", project_code: "未分摊境外公共费用", project_name: "未分摊境外公共费用", project_stage: "unknown" },
  { fieldname: "row_total", label: "汇总", fieldtype: "Currency" },
];
const namedResult = [
  { period: "2026-06", voucher_no: "118", account_level_3: "差旅费", account_level_4: "", project_1: 10, project_2: 20, project_3: 5, row_total: 35 },
];

test("export matrix header carries the project name in one header row, so the sheet stays machine-readable", () => {
  const sheets = buildAllocationExportSheets({
    period: "2026-06", summary: { capitalized: 20, expensed: 10, unknown: 5 }, columns: namedColumns, result: namedResult,
  });

  assert.deepEqual(sheets.matrix[0], [
    "日期", "凭证号", "3级费用科目", "4级费用科目", "RD13 KIBO 5895H", "RD15", "未分摊境外公共费用", "汇总",
  ]);
  // 仍然只有一行表头：第二行是数据
  assert.deepEqual(sheets.matrix[1], ["2026-06", "118", "差旅费", "", 10, 20, 5, 35]);
  assert.equal(sheets.matrix.length, 2);
  // 按阶段拆开的两张表同样带名称，数据列不变
  assert.deepEqual(sheets.expensedMatrix[0].slice(-2), ["RD13 KIBO 5895H", "汇总"]);
  assert.equal(sheets.expensedMatrix[1].at(-2), 10);
  assert.deepEqual(sheets.capitalizedMatrix[0].slice(-2), ["RD15", "汇总"]);
});

test("export header uses the project code when the project key differs, and falls back to the label for old columns", () => {
  const sheets = buildAllocationExportSheets({
    columns: [
      { fieldname: "voucher_no", label: "凭证号" },
      { fieldname: "project_1", label: "PROJ-0001", fieldtype: "Currency", project: "PROJ-0001", project_code: "RD13", project_name: "KIBO 5895H", project_stage: "expensed" },
      { fieldname: "project_2", label: "RD06", fieldtype: "Currency", project_stage: "capitalized" },
    ],
    result: [],
  });

  assert.deepEqual(sheets.matrix[0], ["凭证号", "RD13 KIBO 5895H", "RD06"]);
});

test("export label marks a finalized allocation with who finalized it, and a preview as preview", () => {
  assert.equal(
    allocationExportLabel({ period: "2026-06", state: "finalized", finalizedByName: "演示员工16", modeLabel: "汇总" }),
    "2026-06-已定版-演示员工16-汇总",
  );
  assert.equal(allocationExportLabel({ period: "2026-06", state: "finalized", modeLabel: "资本化" }), "2026-06-已定版-资本化");
  assert.equal(allocationExportLabel({ period: "2026-06", state: "preview", modeLabel: "汇总" }), "2026-06-预览-汇总");
  assert.equal(allocationExportLabel({ period: "2026-06", state: "preview-error", modeLabel: "费用化" }), "2026-06-预览-费用化");
  // 年度汇总不加定版/预览标记
  assert.equal(allocationExportLabel({ period: "2026年", state: "year", modeLabel: "汇总" }), "2026年-汇总");
  assert.equal(allocationExportLabel({ period: "2026-06" }), "2026-06");
});

test("export filename keeps the prefix, carries the label and drops characters Windows file names cannot hold", () => {
  assert.equal(
    allocationExportFilename(allocationExportLabel({ period: "2026-06", state: "finalized", finalizedByName: "演示员工16", modeLabel: "汇总" })),
    "研发费用台账-2026-06-已定版-演示员工16-汇总.xlsx",
  );
  assert.equal(
    allocationExportFilename(allocationExportLabel({ period: "2026-06", state: "preview", modeLabel: "汇总" })),
    "研发费用台账-2026-06-预览-汇总.xlsx",
  );
  assert.equal(
    allocationExportFilename(allocationExportLabel({ period: "2026-06", state: "finalized", finalizedByName: 'a/b:c*"d', modeLabel: "汇总" })),
    "研发费用台账-2026-06-已定版-a_b_c_d-汇总.xlsx",
  );
});

test("export info rows list period, status, finalizer and time for a finalized month", () => {
  assert.deepEqual(
    buildAllocationInfoRows({
      period: "2026-06", state: "finalized", allocationName: "ALLOC-1", finalizedBy: "演示员工16",
      finalizedOn: "2026-10-08 15:20:33.500000", modeLabel: "汇总", exportedAt: "2026-10-09 09:00:00",
    }),
    [
      ["项目", "内容"],
      ["会计期间", "2026-06"],
      ["状态", "已定版"],
      ["分摊单", "ALLOC-1"],
      ["定版人", "演示员工16"],
      ["定版时间", "2026-10-08 15:20:33"],
      ["口径", "汇总"],
      ["导出时间", "2026-10-09 09:00:00"],
    ],
  );
});

test("export info rows of a preview say it is a preview and show the last revoke", () => {
  const rows = buildAllocationInfoRows({
    period: "2026-06", state: "preview", modeLabel: "费用化", exportedAt: "2026-10-09 09:00:00",
    lastRevoke: { by: "zhangmeng@example.com", by_name: "演示员工16", on: "2026-10-08 15:20:33", reason: "补录一笔费用" },
  });

  assert.deepEqual(rows, [
    ["项目", "内容"],
    ["会计期间", "2026-06"],
    ["状态", "预览（未定版，数字会随费用和工时变化）"],
    ["上次撤销", "演示员工16 2026-10-08 15:20:33"],
    ["撤销原因", "补录一笔费用"],
    ["口径", "费用化"],
    ["导出时间", "2026-10-09 09:00:00"],
  ]);
  // 没有撤销记录就没有这两行；年度汇总有自己的状态说明
  const plain = buildAllocationInfoRows({ period: "2026-06", state: "preview" });
  assert.equal(plain.some((row) => row[0] === "上次撤销"), false);
  assert.equal(buildAllocationInfoRows({ period: "2026年", state: "year" })[2][1].startsWith("年度汇总"), true);
});

test("export timestamp is a local YYYY-MM-DD HH:mm:ss string", () => {
  assert.equal(exportTimestamp(new Date(2026, 9, 8, 5, 4, 3)), "2026-10-08 05:04:03");
  assert.match(exportTimestamp(), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
});