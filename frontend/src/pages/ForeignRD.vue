<script setup>
import { computed, ref, watch } from 'vue';
import { Card, Button, Spinner, createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { importForeignRdWorkbookFile, parseForeignRdPaste } from '../lib/foreignRdImport';
import { exportTableWorkbook } from '../lib/tableExport';

const TEXT = {
  title: '\u5883\u5916\u59d4\u6258\u7814\u53d1\u5de5\u65f6',
  subtitle: '\u5883\u5916\u5de5\u65f6\u5355\u72ec\u586b\u62a5\uff0c\u59d4\u6258\u7814\u53d1-\u5883\u5916\u8d39\u7528\u81ea\u52a8\u6309\u9879\u76ee\u5de5\u65f6\u6bd4\u4f8b\u5206\u644a\uff0c\u6700\u7ec8\u5e76\u5165\u603b\u6c47\u603b',
  entry: '\u5883\u5916\u5de5\u65f6\u586b\u62a5',
  lineTable: '\u672c\u671f\u5883\u5916\u5de5\u65f6\u8868',
  accountingPeriod: '\u4f1a\u8ba1\u671f\u95f4',
  status: '\u72b6\u6001',
  date: '\u65e5\u671f',
  projectCode: '\u9879\u76ee\u4ee3\u7801',
  projectName: '\u9879\u76ee\u540d\u79f0',
  activityType: '\u6d3b\u52a8\u7c7b\u578b',
  hours: '\u5de5\u65f6',
  hoursUnit: '\u5de5\u65f6(h)',
  description: '\u5de5\u4f5c\u5185\u5bb9',
  action: '\u64cd\u4f5c',
  choose: '\u8bf7\u9009\u62e9',
  chooseCode: '\u9009\u62e9\u9879\u76ee\u4ee3\u7801',
  chooseName: '\u9009\u62e9\u9879\u76ee\u540d\u79f0',
  expandCode: '\u5c55\u5f00\u9879\u76ee\u4ee3\u7801\u9009\u9879',
  expandName: '\u5c55\u5f00\u9879\u76ee\u540d\u79f0\u9009\u9879',
  noProject: '\u65e0\u5339\u914d\u9879\u76ee\uff0c\u8bf7\u5148\u5728\u9879\u76ee\u7ba1\u7406\u4e2d\u65b0\u589e',
  contentPlaceholder: '\u5b8c\u6210\u7684\u5883\u5916\u7814\u53d1\u5de5\u4f5c',
  addRow: '\u6dfb\u52a0\u4e00\u884c',
  remove: '\u5220\u9664',
  save: '\u4fdd\u5b58',
  importedTotal: '\u5bfc\u5165\u8d39\u7528\u5408\u8ba1',
  commonExpense: '\u516c\u5171\u8d39\u7528',
  projectExpense: '\u9879\u76ee\u8d39\u7528',
  commonAllocation: '\u516c\u5171\u5206\u644a',
  directAllocation: '\u9879\u76ee\u8d39\u7528',
  unallocatedCommon: '\u672a\u5206\u644a\u516c\u5171\u8d39\u7528',
  expenseImport: '\u6765\u6e90\u8d39\u7528\u8868',
  voucherNo: '\u51ed\u8bc1\u53f7',
  accountLevel4: '4\u7ea7\u8d39\u7528\u79d1\u76ee',
  sourceType: '\u5f52\u5c5e',
  sourceAmount: '\u91d1\u989d',
  directProject: '\u76f4\u63a5\u9879\u76ee',
  totalAmount: '\u5883\u5916\u59d4\u6258\u7814\u53d1\u603b\u91d1\u989d',
  totalHours: '\u5883\u5916\u5de5\u65f6\u5408\u8ba1',
  saved: '\u5df2\u4fdd\u5b58\u5883\u5916\u5de5\u65f6\uff0c\u8d39\u7528\u5df2\u6309\u5bfc\u5165\u8868\u91cd\u7b97',
  loadFailed: '\u52a0\u8f7d\u5931\u8d25',
  saveFailed: '\u4fdd\u5b58\u5931\u8d25',
  amountNeedsRows: '\u6709\u5883\u5916\u516c\u5171\u8d39\u7528\u65f6\uff0c\u5fc5\u987b\u5f55\u5165\u81f3\u5c11\u4e00\u6761\u5de5\u65f6',
  requiredFields: '\u8bf7\u586b\u5199\u65e5\u671f\u3001\u9879\u76ee\u4ee3\u7801\u3001\u9879\u76ee\u540d\u79f0\u3001\u6d3b\u52a8\u7c7b\u578b\u3001\u5de5\u65f6\u548c\u5de5\u4f5c\u5185\u5bb9',
  saveDraftBeforeDelete: '\u8bf7\u5148\u4fdd\u5b58\u6216\u6e05\u7a7a\u4e0a\u65b9\u5f85\u4fdd\u5b58\u5de5\u65f6\u540e\u518d\u5220\u9664\u660e\u7ec6',
  badHours: '\u5de5\u65f6\u5fc5\u987b\u5927\u4e8e 0\uff0c\u4e14\u5355\u65e5\u4e0d\u8d85\u8fc7 8 \u5c0f\u65f6',
  dateOutOfPeriod: '\u586b\u62a5\u65e5\u671f\u5fc5\u987b\u5728\u4f1a\u8ba1\u671f\u95f4\u5185',
  projectMismatch: '\u9879\u76ee\u4ee3\u7801\u548c\u9879\u76ee\u540d\u79f0\u5fc5\u987b\u5339\u914d\u9879\u76ee\u7ba1\u7406\u4e2d\u7684\u53ef\u586b\u62a5\u9879\u76ee',
  noData: '\u6682\u65e0\u6570\u636e',
  ratio: '\u6bd4\u4f8b',
  amountColumn: '\u5206\u644a\u91d1\u989d',
  stageLabel: '\u7814\u53d1\u9636\u6bb5',
  domesticAmount: '\u5883\u5185\u91d1\u989d',
  foreignAmount: '\u5883\u5916\u91d1\u989d',
  total: '\u5408\u8ba1',
  domesticHours: '\u5883\u5185\u5de5\u65f6',
  foreignHours: '\u5883\u5916\u5de5\u65f6',
  foreignSubtotal: '\u5883\u5916',
  domesticSubtotal: '\u5883\u5185',
  lineHint: '\u6309\u65e5\u671f\u3001\u9879\u76ee\u3001\u6d3b\u52a8\u7c7b\u578b\u8bb0\u5f55\u5883\u5916\u5de5\u65f6',
  batchTitle: '\u6279\u91cf\u7c98\u8d34 / Excel \u5bfc\u5165',
  batchHint: '\u683c\u5f0f\uff1a\u65e5\u671f\u3001\u9879\u76ee\u4ee3\u7801\u3001\u9879\u76ee\u540d\u79f0\u3001\u6d3b\u52a8\u7c7b\u578b\u3001\u5de5\u65f6\u3001\u5de5\u4f5c\u5185\u5bb9',
  previewImport: '\u9884\u89c8\u5bfc\u5165',
  importExcel: '\u5bfc\u5165Excel',
  appendImport: '\u8ffd\u52a0\u5230\u8868\u683c',
  clearImport: '\u6e05\u7a7a\u5bfc\u5165',
  importPlaceholder: '\u65e5\u671f\t\u9879\u76ee\u4ee3\u7801\t\u9879\u76ee\u540d\u79f0\t\u6d3b\u52a8\u7c7b\u578b\t\u5de5\u65f6(h)\t\u5de5\u4f5c\u5185\u5bb9\n2026/07/01\tRD14\tACONCA 7961\t\u9700\u6c42\u5206\u6790\t6\t\u5b8c\u6210\u5883\u5916\u7814\u53d1\u5de5\u4f5c',
  importNeedsPreview: '\u8bf7\u5148\u9884\u89c8\u901a\u8fc7\u540e\u518d\u8ffd\u52a0\u5230\u8868\u683c\u3002',
  importEmpty: '\u8bf7\u7c98\u8d34\u6216\u5bfc\u5165\u81f3\u5c11\u4e00\u884c\u5883\u5916\u5de5\u65f6\u3002',
  importPreviewed: '\u5df2\u9884\u89c8',
  importRows: '\u884c\u5883\u5916\u5de5\u65f6',
  importAppended: '\u5df2\u8ffd\u52a0\u5230\u4e0a\u65b9\u8868\u683c\uff0c\u8bf7\u70b9\u51fb\u4fdd\u5b58\u3002',
  excelFailed: 'Excel \u5bfc\u5165\u5931\u8d25',
};

const rows = ref([]);
const status = ref('');
const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const msg = ref('');
const errMsg = ref('');
const data = ref({});
const activeProjectPicker = ref('');
const batchPasteText = ref('');
const batchRows = ref([]);
const batchErrors = ref([]);
const batchMessage = ref('');
const batchWorkbookInput = ref(null);

const loader = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd', method: 'GET' });
const saver = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.save_foreign_rd' });
const options = createResource({ url: 'rayher_hr_payroll.api.timesheet_entry.get_rd_options', method: 'GET', auto: true });

const projectOptions = computed(() => options.data?.projects || []);
const activityTypes = computed(() => options.data?.activity_types || []);
const foreignLines = computed(() => data.value.lines || []);
const isYearScope = computed(() => periodScope.value === 'year');
const importedTotalAmount = computed(() => Number(data.value.total_amount || 0));
const commonAmount = computed(() => Number(data.value.common_amount || 0));
const directAmount = computed(() => Number(data.value.direct_amount || 0));
const unallocatedCommonAmount = computed(() => Number(data.value.unallocated_common_amount || 0));
const draftTotalHours = computed(() => activeRows(rows.value).reduce((sum, row) => sum + Number(row.hours || 0), 0));
const savedTotalHours = computed(() => Number(data.value.total_hours || 0));
const totalHours = computed(() => savedTotalHours.value + draftTotalHours.value);
const canSave = computed(() => !saving.value && !loading.value);
const visibleBatchErrors = computed(() => batchErrors.value.slice(0, 5));
const remainingBatchErrorCount = computed(() => Math.max(batchErrors.value.length - visibleBatchErrors.value.length, 0));
const batchPreviewTotal = computed(() => batchRows.value.reduce((sum, row) => sum + Number(row.hours || 0), 0));
const foreignExpenseCards = computed(() => [
  { key: 'total', label: TEXT.importedTotal, value: importedTotalAmount.value },
  { key: 'common', label: TEXT.commonExpense, value: commonAmount.value },
  { key: 'direct', label: TEXT.projectExpense, value: directAmount.value },
  { key: 'hours', label: TEXT.totalHours, value: totalHours.value, suffix: 'h' },
]);

async function exportCurrentForeignRd() {
  exporting.value = true;
  errMsg.value = '';
  try {
    await exportTableWorkbook({
      filename: `境外委托研发工时-${periodScopeLabel(period.value, periodScope.value)}`,
      sheetName: '境外委托研发工时',
      rows: foreignLines.value,
      columns: [
        { label: '会计期间', value: (row) => row.period || period.value, width: 14 },
        { label: '日期', key: 'work_date', width: 14 },
        { label: '项目代码', key: 'project_code', width: 14 },
        { label: '项目名称', key: 'project_name', width: 28 },
        { label: '活动类型', key: 'activity_type', width: 18 },
        { label: '工时(h)', value: (row) => Number(row.hours || 0), width: 12 },
        { label: '工作内容', key: 'description', width: 36 },
        { label: '比例', value: (row) => Number(row.ratio || 0), width: 12 },
        { label: '公共分摊', value: (row) => Number(row.common_allocated_amount || 0), width: 16 },
        { label: '项目费用', value: (row) => Number(row.direct_allocated_amount || 0), width: 16 },
        { label: '分摊金额', value: (row) => Number(row.allocated_amount || 0), width: 16 },
      ],
    });
  } catch (error) {
    errMsg.value = error?.message || '导出失败';
  } finally {
    exporting.value = false;
  }
}

function firstDayOfPeriod(value = period.value) {
  return value ? `${value}-01` : '';
}

function lastDayOfPeriod(value = period.value) {
  const [year, month] = String(value || '').split('-').map(Number);
  if (!year || !month) return '';
  const day = new Date(year, month, 0).getDate();
  return `${value}-${String(day).padStart(2, '0')}`;
}

const dateMin = computed(() => firstDayOfPeriod());
const dateMax = computed(() => lastDayOfPeriod());

function activityName(activity) {
  return activity?.name || activity || '';
}

function defaultActivityType() {
  return activityName(activityTypes.value[0]) || '';
}

function projectCode(project) {
  return project?.rd_project_code || project?.name || '';
}

function projectName(project) {
  return project?.project_name || project?.name || '';
}

function projectLabel(project) {
  const code = projectCode(project);
  const name = projectName(project);
  return code && name ? `${code} | ${name}` : code || name;
}

function blankRow() {
  return {
    work_date: firstDayOfPeriod(),
    project: '',
    project_code: '',
    project_name: '',
    activity_type: defaultActivityType(),
    hours: '',
    description: '',
  };
}

function normalizeRows(list = []) {
  return list.map((row) => ({
    work_date: String(row.work_date || firstDayOfPeriod()).slice(0, 10),
    project: row.project || '',
    project_code: row.project_code || '',
    project_name: row.project_name || '',
    activity_type: row.activity_type || defaultActivityType(),
    hours: row.hours ?? '',
    description: row.description || '',
  }));
}

function rowHasInput(row) {
  return Boolean(row.project || row.project_code || row.project_name || row.hours || row.description);
}

function activeRows(list = rows.value) {
  return list.filter(rowHasInput);
}

function addRow() {
  rows.value.push(blankRow());
}

function delRow(index) {
  rows.value.splice(index, 1);
  if (!rows.value.length) addRow();
}

function projectSearchText(project) {
  return [projectCode(project), projectName(project), project?.rd_project_key || ''].join(' ').toLowerCase();
}

function filteredProjects(value) {
  const query = String(value || '').trim().toLowerCase();
  if (!query) return projectOptions.value;
  return projectOptions.value.filter((project) => projectSearchText(project).includes(query));
}

function filteredCodeProjects(row) {
  return filteredProjects(row.project_code);
}

function filteredNameProjects(row) {
  return filteredProjects(row.project_name);
}

function findProjectByCode(value) {
  const code = String(value || '').trim();
  if (!code) return null;
  return projectOptions.value.find((project) => projectCode(project) === code) || null;
}

function findProjectByName(value) {
  const name = String(value || '').trim();
  if (!name) return null;
  return projectOptions.value.find((project) => projectName(project) === name) || null;
}

function findProjectByIdentity(codeValue, nameValue) {
  const code = String(codeValue || '').trim();
  const name = String(nameValue || '').trim();
  if (!code || !name) return null;
  return projectOptions.value.find((project) => projectCode(project) === code && projectName(project) === name) || null;
}

function fillProject(row, project) {
  if (!project) return;
  row.project = project.name;
  row.project_code = projectCode(project);
  row.project_name = projectName(project);
}

function syncProjectCode(row) {
  const project = findProjectByCode(row.project_code);
  if (project) fillProject(row, project);
  else row.project = '';
}

function syncProjectName(row) {
  const project = findProjectByName(row.project_name);
  if (project) fillProject(row, project);
  else row.project = '';
}

function syncProjectBoth(row) {
  const project = findProjectByIdentity(row.project_code, row.project_name);
  row.project = project?.name || '';
  return project;
}

function pickerKey(index, kind) {
  return `${index}:${kind}`;
}

function openProjectPicker(index, kind) {
  activeProjectPicker.value = pickerKey(index, kind);
}

function closeProjectPickerLater() {
  setTimeout(() => {
    activeProjectPicker.value = '';
  }, 120);
}

function toggleProjectPicker(index, kind) {
  const key = pickerKey(index, kind);
  activeProjectPicker.value = activeProjectPicker.value === key ? '' : key;
}

function chooseProject(row, project) {
  fillProject(row, project);
  activeProjectPicker.value = '';
}

function importOptions() {
  return {
    projects: projectOptions.value,
    activityTypes: activityTypes.value,
    period: period.value,
    existingRows: [...foreignLines.value, ...activeRows()],
  };
}

function clearBatchImport() {
  batchPasteText.value = '';
  batchRows.value = [];
  batchErrors.value = [];
  batchMessage.value = '';
}

function applyBatchResult(result, source = TEXT.importPreviewed) {
  batchErrors.value = result.errors || [];
  batchRows.value = batchErrors.value.length ? [] : (result.rows || []);
  batchMessage.value = '';
  if (batchErrors.value.length) return;
  if (!batchRows.value.length) {
    batchErrors.value = [TEXT.importEmpty];
    return;
  }
  batchMessage.value = `${source} ${batchRows.value.length} ${TEXT.importRows}，${TEXT.totalHours} ${fmt(batchPreviewTotal.value)} h`;
}

function previewBatchPaste() {
  errMsg.value = '';
  applyBatchResult(parseForeignRdPaste(batchPasteText.value, importOptions()), TEXT.importPreviewed);
}

function chooseForeignWorkbook() {
  batchWorkbookInput.value?.click();
}

async function importForeignWorkbookRows(event) {
  errMsg.value = '';
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const result = await importForeignRdWorkbookFile(file, importOptions());
    applyBatchResult(result, 'Excel ' + TEXT.importPreviewed);
  } catch (error) {
    batchRows.value = [];
    batchMessage.value = '';
    batchErrors.value = [error?.message || TEXT.excelFailed];
  }
}

