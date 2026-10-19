// 社保信息管理、公积金信息管理两个页面共用的纯函数：接口名、差异原因分类、明细整理、进度和能不能生效。
// 两个页面走同样的四步：导入申报表 → 核对差异 → 基数与金额 → 确认生效（薪酬直接读取）。

const SOCIAL_API = 'rayher_hr_payroll.api.social_insurance_import_entry.';
const FUND_API = 'rayher_hr_payroll.api.housing_fund_import_entry.';
export const SHARED_API = 'rayher_hr_payroll.api.contribution_workbench_entry.';

export const KINDS = Object.freeze({
  si: {
    key: 'si', name: '社保', title: '社保信息管理', source: '社保局', fileTitle: '社保缴费明细',
    baseLabel: '社保基数', excelBaseLabel: 'Excel缴费工资',
    fn: { workbench: SOCIAL_API + 'get_social_workbench', upload: SOCIAL_API + 'upload_social_workbook', activate: SOCIAL_API + 'activate_social_batch', confirm: SOCIAL_API + 'confirm_social_row', ignore: SOCIAL_API + 'ignore_social_row', cancel: SOCIAL_API + 'cancel_social_batch', reconcile: SOCIAL_API + 'reconcile_pending_batch' },
  },
  fund: {
    key: 'fund', name: '公积金', title: '公积金信息管理', source: '公积金中心', fileTitle: '公积金汇缴明细',
    baseLabel: '公积金基数', excelBaseLabel: 'Excel缴存基数',
    fn: { workbench: FUND_API + 'get_fund_workbench', upload: FUND_API + 'upload_fund_workbook', activate: FUND_API + 'activate_fund_batch', confirm: FUND_API + 'confirm_fund_row', ignore: FUND_API + 'ignore_fund_row', cancel: FUND_API + 'cancel_fund_batch', reconcile: FUND_API + 'reconcile_fund_batch' },
  },
});

export const STEPS = Object.freeze(['导入申报表', '核对差异', '基数与金额', '确认生效']);

export function kindOf(value) {
  return KINDS[value] || KINDS.si;
}

export const money = (value) => Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const signed = (value) => { const n = Number(value || 0); return (n > 0 ? '+' : '') + money(n); };
const num = (value) => Number(value || 0);
const near = (a, b) => Math.abs(num(a) - num(b)) < 0.005;

// ---------------------------------------------------------------- 差异原因
// 后台把原因写成一句话（用"；"连起来），这里按关键字归类：先处理哪一类、什么颜色。
const COMPONENT_NAMES = {
  employee_pension: '个人养老', company_pension: '单位养老', employee_medical: '个人医疗', company_medical: '单位医疗',
  company_maternity: '单位生育', company_injury: '单位工伤', employee_unemployment: '个人失业', company_unemployment: '单位失业',
  local_pension: '地方补充养老', employee_total: '个人合计', company_total: '单位合计', receivable_total: '应收合计',
};
const RULES = [
  ['noBase', '档案缺基数', 'bad', /基数未维护/, 1],
  ['hukou', '户口未维护', 'bad', /户口信息/, 2],
  ['unlinked', '无法关联员工', 'bad', /无法关联|无法自动判断/, 3],
  ['missing', '申报表里没有', 'bad', /申报表里没有/, 4],
  ['duplicate', 'Excel 内重复', 'bad', /重复/, 5],
  ['noPolicy', '政策未配置', 'warn', /政策未配置/, 6],
  ['baseDiff', '基数与档案不一致', 'warn', /(缴费工资|缴存基数).*不一致/, 7],
  ['nameDiff', '姓名不同', 'warn', /姓名不同/, 8],
  ['internal', 'Excel 合计对不上', 'warn', /内部合计/, 9],
  ['compDiff', '与后台复算不一致', 'warn', /与后台计算不一致/, 10],
];
const OTHER = { key: 'other', label: '其他原因', tone: 'warn', order: 99 };

export function reasonText(raw) {
  return String(raw || '').replace(/([a-z_]+)(?=与后台计算不一致)/g, (_all, key) => COMPONENT_NAMES[key] || key);
}

export function reasonTypes(raw) {
  const parts = String(raw || '').split('；').map((part) => part.trim()).filter(Boolean);
  return parts.map((part) => {
    const hit = RULES.find((rule) => rule[3].test(part));
    return hit ? { key: hit[0], label: hit[1], tone: hit[2], order: hit[4], text: reasonText(part) } : { ...OTHER, text: reasonText(part) };
  });
}

