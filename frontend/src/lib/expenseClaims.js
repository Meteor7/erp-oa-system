// 报销单 / 付款单前端逻辑：类型定义、表单校验、提交数据组装、状态展示。
// 服务端仍是权威校验，这里只做即时提示，避免用户白跑一趟提交。
const API = '/api/method/rayher_hr_payroll.api.';

export const CLAIM_KINDS = Object.freeze({
  claim: Object.freeze({
    kind: 'claim',
    requestType: '报销单',
    label: '报销',
    path: '/approval/claim',
    flag: 'reimbursement_request',
    hint: '报销付给本人，明细由发票夹里的发票生成。',
  }),
  payment: Object.freeze({
    kind: 'payment',
    requestType: '付款单',
    label: '付款',
    path: '/approval/payment',
    flag: 'payment_request',
    hint: '付款付给外部单位，可以先付款、后补发票。',
  }),
});

export const CLAIM_STATUS_TONES = Object.freeze({
  草稿: 'bg-gray-100 text-gray-700',
  待审批: 'bg-amber-50 text-amber-700',
  待办理: 'bg-amber-50 text-amber-700',
  已完成: 'bg-emerald-50 text-emerald-700',
  已付款: 'bg-emerald-50 text-emerald-700',
  已拒绝: 'bg-red-50 text-red-700',
  已撤回: 'bg-gray-100 text-gray-600',
  待付款: 'bg-amber-50 text-amber-700',
  部分付款: 'bg-amber-50 text-amber-700',
  '已付款·待补票': 'bg-orange-50 text-orange-700',
  待核验: 'bg-blue-50 text-blue-700',
  已完结: 'bg-emerald-50 text-emerald-700',
  已通过: 'bg-emerald-50 text-emerald-700',
});

export function statusTone(status) {
  return CLAIM_STATUS_TONES[String(status || '').trim()] || 'bg-gray-100 text-gray-700';
}

export function claimKind(requestTypeOrKind) {
  const value = String(requestTypeOrKind || '').trim();
  return Object.values(CLAIM_KINDS).find((item) => item.kind === value || item.requestType === value) || null;
}

export function money(value) {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function cents(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.round(number * 100);
}

export function sumAmount(rows, field = 'total_amount') {
  return (rows || []).reduce((total, row) => total + cents(row?.[field]), 0) / 100;
}

export function csrfHeaders(extra = {}) {
  const token = globalThis.window?.csrf_token;
  return token ? { ...extra, 'X-Frappe-CSRF-Token': token } : extra;
}

// One place for every call these pages make, so error handling stays identical.
export async function callApi(dottedPath, args = {}, { signal, method = 'POST' } = {}) {
  const init = method === 'GET'
    ? { method: 'GET', credentials: 'same-origin', headers: csrfHeaders(), signal }
    : { method: 'POST', credentials: 'same-origin', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(args), signal };
  const url = method === 'GET'
    ? `${API}${dottedPath}?${new URLSearchParams(Object.entries(args).filter(([, value]) => value !== undefined && value !== '')).toString()}`
    : `${API}${dottedPath}`;
  const response = await fetch(url, init);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) {
    const messages = (() => {
      try {
        return JSON.parse(payload?._server_messages || '[]').map((item) => JSON.parse(item).message);
      } catch {
        return [];
      }
    })();
    throw new Error(messages[0] || payload?.message || payload?.exception || '操作失败，请稍后重试');
  }
  return payload.message;
}

export function applicationLabel(application) {
  if (!application) return '';
  const parts = [application.name, application.subject].filter(Boolean);
  if (application.request_type === '购买申请' && application.available_amount !== undefined) {
    parts.push(`剩余 ${money(application.available_amount)} 元`);
  }
  if (application.request_type === '出差申请') {
    parts.push([application.travel_destination, application.travel_start_date].filter(Boolean).join(' '));
  }
  return parts.filter(Boolean).join(' · ');
}

// 购买申请有金额上限，出差申请没有。
export function overBudget(application, amount) {
  if (!application || application.request_type !== '购买申请') return false;
  if (application.available_amount === undefined || application.available_amount === null) return false;
  return cents(amount) > cents(application.available_amount);
}

export function invoiceLines(invoices, projects = {}) {
  return (invoices || []).map((invoice) => ({
    invoice: invoice.name,
    claim_project: projects[invoice.name] || '',
    project_name: invoice.project_name || '',
    issue_date: invoice.issue_date || '',
    invoice_number: invoice.invoice_number || '',
    total_amount: invoice.total_amount,
    expense_description: invoice.expense_description || '',
  }));
}

