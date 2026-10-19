// 发票夹前端逻辑：状态分组、可操作性判断、上传后的轮询条件。
export const FOLDER_TABS = Object.freeze([
  { key: '', label: '全部' },
  { key: '识别中', label: '识别中' },
  { key: '待确认', label: '待确认' },
  { key: '可用', label: '可用' },
  { key: '已使用', label: '已使用' },
  { key: '疑似重复', label: '疑似重复' },
  { key: '识别失败', label: '识别失败' },
]);

export const FOLDER_TONES = Object.freeze({
  识别中: 'bg-blue-50 text-blue-700',
  待确认: 'bg-amber-50 text-amber-700',
  可用: 'bg-emerald-50 text-emerald-700',
  已使用: 'bg-gray-100 text-gray-600',
  疑似重复: 'bg-red-50 text-red-700',
  识别失败: 'bg-red-50 text-red-700',
  已排除: 'bg-gray-100 text-gray-500',
});

export function folderTone(status) {
  return FOLDER_TONES[String(status || '').trim()] || 'bg-gray-100 text-gray-700';
}

export function tabsWithCounts(counts = {}) {
  const total = FOLDER_TABS.slice(1).reduce((sum, tab) => sum + Number(counts[tab.key] || 0), 0);
  return FOLDER_TABS.map((tab) => ({ ...tab, count: tab.key ? Number(counts[tab.key] || 0) : total }));
}

export function canEditFields(invoice) {
  // OCR 识别不出来时也要能手工改，所以待确认和疑似重复都允许编辑。
  return ['待确认', '疑似重复'].includes(String(invoice?.folder_status || '').trim());
}

export function canConfirm(invoice) {
  return String(invoice?.folder_status || '').trim() === '待确认';
}

export function canRetry(invoice) {
  return String(invoice?.folder_status || '').trim() === '识别失败';
}

export function canUse(invoice) {
  return String(invoice?.folder_status || '').trim() === '可用';
}

export function stillRecognizing(invoices) {
  return (invoices || []).some((invoice) => String(invoice?.folder_status || '').trim() === '识别中');
}

// 确认发票时必填的字段，和后端 invoice_ocr.service.confirm_invoice 是同一条规则（页面上用 * 标出）。
// 发票类别可以留空：有的发票识别不出类别，不该卡住确认；留空时各处显示“—”。
export const REQUIRED_FIELDS = Object.freeze([
  ['project_name', '项目名称'],
  ['issue_date', '开票日期'],
  ['invoice_number', '发票号码'],
  ['total_amount', '合计'],
  ['expense_description', '费用说明'],
]);

export const isRequiredField = (field) => REQUIRED_FIELDS.some(([key]) => key === field);

export const categoryText = (value) => String(value ?? '').trim() || '—';

// 补充附件（行程单、付款凭证等，选填）：发票还没用到单据之前，本人都可以加、删（和后端 invoice_supplemental_attachments 一致）。
export function canEditAttachments(invoice) {
  return ['待确认', '疑似重复', '可用'].includes(String(invoice?.folder_status || '').trim());
}

export function missingFields(invoice) {
  const required = REQUIRED_FIELDS;
  return required
    .filter(([field]) => {
      const value = invoice?.[field];
      if (field === 'total_amount') return !Number(value);
      return !String(value ?? '').trim();
    })
    .map(([, label]) => label);
}

export function confirmBlockers(invoice) {
  const missing = missingFields(invoice);
  return missing.length ? [`确认前请补全：${missing.join('、')}`] : [];
}

export function usedByText(invoice) {
  const used = invoice?.used_by;
  if (!used) return '';
  return [used.request_type, used.name, used.business_status || used.workflow_status].filter(Boolean).join(' · ');
}

// ---------------------------------------------------------------- 发票夹页签（按设计稿第 5 版）

const WAITING = ['待确认', '识别中', '识别失败'];

// 员工：全部 / 待确认（含识别中、识别失败）/ 可用 / 已使用 / 疑似重复；财务：疑似重复待处理 / 全部发票。
export function folderTabs(invoices = [], finance = false) {
  const count = (predicate) => invoices.filter(predicate).length;
  if (finance) {
    return [
      { key: 'dup', label: '疑似重复待处理', count: count((row) => row.folder_status === '疑似重复') },
      { key: 'allinv', label: '全部发票', count: invoices.length },
    ];
  }
  return [
    { key: 'list', label: '全部', count: invoices.length },
    { key: 'todo', label: '待确认', count: count((row) => WAITING.includes(row.folder_status)) },
    { key: 'ok', label: '可用', count: count((row) => row.folder_status === '可用') },
    { key: 'used', label: '已使用', count: count((row) => row.folder_status === '已使用') },
    { key: 'dup', label: '疑似重复', count: count((row) => row.folder_status === '疑似重复') },
  ];
}