function appendBatchRows() {
  errMsg.value = '';
  if (!batchRows.value.length) {
    batchErrors.value = [TEXT.importNeedsPreview];
    return;
  }
  const existing = activeRows().map((row) => ({ ...row }));
  rows.value = [...existing, ...batchRows.value.map((row) => ({ ...row }))];
  batchPasteText.value = '';
  batchRows.value = [];
  batchErrors.value = [];
  batchMessage.value = TEXT.importAppended;
}

function resetDraftRows() {
  rows.value = [blankRow()];
}

function applyData(payload = {}) {
  data.value = payload;
  status.value = payload.status || '';
  resetDraftRows();
}

async function load() {
  loading.value = true;
  errMsg.value = '';
  msg.value = '';
  try {
    const payload = await loader.submit({ period: period.value, scope: periodScope.value });
    applyData(payload || {});
  } catch (error) {
    errMsg.value = (error && error.message) || TEXT.loadFailed;
  } finally {
    loading.value = false;
  }
}

function validateRows() {
  const filledRows = activeRows();
  const combinedRows = [...foreignLines.value, ...filledRows];
  if (commonAmount.value > 0 && !combinedRows.length) return TEXT.amountNeedsRows;
  if (!filledRows.length) return TEXT.requiredFields;
  const dailyTotals = new Map();
  for (const row of foreignLines.value) {
    const workDate = String(row.work_date || '').slice(0, 10);
    if (!workDate) continue;
    dailyTotals.set(workDate, Number(dailyTotals.get(workDate) || 0) + Number(row.hours || 0));
  }
  for (let index = 0; index < filledRows.length; index += 1) {
    const row = filledRows[index];
    if (!row.work_date || !row.project_code.trim() || !row.project_name.trim() || !row.activity_type || !row.description.trim()) {
      return `${index + 1}. ${TEXT.requiredFields}`;
    }
    const hours = Number(row.hours || 0);
    if (!Number.isFinite(hours) || hours <= 0 || hours > 8) {
      return `${index + 1}. ${TEXT.badHours}`;
    }
    if (row.work_date < dateMin.value || row.work_date > dateMax.value) {
      return `${index + 1}. ${TEXT.dateOutOfPeriod}`;
    }
    const dayTotal = Number(dailyTotals.get(row.work_date) || 0) + hours;
    if (dayTotal > 8) {
      return `${index + 1}. ${row.work_date} ${TEXT.badHours}`;
    }
    dailyTotals.set(row.work_date, dayTotal);
    if (!syncProjectBoth(row)) {
      return `${index + 1}. ${TEXT.projectMismatch}`;
    }
  }
  return '';
}

