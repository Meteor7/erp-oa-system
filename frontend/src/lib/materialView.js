// 物料进度看板的前端口径（2026-10 改版）：列定义、阶段条、分组、本地筛选排序、生成 PR 的数量校验、剪贴板解析。
// 页面只负责 DOM 和接口，纯逻辑放这里，方便测试。

export const MATERIAL_COLUMNS = Object.freeze([
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
]);

// 默认只显示这些（设计稿的版式）：OA 单号在分组标题里，不再占一列。
export const COMPACT_FIELDS = Object.freeze([
  'material_serial', 'item_name', 'specification', 'project', 'progress_override', 'status_detail',
  'quantity', 'unit', 'pr_available_quantity', 'pr_create_quantity', 'pr_quantity',
  'expected_delivery_date', 'pr_numbers', 'po_numbers', 'supplier',
]);

export const EDITABLE_FIELDS = Object.freeze(new Set([
  'material_code', 'item_name', 'specification', 'product_desc', 'project', 'unit', 'quantity',
  'expected_delivery_date', 'current_handler', 'actual_delivery_date', 'remarks',
]));

// 横向滚动时钉在最左边的列（只钉最前面连续的几列）。
export const STICKY_FIELDS = Object.freeze(['source_request', 'material_serial', 'item_name']);

export const CHECK_WIDTH = 40;

export function isEditableField(field) {
  return EDITABLE_FIELDS.has(field);
}

export function columnLabel(field) {
  return MATERIAL_COLUMNS.find((column) => column.field === field)?.label || field;
}

// 只有 PMC（能提 PR 的人）才有"本次 PR"这一列；其他人看不到。
export function displayColumns({ showAll = false, canCreatePr = false } = {}) {
  const list = showAll ? [...MATERIAL_COLUMNS] : COMPACT_FIELDS.map((field) => MATERIAL_COLUMNS.find((column) => column.field === field));
  return list.filter((column) => column && (canCreatePr || column.field !== 'pr_create_quantity'));
}

export function stickyLeft(columns = [], hasCheck = false) {
  const left = {};
  let offset = hasCheck ? CHECK_WIDTH : 0;
  for (const column of columns) {
    if (!STICKY_FIELDS.includes(column.field)) break;
    left[column.field] = offset;
    offset += parseInt(column.width, 10) || 0;
  }
  return left;
}

export function cellValue(row = {}, field, prQuantities = {}) {
  if (field === 'progress_override') return row.progress_status || '';
  if (field === 'pr_create_quantity') return String(prQuantities[row.name] ?? row.pr_available_quantity ?? '');
  return String(row[field] ?? '');
}

