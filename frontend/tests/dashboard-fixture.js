// get_home 的假响应（字段严格按 rayher_hr_payroll/dashboard/core.py）：测试和本地预览共用。数字是编的，只看结构。
const t = (key, params = {}) => ({ key, params });
const kpi = (key, label, value, extra = {}) => ({ key, label, value, unit: '', sub: '', tone: '', target: null, hint: '', preview: false, ...extra });

export const KPIS = [
  kpi('cost.total', '本月费用合计', '128.6', { unit: '万', sub: '较上月 +3.2%', tone: '', target: t('cost.summary', { period: '2026-10' }), hint: '研发分摊 + 采购 + 报销', preview: true }),
  kpi('pay.unpaid', '待付款', '42.3', { unit: '万', sub: '17 笔，其中加急 2 笔', tone: 'hot', target: t('payment.unpaid'), hint: '待付款 = 已审批、只差演示员工110付款的单据' }),
  kpi('approval.stuck', '审批卡点', '5', { unit: '张', sub: '最久已等 9 天', tone: 'bad', target: t('claim.stuck') }),
  kpi('hr.active', '在职', '86', { unit: '人', sub: '研发 54 · 其他 32', tone: 'info', target: t('personnel.list', { status: 'active' }) }),
  kpi('ts.rate', '工时填报率', '92%', { sub: '研发 54 人，填工时 58 人', tone: 'ok', target: t('timesheet.board', { status: 'open' }), hint: '研发 N = 研发类型为全时/非全时/辅助的在职人数；填工时 M = 工时填报名单人数' }),
  kpi('alloc.status', '研发分摊', '预览', { sub: '未判定 ¥ 2.1 万', tone: 'warn', target: t('allocation', { period: '2026-10' }), preview: true }),
  kpi('hr.expiring', '60 天内到期', '4', { unit: '人', sub: '演示员工173期 3 · 演示员工116 1', tone: 'warn', target: t('personnel.expiring') }),
  kpi('proc.po_transit', 'PO 在途', '12', { unit: '张', target: t('procpay.work', { status: '待到货' }) }),
  // 没有跳转：只显示
  kpi('plain.noTarget', '只看数字', '7', { unit: '项' }),
  // 目标名后端和前端表漂移了
  kpi('plain.unknown', '未知目标', '1', { target: t('no.such.target') }),
  // 指向需要财务权限的页面，用来测试置灰
  kpi('plain.finance', '分摊汇总', '3', { target: t('cost.summary') }),
  kpi('plain.empty', '没有数值', ''),
];

export const ALERTS = [
  { key: 'alert.pay_waiting', tone: 'bad', title: '3 笔待付款已等待超过 3 天', sub: '最久 8 天', go: '去付款', target: t('payment.waiting') },
  { key: 'alert.stuck', tone: 'warn', title: '5 张单据卡在审批中超过 3 天', sub: '报销 3 · 采购付款 2', go: '去看看', target: t('claim.stuck') },
  { key: 'alert.rd_gap', tone: 'info', title: '研发部门有 2 人没设研发类型', sub: '', go: '去设置', target: t('personnel.rd_gap') },
  { key: 'alert.plain', tone: 'warn', title: '只提醒、没有跳转', sub: '', go: '', target: null },
];

export const TODOS = [
  { kind: '报销单', title: '差旅报销 · 演示员工129', sub: '研发软件部 · ¥ 3,280 · 已等待 5 天', btn: '去审批', tone: 'info', target: t('claim.detail', { request: 'OA-18291' }) },
  { kind: '请假', title: '年假 2 天 · 演示员工146', sub: '研发算法部 · 今天提交', btn: '去审批', tone: 'info', target: t('attendance.detail', { request: 'OA-18300' }) },
  { kind: '价格审批', title: 'PA-0042 光学镜片', sub: '终审 · 已等待 2 天', btn: '去处理', tone: 'warn', target: t('price.approvals', { approval: 'PA-0042' }) },
];

export const BARS = {
  key: 'block.dept_headcount', type: 'bars', title: '部门人数', sub: 'Top 5 + 其他', more: '员工信息', target: t('personnel.list', { status: 'active' }), hint: '按在职员工所在部门统计', error: null,
  rows: [
    { label: '研发软件部', value: '24', pct: 100, tone: '' },
    { label: '研发光学部', value: '18', pct: 75, tone: 'info' },
    { label: '研发机械部', value: '12', pct: 50, tone: 'ok' },
    { label: '行政部', value: '6', pct: 25, tone: 'warn' },
    { label: '财务部', value: '3', pct: 12.5, tone: 'hot' },
    { label: '其他', value: '1', pct: 0.3, tone: 'bad' },
  ],
};