export function filterFolder(invoices = [], tab = 'list') {
  if (tab === 'todo') return invoices.filter((row) => WAITING.includes(row.folder_status));
  if (tab === 'ok') return invoices.filter((row) => row.folder_status === '可用');
  if (tab === 'used') return invoices.filter((row) => row.folder_status === '已使用');
  if (tab === 'dup') return invoices.filter((row) => row.folder_status === '疑似重复');
  return invoices.filter((row) => row.folder_status !== '已排除');
}

// 员工能改识别结果的状态：待确认（含 OCR 没认全的）。识别失败先重新识别。
// 第二个参数：当前是不是只读视图（财务的“疑似重复待处理 / 全部发票”页签）。
export function editableByOwner(invoice, readOnlyView = false) {
  return !readOnlyView && String(invoice?.folder_status || '').trim() === '待确认';
}

// ---------------------------------------------------------------- 服务端筛选（修复 2026-09-23）
// 列表按页签在服务端筛选、分页；页签上的数量用服务端按状态统计的结果，不受条数上限影响。
const LISTED = ['识别中', '待确认', '可用', '已使用', '疑似重复', '识别失败'];
export const TAB_STATUSES = Object.freeze({
  list: LISTED, allinv: LISTED, mine: LISTED, todo: WAITING, ok: ['可用'], used: ['已使用'], dup: ['疑似重复'],
  confirm: ['待确认'], failed: ['识别失败'],
});

export function tabStatuses(tab) {
  return TAB_STATUSES[tab] || TAB_STATUSES.list;
}

// 财务的单状态筛选（2026-10-13）：数据看板「发票待处理」点进来时 ?tab=confirm（全部发票里的待确认）/ failed（识别失败），
// 列表只有这一种状态，张数和看板上一样。平时不显示，只有这样进来时页签条上临时多这一个（只读，同“全部发票”）。
export const FINANCE_FILTER_TABS = Object.freeze({ confirm: '全部发票 · 待确认', failed: '全部发票 · 识别失败' });

export function financeFilterTab(tab, finance = false) {
  const key = String((Array.isArray(tab) ? tab[0] : tab) || '').trim();
  return finance && FINANCE_FILTER_TABS[key] ? key : '';
}

export function folderTabsFromCounts(counts = {}, finance = false, mineCounts = null, active = '') {
  const count = (tab, source = counts) => tabStatuses(tab).reduce((total, status) => total + Number((source || {})[status] || 0), 0);
  if (finance) {
    // 修复（2026-09-28）：财务也有自己的发票要报销，加“我的发票”页签（数量按本人发票算）。
    const tabs = [
      { key: 'dup', label: '疑似重复待处理', count: count('dup') },
      { key: 'allinv', label: '全部发票', count: count('allinv') },
      { key: 'mine', label: '我的发票', count: count('mine', mineCounts || counts) },
    ];
    const filter = financeFilterTab(active, true);
    return filter ? [...tabs, { key: filter, label: FINANCE_FILTER_TABS[filter], count: count(filter) }] : tabs;
  }
  const keys = [['list', '全部'], ['todo', '待确认'], ['ok', '可用'], ['used', '已使用'], ['dup', '疑似重复']];
  return keys.map(([key, label]) => ({ key, label, count: count(key) }));
}

// ---------------------------------------------------------------- 重试和疑似重复（修复 2026-09-28）
export const MAX_RECOGNITION_RETRIES = 3;
const STUCK_MS = 15 * 60 * 1000;

// 'retry'：识别失败，可以重新识别；'exhausted'：已重试 3 次，只能排除后重新上传；
// 'stuck'：识别超过 15 分钟没有结果（任务可能丢了），可以重新识别；''：不需要。
export function retryState(invoice, now = Date.now()) {
  const status = String(invoice?.folder_status || '').trim();
  if (status === '识别失败') return Number(invoice?.retry_count || 0) > MAX_RECOGNITION_RETRIES ? 'exhausted' : 'retry';
  if (status === '识别中') {
    const since = Date.parse(String(invoice?.modified || '').replace(' ', 'T'));
    if (Number.isFinite(since) && now - since >= STUCK_MS) return 'stuck';
  }
  return '';
}

// 疑似重复的原因：用服务端写的原因（号码相同；日期或合计不同时会特别提示）。
export function duplicateText(invoice) {
  const reason = String(invoice?.duplicate_reason || '').trim();
  if (reason && !reason.startsWith('duplicate-override:')) return reason;
  return `发票号码与已确认发票 ${invoice?.duplicate_of || ''} 相同`;
}

// ---------------------------------------------------------------- 首页状态条（2026-09-30 改版）
const STATUS_COLORS = [
  ['已使用', '#8C96A8'], ['可用', '#7FA38E'], ['识别中', '#5470C6'], ['待确认', '#78B8AD'], ['识别失败', '#4B9E91'], ['疑似重复', '#B42318'],
];

export function folderStatusBar(counts = {}) {
  const total = STATUS_COLORS.reduce((sum, [status]) => sum + Number(counts[status] || 0), 0) || 1;
  return STATUS_COLORS.map(([label, color]) => {
    const count = Number(counts[label] || 0);
    return { label, color, count, width: `${((count / total) * 100).toFixed(1)}%` };
  });
}
