<script setup>
import MaterialExecutionProgress from "../components/MaterialExecutionProgress.vue";
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { createResource, FeatherIcon } from 'frappe-ui';
import { useRoute } from 'vue-router';

const columns = [
  { field: 'source_request', label: 'OA 单号', width: '116px' },
  { field: 'material_serial', label: '物料流水号', width: '140px' },
  { field: 'item_name', label: '物料名称', width: '140px' },
  { field: 'project', label: '项目', width: '74px' },
  { field: 'progress_override', label: '主状态', width: '106px' },
  { field: 'status_detail', label: '当前节点', width: '150px' },
  { field: 'material_code', label: '物料编号', width: '132px' },
  { field: 'specification', label: '规格型号', width: '142px' },
  { field: 'quantity', label: 'OA 数量', width: '72px' },
  { field: 'pr_available_quantity', label: '可提 PR', width: '76px' },
  { field: 'pr_create_quantity', label: '本次 PR', width: '84px' },
  { field: 'pr_quantity', label: '已提 PR', width: '76px' },
  { field: 'unit', label: '单位', width: '56px' },
  { field: 'expected_delivery_date', label: 'OA 预计交期', width: '108px' },
  { field: 'pr_numbers', label: 'PR 单号', width: '124px' },
  { field: 'po_numbers', label: 'PO 单号', width: '124px' },
  { field: 'supplier', label: '供应商', width: '150px' },
  { field: 'pr_remaining_quantity', label: 'PR 待比价', width: '100px' },
  { field: 'price_approval_quantity', label: '价格审批数量', width: '110px' },
  { field: 'po_quantity', label: 'PO 数量', width: '86px' },
  { field: 'received_quantity', label: '累计到货', width: '86px' },
  { field: 'oa_approval_trail', label: 'OA 审批轨迹', width: '360px' },
  { field: 'contract_delivery_date', label: '合同交期', width: '130px' },
  { field: 'inspection_status', label: '验收状态', width: '100px' },
  { field: 'payment_status', label: '付款状态', width: '100px' },
  { field: 'price_approval_numbers', label: '价格审批单号', width: '170px' },
  { field: 'current_handler', label: '当前环节人', width: '120px' },
  { field: 'remarks', label: '备注', width: '190px' },
];
const primaryFields = new Set(['source_request', 'material_serial', 'item_name', 'project', 'progress_override', 'status_detail', 'quantity', 'pr_available_quantity', 'pr_create_quantity', 'pr_quantity', 'unit', 'expected_delivery_date', 'pr_numbers', 'po_numbers', 'supplier']);const showAllColumns = ref(false);
const displayColumns = computed(() => showAllColumns.value ? columns : columns.filter((column) => primaryFields.has(column.field)));
const stageStatuses = ['OA审批中', '采购确认中', 'PO处理中', '供应商制作中', '到货验收中', '付款中', '已关闭'];
const defaultStatuses = ['OA审批中', '采购确认中', 'PO处理中', '供应商制作中', '到货验收中', '付款中', '已关闭', '已拒绝', '已撤回', '已取消', '退货中', '换货中', '延期'];
const search = ref('');
const requester = ref('');
const status = ref('');
const message = ref('');
const error = ref('');
const selectedOrder = ref('');
const route = useRoute();
const page = ref(0);
const pageSize = 50;
const executionLine = ref(null);
const sourceRequest = computed(() => String(route.query.request || ''));
watch(() => route.query.request, () => { page.value = 0; executionLine.value = null; loader.reload(); });
const tableRef = ref(null);
const menuField = ref('');
const menuSearch = ref('');
const sortField = ref('');
const sortDirection = ref('asc');
const columnFilters = ref({});
const selectedForPr = ref(new Set());
const prQuantities = ref({});

const loader = createResource({
  url: 'rayher_hr_payroll.api.material_progress.list_material_progress',
  method: 'GET',
  makeParams: () => ({ search: search.value, requester: requester.value, status: status.value, limit: pageSize, offset: page.value * pageSize, source_request: sourceRequest.value }),
  auto: true,
});
const updater = createResource({ url: 'rayher_hr_payroll.api.material_progress.update_material_progress' });
const canceller = createResource({ url: 'rayher_hr_payroll.api.material_progress.cancel_material_progress' });
const prCreator = createResource({ url: 'rayher_hr_payroll.api.procurement_chain.create_pr', method: 'POST' });
const rows = computed(() => loader.data?.items || []);
const requesters = computed(() => loader.data?.requesters || []);
const statusOptions = computed(() => [...new Set([...defaultStatuses, ...rows.value.map((row) => row.progress_status).filter(Boolean)])]);
const counts = computed(() => loader.data?.stage_counts || {});
const total = computed(() => Number(loader.data?.total || 0));
const allStageCount = computed(() => Object.values(counts.value).reduce((sum, value) => sum + Number(value), 0));
function turnPage(delta) { page.value += delta; selectedForPr.value = new Set(); executionLine.value = null; loader.reload(); }
watch(rows, (items) => {
  const line = String(route.query.source_line || '');
  if (line && sourceRequest.value) executionLine.value = { source_request: sourceRequest.value, source_line: line };
});
const eligibleCount = computed(() => rows.value.filter((row) => Number(row.pr_eligible)).length);
const lockedCount = computed(() => Math.max(0, rows.value.length - eligibleCount.value));

