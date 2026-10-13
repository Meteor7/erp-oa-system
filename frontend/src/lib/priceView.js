// 价格审批 / PO 工作台的纯函数：页面选择、PR 占用、比价矩阵、供应商报价草稿校验、PO 合同阶段与关闭条件。
// 页面只做展示和调用接口，业务判断都放在这里，方便单测。

export const API = 'rayher_hr_payroll.api.procurement_chain.';
export const DEFAULT_CONTRACT_ENTITY = '示例企业032有限公司';
export const PAYMENT_STAGES = ['预付款', '到货款', '尾款', '到货后全额付款'];
export const INVOICE_REQUIREMENTS = ['付款前提供', '付款后提供', '无需发票'];
export const TRIGGER_SUGGESTIONS = ['合同生效', '全部到货', '全部到货并验收通过', '验收通过'];
export const MIN_SUPPLIER_SLOTS = 3;
export const PO_EDITABLE = ['草稿', '待采购确认'];
export const PAYMENT_PAGE = '/approval/procurement-payment';

// ------------------------------------------------------------------ formatting
export function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function cents(value) {
  return Math.round(toNumber(value) * 100);
}

export function moneyPlain(value) {
  return toNumber(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// 金额一律按人民币显示，保留两位小数。
export function money(value) {
  return `¥ ${moneyPlain(value)}`;
}

// PMC、生产主管看不到金额（服务端已经去掉，单据上带 amounts_hidden）：显示“—”，不显示成 ¥ 0.00。
export function amountText(value, hidden = false) {
  return hidden ? '—' : money(value);
}

// PO 的采购金额 = 物料行金额合计（2026-10-13 决定，看板、费用页同一口径）；表头总额对不上时页面另外标出来。
export function poLineTotal(po) {
  return cents((po?.lines || []).reduce((sum, line) => sum + toNumber(line?.amount), 0)) / 100;
}

export function poHeaderDiffers(po) {
  return Boolean(po?.lines?.length) && cents(po?.total_amount) !== cents(poLineTotal(po));
}

export function quantity(value) {
  return toNumber(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 });
}

export function shortDate(value) {
  const text = String(value || '').slice(0, 10);
  return text || '—';
}

export function dateTime(value) {
  const text = String(value || '').replace('T', ' ');
  return text ? text.slice(0, 16) : '';
}

export function maskAccount(value) {
  const text = String(value || '').replace(/\s+/g, '');
  if (!text) return '';
  if (text.length <= 4) return text;
  return `**** **** ${text.slice(-4)}`;
}

export function splitList(value) {
  return String(value || '').split(/[,，、;；\s]+/).map((item) => item.trim()).filter(Boolean);
}

// ------------------------------------------------------------------ pills
const TONES = { sun: 'p-sun', cobalt: 'p-cobalt', jade: 'p-jade', brand: 'p-brand', red: 'p-red', gray: 'p-gray' };

export function approvalTone(status) {
  if (['已通过', '已转PO'].includes(status)) return 'jade';
  if (['已拒绝', '已取消'].includes(status)) return 'red';
  if (status === '待审批') return 'cobalt';
  if (status === '草稿') return 'sun';
  return 'gray';
}

export function poTone(status) {
  if (status === '已关闭') return 'jade';
  if (status === '已取消') return 'red';
  if (['草稿', '待采购确认', '待合同复核'].includes(status)) return 'sun';
  if (['待电子用印', '到货验收中', '付款中'].includes(status)) return 'cobalt';
  if (['已生效', '供应商制作中'].includes(status)) return 'brand';
  return 'gray';
}

export function pillClass(tone) {
  return `pill ${TONES[tone] || TONES.gray}`;
}

export function inspectionTone(status) {
  const value = String(status || '未验收');
  if (value === '已通过') return 'jade';
  if (['退货中', '换货中', '不合格'].includes(value)) return 'red';
  if (value === '待验收') return 'sun';
  return 'gray';
}

// ------------------------------------------------------------------ page / route
// 明确的页面：tab=po / po= -> PO；view=source / pr= -> PR 待比价物料；view=approvals / approval= -> 价格审批单。
// 没有明确指定时返回空串，由数据决定默认页（见 defaultTab）。
export function resolveTab(query = {}, { canPrice = true, canPo = true } = {}) {
  let tab = '';
  if (query.tab === 'po' || query.po) tab = 'po';
  else if (query.tab === 'source' || query.view === 'source' || query.pr) tab = 'source';
  else if (query.tab === 'approvals' || query.view === 'approvals' || query.approval) tab = 'approvals';
  if (tab === 'po' && !canPo) tab = canPrice ? 'approvals' : '';
  if ((tab === 'source' || tab === 'approvals') && !canPrice) tab = canPo ? 'po' : '';
  return tab;
}

// 沿用旧页面：有待比价物料且没有可处理的价格审批单时先看 PR 物料，否则看价格审批单。
export function defaultTab({ canPrice = true, canPo = true, hasPendingPr = false, hasActionable = false } = {}) {
  if (!canPrice) return canPo ? 'po' : '';
  return hasPendingPr && !hasActionable ? 'source' : 'approvals';
}

export function tabQuery(tab, query = {}) {
  const next = {};
  if (query.request) next.request = query.request;
  if (tab === 'po') next.tab = 'po';
  else next.view = tab === 'source' ? 'source' : 'approvals';
  return next;
}

export function tabsFor({ canPrice, canPo, counts = {} }) {
  return [
    ...(canPrice ? [{ key: 'source', label: 'PR 待比价物料', count: counts.source || 0 }] : []),
    ...(canPrice ? [{ key: 'approvals', label: '价格审批单', count: counts.approvals || 0 }] : []),
    ...(canPo ? [{ key: 'po', label: 'PO 与合同', count: counts.po || 0 }] : []),
  ];
}

// ------------------------------------------------------------------ context (?request=OA)
export function contextPrs(prs = [], request = '') {
  if (!request) return prs;
  return prs.map((pr) => ({ ...pr, lines: (pr.lines || []).filter((line) => line.source_request === request) }))
    .filter((pr) => pr.lines.length);
}

export function contextApprovals(approvals = [], request = '') {
  if (!request) return approvals;
  return approvals.filter((item) => splitList(item.source_requests).includes(request));
}

export function contextPos(pos = [], request = '') {
  if (!request) return pos;
  return pos.filter((po) => (po.lines || []).some((line) => line.source_request === request));
}

export function contextSummary({ request, prs = [], approvals = [], pos = [] }) {
  if (!request) return '';
  return `${request} · ${prs.length} 张 PR · 待比价 ${pendingLineCount(prs)} 项 · ${approvals.length} 张价格审批单 · ${pos.length} 张 PO`;
}

// ------------------------------------------------------------------ PR source
export function lineRemaining(line) {
  return Math.max(0, toNumber(line?.remaining_quantity));
}

// 已被占用 = PR 数量 - 可选数量（草稿 / 待审批占着，撤回或取消才释放，已生成 PO 的数量也算）。
export function occupiedQuantity(line) {
  return Math.max(0, toNumber(line?.quantity) - lineRemaining(line));
}

// 草稿 / 已取消 / 已关闭的 PR 不能再生成价格审批单，剩余数量不算待比价（和后端 PR_CLOSED_STATUSES、看板「待比价物料」同一口径）。
export const PR_CLOSED_STATUSES = Object.freeze(['草稿', 'Draft', '已取消', '已关闭']);

export function availableLineCount(pr) {
  if (PR_CLOSED_STATUSES.includes(String(pr?.status || ''))) return 0;
  return (pr?.lines || []).filter((line) => lineRemaining(line) > 0).length;
}

export function pendingLineCount(prs = []) {
  return prs.reduce((sum, pr) => sum + availableLineCount(pr), 0);
}

export function sourceKey(pr, line) {
  return `${pr.name}:${line.name}`;
}

export function filterPrs(prs = [], { query = '', availability = 'available', focusPr = '' } = {}) {
  const needle = String(query || '').trim().toLowerCase();
  let result = prs.map((pr) => ({
    ...pr,
    lines: needle
      ? (pr.lines || []).filter((line) => [pr.name, line.source_request, line.material_serial, line.material_code, line.item_name, line.project]
        .join(' ').toLowerCase().includes(needle))
      : (pr.lines || []),
  })).filter((pr) => pr.lines.length);
  if (focusPr) result = result.filter((pr) => pr.name === focusPr);
  if (availability === 'available') result = result.filter((pr) => availableLineCount(pr) > 0);
  if (availability === 'exhausted') result = result.filter((pr) => availableLineCount(pr) === 0);
  return [...result].sort((a, b) => availableLineCount(b) - availableLineCount(a));
}

// 每条 PR 物料被哪些价格审批单（草稿 / 待审批）和 PO 占着，用来解释"已被占用"。
export function usageByPrLine(approvals = [], pos = []) {
  const map = new Map();
  const push = (key, entry) => {
    if (!key) return;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(entry);
  };
  approvals.filter((item) => ['草稿', '待审批'].includes(item.status)).forEach((item) => {
    (item.lines || []).forEach((line) => push(line.source_pr_line, { kind: 'PA', name: item.name, status: item.status }));
  });
  pos.filter((po) => po.status !== '已取消').forEach((po) => {
    (po.lines || []).forEach((line) => push(line.source_pr_line, { kind: 'PO', name: po.name, status: po.status }));
  });
  return map;
}

export function usageText(entries = []) {
  const seen = new Set();
  return entries.filter((entry) => {
    if (seen.has(entry.name)) return false;
    seen.add(entry.name);
    return true;
  }).map((entry) => `${entry.name} ${entry.status}`).join('、');
}

export function quantityError(line, value) {
  const number = Number(value);
  if (value === '' || value === null || value === undefined || !Number.isFinite(number) || number <= 0) return '请填写大于 0 的数量';
  if (number > lineRemaining(line) + 1e-9) return `最多 ${quantity(lineRemaining(line))}`;
  return '';
}

export function selectedLines(prs = [], selected = new Set(), quantities = {}) {
  const rows = [];
  prs.forEach((pr) => (pr.lines || []).forEach((line) => {
    const key = sourceKey(pr, line);
    if (selected.has(key)) rows.push({ pr, line, key, quantity: quantities[key] });
  }));
  return rows;
}

export function selectionSummary(rows = []) {
  return {
    count: rows.length,
    prs: new Set(rows.map((row) => row.pr.name)).size,
    requests: new Set(rows.map((row) => row.line.source_request).filter(Boolean)).size,
    invalid: rows.filter((row) => quantityError(row.line, row.quantity)).length,
  };
}

export function createApprovalLines(rows = []) {
  return rows.map((row) => ({ source_pr: row.pr.name, source_pr_line: row.line.name, quantity: Number(row.quantity) }));
}

// ------------------------------------------------------------------ price approval: matrix
function priceOf(group, line) {
  return (group?.prices || []).find((item) => item.price_line === line.name) || null;
}

export function chosenGroup(approval) {
  return (approval?.supplier_comparisons || []).find((group) => group.is_selected) || null;
}

// 比价矩阵：总价只在"这家报全了所有物料"时才互相比较；只报了一部分的不比总价、不标最低；每个物料单独标最低单价。
export function buildMatrix(approval) {
  const lines = approval?.lines || [];
  const groups = approval?.supplier_comparisons || [];
  const suppliers = groups.map((group) => {
    const quoted = lines.filter((line) => {
      const price = priceOf(group, line);
      return price && toNumber(price.unit_price) > 0;
    });
    const total = lines.reduce((sum, line) => {
      const price = priceOf(group, line);
      return sum + (price ? toNumber(price.unit_price) * toNumber(line.quantity) : 0);
    }, 0);
    return {
      group, supplier: group.supplier, quotedCount: quoted.length, lineCount: lines.length,
      complete: lines.length > 0 && quoted.length === lines.length, total,
      isRecommended: Boolean(group.is_recommended), isSelected: Boolean(group.is_selected),
      lowestComplete: false,
    };
  });
  const complete = suppliers.filter((item) => item.complete);
  if (complete.length >= 2) {
    const min = Math.min(...complete.map((item) => cents(item.total)));
    complete.forEach((item) => { item.lowestComplete = cents(item.total) === min; });
  }
  const rows = lines.map((line) => {
    const quotes = groups.map((group) => priceOf(group, line)).map((price) => (price && toNumber(price.unit_price) > 0 ? price : null));
    const quotedUnits = quotes.filter(Boolean).map((price) => cents(price.unit_price));
    const best = quotedUnits.length >= 2 ? Math.min(...quotedUnits) : null;
    return {
      line,
      cells: quotes.map((price, index) => ({
        supplier: groups[index].supplier,
        quoted: Boolean(price),
        unit: price ? toNumber(price.unit_price) : null,
        total: price ? toNumber(price.unit_price) * toNumber(line.quantity) : null,
        delivery: price ? String(price.delivery_date || '') : '',
        best: price !== null && best !== null && cents(price.unit_price) === best,
        chosen: Boolean(groups[index].is_selected),
      })),
    };
  });
  return { suppliers, rows };
}

export function supplierQuoteLabel(item) {
  if (!item.lineCount) return '';
  return item.complete ? `${item.lineCount} 项全部报价` : `只报了 ${item.quotedCount} / ${item.lineCount} 项`;
}

export function supplierTotalNote(item) {
  if (!item.complete) return '未报全，不比总价';
  return item.lowestComplete ? '完整报价中最低' : '';
}

export function latestDelivery(group) {
  const dates = (group?.prices || []).map((item) => String(item.delivery_date || '')).filter(Boolean).sort();
  return dates.length ? dates[dates.length - 1] : '';
}

// 副总经理选定供应商后的后果：没报价的物料退回 PR；一张价格审批单只生成一张 PO。
export function selectionConsequence(approval, group) {
  if (!group) return null;
  const lines = approval?.lines || [];
  const quoted = lines.filter((line) => {
    const price = priceOf(group, line);
    return price && toNumber(price.unit_price) > 0;
  });
  const total = quoted.reduce((sum, line) => sum + toNumber(priceOf(group, line).unit_price) * toNumber(line.quantity), 0);
  return { supplier: group.supplier, quoted: quoted.length, returned: lines.length - quoted.length, total, lineCount: lines.length };
}

export function approvalGuide(approval, { canEdit = false } = {}) {
  const status = approval?.status;
  const chosen = chosenGroup(approval);
  if (status === '草稿') {
    return {
      tone: 'sun',
      text: canEdit
        ? '草稿：录入各家报价和商务条件，写好"采购比价总结"后提交。提交会重新占用 PR 数量，如果这期间数量被别人用了，会提交失败。'
        : '草稿：采购正在录入各家报价，提交后才进入副总经理审批。',
    };
  }
  if (status === '待审批' && approval?.can_select_quote) {
    const info = selectionConsequence(approval, chosen);
    if (!info) {
      return { tone: 'sun', text: '第 1 步：在供应商栏点"选择成交供应商"（采购推荐仅供参考，需要您确认成交供应商）。第 2 步：核对后点右上"审批通过，生成 PO"。一张价格审批单只选一家，生成一张 PO。' };
    }
    return {
      tone: 'jade',
      text: `已选择：${info.supplier}，成交总额 ${money(info.total)}。${info.returned ? `它没报价的 ${info.returned} 项物料会退回 PR，需要重新比价。` : `${info.lineCount} 项物料全部成交。`}审批通过后立刻生成 1 张 PO 草稿。`,
    };
  }
  if (status === '待审批') {
    return { tone: 'cobalt', text: '已提交，等待副总经理审批。撤回修改会释放占用的 PR 数量，退回草稿；之后重新提交时数量如被占用会失败。' };
  }
  if (status === '已取消') return { tone: 'gray', text: '价格审批单已取消，物料数量已释放回 PR。' };
  if (status === '已通过' || status === '已转PO') return { tone: 'jade', text: '价格审批已通过，已按成交供应商生成 PO；没报价的物料已退回 PR。' };
  return null;
}

// 提交价格审批前还缺什么（服务端也会检查：比价总结必填、至少一家有效报价）。
export function submitBlockers(approval, summaryDraft = '') {
  const blockers = [];
  if (!String(summaryDraft || '').trim()) blockers.push('填写采购比价总结');
  if (!(approval?.supplier_comparisons || []).length) blockers.push('至少录入一家供应商报价');
  return blockers;
}

export function approvalTimeline(approval) {
  const draft = approval?.status === '草稿';
  const items = [{
    key: 'submit', label: '采购提交价格审批', state: draft ? 'todo' : 'done',
    sub: draft ? '还没提交' : '已提交', note: '',
  }];
  const steps = approval?.steps || [];
  if (!steps.length) {
    items.push({ key: 'vp', label: '价格审批：副总经理', state: 'todo', sub: draft ? '未开始' : '', note: '' });
    return items;
  }
  steps.forEach((step) => {
    const done = step.status === '已通过';
    const rejected = step.status === '已拒绝';
    const when = dateTime(step.acted_on);
    items.push({
      key: step.name || step.label,
      label: String(step.label || '价格审批'),
      state: done ? 'done' : rejected ? 'rejected' : 'now',
      sub: done ? `${step.action_by || '已通过'}${when ? ` · ${when}` : ''}` : rejected ? `已拒绝${when ? ` · ${when}` : ''}` : '待审批',
      note: step.note || '',
    });
  });
  return items;
}

export function posForApproval(pos = [], approvalName = '') {
  return pos.filter((po) => splitList(po.source_price_approvals).includes(approvalName));
}

export const APPROVAL_FILTERS = [
  { key: 'all', label: '全部', match: () => true },
  { key: 'draft', label: '草稿', match: (item) => item.status === '草稿' },
  { key: 'pending', label: '待审批', match: (item) => item.status === '待审批' },
  { key: 'done', label: '已通过', match: (item) => ['已通过', '已转PO'].includes(item.status) },
  { key: 'closed', label: '已取消', match: (item) => ['已取消', '已拒绝'].includes(item.status) },
];

export function filterApprovals(approvals = [], key = 'all', query = '') {
  const filter = APPROVAL_FILTERS.find((item) => item.key === key) || APPROVAL_FILTERS[0];
  const needle = String(query || '').trim().toLowerCase();
  return approvals.filter((item) => filter.match(item)).filter((item) => !needle
    || [item.name, item.source_prs, item.source_requests, item.source_projects, item.demand_summary,
      ...(item.supplier_comparisons || []).map((group) => group.supplier)].join(' ').toLowerCase().includes(needle));
}

// ------------------------------------------------------------------ supplier quote drawer
export function newPlanRow(index = 1, patch = {}) {
  return {
    installment_name: `第${index}期`, payment_stage: '尾款', percentage: 0, amount: 0, planned_date: '',
    trigger_condition: '全部到货并验收通过', invoice_requirement: '付款前提供', ...patch,
  };
}

export function defaultPlanRows() {
  return [newPlanRow(1, {
    installment_name: '验收合格后全额付款', payment_stage: '到货后全额付款', percentage: 100, amount: '',
    trigger_condition: '全部到货并验收通过',
  })];
}

export function emptySupplierDraft(approval, defaults = {}) {
  const prices = {};
  (approval?.lines || []).forEach((line) => { prices[line.name] = { unit_price: '', delivery_date: '' }; });
  const entity = defaults.contract_entity
    || (approval?.supplier_comparisons || []).map((group) => group.contract_entity).find(Boolean)
    || DEFAULT_CONTRACT_ENTITY;
  return {
    original_supplier: '', supplier: '', payment_method: '', currency: 'CNY', tax_rate: 13,
    contract_entity: entity, is_recommended: false, note: '', prices, payment_plan: defaultPlanRows(),
  };
}

export function supplierDraftFromGroup(approval, group) {
  const draft = emptySupplierDraft(approval);
  (approval?.lines || []).forEach((line) => {
    const price = priceOf(group, line);
    draft.prices[line.name] = { unit_price: price ? price.unit_price : '', delivery_date: price?.delivery_date || '' };
  });
  return {
    ...draft,
    original_supplier: group.supplier, supplier: group.supplier,
    payment_method: group.payment_method || '', currency: group.currency || 'CNY',
    tax_rate: group.tax_rate ?? 13, contract_entity: group.contract_entity || '',
    is_recommended: Boolean(group.is_recommended), note: group.note || '',
    payment_plan: (group.payment_plan || []).length ? group.payment_plan.map((row) => ({ ...row })) : defaultPlanRows(),
  };
}

function quotedPrice(draft, line) {
  const raw = draft.prices?.[line.name]?.unit_price;
  if (raw === '' || raw === null || raw === undefined) return null;
  const number = Number(raw);
  return Number.isFinite(number) ? number : null;
}

export function draftLineTotal(draft, line) {
  const price = quotedPrice(draft, line);
  return price === null ? null : price * toNumber(line.quantity);
}

export function draftTotal(approval, draft) {
  return (approval?.lines || []).reduce((sum, line) => sum + (draftLineTotal(draft, line) || 0), 0);
}

export function planTotals(draft) {
  const rows = draft.payment_plan || [];
  return {
    percentage: rows.reduce((sum, row) => sum + toNumber(row.percentage), 0),
    amount: rows.reduce((sum, row) => sum + toNumber(row.amount), 0),
  };
}

export function amountFromPercentage(total, percentage) {
  return Math.round(toNumber(total) * toNumber(percentage)) / 100;
}

// "按报价总额"：每期金额 = 报价合计 x 比例，最后一期取差额，保证合计等于报价合计。
export function fillPlanAmounts(draft, total) {
  const rows = draft.payment_plan || [];
  const target = cents(total);
  let used = 0;
  rows.forEach((row, index) => {
    if (index === rows.length - 1) row.amount = (target - used) / 100;
    else {
      const part = Math.round(target * toNumber(row.percentage) / 100);
      used += part;
      row.amount = part / 100;
    }
  });
  return rows;
}

export function validateSupplierDraft(approval, draft) {
  const errors = [];
  if (!String(draft.supplier || '').trim()) errors.push('请先填写供应商名称');
  if (!String(draft.payment_method || '').trim()) errors.push('请填写付款方式');
  const lines = approval?.lines || [];
  const quoted = lines.filter((line) => quotedPrice(draft, line) !== null);
  if (!quoted.length) errors.push('至少给一项物料报价（没有报价的物料留空）');
  if (quoted.some((line) => quotedPrice(draft, line) <= 0)) errors.push('报价单价必须大于 0');
  const rate = Number(draft.tax_rate);
  if (!Number.isFinite(rate) || rate < 0 || rate > 100) errors.push('税率必须在 0 到 100 之间');
  const rows = draft.payment_plan || [];
  if (!rows.length) errors.push('请填写付款计划');
  rows.forEach((row, index) => {
    const label = `第${index + 1}期`;
    if (toNumber(row.percentage) <= 0 || toNumber(row.amount) <= 0) errors.push(`${label}的比例和金额必须大于 0`);
    if (!PAYMENT_STAGES.includes(row.payment_stage)) errors.push(`${label}请选择付款阶段`);
    if (!String(row.trigger_condition || '').trim()) errors.push(`${label}请填写触发条件`);
    if (!INVOICE_REQUIREMENTS.includes(row.invoice_requirement)) errors.push(`${label}请选择发票要求`);
  });
  const totals = planTotals(draft);
  if (rows.length && Math.abs(totals.percentage - 100) > 0.0001) errors.push('付款计划比例合计必须为 100%');
  if (rows.length && quoted.length && Math.abs(totals.amount - draftTotal(approval, draft)) > 0.01) errors.push('付款计划金额合计必须等于报价合计');
  return errors;
}

export function supplierPayload(approval, draft) {
  const prices = (approval?.lines || []).map((line) => {
    const price = quotedPrice(draft, line);
    return { price_line: line.name, unit_price: price === null ? '' : price, delivery_date: draft.prices?.[line.name]?.delivery_date || '' };
  });
  return {
    price_approval: approval.name,
    original_supplier: draft.original_supplier || '',
    supplier: String(draft.supplier || '').trim(),
    payment_method: String(draft.payment_method || '').trim(),
    currency: 'CNY',
    tax_rate: Number(draft.tax_rate || 0),
    contract_entity: String(draft.contract_entity || '').trim(),
    is_recommended: draft.is_recommended ? 1 : 0,
    note: draft.note || '',
    payment_plan: JSON.stringify((draft.payment_plan || []).map((row) => ({
      installment_name: row.installment_name, payment_stage: row.payment_stage, percentage: Number(row.percentage),
      amount: Number(row.amount), planned_date: row.planned_date || '', trigger_condition: row.trigger_condition,
      invoice_requirement: row.invoice_requirement,
    }))),
    prices: JSON.stringify(prices),
  };
}

// ------------------------------------------------------------------ PO / contract
export function isPoDraft(po) {
  return PO_EDITABLE.includes(po?.status);
}

// 合同办理走到哪：draft(PO 草稿) -> fill(补充合同信息) -> review(草稿待复核) -> seal(待电子用印) -> effective(已生效)。
export function contractMode(po) {
  if (!po) return 'draft';
  if (po.status === '已取消') return 'cancelled';
  if (isPoDraft(po)) return 'draft';
  const contract = po.contract_status || '待补充信息';
  if (contract === '已生效') return 'effective';
  if (contract === '待电子用印') return 'seal';
  if (contract === '草稿待复核') return 'review';
  return 'fill';
}

export const CONTRACT_STEPS = [
  { label: '补充信息', sub: '供应商全称、合同交期' },
  { label: '复核合同', sub: '采购核对合同草稿' },
  { label: '电子用印', sub: '副总经理用印' },
  { label: '合同生效', sub: '制作 · 到货 · 验收 · 付款' },
];

export function contractStepper(po) {
  const mode = contractMode(po);
  const stage = { draft: 0, fill: 0, review: 1, seal: 2, effective: 3, cancelled: 0 }[mode];
  const sealed = mode === 'effective';
  return CONTRACT_STEPS.map((step, index) => {
    const done = index < stage || (sealed && index === 3);
    const now = index === stage && !sealed && mode !== 'cancelled';
    return { ...step, index, done, now, mark: done ? '✓' : String(index + 1) };
  });
}

// 当前账号在这张 PO 上能做的下一步，以及不能做时显示的等待说明。
export function poMainAction(po) {
  const mode = contractMode(po);
  const manage = Boolean(po?.can_manage_purchase);
  if (mode === 'draft') return manage ? { key: 'confirm', text: '确认 PO' } : { key: '', wait: '等待采购确认 PO' };
  if (mode === 'fill') return manage ? { key: 'generate', text: '生成合同草稿' } : { key: '', wait: '等待采购补充合同信息' };
  if (mode === 'review') return manage ? { key: 'review', text: '复核合同' } : { key: '', wait: '等待采购复核合同' };
  if (mode === 'seal') return po.can_seal_contract ? { key: 'seal', text: '电子用印' } : { key: '', wait: '等待副总经理电子用印' };
  return { key: '', wait: '' };
}

export function poNextStep(po) {
  const mode = contractMode(po);
  if (po?.status === '已关闭') return '已关闭';
  if (mode === 'cancelled') return '已取消';
  if (mode === 'draft') return '确认合同交期，确认 PO';
  if (mode === 'fill') return '补充合同信息，生成合同草稿';
  if (mode === 'review') return '复核合同草稿';
  if (mode === 'seal') return '副总经理电子用印';
  return poCloseBlockers(po).length ? '到货 / 验收 / 付款进行中' : '可校验并关闭';
}

export function lineReceived(line) {
  return toNumber(line?.received_quantity) >= toNumber(line?.quantity) && toNumber(line?.quantity) > 0;
}

export function poProgress(po) {
  const lines = po?.lines || [];
  const received = lines.filter(lineReceived).length;
  const passed = lines.filter((line) => String(line.inspection_status || '') === '已通过').length;
  const planPaid = (po?.payment_plan || []).every((row) => toNumber(row.paid_amount) >= toNumber(row.amount));
  const paidFull = cents(po?.paid_amount) >= cents(po?.total_amount) && cents(po?.total_amount) > 0 && planPaid;
  return {
    lineCount: lines.length, received, passed, paid: toNumber(po?.paid_amount), total: toNumber(po?.total_amount),
    allReceived: lines.length > 0 && received === lines.length,
    allPassed: lines.length > 0 && passed === lines.length,
    paidFull,
  };
}

// 校验并关闭 PO 还差什么：全部到货、全部验收通过、付款结清。
export function poCloseBlockers(po) {
  const progress = poProgress(po);
  const missing = [];
  if (!progress.allReceived) missing.push('全部到货');
  if (!progress.allPassed) missing.push('全部验收通过');
  if (!progress.paidFull) missing.push('付款结清');
  return missing;
}

export function planStatus(row) {
  const amount = toNumber(row?.amount);
  if (row?.status === '已付款' || (amount > 0 && toNumber(row?.paid_amount) >= amount)) return { text: '已付款', tone: 'jade' };
  if (row?.payment_request) return { text: row.status === '审批中' ? '付款审批中' : (row.status || '付款审批中'), tone: 'cobalt' };
  if (row?.status === '待审批') return { text: '待审批（未发起）', tone: 'gray' };
  return { text: row?.status || '待生成', tone: 'gray' };
}

export function paymentLink(row) {
  return row?.payment_request ? { path: PAYMENT_PAGE, query: { request: row.payment_request } } : { path: PAYMENT_PAGE };
}

// "去登记到货 / 验收 / 付款"：带上这张 PO（采购付款页的付款工作项按 po= 预选这张 PO 并显示全部状态），不再丢到页面最前面。
export function paymentPoLink(po) {
  const name = typeof po === 'string' ? po : String(po?.name || '');
  return name ? { path: PAYMENT_PAGE, query: { po: name } } : { path: PAYMENT_PAGE };
}

// 价格审批工作台的页面标题：三个页签共用一个页面，PO 页签要说清楚是"采购订单与合同"，不是价格审批本身。
export function pageTitle(tab = '') {
  if (tab === 'po') return '价格审批 · 采购订单与合同';
  if (tab === 'source') return '价格审批 · PR 待比价物料';
  return '价格审批';
}

export function contractFields(po) {
  return [
    { key: 'supplier_legal_name', label: '供应商全称', value: po?.contract_supplier_legal_name || po?.supplier || '' },
    { key: 'credit_code', label: '统一社会信用代码', value: po?.contract_credit_code || '' },
    { key: 'supplier_address', label: '供应商地址', value: po?.contract_supplier_address || '', wide: true },
    { key: 'contract_contact', label: '联系人 / 电话', value: po?.contract_contact || '' },
    { key: 'contract_bank_name', label: '开户行', value: po?.contract_bank_name || '' },
    { key: 'contract_bank_account', label: '银行账号', value: po?.contract_bank_account || '', secret: true },
    { key: 'contract_delivery_date', label: '合同交期', value: po?.contract_delivery_date || '', date: true },
  ];
}

export function contractDraftFor(po) {
  const draft = {};
  contractFields(po).forEach((field) => { draft[field.key] = field.value; });
  return draft;
}

// 生成合同草稿接口收到的参数；没填的字段不传，服务端只更新有传入的字段。
export function contractPayload(po, draft) {
  const payload = { name: po.name, supplier_legal_name: String(draft.supplier_legal_name || '').trim() };
  ['credit_code', 'supplier_address', 'contract_contact', 'contract_bank_name', 'contract_bank_account'].forEach((key) => {
    const value = String(draft[key] ?? '').trim();
    if (value) payload[key] = value;
  });
  if (draft.contract_delivery_date) payload.contract_delivery_date = draft.contract_delivery_date;
  return payload;
}

export function deliveryPayload(po, deliveryDraft = {}) {
  return (po?.lines || []).map((line) => ({ line: line.name, contract_delivery_date: deliveryDraft[line.name] || '' }));
}

export function missingDelivery(po, deliveryDraft = {}) {
  return (po?.lines || []).filter((line) => !deliveryDraft[line.name]).length;
}

export function poTrail(po) {
  const trail = [];
  if (po?.creation) trail.push({ key: 'create', time: dateTime(po.creation), text: `价格审批通过，生成 PO 草稿${po.source_price_approvals ? `（${po.source_price_approvals}）` : ''}` });
  (po?.steps || []).forEach((step) => {
    if (step.acted_on) trail.push({ key: `step-${step.name || step.label}`, time: dateTime(step.acted_on), text: `${step.action_by || ''} ${step.label || ''} ${step.status || ''}`.trim() });
  });
  if (po?.contract_reviewed_on) trail.push({ key: 'review', time: dateTime(po.contract_reviewed_on), text: `${po.contract_reviewed_by || '采购'} 复核合同` });
  if (po?.contract_sealed_on) trail.push({ key: 'seal', time: dateTime(po.contract_sealed_on), text: `${po.contract_sealed_by || '副总经理'} 电子用印，合同生效` });
  return trail.reverse();
}

export const PO_FILTERS = [
  { key: 'all', label: '全部', match: () => true },
  { key: 'contract', label: '合同办理中', match: (po) => ['草稿', '待采购确认', '待合同复核', '待电子用印'].includes(po.status) },
  { key: 'running', label: '执行中', match: (po) => ['已生效', '供应商制作中', '到货验收中', '付款中'].includes(po.status) },
  { key: 'closed', label: '已关闭', match: (po) => ['已关闭', '已取消'].includes(po.status) },
];

export function filterPos(pos = [], key = 'all', query = '') {
  const filter = PO_FILTERS.find((item) => item.key === key) || PO_FILTERS[0];
  const needle = String(query || '').trim().toLowerCase();
  return pos.filter((po) => filter.match(po)).filter((po) => !needle
    || [po.name, po.supplier, po.source_price_approvals, ...(po.lines || []).flatMap((line) => [line.source_request, line.project, line.item_name, line.material_serial])]
      .join(' ').toLowerCase().includes(needle));
}

export function poSources(po) {
  const lines = po?.lines || [];
  return {
    requests: [...new Set(lines.map((line) => line.source_request).filter(Boolean))],
    projects: [...new Set(lines.map((line) => line.project).filter(Boolean))],
    prs: [...new Set(lines.map((line) => line.source_pr).filter(Boolean))],
  };
}