export const COLS = {
  key: 'block.cost_trend', type: 'cols', title: '近 6 个月费用', sub: '万元', more: '', target: t('cost.summary'), hint: '', error: null,
  rows: [
    { label: '5月', value: '98', pct: 70, last: false }, { label: '6月', value: '110', pct: 80, last: false },
    { label: '7月', value: '105', pct: 76, last: false }, { label: '8月', value: '121', pct: 88, last: false },
    { label: '9月', value: '124', pct: 90, last: false }, { label: '10月', value: '128.6', pct: 100, last: true },
  ],
};

export const STACK = {
  key: 'block.cost_mix', type: 'stack', title: '费用构成', sub: '本月', more: '', target: null, hint: '', error: null,
  rows: [
    { label: '研发分摊', value: '79.2 万', pct: 61.6, color: '#D9731F' },
    { label: '采购', value: '31.0 万', pct: 24.1, color: '#34489A' },
    { label: '报销', value: '18.4 万', pct: 14.3, color: 'javascript:alert(1)' },
    { label: '没有占比', value: '0', pct: 0, color: '#8A93A3' },
  ],
};

export const LIST = {
  key: 'block.expiring_list', type: 'list', title: '60 天内到期', sub: '演示员工173期 / 演示员工116', more: '全部', target: t('personnel.expiring'), hint: '', error: null,
  rows: [
    { label: '演示员工157', sub: '演示员工173期', value: '10-15', tone: 'bad', target: t('personnel.expiring') },
    { label: '演示员工175', sub: '演示员工116', value: '11-02', tone: 'warn', target: null },
    { label: '孙七', sub: '演示员工173期', value: '11-20', tone: 'ok', target: t('no.such.target') },
    { label: '周八', sub: '演示员工116', value: '12-01', tone: 'info', target: t('cost.summary') },
  ],
};

export const BLOCK_ERROR = {
  key: 'block.pay_steps', type: 'bars', title: '付款审批卡在哪一步', sub: '', rows: [], more: '', target: null, hint: '', error: '这一块暂时加载失败',
};

export const BLOCK_EMPTY = { key: 'block.leave_types', type: 'bars', title: '本月请假类型', sub: '', rows: [], more: '', target: null, hint: '', error: null };

const page = (extra) => ({ kpis: [], alerts: [], todos: [], blocks: [], errors: [], has_todos: false, has_alerts: false, ...extra });

// 领导：总览有 todo 和 alert，另外三个页签。
export const HOME_LEADER = {
  role: { key: 'general_manager', label: '总经理', person: '演示员工21', note: '公司整体 + 要你终审的事，一屏看全。' },
  period: '2026-10',
  tabs: [{ key: 'overview', label: '总览' }, { key: 'cost', label: '经营' }, { key: 'people', label: '人事' }],
  pages: {
    overview: page({ kpis: KPIS, alerts: ALERTS, todos: TODOS, blocks: [STACK, BLOCK_ERROR], has_todos: true, has_alerts: true, errors: [{ key: 'block.pay_steps', message: 'boom' }] }),
    cost: page({ kpis: KPIS.slice(0, 4), blocks: [COLS, BARS] }),
    people: page({ kpis: KPIS.slice(3, 5), blocks: [LIST, BLOCK_EMPTY] }),
  },
  generated_at: 1790000000,
};

// 只有一个页签的岗位；待办为空；提醒块也在，但这会儿没有触发。
export const HOME_SINGLE = {
  role: { key: 'employee', label: '员工', person: '演示员工129', note: '我的待办、假期、申请、报销和工时。' },
  period: '2026-10',
  tabs: [{ key: 'overview', label: '总览' }],
  pages: { overview: page({ kpis: KPIS.slice(0, 2), has_todos: true, has_alerts: true, blocks: [BARS] }) },
  generated_at: 1790000000,
};

// 只有「要我处理」，没有提醒。
export const HOME_TODOS_ONLY = {
  ...HOME_SINGLE,
  pages: { overview: page({ kpis: KPIS.slice(0, 2), has_todos: true, todos: TODOS }) },
};

// 页签里什么都没有。
export const HOME_NOTHING = { ...HOME_SINGLE, pages: { overview: page({}) } };
