// 研发费用汇总 / 首页数据看板：未定版月份的「预览」标签与说明文字。
// 后端新增的字段都可能缺失，缺了就什么演示员工177显示。

export const PREVIEW_TAG_TEXT = "预览 · 未定版";
export const FINALIZED_TAG_TEXT = "已定版";
export const PREVIEW_MONTH_HINT = "本月还没有定版，数字是按当前费用和工时算出的预览。";
export const COST_PREVIEW_TAG_TEXT = "含预览";
export const COST_PREVIEW_TITLE = "包含未定版月份的预览数字";

function monthNumber(value) {
  const match = /^(\d{4})-(\d{1,2})$/.exec(String(value ?? "").trim());
  if (!match) return null;
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? { key: `${match[1]}-${String(month).padStart(2, "0")}`, month } : null;
}

// ["2026-03", "2026-04"] -> "3 月、4 月"；去重、按时间排序、丢掉无法识别的值。
export function formatPreviewMonths(months) {
  if (!Array.isArray(months)) return "";
  const seen = new Map();
  for (const value of months) {
    const parsed = monthNumber(value);
    if (parsed && !seen.has(parsed.key)) seen.set(parsed.key, parsed.month);
  }
  return [...seen.keys()].sort().map((key) => `${seen.get(key)} 月`).join("、");
}

export function previewMonthCount(months) {
  if (!Array.isArray(months)) return 0;
  return new Set(months.map((value) => monthNumber(value)?.key).filter(Boolean)).size;
}

// 研发费用汇总页（月度）：未定版显示琥珀色「预览 · 未定版」，已定版显示绿色「已定版」，其余不显示。
// cls 与 .rd .tag 的 warn / ok 对应。
export function dashboardStatusTag(payload, scope) {
  if (scope === "year" || !payload || typeof payload !== "object") return null;
  if (payload.preview) {
    return { text: PREVIEW_TAG_TEXT, cls: "warn", hint: PREVIEW_MONTH_HINT };
  }
  if (payload.finalized) {
    return { text: FINALIZED_TAG_TEXT, cls: "ok", hint: "" };
  }
  return null;
}

// 研发费用汇总页（全年）：「全年数字包含 N 个月的预览（M 月、…），这些月份定版后可能有变化。」
export function yearPreviewNote(payload) {
  if (!payload || typeof payload !== "object") return "";
  const months = Array.isArray(payload.preview_months) ? payload.preview_months : [];
  const count = previewMonthCount(months);
  if (!payload.has_preview && !count) return "";
  if (!count) return "全年数字包含未定版月份的预览，这些月份定版后可能有变化。";
  return `全年数字包含 ${count} 个月的预览（${formatPreviewMonths(months)}），这些月份定版后可能有变化。`;
}

// 年度逐月明细里，某个月是不是预览月（用来给该月打小「预览」标签）。
export function isPreviewMonth(payload, month) {
  const target = monthNumber(month)?.key;
  if (!target || !Array.isArray(payload?.preview_months)) return false;
  return payload.preview_months.some((value) => monthNumber(value)?.key === target);
}

// 首页成本区块：月度 preview=true，或 preview_months 非空，就显示小「含预览」标签。
export function costPreviewTag(payload) {
  if (!payload || typeof payload !== "object") return null;
  const months = Array.isArray(payload.preview_months) ? payload.preview_months : [];
  const label = formatPreviewMonths(months);
  if (!payload.preview && !label) return null;
  return {
    text: COST_PREVIEW_TAG_TEXT,
    title: label ? `${COST_PREVIEW_TITLE}（${label}）` : COST_PREVIEW_TITLE,
  };
}
