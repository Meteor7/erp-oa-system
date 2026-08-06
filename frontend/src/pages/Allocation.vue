<script setup>
import { ref, computed, watch } from "vue";
import { Card, Button, Spinner, createResource } from "frappe-ui";
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { exportAllocationWorkbook } from "../lib/allocationExport";
import {
  allocationEmptyState,
  buildAllocationMatrixFilters,
  hasAllocationData,
  loadAllocationStageMatrices,
} from "../lib/allocationView";

const TEXT = {
  title: "\u7814\u53d1\u8d39\u7528\u53f0\u8d26",
  subtitle: "\u6309\u5de5\u65f6\u5206\u914d\u7387\u628a\u8d39\u7528\u6c60\u644a\u5230\u5404\u9879\u76ee\uff0c\u5e76\u6309\u9879\u76ee\u8d44\u672c\u5316\u9636\u6bb5\u6c47\u603b",
  accountingPeriod: "\u4f1a\u8ba1\u671f\u95f4",
  viewScope: "\u53e3\u5f84",
  recalc: "\u91cd\u7b97\u5206\u644a",
  cancel: "\u64a4\u9500\u672c\u671f\u5206\u644a",
  exportExcel: "\u5bfc\u51faExcel",
  capitalized: "\u8d44\u672c\u5316\u5408\u8ba1",
  expensed: "\u8d39\u7528\u5316\u5408\u8ba1",
  capitalExpense: "\u8d44\u672c\u548c\u8d39\u7528\u5408\u8ba1",
  unknown: "\u672a\u5224\u5b9a\u5408\u8ba1",
  projectTotal: "\u9879\u76ee\u6c47\u603b",
  noBusinessData: "\u672c\u671f\u6682\u65e0\u6570\u636e\u3002",
  noAllocationDetail: "\u5df2\u6709\u8d39\u7528\u6216\u4e1a\u52a1\u6570\u636e\uff0c\u4f46\u6682\u65e0\u53ef\u5c55\u793a\u7684\u9879\u76ee\u5206\u644a\u660e\u7ec6\u3002",
  noDetailForMode: "\u5f53\u524d\u53e3\u5f84\u6682\u65e0\u53ef\u5c55\u793a\u7684\u5206\u644a\u660e\u7ec6\u3002",
  confirmCancel: "\u786e\u5b9a\u64a4\u9500",
};

const modeOptions = [
  { value: "all", label: "\u6c47\u603b" },
  { value: "capitalized", label: "\u8d44\u672c\u5316" },
  { value: "expensed", label: "\u8d39\u7528\u5316" },
];

const columns = ref([]);
const result = ref([]);
const summary = ref(null);
const allocName = ref(null);
const loading = ref(false);
const recalcing = ref(false);
const canceling = ref(false);
const exporting = ref(false);
const msg = ref("");
const allocationMode = ref("all");

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
  return [
    { key: "capitalized", label: TEXT.capitalized, value: capitalized },
    { key: "expensed", label: TEXT.expensed, value: expensed },
    { key: "capitalExpense", label: TEXT.capitalExpense, value: capitalized + expensed },
    { key: "unknown", label: TEXT.unknown, value: Number(data.unknown || 0) },
  ];
});

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
  msg.value = "";
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
  msg.value = "";
  try {
    const a = await recalcRes.submit({ period: period.value });
    if (recalcRes.error) {
      const er = recalcRes.error;
      msg.value = (er.messages && er.messages.join("\uff1b")) || er.message || "\u91cd\u7b97\u5931\u8d25";
      return;
    }
    summary.value = hasAllocationData(a) ? a : null;
    allocName.value = a && a.name ? a.name : null;
    await loadMatrix();
    msg.value = "\u5df2\u91cd\u7b97\uff1a" + period.value;
  } catch (e) {
    msg.value = (e && e.message) || "\u91cd\u7b97\u5931\u8d25";
  } finally {
    recalcing.value = false;
  }
}

