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
  allocationEmptyState,
  buildAllocationMatrixFilters,
  hasAllocationData,
  loadAllocationStageMatrices,
} from "../lib/allocationView";
import { groupAllocationRows, stageLabel } from "../lib/allocationGroups";

const TEXT = {
  title: "研发费用台账",
  subtitle: "按工时分配率把费用池摊到各项目，并按项目资本化阶段汇总",
  view: "查看",
  actions: "操作",
  recalc: "重算分摊",
  recalcing: "重算中…",
  cancel: "撤销本期分摊",
  exportExcel: "导出 Excel",
  exporting: "导出中…",
  capitalized: "资本化",
  expensed: "费用化",
  capitalExpense: "资本 + 费用 合计",
  unknown: "未判定",
  projectTotal: "项目汇总",
  accountColumn: "科目（三级 › 四级）",
  ungrouped: "（未分类）",
  noBusinessData: "本期暂无数据。",
  noAllocationDetail: "已有费用或业务数据，但暂无可展示的项目分摊明细。",
  noDetailForMode: "当前口径暂无可展示的分摊明细。",
  confirmCancel: "确定撤销",
  confirmCancelTail: "的分摊吗？撤销后本期工时可以继续调整，调整后需要重新分摊。",
  confirmYes: "确认撤销",
  confirmNo: "返回",
  yearHint: "年度汇总各月已提交的分摊，只读",
  notAllocated: "本期尚未分摊，调整完工时后点「重算分摊」",
  matrixTitle: "分摊明细矩阵",
};

const modeOptions = [
  { value: "all", label: "汇总" },
  { value: "capitalized", label: "资本化" },
  { value: "expensed", label: "费用化" },
];

// 服务端报表里 voucher_no 列的英文表头，页面里统一显示为中文。
const COLUMN_LABELS = { "Voucher No": "凭证号" };

const columns = ref([]);
const result = ref([]);
const summary = ref(null);
const allocName = ref(null);
const loading = ref(false);
const recalcing = ref(false);
const canceling = ref(false);
const exporting = ref(false);
const confirmingCancel = ref(false);
const msg = ref("");
const msgBad = ref(false);
const allocationMode = ref("all");
const collapsed = ref({});

const allocRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.get_allocation", method: "GET" });
const matrixRes = createResource({ url: "frappe.desk.query_report.run", method: "GET" });
const exportMatrixRes = createResource({ url: "frappe.desk.query_report.run", method: "GET" });
const recalcRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.recalc_allocation" });
const cancelRes = createResource({ url: "rayher_hr_payroll.api.allocation_entry.cancel_allocation" });

