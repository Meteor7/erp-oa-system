import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/pages/Allocation.vue", import.meta.url), "utf8");

test("allocation page can cancel the finalized allocation with an inline confirmation", () => {
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.cancel_allocation/);
  assert.match(source, /const canceling = ref\(false\)/);
  assert.ok(source.includes("cancelAllocation"));
  assert.ok(source.includes("confirmCancel"));
  assert.match(source, /cancelRes\.submit\(\{ period: period\.value, reason: cancelReasonText\.value \}\)/);
  assert.match(source, /await load\(\)/);
  // 不再用 window.confirm，改成「确认撤销 / 返回」的行内确认
  assert.doesNotMatch(source, /window\.confirm/);
  assert.match(source, /const confirmingCancel = ref\(false\)/);
  assert.ok(source.includes("确认撤销"));
  assert.ok(source.includes("返回"));
  assert.ok(source.includes("撤销定版"));
  assert.ok(source.includes("撤销后本月回到预览，工时和费用可以再修改。"));
  // 只有月度、已定版时才出现撤销按钮；不是财务主管时按钮禁用
  assert.match(source, /v-if="actionState\.showCancel"/);
  assert.match(source, /:disabled="actionState\.cancelDisabled \|\| canceling"/);
  assert.match(source, /if \(!isFinalized\.value \|\| isYearScope\.value \|\| !canSubmitCancel\.value\) return/);
});

