<script setup>
// 物料进度看板（2026-10 改版）：按物料看它在 OA、PR、价格审批、PO、到货验收、付款走到哪一步。
// 版式：阶段条 -> 一行筛选 -> 左边 OA 订单 + 右边按 OA 分组的物料表；点"明细 ›"打开右侧抽屉。
// 原来的功能都在：列菜单筛选排序、显示全部字段、单元格直接编辑（乐观锁）、框选复制、粘贴、
// 分批生成 PR（只有 PMC）、标记取消、?request= / ?source_line= 深链接。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute } from 'vue-router';
import '../styles/expenseUi.css';
import '../styles/boardsUi.css';
import MaterialDrawer from '../components/material/MaterialDrawer.vue';
import { canCreateProcurementPr } from '../lib/access';
import {
  CHECK_WIDTH, allStageCount as sumStages, buildPrLines, cellValue as valueOf, columnLabel, displayColumns, drawerKey, errorText,
  filterSortRows, groupDateText, groupRows, isEditableField, normalizedText, otherStatuses, parseClipboardMatrix,
  selectionBounds, selectionHint, selectionLabel, statusPill, stickyLeft,
} from '../lib/materialView.js';

const stageStatuses = ['OA审批中', '采购确认中', 'PO处理中', '供应商制作中', '到货验收中', '付款中', '已关闭'];
// 这两列的文字很长，单元格里允许换行（审批轨迹、备注）。
const wideFields = new Set(['oa_approval_trail', 'remarks']);
const ACTION_WIDTH = 84;

const route = useRoute();
const search = ref('');
const requester = ref('');
const status = ref('');
const message = ref('');
const error = ref('');
const selectedOrder = ref('');
const page = ref(0);
const pageSize = 50;
const executionLine = ref(null);
const tableRef = ref(null);
const menuField = ref('');
const menuSearch = ref('');
const sortField = ref('');
const sortDirection = ref('asc');
const columnFilters = ref({});
const showAllColumns = ref(false);
const selectedForPr = ref(new Set());
const prQuantities = ref({});
const epoch = ref(0);
const canCreatePr = canCreateProcurementPr();
const sourceRequest = computed(() => String(route.query.request || ''));
let deepLinkOpened = '';
let autoSelected = '';

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
const counts = computed(() => loader.data?.stage_counts || {});
const total = computed(() => Number(loader.data?.total || 0));
const allStageCount = computed(() => sumStages(counts.value));
const otherCounts = computed(() => otherStatuses(counts.value, stageStatuses));
const eligibleCount = computed(() => rows.value.filter((row) => Number(row.pr_eligible)).length);
const lockedCount = computed(() => Math.max(0, rows.value.length - eligibleCount.value));
const columns = computed(() => displayColumns({ showAll: showAllColumns.value, canCreatePr }));
const stickyMap = computed(() => stickyLeft(columns.value, canCreatePr));
const tableWidth = computed(() => (canCreatePr ? CHECK_WIDTH : 0) + ACTION_WIDTH + columns.value.reduce((sum, column) => sum + (parseInt(column.width, 10) || 0), 0));
const colSpan = computed(() => columns.value.length + 1 + (canCreatePr ? 1 : 0));

// 左边订单列表按本页全部物料分组；右边表格还要受"点了哪张订单"限制。
const matched = computed(() => filterSortRows(rows.value, {
  filters: columnFilters.value, sortField: sortField.value, sortDirection: sortDirection.value, value: (row, field) => valueOf(row, field, prQuantities.value),
}));
const groups = computed(() => groupRows(matched.value));
const shownGroups = computed(() => (selectedOrder.value ? groups.value.filter((group) => group.key === selectedOrder.value) : groups.value));
const visibleRows = computed(() => shownGroups.value.flatMap((group) => group.rows));
const eligibleVisible = computed(() => visibleRows.value.filter((row) => Number(row.pr_eligible)));
const allPrSelected = computed(() => eligibleVisible.value.length > 0 && eligibleVisible.value.every((row) => selectedForPr.value.has(row.name)));
const drawerRow = computed(() => (executionLine.value
  ? rows.value.find((row) => row.source_request === executionLine.value.source_request && row.source_line === executionLine.value.source_line) || null
  : null));
