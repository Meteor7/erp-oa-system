<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { period, periodScope, PERIOD_SCOPES, setPeriodScope, periodScopeLabel } from '../lib/period';
import { EXPENSE_ACCOUNT_PATHS, clearInvalidLowerLevels, accountOptions, unknownExpenseAccountPaths, validateExpenseAccount } from '../lib/expenseAccounts';
import { deriveExpenseCategory, filterNewExpenseRows, importWorkbookFile, parseExpensePaste, resolveProjectValue } from '../lib/expensePaste';
import {
  SORT_OPTIONS, STATUS_FILTERS, account2Options, accountPathKey, activeFilterChips, ariaSort, buildDisplayRows, computeStripState,
  duplicateVoucherRows, emptyFilters, errorFields, expenseTotals, filterExpenseEntries, groupTitle, isProjectRow,
  nextSort, projectFilterOptions, pruneAcks, saveBlockReason, scopeCounts, sortExpenseEntries, sortIndicator, statusCounts, stripLinePrefix, sumAmounts,
} from '../lib/rdExpense';
import { exportTableWorkbook } from '../lib/tableExport';
import RdPage from '../components/rd/RdPage.vue';
import RdPeriod from '../components/rd/RdPeriod.vue';
import RdSeg from '../components/rd/RdSeg.vue';
import RdKpi from '../components/rd/RdKpi.vue';
import RdIcon from '../components/rd/RdIcon.vue';
import '../styles/rdExpenseImport.css';

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

// 工具栏状态：筛选、排序、按凭证号分组
const filters = reactive(emptyFilters());
const sortKey = ref('line');
const groupOn = ref(false);
// “确认无误”只对本次编辑有效：用内容键记，换期间 / 重新加载 / 覆盖导入就清空
const ackedKeys = ref(new Set());
// 在表格里输入时把当前显示的行序固定下来，免得筛选 / 排序 / 分组让正在编辑的行跳走
const frozen = ref(null);
const popOpen = ref(false);
const importMenuOpen = ref(false);
const stripRef = ref(null);
const popBtn = ref(null);
const importMenuRef = ref(null);
const importBtn = ref(null);
const tableScroll = ref(null);
const flashIndex = ref(-1);
let flashTimer = null;

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
    resetEditingSession();
    filters.account2 = '';
    filters.project = '';
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
const dataLoading = computed(() => loader.loading || accountCatalog.loading);

// 每一行的问题：校验错误（会挡住保存）+ 完全相同的行（只提醒，不挡保存）+ 目录里没有的新科目。年度视图只读，不做检查。
const duplicates = computed(() => (isYearScope.value ? { groups: [], keys: [], indexes: new Map() } : duplicateVoucherRows(items.value)));
const noticeGroups = computed(() => duplicates.value.groups.map((indexes, g) => {
  const key = duplicates.value.keys[g];
  return { key, indexes, acked: ackedKeys.value.has(key), lineText: indexes.map((n) => n + 1).join('、') };
}));
const noticeByIndex = computed(() => {
  const map = new Map();
  noticeGroups.value.forEach((group) => group.indexes.forEach((index) => map.set(index, group)));
  return map;
});
const pendingNoticeGroups = computed(() => noticeGroups.value.filter((group) => !group.acked));
const ackedNoticeCount = computed(() => noticeGroups.value.filter((group) => group.acked).length);
const newPathKeys = computed(() => new Set(pendingAccountPaths.value.map(accountPathKey)));
const entries = computed(() => items.value.map((row, index) => {
  const errors = isYearScope.value ? [] : rowValidationErrors(row, index).map(stripLinePrefix);
  const group = noticeByIndex.value.get(index);
  const others = group ? group.indexes.filter((n) => n !== index) : [];
  return {
    row,
    index,
    errors,
    bad: errorFields(errors),
    notice: group ? {
      key: group.key,
      acked: group.acked,
      text: '与第 ' + others.map((n) => n + 1).join('、') + ' 行完全相同（凭证号、科目、金额、项目），请确认不是重复录入；不影响保存',
    } : null,
    isNew: !isYearScope.value && newPathKeys.value.has(accountPathKey(row)),
    projectText: isProjectRow(row) && row.direct_project ? projectLabelByName(row.direct_project) : '',
  };
}));
const errorEntries = computed(() => entries.value.filter((entry) => entry.errors.length));
const errorRowCount = computed(() => errorEntries.value.length);

