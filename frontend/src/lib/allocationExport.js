const STAGE_TOTAL_HEADERS = ["\u4f1a\u8ba1\u671f\u95f4", "\u7c7b\u578b", "\u91d1\u989d"];
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