const tableNote = computed(() => {
  if (selectedOrder.value) return `只看 ${selectedOrder.value}`;
  return canCreatePr ? '勾选可提 PR 的物料，填"本次 PR"数量后生成；可以只提一部分' : '业务字段可表格化维护，流程状态由关联单据自动更新；只有 PMC 能提 PR';
});

watch(() => [route.query.request, route.query.source_line], () => {
  page.value = 0;
  executionLine.value = null;
  selectedOrder.value = '';
  deepLinkOpened = '';
  autoSelected = '';
  loader.reload();
});
watch(() => loader.data, () => { epoch.value += 1; });
watch(rows, () => {
  const line = String(route.query.source_line || '');
  const key = `${sourceRequest.value}:${line}`;
  if (line && sourceRequest.value && deepLinkOpened !== key) {
    deepLinkOpened = key;
    executionLine.value = { source_request: sourceRequest.value, source_line: line };
  }
});
watch(groups, async (items) => {
  const request = sourceRequest.value.trim();
  if (!request || autoSelected === request) return;
  const group = items.find((item) => item.key === request);
  if (!group) return;
  autoSelected = request;
  await nextTick();
  selectOrder(group);
}, { immediate: true });

function turnPage(delta) {
  page.value += delta;
  selectedForPr.value = new Set();
  executionLine.value = null;
  selectedOrder.value = '';
  loader.reload();
}
function refresh() { message.value = ''; error.value = ''; loader.reload(); }
function query() {
  page.value = 0;
  executionLine.value = null;
  selectedOrder.value = '';
  refresh();
}
function selectStage(value) {
  status.value = status.value === value ? '' : value;
  query();
}
function selectOrder(group) {
  selectedOrder.value = group ? group.key : '';
  nextTick(() => document.getElementById(group ? `material-order-${group.key}` : 'material-table-top')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' }));
}

// ---------------------------------------------------------------- 单元格
function display(row, field) {
  const value = valueOf(row, field, prQuantities.value);
  if (value !== '') return value;
  return isEditableField(field) ? '无' : '—';
}
function cellClass(row, column) {
  return [
    isEditableField(column.field) && row.record_status !== '已取消' ? 'mp-edit' : 'mp-ro',
    column.field === 'progress_override' ? 'mp-status-cell' : '',
    stickyMap.value[column.field] !== undefined ? 'mp-sticky' : '',
    wideFields.has(column.field) ? 'mp-wide' : '',
    ['quantity', 'pr_available_quantity', 'pr_quantity', 'pr_create_quantity', 'pr_remaining_quantity', 'price_approval_quantity', 'po_quantity', 'received_quantity'].includes(column.field) ? 'mp-num' : '',
    row.record_status === '已取消' ? 'mp-cancelled' : '',
  ];
}
function stickyStyle(field) {
  return stickyMap.value[field] !== undefined ? { left: `${stickyMap.value[field]}px` } : null;
}
function flashCell(cell, kind) {
  cell.classList.remove('cell-saved', 'cell-error');
  cell.classList.add(kind === 'ok' ? 'cell-saved' : 'cell-error');
  window.setTimeout(() => cell.classList.remove('cell-saved', 'cell-error'), kind === 'ok' ? 900 : 1600);
}
function renderCell(cell, row, field) {
  cell.textContent = display(row, field);
  cell.dataset.original = cell.textContent;
  cell.title = cell.textContent;
}
function beginCellEdit(event) {
  const cell = event.currentTarget;
  cell.dataset.original = cell.textContent;
}
async function saveCell(event, row, field) {
  const cell = event.currentTarget;
  const next = normalizedText(cell.textContent);
  const previous = normalizedText(cell.dataset.original || valueOf(row, field, prQuantities.value));
  if (next === previous) return;
  try {
    const result = await updater.submit({ name: row.name, expected_modified: row.modified, values: JSON.stringify({ [field]: next === '无' ? '' : next }) });
    Object.assign(row, result);
    renderCell(cell, row, field);
    flashCell(cell, 'ok');
    message.value = `${row.source_request} · ${columnLabel(field)} 已保存并通知相关人员`;
    error.value = '';
  } catch (err) {
    cell.textContent = previous;
    flashCell(cell, 'error');
    error.value = errorText(err, '单元格保存失败');
  }
}
function cellKeydown(event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    event.currentTarget.blur();
  } else if (event.key === 'Escape' && event.currentTarget.dataset.original !== undefined) {
    event.currentTarget.textContent = event.currentTarget.dataset.original;
    event.currentTarget.blur();
  }
}

