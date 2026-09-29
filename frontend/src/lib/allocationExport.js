const STAGE_TOTAL_HEADERS = ["\u4f1a\u8ba1\u671f\u95f4", "\u7c7b\u578b", "\u91d1\u989d"];
const UNRECONCILED_LABEL = "\u672a\u5bf9\u8d26\u5dee\u989d\uff08\u9636\u6bb5\u5408\u8ba1\u2212\u5206\u644a\u660e\u7ec6\uff09";
const STAGE_SHEET_NAMES = {
  all: "\u5206\u644a\u660e\u7ec6",
  capitalized: "\u8d44\u672c\u5316\u5206\u644a",
  expensed: "\u8d39\u7528\u5316\u5206\u644a",
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

export function allocationExportFilename(period) {
  return `\u7814\u53d1\u8d39\u7528\u53f0\u8d26-${period}.xlsx`;
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
    [period, "\u8d44\u672c\u5316\u5408\u8ba1", capitalized],
    [period, "\u8d39\u7528\u5316\u5408\u8ba1", expensed],
    [period, "\u8d44\u672c\u548c\u8d39\u7528\u5408\u8ba1", capitalized + expensed],
    [period, "\u672a\u5224\u5b9a\u5408\u8ba1", unknown],
  ];
  // 修复（2026-09-29，审查 X2-11-A）：阶段合计来自服务端汇总，明细来自矩阵报表，两边口径或舍入
  // 不一致时原来看不出来。有差额就在合计表里多写一行，方便财务对账。
  const allResult = allMatrix.result || [];
  if (allResult.length) {
    const difference = Math.round((capitalized + expensed + unknown - matrixTotal(allMatrix.columns || [], allResult)) * 100) / 100;
    if (Math.abs(difference) >= 0.01) stageTotals.push([period, UNRECONCILED_LABEL, difference]);
  }

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

  appendSheet(XLSX, workbook, "\u9636\u6bb5\u5408\u8ba1", sheets.stageTotals, [14, 16, 16]);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.all, sheets.matrix, matrixWidths);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.capitalized, sheets.capitalizedMatrix, matrixWidths);
  appendSheet(XLSX, workbook, STAGE_SHEET_NAMES.expensed, sheets.expensedMatrix, matrixWidths);

  const filename = allocationExportFilename(payload.period);
  XLSX.writeFile(workbook, filename);
  return filename;
}