export function normalizedText(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

// 状态小标签的颜色：沿用付款/报销页的 pill 配色。
export function statusPill(status) {
  const value = String(status || '').trim();
  let tone = 'p-gray';
  if (value === 'OA审批中' || value === '付款中') tone = 'p-cobalt';
  else if (['采购确认中', 'PO处理中', '到货验收中', '部分到货', '验收中'].includes(value)) tone = 'p-sun';
  else if (value === '供应商制作中') tone = 'p-brand';
  else if (['已关闭', '已完成', '已付款'].includes(value)) tone = 'p-jade';
  else if (['退货中', '换货中', '延期'].includes(value)) tone = 'p-red';
  return `pill ${tone}`;
}

export function selectionLabel(row = {}) {
  if (Number(row.pr_eligible)) return '可提 PR';
  if (row.progress_status === 'OA审批中') return '待审批';
  if (row.progress_status === '已关闭') return '已关闭';
  return '已提完';
}

export function selectionHint(row = {}) {
  return Number(row.pr_eligible) ? '勾选后生成 PR' : '需求审批未完成或已全部提 PR';
}

// 阶段条下面的第二行：不在 7 个阶段里、而且有数据的状态（已取消、已拒绝、已撤回、退货中……）。
export function otherStatuses(counts = {}, stages = [], order = ['已取消', '已拒绝', '已撤回', '退货中', '换货中', '延期']) {
  const keys = Object.keys(counts || {}).filter((key) => !stages.includes(key) && Number(counts[key]) > 0);
  const rank = (key) => (order.includes(key) ? order.indexOf(key) : order.length);
  return keys.sort((a, b) => rank(a) - rank(b)).map((key) => ({ status: key, count: Number(counts[key]) }));
}

export function allStageCount(counts = {}) {
  return Object.values(counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
}

// 本页的行按 OA 分组，保持服务端给的顺序。
export function groupRows(rows = []) {
  const map = new Map();
  rows.forEach((row) => {
    const key = row.source_request;
    if (!map.has(key)) map.set(key, { key, rows: [], requester: row.requester, projects: new Set(), statuses: {} });
    const group = map.get(key);
    group.rows.push(row);
    if (row.project) group.projects.add(row.project);
    group.statuses[row.progress_status] = (group.statuses[row.progress_status] || 0) + 1;
  });
  return [...map.values()].map((group) => ({ ...group, projects: [...group.projects].join('、') }));
}

export function groupDateText(group = { rows: [] }) {
  const dates = group.rows.map((row) => row.expected_delivery_date).filter(Boolean).sort();
  if (!dates.length) return '交期待确认';
  return dates[0] === dates[dates.length - 1] ? `交期 ${dates[0]}` : `交期 ${dates[0]} 至 ${dates[dates.length - 1]}`;
}

// 列菜单里的筛选（包含）和排序（中文、数字自然排序）。
export function filterSortRows(rows = [], { filters = {}, sortField = '', sortDirection = 'asc', value = cellValue } = {}) {
  let result = [...rows];
  Object.entries(filters || {}).forEach(([field, text]) => {
    if (!text) return;
    const query = String(text).toLowerCase();
    result = result.filter((row) => value(row, field).toLowerCase().includes(query));
  });
  if (sortField) {
    const direction = sortDirection === 'desc' ? -1 : 1;
    result.sort((a, b) => value(a, sortField).localeCompare(value(b, sortField), 'zh-CN', { numeric: true }) * direction);
  }
  return result;
}

// 生成 PR：每行"本次 PR"数量必须大于 0 且不超过可提数量（可以只提一部分）。
export function buildPrLines(selectedRows = [], quantities = {}) {
  const lines = selectedRows.map((row) => ({
    source_request: row.source_request,
    source_line: row.source_line,
    quantity: Number(quantities[row.name] || 0),
  }));
  const invalid = selectedRows.find((row) => {
    const value = Number(quantities[row.name] || 0);
    return value <= 0 || value > Number(row.pr_available_quantity || 0);
  }) || null;
  return { lines, invalid };
}

// 粘贴：Excel / 本页复制出来的是制表符分隔文本，末尾多出的空行去掉。
export function parseClipboardMatrix(text = '') {
  return String(text).replace(/\r\n?/g, '\n').split('\n')
    .filter((line, index, lines) => index < lines.length - 1 || line !== '')
    .map((line) => line.split('\t'));
}

export function selectionBounds(start, end) {
  return {
    minRow: Math.min(start.row, end.row), maxRow: Math.max(start.row, end.row),
    minCol: Math.min(start.col, end.col), maxCol: Math.max(start.col, end.col),
  };
}

// 取消原因：必填，最多 500 字。
export function cancelReasonProblem(reason) {
  const text = String(reason ?? '').trim();
  if (!text) return '请填写取消原因';
  if (text.length > 500) return '取消原因不能超过 500 字';
  return '';
}

export function drawerKey(line) {
  return line ? `${line.source_request}:${line.source_line || ''}` : '';
}

export function errorText(error, fallback = '操作失败') {
  return error?.messages?.[0] || error?.message || fallback;
}
