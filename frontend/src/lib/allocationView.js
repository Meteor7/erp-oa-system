import { stageLabel } from "./allocationGroups.js";

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

// ---- 矩阵列头：项目编号 + 项目名称 ----

// 项目列的页面列头和 Excel 列头。服务端列里 label 是项目键，project_code / project_name 是编号和名称
// （旧数据没有这两个字段时退回 label）。名称和编号/项目键相同时不重复显示。
// 返回 { code, name, stage, title, exportLabel }：
//   页面：code 一行，name 小字一行（单行省略），stage（资本化 / 费用化 / 未判定）小字一行，悬停 title；
//   title："RD13 · KIBO 5895H · 费用化"；Excel 列头 exportLabel："RD13 KIBO 5895H"（单行表头，导出仍可被程序读取）。
export function projectColumnHeader(column = {}) {
  const label = String(column.label ?? column.fieldname ?? column.id ?? "").trim();
  const code = String(column.project_code || label).trim();
  let name = String(column.project_name || "").trim();
  if (name === code || name === label) name = "";
  const stage = stageLabel(column.project_stage);
  return {
    code,
    name,
    stage,
    title: [code, name, stage].filter(Boolean).join(" · "),
    exportLabel: name ? `${code} ${name}` : code,
  };
}

// ---- 定版人、撤销记录 ----

const DATETIME_RE = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?/;

// "2026-10-08 15:20:33" -> "10-08 15:20"（页面上的短时间）；认不出来返回空串。
export function shortDateTime(value) {
  const m = DATETIME_RE.exec(String(value ?? "").trim());
  return m ? `${m[1].slice(5)} ${m[2]}` : "";
}

// "2026-10-08T15:20:33.123456" -> "2026-10-08 15:20:33"（悬停和导出里的完整时间）；认不出来原样返回。
export function fullDateTime(value) {
  const text = String(value ?? "").trim();
  const m = DATETIME_RE.exec(text);
  return m ? `${m[1]} ${m[2]}${m[3] || ""}` : text;
}

function personName(by_name, by) {
  return String(by_name || by || "").trim();
}

// 已定版时页头状态标签旁的小字："演示员工16 · 10-08 15:20 定版"；title 是完整时间。没有定版人和时间返回 null。
export function finalizedStamp(payload) {
  if (!payload || !payload.finalized) return null;
  const who = personName(payload.finalized_by_name, payload.finalized_by);
  const short = shortDateTime(payload.finalized_on);
  if (!who && !short) return null;
  const full = fullDateTime(payload.finalized_on);
  const text = `${[who, short].filter(Boolean).join(" · ")} 定版`;
  const title = who && full ? `${who} 于 ${full} 定版` : who ? `${who} 定版` : `${full} 定版`;
  return { text, title };
}

// 预览状态下状态标签下面的小字："上次撤销：演示员工16 · 10-08 15:20 · 原因：补录一笔费用"。没有撤销记录返回 null。
export function lastRevokeLine(payload) {
  const revoke = payload && payload.last_revoke;
  if (!revoke) return null;
  const who = personName(revoke.by_name, revoke.by);
  const short = shortDateTime(revoke.on);
  const reason = String(revoke.reason || "").trim();
  const parts = [who, short, reason && `原因：${reason}`].filter(Boolean);
  const full = fullDateTime(revoke.on);
  const head = who && full ? `${who} 于 ${full} 撤销定版` : who ? `${who} 撤销定版` : full ? `${full} 撤销定版` : "撤销定版";
  return {
    text: parts.length ? `上次撤销：${parts.join(" · ")}` : "上次撤销",
    title: reason ? `${head}\n原因：${reason}` : head,
  };
}

// 预览提示（preview_warnings）：字符串或 {message}，去掉空项。
export function previewWarningTexts(payload) {
  const list = payload && Array.isArray(payload.preview_warnings) ? payload.preview_warnings : [];
  return list.map(warningText).filter(Boolean);
}
