<script setup>
import { computed, ref, watch } from 'vue';
import { Spinner, createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { importForeignRdWorkbookFile, parseForeignRdPaste } from '../lib/foreignRdImport';
import { HOUR_STEP, daysOfHours, payloadRow, stepHours, validateForeignRows } from '../lib/foreignRdHours';
import { exportTableWorkbook } from '../lib/tableExport';
import RdPage from '../components/rd/RdPage.vue';
import RdPeriod from '../components/rd/RdPeriod.vue';
import RdSeg from '../components/rd/RdSeg.vue';
import RdKpi from '../components/rd/RdKpi.vue';
import RdIcon from '../components/rd/RdIcon.vue';

const DEFAULT_ENTITY = 'QIHENG DEMO OVERSEAS';
const foreignEntities = [DEFAULT_ENTITY];
const TEXT = {
  title: '境外委托研发工时',
  subtitle: '境外工时按月填报，境外费用按项目工时比例分摊，最终并入总汇总',
  entry: '境外工时填报',
  entity: '研发主体',
  project: '项目',
  occurrenceDays: '发生天数',
  hours: '工时（小时）',
  remark: '备注',
  addProject: '添加项目',
  save: '保存并重新计算费用',
  exportExcel: '导出 Excel',
  importedTotal: '导入费用合计',
  commonExpense: '公共费用',
  projectExpense: '项目费用',
  totalHours: '境外工时合计',
  saved: '已保存境外工时，费用已重新计算',
  noData: '暂无数据',
};
const SCOPE_OPTIONS = PERIOD_SCOPES.map((scope) => (scope.value === 'year' ? { ...scope, label: '年度（只读）' } : scope));

const rows = ref([]);
const data = ref({});
const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const message = ref('');
const errorMessage = ref('');
const loadError = ref('');
const batchOpen = ref(false);
const batchPasteText = ref('');
const batchRows = ref([]);
const batchErrors = ref([]);
const batchWorkbookInput = ref(null);
const pickerOpen = ref(false);
const pickerQuery = ref('');

const loader = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd', method: 'GET' });
const saver = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.save_foreign_rd' });
const options = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_project_options', method: 'GET', auto: true });

const projectOptions = computed(() => options.data?.projects || []);
const isYearScope = computed(() => periodScope.value === 'year');
const importedTotalAmount = computed(() => Number(data.value.total_amount || 0));
const commonAmount = computed(() => Number(data.value.common_amount || 0));
const directAmount = computed(() => Number(data.value.direct_amount || 0));
const unallocatedCommonAmount = computed(() => Number(data.value.unallocated_common_amount || 0));
const importChanged = computed(() => Boolean(data.value.stale));
const allocationSubmitted = computed(() => Boolean(data.value.allocation_submitted));
const totalHours = computed(() => activeRows().reduce((sum, row) => sum + Number(row.hours || 0), 0));
// 年度视图只读；本期国内分摊已提交时境外工时冻结，也按只读显示。
const readonly = computed(() => isYearScope.value || allocationSubmitted.value);
const foreignExpenseCards = computed(() => [
  { key: 'total', label: TEXT.importedTotal, value: importedTotalAmount.value, unit: '元', sub: '本期研发费用导入' },
  { key: 'common', label: TEXT.commonExpense, value: commonAmount.value, unit: '元', sub: '按境外工时比例分摊' },
  { key: 'direct', label: TEXT.projectExpense, value: directAmount.value, unit: '元', sub: '直接归属项目' },
  { key: 'hours', label: TEXT.totalHours, value: totalHours.value, unit: 'h', sub: `${fmtNum(daysOfHours(totalHours.value))} 天（工时 ÷ 8）` },
]);
const statusNotes = computed(() => {
  const notes = [];
  if (allocationSubmitted.value && !isYearScope.value) notes.push({ key: 'submitted', tone: 'info', icon: 'lock', text: '本期国内研发费用分摊已提交，境外工时已冻结；需要修改请先在分摊页撤销分摊。' });
  if (importChanged.value && !isYearScope.value) notes.push({ key: 'stale', tone: 'warn', icon: 'alert', text: `费用导入在上次保存后变了（上次 ${Number(data.value.saved_total_amount || 0).toFixed(2)} 元，现在 ${importedTotalAmount.value.toFixed(2)} 元），下面的金额已按最新导入重算，请核对后重新保存。` });
  if (unallocatedCommonAmount.value > 0) notes.push({ key: 'unallocated', tone: 'warn', icon: 'alert', text: `有 ${unallocatedCommonAmount.value.toFixed(2)} 元境外公共费用还没有境外工时可分，暂按"未分摊境外公共费用"计入未判定；录入境外工时并保存后会分到项目。` });
  return notes;
});

const availableProjects = computed(() => {
  const used = new Set(activeRows().map((row) => `${row.foreign_entity}|${row.project}`));
  return projectOptions.value.filter((project) => !used.has(`${DEFAULT_ENTITY}|${project.name}`));
});
const pickerList = computed(() => {
  const query = pickerQuery.value.trim().toLowerCase();
  const matched = availableProjects.value.filter((project) => !query || `${projectCode(project)} ${projectName(project)} ${project.name}`.toLowerCase().includes(query));
  return matched.slice(0, 80);
});

const fmtMoney = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function fmtNum(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function projectCode(project) {
  return project?.rd_project_code || project?.name || '';
}

function projectName(project) {
  return project?.project_name || project?.name || '';
}

function findProject(name) {
  return projectOptions.value.find((project) => project.name === name);
}

function normalizeRows(list = []) {
  return list.map((row) => ({
    foreign_entity: row.foreign_entity || DEFAULT_ENTITY,
    project: row.project || '',
    project_code: row.project_code || row.rd_project_code || '',
    project_name: row.project_name || '',
    // 工时（小时）是源头，天数 = 工时 ÷ 8，只用来显示。
    hours: Number(row.hours || 0),
    occurrence_days: daysOfHours(row.hours),
    remark: row.remark ?? row.description ?? '',
    period: row.period || '',
  }));
}

function rowHasInput(row) {
  return Boolean(row.project || Number(row.hours || 0) || String(row.remark || '').trim());
}

function activeRows() {
  return rows.value.filter(rowHasInput);
}

function stepRowHours(row, delta) {
  row.hours = stepHours(row.hours, delta);
}

function selectProject(row) {
  const project = findProject(row.project);
  row.project_code = projectCode(project);
  row.project_name = projectName(project);
}

function togglePicker() {
  pickerOpen.value = !pickerOpen.value;
  pickerQuery.value = '';
}

function addProject(project) {
  const row = {
    foreign_entity: DEFAULT_ENTITY,
    project: project.name,
    project_code: '',
    project_name: '',
    hours: 8,
    remark: '',
  };
  selectProject(row);
  rows.value.push(row);
  pickerOpen.value = false;
  pickerQuery.value = '';
}

function deleteRow(index) {
  rows.value.splice(index, 1);
  // 一行都没有时直接展开项目选择，相当于原来自动补的空行。
  if (!rows.value.length) pickerOpen.value = true;
}

function applyData(payload = {}) {
  data.value = payload;
  rows.value = normalizeRows(payload.lines || []);
  pickerOpen.value = !rows.value.length;
  pickerQuery.value = '';
  batchPasteText.value = '';
  batchRows.value = [];
  batchErrors.value = [];
}

async function load() {
  loading.value = true;
  message.value = '';
  errorMessage.value = '';
  loadError.value = '';
  try {
    applyData(await loader.submit({ period: period.value, scope: periodScope.value }) || {});
  } catch (error) {
    loadError.value = error?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

// 校验和保存的规则都在 lib/foreignRdHours.js：填小时（最多两位小数），天数 = 小时 ÷ 8，
// 每行不超过当月自然日数 × 8 小时。
function validateRows() {
  return validateForeignRows(activeRows(), { period: period.value, entities: foreignEntities, commonAmount: commonAmount.value });
}

function payloadRows() {
  return activeRows().map(payloadRow);
}

async function save() {
  message.value = '';
  errorMessage.value = '';
  const validation = validateRows();
  if (validation) {
    errorMessage.value = validation;
    return;
  }
  saving.value = true;
  try {
    applyData(await saver.submit({ period: period.value, rows: JSON.stringify(payloadRows()) }) || {});
    message.value = TEXT.saved;
  } catch (error) {
    errorMessage.value = error?.message || '保存失败';
  } finally {
    saving.value = false;
  }
}

function importOptions() {
  return { projects: projectOptions.value, foreignEntities, existingRows: activeRows(), period: period.value };
}

function openBatch() {
  batchOpen.value = true;
}

function closeBatch() {
  batchOpen.value = false;
}

function previewBatchPaste() {
  const result = parseForeignRdPaste(batchPasteText.value, importOptions());
  batchErrors.value = result.errors || [];
  batchRows.value = batchErrors.value.length ? [] : (result.rows || []);
}

function appendBatchRows() {
  if (!batchRows.value.length) return;
  rows.value = [...activeRows(), ...batchRows.value];
  batchPasteText.value = '';
  batchRows.value = [];
  batchErrors.value = [];
  pickerOpen.value = false;
  batchOpen.value = false;
}

function chooseWorkbook() {
  batchWorkbookInput.value?.click();
}

async function importWorkbook(event) {
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  const result = await importForeignRdWorkbookFile(file, importOptions());
  batchErrors.value = result.errors || [];
  batchRows.value = batchErrors.value.length ? [] : (result.rows || []);
}

async function exportCurrentForeignRd() {
  exporting.value = true;
  try {
    await exportTableWorkbook({
      filename: `境外委托研发工时-${periodScopeLabel(period.value, periodScope.value)}`,
      sheetName: '境外委托研发工时',
      rows: activeRows(),
      columns: [
        { label: isYearScope.value ? '月份' : TEXT.entity, value: (row) => isYearScope.value ? row.period : row.foreign_entity, width: 24 },
        { label: TEXT.project, value: (row) => `${row.project_code} ${row.project_name}`.trim(), width: 28 },
        { label: TEXT.hours, key: 'hours', width: 14 },
        { label: TEXT.occurrenceDays, value: (row) => daysOfHours(row.hours), width: 14 },
        { label: TEXT.remark, key: 'remark', width: 32 },
      ],
    });
  } finally {
    exporting.value = false;
  }
}

watch(period, load);
watch(periodScope, load);
load();
</script>

<template>
  <RdPage :title="TEXT.title" :subtitle="TEXT.subtitle">
    <template #ctl><RdPeriod /></template>

    <div class="bar">
      <RdSeg :model-value="periodScope" :options="SCOPE_OPTIONS" label="统计范围" @update:model-value="setPeriodScope" />
      <button type="button" class="btn" :disabled="exporting || !activeRows().length" @click="exportCurrentForeignRd"><RdIcon name="download" />{{ exporting ? '导出中…' : TEXT.exportExcel }}</button>
    </div>

    <div v-if="loading" class="card"><div class="bd" style="display:flex;justify-content:center"><Spinner class="w-6" /></div></div>
    <template v-else>
      <div v-if="loadError" class="note bad"><RdIcon name="alert" /><span class="grow">{{ loadError }}</span></div>

      <div class="kpis foreign-expense-cards">
        <RdKpi v-for="card in foreignExpenseCards" :key="card.key" :label="card.label" :value="card.key === 'hours' ? fmtNum(card.value) : fmtMoney(card.value)" :unit="card.unit" :sub="card.sub" />
      </div>

      <div class="card foreign-rd-status">
        <div class="hd">
          <b>分摊状态</b>
          <span class="row" style="gap:8px">
            <span class="muted">状态 {{ data.status || '-' }}<template v-if="data.expense_import"> · 来源费用表 {{ data.expense_import }}</template></span>
            <span v-if="!isYearScope" class="tag" :class="allocationSubmitted ? 'info' : 'ok'">{{ allocationSubmitted ? '已提交' : '未提交' }}</span>
          </span>
        </div>
        <div class="bd">
          <div v-for="note in statusNotes" :key="note.key" class="note" :class="note.tone"><RdIcon :name="note.icon" /><span class="grow">{{ note.text }}</span></div>
          <div v-if="!statusNotes.length" class="muted">{{ isYearScope ? '年度视图只读，按月份汇总显示。' : '没有需要处理的提示。' }}</div>
        </div>
      </div>

      <div class="card foreign-rd-entry">
        <div class="hd"><b>{{ TEXT.entry }}</b><span class="muted">{{ TEXT.entity }} {{ DEFAULT_ENTITY }} · 填小时，天数 = 小时 ÷ 8 · 每行不超过当月自然日数 × 8 小时</span></div>
        <div v-for="(row, index) in rows" :key="`${row.period || period}-${index}`" class="line">
          <div style="min-width:0">
            <div style="font-weight:500">{{ row.project_name || row.project }}</div>
            <div class="muted">
              {{ row.project_code }}<template v-if="isYearScope && row.period"> · {{ row.period }}</template>
              <select v-if="!readonly && foreignEntities.length > 1" v-model="row.foreign_entity" class="field" style="width:auto;padding:1px 6px;margin-left:6px" aria-label="研发主体">
                <option v-for="entity in foreignEntities" :key="entity" :value="entity">{{ entity }}</option>
              </select>
              <template v-else-if="foreignEntities.length > 1"> · {{ row.foreign_entity }}</template>
            </div>
          </div>
          <div v-if="readonly" class="num" style="font-weight:700">{{ fmtNum(row.hours) }} h</div>
          <div v-else class="step">
            <button type="button" aria-label="减 1 小时" @click="stepRowHours(row, -HOUR_STEP)">−</button>
            <input v-model="row.hours" inputmode="decimal" aria-label="工时（小时）" />
            <button type="button" aria-label="加 1 小时" @click="stepRowHours(row, HOUR_STEP)">＋</button>
          </div>
          <div class="num sub r">≈ {{ fmtNum(daysOfHours(row.hours)) }} 天</div>
          <span v-if="readonly" class="muted">{{ row.remark || '–' }}</span>
          <input v-else v-model="row.remark" class="field" placeholder="备注" :aria-label="TEXT.remark" />
          <button v-if="!readonly" type="button" class="btn quiet sm bad" :aria-label="`删除 ${row.project_code}`" @click="deleteRow(index)"><RdIcon name="trash" /></button>
          <span v-else></span>
        </div>
        <div v-if="!rows.length" class="bd muted" style="text-align:center">{{ readonly ? TEXT.noData : '本月还没有境外工时记录。从下面选一个项目开始，或批量导入。' }}</div>

        <div v-if="!readonly" class="addp">
          <div v-if="pickerOpen" style="margin-bottom:10px">
            <label class="input"><RdIcon name="search" /><input v-model="pickerQuery" :placeholder="`搜索项目名称或编号（共 ${availableProjects.length} 个项目可选）`" /></label>
            <div class="plist">
              <button v-for="project in pickerList" :key="project.name" type="button" class="pitem" @click="addProject(project)">
                <span><b style="font-weight:500">{{ projectName(project) }}</b> <span class="muted">{{ projectCode(project) }}</span></span>
              </button>
              <div v-if="!pickerList.length" class="muted" style="padding:12px">没有匹配的项目</div>
            </div>
          </div>
          <div class="row between">
            <button type="button" class="btn sm" @click="togglePicker"><RdIcon :name="pickerOpen ? 'x' : 'plus'" />{{ pickerOpen ? '收起' : TEXT.addProject }}</button>
            <button type="button" class="btn quiet sm" @click="openBatch"><RdIcon name="upload" />批量导入…</button>
          </div>
        </div>
      </div>

      <div v-if="!isYearScope" class="savebar">
        <div class="row"><span><b class="num">{{ fmtNum(totalHours) }}</b> <span class="muted">小时 · ≈ {{ fmtNum(daysOfHours(totalHours)) }} 天</span></span></div>
        <div class="row">
          <span v-if="message" style="color:var(--rd-ok);font-size:13px">{{ message }}</span>
          <span v-if="errorMessage" style="color:var(--rd-bad);font-size:13px">{{ errorMessage }}</span>
          <button type="button" class="btn pri" :disabled="allocationSubmitted || saving" @click="save">{{ saving ? '保存中…' : TEXT.save }}</button>
        </div>
      </div>
    </template>

    <Teleport to="body">
    <div v-if="batchOpen" class="rd foreign-rd-batch-import">
      <div class="rd-drawer-bg" @click="closeBatch"></div>
      <aside class="rd-drawer" role="dialog" aria-label="批量导入境外工时" @keydown.esc="closeBatch">
        <header>批量导入境外工时<button type="button" class="btn quiet sm" aria-label="关闭" @click="closeBatch"><RdIcon name="x" /></button></header>
        <div class="body">
          <div class="muted">每行一条：主体、项目代码、项目名称、工时（小时）、备注。支持制表符、逗号或多个空格分隔，也可以直接选择 Excel；老模板里只有“发生天数”的，按 1 天 = 8 小时换算。</div>
          <textarea v-model="batchPasteText" class="field" rows="5" placeholder="QIHENG DEMO OVERSEAS  RD16  EFEM-8-2LP-EG-A  12  验收"></textarea>
          <div class="row">
            <button type="button" class="btn" @click="chooseWorkbook"><RdIcon name="upload" />选择 Excel</button>
            <input ref="batchWorkbookInput" type="file" accept=".xlsx,.xls" style="display:none" @change="importWorkbook" />
            <button type="button" class="btn pri" @click="previewBatchPaste">预览导入</button>
          </div>
          <div v-if="batchErrors.length" class="note bad" style="margin:0">
            <RdIcon name="alert" />
            <span class="grow">有 {{ batchErrors.length }} 处错误，整批不会导入，请改正后重新预览。
              <span v-for="error in batchErrors" :key="error" style="display:block">{{ error }}</span>
            </span>
          </div>
          <div v-else-if="batchRows.length">
            <div v-for="(row, index) in batchRows" :key="index" class="row between" style="padding:7px 0;border-bottom:1px solid var(--rd-line)">
              <span>{{ row.project_code }} · {{ row.project_name }} · <b class="num">{{ fmtNum(row.hours) }}</b> 小时 · ≈ {{ fmtNum(daysOfHours(row.hours)) }} 天</span>
              <span class="tag ok">通过</span>
            </div>
          </div>
          <div v-else class="muted">预览后在这里显示校验结果。</div>
        </div>
        <footer>
          <button type="button" class="btn" @click="closeBatch">关闭</button>
          <button type="button" class="btn pri" :disabled="!batchRows.length" @click="appendBatchRows">加入表格</button>
        </footer>
      </aside>
    </div>
    </Teleport>
  </RdPage>
</template>
