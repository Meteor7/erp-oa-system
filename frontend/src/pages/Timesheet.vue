<script setup>
import { computed, ref, watch } from "vue";
import { Card, Button, Spinner, createResource } from "frappe-ui";
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { exportTableWorkbook } from "../lib/tableExport";
import { buildEmployeeProjectPivot, buildMonthlyProjectRatePivot } from "../lib/timesheetPivot";

const TEXT = {
  title: "\u7814\u53d1\u5de5\u65f6\u62a5\u8868",
  monthSubtitle: "\u7814\u53d1\u4eba\u5458\u6309\u9879\u76ee\u7684\u672c\u671f\u5de5\u65f6\u900f\u89c6\uff0c\u542b\u5206\u914d\u7387",
  yearSubtitle: "\u6309\u6708\u67e5\u770b\u5168\u5e74\u5404\u9879\u76ee\u5de5\u65f6\u5206\u914d\u7387",
  accountingPeriod: "\u4f1a\u8ba1\u671f\u95f4",
  employee: "\u5458\u5de5",
  month: "\u6708\u4efd",
  total: "\u5408\u8ba1",
  projectTotal: "\u9879\u76ee\u5408\u8ba1",
  allocationRate: "\u5206\u914d\u7387%",
  exportExcel: "\u5bfc\u51faExcel",
  noData: "\u672c\u671f\u65e0\u5de5\u65f6\u6570\u636e",
};

const exporting = ref(false);
const r = createResource({
  url: "rayher_hr_payroll.api.timesheet_entry.list_rd_hours",
  method: "GET",
  makeParams: () => ({ period: period.value, scope: periodScope.value }),
  auto: true,
});
watch(period, () => r.reload());
watch(periodScope, () => r.reload());

const rows = computed(() => r.data || []);
const isYearScope = computed(() => periodScope.value === "year");
const viewLabel = computed(() => periodScopeLabel(period.value, periodScope.value));
const viewSubtitle = computed(() => isYearScope.value ? TEXT.yearSubtitle : TEXT.monthSubtitle);
const pivot = computed(() => buildEmployeeProjectPivot(rows.value));
const yearlyPivot = computed(() => buildMonthlyProjectRatePivot(rows.value, Number(String(period.value).slice(0, 4))));
const activePivot = computed(() => isYearScope.value ? yearlyPivot.value : pivot.value);

const fmt = (n) => Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function fmtCell(n) {
  return Number(n || 0) ? fmt(n) : "";
}
function fmtRate(n) {
  return Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtYearRate(n) {
  return Number(n || 0) ? `${fmtRate(n)}%` : "";
}

async function exportCurrentTimesheetPivot() {
  exporting.value = true;
  try {
    const current = activePivot.value;
    const exportRows = isYearScope.value
      ? current.data.map((row) => ({
          ...row,
          vals: row.vals.map((value) => fmtYearRate(value)),
          total: fmtYearRate(row.total),
        }))
      : [
          ...current.data,
          { emp: TEXT.projectTotal, vals: current.projTotals, total: current.grand },
          { emp: TEXT.allocationRate, vals: current.rates.map((value) => `${fmtRate(value)}%`), total: "" },
        ];
    await exportTableWorkbook({
      filename: `${TEXT.title}-${viewLabel.value}`,
      sheetName: TEXT.title,
      rows: exportRows,
      columns: [
        { label: isYearScope.value ? TEXT.month : TEXT.employee, key: isYearScope.value ? "month" : "emp", width: 18 },
        ...current.projects.map((project, index) => ({
          label: project.label,
          value: (row) => row.vals?.[index] ?? "",
          width: 14,
        })),
        { label: TEXT.total, key: "total", width: 14 },
      ],
    });
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <Card :title="TEXT.title" :subtitle="viewSubtitle">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
      <input type="month" v-model="period" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
      </div>
      <Button variant="subtle" :loading="exporting" :disabled="!activePivot.data.length" @click="exportCurrentTimesheetPivot">{{ TEXT.exportExcel }}</Button>
    </div>
    <div v-if="r.loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!activePivot.data.length" class="py-6 text-sm text-gray-500">{{ TEXT.noData }}</div>
    <div v-else class="max-h-[70vh] overflow-auto overflow-x-auto rounded-lg border border-gray-100">
      <table class="w-full min-w-max border-separate border-spacing-0 text-sm">
        <thead class="sticky top-0 z-20 bg-white text-gray-500 shadow-sm">
          <tr>
            <th class="sticky left-0 z-30 min-w-[110px] bg-white px-3 py-3 text-left font-medium">{{ isYearScope ? TEXT.month : TEXT.employee }}</th>
            <th v-for="project in activePivot.projects" :key="project.id" class="min-w-[96px] px-3 py-3 text-right text-xs font-medium">
              {{ project.label }}
            </th>
            <th class="min-w-[96px] bg-white px-3 py-3 text-right font-medium">{{ TEXT.total }}</th>
          </tr>
        </thead>
        <tbody v-if="isYearScope">
          <tr v-for="row in yearlyPivot.data" :key="row.id" class="group hover:bg-gray-50">
            <td class="sticky left-0 z-10 whitespace-nowrap border-b border-gray-100 bg-white px-3 py-2 font-medium group-hover:bg-gray-50">{{ row.month }}</td>
            <td v-for="(value, index) in row.vals" :key="index" class="border-b border-gray-100 px-3 py-2 text-right tabular-nums">{{ fmtYearRate(value) }}</td>
            <td class="border-b border-gray-100 px-3 py-2 text-right font-semibold tabular-nums">{{ fmtYearRate(row.total) }}</td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr v-for="row in pivot.data" :key="row.id" class="group hover:bg-gray-50">
            <td class="sticky left-0 z-10 whitespace-nowrap border-b border-gray-100 bg-white px-3 py-2 group-hover:bg-gray-50">{{ row.emp }}</td>
            <td v-for="(v, i) in row.vals" :key="i" class="border-b border-gray-100 px-3 py-2 text-right tabular-nums">{{ fmtCell(v) }}</td>
            <td class="border-b border-gray-100 px-3 py-2 text-right font-medium tabular-nums">{{ fmt(row.total) }}</td>
          </tr>
        </tbody>
        <tfoot v-if="!isYearScope" class="sticky bottom-0 z-20 bg-gray-50 text-gray-600 shadow-[0_-1px_0_rgba(229,231,235,1)]">
          <tr>
            <td class="sticky left-0 z-30 whitespace-nowrap bg-gray-50 px-3 py-2 font-medium">{{ TEXT.allocationRate }}</td>
            <td v-for="(rate, i) in pivot.rates" :key="i" class="px-3 py-2 text-right tabular-nums">{{ fmtRate(rate) }}%</td>
            <td class="px-3 py-2 text-right font-semibold tabular-nums">{{ fmt(pivot.grand) }}h</td>
          </tr>
        </tfoot>
      </table>
    </div>
    <p class="mt-3 text-xs text-gray-400">{{ viewLabel }} &middot; {{ isYearScope ? TEXT.yearSubtitle : TEXT.monthSubtitle }}</p>
  </Card>
</template>