// 粘贴：从 Excel 或本页复制的制表符文本，从点中的单元格开始，按行列填进可编辑的单元格。
async function pasteCells(event) {
  const startCell = event.target.closest('td[data-progress-field]');
  if (!startCell || startCell.getAttribute('contenteditable') !== 'true') return;
  const text = event.clipboardData?.getData('text/plain') || '';
  if (!text) return;
  const matrix = parseClipboardMatrix(text);
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
      const value = normalizedText(raw);
      if (!value) return;
      const target = tr.querySelector(`td[data-progress-column="${startColumn + columnOffset}"]`);
      if (!target?.dataset.progressField || target.getAttribute('contenteditable') !== 'true') return;
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
    error.value = errorText(err, '批量粘贴保存失败，已重新加载数据');
    await loader.reload();
  }
}

// 框选 + Ctrl/Cmd+C：按单元格显示的文字复制成制表符分隔的文本，可以直接粘到 Excel。
const selection = { start: null, end: null, dragging: false };
function dataRowsOf() { return [...(tableRef.value?.querySelectorAll('tbody tr[data-progress-row]') || [])]; }
function position(cell) {
  const row = dataRowsOf().indexOf(cell.closest('tr'));
  const col = Number(cell.dataset.progressColumn);
  return row >= 0 && !Number.isNaN(col) ? { row, col } : null;
}
function paintSelection() {
  tableRef.value?.querySelectorAll('.cell-selected').forEach((cell) => cell.classList.remove('cell-selected'));
  if (!selection.start || !selection.end) return;
  const { minRow, maxRow, minCol, maxCol } = selectionBounds(selection.start, selection.end);
  dataRowsOf().slice(minRow, maxRow + 1).forEach((tr) => {
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
function copyText(cell) {
  const input = cell?.querySelector('input');
  const text = normalizedText(input ? input.value : cell?.textContent);
  return text === '—' ? '' : text;
}
async function copySelection(event) {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'c' || !selection.start || !selection.end) return;
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target?.tagName) || executionLine.value) return;
  const { minRow, maxRow, minCol, maxCol } = selectionBounds(selection.start, selection.end);
  const text = dataRowsOf().slice(minRow, maxRow + 1).map((tr) => {
    const values = [];
    for (let col = minCol; col <= maxCol; col += 1) values.push(copyText(tr.querySelector(`td[data-progress-column="${col}"]`)));
    return values.join('\t');
  }).join('\r\n');
  if (!text) return;
  event.preventDefault();
  await navigator.clipboard.writeText(text);
  message.value = `已复制 ${maxRow - minRow + 1} 行 × ${maxCol - minCol + 1} 列`;
}
function closeMenu() { menuField.value = ''; }
onMounted(() => {
  window.addEventListener('keydown', copySelection);
  document.addEventListener('click', closeMenu);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', copySelection);
  document.removeEventListener('click', closeMenu);
});

// ---------------------------------------------------------------- 列菜单
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
const columnActive = (field) => Boolean(columnFilters.value[field]) || sortField.value === field;

