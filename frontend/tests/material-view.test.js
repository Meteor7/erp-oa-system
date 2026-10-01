import assert from "node:assert/strict";
import test from "node:test";
import {
  CHECK_WIDTH, MATERIAL_COLUMNS, allStageCount, buildPrLines, cancelReasonProblem, cellValue, columnLabel, displayColumns,
  filterSortRows, groupDateText, groupRows, isEditableField, normalizedText, otherStatuses, parseClipboardMatrix,
  selectionBounds, selectionLabel, statusPill, stickyLeft,
} from "../src/lib/materialView.js";

const STAGES = ["OA审批中", "采购确认中", "PO处理中", "供应商制作中", "到货验收中", "付款中", "已关闭"];

test("the full column set keeps all 28 old columns and the compact set drops 本次 PR for everyone but PMC", () => {
  assert.equal(MATERIAL_COLUMNS.length, 28);
  assert.equal(displayColumns({ showAll: true, canCreatePr: true }).length, 28);
  assert.equal(displayColumns({ showAll: true, canCreatePr: false }).length, 27);
  const compactPmc = displayColumns({ canCreatePr: true }).map((column) => column.field);
  const compactView = displayColumns({ canCreatePr: false }).map((column) => column.field);
  assert.ok(compactPmc.includes("pr_create_quantity"));
  assert.ok(!compactView.includes("pr_create_quantity"));
  assert.equal(compactPmc[0], "material_serial", "OA 单号 moved into the group header");
  assert.ok(!compactPmc.includes("source_request"));
});

test("editable fields and labels", () => {
  for (const field of ["material_code", "item_name", "specification", "project", "unit", "quantity", "expected_delivery_date", "current_handler", "actual_delivery_date", "remarks"]) {
    assert.equal(isEditableField(field), true, field);
  }
  for (const field of ["progress_override", "pr_numbers", "supplier", "pr_create_quantity"]) assert.equal(isEditableField(field), false, field);
  assert.equal(columnLabel("quantity"), "OA 数量");
  assert.equal(columnLabel("nope"), "nope");
});

test("sticky offsets accumulate over the leading identity columns and leave room for the checkbox", () => {
  const compact = displayColumns({ canCreatePr: true });
  assert.deepEqual(stickyLeft(compact, true), { material_serial: CHECK_WIDTH, item_name: CHECK_WIDTH + 140 });
  assert.deepEqual(stickyLeft(compact, false), { material_serial: 0, item_name: 140 });
  const full = displayColumns({ showAll: true, canCreatePr: false });
  assert.deepEqual(stickyLeft(full, false), { source_request: 0, material_serial: 116, item_name: 256 });
});

test("cell values: status comes from progress_status and the per-line PR quantity defaults to what is still available", () => {
  const row = { name: "R1", progress_status: "采购确认中", pr_available_quantity: 5, quantity: 8, supplier: null };
  assert.equal(cellValue(row, "progress_override"), "采购确认中");
  assert.equal(cellValue(row, "pr_create_quantity"), "5");
  assert.equal(cellValue(row, "pr_create_quantity", { R1: 3 }), "3");
  assert.equal(cellValue(row, "supplier"), "");
  assert.equal(cellValue(row, "quantity"), "8");
  assert.equal(normalizedText("  a \n b  "), "a b");
});

test("status pills follow the colours of the other pages", () => {
  assert.equal(statusPill("OA审批中"), "pill p-cobalt");
  assert.equal(statusPill("付款中"), "pill p-cobalt");
  assert.equal(statusPill("采购确认中"), "pill p-sun");
  assert.equal(statusPill("供应商制作中"), "pill p-brand");
  assert.equal(statusPill("已关闭"), "pill p-jade");
  assert.equal(statusPill("已取消"), "pill p-gray");
  assert.equal(statusPill("换货中"), "pill p-red");
});

test("selection label explains why a row cannot go into a PR", () => {
  assert.equal(selectionLabel({ pr_eligible: 1 }), "可提 PR");
  assert.equal(selectionLabel({ pr_eligible: 0, progress_status: "OA审批中" }), "待审批");
  assert.equal(selectionLabel({ pr_eligible: 0, progress_status: "已关闭" }), "已关闭");
  assert.equal(selectionLabel({ pr_eligible: 0, progress_status: "PO处理中" }), "已提完");
});