export function mainReason(types) {
  return [...types].sort((a, b) => a.order - b.order)[0] || OTHER;
}

// ---------------------------------------------------------------- 明细
const SOCIAL_LINES = [
  ['contribution_base', '缴费工资', 'reference_base'], ['employee_pension', '个人养老 8%'], ['company_pension', '单位养老 16%'],
  ['employee_medical', '个人医疗 2%'], ['company_medical', '单位医疗 6%'], ['company_maternity', '单位生育 0.5%'], ['company_injury', '单位工伤 0.8%'],
  ['employee_unemployment', '个人失业 0.2%'], ['company_unemployment', '单位失业 0.8%'], ['local_pension', '地方补充养老 1%（仅深户）'],
  ['employee_total', '个人合计'], ['company_total', '单位合计'], ['receivable_total', '应收合计'],
];
const FUND_LINES = [
  ['contribution_base', '缴存基数', 'reference_base'], ['employee_amount', '个人缴存额', 'calculated_employee_amount'],
  ['company_amount', '单位缴存额', 'calculated_company_amount'], ['receivable_total', '缴存合计', 'calculated_receivable_total'],
];

export function hasCalculation(_kind, row) {
  return num(row?.calculated_receivable_total) > 0;
}

// 抽屉里"申报 vs 复算"的逐项对比。没复算出来（档案缺基数、户口未维护……）时复算一列留空，不拿 0 当结果。
export function comparisonLines(kind, row) {
  const lines = kind === 'si' ? SOCIAL_LINES : FUND_LINES;
  const calculated = hasCalculation(kind, row);
  return lines.map(([field, label, calcField]) => {
    const excel = num(row?.[field]);
    let calc = null;
    if (field === 'contribution_base') calc = num(row?.reference_base) > 0 ? num(row.reference_base) : null;
    else if (calculated) calc = num(row?.[calcField || `calculated_${field}`]);
    return { field, label, excel, calc, differs: calc != null && !near(excel, calc) };
  });
}

export function excelTotal(kind, row) {
  return kind === 'si' ? num(row?.receivable_total) : num(row?.employee_amount) + num(row?.company_amount);
}
export function calcTotal(kind, row) {
  return hasCalculation(kind, row) ? num(row?.calculated_receivable_total) : null;
}

export const STATUS_LABEL = Object.freeze({
  Matched: '匹配成功', Pending: '待处理', 'Confirmed Difference': '已确认纳入', Ignored: '已忽略',
  Current: '已生效', Historical: '历史批次', 'Pending Activation': '待确认导入', Canceled: '已取消', Failed: '失败',
});

export function normalizeRow(kind, row) {
  const types = reasonTypes(row.difference_reasons);
  const main = mainReason(types);
  const excel = excelTotal(kind, row);
  const calc = calcTotal(kind, row);
  return {
    id: row.name, raw: row, kind, name: row.employee_name || row.excel_name, excelName: row.excel_name, company: row.company,
    employee: row.employee || '', rowType: row.row_type === 'missing' ? 'missing' : 'excel', status: row.status, remark: row.remark || '',
    types, main, reasons: types.map((item) => item.text),
    excelTotal: row.row_type === 'missing' ? null : excel, calcTotal: calc, diff: calc == null || row.row_type === 'missing' ? null : Number((excel - calc).toFixed(2)),
    resolved: row.status !== 'Pending', identity: row.masked_identity || '',
  };
}

// 没处理的排前面；同一类里按原因的轻重（挡路的先），再按姓名。
export function sortIssues(list) {
  return [...list].sort((a, b) => Number(a.resolved) - Number(b.resolved) || a.main.order - b.main.order || String(a.name).localeCompare(String(b.name), 'zh-CN'));
}

export function issueFilter(list, filter) {
  if (filter === 'done') return list.filter((item) => item.resolved);
  if (filter === 'all') return list;
  return list.filter((item) => !item.resolved);
}