function cellValue(row, field) {
  if (field === 'progress_override') return row.progress_status || '';
  if (field === 'pr_create_quantity') return String(prQuantities.value[row.name] ?? row.pr_available_quantity ?? '');
  return String(row[field] ?? '');
}
const editableFields = new Set(['material_code', 'item_name', 'specification', 'product_desc', 'project', 'unit', 'quantity', 'expected_delivery_date', 'current_handler', 'actual_delivery_date', 'remarks']);
function canEditField(field) { return editableFields.has(field); }
function selectionLabel(row) {
  if (Number(row.pr_eligible)) return '可提 PR';
  if (row.progress_status === 'OA审批中') return '待审批';
  if (row.progress_status === '已关闭') return '已关闭';
  return '已提完';
}
function normalized(value) { return String(value ?? '').replace(/\s+/g, ' ').trim(); }
function filteredLocalRows() {
  let result = [...rows.value];
  Object.entries(columnFilters.value).forEach(([field, value]) => {
    if (!value) return;
    const query = value.toLowerCase();
    result = result.filter((row) => cellValue(row, field).toLowerCase().includes(query));
  });
  if (sortField.value) {
    const field = sortField.value;
    const direction = sortDirection.value === 'desc' ? -1 : 1;
    result.sort((a, b) => cellValue(a, field).localeCompare(cellValue(b, field), 'zh-CN', { numeric: true }) * direction);
  }
  return result;
}
const visibleRows = computed(filteredLocalRows);
const groups = computed(() => {
  const map = new Map();
  visibleRows.value.forEach((row) => {
    if (!map.has(row.source_request)) map.set(row.source_request, { key: row.source_request, rows: [], requester: row.requester, projects: new Set(), statuses: {} });
    const group = map.get(row.source_request);
    group.rows.push(row);
    if (row.project) group.projects.add(row.project);
    group.statuses[row.progress_status] = (group.statuses[row.progress_status] || 0) + 1;
  });
  return [...map.values()].map((group) => ({ ...group, projects: [...group.projects].join('、') }));
});

watch(groups, async (items) => {
  const request = String(route.query.request || '').trim();
  if (!request) return;
  const group = items.find((item) => item.key === request);
  if (!group) return;
  await nextTick();
  selectOrder(group);
}, { immediate: true });
function togglePrRow(row, checked) {
  const next = new Set(selectedForPr.value);
  if (checked) {
    next.add(row.name);
    if (!prQuantities.value[row.name]) prQuantities.value[row.name] = Number(row.pr_available_quantity || 0);
  } else {
    next.delete(row.name);
  }
  selectedForPr.value = next;
}
function toggleAllPrRows() {
  const eligible = visibleRows.value.filter((row) => Number(row.pr_eligible));
  const selectAll = selectedForPr.value.size !== eligible.length;
  selectedForPr.value = new Set(selectAll ? eligible.map((row) => row.name) : []);
  if (selectAll) eligible.forEach((row) => { prQuantities.value[row.name] ||= Number(row.pr_available_quantity || 0); });
}
async function createPrFromBoard() {
  const selectedRows = rows.value.filter((row) => selectedForPr.value.has(row.name));
  const lines = selectedRows.map((row) => ({
    source_request: row.source_request,
    source_line: row.source_line,
    quantity: Number(prQuantities.value[row.name] || 0),
  }));
  if (!lines.length) { error.value = '请先选择需求审批已完成的物料'; return; }
  const invalid = selectedRows.find((row) => {
    const value = Number(prQuantities.value[row.name] || 0);
    return value <= 0 || value > Number(row.pr_available_quantity || 0);
  });
  if (invalid) { error.value = invalid.material_serial + ' 本次 PR 数量必须大于 0 且不超过可提数量'; return; }
  try {
    const result = await prCreator.submit({ lines: JSON.stringify(lines) });
    message.value = result.name + ' 已生成，共 ' + result.lines.length + ' 项物料';
    error.value = '';
    selectedForPr.value = new Set();
    prQuantities.value = {};
    await loader.reload();
  } catch (err) {
    error.value = err?.messages?.[0] || err?.message || '生成 PR 失败';
  }
}

function selectStage(value) {
  status.value = status.value === value ? '' : value;
  query();
}
function refresh() { message.value = ''; error.value = ''; loader.reload(); }
function query() {
  page.value = 0; executionLine.value = null; selectedOrder.value = ''; refresh(); }