export function claimDraftPayload(kind, form, { invoices = [], projects = {}, lines = [] } = {}) {
  const payload = {
    source_request: form.source_request || '',
    subject: form.subject || '',
    reason: form.reason || '',
    urgency: form.urgency || '一般',
    doc_type: form.doc_type || '非固定资产',
    asset_category: form.asset_category || '其他',
    payment_method: form.payment_method || '银行转账',
  };
  if (kind === 'claim') {
    payload.invoices = invoices.map((invoice) => ({ invoice: invoice.name, claim_project: projects[invoice.name] || '' }));
    return payload;
  }
  payload.payee_name = form.payee_name || '';
  payload.bank_name = form.bank_name || '';
  payload.branch = form.branch || '';
  payload.account_no = form.account_no || '';
  payload.expected_invoice_date = form.expected_invoice_date || '';
  payload.no_invoice_reason = form.no_invoice_reason || '';
  payload.invoice_difference_note = form.invoice_difference_note || '';
  payload.lines = (lines || []).map((line) => ({
    line_key: line.line_key || '',
    project_name: line.project_name || '',
    claim_project: line.claim_project || '',
    issue_date: line.issue_date || '',
    total_amount: line.total_amount || 0,
    expense_description: line.expense_description || '',
  }));
  payload.invoices = invoices.map((invoice) => invoice.name);
  return payload;
}

export function submitBlockers(kind, form, { invoices = [], lines = [], application = null } = {}) {
  const messages = [];
  if (!form.source_request) messages.push('请选择关联申请');
  if (!String(form.subject || '').trim()) messages.push('请填写主题');
  if (kind === 'claim') {
    if (!invoices.length) messages.push('请从发票夹选择至少一张发票');
    if (invoices.some((invoice) => !Number(invoice.total_amount))) messages.push('所选发票缺少合计金额，请先在发票夹补全');
    if (overBudget(application, sumAmount(invoices))) messages.push('发票合计超过关联购买申请的剩余额度');
    return messages;
  }
  if (!lines.length) messages.push('请填写付款明细');
  if (lines.some((line) => !String(line.project_name || '').trim())) messages.push('每行明细都要填写付款内容');
  if (lines.some((line) => !String(line.expense_description || '').trim())) messages.push('每行明细都要填写费用说明');
  if (lines.some((line) => cents(line.total_amount) <= 0)) messages.push('每行明细的金额必须大于 0');
  if (form.payment_method === '银行转账' && !(String(form.payee_name || '').trim() && String(form.bank_name || '').trim() && String(form.account_no || '').trim())) {
    messages.push('银行转账需要填写收款单位、开户行和银行账号');
  }
  if (invoices.length) {
    const gap = Math.abs(cents(sumAmount(lines)) - cents(sumAmount(invoices)));
    if (gap > 2 && !String(form.invoice_difference_note || '').trim()) messages.push('发票合计与付款金额相差超过 0.02 元，请填写差异说明');
  } else if (!String(form.no_invoice_reason || '').trim() || !form.expected_invoice_date) {
    messages.push('暂未取得发票时要填写原因和预计取票日期');
  }
  if (overBudget(application, sumAmount(lines))) messages.push('付款金额超过关联购买申请的剩余额度');
  return messages;
}

// 修复（2026-09-23 验收发现）：有的一级科目没有二级科目（如办公费、维修费），服务端允许只填一级；
// 原来前端一律要求二级科目，演示员工110选这些科目时永远点不了同意。传入科目表时按科目表判断。
export function hasLevelTwo(levelOne, tree = null) {
  if (!Array.isArray(tree)) return true;
  const item = tree.find((entry) => entry.level_1 === String(levelOne || '').trim());
  return !item || (item.level_2 || []).length > 0;
}

export function accountBlockers(lines, tree = null) {
  return (lines || []).some((line) => {
    const levelOne = String(line.expense_account_level_1 || '').trim();
    if (!levelOne) return true;
    return hasLevelTwo(levelOne, tree) && !String(line.expense_account_level_2 || '').trim();
  })
    ? ['演示员工110需要为每行明细选择科目（有二级科目的要选到二级）']
    : [];
}

// 演示员工110填科目用的草稿：每行一份，取单据上已保存的科目。无论从列表点开还是从通知链接
// 直接打开单据，都要用它初始化，否则科目下拉框不会出现。
export function accountDraftFor(lines) {
  return Object.fromEntries((lines || []).filter((line) => line?.line_key).map((line) => [line.line_key, {
    expense_account_level_1: line.expense_account_level_1 || '',
    expense_account_level_2: line.expense_account_level_2 || '',
  }]));
}

