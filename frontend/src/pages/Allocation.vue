<script setup>
import { ref, computed, watch } from "vue";
import { Spinner, createResource } from "frappe-ui";
import RdPage from "../components/rd/RdPage.vue";
import RdPeriod from "../components/rd/RdPeriod.vue";
import RdSeg from "../components/rd/RdSeg.vue";
import RdKpi from "../components/rd/RdKpi.vue";
import RdIcon from "../components/rd/RdIcon.vue";
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { exportAllocationWorkbook, allocationReconcileDifference } from "../lib/allocationExport";
import {
  allocationActionState,
  allocationEmptyState,
  allocationStatusTag,
  allocationViewState,
  buildAllocationMatrixFilters,
  buildFinalizeCheckLines,
  finalizeCheckIssueCount,
  hasAllocationData,
  loadAllocationStageMatrices,
  previewWarningTexts,
} from "../lib/allocationView";
import { extractFrappeError } from "../lib/frappeError";
import { groupAllocationRows, stageLabel } from "../lib/allocationGroups";

const TEXT = {
  title: "研发费用台账",
  subtitle: "按工时分配率把费用池摊到各项目，并按项目资本化阶段汇总",
  view: "查看",
  actions: "操作",
  finalize: "定版本月分摊",
  finalizing: "定版中…",
  cancel: "撤销定版",
  canceling: "撤销中…",
  exportExcel: "导出 Excel",
  exporting: "导出中…",
  capitalized: "资本化",
  expensed: "费用化",
  capitalExpense: "资本 + 费用 合计",
  unknown: "未判定",
  projectTotal: "项目汇总",
  accountColumn: "科目（三级 › 四级）",
  ungrouped: "（未分类）",
  noBusinessData: "本期没有费用导入，先在「研发费用导入」录入费用。",
  noYearData: "本年还没有已定版的月份。",
  noAllocationDetail: "已有费用或业务数据，但暂无可展示的项目分摊明细。",
  noDetailForMode: "当前口径暂无可展示的分摊明细。",
  confirmCancel: "确定撤销",
  confirmCancelTail: "的定版吗？撤销后本月回到预览，工时和费用可以再修改。",
  confirmYes: "确认撤销",
  confirmNo: "返回",
  cancelReasonLabel: "撤销原因（必填，会记录在这张分摊单上）",
  cancelReasonHint: "例如：发现 6 月有一笔费用录错了项目，改完后重新定版",
  yearHint: "年度汇总各月已定版的分摊，只读",
  previewNote: "这是按当前费用和工时算出的预览，还没有定版。财务主管点「定版本月分摊」后，本月的工时和费用都会锁定。",
  finalizeLock: "定版后本月工时和费用都不能再改，要改需先撤销定版。",
  confirmFinalize: "确认定版",
  confirmFinalizeNo: "取消",
  matrixTitle: "分摊明细矩阵",
};

const modeOptions = [
  { value: "all", label: "汇总" },
  { value: "capitalized", label: "资本化" },
  { value: "expensed", label: "费用化" },
];

// 撤销定版必须写原因（服务端要求 1-200 字，并记录在分摊单上）。
const CANCEL_REASON_MAX = 200;
// 预览算不出来的提示里出现这个词时，把它做成去工时填报页的链接。
const ENTRY_LINK_TEXT = "研发工时填报";

// 服务端报表里 voucher_no 列的英文表头，页面里统一显示为中文。
const COLUMN_LABELS = { "Voucher No": "凭证号" };

const columns = ref([]);
const result = ref([]);
const summary = ref(null);
const payload = ref(null);
const allocName = ref(null);
const loading = ref(false);
const finalizing = ref(false);
const canceling = ref(false);
const exporting = ref(false);
const confirmingCancel = ref(false);
const cancelReason = ref("");
const cancelError = ref("");
const confirmingFinalize = ref(false);
const checking = ref(false);
const checkData = ref(null);
const checkError = ref("");
const finalizeError = ref("");
const msg = ref("");
const msgBad = ref(false);
const allocationMode = ref("all");
const collapsed = ref({});

const allocRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.get_allocation", method: "GET" });
const checkRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.get_finalize_check", method: "GET" });
const matrixRes = createResource({ url: "frappe.desk.query_report.run", method: "GET" });
const exportMatrixRes = createResource({ url: "frappe.desk.query_report.run", method: "GET" });
const finalizeRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.finalize_allocation" });
const cancelRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.cancel_allocation" });

const isYearScope = computed(() => periodScope.value === "year");
const viewState = computed(() => allocationViewState({ payload: payload.value, scope: periodScope.value }));
const isPreview = computed(() => viewState.value === "preview");
const isPreviewError = computed(() => viewState.value === "preview-error");
const isFinalized = computed(() => viewState.value === "finalized");
const actionState = computed(() => allocationActionState({ state: viewState.value, payload: payload.value }));
const statusTag = computed(() => allocationStatusTag(viewState.value));
const previewError = computed(() => (isPreviewError.value ? String(payload.value?.preview_error || "") : ""));
// 服务端的中文提示原样显示；其中的「研发工时填报」变成链接（文本始终按普通文字渲染，不会被当成 HTML）
const previewErrorParts = computed(() => {
  const text = previewError.value;
  const at = text.indexOf(ENTRY_LINK_TEXT);
  if (at < 0) return [{ text }];
  return [
    { text: text.slice(0, at) },
    { text: ENTRY_LINK_TEXT, to: "/entry" },
    { text: text.slice(at + ENTRY_LINK_TEXT.length) },
  ].filter((part) => part.text);
});
const cancelReasonText = computed(() => cancelReason.value.trim());
const canSubmitCancel = computed(() => (
  cancelReasonText.value.length >= 1 && cancelReasonText.value.length <= CANCEL_REASON_MAX && !canceling.value
));
const previewWarnings = computed(() => (isPreview.value ? previewWarningTexts(payload.value) : []));
const displayPeriod = computed(() => periodScopeLabel(period.value, periodScope.value));
const matrixTag = computed(() => allocName.value || (isPreview.value ? "预览" : displayPeriod.value));
const allocationModeLabel = computed(() => modeOptions.find((option) => option.value === allocationMode.value)?.label || modeOptions[0].label);
const matrixFilters = computed(() => buildAllocationMatrixFilters({
  scope: periodScope.value,
  period: period.value,
  allocation: allocName.value,
  stage: allocationMode.value,
  preview: isPreview.value,
}));
const emptyText = computed(() => {
  const state = allocationEmptyState({
    hasData: Boolean(summary.value?.has_data),
    mode: allocationMode.value,
  });
  if (state === "no-detail") return TEXT.noAllocationDetail;
  if (state === "no-detail-for-mode") return TEXT.noDetailForMode;
  return isYearScope.value ? TEXT.noYearData : TEXT.noBusinessData;
});
const canExport = computed(() => Boolean(summary.value && columns.value.length && result.value.length));
const totalRows = computed(() => result.value.filter((row) => !isTotalRow(row)).length);
const viewSummary = computed(() => {
  const data = summary.value || {};
  if (allocationMode.value === "capitalized") {
    return { ...data, expensed: 0, unknown: 0 };
  }
  if (allocationMode.value === "expensed") {
    return { ...data, capitalized: 0, unknown: 0 };
  }
  return data;
});
const summaryCards = computed(() => {
  const data = viewSummary.value;
  const capitalized = Number(data.capitalized || 0);
  const expensed = Number(data.expensed || 0);
  const unknown = Number(data.unknown || 0);
  const allMode = allocationMode.value === "all";
  return [
    { key: "capitalized", label: TEXT.capitalized, value: capitalized, sub: "处于资本化阶段的项目", tone: "" },
    { key: "expensed", label: TEXT.expensed, value: expensed, sub: "处于费用化阶段的项目", tone: "" },
    { key: "capitalExpense", label: TEXT.capitalExpense, value: capitalized + expensed, sub: "= 资本化 + 费用化", tone: "" },
    {
      key: "unknown",
      label: TEXT.unknown,
      value: unknown,
      sub: unknown > 0 ? "无法归属到项目，需处理" : allMode ? "没有未判定金额" : "当前口径不含",
      tone: unknown > 0 ? "warn" : "",
    },
  ];
});