function toPayloadRow(row) {
  return {
    work_date: String(row.work_date || '').slice(0, 10),
    project: row.project,
    project_code: String(row.project_code || '').trim(),
    project_name: String(row.project_name || '').trim(),
    activity_type: row.activity_type,
    hours: Number(row.hours || 0),
    description: String(row.description || '').trim(),
  };
}

function savedRowsForPayload(excludeIndex = -1) {
  return foreignLines.value
    .filter((_row, index) => index !== excludeIndex)
    .map(toPayloadRow);
}

async function persistRows(payloadRows) {
  const payload = await saver.submit({ period: period.value, rows: JSON.stringify(payloadRows) });
  applyData(payload || {});
  return payload;
}

async function save() {
  errMsg.value = '';
  msg.value = '';
  const error = validateRows();
  if (error) {
    errMsg.value = error;
    return;
  }
  saving.value = true;
  try {
    const payloadRows = [
      ...savedRowsForPayload(),
      ...activeRows().map(toPayloadRow),
    ];
    await persistRows(payloadRows);
    msg.value = TEXT.saved;
  } catch (error) {
    errMsg.value = (error && error.message) || TEXT.saveFailed;
  } finally {
    saving.value = false;
  }
}

async function deleteSavedLine(index) {
  if (isYearScope.value) return;
  errMsg.value = '';
  msg.value = '';
  if (activeRows().length) {
    errMsg.value = TEXT.saveDraftBeforeDelete;
    return;
  }
  saving.value = true;
  try {
    await persistRows(savedRowsForPayload(index));
    msg.value = TEXT.saved;
  } catch (error) {
    errMsg.value = (error && error.message) || TEXT.saveFailed;
  } finally {
    saving.value = false;
  }
}

