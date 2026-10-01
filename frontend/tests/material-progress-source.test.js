import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/pages/MaterialProgress.vue");
const drawer = read("../src/components/material/MaterialDrawer.vue");
const view = read("../src/lib/materialView.js");

test("material board keeps the old page's server calls, paging and optimistic lock", () => {
  assert.match(page, /rayher_hr_payroll\.api\.material_progress\.list_material_progress/);
  assert.match(page, /rayher_hr_payroll\.api\.material_progress\.update_material_progress/);
  assert.match(page, /rayher_hr_payroll\.api\.material_progress\.cancel_material_progress/);
  assert.match(page, /rayher_hr_payroll\.api\.procurement_chain\.create_pr/);
  assert.match(page, /const pageSize = 50/);
  assert.match(page, /expected_modified: row\.modified/);
  assert.match(page, /source_request: sourceRequest\.value/);
  assert.match(page, /stage_counts/);
});

test("the page is the redesigned board: title, stage strip, one filter row, sidebar kept, group headers", () => {
  assert.match(page, />物料进度看板</);
  assert.doesNotMatch(page, /物料进度查询/);
  for (const stage of ["OA审批中", "采购确认中", "PO处理中", "供应商制作中", "到货验收中", "付款中", "已关闭"]) assert.match(page, new RegExp(stage));
  assert.match(page, /class="mp-stages"/);
  assert.match(page, /class="mp-others"/);
  assert.match(page, /otherStatuses\(counts\.value, stageStatuses\)/);
  assert.match(page, /class="mp-filter"/);
  assert.match(page, /@keyup\.enter="query"/);
  assert.match(page, /OA 订单（本页）/);
  assert.match(page, /class="mp-side"/);
  assert.match(page, /class="mp-group"/);
  assert.match(page, /来源 OA →/);
  assert.match(page, /显示全部字段（28 列）/);
  assert.match(page, /流程状态由关联单据自动更新/);
  assert.doesNotMatch(page, /<select v-model="status"/, "the status select became the stage strip");
});

test("PR creation belongs to PMC only: button, checkbox column and 本次 PR column", () => {
  assert.match(page, /const canCreatePr = canCreateProcurementPr\(\)/);
  assert.match(page, /v-if="canCreatePr" type="button" class="btn pri lg"/);
  assert.match(page, /<th v-if="canCreatePr" class="mp-check/);
  assert.match(page, /<td v-if="canCreatePr" class="mp-check/);
  assert.match(page, /displayColumns\(\{ showAll: showAllColumns\.value, canCreatePr \}\)/);
  assert.match(view, /canCreatePr \|\| column\.field !== 'pr_create_quantity'/);
  assert.match(page, /createPrFromBoard/);
  assert.match(page, /prQuantities/);
  assert.match(page, /本次 PR 数量必须大于 0 且不超过可提数量/);
  assert.match(page, /请先选择需求审批已完成的物料/);
  assert.match(page, /生成 PR/);
});

test("inline editing, range copy and paste behaviours survive", () => {
  assert.match(page, /contenteditable/);
  assert.match(page, /cell-saved/);
  assert.match(page, /cell-error/);
  assert.match(page, /async function pasteCells/);
  assert.match(page, /parseClipboardMatrix/);
  assert.match(page, /async function copySelection/);
  assert.match(page, /navigator\.clipboard\.writeText/);
  assert.match(page, /event\.ctrlKey \|\| event\.metaKey/);
  assert.match(page, /@paste="pasteCells"/);
  assert.match(page, /@pointerdown="startSelection"/);
  assert.match(page, /已粘贴并保存/);
  assert.match(page, /已复制/);
  assert.match(page, /oa_approval_trail/);
});

test("column menus filter and sort, and deep links open the drawer", () => {
  assert.match(page, /sortColumn\(column\.field, 'asc'\)/);
  assert.match(page, /sortColumn\(column\.field, 'desc'\)/);
  assert.match(page, /applyColumnFilter/);
  assert.match(page, /clearColumn/);
  assert.match(page, /route\.query\.source_line/);
  assert.match(page, /route\.query\.request/);
  assert.match(page, /scrollIntoView/);
  assert.match(page, /<MaterialDrawer/);
  assert.match(page, /明细 ›/);
  assert.match(page, /正在加载…/);
  assert.match(page, /暂无符合条件的物料进度/);
  assert.match(page, />刷新</);
});

test("the drawer embeds the execution component unchanged and cancels with an inline required reason", () => {
  assert.match(drawer, /import MaterialExecutionProgress from '\.\.\/MaterialExecutionProgress\.vue'/);
  assert.match(drawer, /<MaterialExecutionProgress[^>]+:request="line\.source_request"[^>]+:source-line="line\.source_line"[^>]+expanded/);
  assert.match(drawer, /标记为取消/);
  assert.match(drawer, /取消原因（必填/);
  assert.match(drawer, /不会取消已经生成的 PR \/ 价格审批 \/ PO/);
  assert.match(drawer, /cancelReasonProblem/);
  assert.doesNotMatch(page + drawer, /window\.prompt/);
  assert.doesNotMatch(page + drawer, /window\.confirm/);
  assert.match(page, /canceller\.submit\(\{ name: row\.name, reason \}\)/);
});

test("no hard-coded person names on the board", () => {
  for (const name of ["演示员工178", "何静", "演示员工21"]) assert.doesNotMatch(page + drawer, new RegExp(name));
});
