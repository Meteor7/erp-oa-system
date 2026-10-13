// 操作记录里每一条的名字。后端早期写的是英文（Targeted rejection、Add-sign …），页面上一律显示中文。
const LABELS = {
  'Targeted rejection': '驳回',
  '定向驳回': '驳回',
  'Add-sign': '加签',
  'Finance expense classification': '财务分类',
};

export function eventLabel(action) {
  const text = String(action || '');
  return LABELS[text] || text;
}

// 这一条是不是驳回 / 退回（含早期的英文 Targeted rejection）。
export function isRejectionEvent(action) {
  return /驳回|退回/.test(eventLabel(action));
}
