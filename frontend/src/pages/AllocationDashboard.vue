<script setup>
import { computed, ref, watch } from "vue";
import { Card, Button, Spinner, createResource } from "frappe-ui";
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { exportTableWorkbook } from "../lib/tableExport";

const TEXT = {
  title: "\u7814\u53d1\u8d39\u7528\u6c47\u603b",
  subtitle: "\u6309\u4e8c\u7ea7\u8d39\u7528\u79d1\u76ee\u5c55\u5f00\u4e09\u7ea7\u8d39\u7528\uff0c\u6c47\u603b\u5404\u9879\u76ee\u627f\u62c5\u91d1\u989d",
  accountingPeriod: "\u4f1a\u8ba1\u671f\u95f4",
  viewScope: "\u53e3\u5f84",
  refresh: "\u5237\u65b0",
  exportExcel: "\u5bfc\u51faExcel",
  totalAmount: "\u5206\u644a\u5408\u8ba1",
  projectCount: "\u9879\u76ee\u6570",
  secondLevelCount: "\u4e8c\u7ea7\u79d1\u76ee",
  thirdLevelCount: "\u4e09\u7ea7\u8d39\u7528",
  summaryTitle: "\u8d39\u7528\u6c47\u603b",
  noData: "\u5f53\u524d\u8303\u56f4\u6682\u65e0\u5206\u644a\u770b\u677f\u6570\u636e\u3002",
  level2: "2\u7ea7\u8d39\u7528\u79d1\u76ee",
  level3: "3\u7ea7\u8d39\u7528\u79d1\u76ee",
  total: "\u5408\u8ba1",
};

const modeOptions = [
  { value: "all", label: "\u6c47\u603b" },
  { value: "capitalized", label: "\u8d44\u672c\u5316" },
  { value: "expensed", label: "\u8d39\u7528\u5316" },
];

const dashboardMode = ref("all");
const dashboard = ref(null);
const loading = ref(false);
const exporting = ref(false);
const msg = ref("");

const dashboardRes = createResource({
  url: "rayher_hr_payroll.api.allocation_entry.get_allocation_dashboard",
  method: "GET",
});

const projectColumns = computed(() => dashboard.value?.project_columns || []);
const summaryRows = computed(() => dashboard.value?.summary_rows || []);
const displayPeriod = computed(() => periodScopeLabel(period.value, periodScope.value));
const cards = computed(() => {
  const data = dashboard.value || {};
  return [
    { key: "total", label: TEXT.totalAmount, value: formatMoney(data.total_amount || 0), tone: "bg-emerald-50 text-emerald-700" },
    { key: "project", label: TEXT.projectCount, value: data.project_count || 0, tone: "bg-blue-50 text-blue-700" },
    { key: "l2", label: TEXT.secondLevelCount, value: data.second_level_count || 0, tone: "bg-amber-50 text-amber-700" },
    { key: "l3", label: TEXT.thirdLevelCount, value: data.third_level_count || 0, tone: "bg-slate-100 text-slate-700" },
  ];
});