function groupDate(group) {
  const dates = group.rows.map((row) => row.expected_delivery_date).filter(Boolean).sort();
  if (!dates.length) return '交期待确认';
  return dates[0] === dates[dates.length - 1] ? `交期 ${dates[0]}` : `交期 ${dates[0]} 至 ${dates[dates.length - 1]}`;
}
function selectOrder(group) {
  selectedOrder.value = group.key;
  document.getElementById(`material-order-${group.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function badgeClass(value) {
  if (['已完成', '已付款', '已关闭'].includes(value)) return 'bg-emerald-50 text-emerald-700';
  if (['已取消', '已撤回', '已拒绝'].includes(value)) return 'bg-gray-100 text-gray-500';
  if (['采购确认中', 'PO处理中', '到货验收中', '付款中', '部分到货', '验收中'].includes(value)) return 'bg-amber-50 text-amber-700';
  if (value === '供应商制作中') return 'bg-cyan-50 text-cyan-700';
  return 'bg-orange-50 text-orange-700';
}
function flashCell(cell, kind) {
  cell.classList.remove('cell-saved', 'cell-error');
  cell.classList.add(kind === 'ok' ? 'cell-saved' : 'cell-error');
  window.setTimeout(() => cell.classList.remove('cell-saved', 'cell-error'), kind === 'ok' ? 900 : 1600);
}
function renderCell(cell, row, field) {
  cell.textContent = cellValue(row, field) || '无';
  cell.dataset.original = cell.textContent;
  cell.title = cell.textContent;
}
function beginCellEdit(event) {
  const cell = event.currentTarget;
  cell.dataset.original = cell.textContent;
}
async function saveCell(event, row, field) {
  const cell = event.currentTarget;
  const next = normalized(cell.textContent);
  const previous = normalized(cell.dataset.original || cellValue(row, field));
  if (next === previous) return;
  try {
    const result = await updater.submit({ name: row.name, expected_modified: row.modified, values: JSON.stringify({ [field]: next === '无' ? '' : next }) });
    Object.assign(row, result);
    renderCell(cell, row, field);
    flashCell(cell, 'ok');
    message.value = `${row.source_request} · ${columns.find((column) => column.field === field)?.label || field} 已保存并通知相关人员`;
    error.value = '';
  } catch (err) {
    cell.textContent = previous;
    flashCell(cell, 'error');
    error.value = err?.messages?.[0] || err?.message || '单元格保存失败';
  }
}
function cellKeydown(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    event.currentTarget.blur();
  }
}
async function pasteCells(event) {
  const startCell = event.target.closest('td[data-progress-field]');
  if (!startCell || startCell.getAttribute('contenteditable') !== 'true') return;
  const text = event.clipboardData?.getData('text/plain') || '';
  if (!text) return;
  const matrix = text.replace(/\r\n?/g, '\n').split('\n').filter((line, index, lines) => index < lines.length - 1 || line !== '').map((line) => line.split('\t'));
  const dataRows = [...tableRef.value.querySelectorAll('tbody tr[data-progress-row]')];
  const startRow = dataRows.indexOf(startCell.closest('tr'));
  const startColumn = Number(startCell.dataset.progressColumn);
  if (startRow < 0 || Number.isNaN(startColumn)) return;
  const changes = new Map();
  const touched = [];
  matrix.forEach((values, rowOffset) => {
    const tr = dataRows[startRow + rowOffset];
    if (!tr) return;
    values.forEach((raw, columnOffset) => {
      const value = normalized(raw);
      if (!value) return;
      const target = tr.querySelector(`td[data-progress-column="${startColumn + columnOffset}"]`);
      if (!target?.dataset.progressField) return;
      const rowName = tr.dataset.progressRow;
      if (!changes.has(rowName)) changes.set(rowName, { row: rows.value.find((item) => item.name === rowName), values: {}, cells: [] });
      const entry = changes.get(rowName);
      entry.values[target.dataset.progressField] = value === '无' ? '' : value;
      entry.cells.push(target);
      target.textContent = value;
      touched.push(target);
    });
  });
  if (!changes.size) return;
  event.preventDefault();
  try {
    for (const [name, entry] of changes) {
      const result = await updater.submit({ name, expected_modified: entry.row.modified, values: JSON.stringify(entry.values) });
      Object.assign(entry.row, result);
      entry.cells.forEach((cell) => {
        renderCell(cell, entry.row, cell.dataset.progressField);
        flashCell(cell, 'ok');
      });
    }
    message.value = `已粘贴并保存 ${changes.size} 条物料记录，已通知相关人员`;
    error.value = '';
  } catch (err) {
    touched.forEach((cell) => flashCell(cell, 'error'));
    error.value = err?.messages?.[0] || err?.message || '批量粘贴保存失败，已重新加载数据';
    await loader.reload();
  }
}

const selection = { start: null, end: null, dragging: false };
function dataCells() { return [...(tableRef.value?.querySelectorAll('tbody tr[data-progress-row]') || [])]; }
function position(cell) {
  const row = dataCells().indexOf(cell.closest('tr'));
  const col = Number(cell.dataset.progressColumn);
  return row >= 0 && !Number.isNaN(col) ? { row, col } : null;
}
function paintSelection() {
  tableRef.value?.querySelectorAll('.cell-selected').forEach((cell) => cell.classList.remove('cell-selected'));
  if (!selection.start || !selection.end) return;
  const minRow = Math.min(selection.start.row, selection.end.row);
  const maxRow = Math.max(selection.start.row, selection.end.row);
  const minCol = Math.min(selection.start.col, selection.end.col);
  const maxCol = Math.max(selection.start.col, selection.end.col);
  dataCells().slice(minRow, maxRow + 1).forEach((tr) => {
    for (let col = minCol; col <= maxCol; col += 1) tr.querySelector(`td[data-progress-column="${col}"]`)?.classList.add('cell-selected');
  });
}
function startSelection(event) {
  if (event.button !== 0) return;
  const cell = event.target.closest('td[data-progress-column]');
  if (!cell) return;
  selection.start = position(cell);
  selection.end = selection.start;
  selection.dragging = true;
  paintSelection();
  const move = (moveEvent) => {
    const target = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)?.closest?.('td[data-progress-column]');
    const next = target && position(target);
    if (next) { selection.end = next; paintSelection(); }
  };
  const up = () => {
    selection.dragging = false;
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', up);
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', up, { once: true });
}
async function copySelection(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'c' || !selection.start || !selection.end) return;
  const minRow = Math.min(selection.start.row, selection.end.row);
  const maxRow = Math.max(selection.start.row, selection.end.row);
  const minCol = Math.min(selection.start.col, selection.end.col);
  const maxCol = Math.max(selection.start.col, selection.end.col);
  const text = dataCells().slice(minRow, maxRow + 1).map((tr) => {
    const values = [];
    for (let col = minCol; col <= maxCol; col += 1) values.push(normalized(tr.querySelector(`td[data-progress-column="${col}"]`)?.textContent));
    return values.join('\t');
  }).join('\r\n');
  if (!text) return;
  event.preventDefault();
  await navigator.clipboard.writeText(text);
  message.value = `已复制 ${maxRow - minRow + 1} 行 × ${maxCol - minCol + 1} 列`;
}
window.addEventListener('keydown', copySelection);
onBeforeUnmount(() => window.removeEventListener('keydown', copySelection));

function toggleColumnMenu(field) {
  menuField.value = menuField.value === field ? '' : field;
  menuSearch.value = columnFilters.value[field] || '';
}
function applyColumnFilter(field) {
  columnFilters.value = { ...columnFilters.value, [field]: menuSearch.value.trim() };
  menuField.value = '';
}
function sortColumn(field, direction) {
  sortField.value = field;
  sortDirection.value = direction;
  menuField.value = '';
}
function clearColumn(field) {
  const next = { ...columnFilters.value };
  delete next[field];
  columnFilters.value = next;
  if (sortField.value === field) sortField.value = '';
  menuField.value = '';
}
async function cancelRow(row) {
  const reason = window.prompt('请输入取消原因');
  if (!reason) return;
  try {
    await canceller.submit({ name: row.name, reason });
    message.value = '记录已标记为取消，并已通知相关人员';
    await loader.reload();
  } catch (err) {
    error.value = err?.messages?.[0] || err?.message || '操作失败';
  }
}
</script>

<template>
  <div class="material-progress-shell space-y-4">
    <div class="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
      <div><div class="text-xs font-semibold tracking-wide text-slate-600">采购执行</div><h1 class="mt-1 text-xl font-semibold text-slate-900">物料进度查询</h1><p class="mt-1 text-sm text-gray-500">按物料查看 OA、PR、价格审批、PO 与履约状态。</p></div>
      <div class="flex items-center gap-2">
        <button type="button" class="inline-flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium hover:bg-gray-50" :disabled="loader.loading" @click="refresh"><FeatherIcon name="refresh-cw" class="h-4 w-4" />刷新</button>
        <button type="button" class="inline-flex items-center justify-center gap-2 rounded-md bg-teal-700 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-800 disabled:bg-gray-400" :disabled="!selectedForPr.size || prCreator.loading" @click="createPrFromBoard"><FeatherIcon name="git-merge" class="h-4 w-4" />生成 PR<span v-if="selectedForPr.size" class="rounded-full bg-white/20 px-1.5">{{ selectedForPr.size }}</span></button>
      </div>
    </div>

    <div class="flex flex-col gap-3 border-y border-gray-200 bg-gray-100/70 px-3 py-3 lg:flex-row">
      <select v-model="requester" class="rounded-md border-gray-300 px-3 py-2 text-sm" @change="query"><option value="">全部需求人</option><option v-for="item in requesters" :key="item" :value="item">{{ item }}</option></select>
      <input v-model="search" class="min-w-0 flex-1 rounded-md border-gray-300 px-3 py-2 text-sm" placeholder="输入物料编号、名称、型号、日期、项目、PR、PO、供应商或单号" @keyup.enter="query" />
      <select v-model="status" class="rounded-md border-gray-300 px-3 py-2 text-sm" @change="query"><option value="">全部状态</option><option v-for="item in statusOptions" :key="item" :value="item">{{ item }}</option></select>
      <button type="button" class="rounded-md bg-teal-700 px-5 py-2 text-sm font-medium text-white hover:bg-teal-800" @click="query">查询</button>
    </div>

    <div v-if="sourceRequest" class="flex flex-wrap items-center justify-between gap-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-sm"><span>来源 OA：{{ sourceRequest }}</span><router-link :to="{ path: '/approval/procurement', query: { request: sourceRequest } }" class="text-blue-700">查看来源 OA →</router-link><router-link to="/approval/material-progress" class="text-gray-600">查看全部 OA</router-link></div>

    <div class="stage-strip">
      <button type="button" :class="{ active: !status }" @click="status = ''; query()"><span>全部</span><strong>{{ allStageCount }}</strong></button>
      <button v-for="(item, index) in stageStatuses" :key="item" type="button" :class="{ active: status === item }" @click="selectStage(item)">
        <small>{{ String(index + 1).padStart(2, '0') }}</small><span>{{ item }}</span><strong>{{ counts[item] || 0 }}</strong>
      </button>
    </div>
    <div class="board-meta"><div class="flex flex-wrap items-center gap-2 text-sm"><span class="font-semibold text-gray-900">共 {{ total }} 项物料 · 本页 {{ rows.length }} 项</span><span class="board-count board-count-selectable">本页可提 PR {{ eligibleCount }}</span><span class="board-count board-count-locked">本页不可选 {{ lockedCount }}</span><span v-for="item in statusOptions.filter((value) => !stageStatuses.includes(value) && counts[value])" :key="item" class="rounded px-2 py-1 text-xs font-medium" :class="badgeClass(item)">{{ item }} {{ counts[item] }}</span></div><div class="board-legend"><span class="legend-item legend-selectable"><i></i>可提 PR</span><span class="legend-item legend-locked"><i></i>不可选</span><span class="legend-item legend-editable"><i></i>黄色单元格可编辑</span><button type="button" class="view-toggle" @click="showAllColumns = !showAllColumns"><FeatherIcon :name="showAllColumns ? 'chevron-left' : 'columns'" class="h-3.5 w-3.5" />{{ showAllColumns ? '收起扩展字段' : '显示全部字段' }}</button></div></div>
    <p v-if="message" class="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{{ message }}</p>
    <p v-if="error" class="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{{ error }}</p>

    <div class="grid min-h-[620px] overflow-hidden rounded-md border border-gray-200 bg-white lg:grid-cols-[210px_minmax(0,1fr)]">
      <aside class="border-b border-gray-200 bg-gray-50 lg:border-b-0 lg:border-r">
        <div class="border-b border-gray-200 px-4 py-3"><h2 class="text-sm font-semibold text-gray-900">OA订单（本页）</h2><p class="mt-0.5 text-xs text-gray-500">当前 {{ groups.length }} 张</p></div>
        <div class="max-h-[620px] overflow-y-auto">
          <button v-for="group in groups" :key="group.key" type="button" class="block w-full border-b border-gray-200 px-3 py-3 text-left hover:bg-white" :class="selectedOrder === group.key ? 'border-l-4 border-l-teal-600 bg-white' : ''" @click="selectOrder(group)">
            <div class="flex items-center justify-between gap-2"><strong class="text-sm text-gray-900">{{ group.key }}</strong><span class="text-xs text-gray-500">{{ group.rows.length }} 项</span></div>
            <div class="mt-1 text-xs text-gray-700">{{ group.requester || '-' }}</div><div class="mt-1 truncate text-xs text-gray-500" :title="group.projects">{{ group.projects || '-' }}</div><div class="mt-1 text-xs text-gray-500">{{ groupDate(group) }}</div>
            <div class="mt-2 flex flex-wrap gap-1"><span v-for="(count, value) in group.statuses" :key="value" class="rounded px-1.5 py-0.5 text-[11px] font-medium" :class="badgeClass(value)">{{ value }} {{ count }}</span></div>
          </button>
        </div>
      </aside>

      <section class="min-w-0">
        <div class="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-3"><div><h2 class="text-sm font-semibold text-gray-900">物料进度明细</h2><p class="mt-0.5 text-xs text-gray-500">业务字段可表格化维护，流程状态由关联单据自动更新。</p></div><div class="text-right text-xs text-gray-500"><strong class="block text-sm text-gray-900">{{ groups.length }} 张订单</strong>{{ visibleRows.length }} 项物料</div></div>
        <div class="max-h-[620px] overflow-auto">
          <table ref="tableRef" class="progress-grid w-full table-fixed text-sm" :class="showAllColumns ? 'progress-grid-expanded' : 'progress-grid-compact'" @paste="pasteCells" @pointerdown="startSelection">
            <colgroup><col style="width: 86px" /><col v-for="column in displayColumns" :key="column.field" :style="{ width: column.width }" /><col style="width: 74px" /></colgroup>
            <thead class="sticky top-0 z-20 bg-gray-100 text-left text-xs font-semibold text-gray-600"><tr>
              <th class="selection-header border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox" title="全选可提 PR 物料" @change="toggleAllPrRows" /><span>选择</span></th>
              <th v-for="column in displayColumns" :key="column.field" :data-progress-field="column.field" class="relative border-b border-r border-gray-200 px-2 py-2">
                <button type="button" class="flex w-full items-center justify-between gap-1 text-left" @click.stop="toggleColumnMenu(column.field)"><span>{{ column.label }}</span><FeatherIcon name="chevron-down" class="h-3 w-3" /></button>
                <div v-if="menuField === column.field" class="absolute left-1 top-9 z-40 w-52 rounded-md border border-gray-200 bg-white p-2 text-gray-700 shadow-xl" @click.stop>
                  <button type="button" class="block w-full rounded px-2 py-1.5 text-left hover:bg-gray-50" @click="sortColumn(column.field, 'asc')">升序排列</button><button type="button" class="block w-full rounded px-2 py-1.5 text-left hover:bg-gray-50" @click="sortColumn(column.field, 'desc')">降序排列</button>
                  <input v-model="menuSearch" class="mt-2 w-full rounded border-gray-300 px-2 py-1.5 text-xs" :placeholder="`筛选${column.label}`" @keyup.enter="applyColumnFilter(column.field)" />
                  <div class="mt-2 flex gap-1"><button type="button" class="flex-1 rounded bg-gray-900 px-2 py-1.5 text-xs text-white" @click="applyColumnFilter(column.field)">应用</button><button type="button" class="rounded border border-gray-300 px-2 py-1.5 text-xs" @click="clearColumn(column.field)">清除</button></div>
                </div>
              </th>
              <th class="border-b border-gray-200 px-2 py-2 text-center">操作</th>
            </tr></thead>
            <tbody>
              <template v-for="group in groups" :key="group.key">
                <tr :id="`material-order-${group.key}`" class="bg-teal-50/70"><td :colspan="displayColumns.length + 2" class="border-b border-teal-200 px-3 py-2"><strong>{{ group.key }}</strong><span class="ml-4 text-xs text-gray-600">需求人：{{ group.requester || '-' }}</span><span class="ml-4 text-xs text-gray-600">项目：{{ group.projects || '-' }}</span><span class="ml-4 text-xs text-gray-500">{{ group.rows.length }} 项</span></td></tr>
                <tr v-for="row in group.rows" :key="row.name" :data-progress-row="row.name" class="hover:bg-gray-50" :class="{ 'bg-teal-50': selectedForPr.has(row.name) }">
                  <td class="selection-cell border-b border-r border-gray-200 px-2 py-2 text-center"><input type="checkbox" :checked="selectedForPr.has(row.name)" :disabled="!Number(row.pr_eligible)" :title="Number(row.pr_eligible) ? '选择生成 PR' : '需求审批未完成或已全部提 PR'" @change="togglePrRow(row, $event.target.checked)" /><span class="selection-badge" :class="Number(row.pr_eligible) ? 'is-selectable' : 'is-locked'">{{ selectionLabel(row) }}</span></td>
                  <td v-for="(column, columnIndex) in displayColumns" :key="column.field" class="editable-cell border-b border-r border-gray-200 px-2 py-2 align-top outline-none" :class="[column.field === 'progress_override' ? badgeClass(row.progress_status) : '', row.record_status === '已取消' ? 'text-gray-400' : '', canEditField(column.field) ? 'is-editable' : 'is-readonly']" :contenteditable="row.record_status !== '已取消' && canEditField(column.field)" spellcheck="false" :data-progress-field="column.field" :data-progress-column="columnIndex" :data-original="cellValue(row, column.field) || '无'" :title="canEditField(column.field) ? '可编辑：点击输入，失焦自动保存' : (cellValue(row, column.field) || '无')" @focus="canEditField(column.field) && beginCellEdit($event)" @blur="canEditField(column.field) && saveCell($event, row, column.field)" @keydown="cellKeydown"><input v-if="column.field === 'pr_create_quantity'" v-model.number="prQuantities[row.name]" type="number" min="0.0001" :max="row.pr_available_quantity" step="0.0001" class="h-7 w-full rounded border border-gray-300 bg-white px-1.5 text-right text-xs disabled:bg-gray-100" :disabled="!selectedForPr.has(row.name)" /><template v-else>{{ cellValue(row, column.field) || '无' }}</template></td>
                  <td class="border-b border-gray-200 px-2 py-2 text-center"><button type="button" class="mb-2 block text-xs text-blue-700" @click="executionLine = row">拆分明细</button><router-link :to="{ path: '/approval/procurement', query: { request: row.source_request } }" class="mb-2 block text-xs text-blue-700">来源 OA</router-link><button v-if="row.record_status !== '已取消'" type="button" class="inline-flex h-7 w-7 items-center justify-center rounded text-red-600 hover:bg-red-50" title="标记为取消" @click="cancelRow(row)"><FeatherIcon name="trash-2" class="h-4 w-4" /></button><span v-else class="text-xs text-gray-400">已取消</span></td>
                </tr>
              </template>
              <tr v-if="!groups.length && !loader.loading"><td :colspan="displayColumns.length + 2" class="px-4 py-16 text-center text-sm text-gray-500">暂无符合条件的物料进度</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
    <div class="flex items-center justify-end gap-3 text-sm"><button type="button" :disabled="page === 0 || loader.loading" class="rounded border border-gray-300 px-3 py-1.5 disabled:opacity-40" @click="turnPage(-1)">上一页</button><span>第 {{ page + 1 }} 页 · 共 {{ total }} 项</span><button type="button" :disabled="!loader.data?.has_more || loader.loading" class="rounded border border-gray-300 px-3 py-1.5 disabled:opacity-40" @click="turnPage(1)">下一页</button></div>
    <MaterialExecutionProgress v-if="executionLine" :key="executionLine.source_request + executionLine.source_line" :request="executionLine.source_request" :source-line="executionLine.source_line" expanded />
  </div>
</template>

<style scoped>
.editable-cell[contenteditable='true'] { cursor: text; }
.editable-cell[contenteditable='true']:focus { box-shadow: inset 0 0 0 2px #0f766e; background: #fff; }
.cell-selected { box-shadow: inset 0 0 0 2px #2563eb; background-color: #eff6ff !important; }
.cell-saved { animation: saved-cell 900ms ease; }
.cell-error { animation: error-cell 1600ms ease; }
@keyframes saved-cell { 0%, 55% { background-color: #bbf7d0; } 100% { background-color: transparent; } }
@keyframes error-cell { 0%, 55% { background-color: #fecaca; } 100% { background-color: transparent; } }

.material-progress-shell { color: #27343a; }
.material-progress-shell :deep(button),
.material-progress-shell :deep(input),
.material-progress-shell :deep(select) { border-radius: 3px; }
.material-progress-shell > .flex:first-child { border-bottom: 1px solid #d4e0e4; padding-bottom: 12px; }
.material-progress-shell .progress-grid { border-collapse: separate; border-spacing: 0; background: #fbfdfe; }.progress-grid-compact { min-width: 1520px; }
.progress-grid-expanded { min-width: 2880px; }
.board-count { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.board-count-selectable { background: #ccfbf1; color: #0f766e; }
.board-count-locked { background: #e2e8f0; color: #64748b; }
.material-progress-shell .progress-grid tbody td.is-editable { border-left: 2px solid #f4d58a; }

.material-progress-shell .progress-grid thead th { background: #e8f1f4; color: #415b65; border-color: #c9d9de; font-weight: 700; }
.material-progress-shell .progress-grid thead th button { color: #415b65; }
.material-progress-shell .progress-grid tbody td { border-color: #d8e3e7; color: #33434a; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.material-progress-shell .progress-grid tbody tr:hover td { background: #f1f8fa; }
.material-progress-shell .progress-grid tbody tr.bg-teal-50\/70 td { background: #e8f2f5; color: #2d4c57; border-top: 1px solid #b7cfd6; border-bottom: 1px solid #b7cfd6; }
.material-progress-shell aside { background: #eef5f7; border-color: #c9d9de; }
.material-progress-shell aside > div:first-child { background: #e5eff2; border-color: #c9d9de; }
.material-progress-shell aside button { border-color: #d4e1e5; }
.material-progress-shell aside button:hover { background: #fafdfe; }
.material-progress-shell .editable-cell { min-height: 32px; }
.material-progress-shell .editable-cell[contenteditable='true']:hover { background: #f7fbfc; }
.material-progress-shell .cell-selected { outline: 2px solid #2b79a0; outline-offset: -2px; background: #eaf5fb !important; }
.material-progress-shell .max-h-\[620px\] { scrollbar-color: #a9c1c9 #edf4f6; scrollbar-width: thin; }
.material-progress-shell .max-h-\[620px\]::-webkit-scrollbar { width: 10px; height: 10px; }
.material-progress-shell .max-h-\[620px\]::-webkit-scrollbar-thumb { background: #a9c1c9; border-radius: 4px; }
.material-progress-shell .max-h-\[620px\]::-webkit-scrollbar-track { background: #edf4f6; }
.stage-strip { display: grid; grid-template-columns: repeat(8, minmax(105px, 1fr)); border: 1px solid #cbd7d9; border-radius: 4px; overflow-x: auto; background: #edf3f3; }
.stage-strip button { position: relative; min-height: 54px; display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; gap: 5px; padding: 7px 9px; border: 0; border-right: 1px solid #cfdbdc; background: transparent; color: #536669; text-align: left; }
.stage-strip button:last-child { border-right: 0; }
.stage-strip button:hover { background: #f7fbfb; }
.stage-strip button.active { background: #fff; color: #155d61; box-shadow: inset 0 -3px #1b7478; }
.stage-strip small { color: #91a0a2; font: 600 9px ui-monospace, monospace; }
.stage-strip span { font-size: 11px; font-weight: 700; white-space: nowrap; }
.stage-strip strong { min-width: 22px; height: 20px; display: inline-flex; align-items: center; justify-content: center; border-radius: 10px; background: #dce5e6; font-size: 10px; }
.stage-strip button.active strong { background: #d3e9e6; color: #12575a; }
@media (max-width: 900px) { .stage-strip { grid-template-columns: repeat(8, minmax(125px, 1fr)); } }
.board-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.board-legend { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; color: #64748b; font-size: 12px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.legend-item i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.legend-selectable i { background: #0f766e; }
.legend-locked i { background: #cbd5e1; }
.legend-editable i { background: #fef3c7; border: 1px solid #f59e0b; }
.view-toggle { display: inline-flex; align-items: center; gap: 5px; border: 1px solid #cbd5e1; background: #fff; color: #334155; padding: 5px 9px; font-size: 12px; }
.view-toggle:hover { background: #f8fafc; border-color: #94a3b8; }
.selection-header { width: 86px; min-width: 86px; }
.selection-header span { display: block; margin-top: 3px; font-size: 10px; color: #64748b; font-weight: 600; }
.selection-cell { width: 86px; min-width: 86px; background: #f8fafc; }
.selection-cell input { width: 15px; height: 15px; vertical-align: middle; accent-color: #0f766e; }
.selection-badge { display: block; margin: 3px auto 0; width: max-content; max-width: 72px; border-radius: 999px; padding: 1px 5px; font-size: 9px; line-height: 1.2; font-weight: 700; }
.selection-badge.is-selectable { background: #ccfbf1; color: #0f766e; }
.selection-badge.is-locked { background: #e2e8f0; color: #64748b; }
.material-progress-shell .progress-grid tbody td.is-editable { background: #fffbeb; box-shadow: inset 0 0 0 1px rgba(245,158,11,.10); }
.material-progress-shell .progress-grid tbody td.is-editable:hover { background: #fef3c7; }
.material-progress-shell .progress-grid tbody td.is-readonly { color: #475569; }
.material-progress-shell .progress-grid tbody td[data-progress-field='progress_override'] { font-weight: 700; }
@media (max-width: 900px) { .board-legend { width: 100%; } .view-toggle { margin-left: auto; } }</style>

<style scoped>
.material-progress-shell { background: #f7fafb; padding: 4px 2px 18px; }
.material-progress-shell > .grid { box-shadow: 0 10px 28px rgba(30, 64, 72, .08); }
.material-progress-shell .progress-grid thead th { height: 36px; padding-top: 7px; padding-bottom: 7px; letter-spacing: .01em; }
.material-progress-shell .progress-grid tbody td { height: 34px; padding-top: 6px; padding-bottom: 6px; }
.material-progress-shell .progress-grid tbody tr:nth-child(even):not(.bg-teal-50\/70) td { background: #f8fbfc; }
.material-progress-shell .progress-grid tbody tr.bg-teal-50\/70 td { height: 32px; padding-top: 6px; padding-bottom: 6px; font-size: 11px; letter-spacing: .01em; }
.material-progress-shell .progress-grid .selection-header, .material-progress-shell .progress-grid .selection-cell { position: sticky; left: 0; z-index: 10; background: #fbfdfe; box-shadow: 1px 0 0 #d8e3e7; }
.material-progress-shell .progress-grid thead th[data-progress-field="source_request"], .material-progress-shell .progress-grid tbody td[data-progress-field="source_request"] { position: sticky; left: 86px; z-index: 9; background: #fbfdfe; box-shadow: 1px 0 0 #d8e3e7; }
.material-progress-shell .progress-grid thead th[data-progress-field="material_serial"], .material-progress-shell .progress-grid tbody td[data-progress-field="material_serial"] { position: sticky; left: 202px; z-index: 9; background: #fbfdfe; box-shadow: 1px 0 0 #d8e3e7; }
.material-progress-shell .progress-grid thead th[data-progress-field="item_name"], .material-progress-shell .progress-grid tbody td[data-progress-field="item_name"] { position: sticky; left: 342px; z-index: 9; background: #fbfdfe; box-shadow: 1px 0 0 #d8e3e7; }
.material-progress-shell .progress-grid thead th[data-progress-field="project"], .material-progress-shell .progress-grid tbody td[data-progress-field="project"] { position: sticky; left: 482px; z-index: 9; background: #fbfdfe; box-shadow: 2px 0 0 #c9d9de; }
.material-progress-shell .progress-grid thead th[data-progress-field="source_request"], .material-progress-shell .progress-grid thead th[data-progress-field="material_serial"], .material-progress-shell .progress-grid thead th[data-progress-field="item_name"], .material-progress-shell .progress-grid thead th[data-progress-field="project"] { z-index: 12; background: #e8f1f4; }
.material-progress-shell .progress-grid tbody tr[data-progress-row]:hover td[data-progress-field="source_request"], .material-progress-shell .progress-grid tbody tr[data-progress-row]:hover td[data-progress-field="material_serial"], .material-progress-shell .progress-grid tbody tr[data-progress-row]:hover td[data-progress-field="item_name"], .material-progress-shell .progress-grid tbody tr[data-progress-row]:hover td[data-progress-field="project"] { background: #eef8fa; }
.material-progress-shell .progress-grid tbody td[data-progress-field="progress_override"] { font-weight: 600; }
.material-progress-shell aside button { transition: background .15s ease, box-shadow .15s ease; padding-top: 9px; padding-bottom: 9px; }
.material-progress-shell aside button:hover { box-shadow: inset 3px 0 0 #2b8791; }
.material-progress-shell aside button.border-l-4 { box-shadow: inset 3px 0 0 #0f766e, 0 1px 0 rgba(15,118,110,.08); }

</style>