test("second status row only lists statuses outside the seven stages that have data", () => {
  assert.deepEqual(otherStatuses({ OA审批中: 3, 已取消: 2, 已拒绝: 0, 已撤回: 1, 延期: 4 }, STAGES), [
    { status: "已取消", count: 2 }, { status: "已撤回", count: 1 }, { status: "延期", count: 4 },
  ]);
  assert.deepEqual(otherStatuses({ OA审批中: 3 }, STAGES), []);
  assert.equal(allStageCount({ OA审批中: 3, 付款中: 2, 已取消: 1 }), 6);
});

test("rows are grouped per OA in server order with projects, status counts and a delivery range", () => {
  const groups = groupRows([
    { name: "1", source_request: "OA-A", requester: "甲", project: "P1", progress_status: "OA审批中", expected_delivery_date: "2026-10-20" },
    { name: "2", source_request: "OA-B", requester: "乙", project: "", progress_status: "付款中", expected_delivery_date: "" },
    { name: "3", source_request: "OA-A", requester: "甲", project: "P2", progress_status: "OA审批中", expected_delivery_date: "2026-10-12" },
  ]);
  assert.deepEqual(groups.map((group) => group.key), ["OA-A", "OA-B"]);
  assert.equal(groups[0].projects, "P1、P2");
  assert.deepEqual(groups[0].statuses, { OA审批中: 2 });
  assert.equal(groupDateText(groups[0]), "交期 2026-10-12 至 2026-10-20");
  assert.equal(groupDateText(groups[1]), "交期待确认");
});

test("column filter is a contains match and sort uses natural Chinese ordering", () => {
  const rows = [{ name: "a", item_name: "光纤 10" }, { name: "b", item_name: "光纤 2" }, { name: "c", item_name: "连接器" }];
  assert.deepEqual(filterSortRows(rows, { filters: { item_name: "光纤" } }).map((row) => row.name), ["a", "b"]);
  assert.deepEqual(filterSortRows(rows, { sortField: "item_name", sortDirection: "asc" }).map((row) => row.name), ["b", "a", "c"]);
  assert.deepEqual(filterSortRows(rows, { sortField: "item_name", sortDirection: "desc" }).map((row) => row.name), ["c", "a", "b"]);
  assert.equal(filterSortRows(rows).length, 3);
});

test("partial PR: every selected line needs a quantity above 0 and not above what is still available", () => {
  const rows = [
    { name: "a", source_request: "OA-1", source_line: "L1", pr_available_quantity: 5, material_serial: "M1" },
    { name: "b", source_request: "OA-1", source_line: "L2", pr_available_quantity: 2, material_serial: "M2" },
  ];
  const ok = buildPrLines(rows, { a: 3, b: 2 });
  assert.equal(ok.invalid, null);
  assert.deepEqual(ok.lines, [{ source_request: "OA-1", source_line: "L1", quantity: 3 }, { source_request: "OA-1", source_line: "L2", quantity: 2 }]);
  assert.equal(buildPrLines(rows, { a: 3, b: 3 }).invalid.material_serial, "M2");
  assert.equal(buildPrLines(rows, { a: 0, b: 1 }).invalid.material_serial, "M1");
  assert.deepEqual(buildPrLines([], {}).lines, []);
});

test("clipboard text becomes a matrix without the trailing blank line", () => {
  assert.deepEqual(parseClipboardMatrix("a\tb\r\nc\td\r\n"), [["a", "b"], ["c", "d"]]);
  assert.deepEqual(parseClipboardMatrix("x"), [["x"]]);
  assert.deepEqual(selectionBounds({ row: 3, col: 5 }, { row: 1, col: 2 }), { minRow: 1, maxRow: 3, minCol: 2, maxCol: 5 });
});

test("cancel reason is required and capped at 500 characters", () => {
  assert.equal(cancelReasonProblem("   "), "请填写取消原因");
  assert.equal(cancelReasonProblem(undefined), "请填写取消原因");
  assert.equal(cancelReasonProblem("a".repeat(501)), "取消原因不能超过 500 字");
  assert.equal(cancelReasonProblem("供应商停产"), "");
});