// 对账：和导出 Excel 里「未对账差额」同一个算法（阶段合计 − 分摊明细合计）。
const reconcileDiff = computed(() => {
  if (!summary.value || !result.value.length) return null;
  return allocationReconcileDifference({ summary: viewSummary.value, columns: columns.value, result: result.value });
});
const reconcileBalanced = computed(() => reconcileDiff.value !== null && Math.abs(reconcileDiff.value) < 0.01);
const reconcileOff = computed(() => reconcileDiff.value !== null && !reconcileBalanced.value);
// 差额不为 0：只在月度提示（年度是只读汇总）
const showDiffStrip = computed(() => !loading.value && !isYearScope.value && reconcileOff.value);

const checkLines = computed(() => buildFinalizeCheckLines(checkData.value));
const checkIssueCount = computed(() => finalizeCheckIssueCount(checkLines.value));
const canConfirmFinalize = computed(() => Boolean(
  checkData.value && checkData.value.can_finalize !== false && !checking.value && !finalizing.value,
));

const matrixView = computed(() => groupAllocationRows({ columns: columns.value, result: result.value }));
const labelColumns = computed(() => columns.value.filter((c) => !isCur(c) && !["account_level_3", "account_level_4"].includes(colKey(c))));
const moneyColumns = computed(() => columns.value.filter((c) => isCur(c)));

function setMessage(text, bad = false) {
  msg.value = text;
  msgBad.value = bad;
}

function errorText(res, e, fallback) {
  return extractFrappeError((res && res.error) || e, fallback);
}

function resetConfirms() {
  confirmingCancel.value = false;
  cancelReason.value = "";
  cancelError.value = "";
  confirmingFinalize.value = false;
  checkData.value = null;
  checkError.value = "";
  finalizeError.value = "";
}

async function loadMatrix() {
  columns.value = [];
  result.value = [];
  if (!summary.value || isPreviewError.value) return;
  const d = await matrixRes.submit({ report_name: "RD Allocation Matrix", filters: JSON.stringify(matrixFilters.value) });
  columns.value = d.columns || [];
  result.value = d.result || [];
}

async function load() {
  loading.value = true;
  resetConfirms();
  setMessage("");
  try {
    const a = await allocRes.submit({ period: period.value, scope: periodScope.value });
    payload.value = a || null;
    summary.value = hasAllocationData(a) ? a : null;
    allocName.value = a && a.name ? a.name : null;
    await loadMatrix();
  } catch (e) {
    payload.value = null;
    summary.value = null;
    allocName.value = null;
    columns.value = [];
    result.value = [];
    setMessage(errorText(allocRes, e, "加载失败，请刷新重试"), true);
  } finally {
    loading.value = false;
  }
}

async function openFinalize() {
  if (actionState.value.finalizeDisabled) return;
  confirmingFinalize.value = true;
  confirmingCancel.value = false;
  checkData.value = null;
  checkError.value = "";
  finalizeError.value = "";
  checking.value = true;
  const requested = period.value;
  try {
    const r = await checkRes.submit({ period: requested });
    if (requested === period.value && confirmingFinalize.value) checkData.value = r || {};
  } catch (e) {
    if (requested === period.value) checkError.value = errorText(checkRes, e, "定版检查失败");
  } finally {
    checking.value = false;
  }
}

function closeFinalize() {
  confirmingFinalize.value = false;
  checkData.value = null;
  checkError.value = "";
  finalizeError.value = "";
}

