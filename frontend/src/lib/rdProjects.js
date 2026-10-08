// 项目管理页的纯逻辑：指标卡数字、附件药丸、待处理事项。都从 list_projects 已经返回的字段算出来，不需要新接口。
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

function projectStatus(row) {
  return row?.status || 'Open';
}

function isOpen(row) {
  return projectStatus(row) === 'Open';
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

// 三类附件各自「需不需要」的规则（表格里的药丸和待处理事项共用这一处）：
//   已取消的项目：都不需要
//   立项报告：进行中、已结束都要
//   结项报告：已结束才要
//   资本化确认书：阶段是资本化，且进行中或已结束
export function requiredAttachments(row) {
  const status = projectStatus(row);
  const active = status === 'Open' || status === 'Completed';
  return {
    project_initiation_report: active,
    project_completion_report: status === 'Completed',
    capitalization_confirmation_file: active && projectStage(row) === '资本化',
  };
}

// 每个项目固定三枚药丸，顺序：立项报告、结项报告、资本化确认书。
// state: 'up' 已上传（不管要不要都算已上传）；'miss' 需要但没传；'na' 不需要。
export function attachmentPills(row) {
  const required = requiredAttachments(row);
  return PROJECT_FILE_FIELDS.map((field) => {
    const file = row?.[field.key] || '';
    const needed = Boolean(required[field.key]);
    const state = file ? 'up' : needed ? 'miss' : 'na';
    return {
      key: field.key,
      label: field.label,
      state,
      text: state === 'miss' ? `缺${field.label}` : field.label,
      file,
      required: needed,
      missing: state === 'miss',
    };
  });
}

export function hasMissingAttachment(row) {
  return attachmentPills(row).some((pill) => pill.missing);
}

// 待处理事项（取消的项目不算），顺序：缺立项报告 → 阶段未判定 → 资本化缺确认书 → 缺结项报告。
// 附件类事项和表格里的「缺…」药丸用同一套规则，所以指标卡数字和药丸数量始终一致。
export function pendingProjectItems(rows = []) {
  const list = Array.isArray(rows) ? rows : [];
  const label = (row) => `${projectCode(row)} ${row?.project_name || ''}`.trim();
  const missing = (row, key) => attachmentPills(row).some((pill) => pill.key === key && pill.missing);
  const item = (row, text, tone) => ({ code: projectCode(row), label: label(row), text, tone });
  const items = [];
  list.filter((row) => missing(row, 'project_initiation_report')).forEach((row) => items.push(item(row, isOpen(row) ? '进行中但缺立项报告' : '已结项但缺立项报告', 'bad')));
  list.filter(isOpen).filter((row) => projectStage(row) === '未判定').forEach((row) => items.push(item(row, '研发阶段未判定，费用暂不能资本化', 'warn')));
  list.filter((row) => missing(row, 'capitalization_confirmation_file')).forEach((row) => items.push(item(row, '资本化项目缺确认书', 'warn')));
  list.filter((row) => missing(row, 'project_completion_report')).forEach((row) => items.push(item(row, '已结项但缺结项报告', 'warn')));
  return items;
}

// 提示条：最多列 limit 条，其余用省略号
export function pendingSummary(items = [], limit = 3) {
  const shown = items.slice(0, limit).map((item) => `${item.label}：${item.text}`);
  return { count: items.length, text: shown.join('；'), more: items.length > limit };
}