// 筛选 / 排序 / 分组
const scopeCountMap = computed(() => scopeCounts(entries.value));
const scopeChips = computed(() => [
  { value: 'all', label: '全部', count: scopeCountMap.value.all },
  { value: 'common', label: '公共', count: scopeCountMap.value.common },
  { value: 'project', label: '项目', count: scopeCountMap.value.project },
]);
const statusCountMap = computed(() => statusCounts(entries.value));
const statusOptions = computed(() => STATUS_FILTERS
  .filter((item) => !isYearScope.value || item.value === 'foreign')
  .map((item) => ({ ...item, count: statusCountMap.value[item.value] })));
const account2List = computed(() => account2Options(entries.value));
const projectList = computed(() => projectFilterOptions(entries.value, projectLabelByName));
const filterChips = computed(() => activeFilterChips(filters, { projectLabel: projectLabelByName }));
const liveEntries = computed(() => sortExpenseEntries(filterExpenseEntries(entries.value, filters), sortKey.value));
const shownEntries = computed(() => {
  const lock = frozen.value;
  if (!lock) return liveEntries.value;
  return lock.order.map((index) => entries.value[index]).filter(Boolean);
});
const displayRows = computed(() => buildDisplayRows(shownEntries.value, {
  group: groupOn.value,
  keyOf: frozen.value ? (entry) => frozen.value.vouchers.get(entry.index) ?? String(entry.row.voucher_no ?? '').trim() : undefined,
}));
const shownTotal = computed(() => sumAmounts(shownEntries.value));
const colCount = computed(() => (isYearScope.value ? 9 : 10));

// 检查状态条与保存
const stripState = computed(() => (isYearScope.value || !items.value.length ? null : computeStripState({
  errorRows: errorRowCount.value,
  newCount: pendingAccountPaths.value.length,
  newConfirmed: confirmNewAccounts.value,
  noticePending: pendingNoticeGroups.value.length,
  noticeAcked: ackedNoticeCount.value,
})));
const showPop = computed(() => popOpen.value && Boolean(stripState.value?.hasList));
const newAccountsPending = computed(() => pendingAccountPaths.value.length > 0 && !confirmNewAccounts.value);
const saveReason = computed(() => saveBlockReason({
  isYear: isYearScope.value,
  loading: dataLoading.value,
  catalogReady: catalogReady.value,
  saving: saving.value,
  errorRows: errorRowCount.value,
  newPending: newAccountsPending.value,
}));
// 本月分摊已定版：费用不能再改（服务端也会拒绝），要改先让财务主管在台账页撤销定版。
const finalized = computed(() => !isYearScope.value && status.value === 'Allocated');
const FINALIZED_TEXT = '本月分摊已定版，费用不能修改。请财务主管先在「研发费用台账」撤销定版。';
const statusText = computed(() => (status.value === 'Allocated' ? '已定版' : status.value));
const saveBlocked = computed(() => finalized.value || Boolean(saveReason.value));
const saveTip = computed(() => (finalized.value ? FINALIZED_TEXT : saveReason.value || '保存会整月覆盖本月已有费用'));

function pathText(path) {
  return [path.account_level_1, path.account_level_2, path.account_level_3, path.account_level_4].filter(Boolean).join(' → ');
}

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

// 表里的行被整体换掉（重新加载、保存后回读、覆盖导入）：确认无误的记录和固定的行序都作废
function resetEditingSession() {
  ackedKeys.value = new Set();
  frozen.value = null;
}

function resetFilters() {
  Object.assign(filters, emptyFilters());
}

function clearFilter(key) {
  filters[key] = key === 'scope' ? 'all' : '';
}

