<script setup>
import { computed, ref, watch } from 'vue';
import { Card, Button, Spinner, createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { importForeignRdWorkbookFile, parseForeignRdPaste } from '../lib/foreignRdImport';
import { exportTableWorkbook } from '../lib/tableExport';

const DEFAULT_ENTITY = 'QIHENG DEMO OVERSEAS';
const foreignEntities = [DEFAULT_ENTITY];
const TEXT = {
  title: '境外委托研发工时',
  subtitle: '境外工时按月填报，境外费用按项目工时比例分摊，最终并入总汇总',
  accountingPeriod: '会计期间',
  entry: '境外工时填报（按月）',
  entity: '研发主体',
  project: '项目',
  occurrenceDays: '发生天数',
  hours: '工时',
  remark: '备注',
  action: '操作',
  addRow: '添加一行',
  remove: '删除',
  save: '保存',
  exportExcel: '导出Excel',
  importedTotal: '导入费用合计',
  commonExpense: '公共费用',
  projectExpense: '项目费用',
  totalHours: '境外工时合计',
  saved: '已保存境外工时，费用已重新计算',
  noData: '暂无数据',
};

const rows = ref([]);
const data = ref({});
const loading = ref(false);
const saving = ref(false);
const exporting = ref(false);
const message = ref('');
const errorMessage = ref('');
const batchPasteText = ref('');
const batchRows = ref([]);
const batchErrors = ref([]);
const batchWorkbookInput = ref(null);

const loader = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_rd', method: 'GET' });
const saver = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.save_foreign_rd' });
const options = createResource({ url: 'rayher_hr_payroll.api.foreign_rd_entry.get_foreign_project_options', method: 'GET', auto: true });

const projectOptions = computed(() => options.data?.projects || []);
const isYearScope = computed(() => periodScope.value === 'year');
const importedTotalAmount = computed(() => Number(data.value.total_amount || 0));
const commonAmount = computed(() => Number(data.value.common_amount || 0));
const directAmount = computed(() => Number(data.value.direct_amount || 0));
const unallocatedCommonAmount = computed(() => Number(data.value.unallocated_common_amount || 0));
const totalHours = computed(() => activeRows().reduce((sum, row) => sum + Number(row.hours || 0), 0));
const foreignExpenseCards = computed(() => [
  { key: 'total', label: TEXT.importedTotal, value: importedTotalAmount.value },
  { key: 'common', label: TEXT.commonExpense, value: commonAmount.value },
  { key: 'direct', label: TEXT.projectExpense, value: directAmount.value },
  { key: 'hours', label: TEXT.totalHours, value: totalHours.value, suffix: 'h' },
]);

function projectCode(project) {
  return project?.rd_project_code || project?.name || '';
}

function projectName(project) {
  return project?.project_name || project?.name || '';
}

function findProject(name) {
  return projectOptions.value.find((project) => project.name === name);
}

function blankRow() {
  return {
    foreign_entity: DEFAULT_ENTITY,
    project: '',
    project_code: '',
    project_name: '',
    occurrence_days: '',
    hours: 0,
    remark: '',
  };
}

function normalizeRows(list = []) {
  return list.map((row) => ({
    foreign_entity: row.foreign_entity || DEFAULT_ENTITY,
    project: row.project || '',
    project_code: row.project_code || row.rd_project_code || '',
    project_name: row.project_name || '',
    occurrence_days: row.occurrence_days ?? (Number(row.hours || 0) / 8),
    hours: Number(row.hours || 0),
    remark: row.remark ?? row.description ?? '',
    period: row.period || '',
  }));
}

function rowHasInput(row) {
  return Boolean(row.project || Number(row.occurrence_days || 0) || String(row.remark || '').trim());
}

function activeRows() {
  return rows.value.filter(rowHasInput);
}

function recalculateHours(row) {
  row.hours = Math.round(Number(row.occurrence_days || 0) * 8 * 100) / 100;
}

function selectProject(row) {
  const project = findProject(row.project);
  row.project_code = projectCode(project);
  row.project_name = projectName(project);
}

function addRow() {
  rows.value.push(blankRow());
}

function deleteRow(index) {
  rows.value.splice(index, 1);
  if (!rows.value.length) addRow();
}

function applyData(payload = {}) {
  data.value = payload;
  const saved = normalizeRows(payload.lines || []);
  rows.value = saved.length ? saved : [blankRow()];
  batchPasteText.value = '';
  batchRows.value = [];
  batchErrors.value = [];
}

async function load() {
  loading.value = true;
  message.value = '';
  errorMessage.value = '';
  try {
    applyData(await loader.submit({ period: period.value, scope: periodScope.value }) || {});
  } catch (error) {
    errorMessage.value = error?.message || '加载失败';
  } finally {
    loading.value = false;
  }
}

function validateRows() {
  const filled = activeRows();
  if (!filled.length) return commonAmount.value > 0 ? '有境外公共费用时，必须录入至少一条工时' : '请至少填写一条境外工时';
  const keys = new Set();
  for (let index = 0; index < filled.length; index += 1) {
    const row = filled[index];
    const daysText = String(row.occurrence_days ?? '').trim();
    const days = Number(daysText);
    if (!foreignEntities.includes(row.foreign_entity)) return `${index + 1}. 请选择研发主体`;
    if (!row.project || !row.project_code || !row.project_name) return `${index + 1}. 请选择项目`;
    if (!/^\d+(?:\.\d{1,2})?$/.test(daysText) || !Number.isFinite(days) || days <= 0) return `${index + 1}. 发生天数必须大于 0，且最多保留两位小数`;
    const key = `${row.foreign_entity}|${row.project}`;
    if (keys.has(key)) return `${index + 1}. 同一主体和项目只能填写一行`;
    keys.add(key);
    recalculateHours(row);
  }
  return '';
}

function payloadRows() {
  return activeRows().map((row) => ({
    foreign_entity: row.foreign_entity,
    project: row.project,
    project_code: row.project_code,
    project_name: row.project_name,
    occurrence_days: Number(row.occurrence_days),
    hours: Number(row.hours),
    remark: String(row.remark || '').trim(),
  }));
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
  return { projects: projectOptions.value, foreignEntities, existingRows: activeRows() };
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
        { label: TEXT.occurrenceDays, key: 'occurrence_days', width: 14 },
        { label: TEXT.hours, key: 'hours', width: 14 },
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
  <div class="space-y-5">
    <Card :title="TEXT.title" :subtitle="TEXT.subtitle">
      <div class="mb-5 flex flex-wrap items-center gap-3">
        <span class="text-sm text-gray-500">{{ TEXT.accountingPeriod }}</span>
        <input v-model="period" type="month" class="rounded border border-gray-300 px-3 py-1.5 text-sm" />
        <div class="inline-flex overflow-hidden rounded border border-gray-200 bg-white">
          <button v-for="scope in PERIOD_SCOPES" :key="scope.value" type="button" class="px-3 py-1.5 text-sm" :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click="setPeriodScope(scope.value)">{{ scope.label }}</button>
        </div>
        <Button variant="subtle" :loading="exporting" :disabled="!activeRows().length" @click="exportCurrentForeignRd">{{ TEXT.exportExcel }}</Button>
        <span class="text-xs text-gray-400">状态: {{ data.status || '-' }}</span>
        <span v-if="data.expense_import" class="text-xs text-gray-400">来源费用表: {{ data.expense_import }}</span>
      </div>

      <div v-if="loading" class="flex justify-center py-10"><Spinner class="w-6" /></div>
      <template v-else>
        <div class="mb-4 grid gap-3 md:grid-cols-4 foreign-expense-cards">
          <div v-for="card in foreignExpenseCards" :key="card.key" class="rounded border border-gray-200 bg-gray-50 px-4 py-3">
            <div class="text-xs text-gray-500">{{ card.label }}</div>
            <div class="mt-1 text-xl font-semibold tabular-nums text-gray-900">{{ Number(card.value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}<span v-if="card.suffix" class="ml-1 text-sm font-normal text-gray-500">{{ card.suffix }}</span></div>
          </div>
        </div>

        <div v-if="unallocatedCommonAmount > 0" class="mb-4 rounded border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-700">有 {{ unallocatedCommonAmount.toFixed(2) }} 元公共费用等待境外工时分摊</div>

        <section class="rounded border border-gray-200 bg-gray-50 p-4">
          <h3 class="mb-3 text-base font-semibold text-gray-900">{{ TEXT.entry }}</h3>
          <div class="foreign-rd-entry-table overflow-x-auto rounded border border-gray-200 bg-white">
            <table class="w-full min-w-[980px] text-sm">
              <thead class="bg-gray-50 text-xs text-gray-500">
                <tr>
                  <th v-if="isYearScope" class="px-3 py-2 text-left">月份</th>
                  <th class="px-3 py-2 text-left">{{ TEXT.entity }}</th>
                  <th class="px-3 py-2 text-left">{{ TEXT.project }}</th>
                  <th class="px-3 py-2 text-right">{{ TEXT.occurrenceDays }}</th>
                  <th class="px-3 py-2 text-right">{{ TEXT.hours }}</th>
                  <th class="px-3 py-2 text-left">{{ TEXT.remark }}</th>
                  <th v-if="!isYearScope" class="px-3 py-2 text-right">{{ TEXT.action }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, index) in rows" :key="`${row.period || period}-${index}`" class="border-t border-gray-100">
                  <td v-if="isYearScope" class="px-3 py-2">{{ row.period }}</td>
                  <td class="px-3 py-2">
                    <select v-model="row.foreign_entity" class="w-full rounded border border-gray-300 px-2 py-2" :disabled="isYearScope">
                      <option v-for="entity in foreignEntities" :key="entity" :value="entity">{{ entity }}</option>
                    </select>
                  </td>
                  <td class="px-3 py-2">
                    <select v-model="row.project" class="w-full min-w-[260px] rounded border border-gray-300 px-2 py-2" :disabled="isYearScope" @change="selectProject(row)">
                      <option value="">请选择项目</option>
                      <option v-for="project in projectOptions" :key="project.name" :value="project.name">{{ projectCode(project) }} {{ projectName(project) }}</option>
                    </select>
                  </td>
                  <td class="px-3 py-2 text-right"><input v-model="row.occurrence_days" type="number" min="0.01" step="0.01" class="w-28 rounded border border-gray-300 px-2 py-2 text-right" :readonly="isYearScope" @input="recalculateHours(row)" /></td>
                  <td class="px-3 py-2 text-right"><input :value="Number(row.hours || 0).toFixed(2)" readonly class="w-28 rounded border border-gray-200 bg-gray-50 px-2 py-2 text-right text-gray-600" /></td>
                  <td class="px-3 py-2"><input v-model="row.remark" class="w-full min-w-[220px] rounded border border-gray-300 px-2 py-2" :readonly="isYearScope" placeholder="备注" /></td>
                  <td v-if="!isYearScope" class="px-3 py-2 text-right"><button type="button" class="text-red-600" @click="deleteRow(index)">{{ TEXT.remove }}</button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="!isYearScope" class="mt-3 flex flex-wrap items-center gap-3">
            <Button variant="subtle" @click="addRow">{{ TEXT.addRow }}</Button>
            <Button :loading="saving" @click="save">{{ TEXT.save }}</Button>
            <span class="text-xs text-gray-500">合计 {{ (totalHours / 8).toFixed(2) }} 天 / {{ totalHours.toFixed(2) }} 小时</span>
          </div>

          <div v-if="!isYearScope" class="foreign-rd-batch-import mt-5 border-t border-gray-200 pt-4">
            <div class="mb-2 flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold">批量粘贴 / Excel 导入</span>
              <Button variant="subtle" @click="chooseWorkbook">导入Excel</Button>
              <input ref="batchWorkbookInput" type="file" accept=".xlsx,.xls" class="hidden" @change="importWorkbook" />
            </div>
            <textarea v-model="batchPasteText" rows="3" class="w-full rounded border border-gray-300 px-3 py-2 text-sm" placeholder="主体　项目代码　项目名称　发生天数　备注"></textarea>
            <div class="mt-2 flex gap-2"><Button variant="subtle" @click="previewBatchPaste">预览导入</Button><Button variant="subtle" :disabled="!batchRows.length" @click="appendBatchRows">追加到表格</Button></div>
            <p v-for="error in batchErrors" :key="error" class="mt-1 text-xs text-red-600">{{ error }}</p>
          </div>
        </section>

        <p v-if="message" class="mt-3 text-sm text-green-700">{{ message }}</p>
        <p v-if="errorMessage" class="mt-3 text-sm text-red-600">{{ errorMessage }}</p>
      </template>
    </Card>
  </div>
</template>