async function finalizeAllocation() {
  if (isYearScope.value || !canConfirmFinalize.value) return;
  finalizing.value = true;
  finalizeError.value = "";
  try {
    await finalizeRes.submit({ period: period.value });
    const done = period.value;
    await load();
    setMessage("已定版：" + done);
  } catch (e) {
    finalizeError.value = errorText(finalizeRes, e, "定版失败");
  } finally {
    finalizing.value = false;
  }
}

function openCancelConfirm() {
  cancelReason.value = "";
  cancelError.value = "";
  confirmingCancel.value = true;
}

function closeCancelConfirm() {
  confirmingCancel.value = false;
  cancelReason.value = "";
  cancelError.value = "";
}

async function cancelAllocation() {
  if (!isFinalized.value || isYearScope.value || !canSubmitCancel.value) return;
  canceling.value = true;
  cancelError.value = "";
  setMessage("");
  try {
    await cancelRes.submit({ period: period.value, reason: cancelReasonText.value });
    confirmingCancel.value = false;
    await load();
    setMessage("已撤销定版，本月回到预览，可继续调整工时和费用");
  } catch (e) {
    cancelError.value = errorText(cancelRes, e, "撤销失败");
  } finally {
    canceling.value = false;
  }
}

async function exportCurrentAllocation() {
  if (!canExport.value) return;
  exporting.value = true;
  setMessage("");
  try {
    const stageMatrices = await loadAllocationStageMatrices({
      scope: periodScope.value,
      period: period.value,
      allocation: allocName.value,
      preview: isPreview.value,
      load: (filters) => exportMatrixRes.submit({
        report_name: "RD Allocation Matrix",
        filters: JSON.stringify(filters),
      }),
    });
    const filename = await exportAllocationWorkbook({
      period: `${displayPeriod.value}${isPreview.value ? "（预览）" : ""}-${allocationModeLabel.value}`,
      summary: summary.value,
      columns: columns.value,
      result: result.value,
      stageMatrices,
    });
    setMessage("已导出：" + filename);
  } catch (e) {
    setMessage((e && e.message) || "导出失败", true);
  } finally {
    exporting.value = false;
  }
}

const fmt = (n) => (typeof n === "number" ? n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : n);
const colKey = (c) => c.fieldname || c.id;
const colLabel = (c) => COLUMN_LABELS[c.label] || c.label || c.fieldname;
const isCur = (c) => c.fieldtype === "Currency";
function isTotalRow(row = {}) { return Boolean(row._is_total); }
function moneyText(value) {
  const n = Number(value || 0);
  return Math.abs(n) < 0.005 ? "·" : fmt(n);
}
function isZero(value) { return Math.abs(Number(value || 0)) < 0.005; }
function cellText(row, column) {
  const key = colKey(column);
  if (isTotalRow(row) && key === "account_level_3") return TEXT.projectTotal;
  const value = row[key];
  return isCur(column) ? moneyText(value) : (value ?? "");
}
function projectTitle(column) {
  const name = column.project_name || column.project || colLabel(column);
  const stage = stageLabel(column.project_stage);
  return stage ? `${name} · ${stage}` : String(name);
}
function isCollapsed(key) { return Boolean(collapsed.value[key]); }
function toggleGroup(key) { collapsed.value = { ...collapsed.value, [key]: !collapsed.value[key] }; }

watch(period, () => load());
watch(periodScope, () => load());
watch(allocationMode, () => loadMatrix());
load();
</script>