test("revoking a finalized allocation needs a written reason (1-200 chars) that is sent and recorded", () => {
  assert.ok(source.includes("撤销原因（必填，会记录在这张分摊单上）"));
  assert.match(source, /const CANCEL_REASON_MAX = 200/);
  assert.match(source, /<textarea v-model="cancelReason"[^>]*:maxlength="CANCEL_REASON_MAX"/);
  // live counter
  assert.match(source, /\{\{ cancelReason\.length \}\} \/ \{\{ CANCEL_REASON_MAX \}\}/);
  // the confirm button stays disabled until the trimmed reason is non-empty
  assert.match(source, /const cancelReasonText = computed\(\(\) => cancelReason\.value\.trim\(\)\)/);
  assert.match(source, /cancelReasonText\.value\.length >= 1 && cancelReasonText\.value\.length <= CANCEL_REASON_MAX/);
  assert.match(source, /class="btn sm bad" :disabled="!canSubmitCancel" @click="cancelAllocation"/);
  // the server error is shown next to the form, which stays open
  assert.match(source, /cancelError\.value = errorText\(cancelRes, e, "撤销失败"\)/);
  assert.match(source, /<span v-if="cancelError" class="cancel-err" role="alert">/);
  // opening / closing / reloading clears the reason
  assert.match(source, /function openCancelConfirm\(\) \{\s*cancelReason\.value = "";/);
  assert.match(source, /function resetConfirms\(\) \{\s*confirmingCancel\.value = false;\s*cancelReason\.value = "";/);
});

test("the preview error is rendered as plain text with the timesheet page name turned into a link", () => {
  assert.match(source, /const ENTRY_LINK_TEXT = "研发工时填报"/);
  assert.match(source, /\{ text: ENTRY_LINK_TEXT, to: "\/entry" \}/);
  assert.match(source, /<router-link v-if="part\.to" :to="part\.to" class="pe-link">\{\{ part\.text \}\}<\/router-link>/);
  // never injected as HTML
  assert.doesNotMatch(source, /v-html/);
});

test("allocation page no longer recalculates; it previews and finalizes in month scope only", () => {
  assert.doesNotMatch(source, /recalc/);
  assert.doesNotMatch(source, /重算/);
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.finalize_allocation/);
  assert.match(source, /rayher_hr_payroll\.api\.allocation_entry\.get_finalize_check/);
  assert.match(source, /finalizeRes\.submit\(\{ period: period\.value \}\)/);
  assert.match(source, /checkRes\.submit\(\{ period: requested \}\)/);
  assert.match(source, /if \(isYearScope\.value \|\| !canConfirmFinalize\.value\) return/);
  assert.match(source, /extractFrappeError/);
});

test("allocation page shows an amber preview strip, a red preview error and collapsible warnings", () => {
  assert.ok(source.includes("这是按当前费用和工时算出的预览，还没有定版。财务主管点「定版本月分摊」后，本月的工时和费用都会锁定。"));
  assert.match(source, /v-if="!loading && isPreview" class="note warn strip"/);
  assert.ok(source.includes("预览算不出来："));
  assert.match(source, /v-if="!loading && isPreviewError" class="note bad strip" role="alert"/);
  assert.match(source, /previewWarningTexts\(payload\.value\)/);
  assert.match(source, /<details v-if="!loading && previewWarnings\.length"/);
  // 预览算不出来时不再取矩阵
  assert.match(source, /if \(!summary\.value \|\| isPreviewError\.value\) return/);
});

test("allocation page finalize button and inline confirm card", () => {
  assert.ok(source.includes('finalize: "定版本月分摊"'));
  assert.match(source, /v-if="actionState\.showFinalize"/);
  assert.match(source, /:disabled="actionState\.finalizeDisabled/);
  assert.match(source, /:title="actionState\.finalizeDisabled \? actionState\.finalizeTitle : undefined"/);
  assert.match(source, /v-if="confirmingFinalize" class="card fin"/);
  assert.ok(source.includes("定版后本月工时和费用演示员工177能再改，要改需先撤销定版。"));
  assert.ok(source.includes('confirmFinalize: "确认定版"'));
  assert.ok(source.includes('confirmFinalizeNo: "取消"'));
  assert.match(source, /buildFinalizeCheckLines\(checkData\.value\)/);
  // 服务端错误用红色提示显示
  assert.match(source, /finalizeError/);
  assert.match(source, /checkError/);
  // 定版成功后重新加载
  assert.match(source, /await load\(\);\s*setMessage\("已定版：" \+ done\)/);
});

test("allocation page matrix is filled from the preview while the month is not finalized", () => {
  assert.match(source, /preview: isPreview\.value/);
  assert.match(source, /const matrixTag = computed\(\(\) => allocName\.value \|\| \(isPreview\.value \? "预览" : displayPeriod\.value\)\)/);
  // 导出文件名 / 期间列带「已定版-定版人」或「预览」标记（allocationExportLabel）
  assert.match(source, /period: allocationExportLabel\(\{\s*period: displayPeriod\.value,\s*state: viewState\.value,\s*finalizedByName: finalizedBy,/);
});

test("allocation page shows who finalized and when next to the status tag, and the last revoke in preview", () => {
  assert.match(source, /const finalizedInfo = computed\(\(\) => \(isFinalized\.value \? finalizedStamp\(payload\.value\) : null\)\)/);
  assert.match(source, /const revokeInfo = computed\(\(\) => \(isPreview\.value \|\| isPreviewError\.value \? lastRevokeLine\(payload\.value\) : null\)\)/);
  // 定版人和时间紧跟在状态标签后面，完整时间在悬停提示里
  assert.match(source, /<span v-if="finalizedInfo" class="muted stamp" :title="finalizedInfo\.title">\{\{ finalizedInfo\.text \}\}<\/span>/);
  // 上次撤销放在状态标签下面一行（不是同一行的 inline）
  assert.match(source, /<div v-if="!loading && statusTag" class="stat-col">[\s\S]*<span v-if="revokeInfo" class="muted revoke" :title="revokeInfo\.title">\{\{ revokeInfo\.text \}\}<\/span>/);
  // 纯文本渲染，不用 v-html（撤销原因是用户输入）
  assert.doesNotMatch(source, /v-html/);
});

test("allocation export carries the info sheet with status, finalizer and last revoke", () => {
  assert.match(source, /info: buildAllocationInfoRows\(\{/);
  assert.match(source, /finalizedOn: data\.finalized_on/);
  assert.match(source, /lastRevoke: isPreview\.value \? data\.last_revoke : null/);
  assert.match(source, /exportedAt: exportTimestamp\(\)/);
});

test("allocation page supports month and year views with four top totals", () => {
  assert.match(source, /periodScope/);
  assert.match(source, /scope: periodScope\.value/);
  assert.match(source, /PERIOD_SCOPES/);
  assert.match(source, /capitalExpense/);
  assert.match(source, /capitalized/);
  assert.match(source, /expensed/);
  assert.match(source, /unknown/);
  assert.match(source, /hasAllocationData\(a\)/);
  assert.match(source, /buildAllocationMatrixFilters/);
  assert.match(source, /allocationEmptyState/);
  assert.match(source, /allocName\.value \|\| \(isPreview/);
  assert.match(source, /loadAllocationStageMatrices/);
  assert.match(source, /const exportMatrixRes = createResource/);
  assert.match(source, /stageMatrices = await loadAllocationStageMatrices/);
  assert.match(source, /stageMatrices,/);
  // 未判定大于 0 时卡片用「需处理」色调
  assert.match(source, /tone: unknown > 0 \? "warn" : ""/);
  assert.ok(source.includes("本期没有费用导入，先在「研发费用导入」录入费用"));
});

test("allocation ledger uses the shared summary capitalized and expensed views", () => {
  assert.ok(source.includes('title: "研发费用台账"'));
  assert.match(source, /const modeOptions =/);
  assert.ok(source.includes('{ value: "all", label: "汇总" }'));
  assert.ok(source.includes('{ value: "capitalized", label: "资本化" }'));
  assert.ok(source.includes('{ value: "expensed", label: "费用化" }'));
  assert.match(source, /const allocationMode = ref\("all"\)/);
  assert.match(source, /stage: allocationMode\.value/);
  assert.match(source, /watch\(allocationMode, \(\) => loadMatrix\(\)\)/);
  assert.match(source, /v-model="allocationMode"/);
  assert.match(source, /:options="modeOptions"/);
});

test("allocation page uses the shared R&D page shell and groups the toolbar into view and actions", () => {
  assert.match(source, /<RdPage /);
  assert.match(source, /<RdPeriod \/>/);
  assert.match(source, /<RdSeg /);
  assert.match(source, /<RdKpi /);
  assert.ok(source.includes('view: "查看"'));
  assert.ok(source.includes('actions: "操作"'));
  assert.match(source, /allocationReconcileDifference/);
  assert.ok(source.includes("分摊合计与费用池差额"));
});

test("allocation page has no status-and-reconcile card; status is a tag by the title and reconcile sits in the matrix header", () => {
  assert.ok(!source.includes("分摊状态与对账"));
  assert.doesNotMatch(source, /statusTitle/);
  assert.doesNotMatch(source, /const checks = computed/);
  assert.doesNotMatch(source, /class="chk"/);
  // 状态标签放在页头右侧（状态文字来自 allocationStatusTag：已定版 / 预览 · 未定版 / 年度 · 只读）
  assert.match(source, /<template #ctl>[\s\S]*statusTag\.text[\s\S]*<RdPeriod \/>/);
  assert.match(source, /allocationStatusTag\(viewState\.value\)/);
  assert.ok(source.includes("年度汇总各月已定版的分摊，只读"));
  assert.match(source, /isFinalized && allocName/);
  assert.ok(source.includes("分摊单 {{ allocName }}"));
  // 矩阵卡片头里的对账标签
  assert.ok(source.includes("已对账 · 差额 0.00"));
  assert.match(source, /差额 \{\{ fmt\(reconcileDiff\) \}\} 元/);
  // 差额异常条：已定版时让用户撤销定版，没有重算按钮
  assert.match(source, /v-if="showDiffStrip" class="note warn strip" role="alert"/);
  assert.ok(source.includes("请撤销定版后重新定版。"));
  assert.match(source, /const showDiffStrip = computed\(\(\) => !loading\.value && !isYearScope\.value && reconcileOff\.value\)/);
  // 未判定的重复检查行已去掉
  assert.ok(!source.includes("来自阶段未判定的项目"));
});

test("allocation page removes the middle project summary and keeps a bottom total row in the matrix", () => {
  assert.doesNotMatch(source, /projectSummaries/);
  assert.doesNotMatch(source, /project_summaries/);
  assert.match(source, /isTotalRow/);
  assert.match(source, /projectTotal/);
  assert.match(source, /result\.length/);
  assert.match(source, /matrixView\.totalRow/);
});

test("allocation matrix groups rows under collapsible level-3 account headers", () => {
  assert.match(source, /groupAllocationRows/);
  assert.match(source, /toggleGroup/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /class="g"/);
  assert.match(source, /group\.totals\[colKey\(c\)\]/);
  // 项目列头：编号一行、项目名称小字一行（省略号）、阶段一行，悬停显示 "RD13 · KIBO 5895H · 费用化"
  assert.match(source, /projectColumnHeader\(c\)/);
  assert.match(source, /<th v-for="h in moneyHeaders" :key="h\.key" class="r ph" :title="h\.title">/);
  assert.match(source, /<small v-if="h\.name" class="ph-name">\{\{ h\.name \}\}<\/small>/);
  assert.match(source, /<small v-if="h\.stage" class="ph-stage">\{\{ h\.stage \}\}<\/small>/);
  assert.match(source, /\.ph-name \{[^}]*text-overflow: ellipsis/);
});

test("allocation page can export the current allocation workbook", () => {
  assert.match(source, /exportAllocationWorkbook/);
  assert.match(source, /const exporting = ref\(false\)/);
  assert.match(source, /const canExport = computed/);
  assert.match(source, /exportExcel/);
  assert.match(source, /!canExport/);
  assert.match(source, /summary: summary\.value/);
  assert.match(source, /allocationModeLabel\.value/);
});

test("allocation footer line uses Chinese separators and a Chinese row count", () => {
  assert.ok(source.includes("{{ totalRows }} 行明细"));
  assert.doesNotMatch(source, /\?\s*\{\{/);
  assert.doesNotMatch(source, /\}\}\s*\?/);
  assert.doesNotMatch(source, /totalRows \}\} rows/);
});

test("allocation total row label is rendered in the level-3 expense column", () => {
  assert.match(source, /key === "account_level_3"/);
  assert.doesNotMatch(source, /key === "expense_item_name"/);
});
