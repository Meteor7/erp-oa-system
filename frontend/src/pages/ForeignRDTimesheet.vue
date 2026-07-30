<script setup>
import { computed, ref, watch } from 'vue';
import { Card, Button, Spinner, createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { exportTableWorkbook } from '../lib/tableExport';
import { buildForeignEntityProjectPivot, buildMonthlyProjectRatePivot } from '../lib/timesheetPivot';

const TEXT = {
  title: '境外委托研发工时报表',
  monthSubtitle: '境外研发主体按项目的本期工时透视，含分配率',
  yearSubtitle: '按月查看全年境外项目工时分配率',
  accountingPeriod: '会计期间',
  entity: '主体',
  month: '月份',
  total: '合计',
  allocationRate: '分配率%',
  exportExcel: '导出Excel',
  noData: '本期无境外工时数据',
};

const exporting = ref(false);
const resource = createResource({
  url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd',
  method: 'GET',
  makeParams: () => ({ period: period.value, scope: periodScope.value }),
  auto: true,
});
watch(period, () => resource.reload());
watch(periodScope, () => resource.reload());

const rows = computed(() => (resource.data?.lines || []).map((row) => ({
  ...row,
  rd_project_code: row.rd_project_code || row.project_code,
  rd_project_key: row.rd_project_key || [row.project_code, row.project_name].filter(Boolean).join(' | '),
})));
const isYearScope = computed(() => periodScope.value === 'year');
const subtitle = computed(() => isYearScope.value ? TEXT.yearSubtitle : TEXT.monthSubtitle);
const viewLabel = computed(() => periodScopeLabel(period.value, periodScope.value));
const pivot = computed(() => buildForeignEntityProjectPivot(rows.value));
const yearlyPivot = computed(() => buildMonthlyProjectRatePivot(rows.value, Number(String(period.value).slice(0, 4))));
const activePivot = computed(() => isYearScope.value ? yearlyPivot.value : pivot.value);

const fmt = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtCell = (value) => Number(value || 0) ? fmt(value) : '';
const fmtRate = (value) => Number(value || 0) ? `${fmt(value)}%` : '';

async function exportReport() {
  exporting.value = true;
  try {
    const current = activePivot.value;
    const exportRows = isYearScope.value
      ? current.data.map((row) => ({ ...row, vals: row.vals.map(fmtRate), total: fmtRate(row.total) }))
      : [...current.data, { emp: TEXT.allocationRate, vals: current.rates.map((rate) => `${fmt(rate)}%`), total: `${fmt(current.grand)}h` }];
    await exportTableWorkbook({
      filename: `${TEXT.title}-${viewLabel.value}`,
      sheetName: TEXT.title,
      rows: exportRows,
      columns: [
        { label: isYearScope.value ? TEXT.month : TEXT.entity, key: isYearScope.value ? 'month' : 'emp', width: 28 },
        ...current.projects.map((project, index) => ({ label: project.label, value: (row) => row.vals?.[index] ?? '', width: 14 })),
        { label: TEXT.total, key: 'total', width: 14 },
      ],
    });
  } finally {
    exporting.value = false;
  }
}
</script>

<template>
  <Card :title="TEXT.title" :subtitle="subtitle">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
      <input v-model="period" type="month" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
      <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
        <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
      </div>
      <Button variant="subtle" :loading="exporting" :disabled="!activePivot.data.length" @click="exportReport">{{ TEXT.exportExcel }}</Button>
    </div>
    <div v-if="resource.loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!activePivot.data.length" class="py-6 text-sm text-gray-500">{{ TEXT.noData }}</div>
    <div v-else class="max-h-[70vh] overflow-auto overflow-x-auto rounded-lg border border-gray-100">
      <table class="w-full min-w-max border-separate border-spacing-0 text-sm">
        <thead class="sticky top-0 z-20 bg-white text-gray-500 shadow-sm">
          <tr>
            <th class="sticky left-0 z-30 min-w-[180px] bg-white px-3 py-3 text-left font-medium">{{ isYearScope ? TEXT.month : TEXT.entity }}</th>
            <th v-for="project in activePivot.projects" :key="project.id" class="min-w-[96px] px-3 py-3 text-right text-xs font-medium">{{ project.label }}</th>
            <th class="min-w-[96px] bg-white px-3 py-3 text-right font-medium">{{ TEXT.total }}</th>
          </tr>
        </thead>
        <tbody v-if="isYearScope">
          <tr v-for="row in yearlyPivot.data" :key="row.id" class="group hover:bg-gray-50">
            <td class="sticky left-0 z-10 whitespace-nowrap border-b border-gray-100 bg-white px-3 py-2 font-medium">{{ row.month }}</td>
            <td v-for="(value, index) in row.vals" :key="index" class="border-b border-gray-100 px-3 py-2 text-right tabular-nums">{{ fmtRate(value) }}</td>
            <td class="border-b border-gray-100 px-3 py-2 text-right font-semibold tabular-nums">{{ fmtRate(row.total) }}</td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr v-for="row in pivot.data" :key="row.id" class="group hover:bg-gray-50">
            <td class="sticky left-0 z-10 whitespace-nowrap border-b border-gray-100 bg-white px-3 py-2">{{ row.emp }}</td>
            <td v-for="(value, index) in row.vals" :key="index" class="border-b border-gray-100 px-3 py-2 text-right tabular-nums">{{ fmtCell(value) }}</td>
            <td class="border-b border-gray-100 px-3 py-2 text-right font-medium tabular-nums">{{ fmt(row.total) }}</td>
          </tr>
        </tbody>
        <tfoot v-if="!isYearScope" class="sticky bottom-0 z-20 bg-gray-50 text-gray-600 shadow-[0_-1px_0_rgba(229,231,235,1)]">
          <tr>
            <td class="sticky left-0 z-30 whitespace-nowrap bg-gray-50 px-3 py-2 font-medium">{{ TEXT.allocationRate }}</td>
            <td v-for="(rate, index) in pivot.rates" :key="index" class="px-3 py-2 text-right tabular-nums">{{ fmt(rate) }}%</td>
            <td class="px-3 py-2 text-right font-semibold tabular-nums">{{ fmt(pivot.grand) }}h</td>
          </tr>
        </tfoot>
      </table>
    </div>
    <p class="mt-3 text-xs text-gray-400">{{ viewLabel }} · 境外项目工时独立计算分配率</p>
  </Card>
</template>