function fmt(n) {
  return Number(n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPercent(n) {
  return `${fmt(n)}%`;
}

watch(activityTypes, () => {
  rows.value.forEach((row) => {
    if (!row.activity_type) row.activity_type = defaultActivityType();
  });
}, { immediate: true });

watch(periodScope, () => load());

watch(period, (next, previous) => {
  rows.value.forEach((row) => {
    if (!row.work_date || row.work_date === firstDayOfPeriod(previous)) {
      row.work_date = firstDayOfPeriod(next);
    }
  });
  clearBatchImport();
  load();
});

load();
</script>

<template>
  <div class="space-y-5">
    <Card :title="TEXT.title" :subtitle="TEXT.subtitle">
      <div class="mb-5 flex flex-wrap items-center gap-3">
        <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
        <input v-model="period" type="month" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
        <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
          <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
        </div>
        <Button variant="subtle" :loading="exporting" :disabled="!foreignLines.length" @click="exportCurrentForeignRd">导出Excel</Button>
        <span v-if="status" class="text-xs text-gray-400">{{ TEXT.status }}: {{ status }}</span>
        <span v-if="data.expense_import" class="text-xs text-gray-400">{{ TEXT.expenseImport }}: {{ data.expense_import }}</span>
        <span v-if="msg" class="text-xs text-green-700">{{ msg }}</span>
        <span v-if="errMsg" class="text-xs text-red-600">{{ errMsg }}</span>
      </div>
      <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
      <template v-else>
        <div class="mb-4 grid gap-3 md:grid-cols-4 foreign-expense-cards">
          <div v-for="card in foreignExpenseCards" :key="card.key" class="rounded border border-gray-200 bg-gray-50 px-4 py-3">
            <div class="text-xs text-gray-500">{{ card.label }}</div>
            <div class="mt-1 text-xl font-semibold tabular-nums text-gray-900">{{ fmt(card.value) }}<span v-if="card.suffix" class="ml-1 text-sm font-normal text-gray-500">{{ card.suffix }}</span></div>
          </div>
        </div>
        <div v-if="unallocatedCommonAmount" class="mb-4 rounded border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-700">
          {{ TEXT.unallocatedCommon }} {{ fmt(unallocatedCommonAmount) }}
        </div>
        <div class="grid gap-4">
          <section v-if="!isYearScope" class="rounded border border-gray-200 bg-gray-50 p-4 overflow-visible">
            <h3 class="mb-3 text-base font-semibold text-gray-900">{{ TEXT.entry }}</h3>
            <div class="foreign-rd-entry-table overflow-x-auto overflow-y-visible rounded border border-gray-200 bg-white pb-36">
              <table class="w-full min-w-[1280px] text-sm">
                <thead class="bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th class="px-3 py-2 text-left w-[150px]">{{ TEXT.date }}</th>
                    <th class="px-3 py-2 text-left w-[210px]">{{ TEXT.projectCode }}</th>
                    <th class="px-3 py-2 text-left min-w-[300px]">{{ TEXT.projectName }}</th>
                    <th class="px-3 py-2 text-left w-[150px]">{{ TEXT.activityType }}</th>
                    <th class="px-3 py-2 text-right w-[110px]">{{ TEXT.hoursUnit }}</th>
                    <th class="px-3 py-2 text-left min-w-[300px]">{{ TEXT.description }}</th>
                    <th class="px-3 py-2 text-right w-[70px]">{{ TEXT.action }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, index) in rows" :key="index" class="foreign-rd-entry-row border-t align-top">
                    <td class="px-3 py-2"><input v-model="row.work_date" type="date" :min="dateMin" :max="dateMax" class="w-full rounded border border-gray-300 bg-white px-2 py-2 text-sm" /></td>
                    <td class="px-3 py-2"><div class="relative overflow-visible"><input v-model="row.project_code" class="w-full rounded border border-gray-300 bg-white px-3 py-2 pr-8 text-sm" :placeholder="TEXT.chooseCode" @focus="openProjectPicker(index, 'code')" @input="openProjectPicker(index, 'code')" @change="syncProjectCode(row)" @blur="closeProjectPickerLater" /><button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-900" :aria-label="TEXT.expandCode" @mousedown.prevent="toggleProjectPicker(index, 'code')">&#9662;</button><div v-if="activeProjectPicker === pickerKey(index, 'code')" class="foreign-rd-project-menu absolute z-50 mt-1 max-h-72 min-w-[300px] overflow-auto rounded border border-gray-200 bg-white py-1 shadow-xl"><button v-for="project in filteredCodeProjects(row)" :key="project.name" type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-100" @mousedown.prevent="chooseProject(row, project)"><span class="block text-sm text-gray-900">{{ projectCode(project) }}</span><span class="block text-xs text-gray-500">{{ projectName(project) }}</span></button><div v-if="!filteredCodeProjects(row).length" class="px-3 py-2 text-xs text-gray-500">{{ TEXT.noProject }}</div></div></div></td>
                    <td class="px-3 py-2"><div class="relative overflow-visible"><input v-model="row.project_name" class="w-full rounded border border-gray-300 bg-white px-3 py-2 pr-8 text-sm" :placeholder="TEXT.chooseName" @focus="openProjectPicker(index, 'name')" @input="openProjectPicker(index, 'name')" @change="syncProjectName(row)" @blur="closeProjectPickerLater" /><button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-900" :aria-label="TEXT.expandName" @mousedown.prevent="toggleProjectPicker(index, 'name')">&#9662;</button><div v-if="activeProjectPicker === pickerKey(index, 'name')" class="foreign-rd-project-menu absolute z-50 mt-1 max-h-72 min-w-[360px] overflow-auto rounded border border-gray-200 bg-white py-1 shadow-xl"><button v-for="project in filteredNameProjects(row)" :key="project.name" type="button" class="block w-full px-3 py-2 text-left hover:bg-gray-100" @mousedown.prevent="chooseProject(row, project)"><span class="block text-sm text-gray-900">{{ projectName(project) }}</span><span class="block text-xs text-gray-500">{{ projectCode(project) }}</span></button><div v-if="!filteredNameProjects(row).length" class="px-3 py-2 text-xs text-gray-500">{{ TEXT.noProject }}</div></div></div></td>
                    <td class="px-3 py-2"><select v-model="row.activity_type" class="w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm"><option value="">{{ TEXT.choose }}</option><option v-for="activity in activityTypes" :key="activityName(activity)" :value="activityName(activity)">{{ activityName(activity) }}</option></select></td>
                    <td class="px-3 py-2"><input v-model="row.hours" type="number" min="0.5" max="8" step="0.5" class="w-full rounded border border-gray-300 px-3 py-2 text-right text-sm" /></td>
                    <td class="px-3 py-2"><input v-model="row.description" class="w-full rounded border border-gray-300 px-3 py-2 text-sm" :placeholder="TEXT.contentPlaceholder" /></td>
                    <td class="px-3 py-2 text-right"><button type="button" class="rounded px-2 py-2 text-xs text-red-600 hover:bg-red-50 hover:underline" @click="delRow(index)">{{ TEXT.remove }}</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="mt-3 flex flex-wrap items-center gap-3"><Button variant="subtle" @click="addRow">{{ TEXT.addRow }}</Button><Button variant="solid" :loading="saving" :disabled="!canSave" @click="save">{{ TEXT.save }}</Button><span class="text-xs text-gray-400">{{ TEXT.totalHours }} {{ fmt(draftTotalHours) }} h</span></div>
            <div class="foreign-rd-batch-import mt-5 border-t border-gray-200 pt-4">
              <div class="mb-2 flex flex-col gap-2 md:flex-row md:items-center md:justify-between"><div><h4 class="text-sm font-semibold text-gray-900">{{ TEXT.batchTitle }}</h4><p class="text-xs text-gray-500">{{ TEXT.batchHint }}</p></div><div class="flex gap-2"><Button variant="subtle" @click="chooseForeignWorkbook">{{ TEXT.importExcel }}</Button><input ref="batchWorkbookInput" type="file" accept=".xlsx,.xls,.csv" class="hidden" @change="importForeignWorkbookRows" /></div></div>
              <textarea v-model="batchPasteText" class="min-h-[120px] w-full rounded border border-gray-300 bg-white px-3 py-2 font-mono text-xs" :placeholder="TEXT.importPlaceholder"></textarea>
              <div class="mt-3 flex flex-wrap items-center gap-3"><Button variant="subtle" @click="previewBatchPaste">{{ TEXT.previewImport }}</Button><Button variant="subtle" :disabled="!batchRows.length" @click="appendBatchRows">{{ TEXT.appendImport }}</Button><Button variant="ghost" @click="clearBatchImport">{{ TEXT.clearImport }}</Button><span v-if="batchMessage" class="text-xs text-green-700">{{ batchMessage }}</span></div>
              <div v-if="batchErrors.length" class="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700"><div v-for="error in visibleBatchErrors" :key="error">{{ error }}</div><div v-if="remainingBatchErrorCount">还有 {{ remainingBatchErrorCount }} 条错误</div></div>
              <div v-if="batchRows.length" class="mt-3 overflow-x-auto rounded border border-gray-200 bg-white"><table class="w-full min-w-[900px] text-xs"><thead class="bg-gray-50 text-gray-500"><tr><th class="px-3 py-2 text-left">{{ TEXT.date }}</th><th class="px-3 py-2 text-left">{{ TEXT.projectCode }}</th><th class="px-3 py-2 text-left">{{ TEXT.projectName }}</th><th class="px-3 py-2 text-left">{{ TEXT.activityType }}</th><th class="px-3 py-2 text-right">{{ TEXT.hours }}</th><th class="px-3 py-2 text-left">{{ TEXT.description }}</th></tr></thead><tbody><tr v-for="(row, index) in batchRows" :key="index" class="border-t"><td class="px-3 py-2 whitespace-nowrap">{{ row.work_date }}</td><td class="px-3 py-2 whitespace-nowrap">{{ row.project_code }}</td><td class="px-3 py-2">{{ row.project_name }}</td><td class="px-3 py-2 whitespace-nowrap">{{ row.activity_type }}</td><td class="px-3 py-2 text-right tabular-nums">{{ fmt(row.hours) }}</td><td class="px-3 py-2">{{ row.description }}</td></tr><tr class="border-t bg-gray-50 font-medium"><td colspan="4" class="px-3 py-2 text-right">{{ TEXT.total }}</td><td class="px-3 py-2 text-right tabular-nums">{{ fmt(batchPreviewTotal) }}</td><td></td></tr></tbody></table></div>
            </div>
          </section>
        </div>
      </template>
    </Card>

    <Card :title="TEXT.lineTable" :subtitle="TEXT.lineHint">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[1180px] text-sm">
          <thead class="border-b bg-gray-50 text-gray-500">
            <tr>
              <th v-if="isYearScope" class="px-3 py-2 text-left">{{ TEXT.accountingPeriod }}</th>
              <th class="px-3 py-2 text-left">{{ TEXT.date }}</th>
              <th class="px-3 py-2 text-left">{{ TEXT.projectCode }}</th>
              <th class="px-3 py-2 text-left">{{ TEXT.projectName }}</th>
              <th class="px-3 py-2 text-left">{{ TEXT.activityType }}</th>
              <th class="px-3 py-2 text-right">{{ TEXT.hours }}</th>
              <th class="px-3 py-2 text-left">{{ TEXT.description }}</th>
              <th class="px-3 py-2 text-right">{{ TEXT.ratio }}</th>
              <th class="px-3 py-2 text-right">{{ TEXT.commonAllocation }}</th>
              <th class="px-3 py-2 text-right">{{ TEXT.directAllocation }}</th>
              <th class="px-3 py-2 text-right">{{ TEXT.amountColumn }}</th>
              <th v-if="!isYearScope" class="px-3 py-2 text-right">{{ TEXT.action }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in foreignLines" :key="row.project + row.work_date + row.activity_type + index" class="border-b last:border-0 hover:bg-gray-50">
              <td v-if="isYearScope" class="px-3 py-2 whitespace-nowrap">{{ row.period }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.work_date }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.project_code }}</td>
              <td class="px-3 py-2 min-w-[160px]">{{ row.project_name }}</td>
              <td class="px-3 py-2 whitespace-nowrap">{{ row.activity_type }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ fmt(row.hours) }}</td>
              <td class="px-3 py-2 min-w-[220px] text-gray-700">{{ row.description }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ fmtPercent(row.ratio) }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ fmt(row.common_allocated_amount) }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ fmt(row.direct_allocated_amount) }}</td>
              <td class="px-3 py-2 text-right tabular-nums">{{ fmt(row.allocated_amount) }}</td>
              <td v-if="!isYearScope" class="px-3 py-2 text-right"><button type="button" class="rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 hover:underline" @click="deleteSavedLine(index)">{{ TEXT.remove }}</button></td>
            </tr>
            <tr v-if="!foreignLines.length"><td :colspan="isYearScope ? 11 : 11" class="py-6 text-center text-gray-400">{{ TEXT.noData }}</td></tr>
          </tbody>
        </table>
      </div>
    </Card>

  </div>
</template>
