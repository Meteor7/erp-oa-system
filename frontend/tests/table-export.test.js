import assert from "node:assert/strict";
import test from "node:test";

import { buildExportRows, normalizeExportFilename } from "../src/lib/tableExport.js";

test("table export maps row values to Chinese column labels", () => {
  const rows = buildExportRows(
    [{ code: "RD01", amount: 12.5 }],
    [
      { label: "项目代码", key: "code" },
      { label: "金额", value: (row) => row.amount },
    ],
  );

  assert.deepEqual(rows, [{ "项目代码": "RD01", "金额": 12.5 }]);
});

test("table export adds an xlsx suffix only when missing", () => {
  assert.equal(normalizeExportFilename("研发项目-2026-07"), "研发项目-2026-07.xlsx");
  assert.equal(normalizeExportFilename("研发项目.xlsx"), "研发项目.xlsx");
});