// ---------------------------------------------------------------- 生成 PR（只有 PMC）
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
  const eligible = eligibleVisible.value;
  const selectAll = !allPrSelected.value;
  selectedForPr.value = new Set(selectAll ? eligible.map((row) => row.name) : []);
  if (selectAll) eligible.forEach((row) => { prQuantities.value[row.name] ||= Number(row.pr_available_quantity || 0); });
}
async function createPrFromBoard() {
  const selectedRows = rows.value.filter((row) => selectedForPr.value.has(row.name));
  const { lines, invalid } = buildPrLines(selectedRows, prQuantities.value);
  if (!lines.length) { error.value = '请先选择需求审批已完成的物料'; return; }
  if (invalid) { error.value = invalid.material_serial + ' 本次 PR 数量必须大于 0 且不超过可提数量'; return; }
  try {
    const result = await prCreator.submit({ lines: JSON.stringify(lines) });
    message.value = result.name + ' 已生成，共 ' + result.lines.length + ' 项物料';
    error.value = '';
    selectedForPr.value = new Set();
    prQuantities.value = {};
    await loader.reload();
  } catch (err) {
    error.value = errorText(err, '生成 PR 失败');
  }
}

// ---------------------------------------------------------------- 取消（在抽屉里填原因）
async function cancelRow(reason) {
  const row = drawerRow.value;
  if (!row) return;
  try {
    await canceller.submit({ name: row.name, reason });
    message.value = '记录已标记为取消，并已通知相关人员';
    error.value = '';
    executionLine.value = null;
    await loader.reload();
  } catch (err) {
    error.value = errorText(err, '操作失败');
  }
}
</script>

