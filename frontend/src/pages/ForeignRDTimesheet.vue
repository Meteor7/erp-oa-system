<script setup>
import { computed, ref, watch } from 'vue';
import { Spinner, createResource } from 'frappe-ui';
import { period, periodScope, periodYear, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { exportTableWorkbook } from '../lib/tableExport';
import { buildForeignEntityProjectPivot, buildMonthlyProjectRatePivot } from '../lib/timesheetPivot';
import { formatDelta, hoursDelta, hoursToDays, previousPeriod, projectNames, sumHours, topProject } from '../lib/rdReportView';
import RdPage from '../components/rd/RdPage.vue';
import RdPeriod from '../components/rd/RdPeriod.vue';
import RdSeg from '../components/rd/RdSeg.vue';
import RdKpi from '../components/rd/RdKpi.vue';
import RdIcon from '../components/rd/RdIcon.vue';

const FOREIGN_RD_URL = 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd';
const TEXT = {
  title: '境外研发工时报表',
  monthSubtitle: '境外研发主体按项目的本期工时透视，含分配率',
  yearSubtitle: '按月查看全年境外项目工时分配率',
  entity: '主体',
  month: '月份',
  total: '合计',
  allocationRate: '分配率%',
  exportExcel: '导出 Excel',
  noData: '本期无境外工时数据',
};

const exporting = ref(false);
const focusId = ref('');

function withProjectKeys(lines = []) {
  return (lines || []).map((row) => ({
    ...row,
    rd_project_code: row.rd_project_code || row.project_code,
    rd_project_key: row.rd_project_key || [row.project_code, row.project_name].filter(Boolean).join(' | '),
  }));
}

const resource = createResource({
  url: FOREIGN_RD_URL,
  method: 'GET',
  makeParams: () => ({ period: period.value, scope: periodScope.value }),
  auto: true,
});
watch(period, () => resource.reload());
watch(periodScope, () => resource.reload());

// 较上月：同一个接口再取上一个月，只在月度视图用。
const previous = createResource({ url: FOREIGN_RD_URL, method: 'GET' });
const previousHours = ref(null);
let previousToken = 0;
async function loadPrevious() {
  const token = ++previousToken;
  previousHours.value = null;
  const target = previousPeriod(period.value);
  if (periodScope.value !== 'month' || !target) return;
  try {
    const data = await previous.submit({ period: target, scope: 'month' });
    if (token === previousToken) previousHours.value = sumHours(data?.lines || []);
  } catch (error) {
    if (token === previousToken) previousHours.value = null;
  }
}
watch([period, periodScope], loadPrevious, { immediate: true });

const rows = computed(() => withProjectKeys(resource.data?.lines));
const isYearScope = computed(() => periodScope.value === 'year');
const subtitle = computed(() => isYearScope.value ? TEXT.yearSubtitle : TEXT.monthSubtitle);
const viewLabel = computed(() => periodScopeLabel(period.value, periodScope.value));
const pivot = computed(() => buildForeignEntityProjectPivot(rows.value));
const yearlyPivot = computed(() => buildMonthlyProjectRatePivot(rows.value, Number(String(period.value).slice(0, 4))));
const activePivot = computed(() => isYearScope.value ? yearlyPivot.value : pivot.value);
const names = computed(() => projectNames(rows.value));

const totalHours = computed(() => sumHours(rows.value));
const entities = computed(() => pivot.value.data.map((row) => row.emp));
const top = computed(() => topProject(pivot.value, names.value));
const hoursSub = computed(() => {
  const days = `${fmt(hoursToDays(totalHours.value))} 天`;
  if (isYearScope.value) return `${days} · ${periodYear()} 年累计`;
  const delta = formatDelta(hoursDelta(totalHours.value, previousHours.value));
  return delta ? `${days} · ${delta}` : days;
});

const fmt = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPercent = (value) => `${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const fmtCell = (value) => Number(value || 0) ? fmt(value) : '–';
const fmtRate = (value) => Number(value || 0) ? `${fmt(value)}%` : '';
const fmtYearRate = (value) => Number(value || 0) ? `${fmt(value)}%` : '–';
function nameOf(id) {
  return names.value[id] || '';
}
function toggleFocus(id) {
  focusId.value = focusId.value === id ? '' : id;
}
function dimmed(id) {
  return Boolean(focusId.value) && focusId.value !== id;
}

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
  <RdPage :title="TEXT.title" :subtitle="subtitle">
    <template #ctl><RdPeriod /></template>

    <div class="bar">
      <RdSeg :model-value="periodScope" :options="PERIOD_SCOPES" label="统计范围" @update:model-value="setPeriodScope" />
      <button type="button" class="btn" :disabled="exporting || !activePivot.data.length" @click="exportReport"><RdIcon name="download" />{{ exporting ? '导出中…' : TEXT.exportExcel }}</button>
    </div>

    <div v-if="resource.loading" class="card"><div class="bd" style="display:flex;justify-content:center"><Spinner class="w-6" /></div></div>
    <template v-else>
      <div class="kpis">
        <RdKpi label="境外工时合计" :value="fmt(totalHours)" unit="h" :sub="hoursSub" />
        <RdKpi label="研发主体" :value="entities.length" unit="个" :sub="entities.join('、')" />
        <RdKpi label="涉及项目" :value="pivot.projects.length" unit="个" :sub="top ? `占比最高 ${top.label} · ${fmtPercent(top.percent)}` : ''" />
      </div>

      <div class="card">
        <div class="hd">
          <b>{{ isYearScope ? '各月项目分配率' : '主体 × 项目工时' }}</b>
          <span class="muted">{{ isYearScope ? '境外工时独立计算，不与国内工时混算' : `${viewLabel} · 单位 小时，境外工时独立计算分配率` }}</span>
        </div>
        <div v-if="!activePivot.data.length" class="bd muted">{{ TEXT.noData }}</div>
        <div v-else class="tbl pv" style="max-height:70vh">
          <table>
            <thead>
              <tr>
                <th class="l">{{ isYearScope ? TEXT.month : TEXT.entity }}</th>
                <th v-for="project in activePivot.projects" :key="project.id" class="r" :class="{ focus: focusId === project.id }">
                  <button type="button" class="proj" :title="nameOf(project.id) || project.label" :aria-pressed="focusId === project.id" @click="toggleFocus(project.id)">
                    <span>{{ project.label }}</span>
                    <small v-if="nameOf(project.id) && nameOf(project.id) !== project.label">{{ nameOf(project.id) }}</small>
                  </button>
                </th>
                <th class="r">{{ TEXT.total }}</th>
              </tr>
            </thead>
            <tbody v-if="isYearScope">
              <tr v-for="row in yearlyPivot.data" :key="row.id">
                <td class="l nw">{{ row.month }}</td>
                <td v-for="(value, index) in row.vals" :key="index" class="r num" :class="{ dim: dimmed(yearlyPivot.projects[index].id) }">{{ fmtYearRate(value) }}</td>
                <td class="r num"><b>{{ fmtYearRate(row.total) }}</b></td>
              </tr>
            </tbody>
            <tbody v-else>
              <tr v-for="row in pivot.data" :key="row.id">
                <td class="l nw">{{ row.emp }}</td>
                <td v-for="(value, index) in row.vals" :key="index" class="r num" :class="{ dim: dimmed(pivot.projects[index].id) }">{{ fmtCell(value) }}</td>
                <td class="r num"><b>{{ fmt(row.total) }}</b></td>
              </tr>
            </tbody>
            <tfoot v-if="!isYearScope">
              <tr>
                <td class="l">{{ TEXT.allocationRate }}</td>
                <td v-for="(rate, index) in pivot.rates" :key="index" class="r num" :class="{ dim: dimmed(pivot.projects[index].id) }">{{ fmt(rate) }}%</td>
                <td class="r num">{{ fmt(pivot.grand) }}h</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </template>
  </RdPage>
</template>

<style scoped>
.pv th button.proj { display: flex; flex-direction: column; align-items: flex-end; width: 100%; max-width: 132px; margin-left: auto; text-align: right; line-height: 1.25; }
.pv th button.proj small { max-width: 132px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 400; color: var(--rd-ink3); }
.pv th button.proj:hover { color: var(--rd-brand-d); }
</style>
