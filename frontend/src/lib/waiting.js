// "等了多久"和"等太久"的统一口径，所有页面都用这里：
// 1. 按日历日期算（今天减起点那天），和后端看板、催办是同一个算法：10 月 9 日 23:30 起算，10 月 12 日 00:30 就是 3 天。
//    不能按满 24 小时算，那样临近午夜时前后端会差一天。
// 2. "等太久"= 严格大于 3 天（正好 3 天不算）。数据看板的"审批卡点"、采购催办的卡住提示都是这个口径。
//    催办按钮的"至少等 3 天才能催"是另一条规则（NUDGE_AFTER_DAYS，>=），不在这里。
export const STUCK_AFTER_DAYS = 3;

const DAY_MS = 86400000;

const startOfDay = (time) => {
  const day = new Date(time);
  return new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime();
};

// 起点（"2026-10-09 23:30:00" 或 ISO 字符串或毫秒数）到 now 过了几个日历日；起点算不出来返回 null，永远不为负。
export function calendarDaysSince(since, now = Date.now()) {
  const time = typeof since === 'number' ? since : Date.parse(String(since || '').replace(' ', 'T'));
  return Number.isFinite(time) ? Math.max(0, Math.round((startOfDay(now) - startOfDay(time)) / DAY_MS)) : null;
}

// 等了多少天算"等太久"：只看天数，null / 空 / 非数字都不算。
export function isWaitingTooLong(days) {
  if (days === null || days === undefined || days === '') return false;
  return Number(days) > STUCK_AFTER_DAYS;
}
