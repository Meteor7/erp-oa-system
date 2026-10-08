import { fullDateTime, projectColumnHeader } from "./allocationView.js";

const STAGE_TOTAL_HEADERS = ["会计期间", "类型", "金额"];
const UNRECONCILED_LABEL = "未对账差额（阶段合计−分摊明细）";
const STAGE_SHEET_NAMES = {
  all: "分摊明细",
  capitalized: "资本化分摊",
  expensed: "费用化分摊",
};

function fieldKey(column = {}) {
  return column.fieldname || column.id;
}

function fieldLabel(column = {}) {
  return column.label || column.fieldname || column.id || "";
}

function amount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function isStaticColumn(column = {}) {
  return ["period", "voucher_no", "account_level_3", "account_level_4", "row_total"].includes(fieldKey(column));
}

function columnsForStage(columns = [], stage) {
  return columns.filter((column) => isStaticColumn(column) || column.project_stage === stage);
}

// 项目列的表头带项目名称（"RD13 KIBO 5895H"，仍是单行表头）；其他列沿用原来的表头。
function headerLabel(column = {}) {
  if (isStaticColumn(column)) return fieldLabel(column);
  return projectColumnHeader(column).exportLabel;
}

function matrixRows(columns = [], result = []) {
  const headers = columns.map((column) => headerLabel(column));
  const projectKeys = columns
    .filter((column) => !isStaticColumn(column) && (column.project || column.project_stage))
    .map((column) => fieldKey(column));
  const rows = result.map((row) => columns.map((column) => {
    if (fieldKey(column) === "row_total") {
      return projectKeys.reduce((sum, key) => sum + amount(row[key]), 0);
    }
    return row[fieldKey(column)] ?? "";
  }));
  return [headers, ...rows];
}

function matrixTotal(columns = [], result = []) {
  const projectKeys = columns
    .filter((column) => !isStaticColumn(column) && (column.project || column.project_stage))
    .map((column) => fieldKey(column));
  return result
    .filter((row) => !row._is_total)
    .reduce((sum, row) => sum + projectKeys.reduce((rowSum, key) => rowSum + amount(row[key]), 0), 0);
}

// 修复（2026-09-29，审查 X2-11-A）：阶段合计来自服务端汇总，明细来自矩阵报表，两边口径或舍入
// 不一致时原来看不出来。差额 = 阶段合计（资本化 + 费用化 + 未判定）− 矩阵明细合计，保留两位小数。
// 矩阵没有明细行时返回 null（没有东西可对账）。导出和台账页面的「对账」检查共用这一个算法。
export function allocationReconcileDifference({ summary = {}, columns = [], result = [] } = {}) {
  if (!result || !result.length) return null;
  const stageTotal = amount(summary?.capitalized) + amount(summary?.expensed) + amount(summary?.unknown);
  return Math.round((stageTotal - matrixTotal(columns || [], result)) * 100) / 100;
}

// 导出文件名和「阶段合计」表里「会计期间」列用的标签：
//   已定版 "2026-06-已定版-演示员工16-汇总"，预览 "2026-06-预览-汇总"，年度 "2026年-汇总"。
export function allocationExportLabel({ period, state, finalizedByName, modeLabel } = {}) {
  const parts = [period];
  if (state === "finalized") {
    parts.push("已定版");
    if (finalizedByName) parts.push(finalizedByName);
  } else if (state === "preview" || state === "preview-error") {
    parts.push("预览");
  }
  parts.push(modeLabel);
  return parts.filter(Boolean).join("-");
}

