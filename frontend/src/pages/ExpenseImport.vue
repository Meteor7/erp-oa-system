<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { EXPENSE_ACCOUNT_PATHS, clearInvalidLowerLevels, accountOptions, unknownExpenseAccountPaths, validateExpenseAccount } from '../lib/expenseAccounts';
import { deriveExpenseCategory, filterNewExpenseRows, importWorkbookFile, parseExpensePaste, resolveProjectValue } from '../lib/expensePaste';
import { duplicateVoucherRows, expenseFilterCounts, expenseTotals, filterExpenseRows, stripLinePrefix } from '../lib/rdExpense';
import { exportTableWorkbook } from '../lib/tableExport';
import RdPage from '../components/rd/RdPage.vue';
import RdPeriod from '../components/rd/RdPeriod.vue';
import RdSeg from '../components/rd/RdSeg.vue';
import RdKpi from '../components/rd/RdKpi.vue';
import RdIcon from '../components/rd/RdIcon.vue';

const ALLOCATION_TYPES = [
  { v: 'common', l: '公共费用' },
  { v: 'project', l: '项目费用' },
];

const pastePlaceholder = [
  '凭证号\t1级费用科目\t2级费用科目\t3级费用科目\t4级费用科目\t费用金额\t项目',
  '2\t研发支出\t直接投入费用\t仪器、设备的运行维护、调整、检验、维修等费用\t\t7477.88\t公共费用',
  '3\t研发支出\t其他相关费用\t职工福利费\t节日福利\t2389.93\tRD16',
].join('\n');

const scopeOptions = PERIOD_SCOPES.map((scope) => ({ value: scope.value, label: scope.label }));

const items = ref([]);
const status = ref(null);
const saving = ref(false);
const exporting = ref(false);
const errMsg = ref('');
const pasteText = ref('');
const pasteErrors = ref([]);
const pasteMessage = ref('');
const pasteOpen = ref(false);
const workbookInput = ref(null);
const workbookReplace = ref(false);
const confirmNewAccounts = ref(false);
const confirmWorkbookOverwrite = ref(false);
const confirmPasteOverwrite = ref(false);
const filterKind = ref('all');
const searchText = ref('');

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
const accountCatalog = createResource({
  url: 'rayher_hr_payroll.api.expense_entry.get_expense_account_catalog',
  method: 'GET',
  auto: true,
});
const saver = createResource({ url: 'rayher_hr_payroll.api.expense_entry.save_expense' });

