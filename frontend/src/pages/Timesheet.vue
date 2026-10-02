<script setup>
import { computed, ref, watch } from "vue";
import { Spinner, createResource } from "frappe-ui";
import { period, periodScope, periodYear, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { exportTableWorkbook } from "../lib/tableExport";
import { buildEmployeeProjectPivot, buildMonthlyProjectRatePivot } from "../lib/timesheetPivot";
import { employeeShareRow, formatDelta, hoursDelta, previousPeriod, projectNames, sumHours, topProject } from "../lib/rdReportView";
import RdPage from "../components/rd/RdPage.vue";
import RdPeriod from "../components/rd/RdPeriod.vue";
import RdSeg from "../components/rd/RdSeg.vue";
import RdKpi from "../components/rd/RdKpi.vue";
import RdIcon from "../components/rd/RdIcon.vue";

const TEXT = {
  title: "研发工时报表",
  monthSubtitle: "研发人员按项目的本期工时透视，含分配率",
  yearSubtitle: "按月查看全年各项目工时分配率",
  employee: "员工",
  month: "月份",
  total: "合计",
  projectTotal: "项目合计",
  allocationRate: "分配率%",
  exportExcel: "导出 Excel",
  noData: "本期无工时数据",
};
const MODE_OPTIONS = [
  { value: "hours", label: "工时" },
  { value: "share", label: "个人占比" },
];

const exporting = ref(false);
const mode = ref("hours");
const focusId = ref("");

const r = createResource({
  url: "rayher_hr_payroll.api.timesheet_entry.list_rd_hours",
  method: "GET",
  makeParams: () => ({ period: period.value, scope: periodScope.value }),
  auto: true,
});
watch(period, () => r.reload());
watch(periodScope, () => r.reload());

// 较上月：同一个接口再取上一个月，只在月度视图用。
const previous = createResource({ url: "rayher_hr_payroll.api.timesheet_entry.list_rd_hours", method: "GET" });
const previousHours = ref(null);
let previousToken = 0;
async function loadPrevious() {
  const token = ++previousToken;
  previousHours.value = null;
  const target = previousPeriod(period.value);
  if (periodScope.value !== "month" || !target) return;
  try {
    const data = await previous.submit({ period: target, scope: "month" });
    if (token === previousToken) previousHours.value = sumHours(data || []);
  } catch (error) {
    if (token === previousToken) previousHours.value = null;
  }
}
watch([period, periodScope], loadPrevious, { immediate: true });

const rows = computed(() => r.data || []);
const isYearScope = computed(() => periodScope.value === "year");
const viewLabel = computed(() => periodScopeLabel(period.value, periodScope.value));
const viewSubtitle = computed(() => isYearScope.value ? TEXT.yearSubtitle : TEXT.monthSubtitle);
const pivot = computed(() => buildEmployeeProjectPivot(rows.value));
const yearlyPivot = computed(() => buildMonthlyProjectRatePivot(rows.value, Number(String(period.value).slice(0, 4))));
const activePivot = computed(() => isYearScope.value ? yearlyPivot.value : pivot.value);
const names = computed(() => projectNames(rows.value));
const shareRows = computed(() => pivot.value.data.map((row) => ({ ...row, shares: employeeShareRow(row.vals, row.total) })));

const totalHours = computed(() => sumHours(rows.value));
const participants = computed(() => pivot.value.data.filter((row) => row.total > 0).length);
const top = computed(() => topProject(pivot.value, names.value));
const hoursLabel = computed(() => isYearScope.value ? "全年累计工时" : "本月总工时");
const hoursSub = computed(() => isYearScope.value ? `${periodYear()} 年累计` : formatDelta(hoursDelta(totalHours.value, previousHours.value)));

const fmt = (n) => Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtPercent = (n) => `${Number(n || 0).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
function fmtCell(n) {
  return Number(n || 0) ? fmt(n) : "–";
}
function fmtRate(n) {
  return fmt(n);
}
function fmtYearRate(n) {
  return Number(n || 0) ? `${fmtRate(n)}%` : "–";
}
function exportYearRate(n) {
  return Number(n || 0) ? `${fmtRate(n)}%` : "";
}
function nameOf(id) {
  return names.value[id] || "";
}
function toggleFocus(id) {
  focusId.value = focusId.value === id ? "" : id;
}
function dimmed(id) {
  return Boolean(focusId.value) && focusId.value !== id;
}

async function exportCurrentTimesheetPivot() {
  exporting.value = true;
  try {
    const current = activePivot.value;
    const exportRows = isYearScope.value
      ? current.data.map((row) => ({
          ...row,
          vals: row.vals.map((value) => exportYearRate(value)),
          total: exportYearRate(row.total),
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
  <RdPage :title="TEXT.title" :subtitle="viewSubtitle">
    <template #ctl><RdPeriod /></template>

    <div class="bar">
      <div class="row">
        <RdSeg :model-value="periodScope" :options="PERIOD_SCOPES" label="统计范围" @update:model-value="setPeriodScope" />
        <RdSeg v-if="!isYearScope" v-model="mode" :options="MODE_OPTIONS" label="显示方式" />
      </div>
      <button type="button" class="btn" :disabled="exporting || !activePivot.data.length" @click="exportCurrentTimesheetPivot"><RdIcon name="download" />{{ exporting ? "导出中…" : TEXT.exportExcel }}</button>
    </div>

    <div v-if="r.loading" class="card"><div class="bd" style="display:flex;justify-content:center"><Spinner class="w-6" /></div></div>
    <template v-else>
      <div class="kpis">
        <RdKpi :label="hoursLabel" :value="fmt(totalHours)" unit="h" :sub="hoursSub" />
        <RdKpi label="参与人数" :value="participants" unit="人" sub="本期有工时记录" />
        <RdKpi label="占比最高项目" :value="top ? top.label : '–'" :sub="top ? `${top.name ? top.name + ' · ' : ''}${fmtPercent(top.percent)}` : ''" />
      </div>

      <div class="card">
        <div class="hd">
          <b>{{ isYearScope ? "各月项目分配率" : "员工 × 项目工时" }}</b>
          <span class="muted">{{ isYearScope ? "每行合计 100%" : `${viewLabel} · 单位 ${mode === "hours" ? "小时" : "占该员工工时的百分比"}` }}</span>
        </div>
        <div v-if="!activePivot.data.length" class="bd muted">{{ TEXT.noData }}</div>
        <div v-else class="tbl pv" style="max-height:70vh">
          <table>
            <thead>
              <tr>
                <th class="l">{{ isYearScope ? TEXT.month : TEXT.employee }}</th>
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
            <tbody v-else-if="mode === 'share'">
              <tr v-for="row in shareRows" :key="row.id">
                <td class="l nw">{{ row.emp }}</td>
                <td v-for="(value, index) in row.vals" :key="index" class="r num" :class="{ dim: dimmed(pivot.projects[index].id) }">{{ value ? fmtPercent(row.shares[index]) : "–" }}</td>
                <td class="r num"><b>{{ row.total ? "100.0%" : "–" }}</b></td>
              </tr>
            </tbody>
            <tbody v-else>
              <tr v-for="row in pivot.data" :key="row.id">
                <td class="l nw">{{ row.emp }}</td>
                <td v-for="(v, i) in row.vals" :key="i" class="r num" :class="{ dim: dimmed(pivot.projects[i].id) }">{{ fmtCell(v) }}</td>
                <td class="r num"><b>{{ fmt(row.total) }}</b></td>
              </tr>
            </tbody>
            <tfoot v-if="!isYearScope">
              <tr>
                <td class="l">{{ TEXT.projectTotal }} h</td>
                <td v-for="(value, i) in pivot.projTotals" :key="i" class="r num" :class="{ dim: dimmed(pivot.projects[i].id) }">{{ fmt(value) }}</td>
                <td class="r num">{{ fmt(pivot.grand) }}</td>
              </tr>
              <tr>
                <td class="l">{{ TEXT.allocationRate }}</td>
                <td v-for="(rate, i) in pivot.rates" :key="i" class="r num" :class="{ dim: dimmed(pivot.projects[i].id) }">{{ fmtRate(rate) }}%</td>
                <td class="r num">100.00%</td>
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