<template>
  <div class="xp mp">
    <div class="mp-head">
      <div class="grow-col">
        <div class="crumb">审批中心 · 采购执行</div>
        <h1 class="mp-title">物料进度看板</h1>
        <div class="muted">按物料看它在 OA、PR、价格审批、PO、到货验收、付款走到哪一步了。</div>
      </div>
      <div class="head-actions">
        <button type="button" class="btn" :disabled="loader.loading" @click="refresh">刷新</button>
        <button v-if="canCreatePr" type="button" class="btn pri lg" :disabled="!selectedForPr.size || prCreator.loading" @click="createPrFromBoard">生成 PR<template v-if="selectedForPr.size"> · 已选 {{ selectedForPr.size }} 项</template></button>
      </div>
    </div>

    <div v-if="sourceRequest" class="mp-source">
      <span>来源 OA：<b class="num">{{ sourceRequest }}</b></span>
      <router-link :to="{ path: '/approval/procurement', query: { request: sourceRequest } }" class="link">查看来源 OA →</router-link>
      <router-link to="/approval/material-progress" class="link">查看全部 OA</router-link>
    </div>

    <div class="mp-stages" role="tablist" aria-label="物料阶段">
      <button type="button" :class="{ on: !status }" :aria-pressed="!status" @click="status = ''; query()"><small>&nbsp;</small><span>全部</span><strong>{{ allStageCount }}</strong></button>
      <button v-for="(item, index) in stageStatuses" :key="item" type="button" :class="{ on: status === item, zero: !counts[item] }" :aria-pressed="status === item" @click="selectStage(item)">
        <small>{{ String(index + 1).padStart(2, '0') }}</small><span>{{ item }}</span><strong>{{ counts[item] || 0 }}</strong>
      </button>
    </div>
    <div v-if="otherCounts.length" class="mp-others">
      <span>其他状态：</span>
      <button v-for="item in otherCounts" :key="item.status" type="button" :class="['mp-other', { on: status === item.status }]" @click="selectStage(item.status)">{{ item.status }} {{ item.count }}</button>
    </div>

    <div class="mp-filter">
      <select v-model="requester" aria-label="需求人" @change="query"><option value="">全部需求人</option><option v-for="item in requesters" :key="item" :value="item">{{ item }}</option></select>
      <input v-model="search" type="search" placeholder="物料编号、名称、型号、日期、项目、PR、PO、供应商或单号，回车搜索" aria-label="搜索物料" @keyup.enter="query" />
      <button type="button" class="btn dark" @click="query">查询</button>
    </div>

    <div v-if="message" class="banner ok">{{ message }}</div>
    <div v-if="error" class="banner err" role="alert">{{ error }}</div>
    <div v-if="loader.error && !loader.loading" class="banner err" role="alert">物料进度加载失败：{{ errorText(loader.error) }}</div>

    <div class="mp-layout">
      <aside class="mp-side">
        <div class="mp-side-head"><b>OA 订单（本页）</b><span class="muted">{{ groups.length }} 张</span></div>
        <div class="mp-side-list">
          <button type="button" :class="['mp-order', { on: !selectedOrder }]" @click="selectOrder(null)"><span class="mp-order-top"><b>全部订单</b><span class="muted">{{ matched.length }} 项物料</span></span></button>
          <button v-for="group in groups" :key="group.key" type="button" :class="['mp-order', { on: selectedOrder === group.key }]" @click="selectOrder(group)">
            <span class="mp-order-top"><b class="num">{{ group.key }}</b><span class="muted">{{ group.rows.length }} 项</span></span>
            <span class="mp-order-who">{{ group.requester || '-' }} · <span :title="group.projects">{{ group.projects || '-' }}</span></span>
            <span class="muted">{{ groupDateText(group) }}</span>
            <span class="mp-order-badges"><span v-for="(count, value) in group.statuses" :key="value" :class="statusPill(value)">{{ value }} {{ count }}</span></span>
          </button>
          <div v-if="!groups.length" class="empty">{{ loader.loading ? '正在加载…' : '没有订单' }}</div>
        </div>
      </aside>

      <section class="mp-main">
        <div id="material-table-top" class="mp-main-head">
          <div class="mp-main-title"><b>物料进度明细</b><span class="muted">{{ tableNote }}</span></div>
          <div class="mp-main-tools">
            <template v-if="canCreatePr"><span class="pill p-jade">本页可提 PR {{ eligibleCount }}</span><span class="pill p-gray">本页不可选 {{ lockedCount }}</span></template>
            <span class="mp-legend"><i></i>黄色单元格可编辑</span>
            <button type="button" class="link" @click="showAllColumns = !showAllColumns">{{ showAllColumns ? '收起扩展字段' : '显示全部字段（28 列）' }}</button>
          </div>
        </div>
        <div class="mp-scroll">
          <table ref="tableRef" class="mp-grid" :style="{ minWidth: tableWidth + 'px' }" @paste="pasteCells" @pointerdown="startSelection">
            <colgroup>
              <col v-if="canCreatePr" :style="{ width: CHECK_WIDTH + 'px' }" />
              <col v-for="column in columns" :key="column.field" :style="{ width: column.width }" />
              <col :style="{ width: ACTION_WIDTH + 'px' }" />
            </colgroup>
            <thead>
              <tr>
                <th v-if="canCreatePr" class="mp-check mp-sticky" style="left: 0"><input type="checkbox" :checked="allPrSelected" title="全选可提 PR 物料" aria-label="全选可提 PR 物料" @change="toggleAllPrRows" /></th>
                <th v-for="column in columns" :key="column.field" :data-progress-field="column.field" :class="{ 'mp-sticky': stickyMap[column.field] !== undefined, 'mp-th-on': columnActive(column.field), 'mp-th-open': menuField === column.field }" :style="stickyStyle(column.field)">
                  <button type="button" class="mp-th-btn" @click.stop="toggleColumnMenu(column.field)"><span>{{ column.label }}</span><i aria-hidden="true">▾</i></button>
                  <div v-if="menuField === column.field" class="mp-menu" @click.stop>
                    <button type="button" @click="sortColumn(column.field, 'asc')">升序排列</button>
                    <button type="button" @click="sortColumn(column.field, 'desc')">降序排列</button>
                    <input v-model="menuSearch" :placeholder="`筛选${column.label}`" :aria-label="`筛选${column.label}`" @keyup.enter="applyColumnFilter(column.field)" />
                    <div class="mp-menu-actions"><button type="button" class="btn sm dark" @click="applyColumnFilter(column.field)">应用</button><button type="button" class="btn sm" @click="clearColumn(column.field)">清除</button></div>
                  </div>
                </th>
                <th class="mp-act-th">明细</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="group in shownGroups" :key="group.key">
                <tr :id="`material-order-${group.key}`" class="mp-group">
                  <td :colspan="colSpan">
                    <span class="mp-group-in">
                      <router-link :to="{ path: '/approval/procurement', query: { request: group.key } }" class="link strong num">{{ group.key }}</router-link>
                      <span class="muted">{{ group.rows.length }} 项</span>
                      <span class="muted">需求人 {{ group.requester || '-' }}</span>
                      <span v-if="group.projects" class="muted">项目 {{ group.projects }}</span>
                      <router-link :to="{ path: '/approval/procurement', query: { request: group.key } }" class="link mp-group-link">来源 OA →</router-link>
                    </span>
                  </td>
                </tr>
                <tr v-for="row in group.rows" :key="row.name + ':' + epoch" :data-progress-row="row.name" :class="{ 'mp-picked': selectedForPr.has(row.name) }">
                  <td v-if="canCreatePr" class="mp-check mp-sticky" style="left: 0"><input type="checkbox" :checked="selectedForPr.has(row.name)" :disabled="!Number(row.pr_eligible)" :title="Number(row.pr_eligible) ? selectionHint(row) : selectionLabel(row) + '：' + selectionHint(row)" :aria-label="'选择 ' + row.material_serial" @change="togglePrRow(row, $event.target.checked)" /></td>
                  <td
                    v-for="(column, columnIndex) in columns"
                    :key="column.field"
                    :class="cellClass(row, column)"
                    :style="stickyStyle(column.field)"
                    :contenteditable="row.record_status !== '已取消' && isEditableField(column.field)"
                    spellcheck="false"
                    :data-progress-field="column.field"
                    :data-progress-column="columnIndex"
                    :data-original="display(row, column.field)"
                    :title="isEditableField(column.field) ? '可编辑：点击输入，失焦自动保存' : (display(row, column.field))"
                    @focus="isEditableField(column.field) && beginCellEdit($event)"
                    @blur="isEditableField(column.field) && saveCell($event, row, column.field)"
                    @keydown="cellKeydown"
                  ><template v-if="column.field === 'pr_create_quantity'"><input v-if="Number(row.pr_eligible)" v-model.number="prQuantities[row.name]" type="number" min="0.0001" :max="row.pr_available_quantity" step="0.0001" class="mp-qty" :disabled="!selectedForPr.has(row.name)" aria-label="本次 PR 数量" /><template v-else>—</template></template><span v-else-if="column.field === 'progress_override' && row.progress_status" :class="statusPill(row.progress_status)">{{ row.progress_status }}</span><template v-else>{{ display(row, column.field) }}</template></td>
                  <td class="mp-act">
                    <button type="button" class="link" @click="executionLine = { source_request: row.source_request, source_line: row.source_line }">明细 ›</button>
                    <span v-if="row.record_status === '已取消'" class="muted">已取消</span>
                  </td>
                </tr>
              </template>
              <tr v-if="!shownGroups.length"><td :colspan="colSpan" class="empty">{{ loader.loading ? '正在加载…' : '暂无符合条件的物料进度' }}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="mp-pager">
          <span class="muted">第 {{ page + 1 }} 页 · 共 {{ total }} 项（每页 {{ pageSize }} 项）· 本页 {{ rows.length }} 项</span>
          <div class="head-actions">
            <button type="button" class="btn sm" :disabled="page === 0 || loader.loading" @click="turnPage(-1)">上一页</button>
            <button type="button" class="btn sm" :disabled="!loader.data?.has_more || loader.loading" @click="turnPage(1)">下一页</button>
          </div>
        </div>
      </section>
    </div>

    <MaterialDrawer :key="drawerKey(executionLine)" :line="executionLine" :row="drawerRow" :busy="canceller.loading" @close="executionLine = null" @cancel="cancelRow" />
  </div>
</template>
