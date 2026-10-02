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

function matrixRows(columns = [], result = []) {
  const headers = columns.map((column) => fieldLabel(column));
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

export function allocationExportFilename(period) {
  return `研发费用台账-${period}.xlsx`;
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

  const filename = allocationExportFilename(payload.period);
  XLSX.writeFile(workbook, filename);
  return filename;
}