const isYearScope = computed(() => periodScope.value === 'year');
const projectOptions = computed(() => (projects.data || []).filter((project) => project.status !== 'Cancelled'));
const catalogReady = computed(() => Array.isArray(accountCatalog.data?.paths));
const expenseAccountPaths = computed(() => catalogReady.value ? accountCatalog.data.paths : EXPENSE_ACCOUNT_PATHS);
const pendingAccountPaths = computed(() => unknownExpenseAccountPaths(items.value, expenseAccountPaths.value));
const fmt = (n) => (n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const totals = computed(() => expenseTotals(items.value));
const total = computed(() => totals.value.total);
const visiblePasteErrors = computed(() => pasteErrors.value.slice(0, 5));
const remainingPasteErrorCount = computed(() => Math.max(pasteErrors.value.length - visiblePasteErrors.value.length, 0));

// 每一行的问题：校验错误（会挡住保存）+ 重复凭证行（只提醒）。年度视图只读，不做检查。
const duplicates = computed(() => duplicateVoucherRows(items.value));
const entries = computed(() => items.value.map((row, index) => {
  const errors = isYearScope.value ? [] : rowValidationErrors(row, index).map(stripLinePrefix);
  const problems = [...errors];
  const same = isYearScope.value ? null : duplicates.value.indexes.get(index);
  if (same) problems.push('与第 ' + same.map((n) => n + 1).join('、') + ' 行的凭证号和科目重复');
  return { row, index, errors, problems };
}));
const filterCounts = computed(() => expenseFilterCounts(entries.value));
const visibleEntries = computed(() => filterExpenseRows(entries.value, { kind: filterKind.value, query: searchText.value }));
const errorRowCount = computed(() => entries.value.filter((entry) => entry.errors.length).length);
const duplicateGroupCount = computed(() => duplicates.value.groups.length);
const filterChips = computed(() => [
  { value: 'all', label: '全部', count: filterCounts.value.all },
  { value: 'common', label: '公共', count: filterCounts.value.common },
  { value: 'project', label: '项目', count: filterCounts.value.project },
  ...(isYearScope.value ? [] : [{ value: 'bad', label: '有问题', count: filterCounts.value.bad }]),
]);
const checksPassed = computed(() => !errorRowCount.value && !pendingAccountPaths.value.length && !duplicateGroupCount.value);
const saveBlocked = computed(() => isYearScope.value || !catalogReady.value || saving.value || errorRowCount.value > 0 || (pendingAccountPaths.value.length > 0 && !confirmNewAccounts.value));

function parseFrappeServerMessages(raw) {
  if (!raw) return [];
  try {
    const items = typeof raw === 'string' ? JSON.parse(raw) : raw;
    if (!Array.isArray(items)) return [];
    return items.map((message) => {
      try {
        const parsed = typeof message === 'string' ? JSON.parse(message) : message;
        return parsed.message || parsed.title || message;
      } catch {
        return message;
      }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

function cleanMessage(value) {
  return String(value || '').replace(/<[^>]*>/g, '').trim();
}

function serverMessage(error, fallback) {
  const messages = [
    ...(error?.messages || []),
    ...parseFrappeServerMessages(error?._server_messages),
  ].map(cleanMessage).filter(Boolean);
  if (messages.length) return messages.join('；');
  return cleanMessage(error?._error_message || error?.message) || fallback;
}
function projectLabel(project) {
  const code = project?.rd_project_code || project?.name || '';
  const name = project?.project_name || '';
  return code && name ? code + ' | ' + name : code || name;
}

function projectLabelByName(name) {
  if (!name) return '-';
  const project = (projects.data || []).find((item) => item.name === name);
  return project ? projectLabel(project) : name;
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
  filterKind.value = 'all';
  searchText.value = '';
  items.value.push(normalizeRow());
}

function delRow(i) {
  items.value.splice(i, 1);
}

function clearPaste() {
  pasteText.value = '';
  pasteErrors.value = [];
  pasteMessage.value = '';
  confirmPasteOverwrite.value = false;
}

function dismissImportMessages() {
  pasteErrors.value = [];
  pasteMessage.value = '';
}

function openPaste() {
  confirmPasteOverwrite.value = false;
  pasteOpen.value = true;
}

function closePaste() {
  confirmPasteOverwrite.value = false;
  pasteOpen.value = false;
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
  let acceptedRows = rows;
  let skipped = 0;
  if (replace) {
    items.value = rows;
  } else {
    const filtered = filterNewExpenseRows(items.value, rows);
    acceptedRows = filtered.rows;
    skipped = filtered.skipped;
    items.value.push(...acceptedRows);
  }
  filterKind.value = 'all';
  searchText.value = '';
  pasteMessage.value = source + ' ' + acceptedRows.length + ' 行'
    + (skipped ? '，已跳过 ' + skipped + ' 条页面中已有明细' : '')
    + '，请确认后保存';
}

function importPastedRows(replace = false) {
  errMsg.value = '';
  confirmPasteOverwrite.value = false;
  const result = parseExpensePaste(pasteText.value, projectOptions.value, expenseAccountPaths.value);
  applyImportedRows(result, replace, '已导入');
  if (!pasteErrors.value.length) {
    pasteText.value = '';
    pasteOpen.value = false;
  }
}

// 覆盖会清空现有明细：表里有内容时先在页面内确认一次
function requestPasteReplace() {
  if (items.value.length) confirmPasteOverwrite.value = true;
  else importPastedRows(true);
}

function chooseWorkbook(replace = false) {
  workbookReplace.value = replace;
  workbookInput.value?.click();
}

function requestWorkbookReplace() {
  if (items.value.length) confirmWorkbookOverwrite.value = true;
  else chooseWorkbook(true);
}

function confirmWorkbookReplace() {
  confirmWorkbookOverwrite.value = false;
  chooseWorkbook(true);
}

async function importWorkbookRows(event) {
  errMsg.value = '';
  const file = event.target.files?.[0];
  event.target.value = '';
  if (!file) return;
  try {
    const result = await importWorkbookFile(file, projectOptions.value, expenseAccountPaths.value);
    applyImportedRows(result, workbookReplace.value, 'Excel 已导入');
  } catch (error) {
    pasteErrors.value = [(error && error.message) || 'Excel 导入失败'];
  }
}

function accountDatalistId(index, level) {
  return 'expense-account-level-' + level + '-' + index;
}

function accountLevelOptions(row, level) {
  return accountOptions(row, level, expenseAccountPaths.value);
}

function syncAccountLevels(row, level) {
  clearInvalidLowerLevels(row, level, expenseAccountPaths.value);
}

function syncAllocationType(row) {
  if (row.allocation_type !== 'project') row.direct_project = '';
}

function rowValidationErrors(row, index) {
  const lineNo = index + 1;
  const errors = [];
  errors.push(...validateExpenseAccount(row, lineNo, expenseAccountPaths.value, true));
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
  if (isYearScope.value || !catalogReady.value) return;
  errMsg.value = '';
  const errors = items.value.flatMap((row, index) => rowValidationErrors(row, index));
  if (errors.length) {
    errMsg.value = errors.slice(0, 5).join('；') + (errors.length > 5 ? '；还有 ' + (errors.length - 5) + ' 条错误' : '');
    return;
  }
  if (pendingAccountPaths.value.length && !confirmNewAccounts.value) {
    errMsg.value = '请先确认新增下方列出的三级/四级费用科目';
    return;
  }
  saving.value = true;
  try {
    const d = await saver.submit({
      period: period.value,
      items: JSON.stringify(payloadRows()),
      new_account_paths: JSON.stringify(pendingAccountPaths.value),
    });
    status.value = d.status;
    items.value = normalizeRows(d.items || []);
    confirmNewAccounts.value = false;
    await accountCatalog.reload();
  } catch (e) {
    errMsg.value = serverMessage(saver.error || e, '保存失败');
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

function onKeydown(event) {
  if (event.key === 'Escape' && pasteOpen.value) closePaste();
}
onMounted(() => window.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));

watch(period, () => loader.reload());
watch(periodScope, () => { confirmWorkbookOverwrite.value = false; loader.reload(); });
watch(() => pendingAccountPaths.value.map((path) => Object.values(path).join('|')).join('||'), () => { confirmNewAccounts.value = false; });
</script>

<template>
  <RdPage title="研发费用导入" subtitle="录入或导入本期研发费用。公共费用按工时比例分摊，项目费用直接归属。">
    <template #ctl>
      <span v-if="status" class="tag">状态：{{ status }}</span>
      <RdSeg :model-value="periodScope" :options="scopeOptions" label="统计范围" @update:model-value="setPeriodScope" />
      <RdPeriod />
    </template>

    <div v-if="loader.loading || accountCatalog.loading" class="muted" style="padding: 16px 0">加载中…</div>
    <template v-else>
      <div class="kpis">
        <RdKpi :label="isYearScope ? '年度累计费用合计' : '本期费用合计'" :value="fmt(totals.total)" unit="元" :sub="`共 ${items.length} 行`" />
        <RdKpi label="公共费用" :value="fmt(totals.common)" unit="元" :sub="`占 ${totals.commonShare}% · 按工时比例分摊`" />
        <RdKpi label="项目费用" :value="fmt(totals.project)" unit="元" :sub="`占 ${totals.projectShare}% · 直接归属`" />
      </div>

      <div v-if="isYearScope" class="note info"><RdIcon name="info" /><span class="grow">年度视图只读。要录入或修改，请切回月度。</span></div>

      <div v-if="!isYearScope && items.length" class="card">
        <div class="hd"><b>保存前检查</b><span class="muted">{{ checksPassed ? '全部通过' : '有待处理项' }}</span></div>
        <div class="bd" style="padding-top: 4px">
          <div class="chk" :class="errorRowCount ? 'bad' : 'ok'">
            <RdIcon :name="errorRowCount ? 'alert' : 'check'" />
            <span>{{ errorRowCount ? `${errorRowCount} 行有问题（金额未填、项目未选或科目不合规），见下方明细` : '金额、归属、项目都已填写' }}</span>
          </div>
          <div class="chk" :class="pendingAccountPaths.length && !confirmNewAccounts ? 'warn' : 'ok'">
            <RdIcon :name="pendingAccountPaths.length && !confirmNewAccounts ? 'alert' : 'check'" />
            <span>{{ pendingAccountPaths.length ? (confirmNewAccounts ? `${pendingAccountPaths.length} 个新科目已确认，保存时创建` : `${pendingAccountPaths.length} 个科目目录里没有，需确认后创建`) : '科目都在目录里' }}</span>
          </div>
          <div class="chk" :class="duplicateGroupCount ? 'warn' : 'ok'">
            <RdIcon :name="duplicateGroupCount ? 'alert' : 'check'" />
            <span>{{ duplicateGroupCount ? `${duplicateGroupCount} 组重复凭证行（同凭证号、同科目）` : '没有重复的凭证行' }}</span>
          </div>
        </div>
      </div>

      <div v-if="!isYearScope && pendingAccountPaths.length" class="note warn">
        <RdIcon name="alert" />
        <div class="grow">
          <div><b>检测到 {{ pendingAccountPaths.length }} 个新三级/四级费用科目</b></div>
          <ul style="margin: 4px 0 0; padding-left: 18px; list-style: disc">
            <li v-for="path in pendingAccountPaths" :key="[path.account_level_1, path.account_level_2, path.account_level_3, path.account_level_4].join('|')">{{ [path.account_level_1, path.account_level_2, path.account_level_3, path.account_level_4].filter(Boolean).join(' → ') }}</li>
          </ul>
          <label style="display: flex; gap: 8px; align-items: flex-start; margin-top: 8px">
            <input v-model="confirmNewAccounts" type="checkbox" style="margin-top: 4px" />
            <span>我已核对，保存时将创建这些科目并导入本月费用。</span>
          </label>
        </div>
      </div>

      <div v-if="confirmWorkbookOverwrite" class="note bad">
        <RdIcon name="alert" />
        <span class="grow"><b>覆盖当前表格？</b> 会清空现有 {{ items.length }} 行明细，再放入 Excel 里的内容。</span>
        <button type="button" class="btn sm bad" @click="confirmWorkbookReplace">确认覆盖</button>
        <button type="button" class="btn sm" @click="confirmWorkbookOverwrite = false">返回</button>
      </div>

      <template v-if="!pasteOpen">
        <div v-if="pasteErrors.length" class="note bad">
          <RdIcon name="alert" />
          <div class="grow">
            <p v-for="(message, idx) in visiblePasteErrors" :key="idx" style="margin: 0">{{ message }}</p>
            <p v-if="remainingPasteErrorCount" style="margin: 0">还有 {{ remainingPasteErrorCount }} 条错误</p>
          </div>
          <button type="button" class="btn sm" @click="dismissImportMessages">清空</button>
        </div>
        <div v-else-if="pasteMessage" class="note ok">
          <RdIcon name="check" /><span class="grow">{{ pasteMessage }}</span>
          <button type="button" class="btn sm" @click="dismissImportMessages">知道了</button>
        </div>
      </template>

      <div class="bar">
        <div class="row">
          <div class="chips">
            <button v-for="chip in filterChips" :key="chip.value" type="button" class="chip" :aria-pressed="filterKind === chip.value" @click="filterKind = chip.value">{{ chip.label }}<small>{{ chip.count }}</small></button>
          </div>
          <label class="input" style="width: 210px"><RdIcon name="search" /><input v-model="searchText" placeholder="搜索凭证号、科目" /></label>
        </div>
        <div class="row">
          <template v-if="!isYearScope">
            <button type="button" class="btn quiet" @click="openPaste"><RdIcon name="copy" />粘贴导入</button>
            <button type="button" class="btn quiet" @click="requestWorkbookReplace">覆盖导入…</button>
            <button type="button" class="btn" @click="addRow"><RdIcon name="plus" />添加一行</button>
          </template>
          <button type="button" class="btn" :disabled="exporting || !items.length" @click="exportCurrentExpense"><RdIcon name="download" />{{ exporting ? '导出中…' : '导出 Excel' }}</button>
          <template v-if="!isYearScope">
            <button type="button" class="btn pri" @click="chooseWorkbook(false)"><RdIcon name="upload" />导入 Excel</button>
            <input ref="workbookInput" type="file" accept=".xlsx,.xls" class="hidden" @change="importWorkbookRows" />
          </template>
        </div>
      </div>

      <div v-if="isYearScope" class="card">
        <div class="tbl overflow-x-auto">
          <table class="min-w-[1500px] whitespace-nowrap">
            <thead>
              <tr>
                <th class="w-28">日期</th>
                <th class="w-28">凭证号</th>
                <th class="min-w-[180px]">一级科目</th>
                <th class="min-w-[220px]">二级科目</th>
                <th class="min-w-[340px]">三级科目</th>
                <th class="min-w-[220px]">四级科目</th>
                <th class="r min-w-[140px]">费用金额</th>
                <th class="min-w-[150px]">归属方式</th>
                <th class="min-w-[260px]">所属项目</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="{ row: it, index: i } in visibleEntries" :key="i">
                <td class="num muted">{{ it.period }}</td>
                <td class="num">{{ it.voucher_no }}</td>
                <td>{{ it.account_level_1 }}</td>
                <td>{{ it.account_level_2 }}</td>
                <td>{{ it.account_level_3 }}</td>
                <td>{{ it.account_level_4 }}</td>
                <td class="r num">{{ fmt(Number(it.amount || 0)) }}</td>
                <td>{{ it.allocation_type === 'project' ? '项目费用' : '公共费用' }}</td>
                <td>{{ it.allocation_type === 'project' ? projectLabelByName(it.direct_project) : '-' }}</td>
              </tr>
              <tr v-if="!visibleEntries.length"><td colspan="9" class="muted" style="text-align: center; padding: 30px">{{ items.length ? '没有符合条件的明细' : '本期暂无费用' }}</td></tr>
            </tbody>
            <tfoot v-if="items.length">
              <tr>
                <td colspan="6">合计（公共 {{ fmt(totals.common) }} + 项目 {{ fmt(totals.project) }}）</td>
                <td class="r num">{{ fmt(total) }}</td>
                <td colspan="2"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <div v-else class="card">
        <div class="tbl overflow-x-auto">
          <table class="min-w-[1500px] whitespace-nowrap">
            <thead>
              <tr>
                <th style="width: 34px">#</th>
                <th class="w-28">凭证号</th>
                <th class="min-w-[180px]">一级科目</th>
                <th class="min-w-[220px]">二级科目</th>
                <th class="min-w-[340px]">三级科目</th>
                <th class="min-w-[220px]">四级科目</th>
                <th class="r min-w-[140px]">费用金额</th>
                <th class="min-w-[150px]">归属方式</th>
                <th class="min-w-[260px]">所属项目</th>
                <th class="w-12">删除</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="{ row: it, index: i, problems } in visibleEntries" :key="i">
                <tr :class="{ rowerr: problems.length }">
                  <td class="num muted">{{ i + 1 }}</td>
                  <td><input v-model="it.voucher_no" class="field num" placeholder="V001" /></td>
                  <td>
                    <input v-model="it.account_level_1" :list="accountDatalistId(i, 1)" class="field" placeholder="研发支出" @change="syncAccountLevels(it, 1)" />
                    <datalist :id="accountDatalistId(i, 1)"><option v-for="option in accountLevelOptions(it, 1)" :key="option" :value="option"></option></datalist>
                  </td>
                  <td>
                    <input v-model="it.account_level_2" :list="accountDatalistId(i, 2)" class="field" placeholder="直接投入费用" @change="syncAccountLevels(it, 2)" />
                    <datalist :id="accountDatalistId(i, 2)"><option v-for="option in accountLevelOptions(it, 2)" :key="option" :value="option"></option></datalist>
                  </td>
                  <td>
                    <input v-model="it.account_level_3" :list="accountDatalistId(i, 3)" class="field" placeholder="如 差旅费" @change="syncAccountLevels(it, 3)" />
                    <datalist :id="accountDatalistId(i, 3)"><option v-for="option in accountLevelOptions(it, 3)" :key="option" :value="option"></option></datalist>
                  </td>
                  <td>
                    <input v-model="it.account_level_4" :list="accountDatalistId(i, 4)" class="field" placeholder="可为空" />
                    <datalist :id="accountDatalistId(i, 4)"><option v-for="option in accountLevelOptions(it, 4)" :key="option" :value="option"></option></datalist>
                  </td>
                  <td><input v-model="it.amount" type="number" step="0.01" class="field num" style="text-align: right" placeholder="0" /></td>
                  <td>
                    <select v-model="it.allocation_type" class="field" @change="syncAllocationType(it)">
                      <option v-for="type in ALLOCATION_TYPES" :key="type.v" :value="type.v">{{ type.l }}</option>
                    </select>
                  </td>
                  <td>
                    <select v-model="it.direct_project" :disabled="it.allocation_type !== 'project'" class="field">
                      <option value="">请选择项目</option>
                      <option v-for="project in projectOptions" :key="project.name" :value="project.name">{{ projectLabel(project) }}</option>
                    </select>
                  </td>
                  <td class="r nw"><button type="button" class="btn quiet sm bad" aria-label="删除这一行" @click="delRow(i)"><RdIcon name="trash" /></button></td>
                </tr>
                <tr v-if="problems.length" class="rowerr">
                  <td></td>
                  <td colspan="9" style="font-size: 12px; padding-top: 0; color: var(--rd-bad)">{{ problems.join('；') }}</td>
                </tr>
              </template>
              <tr v-if="!visibleEntries.length"><td colspan="10" class="muted" style="text-align: center; padding: 30px">{{ items.length ? '没有符合条件的明细' : '本期暂无费用，点“添加一行”录入，或粘贴 / 导入 Excel' }}</td></tr>
            </tbody>
            <tfoot v-if="items.length">
              <tr>
                <td></td>
                <td colspan="5">合计（公共 {{ fmt(totals.common) }} + 项目 {{ fmt(totals.project) }}）</td>
                <td class="r num">{{ fmt(total) }}</td>
                <td colspan="3"></td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div v-if="errMsg" class="note bad" style="margin: 12px 16px 0"><RdIcon name="alert" /><span class="grow">{{ errMsg }}</span></div>
        <div class="savebar">
          <div class="row">
            <span><b class="num">{{ fmt(total) }}</b> <span class="muted">元 · {{ items.length }} 行</span></span>
            <span v-if="errorRowCount" class="tag bad">{{ errorRowCount }} 行有问题</span>
            <span v-if="pendingAccountPaths.length && !confirmNewAccounts" class="tag warn">请先确认新科目</span>
            <span class="muted">保存会整月覆盖本月已有费用</span>
          </div>
          <button type="button" class="btn pri" :disabled="saveBlocked" @click="save">{{ saving ? '保存中…' : '保存本月费用' }}</button>
        </div>
      </div>
      <p v-if="errMsg && isYearScope" class="muted" style="color: var(--rd-bad)">{{ errMsg }}</p>
    </template>

    <Teleport to="body">
      <div v-if="pasteOpen" class="rd">
        <div class="rd-drawer-bg" @click="closePaste"></div>
        <aside class="rd-drawer" style="width: min(640px, 100%)" role="dialog" aria-modal="true" aria-label="批量粘贴导入">
          <header>
            批量粘贴导入
            <button type="button" class="btn quiet sm" aria-label="关闭" @click="closePaste"><RdIcon name="x" /></button>
          </header>
          <div class="body">
            <p class="muted" style="margin: 0">从 Excel 复制整块内容后粘贴到下面。每行按“凭证号、1-4 级费用科目、费用金额、项目”排列，最后一列写项目编号；公共费用就写公共费用。</p>
            <textarea v-model="pasteText" :placeholder="pastePlaceholder" rows="10" class="field" style="min-height: 200px; white-space: pre"></textarea>
            <div v-if="pasteErrors.length" class="note bad" style="margin: 0">
              <RdIcon name="alert" />
              <div class="grow">
                <p v-for="(message, idx) in visiblePasteErrors" :key="idx" style="margin: 0">{{ message }}</p>
                <p v-if="remainingPasteErrorCount" style="margin: 0">还有 {{ remainingPasteErrorCount }} 条错误</p>
              </div>
            </div>
          </div>
          <footer style="flex-wrap: wrap">
            <template v-if="confirmPasteOverwrite">
              <span class="muted" style="align-self: center; flex: 1">覆盖会清空现有 {{ items.length }} 行明细，再放入粘贴的内容。</span>
              <button type="button" class="btn sm bad" @click="importPastedRows(true)">确认覆盖</button>
              <button type="button" class="btn sm" @click="confirmPasteOverwrite = false">返回</button>
            </template>
            <template v-else>
              <button v-if="pasteText || pasteErrors.length" type="button" class="btn quiet" @click="clearPaste">清空</button>
              <button type="button" class="btn" :disabled="!pasteText.trim()" @click="requestPasteReplace">覆盖当前表格</button>
              <button type="button" class="btn pri" :disabled="!pasteText.trim()" @click="importPastedRows(false)">追加导入</button>
            </template>
          </footer>
        </aside>
      </div>
    </Teleport>
  </RdPage>
</template>
