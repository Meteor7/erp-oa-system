export function normalizeExportFilename(filename) {
  const value = String(filename || "export").trim() || "export";
  return value.toLowerCase().endsWith(".xlsx") ? value : `${value}.xlsx`;
}

export function buildExportRows(rows = [], columns = []) {
  return (rows || []).map((row) => {
    const result = {};
    for (const column of columns || []) {
      result[column.label] = typeof column.value === "function"
        ? column.value(row)
        : row?.[column.key];
    }
    return result;
  });
}

// 多工作表导出：sheets = [{ name, rows: 二维数组（第一行可以是表头）, widths: [列宽…] }]，顺序即工作表顺序。
export async function exportSheetsWorkbook({ filename, sheets = [] } = {}) {
  const XLSX = await import("xlsx");
  const workbook = XLSX.utils.book_new();
  for (const sheet of sheets) {
    const worksheet = XLSX.utils.aoa_to_sheet(sheet.rows || []);
    if (Array.isArray(sheet.widths)) worksheet["!cols"] = sheet.widths.map((wch) => ({ wch }));
    XLSX.utils.book_append_sheet(workbook, worksheet, String(sheet.name || "Sheet").slice(0, 31));
  }
  const output = normalizeExportFilename(filename);
  XLSX.writeFile(workbook, output);
  return output;
}

export async function exportTableWorkbook({ filename, sheetName = "Data", columns = [], rows = [] } = {}) {
  const XLSX = await import("xlsx");
  const exportRows = buildExportRows(rows, columns);
  const worksheet = XLSX.utils.json_to_sheet(exportRows, { header: columns.map((column) => column.label) });
  worksheet["!cols"] = columns.map((column) => ({ wch: column.width || 16 }));
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, String(sheetName || "Data").slice(0, 31));
  const output = normalizeExportFilename(filename);
  XLSX.writeFile(workbook, output);
  return output;
}