async function cancelAllocation() {
  if (!allocName.value || isYearScope.value) return;
  const confirmed = window.confirm(`${TEXT.confirmCancel} ${period.value} \u7684\u5206\u644a\u5417\uff1f\u64a4\u9500\u540e\u672c\u671f\u5de5\u65f6\u53ef\u4ee5\u7ee7\u7eed\u8c03\u6574\uff0c\u8c03\u6574\u540e\u9700\u8981\u91cd\u65b0\u5206\u644a\u3002`);
  if (!confirmed) return;
  canceling.value = true;
  msg.value = "";
  try {
    await cancelRes.submit({ period: period.value });
    if (cancelRes.error) {
      const er = cancelRes.error;
      msg.value = (er.messages && er.messages.join("\uff1b")) || er.message || "\u64a4\u9500\u5931\u8d25";
      return;
    }
    await load();
    msg.value = "\u5df2\u64a4\u9500\u672c\u671f\u5206\u644a\uff0c\u53ef\u7ee7\u7eed\u8c03\u6574\u5de5\u65f6";
  } catch (e) {
    msg.value = (e && e.message) || "\u64a4\u9500\u5931\u8d25";
  } finally {
    canceling.value = false;
  }
}

async function exportCurrentAllocation() {
  if (!canExport.value) return;
  exporting.value = true;
  msg.value = "";
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
      summary: viewSummary.value,
      columns: columns.value,
      result: result.value,
      stageMatrices,
    });
    msg.value = "\u5df2\u5bfc\u51fa\uff1a" + filename;
  } catch (e) {
    msg.value = (e && e.message) || "\u5bfc\u51fa\u5931\u8d25";
  } finally {
    exporting.value = false;
  }
}

const fmt = (n) => (typeof n === "number" ? n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : n);
const colKey = (c) => c.fieldname || c.id;
const colLabel = (c) => c.label || c.fieldname;
const isCur = (c) => c.fieldtype === "Currency";
function isTotalRow(row = {}) { return Boolean(row._is_total); }
function cellText(row, column) {
  const key = colKey(column);
  if (isTotalRow(row) && key === "account_level_3") return TEXT.projectTotal;
  const value = row[key];
  return isCur(column) ? fmt(Number(value || 0)) : value;
}

watch(period, () => load());
watch(periodScope, () => load());
watch(allocationMode, () => loadMatrix());
load();
</script>

<template>
  <Card :title="TEXT.title" :subtitle="TEXT.subtitle">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
      <input type="month" v-model="period" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
      </div>
      <span class="ml-2 text-sm text-gray-500">{{ TEXT.viewScope }}</span>
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="option in modeOptions" :key="option.value" type="button" class="px-3 py-1.5 text-sm" :class="allocationMode === option.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="allocationMode = option.value">{{ option.label }}</button>
      </div>
      <Button v-if="!isYearScope" variant="solid" :loading="recalcing" @click="recalc" class="ml-2">{{ TEXT.recalc }}</Button>
      <Button v-if="allocName && !isYearScope" variant="subtle" :loading="canceling" @click="cancelAllocation">{{ TEXT.cancel }}</Button>
      <Button v-if="summary" variant="subtle" :loading="exporting" :disabled="!canExport" @click="exportCurrentAllocation">{{ TEXT.exportExcel }}</Button>
      <span v-if="msg" class="ml-1 text-xs text-green-600">{{ msg }}</span>
    </div>

    <div v-if="summary" class="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      <div v-for="card in summaryCards" :key="card.key" class="rounded-lg bg-gray-50 p-3">
        <div class="text-xs text-gray-500">{{ card.label }}</div>
        <div class="text-lg font-semibold tabular-nums">{{ fmt(card.value) }}</div>
      </div>
    </div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!result.length" class="py-6 text-sm text-gray-500">{{ emptyText }}</div>
    <template v-else>
      <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table class="w-full min-w-[1280px] text-sm">
          <thead class="border-b bg-gray-50 text-gray-500">
            <tr>
              <th v-for="c in columns" :key="colKey(c)" class="whitespace-nowrap px-3 py-2" :class="isCur(c) ? 'text-right' : 'text-left'">{{ colLabel(c) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in result" :key="i" class="border-b last:border-0" :class="isTotalRow(row) ? 'bg-gray-50 font-semibold text-gray-900' : 'hover:bg-gray-50'">
              <td v-for="c in columns" :key="colKey(c)" class="whitespace-nowrap px-3 py-2 tabular-nums" :class="isCur(c) ? 'text-right' : 'text-left'">{{ cellText(row, c) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="mt-3 text-xs text-gray-400">{{ displayPeriod }} ? {{ allocName || displayPeriod }} ? {{ totalRows }} rows</p>
    </template>
  </Card>
</template>
