// 项目管理页的纯逻辑：指标卡数字、待处理事项。都从 list_projects 已经返回的字段算出来，不需要新接口。
export const PROJECT_FILE_FIELDS = [
  { key: 'project_initiation_report', label: '立项报告', short: '立' },
  { key: 'project_completion_report', label: '结项报告', short: '结' },
  { key: 'capitalization_confirmation_file', label: '资本化确认书', short: '资' },
];

export function projectCode(row) {
  return row?.rd_project_code || row?.name || '';
}

export function projectStage(row) {
  return row?.rd_stage_label || row?.rd_stage || '未判定';
}

// 页面里用的色调：资本化 ok、费用化 info、其余中性
export function stageTone(stage) {
  if (stage === '资本化') return 'ok';
  if (stage === '费用化') return 'info';
  return '';
}

export function statusTone(status) {
  if (status === 'Cancelled') return 'bad';
  if (status === 'Completed') return '';
  return 'ok';
}

function isOpen(row) {
  return (row?.status || 'Open') === 'Open';
}

export function projectStats(rows = []) {
  const list = Array.isArray(rows) ? rows : [];
  const open = list.filter(isOpen);
  return {
    total: list.length,
    open: open.length,
    capitalized: open.filter((row) => projectStage(row) === '资本化').length,
    expensed: open.filter((row) => projectStage(row) === '费用化').length,
  };
}

// 待处理事项（取消的项目不算），顺序：缺立项报告 → 阶段未判定 → 资本化缺确认书 → 已结项缺结项报告
export function pendingProjectItems(rows = []) {
  const list = Array.isArray(rows) ? rows : [];
  const label = (row) => `${projectCode(row)} ${row?.project_name || ''}`.trim();
  const open = list.filter(isOpen);
  const items = [];
  open.filter((row) => !row.project_initiation_report).forEach((row) => items.push({ code: projectCode(row), label: label(row), text: '进行中但缺立项报告', tone: 'bad' }));
  open.filter((row) => projectStage(row) === '未判定').forEach((row) => items.push({ code: projectCode(row), label: label(row), text: '研发阶段未判定，费用暂不能资本化', tone: 'warn' }));
  open.filter((row) => projectStage(row) === '资本化' && !row.capitalization_confirmation_file).forEach((row) => items.push({ code: projectCode(row), label: label(row), text: '资本化项目缺确认书', tone: 'warn' }));
  list.filter((row) => row?.status === 'Completed' && !row.project_completion_report).forEach((row) => items.push({ code: projectCode(row), label: label(row), text: '已结项但缺结项报告', tone: 'warn' }));
  return items;
}

// 提示条：最多列 limit 条，其余用省略号
export function pendingSummary(items = [], limit = 3) {
  const shown = items.slice(0, limit).map((item) => `${item.label}：${item.text}`);
  return { count: items.length, text: shown.join('；'), more: items.length > limit };
}
