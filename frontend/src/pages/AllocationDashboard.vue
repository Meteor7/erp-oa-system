<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Spinner, createResource } from "frappe-ui";
import RdPage from "../components/rd/RdPage.vue";
import RdPeriod from "../components/rd/RdPeriod.vue";
import RdSeg from "../components/rd/RdSeg.vue";
import RdKpi from "../components/rd/RdKpi.vue";
import RdIcon from "../components/rd/RdIcon.vue";
import { period, periodRouteSpec, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from "../lib/period";
import { bindRouteFilters, queryText } from "../lib/urlFilterState";
import { exportTableWorkbook } from "../lib/tableExport";
import { rankProjects } from "../lib/allocationGroups";
import { dashboardStatusTag, yearPreviewNote } from "../lib/previewTags";

const TEXT = {
  title: "研发费用汇总",
  subtitle: "按二级费用科目展开三级费用，汇总各项目承担金额",
  viewScope: "口径",
  exportExcel: "导出 Excel",
  totalAmount: "分摊合计",
  projectCount: "项目数",
  accountCount: "科目数",
  summaryTitle: "费用汇总",
  rankTitle: "各项目承担",
  rankHint: "金额由大到小，最多显示 8 个，其余合并为「其他」",
  noData: "当前范围暂无分摊看板数据。",
  level2: "2级费用科目",
  level3: "3级费用科目",
  total: "合计",
};

const modeOptions = [
  { value: "all", label: "汇总" },
  { value: "capitalized", label: "资本化" },
  { value: "expensed", label: "费用化" },
];

const dashboardMode = ref("all");
const dashboard = ref(null);
const loading = ref(false);
const exporting = ref(false);
const msg = ref("");

// 看板链接 ?period=YYYY-MM&project=<项目编号>：期间要在文件末尾第一次 load() 之前读好。
// project 不过滤数据（合计、其他项目的列还在，否则合计对不上），只把该项目定位出来：
// 汇总表里它的那一列和「各项目承担」里它的那一行高亮，页面上方有可清除的提示。
const projectFocus = ref("");
bindRouteFilters({
  route: useRoute(),
  router: useRouter(),
  specs: [periodRouteSpec(), {
    keys: ["project"],
    read: (query) => ({ project: queryText(query, "project") }),
    snapshot: () => ({ project: projectFocus.value }),
    apply: (state) => { projectFocus.value = state.project; },
    toQuery: (state) => (state.project ? { project: state.project } : {}),
    sources: [projectFocus],
  }],
});

const dashboardRes = createResource({
  url: "rayher_hr_payroll.api.allocation_entry.get_allocation_dashboard",
  method: "GET",
});

const projectColumns = computed(() => dashboard.value?.project_columns || []);
const summaryRows = computed(() => dashboard.value?.summary_rows || []);
const displayPeriod = computed(() => periodScopeLabel(period.value, periodScope.value));
// 月度：预览 / 已定版标签；全年：包含预览月份的提示。后端没给这些字段时都为空。
const statusTag = computed(() => dashboardStatusTag(dashboard.value, periodScope.value));
const previewNote = computed(() => {
  if (!dashboard.value) return "";
  if (periodScope.value === "year") return yearPreviewNote(dashboard.value);
  return statusTag.value?.hint || "";
});
const cards = computed(() => {
  const data = dashboard.value || {};
  return [
    { key: "total", label: TEXT.totalAmount, value: formatMoney(data.total_amount || 0), unit: "元", sub: `${displayPeriod.value} · ${data.mode_label || ""}` },
    { key: "project", label: TEXT.projectCount, value: data.project_count || 0, unit: "", sub: "参与分摊的项目" },
    { key: "account", label: TEXT.accountCount, value: `${data.second_level_count || 0} / ${data.third_level_count || 0}`, unit: "", sub: "二级科目 / 三级科目" },
  ];
});
const ranking = computed(() => rankProjects({ rows: summaryRows.value, projectColumns: projectColumns.value, topN: 8, otherLabel: "其他" }));

// 项目编号（project_code）或项目记录名都认；「其他」合并行不会被定位
function isFocusedProject(project) {
  const wanted = projectFocus.value;
  return Boolean(wanted) && (project?.project_code === wanted || project?.project === wanted);
}
function isFocusedRank(item) {
  const wanted = projectFocus.value;
  return Boolean(wanted) && !item.isOther && (item.code === wanted || item.key === wanted);
}
const focusedProject = computed(() => projectColumns.value.find(isFocusedProject) || null);
function revealFocus() {
  if (!projectFocus.value) return;
  nextTick(() => document.querySelector(".rd .matrix th.focus")?.scrollIntoView?.({ inline: "center", block: "nearest" }));
}

function formatMoney(value) {
  return Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function percent(share) {
  return `${(share * 100).toLocaleString("zh-CN", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function projectValue(row, project) {
  return Number(row?.projects?.[project.project] || 0);
}

function projectAmount(row, project) {
  const value = projectValue(row, project);
  return value ? formatMoney(value) : "·";
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

function rowClass(row) {
  if (isGrandTotal(row)) return "t";
  if (isSubtotal(row)) return "g";
  return "";
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
      filename: `研发费用看板-${displayPeriod.value}${statusTag.value?.cls === "warn" ? "（预览）" : ""}-${dashboard.value?.mode_label || "汇总"}`,
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
    msg.value = error?.message || "导出失败";
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
    dashboard.value = null;
    msg.value = (error && error.message) || "看板加载失败";
  } finally {
    loading.value = false;
    revealFocus();
  }
}

watch(period, () => load());
watch(periodScope, () => load());
watch(dashboardMode, () => load());
load();
</script>

<template>
  <RdPage :title="TEXT.title" :subtitle="TEXT.subtitle">
    <template #ctl>
      <span v-if="!loading && statusTag" class="stat" aria-live="polite">
        <span class="tag" :class="statusTag.cls"><RdIcon v-if="statusTag.cls === 'ok'" name="check" />{{ statusTag.text }}</span>
      </span>
      <RdPeriod />
    </template>

    <div v-if="dashboard" class="kpis">
      <RdKpi v-for="card in cards" :key="card.key" :label="card.label" :value="card.value" :unit="card.unit" :sub="card.sub" />
    </div>

    <div v-if="!loading && previewNote" class="note warn strip" role="status">
      <RdIcon name="alert" />
      <span class="grow">{{ previewNote }}</span>
    </div>

    <div class="bar">
      <div class="row">
        <span class="muted">{{ TEXT.viewScope }}</span>
        <RdSeg v-model="dashboardMode" :options="modeOptions" label="口径" />
        <RdSeg :model-value="periodScope" :options="PERIOD_SCOPES" label="期间范围" @update:model-value="setPeriodScope" />
      </div>
      <button type="button" class="btn" :disabled="exporting || !summaryRows.length" @click="exportCurrentAllocationDashboard"><RdIcon name="download" />{{ exporting ? "导出中…" : TEXT.exportExcel }}</button>
    </div>

    <div v-if="projectFocus && !loading && dashboard" class="note strip" :class="focusedProject ? 'info' : 'warn'" role="status" data-project-focus>
      <RdIcon :name="focusedProject ? 'check' : 'alert'" />
      <span v-if="focusedProject" class="grow">已定位到项目 <b>{{ focusedProject.project_code || focusedProject.project }}</b><span v-if="focusedProject.project_name"> {{ focusedProject.project_name }}</span>：汇总表和「各项目承担」里已高亮，合计仍是全部项目。</span>
      <span v-else class="grow">当前范围里没有项目 {{ projectFocus }} 的分摊数据。</span>
      <button type="button" class="btn sm" data-project-clear @click="projectFocus = ''">取消定位</button>
    </div>

    <div v-if="msg" class="note bad"><RdIcon name="alert" /><span class="grow">{{ msg }}</span></div>

    <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
    <div v-else-if="!summaryRows.length" class="card"><div class="bd muted">{{ TEXT.noData }}</div></div>
    <template v-else>
      <div v-if="ranking.items.length" class="card">
        <div class="hd"><b>{{ TEXT.rankTitle }}</b><span class="muted">{{ TEXT.rankHint }}</span></div>
        <div class="bd">
          <div v-for="item in ranking.items" :key="item.key" class="rank wide" :class="{ focus: isFocusedRank(item) }" :title="`${item.code}${item.name ? ' ' + item.name : ''} · ${formatMoney(item.value)} 元 · ${percent(item.share)}`">
            <span class="lbl"><b>{{ item.code }}</b> <span v-if="item.name" class="muted">{{ item.name }}</span></span>
            <span class="t"><i :style="{ width: item.width + '%' }"></i></span>
            <span class="val num"><b>{{ formatMoney(item.value) }}</b> <span class="muted">{{ percent(item.share) }}</span></span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="hd"><b>{{ TEXT.summaryTitle }}</b><span class="muted">{{ displayPeriod }} · {{ dashboard?.mode_label }} · 单位：元</span></div>
        <div class="tbl dash-tbl">
          <table class="matrix">
            <thead>
              <tr>
                <th class="c1">{{ TEXT.level2 }}</th>
                <th class="c2">{{ TEXT.level3 }}</th>
                <th v-for="project in projectColumns" :key="project.project" :title="project.project_name" class="r" :class="{ focus: isFocusedProject(project) }">{{ project.project_code || project.project }}</th>
                <th class="ct r">{{ TEXT.total }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in summaryRows" :key="index" :class="rowClass(row)">
                <td class="c1">{{ secondLevelText(row, index) }}</td>
                <td class="c2" :class="{ detail: !isSubtotal(row) && !isGrandTotal(row) }">{{ cellText(row.account_level_3) }}</td>
                <td v-for="project in projectColumns" :key="project.project" class="r num nw" :class="{ zero: !projectValue(row, project), focus: isFocusedProject(project) }">{{ projectAmount(row, project) }}</td>
                <td class="ct r num nw">{{ formatMoney(row.total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </RdPage>
</template>

<style scoped>
.rd .stat { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rd .strip { align-items: center; }
.rd .strip svg { margin-top: 0; }
.rd .dash-tbl { max-height: 72vh; }
.rd .dash-tbl table { min-width: 1120px; }
.rd .matrix .c1 { width: 180px; min-width: 180px; max-width: 180px; }
.rd .matrix .c2, .rd .matrix .ct { position: sticky; background: var(--rd-surface); z-index: 1; }
.rd .matrix th.c2, .rd .matrix th.ct { background: var(--rd-surface2); z-index: 3; }
.rd .matrix .c2 { left: 180px; width: 280px; min-width: 280px; border-right: 1px solid var(--rd-line); }
.rd .matrix .ct { right: 0; min-width: 120px; font-weight: 600; border-left: 1px solid var(--rd-line); }
.rd .matrix td.detail { padding-left: 24px; }
.rd .matrix tr.g td.c2, .rd .matrix tr.g td.ct, .rd .matrix tr.t td.c2, .rd .matrix tr.t td.ct { background: var(--rd-surface2); }
.rd .matrix tr.t td { padding-top: 7px; padding-bottom: 7px; }
.rd .rank.wide { grid-template-columns: minmax(110px, 200px) minmax(0, 1fr) minmax(150px, 220px); }
.rd .rank.wide .lbl { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rd .rank.wide .val { text-align: right; white-space: nowrap; }
.rd .rank.wide .val b { font-weight: 600; }
.rd .rank.focus { background: var(--rd-info-soft); border-radius: 8px; }
.rd .matrix th.focus, .rd .matrix td.focus { background: var(--rd-info-soft); }
.rd .matrix th.focus { color: var(--rd-info); }
</style>
