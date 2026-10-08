export function hasAllocationData(payload) {
  return Boolean(payload && payload.has_data);
}

// 月度未定版时（preview=true）矩阵按预览取数：不带分摊单名，多一个 preview: 1。
export function buildAllocationMatrixFilters({ scope, period, allocation, stage, preview }) {
  if (scope === "year") {
    return { year: Number(String(period).slice(0, 4)), stage };
  }
  if (preview) {
    const [previewYear, previewMonth] = String(period).split("-").map(Number);
    return { year: previewYear, month: previewMonth, stage, preview: 1 };
  }
  if (allocation) {
    return { allocation, stage };
  }
  const [year, month] = String(period).split("-").map(Number);
  return { year, month, stage };
}

export function allocationEmptyState({ hasData, mode }) {
  if (!hasData) return "no-data";
  return mode === "all" ? "no-detail" : "no-detail-for-mode";
}

export async function loadAllocationStageMatrices({
  scope,
  period,
  allocation,
  preview,
  load,
}) {
  const stageMatrices = {};
  for (const stage of ["all", "capitalized", "expensed"]) {
    const data = await load(buildAllocationMatrixFilters({
      scope,
      period,
      allocation,
      stage,
      preview,
    }));
    stageMatrices[stage] = {
      columns: data?.columns || [],
      result: data?.result || [],
    };
  }
  return stageMatrices;
}

// ---- 预览 + 定版 ----

// 页面状态：year（年度只读）/ finalized（已定版）/ preview（预览）/ preview-error（预览算不出来）/ empty（没有数据）。
export function allocationViewState({ payload, scope } = {}) {
  if (scope === "year") return "year";
  if (!payload) return "empty";
  if (payload.preview && payload.preview_error) return "preview-error";
  if (payload.finalized) return "finalized";
  if (payload.preview && payload.has_data) return "preview";
  return "empty";
}

// 状态标签（页头）；没有数据时不显示。
export function allocationStatusTag(state) {
  if (state === "year") return { text: "年度 · 只读", cls: "" };
  if (state === "finalized") return { text: "已定版", cls: "ok" };
  if (state === "preview" || state === "preview-error") return { text: "预览 · 未定版", cls: "warn" };
  return null;
}

export const FINALIZE_DENIED_TITLE = "只有财务主管可以定版";
export const CANCEL_FINALIZE_DENIED_TITLE = "只有财务主管可以撤销定版";
export const PREVIEW_ERROR_TITLE = "预览算不出来，暂时不能定版";

// 操作按钮：预览显示「定版本月分摊」，已定版显示「撤销定版」；只有 can_finalize 才能点。
export function allocationActionState({ state, payload } = {}) {
  const canFinalize = Boolean(payload && payload.can_finalize);
  const out = {
    showFinalize: false,
    finalizeDisabled: true,
    finalizeTitle: undefined,
    showCancel: false,
    cancelDisabled: true,
    cancelTitle: undefined,
  };
  if (state === "preview" || state === "preview-error") {
    out.showFinalize = true;
    if (!canFinalize) {
      out.finalizeTitle = FINALIZE_DENIED_TITLE;
    } else if (state === "preview-error") {
      out.finalizeTitle = PREVIEW_ERROR_TITLE;
    } else {
      out.finalizeDisabled = false;
    }
  } else if (state === "finalized") {
    out.showCancel = true;
    if (canFinalize) out.cancelDisabled = false;
    else out.cancelTitle = CANCEL_FINALIZE_DENIED_TITLE;
  }
  return out;
}

function formatAmount(value) {
  const n = Number(value || 0);
  return (Number.isFinite(n) ? n : 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function peopleCount(value) {
  if (Array.isArray(value)) return value.length;
  const n = Math.round(Number(value) || 0);
  return n > 0 ? n : 0;
}

function peopleNames(value) {
  if (!Array.isArray(value)) return "";
  const names = value
    .map((item) => (typeof item === "string" ? item : item && (item.employee_name || item.name || item.employee)))
    .filter(Boolean);
  if (!names.length) return "";
  return names.slice(0, 6).join("、") + (names.length > 6 ? " 等" : "");
}

function moneyIsZero(value) {
  return Math.abs(Number(value || 0)) < 0.005;
}

function warningText(item) {
  if (typeof item === "string") return item;
  return (item && (item.message || item.text)) || "";
}

// 把 get_finalize_check 的结果变成确认卡片里的检查行：tone = warn（大于 0，琥珀色）或 ok（为 0）。
export function buildFinalizeCheckLines(check) {
  if (!check) return [];
  const lines = [];
  const people = [
    ["underfilled", check.underfilled_people, (n) => `还有 ${n} 人工时未填满`, "没有人工时未填满"],
    ["unfilled", check.unfilled_people, (n) => `${n} 人未填工时`, "没有人未填工时"],
    ["over-limit", check.over_limit_people, (n) => `${n} 人工时超上限`, "没有人工时超上限"],
  ];
  for (const [key, value, positive, zero] of people) {
    if (value === undefined || value === null) continue;
    const n = peopleCount(value);
    lines.push({ key, tone: n > 0 ? "warn" : "ok", text: n > 0 ? positive(n) : zero, detail: n > 0 ? peopleNames(value) : "" });
  }
  const money = [
    ["unknown", check.unknown_amount, (v) => `未判定金额 ${v} 元`],
    ["foreign-common", check.unallocated_foreign_common_amount, (v) => `没有境外工时可分的境外公共费用 ${v} 元`],
    ["diff", check.reconcile_diff, (v) => `差额 ${v} 元`],
  ];
  for (const [key, value, text] of money) {
    if (value === undefined || value === null) continue;
    lines.push({ key, tone: moneyIsZero(value) ? "ok" : "warn", text: text(formatAmount(value)), detail: "" });
  }
  (Array.isArray(check.warnings) ? check.warnings : []).forEach((item, i) => {
    const text = warningText(item);
    if (text) lines.push({ key: `warning-${i}`, tone: "warn", text, detail: "" });
  });
  return lines;
}

export function finalizeCheckIssueCount(lines = []) {
  return lines.filter((line) => line.tone === "warn").length;
}

// 预览提示（preview_warnings）：字符串或 {message}，去掉空项。
export function previewWarningTexts(payload) {
  const list = payload && Array.isArray(payload.preview_warnings) ? payload.preview_warnings : [];
  return list.map(warningText).filter(Boolean);
}