export function allocationExportFilename(period) {
  // Windows 文件名里不能有的字符（姓名、原因里偶尔会带）换成下划线。
  const safe = String(period ?? "").replace(/[\\/:*?"<>|\r\n]+/g, "_");
  return `研发费用台账-${safe}.xlsx`;
}

const STATE_TEXT = {
  finalized: "已定版",
  preview: "预览（未定版，数字会随费用和工时变化）",
  "preview-error": "预览（算不出来）",
  year: "年度汇总（只含已定版的月份和境外数据）",
};

// 「导出信息」表：会计期间、定版状态、定版人和时间（预览则是上次撤销）、口径、导出时间。
export function buildAllocationInfoRows({
  period,
  state,
  allocationName,
  finalizedBy,
  finalizedOn,
  lastRevoke,
  modeLabel,
  exportedAt,
} = {}) {
  const rows = [["项目", "内容"], ["会计期间", period ?? ""], ["状态", STATE_TEXT[state] || ""]];
  if (allocationName) rows.push(["分摊单", allocationName]);
  if (state === "finalized") {
    if (finalizedBy) rows.push(["定版人", finalizedBy]);
    if (finalizedOn) rows.push(["定版时间", fullDateTime(finalizedOn)]);
  } else if (lastRevoke) {
    const who = lastRevoke.by_name || lastRevoke.by || "";
    const when = lastRevoke.on ? fullDateTime(lastRevoke.on) : "";
    const stamp = [who, when].filter(Boolean).join(" ");
    if (stamp) rows.push(["上次撤销", stamp]);
    if (lastRevoke.reason) rows.push(["撤销原因", lastRevoke.reason]);
  }
  if (modeLabel) rows.push(["口径", modeLabel]);
  if (exportedAt) rows.push(["导出时间", exportedAt]);
  return rows;
}

// 本地时间 "YYYY-MM-DD HH:mm:ss"
export function exportTimestamp(date = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}

export function buildAllocationExportSheets({
  period,
  summary = {},
  columns = [],
  result = [],
  stageMatrices = {},
} = {}) {
  const capitalized = amount(summary.capitalized);
  const expensed = amount(summary.expensed);
  const unknown = amount(summary.unknown);
  const allMatrix = stageMatrices.all || { columns, result };
  const capitalizedMatrix = stageMatrices.capitalized;
  const expensedMatrix = stageMatrices.expensed;
  const stageTotals = [
    STAGE_TOTAL_HEADERS,
    [period, "资本化合计", capitalized],
    [period, "费用化合计", expensed],
    [period, "资本和费用合计", capitalized + expensed],
    [period, "未判定合计", unknown],
  ];
  // 阶段合计和明细对不上时，在合计表里多写一行，方便财务对账。
  const difference = allocationReconcileDifference({
    summary,
    columns: allMatrix.columns || [],
    result: allMatrix.result || [],
  });
  if (difference !== null && Math.abs(difference) >= 0.01) stageTotals.push([period, UNRECONCILED_LABEL, difference]);

  return {
    stageTotals,
    matrix: matrixRows(allMatrix.columns || [], allMatrix.result || []),
    capitalizedMatrix: capitalizedMatrix
      ? matrixRows(capitalizedMatrix.columns || [], capitalizedMatrix.result || [])
      : matrixRows(columnsForStage(columns, "capitalized"), result),
    expensedMatrix: expensedMatrix
      ? matrixRows(expensedMatrix.columns || [], expensedMatrix.result || [])
      : matrixRows(columnsForStage(columns, "expensed"), result),
  };
}

function appendSheet(XLSX, workbook, name, rows, widths) {
  const worksheet = XLSX.utils.aoa_to_sheet(rows);
  worksheet["!cols"] = widths.map((wch) => ({ wch }));
  XLSX.utils.book_append_sheet(workbook, worksheet, name);
}

export async function exportAllocationWorkbook(payload) {
  const XLSX = await import("xlsx");
  const sheets = buildAllocationExportSheets(payload);
  const workbook = XLSX.utils.book_new();
  const matrixWidths = (payload.columns || []).map((column) => (isStaticColumn(column) ? 20 : 14));

  appendSheet(XLSX, workbook, "阶段合计", sheets.stageTotals, [14, 16, 16]);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.all, sheets.matrix, matrixWidths);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.capitalized, sheets.capitalizedMatrix, matrixWidths);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.expensed, sheets.expensedMatrix, matrixWidths);
  // 放在最后，前面几张表的位置和内容不变。
  if (Array.isArray(payload.info) && payload.info.length) {
    appendSheet(XLSX, workbook, "导出信息", payload.info, [14, 44]);
  }

  const filename = allocationExportFilename(payload.period);
  XLSX.writeFile(workbook, filename);
  return filename;
}