// 抽屉里能选的处理方式。后台只有"确认纳入（按 Excel 记账）"和"忽略"两种有记录的处理，其余是引导。
export function drawerOptions(kind, item) {
  const name = kindOf(kind).name;
  if (item.rowType === 'missing') {
    return [
      { key: 'ignore', label: '标记为需补缴，下月申报补上', hint: '申报漏了；备注里写清补缴月份', note: '需补缴：', recommended: true },
      { key: 'ignore', label: '确认本月不用缴纳', hint: '例如停薪留职、已离职未减员；备注里写明原因', note: '无需缴纳：' },
    ];
  }
  const options = [];
  const keys = item.types.map((type) => type.key);
  if (keys.includes('noBase') || keys.includes('hukou')) {
    options.push({ key: 'fix', label: keys.includes('hukou') ? '去补齐户口和基数后重新核对' : '去补齐基数后重新核对', hint: `在“基数与金额”里填写${name}基数${kind === 'si' ? '和户口' : ''}，回来系统会自动重新核对`, recommended: true });
  } else if (keys.includes('baseDiff')) {
    options.push({ key: 'fix', label: `申报是对的：把档案${name}基数改成 Excel 的基数`, hint: '比如年度调基。去“基数与金额”里改，回来会自动重新核对', recommended: true });
  }
  if (keys.includes('unlinked')) options.push({ key: 'link', label: '这是某位在职员工：选择员工后确认纳入', hint: '证件号码对不上，人工关联后会再核对一次' });
  options.push({ key: 'confirm', label: '确认纳入这条差异，按 Excel 记账', hint: '需要写明原因；生效后薪酬按 Excel 金额扣款', needsNote: true });
  options.push({ key: 'ignore', label: '忽略这一行，不进入正式明细', hint: '需要写明原因', needsNote: true });
  return options;
}

// ---------------------------------------------------------------- 进度
export function batchOf(data) {
  const batches = data?.batches || [];
  return batches.find((item) => item.status === 'Pending Activation') || batches.find((item) => item.is_current || item.status === 'Current') || null;
}

export function progress(data) {
  const dashboard = data?.dashboard || {};
  const total = num(dashboard.total_rows);
  const pendingExcel = (data?.pending || []).filter((row) => row.row_type !== 'missing').length;
  const done = Math.max(total - pendingExcel, 0);
  return { total, done, percent: total ? Math.round(done * 100 / total) : 0 };
}

export function stepStates({ data, missingBase = 0 }) {
  const batch = batchOf(data);
  const pending = num(data?.dashboard?.pending_rows);
  const current = batch?.status === 'Current';
  return [
    { done: Boolean(batch), desc: batch ? `${batch.source_filename} · ${num(batch.parsed_rows)} 行` : '还没导入' },
    { done: Boolean(batch) && pending === 0, desc: !batch ? '先导入' : pending ? `${pending} 条待处理` : '差异已处理完' },
    { done: Boolean(batch) && missingBase === 0, desc: missingBase ? `${missingBase} 人缺基数` : '基数齐全' },
    { done: current, desc: current ? '已生效，薪酬可读取' : '未生效' },
  ];
}

// 确认生效前还差什么。每一项带上要去的步骤。
export function activationBlockers({ data, missingBase = 0 }) {
  const batch = batchOf(data);
  if (!batch) return [{ text: '还没有导入申报表', step: 1 }];
  if (batch.status === 'Current') return [];
  const list = [];
  const pending = num(data?.dashboard?.pending_rows);
  if (pending) list.push({ text: `还有 ${pending} 条差异没处理`, step: 2 });
  if (missingBase) list.push({ text: `${missingBase} 人缺基数`, step: 3 });
  return list;
}

export function pendingSummary(items) {
  const counts = new Map();
  items.filter((item) => !item.resolved).forEach((item) => counts.set(item.main.key, { ...item.main, count: (counts.get(item.main.key)?.count || 0) + 1 }));
  return [...counts.values()].sort((a, b) => a.order - b.order);
}

// ---------------------------------------------------------------- 基数表
export function baseStatus(row, kind) {
  if (row.base == null) return { text: '缺基数', tone: 'p-red' };
  if (kind === 'si' && row.household_classification === '待完善') return { text: '缺户口', tone: 'p-red' };
  if (row.note) return { text: row.note, tone: 'p-sun' };
  if (row.prev_base != null && !near(row.prev_base, row.base)) return { text: '较上月有变化', tone: 'p-sun' };
  return { text: '正常', tone: 'p-jade' };
}

export function missingBaseCount(rows, kind) {
  return (rows || []).filter((row) => row.base == null || (kind === 'si' && row.household_classification === '待完善')).length;
}

export function readinessText(readiness, kind) {
  const item = readiness?.kinds?.[kind];
  if (!item) return '';
  return item.missing_count ? `${item.label}还差 ${item.missing_count} 人没有本月记录` : `${item.label}本月记录已齐（${item.ready} 人）`;
}