<template>
  <RdPage :title="TEXT.title" :subtitle="TEXT.subtitle">
    <template #ctl>
      <span v-if="!loading && statusTag" class="stat" aria-live="polite">
        <span class="tag" :class="statusTag.cls"><RdIcon v-if="statusTag.cls === 'ok'" name="check" />{{ statusTag.text }}</span>
        <span v-if="isYearScope" class="muted">{{ TEXT.yearHint }}</span>
        <span v-else-if="isFinalized && allocName" class="muted">分摊单 {{ allocName }}</span>
      </span>
      <RdPeriod />
    </template>

    <div v-if="summary" class="kpis">
      <RdKpi v-for="card in summaryCards" :key="card.key" :label="card.label" :value="fmt(card.value)" unit="元" :sub="card.sub" :tone="card.tone" />
    </div>

    <div v-if="!loading && isPreview" class="note warn strip" role="status">
      <RdIcon name="alert" />
      <span class="grow">{{ TEXT.previewNote }}</span>
    </div>
    <div v-if="!loading && isPreviewError" class="note bad strip" role="alert">
      <RdIcon name="alert" />
      <span class="grow"><b>预览算不出来：</b><template v-for="(part, i) in previewErrorParts" :key="i"><router-link v-if="part.to" :to="part.to" class="pe-link">{{ part.text }}</router-link><template v-else>{{ part.text }}</template></template></span>
    </div>
    <details v-if="!loading && previewWarnings.length" class="pw">
      <summary class="muted">预览提示 {{ previewWarnings.length }} 条</summary>
      <ul class="muted">
        <li v-for="(w, i) in previewWarnings" :key="i">{{ w }}</li>
      </ul>
    </details>

    <div v-if="showDiffStrip" class="note warn strip" role="alert">
      <RdIcon name="alert" />
      <span v-if="isFinalized" class="grow"><b>分摊合计与费用池差额 {{ fmt(reconcileDiff) }} 元</b>（阶段合计与分摊明细对不上），请撤销定版后重新定版。</span>
      <span v-else class="grow"><b>分摊合计与费用池差额 {{ fmt(reconcileDiff) }} 元</b>（阶段合计与分摊明细对不上），请核对费用和工时后再定版。</span>
    </div>

    <div class="bar">
      <div class="row">
        <span class="muted">{{ TEXT.view }}</span>
        <RdSeg :model-value="periodScope" :options="PERIOD_SCOPES" label="期间范围" @update:model-value="setPeriodScope" />
        <RdSeg v-model="allocationMode" :options="modeOptions" label="口径" />
      </div>
      <div class="row">
        <span class="muted">{{ TEXT.actions }}</span>
        <button v-if="actionState.showFinalize" type="button" class="btn pri" :disabled="actionState.finalizeDisabled || finalizing || confirmingFinalize" :title="actionState.finalizeDisabled ? actionState.finalizeTitle : undefined" @click="openFinalize"><RdIcon name="check" />{{ finalizing ? TEXT.finalizing : TEXT.finalize }}</button>
        <button v-if="summary" type="button" class="btn" :disabled="!canExport || exporting" @click="exportCurrentAllocation"><RdIcon name="download" />{{ exporting ? TEXT.exporting : TEXT.exportExcel }}</button>
        <template v-if="actionState.showCancel">
          <div v-if="confirmingCancel" class="note bad confirm cancel-form" role="group" aria-label="撤销定版">
            <span>{{ TEXT.confirmCancel }} {{ period }} {{ TEXT.confirmCancelTail }}</span>
            <label class="cancel-reason">
              <span class="cancel-label">{{ TEXT.cancelReasonLabel }}</span>
              <textarea v-model="cancelReason" class="field" rows="2" :maxlength="CANCEL_REASON_MAX" :placeholder="TEXT.cancelReasonHint" :disabled="canceling" aria-required="true"></textarea>
              <span class="cancel-count" :class="{ full: cancelReason.length >= CANCEL_REASON_MAX }" aria-live="polite">{{ cancelReason.length }} / {{ CANCEL_REASON_MAX }}</span>
            </label>
            <span v-if="cancelError" class="cancel-err" role="alert"><RdIcon name="alert" />{{ cancelError }}</span>
            <span class="cancel-act">
              <button type="button" class="btn sm bad" :disabled="!canSubmitCancel" @click="cancelAllocation">{{ canceling ? TEXT.canceling : TEXT.confirmYes }}</button>
              <button type="button" class="btn sm" :disabled="canceling" @click="closeCancelConfirm">{{ TEXT.confirmNo }}</button>
            </span>
          </div>
          <button v-else type="button" class="btn bad" :disabled="actionState.cancelDisabled || canceling" :title="actionState.cancelDisabled ? actionState.cancelTitle : undefined" @click="openCancelConfirm">{{ TEXT.cancel }}</button>
        </template>
      </div>
    </div>

    <div v-if="confirmingFinalize" class="card fin" role="region" aria-label="确认定版">
      <div class="hd">
        <b>定版 {{ period }}</b>
        <span v-if="checking" class="muted">正在检查…</span>
        <span v-else-if="checkData" class="muted">{{ checkIssueCount ? `有 ${checkIssueCount} 项需要留意，可以继续定版` : "检查都通过了" }}</span>
      </div>
      <div class="bd">
        <div v-if="checking" class="flex justify-center py-3"><Spinner class="w-5" /></div>
        <div v-else-if="checkError" class="note bad" role="alert"><RdIcon name="alert" /><span class="grow">{{ checkError }}</span></div>
        <template v-else>
          <div v-for="line in checkLines" :key="line.key" :class="['chk', line.tone]">
            <RdIcon :name="line.tone === 'warn' ? 'alert' : 'check'" />
            <span>{{ line.text }}<span v-if="line.detail" class="muted">（{{ line.detail }}）</span></span>
          </div>
        </template>
        <p class="fin-lock">{{ TEXT.finalizeLock }}</p>
        <div v-if="finalizeError" class="note bad" role="alert"><RdIcon name="alert" /><span class="grow">{{ finalizeError }}</span></div>
        <div class="row fin-act">
          <button type="button" class="btn pri" :disabled="!canConfirmFinalize" @click="finalizeAllocation">{{ finalizing ? TEXT.finalizing : TEXT.confirmFinalize }}</button>
          <button type="button" class="btn" :disabled="finalizing" @click="closeFinalize">{{ TEXT.confirmFinalizeNo }}</button>
        </div>
      </div>
    </div>

    <div v-if="msg" class="note" :class="msgBad ? 'bad' : 'ok'" :role="msgBad ? 'alert' : 'status'"><RdIcon :name="msgBad ? 'alert' : 'check'" /><span class="grow">{{ msg }}</span></div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <template v-else>
      <div v-if="!result.length && isPreviewError" />
      <div v-else-if="!result.length" class="card"><div class="bd muted">{{ emptyText }}</div></div>
      <div v-else class="card">
        <div class="hd">
          <div class="row hd-l"><b>{{ TEXT.matrixTitle }}</b><span class="muted">{{ displayPeriod }} · {{ matrixTag }} · {{ totalRows }} 行明细</span></div>
          <span v-if="reconcileBalanced" class="tag ok"><RdIcon name="check" />已对账 · 差额 0.00</span>
          <span v-else-if="reconcileOff" class="tag warn">差额 {{ fmt(reconcileDiff) }} 元</span>
        </div>
        <div class="tbl alloc-tbl">
          <table class="matrix">
            <thead>
              <tr>
                <th class="c1">{{ TEXT.accountColumn }}</th>
                <th v-for="c in labelColumns" :key="colKey(c)">{{ colLabel(c) }}</th>
                <th v-for="c in moneyColumns" :key="colKey(c)" class="r" :title="projectTitle(c)">
                  {{ colLabel(c) }}
                  <small v-if="stageLabel(c.project_stage)">{{ stageLabel(c.project_stage) }}</small>
                </th>
              </tr>
            </thead>
            <tbody>
              <template v-for="group in matrixView.groups" :key="group.key">
                <tr v-if="matrixView.grouped" class="g">
                  <td class="c1">
                    <button type="button" class="btn quiet sm tgl" :aria-expanded="!isCollapsed(group.key)" :aria-label="(isCollapsed(group.key) ? '展开 ' : '收起 ') + (group.label || TEXT.ungrouped)" @click="toggleGroup(group.key)"><RdIcon :name="isCollapsed(group.key) ? 'right' : 'down'" /></button>
                    {{ group.label || TEXT.ungrouped }} <span class="muted">· {{ group.rows.length }} 行</span>
                  </td>
                  <td v-for="c in labelColumns" :key="colKey(c)"></td>
                  <td v-for="c in moneyColumns" :key="colKey(c)" class="r num nw" :class="{ zero: isZero(group.totals[colKey(c)]) }">{{ moneyText(group.totals[colKey(c)]) }}</td>
                </tr>
                <template v-if="!matrixView.grouped || !isCollapsed(group.key)">
                  <tr v-for="(row, i) in group.rows" :key="i">
                    <td class="c1 detail">{{ (matrixView.grouped ? row.account_level_4 : row.account_level_3 || row.account_level_4) || "—" }}</td>
                    <td v-for="c in labelColumns" :key="colKey(c)" class="nw num muted">{{ cellText(row, c) }}</td>
                    <td v-for="c in moneyColumns" :key="colKey(c)" class="r num nw" :class="{ zero: isZero(row[colKey(c)]) }">{{ cellText(row, c) }}</td>
                  </tr>
                </template>
              </template>
              <tr v-if="matrixView.totalRow" class="t">
                <td class="c1">{{ TEXT.projectTotal }}</td>
                <td v-for="c in labelColumns" :key="colKey(c)"></td>
                <td v-for="c in moneyColumns" :key="colKey(c)" class="r num nw">{{ cellText(matrixView.totalRow, c) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </RdPage>
</template>

<style scoped>
.rd .confirm { margin: 0; padding: 3px 10px; align-items: center; flex-wrap: wrap; }
.rd .confirm svg { margin-top: 0; }
.rd .stat { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rd .pe-link { color: inherit; font-weight: 600; text-decoration: underline; }
.rd .pe-link:hover { text-decoration-thickness: 2px; }
.rd .cancel-form { flex-direction: column; align-items: stretch; gap: 8px; width: min(560px, 100%); padding: 10px 12px; }
.rd .cancel-reason { display: flex; flex-direction: column; gap: 4px; }
.rd .cancel-label { font-weight: 600; }
.rd .cancel-form textarea.field { min-height: 56px; font-family: inherit; font-size: 13px; color: var(--rd-ink); resize: vertical; }
.rd .cancel-count { align-self: flex-end; font-size: 12px; color: var(--rd-ink3); font-variant-numeric: tabular-nums; }
.rd .cancel-count.full { color: var(--rd-bad); }
.rd .cancel-err { display: flex; gap: 6px; align-items: flex-start; font-weight: 600; }
.rd .cancel-err svg { margin-top: 3px; flex: none; }
.rd .cancel-act { display: flex; gap: 8px; }
.rd .strip { align-items: center; }
.rd .strip svg { margin-top: 0; }
.rd .pw { margin: -4px 0 12px; font-size: 12.5px; }
.rd .pw summary { cursor: pointer; width: fit-content; }
.rd .pw ul { margin: 4px 0 0; padding-left: 20px; }
.rd .fin { margin-bottom: 12px; border-color: var(--rd-warn); }
.rd .fin .fin-lock { margin: 10px 0 8px; font-size: 13px; color: var(--rd-ink2); }
.rd .fin .fin-act { gap: 8px; margin-top: 4px; }
.rd .hd-l { gap: 10px; align-items: baseline; }
.rd .alloc-tbl { max-height: 560px; }
.rd .alloc-tbl table { min-width: 1100px; }
.rd .matrix th small { display: block; font-weight: 400; font-size: 11px; color: var(--rd-ink3); }
.rd .matrix td.detail { padding-left: 40px; }
.rd .matrix .tgl { padding: 0 5px; margin-right: 2px; }
</style>
