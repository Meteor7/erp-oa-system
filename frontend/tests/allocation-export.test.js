import assert from "node:assert/strict";
import test from "node:test";

import { allocationExportFilename, buildAllocationExportSheets } from "../src/lib/allocationExport.js";

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