function addRow() {
  resetFilters();
  sortKey.value = 'line';
  groupOn.value = false;
  frozen.value = null;
  items.value.push(normalizeRow());
  const index = items.value.length - 1;
  nextTick(() => {
    const el = document.getElementById('ei-row-' + index);
    el?.scrollIntoView({ block: 'nearest' });
    el?.querySelector('input')?.focus({ preventScroll: true });
  });
}

function delRow(i) {
  frozen.value = null;
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
    resetEditingSession();
  } else {
    const filtered = filterNewExpenseRows(items.value, rows);
    acceptedRows = filtered.rows;
    skipped = filtered.skipped;
    items.value.push(...acceptedRows);
    frozen.value = null;
  }
  resetFilters();
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

// “导入 Excel”下拉菜单的两项
function closeImportMenu(refocus = false) {
  importMenuOpen.value = false;
  if (refocus) importBtn.value?.focus();
}

function toggleImportMenu() {
  importMenuOpen.value = !importMenuOpen.value;
  if (importMenuOpen.value) nextTick(() => importMenuRef.value?.querySelector('[role="menuitem"]')?.focus());
}

function importAppend() {
  closeImportMenu();
  chooseWorkbook(false);
}

function importOverwrite() {
  closeImportMenu();
  requestWorkbookReplace();
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
  if (isYearScope.value || !catalogReady.value || dataLoading.value) return;
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
    resetEditingSession();
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

// 提醒：只对本次编辑有效，不挡保存
function toggleAck(key) {
  const next = new Set(ackedKeys.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  ackedKeys.value = next;
}

function clickSort(column) {
  sortKey.value = nextSort(sortKey.value, column);
}

// 在表格里输入时固定行序，离开表格再按最新的筛选 / 排序重排
function freezeOrder(event) {
  if (frozen.value || !event.target?.closest?.('input, select')) return;
  frozen.value = {
    order: liveEntries.value.map((entry) => entry.index),
    vouchers: new Map(entries.value.map((entry) => [entry.index, String(entry.row.voucher_no ?? '').trim()])),
  };
}

function releaseOrder(event) {
  const next = event.relatedTarget;
  if (next && event.currentTarget.contains(next)) return;
  frozen.value = null;
}

async function jumpToRow(index) {
  popOpen.value = false;
  frozen.value = null;
  if (!liveEntries.value.some((entry) => entry.index === index)) resetFilters();
  await nextTick();
  const el = document.getElementById('ei-row-' + index);
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  el.querySelector('.ei-bad')?.focus({ preventScroll: true });
  flashIndex.value = index;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { flashIndex.value = -1; }, 1900);
}

function onKeydown(event) {
  if (event.key !== 'Escape') return;
  if (pasteOpen.value) closePaste();
  else if (importMenuOpen.value) closeImportMenu(true);
  else if (popOpen.value) {
    popOpen.value = false;
    popBtn.value?.focus();
  }
}

function onPointerDown(event) {
  if (popOpen.value && stripRef.value && !stripRef.value.contains(event.target)) popOpen.value = false;
  if (importMenuOpen.value && importMenuRef.value && !importMenuRef.value.contains(event.target)) importMenuOpen.value = false;
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  document.addEventListener('mousedown', onPointerDown);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
  document.removeEventListener('mousedown', onPointerDown);
  clearTimeout(flashTimer);
});

watch(period, () => loader.reload());
watch(periodScope, () => { confirmWorkbookOverwrite.value = false; loader.reload(); });
watch(() => pendingAccountPaths.value.map((path) => Object.values(path).join('|')).join('||'), () => { confirmNewAccounts.value = false; });
// 改过内容、不再“完全相同”的组，它的确认无误就作废
watch(() => noticeGroups.value.map((group) => group.key).join('\u0001'), () => {
  ackedKeys.value = pruneAcks(ackedKeys.value, noticeGroups.value.map((group) => group.key));
});
// 换了筛选 / 排序 / 分组，行序按新条件重排
watch([filters, sortKey, groupOn], () => { frozen.value = null; }, { deep: true });
</script>