const isYearScope = computed(() => periodScope.value === "year");
const displayPeriod = computed(() => periodScopeLabel(period.value, periodScope.value));
const allocationModeLabel = computed(() => modeOptions.find((option) => option.value === allocationMode.value)?.label || modeOptions[0].label);
const matrixFilters = computed(() => buildAllocationMatrixFilters({
  scope: periodScope.value,
  period: period.value,
  allocation: allocName.value,
  stage: allocationMode.value,
}));
const emptyText = computed(() => {
  const state = allocationEmptyState({
    hasData: Boolean(summary.value?.has_data),
    mode: allocationMode.value,
  });
  if (state === "no-detail") return TEXT.noAllocationDetail;
  if (state === "no-detail-for-mode") return TEXT.noDetailForMode;
  return TEXT.noBusinessData;
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
// 差额不为 0：只在月度提示（年度是只读汇总，不能在这里重算）
const showDiffStrip = computed(() => !loading.value && !isYearScope.value && reconcileOff.value);
// 月度还没有分摊单：提示先重算
const showNotAllocated = computed(() => !loading.value && !isYearScope.value && !allocName.value);
const statusTag = computed(() => {
  if (isYearScope.value) return { text: "年度 · 只读", cls: "" };
  if (allocName.value) return { text: "已提交", cls: "ok" };
  return { text: "未分摊", cls: "warn" };
});

const matrixView = computed(() => groupAllocationRows({ columns: columns.value, result: result.value }));
const labelColumns = computed(() => columns.value.filter((c) => !isCur(c) && !["account_level_3", "account_level_4"].includes(colKey(c))));
const moneyColumns = computed(() => columns.value.filter((c) => isCur(c)));

function setMessage(text, bad = false) {
  msg.value = text;
  msgBad.value = bad;
}

async function loadMatrix() {
  columns.value = [];
  result.value = [];
  if (!summary.value) return;
  const d = await matrixRes.submit({ report_name: "RD Allocation Matrix", filters: JSON.stringify(matrixFilters.value) });
  columns.value = d.columns || [];
  result.value = d.result || [];
}

async function load() {
  loading.value = true;
  confirmingCancel.value = false;
  setMessage("");
  try {
    const a = await allocRes.submit({ period: period.value, scope: periodScope.value });
    summary.value = hasAllocationData(a) ? a : null;
    allocName.value = a && a.name ? a.name : null;
    await loadMatrix();
  } finally {
    loading.value = false;
  }
}

async function recalc() {
  if (isYearScope.value) return;
  recalcing.value = true;
  confirmingCancel.value = false;
  setMessage("");
  try {
    const a = await recalcRes.submit({ period: period.value });
    if (recalcRes.error) {
      const er = recalcRes.error;
      setMessage((er.messages && er.messages.join("；")) || er.message || "重算失败", true);
      return;
    }
    summary.value = hasAllocationData(a) ? a : null;
    allocName.value = a && a.name ? a.name : null;
    await loadMatrix();
    setMessage("已重算：" + period.value);
  } catch (e) {
    setMessage((e && e.message) || "重算失败", true);
  } finally {
    recalcing.value = false;
  }
}

async function cancelAllocation() {
  if (!allocName.value || isYearScope.value) return;
  canceling.value = true;
  setMessage("");
  try {
    await cancelRes.submit({ period: period.value });
    if (cancelRes.error) {
      const er = cancelRes.error;
      setMessage((er.messages && er.messages.join("；")) || er.message || "撤销失败", true);
      return;
    }
    confirmingCancel.value = false;
    await load();
    setMessage("已撤销本期分摊，可继续调整工时");
  } catch (e) {
    setMessage((e && e.message) || "撤销失败", true);
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
      load: (filters) => exportMatrixRes.submit({
        report_name: "RD Allocation Matrix",
        filters: JSON.stringify(filters),
      }),
    });
    const filename = await exportAllocationWorkbook({
      period: `${displayPeriod.value}-${allocationModeLabel.value}`,
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
      <span v-if="!loading" class="stat">
        <span class="tag" :class="statusTag.cls"><RdIcon v-if="statusTag.cls === 'ok'" name="check" />{{ statusTag.text }}</span>
        <span v-if="isYearScope" class="muted">{{ TEXT.yearHint }}</span>
        <span v-else-if="allocName" class="muted">分摊单 {{ allocName }}</span>
      </span>
      <RdPeriod />
    </template>

    <div v-if="summary" class="kpis">
      <RdKpi v-for="card in summaryCards" :key="card.key" :label="card.label" :value="fmt(card.value)" unit="元" :sub="card.sub" :tone="card.tone" />
    </div>

    <div v-if="showDiffStrip" class="note warn strip" role="alert">
      <RdIcon name="alert" />
      <span class="grow"><b>分摊合计与费用池差额 {{ fmt(reconcileDiff) }} 元</b>（阶段合计与分摊明细对不上），请核对后重算。</span>
      <button type="button" class="btn sm pri" :disabled="recalcing || canceling" @click="recalc">{{ recalcing ? TEXT.recalcing : TEXT.recalc }}</button>
    </div>
    <div v-if="showNotAllocated" class="note warn strip">
      <RdIcon name="alert" />
      <span class="grow">{{ TEXT.notAllocated }}</span>
      <button type="button" class="btn sm pri" :disabled="recalcing || canceling" @click="recalc">{{ recalcing ? TEXT.recalcing : TEXT.recalc }}</button>
    </div>

    <div class="bar">
      <div class="row">
        <span class="muted">{{ TEXT.view }}</span>
        <RdSeg :model-value="periodScope" :options="PERIOD_SCOPES" label="期间范围" @update:model-value="setPeriodScope" />
        <RdSeg v-model="allocationMode" :options="modeOptions" label="口径" />
      </div>
      <div class="row">
        <span class="muted">{{ TEXT.actions }}</span>
        <button type="button" class="btn pri" :disabled="isYearScope || recalcing || canceling" :title="isYearScope ? '年度为只读汇总，请切换到月度重算' : undefined" @click="recalc"><RdIcon name="refresh" />{{ recalcing ? TEXT.recalcing : TEXT.recalc }}</button>
        <button v-if="summary" type="button" class="btn" :disabled="!canExport || exporting" @click="exportCurrentAllocation"><RdIcon name="download" />{{ exporting ? TEXT.exporting : TEXT.exportExcel }}</button>
        <template v-if="allocName && !isYearScope">
          <span v-if="confirmingCancel" class="note bad confirm">
            <span>{{ TEXT.confirmCancel }} {{ period }} {{ TEXT.confirmCancelTail }}</span>
            <button type="button" class="btn sm bad" :disabled="canceling" @click="cancelAllocation">{{ canceling ? TEXT.recalcing : TEXT.confirmYes }}</button>
            <button type="button" class="btn sm" :disabled="canceling" @click="confirmingCancel = false">{{ TEXT.confirmNo }}</button>
          </span>
          <button v-else type="button" class="btn bad" :disabled="recalcing" @click="confirmingCancel = true">{{ TEXT.cancel }}</button>
        </template>
      </div>
    </div>

    <div v-if="msg" class="note" :class="msgBad ? 'bad' : 'ok'"><RdIcon :name="msgBad ? 'alert' : 'check'" /><span class="grow">{{ msg }}</span></div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <template v-else>
      <div v-if="!result.length" class="card"><div class="bd muted">{{ emptyText }}</div></div>
      <div v-else class="card">
        <div class="hd">
          <div class="row hd-l"><b>{{ TEXT.matrixTitle }}</b><span class="muted">{{ displayPeriod }} · {{ allocName || displayPeriod }} · {{ totalRows }} 行明细</span></div>
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
.rd .strip { align-items: center; }
.rd .strip svg { margin-top: 0; }
.rd .hd-l { gap: 10px; align-items: baseline; }
.rd .alloc-tbl { max-height: 560px; }
.rd .alloc-tbl table { min-width: 1100px; }
.rd .matrix th small { display: block; font-weight: 400; font-size: 11px; color: var(--rd-ink3); }
.rd .matrix td.detail { padding-left: 40px; }
.rd .matrix .tgl { padding: 0 5px; margin-right: 2px; }
</style>