function formatMoney(value) {
  return Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function projectAmount(row, project) {
  const value = Number(row?.projects?.[project.project] || 0);
  return value ? formatMoney(value) : "-";
}

function projectValue(row, project) {
  return Number(row?.projects?.[project.project] || 0);
}

function cellText(value) {
  return value || "-";
}

function isSubtotal(row) {
  return row?.row_type === "subtotal";
}

function isGrandTotal(row) {
  return row?.row_type === "grand_total";
}

function secondLevelText(row, index) {
  if (isGrandTotal(row)) return row.account_level_1 || TEXT.total;
  if (isSubtotal(row)) return row.account_level_2 || "";
  const previous = summaryRows.value[index - 1];
  return previous?.row_type === "detail" && previous.account_level_2 === row.account_level_2
    ? ""
    : row.account_level_2;
}

async function exportCurrentAllocationDashboard() {
  exporting.value = true;
  msg.value = "";
  try {
    await exportTableWorkbook({
      filename: `研发费用看板-${displayPeriod.value}-${dashboard.value?.mode_label || "汇总"}`,
      sheetName: "研发费用汇总",
      rows: summaryRows.value,
      columns: [
        { label: TEXT.level2, value: (row) => isGrandTotal(row) ? row.account_level_1 : row.account_level_2, width: 24 },
        { label: TEXT.level3, key: "account_level_3", width: 36 },
        ...projectColumns.value.map((project) => ({
          label: project.project_code || project.project,
          value: (row) => projectValue(row, project),
          width: 14,
        })),
        { label: TEXT.total, value: (row) => Number(row.total || 0), width: 16 },
      ],
    });
  } catch (error) {
    msg.value = error?.message || "\u5bfc\u51fa\u5931\u8d25";
  } finally {
    exporting.value = false;
  }
}

async function load() {
  loading.value = true;
  msg.value = "";
  try {
    dashboard.value = await dashboardRes.submit({
      period: period.value,
      scope: periodScope.value,
      mode: dashboardMode.value,
    });
  } catch (error) {
    msg.value = (error && error.message) || "\u770b\u677f\u52a0\u8f7d\u5931\u8d25";
  } finally {
    loading.value = false;
  }
}

watch(period, () => load());
watch(periodScope, () => load());
watch(dashboardMode, () => load());
load();
</script>

<template>
  <Card :title="TEXT.title" :subtitle="TEXT.subtitle">
    <div class="mb-5 flex flex-wrap items-center gap-2">
      <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
      <input type="month" v-model="period" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
      </div>
      <span class="ml-2 text-sm text-gray-500">{{ TEXT.viewScope }}</span>
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="option in modeOptions" :key="option.value" type="button" class="px-3 py-1.5 text-sm" :class="dashboardMode === option.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="dashboardMode = option.value">{{ option.label }}</button>
      </div>
      <Button variant="subtle" :loading="loading" @click="load">{{ TEXT.refresh }}</Button>
      <Button variant="subtle" :loading="exporting" :disabled="!summaryRows.length" @click="exportCurrentAllocationDashboard">{{ TEXT.exportExcel }}</Button>
      <span v-if="msg" class="text-xs text-red-600">{{ msg }}</span>
    </div>

    <div v-if="dashboard" class="mb-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
      <div v-for="card in cards" :key="card.key" class="rounded-lg border border-gray-200 bg-white p-3">
        <div class="flex items-center justify-between gap-3">
          <div>
            <div class="text-xs text-gray-500">{{ card.label }}</div>
            <div class="mt-1 text-xl font-semibold tabular-nums text-gray-900">{{ card.value }}</div>
          </div>
          <div :class="['h-9 w-9 rounded flex items-center justify-center text-xs font-semibold', card.tone]">{{ card.key.toUpperCase().slice(0, 2) }}</div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!summaryRows.length" class="py-6 text-sm text-gray-500">{{ TEXT.noData }}</div>
    <template v-else>
      <section>
        <div class="mb-2 flex items-end justify-between gap-3">
          <div>
            <h3 class="text-base font-semibold text-gray-900">{{ TEXT.summaryTitle }}</h3>
            <p class="text-xs text-gray-400">{{ displayPeriod }} · {{ dashboard?.mode_label }}</p>
          </div>
        </div>
        <div class="max-h-[72vh] overflow-auto rounded-lg border border-gray-200 bg-white">
          <table class="w-full min-w-[1120px] border-separate border-spacing-0 text-sm">
            <thead class="sticky top-0 z-30 bg-gray-100 text-gray-600 shadow-sm">
              <tr>
                <th class="sticky left-0 z-40 w-[180px] min-w-[180px] bg-gray-100 px-3 py-2.5 text-left">{{ TEXT.level2 }}</th>
                <th class="sticky left-[180px] z-40 w-[280px] min-w-[280px] bg-gray-100 px-3 py-2.5 text-left">{{ TEXT.level3 }}</th>
                <th v-for="project in projectColumns" :key="project.project" :title="project.project_name" class="min-w-[86px] whitespace-nowrap px-2 py-2.5 text-right font-medium">{{ project.project_code || project.project }}</th>
                <th class="sticky right-0 z-40 min-w-[120px] bg-gray-100 px-3 py-2.5 text-right">{{ TEXT.total }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in summaryRows" :key="index" :class="isGrandTotal(row) ? 'bg-gray-900 text-white font-semibold' : isSubtotal(row) ? 'bg-blue-50 font-semibold text-gray-900' : 'group hover:bg-gray-50'">
                <td class="sticky left-0 z-10 w-[180px] min-w-[180px] border-b border-gray-100 px-3 py-2.5" :class="isGrandTotal(row) ? 'bg-gray-900' : isSubtotal(row) ? 'bg-blue-50' : 'bg-white group-hover:bg-gray-50'">{{ secondLevelText(row, index) }}</td>
                <td class="sticky left-[180px] z-10 w-[280px] min-w-[280px] border-b border-gray-100 px-3 py-2.5" :class="isGrandTotal(row) ? 'bg-gray-900' : isSubtotal(row) ? 'bg-blue-50' : 'bg-white pl-6 group-hover:bg-gray-50'">{{ cellText(row.account_level_3) }}</td>
                <td v-for="project in projectColumns" :key="project.project" class="whitespace-nowrap border-b border-gray-100 px-2 py-2.5 text-right tabular-nums">{{ projectAmount(row, project) }}</td>
                <td class="sticky right-0 z-10 whitespace-nowrap border-b border-gray-100 px-3 py-2.5 text-right font-semibold tabular-nums" :class="isGrandTotal(row) ? 'bg-gray-900' : isSubtotal(row) ? 'bg-blue-50' : 'bg-white group-hover:bg-gray-50'">{{ formatMoney(row.total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </Card>
</template>