// 每张可选发票的"所属项目"默认是空字符串，下拉框才会显示"非项目"而不是空白。
export function withDefaultProjects(invoices, projects = {}) {
  const result = { ...projects };
  (invoices || []).forEach((invoice) => {
    if (invoice?.name && result[invoice.name] === undefined) result[invoice.name] = '';
  });
  return result;
}

// ---------------------------------------------------------------- 页面结构（按已确认的设计稿第 5 版）

// 财务（演示员工110、会计）看"待我处理 / 全部"，其他人看"我的 / 新建"；审批人从待办或通知直接打开单据。
export function isFinanceUser(roles = globalThis.window?.roles || []) {
  return (roles || []).some((role) => ['System Manager', 'Accounts User'].includes(role));
}

// 财务除了"待我处理 / 全部"，自己也要报销、付款，所以同样有"我的 / 新建"（修复 2026-09-23）。
export function claimTabs(kind, finance = false, counts = {}) {
  const label = CLAIM_KINDS[kind]?.label || '';
  const own = [{ key: 'list', label: `我的${label}`, count: counts.list }, { key: 'new', label: `新建${label}` }];
  return finance
    ? [{ key: 'todo', label: '待我处理', count: counts.todo }, { key: 'all', label: `全部${label}`, count: counts.all }, ...own]
    : own;
}

export const PILL_TONES = Object.freeze({
  草稿: 'p-gray', 已撤回: 'p-gray', 已使用: 'p-gray', 已排除: 'p-gray', 未出发: 'p-gray',
  待审批: 'p-cobalt', 审批中: 'p-cobalt', 待核验: 'p-cobalt', 识别中: 'p-cobalt', 出差中: 'p-cobalt',
  待付款: 'p-sun', 待办理: 'p-sun', 部分付款: 'p-sun', 待确认: 'p-sun',
  '已付款·待补票': 'p-brand',
  已完结: 'p-jade', 已付款: 'p-jade', 已通过: 'p-jade', 已完成: 'p-jade', 可用: 'p-jade', 已返回: 'p-jade',
  已拒绝: 'p-red', 疑似重复: 'p-red', 识别失败: 'p-red', 逾期: 'p-red',
});

export function pillClass(status) {
  return `pill ${PILL_TONES[String(status || '').trim()] || 'p-gray'}`;
}

// 单据对外显示的状态：审批中的统一叫"审批中"，其余用业务状态。
export function displayStatus(doc = {}) {
  if (doc.workflow_status === '草稿') return '草稿';
  if (doc.workflow_status === '待审批') return '审批中';
  if (doc.workflow_status === '已拒绝') return '已拒绝';
  return doc.business_status || doc.workflow_status || '';
}

// 审批进度小圆点：已过 d、当前 c、驳回 x。
export function stepChips(doc = {}) {
  const current = Number(doc.current_step_index || 0);
  const active = ['待审批', '待办理'].includes(doc.workflow_status);
  return (doc.steps || []).map((step) => {
    const index = Number(step.step_index || 0);
    let state = '';
    if (['已通过', '已办理'].includes(step.status)) state = 'd';
    else if (step.status === '已拒绝') state = 'x';
    else if (active && index === current) state = 'c';
    return { label: String(step.label || ''), state, key: `${index}-${step.label}` };
  });
}

export function sourceTypeLabel(doc = {}) {
  if (doc.payment_source_kind === '关联出差申请') return '出差申请';
  if (doc.payment_source_kind === '关联购买申请') return '购买申请';
  return '';
}

// 关联申请的额度条：购买申请看已付 + 在途占用；出差申请不限金额。
export function quotaOf(application) {
  if (!application) return null;
  if (application.request_type !== '购买申请') return { capped: false, text: '出差申请不限金额' };
  const approved = Number(application.approved_amount || 0);
  const used = Number(application.paid_amount || 0) + Number(application.reserved_amount || 0);
  const pct = approved > 0 ? Math.min(100, Math.round((used / approved) * 100)) : 0;
  return { capped: true, pct, remaining: Number(application.available_amount || 0), text: `剩余 ${money(application.available_amount)} 元` };
}

export function maskAccount(value) {
  const text = String(value || '').replace(/\s+/g, '');
  if (text.length <= 8) return text;
  return `${text.slice(0, 4)} **** ${text.slice(-4)}`;
}