<template>
  <RdPage title="研发费用导入" subtitle="录入或导入本期研发费用。公共费用按工时比例分摊，项目费用直接归属。">
    <template #ctl>
      <span v-if="status" class="tag" :class="{ warn: finalized }">状态：{{ statusText }}</span>
      <RdSeg :model-value="periodScope" :options="scopeOptions" label="统计范围" @update:model-value="setPeriodScope" />
      <RdPeriod />
      <button v-if="!isYearScope" type="button" class="btn pri" :disabled="saveBlocked" :title="saveTip" @click="save">{{ saving ? '保存中…' : '保存本月费用' }}</button>
    </template>

    <div v-if="loader.loading || accountCatalog.loading" class="muted" style="padding: 16px 0">加载中…</div>
    <template v-else>
      <div class="kpis">
        <RdKpi :label="isYearScope ? '年度累计费用合计' : '本期费用合计'" :value="fmt(totals.total)" unit="元" :sub="`共 ${items.length} 行`" />
        <RdKpi label="公共费用" :value="fmt(totals.common)" unit="元" :sub="`占 ${totals.commonShare}% · 按工时比例分摊`" />
        <RdKpi label="项目费用" :value="fmt(totals.project)" unit="元" :sub="`占 ${totals.projectShare}% · 直接归属`" />
      </div>

      <div v-if="isYearScope" class="note info"><RdIcon name="info" /><span class="grow">年度视图只读。要录入或修改，请切回月度。</span></div>

      <div v-if="errMsg" class="note bad" role="alert"><RdIcon name="alert" /><span class="grow">{{ errMsg }}</span></div>

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

      <div v-if="finalized" class="ei-strip bad" role="status">
        <RdIcon name="lock" />
        <b>本月分摊已定版</b>
        <span class="ei-strip-sum">费用不能修改。请财务主管先在「研发费用台账」撤销定版。</span>
      </div>

      <div v-else-if="stripState" ref="stripRef" class="ei-stripwrap">
        <div class="ei-strip" :class="stripState.tone" role="status">
          <RdIcon :name="stripState.tone === 'ok' ? 'check' : 'alert'" />
          <b>{{ stripState.title }}</b>
          <span class="ei-strip-sum">{{ stripState.summary }}</span>
          <span class="ei-strip-hint">保存会整月覆盖本月已有费用</span>
          <button v-if="stripState.hasList" ref="popBtn" type="button" class="btn sm" aria-controls="ei-todo" :aria-expanded="showPop" @click="popOpen = !popOpen">处理清单 {{ showPop ? '▴' : '▾' }}</button>
        </div>
        <div v-if="showPop" id="ei-todo" class="ei-pop" role="dialog" aria-label="处理清单">
          <div v-for="entry in errorEntries" :key="'e' + entry.index" class="ei-it">
            <span class="tag bad">问题</span>
            <span class="t">第 {{ entry.index + 1 }} 行：{{ entry.errors.join('；') }}</span>
            <button type="button" class="btn sm" :aria-label="'跳到第 ' + (entry.index + 1) + ' 行'" @click="jumpToRow(entry.index)">跳到该行</button>
          </div>
          <div v-if="pendingAccountPaths.length" class="ei-it">
            <span class="tag info">新科目</span>
            <div class="t">
              <div>{{ pendingAccountPaths.length }} 个科目目录里还没有：</div>
              <ul>
                <li v-for="path in pendingAccountPaths" :key="accountPathKey(path)">{{ pathText(path) }}</li>
              </ul>
              <label class="ei-check"><input v-model="confirmNewAccounts" type="checkbox" /><span>我已核对，保存时创建</span></label>
            </div>
          </div>
          <div v-for="group in pendingNoticeGroups" :key="'n' + group.key" class="ei-it">
            <span class="tag warn">提醒</span>
            <span class="t">第 {{ group.lineText }} 行完全相同（凭证号、科目、金额、项目），请确认不是重复录入</span>
            <button type="button" class="btn sm" @click="toggleAck(group.key)">确认无误</button>
          </div>
          <div class="muted">红色问题必须处理；黄色提醒点“确认无误”就不再提示，也可以不管，不影响保存。</div>
        </div>
      </div>

      <div class="card">
        <div class="ei-tools">
          <div class="ei-toolrow">
            <label class="input ei-search"><RdIcon name="search" /><input v-model="filters.query" aria-label="搜索费用明细" placeholder="搜索凭证号、科目、项目、金额" /></label>
            <div class="seg" role="group" aria-label="归属">
              <button v-for="chip in scopeChips" :key="chip.value" type="button" :aria-pressed="filters.scope === chip.value" @click="filters.scope = chip.value">{{ chip.label }}<small>{{ chip.count }}</small></button>
            </div>
            <select v-model="filters.account2" class="field ei-sel" aria-label="二级科目">
              <option value="">二级科目：全部</option>
              <option v-for="option in account2List" :key="option" :value="option">{{ option }}</option>
            </select>
            <select v-model="filters.project" class="field ei-sel" aria-label="项目">
              <option value="">项目：全部</option>
              <option v-for="option in projectList" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <select v-model="filters.status" class="field ei-sel" aria-label="状态">
              <option value="">状态：全部</option>
              <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}（{{ option.count }}）</option>
            </select>
            <select v-model="sortKey" class="field ei-sel" aria-label="排序">
              <option v-for="option in SORT_OPTIONS" :key="option.value" :value="option.value">排序：{{ option.label }}</option>
            </select>
            <label class="ei-switch"><input v-model="groupOn" type="checkbox" role="switch" /><b aria-hidden="true"></b>按凭证号分组</label>
            <div class="ei-actions">
              <template v-if="!isYearScope">
                <div ref="importMenuRef" class="ei-menuwrap">
                  <button ref="importBtn" type="button" class="btn" aria-haspopup="menu" :aria-expanded="importMenuOpen" @click="toggleImportMenu"><RdIcon name="upload" />导入 Excel ▾</button>
                  <div v-if="importMenuOpen" class="ei-menu" role="menu" aria-label="导入 Excel">
                    <button type="button" role="menuitem" class="ei-mi" @click="importAppend"><b>追加到现有费用</b><span>Excel 里的行加到下面，原来的保留</span></button>
                    <button type="button" role="menuitem" class="ei-mi" @click="importOverwrite"><b>覆盖现有费用…</b><span>先清空现有明细，再放入 Excel 的内容（会再确认一次）</span></button>
                  </div>
                </div>
                <input ref="workbookInput" type="file" accept=".xlsx,.xls" class="hidden" @change="importWorkbookRows" />
                <button type="button" class="btn" @click="openPaste"><RdIcon name="copy" />粘贴导入</button>
                <button type="button" class="btn" @click="addRow"><RdIcon name="plus" />添加一行</button>
              </template>
              <button type="button" class="btn" :disabled="exporting || !items.length" @click="exportCurrentExpense"><RdIcon name="download" />{{ exporting ? '导出中…' : '导出 Excel' }}</button>
            </div>
          </div>
          <div class="ei-toolrow">
            <template v-if="filterChips.length">
              <span v-for="chip in filterChips" :key="chip.key" class="ei-fchip">{{ chip.label }}<button type="button" :aria-label="'清除筛选：' + chip.label" @click="clearFilter(chip.key)"><RdIcon name="x" /></button></span>
              <button type="button" class="btn sm quiet" @click="resetFilters">清除全部</button>
            </template>
            <span class="ei-result">显示 <b>{{ shownEntries.length }}</b> / {{ items.length }} 行 · 小计 <b class="num">{{ fmt(shownTotal) }}</b> 元</span>
          </div>
        </div>

        <div v-if="isYearScope" ref="tableScroll" class="tbl overflow-x-auto ei-scroll">
          <table class="min-w-[1500px] whitespace-nowrap">
            <thead>
              <tr>
                <th class="w-28">日期</th>
                <th class="w-28" :aria-sort="ariaSort(sortKey, 'voucher')"><button type="button" class="ei-thbtn" @click="clickSort('voucher')">凭证号 {{ sortIndicator(sortKey, 'voucher') }}</button></th>
                <th class="min-w-[180px]">一级科目</th>
                <th class="min-w-[220px]">二级科目</th>
                <th class="min-w-[340px]">三级科目</th>
                <th class="min-w-[220px]">四级科目</th>
                <th class="r min-w-[140px]" :aria-sort="ariaSort(sortKey, 'amount')"><button type="button" class="ei-thbtn" @click="clickSort('amount')">费用金额 {{ sortIndicator(sortKey, 'amount') }}</button></th>
                <th class="min-w-[150px]">归属方式</th>
                <th class="min-w-[260px]">所属项目</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="{ type, key, row: it, index: i, group } in displayRows" :key="key">
                <tr v-if="type === 'group'" class="ei-grp">
                  <td :colspan="colCount"><b>{{ groupTitle(group) }}</b><span>{{ group.count }} 行</span><span class="num">小计 {{ fmt(group.subtotal) }} 元</span></td>
                </tr>
                <tr v-else>
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
              </template>
              <tr v-if="!shownEntries.length"><td :colspan="colCount" class="muted" style="text-align: center; padding: 30px">{{ items.length ? '没有符合条件的明细' : '本期暂无费用' }}</td></tr>
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

        <div v-else ref="tableScroll" class="tbl overflow-x-auto ei-scroll ei-tbl" @focusin="freezeOrder" @focusout="releaseOrder">
          <table class="min-w-[1500px] whitespace-nowrap">
            <thead>
              <tr>
                <th style="width: 34px">#</th>
                <th class="w-28" :aria-sort="ariaSort(sortKey, 'voucher')"><button type="button" class="ei-thbtn" @click="clickSort('voucher')">凭证号 {{ sortIndicator(sortKey, 'voucher') }}</button></th>
                <th class="min-w-[180px]">一级科目</th>
                <th class="min-w-[220px]">二级科目</th>
                <th class="min-w-[340px]">三级科目</th>
                <th class="min-w-[220px]">四级科目</th>
                <th class="r min-w-[140px]" :aria-sort="ariaSort(sortKey, 'amount')"><button type="button" class="ei-thbtn" @click="clickSort('amount')">费用金额 {{ sortIndicator(sortKey, 'amount') }}</button></th>
                <th class="min-w-[150px]">归属方式</th>
                <th class="min-w-[260px]">所属项目</th>
                <th class="w-12">删除</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="{ type, key, row: it, index: i, entry, group } in displayRows" :key="key">
                <tr v-if="type === 'group'" class="ei-grp">
                  <td :colspan="colCount"><b>{{ groupTitle(group) }}</b><span>{{ group.count }} 行</span><span class="num">小计 {{ fmt(group.subtotal) }} 元</span></td>
                </tr>
                <template v-else>
                  <tr :id="'ei-row-' + i" :class="{ rowerr: entry.errors.length, rownote: !entry.errors.length && entry.notice && !entry.notice.acked, 'ei-hasmsg': entry.errors.length || entry.notice, 'ei-flash': flashIndex === i }">
                    <td class="num muted">{{ i + 1 }}</td>
                    <td><input v-model="it.voucher_no" class="field num" placeholder="V001" :aria-label="'第 ' + (i + 1) + ' 行凭证号'" /></td>
                    <td>
                      <input v-model="it.account_level_1" :list="accountDatalistId(i, 1)" class="field" :class="{ 'ei-bad': entry.bad.levels.includes(1) }" placeholder="研发支出" :aria-label="'第 ' + (i + 1) + ' 行一级科目'" @change="syncAccountLevels(it, 1)" />
                      <datalist :id="accountDatalistId(i, 1)"><option v-for="option in accountLevelOptions(it, 1)" :key="option" :value="option"></option></datalist>
                    </td>
                    <td>
                      <input v-model="it.account_level_2" :list="accountDatalistId(i, 2)" class="field" :class="{ 'ei-bad': entry.bad.levels.includes(2) }" placeholder="直接投入费用" :aria-label="'第 ' + (i + 1) + ' 行二级科目'" @change="syncAccountLevels(it, 2)" />
                      <datalist :id="accountDatalistId(i, 2)"><option v-for="option in accountLevelOptions(it, 2)" :key="option" :value="option"></option></datalist>
                    </td>
                    <td>
                      <div class="ei-cellflex">
                        <input v-model="it.account_level_3" :list="accountDatalistId(i, 3)" class="field" :class="{ 'ei-bad': entry.bad.levels.includes(3) }" placeholder="如 差旅费" :aria-label="'第 ' + (i + 1) + ' 行三级科目'" @change="syncAccountLevels(it, 3)" />
                        <span v-if="entry.isNew" class="tag info" title="科目目录里还没有这个科目，保存时会创建">新科目</span>
                      </div>
                      <datalist :id="accountDatalistId(i, 3)"><option v-for="option in accountLevelOptions(it, 3)" :key="option" :value="option"></option></datalist>
                    </td>
                    <td>
                      <input v-model="it.account_level_4" :list="accountDatalistId(i, 4)" class="field" :class="{ 'ei-bad': entry.bad.levels.includes(4) }" placeholder="可为空" :aria-label="'第 ' + (i + 1) + ' 行四级科目'" />
                      <datalist :id="accountDatalistId(i, 4)"><option v-for="option in accountLevelOptions(it, 4)" :key="option" :value="option"></option></datalist>
                    </td>
                    <td><input v-model="it.amount" type="number" step="0.01" class="field num" :class="{ 'ei-bad': entry.bad.amount }" style="text-align: right" placeholder="0" :aria-label="'第 ' + (i + 1) + ' 行费用金额'" /></td>
                    <td>
                      <select v-model="it.allocation_type" class="field" :aria-label="'第 ' + (i + 1) + ' 行归属方式'" @change="syncAllocationType(it)">
                        <option v-for="type in ALLOCATION_TYPES" :key="type.v" :value="type.v">{{ type.l }}</option>
                      </select>
                    </td>
                    <td>
                      <select v-model="it.direct_project" :disabled="it.allocation_type !== 'project'" class="field" :class="{ 'ei-bad': entry.bad.project }" :aria-label="'第 ' + (i + 1) + ' 行所属项目'">
                        <option value="">请选择项目</option>
                        <option v-for="project in projectOptions" :key="project.name" :value="project.name">{{ projectLabel(project) }}</option>
                      </select>
                    </td>
                    <td class="r nw"><button type="button" class="btn quiet sm bad" :aria-label="'删除第 ' + (i + 1) + ' 行'" @click="delRow(i)"><RdIcon name="trash" /></button></td>
                  </tr>
                  <tr v-if="entry.errors.length" class="rowerr ei-msg" :class="{ 'ei-hasmsg': entry.notice }">
                    <td></td>
                    <td colspan="9">{{ entry.errors.join('；') }}</td>
                  </tr>
                  <tr v-if="entry.notice" class="ei-msg" :class="entry.notice.acked ? 'ei-done' : 'rownote'">
                    <td></td>
                    <td colspan="9">
                      <span>{{ entry.notice.acked ? '已确认无误（只对本次编辑有效）' : entry.notice.text }}</span>
                      <button type="button" class="btn sm" @click="toggleAck(entry.notice.key)">{{ entry.notice.acked ? '撤回' : '确认无误' }}</button>
                    </td>
                  </tr>
                </template>
              </template>
              <tr v-if="!shownEntries.length"><td :colspan="colCount" class="muted" style="text-align: center; padding: 30px">{{ items.length ? '没有符合条件的明细' : '本期暂无费用，点“添加一行”录入，或粘贴 / 导入 Excel' }}</td></tr>
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
      </div>
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
