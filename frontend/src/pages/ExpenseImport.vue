<script setup>
import { computed, ref, watch } from 'vue';
import { Card, Button, createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { clearInvalidLowerLevels, accountOptions, validateExpenseAccount } from '../lib/expenseAccounts';
import { deriveExpenseCategory, importWorkbookFile, parseExpensePaste, resolveProjectValue } from '../lib/expensePaste';
import { exportTableWorkbook } from '../lib/tableExport';

const ALLOCATION_TYPES = [
  { v: 'common', l: '公共费用' },
  { v: 'project', l: '项目费用' },
];

const pastePlaceholder = [
  '凭证号\t1级费用科目\t2级费用科目\t3级费用科目\t4级费用科目\t费用金额\t项目',
  '2\t研发支出\t直接投入费用\t仪器、设备的运行维护、调整、检验、维修等费用\t\t7477.88\t公共费用',
  '3\t研发支出\t其他相关费用\t职工福利费\t节日福利\t2389.93\tRD16',
].join('\n');

const items = ref([]);
const status = ref(null);
const saving = ref(false);
const exporting = ref(false);
const errMsg = ref('');
const pasteText = ref('');
const pasteErrors = ref([]);
const pasteMessage = ref('');
const workbookInput = ref(null);
const workbookReplace = ref(false);

const projects = createResource({
  url: 'rayher_hr_payroll.api.project_entry.list_projects',
  method: 'GET',
  auto: true,
});
const loader = createResource({
  url: 'rayher_hr_payroll.api.expense_entry.get_expense',
  method: 'GET',
  makeParams: () => ({ period: period.value, scope: periodScope.value }),
  onSuccess: (d) => {
    status.value = d.status;
    items.value = normalizeRows(d.items || []);
  },
  auto: true,
});
const saver = createResource({ url: 'rayher_hr_payroll.api.expense_entry.save_expense' });

const isYearScope = computed(() => periodScope.value === 'year');
const projectOptions = computed(() => (projects.data || []).filter((project) => project.status !== 'Cancelled'));
const fmt = (n) => (n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const total = computed(() => items.value.reduce((s, r) => s + Number(r.amount || 0), 0));
const visiblePasteErrors = computed(() => pasteErrors.value.slice(0, 5));
const remainingPasteErrorCount = computed(() => Math.max(pasteErrors.value.length - visiblePasteErrors.value.length, 0));

function projectLabel(project) {
  const code = project?.rd_project_code || project?.name || '';
  const name = project?.project_name || '';
  return code && name ? code + ' | ' + name : code || name;
}

function inferredAllocation(row = {}) {
  if (row.allocation_type) {
    return {
      allocation_type: row.allocation_type,
      direct_project: row.allocation_type === 'project' ? (row.direct_project || '') : '',
    };
  }
  if (row.direct_project) return { allocation_type: 'project', direct_project: row.direct_project };
  return resolveProjectValue(row.project_text || '公共费用', projectOptions.value);
}

function normalizeRow(row = {}) {
  const allocation = inferredAllocation(row);
  const allocationType = allocation.allocation_type === 'project' ? 'project' : 'common';
  return {
    voucher_no: row.voucher_no || '',
    account_level_1: row.account_level_1 || '研发支出',
    account_level_2: row.account_level_2 || '',
    account_level_3: row.account_level_3 || '',
    account_level_4: row.account_level_4 || '',
    allocation_type: allocationType,
    direct_project: allocationType === 'project' ? (allocation.direct_project || row.direct_project || '') : '',
    amount: row.amount ?? '',
    period: row.period || '',
  };
}

function normalizeRows(rows) {
  return rows.map((row) => normalizeRow(row));
}

function addRow() {
  items.value.push(normalizeRow());
}

function delRow(i) {
  items.value.splice(i, 1);
}

function clearPaste() {
  pasteText.value = '';
  pasteErrors.value = [];
  pasteMessage.value = '';
}

function applyImportedRows(result, replace = false, source = '导入') {
  pasteErrors.value = [];
  pasteMessage.value = '';
  if (result.errors.length) {
    pasteErrors.value = result.errors;
    return;
  }
  if (!result.rows.length) {
    pasteErrors.value = ['请导入至少一行费用'];
    return;
  }

  const rows = normalizeRows(result.rows);
  if (replace) {
    items.value = rows;
  } else {
    items.value.push(...rows);
  }
  pasteMessage.value = source + ' ' + rows.length + ' 行，请确认后保存';
}

function importPastedRows(replace = false) {
  errMsg.value = '';
  const result = parseExpensePaste(pasteText.value, projectOptions.value);
  applyImportedRows(result, replace, '已导入');
  if (!pasteErrors.value.length) pasteText.value = '';
}

function chooseWorkbook(replace = false) {
  workbookReplace.value = replace;
  workbookInput.value?.click();
}

async function importWorkbookRows(event) {
  errMsg.value = '';
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const result = await importWorkbookFile(file, projectOptions.value);
    applyImportedRows(result, workbookReplace.value, 'Excel 已导入');
  } catch (error) {
    pasteErrors.value = [(error && error.message) || 'Excel 导入失败'];
  }
}

function accountDatalistId(index, level) {
  return 'expense-account-level-' + level + '-' + index;
}

function accountLevelOptions(row, level) {
  return accountOptions(row, level);
}

function syncAccountLevels(row, level) {
  clearInvalidLowerLevels(row, level);
}

function syncAllocationType(row) {
  if (row.allocation_type !== 'project') row.direct_project = '';
}

function rowValidationErrors(row, index) {
  const lineNo = index + 1;
  const errors = [];
  errors.push(...validateExpenseAccount(row, lineNo));
  const rawAmount = String(row.amount ?? '').trim();
  const amount = Number(rawAmount);
  if (!rawAmount || !Number.isFinite(amount)) errors.push('第 ' + lineNo + ' 行：费用金额必须是有效数字');
  if (row.allocation_type === 'project') {
    if (!row.direct_project) {
      errors.push('第 ' + lineNo + ' 行：项目费用请选择所属项目');
    } else if (!projectOptions.value.some((project) => project.name === row.direct_project)) {
      errors.push('第 ' + lineNo + ' 行：所属项目无效');
    }
  }
  return errors;
}

function payloadRows() {
  return items.value.map((row) => ({
    voucher_no: row.voucher_no,
    account_level_1: row.account_level_1,
    account_level_2: row.account_level_2,
    account_level_3: row.account_level_3,
    account_level_4: row.account_level_4,
    category: deriveExpenseCategory(row),
    allocation_type: row.allocation_type || 'common',
    direct_project: row.allocation_type === 'project' ? row.direct_project : '',
    amount: row.amount,
  }));
}

async function save() {
  if (isYearScope.value) return;
  errMsg.value = '';
  const errors = items.value.flatMap((row, index) => rowValidationErrors(row, index));
  if (errors.length) {
    errMsg.value = errors.slice(0, 5).join('；') + (errors.length > 5 ? '；还有 ' + (errors.length - 5) + ' 条错误' : '');
    return;
  }
  saving.value = true;
  try {
    const d = await saver.submit({ period: period.value, items: JSON.stringify(payloadRows()) });
    status.value = d.status;
    items.value = normalizeRows(d.items || []);
  } catch (e) {
    errMsg.value = (e && e.message) || '保存失败';
  } finally {
    saving.value = false;
  }
}

async function exportCurrentExpense() {
  exporting.value = true;
  errMsg.value = '';
  try {
    await exportTableWorkbook({
      filename: `研发费用导入-${periodScopeLabel(period.value, periodScope.value)}`,
      sheetName: '财务费用',
      rows: items.value,
      columns: [
        ...(isYearScope.value ? [{ label: '日期', key: 'period', width: 12 }] : []),
        { label: '凭证号', key: 'voucher_no', width: 14 },
        { label: '1级费用科目', key: 'account_level_1', width: 18 },
        { label: '2级费用科目', key: 'account_level_2', width: 22 },
        { label: '3级费用科目', key: 'account_level_3', width: 34 },
        { label: '4级费用科目', key: 'account_level_4', width: 24 },
        { label: '归属方式', value: (row) => row.allocation_type === 'project' ? '项目费用' : '公共费用', width: 14 },
        { label: '所属项目', key: 'direct_project', width: 18 },
        { label: '费用金额', value: (row) => Number(row.amount || 0), width: 16 },
      ],
    });
  } catch (error) {
    errMsg.value = error?.message || '导出失败';
  } finally {
    exporting.value = false;
  }
}
watch(period, () => loader.reload());
watch(periodScope, () => loader.reload());
</script>

<template>
  <Card title='研发费用导入' subtitle='录入本期研发相关费用，按 1-4 级费用科目进入项目或公共费用池'>
    <div class='flex items-center gap-2 mb-4'>
      <span class='text-sm text-gray-500'>会计期间</span>
      <input type='month' v-model='period' class='border border-gray-300 rounded px-3 py-1.5 text-sm' />
      <div class='inline-flex overflow-hidden rounded border border-gray-200 bg-white'>
        <button v-for='scope in PERIOD_SCOPES' :key='scope.value' type='button' class='px-3 py-1.5 text-sm' :class="periodScope === scope.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-gray-50'" @click='setPeriodScope(scope.value)'>{{ scope.label }}</button>
      </div>
      <span v-if='status' class='text-xs text-gray-400 ml-2'>状态：{{ status }}</span>
      <Button variant='subtle' :loading='exporting' :disabled='!items.length' @click='exportCurrentExpense'>导出Excel</Button>
    </div>

    <div v-if='loader.loading' class='text-gray-500 text-sm py-4'>加载中…</div>
    <template v-else>
      <div v-if='!isYearScope' class='rounded border border-gray-200 bg-gray-50 p-3 mb-4'>
        <div class='flex flex-col gap-2 md:flex-row md:items-center md:justify-between mb-2'>
          <span class='text-sm font-medium text-gray-700'>批量粘贴 / Excel 导入</span>
          <div class='flex flex-wrap gap-2'>
            <Button variant='subtle' @click='chooseWorkbook(false)'>导入Excel</Button>
            <Button variant='subtle' @click='chooseWorkbook(true)'>导入Excel并覆盖</Button>
            <input ref='workbookInput' type='file' accept='.xlsx,.xls' class='hidden' @change='importWorkbookRows' />
          </div>
        </div>
        <textarea v-model='pasteText' :placeholder='pastePlaceholder' rows='4' class='w-full resize-y rounded border border-gray-300 bg-white px-3 py-2 text-sm font-mono leading-6 focus:border-gray-500 focus:outline-none'></textarea>
        <div class='flex flex-wrap items-center gap-2 mt-3'>
          <Button variant='subtle' :disabled='!pasteText.trim()' @click='importPastedRows(false)'>追加导入</Button>
          <Button variant='subtle' :disabled='!pasteText.trim()' @click='importPastedRows(true)'>覆盖当前表格</Button>
          <Button v-if='pasteText || pasteErrors.length || pasteMessage' variant='subtle' @click='clearPaste'>清空</Button>
          <span v-if='pasteMessage' class='text-xs text-green-700'>{{ pasteMessage }}</span>
        </div>
        <div v-if='pasteErrors.length' class='mt-2 space-y-1 text-xs text-red-600'>
          <p v-for='(message, idx) in visiblePasteErrors' :key='idx'>{{ message }}</p>
          <p v-if='remainingPasteErrorCount'>还有 {{ remainingPasteErrorCount }} 条错误</p>
        </div>
      </div>

      <div class='overflow-x-auto rounded border border-gray-200 bg-white'>
        <table class='w-full min-w-[1500px] text-sm whitespace-nowrap'>
          <thead class='text-gray-500 border-b bg-gray-50'>
            <tr>
              <th v-if='isYearScope' class='text-left px-2 py-2 w-28 whitespace-nowrap'>日期</th>
              <th class='text-left px-2 py-2 w-28 whitespace-nowrap'>凭证号</th>
              <th class='text-left px-2 py-2 min-w-[180px] whitespace-nowrap'>1级费用科目</th>
              <th class='text-left px-2 py-2 min-w-[220px] whitespace-nowrap'>2级费用科目</th>
              <th class='text-left px-2 py-2 min-w-[340px] whitespace-nowrap'>3级费用科目</th>
              <th class='text-left px-2 py-2 min-w-[220px] whitespace-nowrap'>4级费用科目</th>
              <th class='text-right px-2 py-2 min-w-[140px] whitespace-nowrap'>费用金额</th>
              <th class='text-left px-2 py-2 min-w-[150px] whitespace-nowrap'>归属方式</th>
              <th class='text-left px-2 py-2 min-w-[260px] whitespace-nowrap'>所属项目</th>
              <th class='w-12'></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for='(it, i) in items' :key='i' class='border-b last:border-0'>
              <td v-if='isYearScope' class='px-2 py-1 text-gray-500'>{{ it.period }}</td>
              <td class='px-2 py-1'><input :disabled='isYearScope' v-model='it.voucher_no' class='border border-gray-200 rounded px-2 py-1 text-sm w-full' placeholder='V001' /></td>
              <td class='px-2 py-1'>
                <input :disabled='isYearScope' v-model='it.account_level_1' :list="accountDatalistId(i, 1)" @change='syncAccountLevels(it, 1)' class='border border-gray-200 rounded px-2 py-1 text-sm w-full' placeholder='研发支出' />
                <datalist :id="accountDatalistId(i, 1)"><option v-for='option in accountLevelOptions(it, 1)' :key='option' :value='option'></option></datalist>
              </td>
              <td class='px-2 py-1'>
                <input :disabled='isYearScope' v-model='it.account_level_2' :list="accountDatalistId(i, 2)" @change='syncAccountLevels(it, 2)' class='border border-gray-200 rounded px-2 py-1 text-sm w-full' placeholder='直接投入费用' />
                <datalist :id="accountDatalistId(i, 2)"><option v-for='option in accountLevelOptions(it, 2)' :key='option' :value='option'></option></datalist>
              </td>
              <td class='px-2 py-1'>
                <input :disabled='isYearScope' v-model='it.account_level_3' :list="accountDatalistId(i, 3)" @change='syncAccountLevels(it, 3)' class='border border-gray-200 rounded px-2 py-1 text-sm w-full' placeholder='如 差旅费' />
                <datalist :id="accountDatalistId(i, 3)"><option v-for='option in accountLevelOptions(it, 3)' :key='option' :value='option'></option></datalist>
              </td>
              <td class='px-2 py-1'>
                <input :disabled='isYearScope' v-model='it.account_level_4' :list="accountDatalistId(i, 4)" class='border border-gray-200 rounded px-2 py-1 text-sm w-full' placeholder='可为空' />
                <datalist :id="accountDatalistId(i, 4)"><option v-for='option in accountLevelOptions(it, 4)' :key='option' :value='option'></option></datalist>
              </td>
              <td class='px-2 py-1'><input :disabled='isYearScope' v-model='it.amount' type='number' step='0.01' class='border border-gray-200 rounded px-2 py-1 text-sm w-full text-right' placeholder='0' /></td>
              <td class='px-2 py-1'>
                <select :disabled='isYearScope' v-model='it.allocation_type' @change='syncAllocationType(it)' class='border border-gray-200 rounded px-2 py-1 text-sm w-full'>
                  <option v-for='type in ALLOCATION_TYPES' :key='type.v' :value='type.v'>{{ type.l }}</option>
                </select>
              </td>
              <td class='px-2 py-1'>
                <select v-model='it.direct_project' :disabled="isYearScope || it.allocation_type !== 'project'" class='border border-gray-200 rounded px-2 py-1 text-sm w-full disabled:bg-gray-50 disabled:text-gray-400'>
                  <option value=''>请选择项目</option>
                  <option v-for='project in projectOptions' :key='project.name' :value='project.name'>{{ projectLabel(project) }}</option>
                </select>
              </td>
              <td class='px-2 py-1 text-center'><button v-if='!isYearScope' @click='delRow(i)' class='text-red-600 text-xs hover:underline'>删</button></td>
            </tr>
            <tr v-if='!items.length'><td :colspan='isYearScope ? 10 : 9' class='text-center text-gray-400 py-6'>本期暂无费用，点“添加一行”录入，或粘贴 / 导入 Excel</td></tr>
          </tbody>
          <tfoot v-if='items.length'>
            <tr class='border-t font-medium'>
              <td :colspan='isYearScope ? 6 : 5' class='px-2 py-2'>合计</td>
              <td class='text-right px-2 py-2 tabular-nums'>{{ fmt(total) }}</td>
              <td colspan='3'></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div v-if='!isYearScope' class='flex items-center gap-3 mt-4'>
        <Button variant='subtle' @click='addRow'>添加一行</Button>
        <Button variant='solid' :loading='saving' @click='save'>保存</Button>
        <span class='text-xs text-gray-400'>公共费用按研发工时比例分配；项目费用直接归属到所选项目</span>
      </div>
      <p v-if='errMsg' class='text-red-600 text-xs mt-2'>{{ errMsg }}</p>
    </template>
  </Card>
</template>
