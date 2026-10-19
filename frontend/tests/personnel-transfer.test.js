import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  GUIDE_SHEET, IMPORT_MAX_ROWS, PREVIEW_LIST_LIMIT, SENSITIVE_KEYS, TEMPLATE_SHEET, TRANSFER_COLUMNS, TRANSFER_HEADERS,
  availableSensitiveKeys, buildEmployeeExportSheet, buildEmployeeTemplateSheets, buildImportPreview, canImportEmployees,
  canOfferSensitiveExport, convertCell, describeChange, detectEmployeeHeader, employeeExportFilename, excelSerialToIso,
  exportCellValue, exportColumns, headerField, importResultText, normalizeDateText, numberToText, parseEmployeeTableRows,
  pickExportRows, readEmployeeWorkbook,
} from "../src/lib/personnelTransfer.js";

const backend = readFileSync(new URL("../../rayher_hr_payroll/api/personnel_entry.py", import.meta.url), "utf8");

async function loadXlsx() {
  const mod = await import("xlsx");
  return mod.utils ? mod : mod.default;
}

const serialOf = (year, month, day) => Math.round(Date.UTC(year, month - 1, day) / 86400000) + 25569;

// ---------- 列定义和后端对得上 ----------
test("transfer columns are the same fields, headers, kinds and sensitivity as the backend IMPORT_COLUMNS", () => {
  const block = backend.match(/IMPORT_COLUMNS = \(([\s\S]*?)\n\)/)?.[1] || "";
  const server = [...block.matchAll(/\("(\w+)", "([^"]+)", "(\w+)", (True|False)\),/g)]
    .map((match) => ({ key: match[1], label: match[2], kind: match[3], sensitive: match[4] === "True" }));
  assert.ok(server.length > 30);
  assert.deepEqual(
    TRANSFER_COLUMNS.map((column) => ({ key: column.key, label: column.label, kind: column.kind, sensitive: Boolean(column.sensitive) })),
    server,
  );
  assert.match(backend, /IMPORT_MAX_ROWS = 300/);
  assert.equal(IMPORT_MAX_ROWS, 300);
});

test("every drawer field has an import column, and sensitive columns are the pay and id tabs", () => {
  const keys = new Set(TRANSFER_COLUMNS.map((column) => column.key));
  for (const key of ["company", "employee_number", "employee_name", "english_name", "gender", "date_of_birth", "cell_number", "household_registration",
    "date_of_joining", "relieving_date", "department", "designation", "reports_to", "employment_type", "rd_personnel_type", "expense_account_category",
    "archive_status", "labour_contract_start_date", "probation_months", "probation_end_date", "first_contract_period_years", "first_contract_end_date",
    "contract_renewal_status", "second_contract_period_years", "second_contract_end_date", "first_education_level", "first_education_school",
    "first_education_major", "education_level_cn", "degree_cn", "education_completion_type", "graduation_school", "major_cn"]) {
    assert.ok(keys.has(key), key);
    assert.ok(!SENSITIVE_KEYS.includes(key), `${key} must not be sensitive`);
  }
  assert.deepEqual([...SENSITIVE_KEYS].sort(), [
    "bank_ac_no", "bank_name", "default_housing_fund_base", "default_monthly_salary", "default_social_insurance_base",
    "housing_fund_number", "id_card_number_cn", "id_type_cn", "salary_months", "social_insurance_number",
  ]);
});

// ---------- 表头识别 + 模板 ----------
test("the template header row is recognised by the same header detection the importer uses", () => {
  const [sheet, guide] = buildEmployeeTemplateSheets();
  assert.equal(sheet.name, TEMPLATE_SHEET);
  assert.equal(guide.name, GUIDE_SHEET);
  assert.deepEqual(sheet.rows[0], TRANSFER_HEADERS);
  const map = detectEmployeeHeader(sheet.rows[0]);
  assert.ok(map);
  for (const column of TRANSFER_COLUMNS) assert.equal(map[column.key], TRANSFER_COLUMNS.indexOf(column), column.key);
  assert.equal(detectEmployeeHeader(["南通工厂9", "A001", "研发软件部", 100]), null);
  assert.equal(detectEmployeeHeader(["姓名", "部门"]), null, "needs the employee number column");
  const headerOnly = parseEmployeeTableRows([sheet.rows[0]]);
  assert.deepEqual(headerOnly.errors, ["表里只有表头，没有数据行。"]);
});

test("headers are matched leniently: aliases, spaces, full-width brackets, required markers", () => {
  assert.equal(headerField("用工类型"), "employment_type");
  assert.equal(headerField(" 合同类型 "), "employment_type");
  assert.equal(headerField("入职时间"), "date_of_joining");
  assert.equal(headerField("*姓名"), "employee_name");
  assert.equal(headerField("试用期(月)"), "probation_months");
  assert.equal(headerField("试用期（月）"), "probation_months");
  assert.equal(headerField("岗位"), "designation");
  assert.equal(headerField("工资卡银行账号"), "bank_ac_no");
  assert.equal(headerField("employee_number"), "employee_number");
  assert.equal(headerField("没有这一列"), "");
  const labels = TRANSFER_COLUMNS.map((column) => column.label);
  assert.equal(new Set(labels).size, labels.length);
});

test("template: two obviously fake rows, no sensitive examples, and a guide row for every column", () => {
  const [sheet, guide] = buildEmployeeTemplateSheets();
  assert.equal(sheet.rows.length, 3);
  const numberIndex = TRANSFER_HEADERS.indexOf("员工号");
  for (const row of sheet.rows.slice(1)) {
    assert.match(String(row[numberIndex]), /^示例/);
    assert.equal(row.length, TRANSFER_HEADERS.length);
  }
  TRANSFER_COLUMNS.forEach((column, index) => {
    if (column.sensitive) assert.equal(sheet.rows[1][index] + sheet.rows[2][index], "", column.key);
  });
  assert.deepEqual(guide.rows[0], ["列名", "是否必填", "格式", "可填的值", "留空时", "谁可以填"]);
  const described = new Map(guide.rows.slice(1, 1 + TRANSFER_COLUMNS.length).map((row) => [row[0], row]));
  for (const column of TRANSFER_COLUMNS) {
    const row = described.get(column.label);
    assert.ok(row, `${column.label} is missing from the guide`);
    assert.ok(row[1] && row[2] && row[4] && row[5], `${column.label} guide row is incomplete`);
    if (column.sensitive) assert.match(row[5], /敏感信息权限/);
  }
  assert.equal(described.get("员工号")[1], "必填");
  assert.match(described.get("所属单位")[1], /新增必填/);
  assert.match(described.get("工资")[4], /保持原值/);
  assert.match(JSON.stringify(guide.rows), /300/);
  assert.match(JSON.stringify(guide.rows), /预览/);
  // the examples themselves parse (and are then blocked by the server because of 示例)
  const parsed = parseEmployeeTableRows(sheet.rows);
  assert.equal(parsed.dataRows, 2);
  assert.equal(parsed.rows[0].employee_number, "示例001");
  assert.equal(parsed.rows[0].probation_months, "3");
});

// ---------- 单元格 / 日期 ----------
test("dates: Excel serials, common spellings and invalid dates", () => {
  assert.equal(excelSerialToIso(serialOf(2026, 1, 5)), "2026-01-05");
  assert.equal(excelSerialToIso(serialOf(2024, 2, 29)), "2024-02-29");
  assert.equal(excelSerialToIso(serialOf(2026, 12, 31) + 0.6), "2026-12-31");
  assert.equal(excelSerialToIso(0), "");
  assert.equal(excelSerialToIso("abc"), "");
  for (const text of ["2026-01-05", "2026/1/5", "2026.01.05", "2026年1月5日", "20260105", "2026-01-05 00:00:00", "2026-01-05T08:30:00", " 2026-01-05 "]) {
    assert.equal(normalizeDateText(text), "2026-01-05", text);
  }
  assert.equal(normalizeDateText("2026-13-45"), "2026-13-45", "left for the server to report");
  assert.equal(normalizeDateText("2026-02-30"), "2026-02-30");
  assert.equal(normalizeDateText("下个月"), "下个月");
  const dateColumn = TRANSFER_COLUMNS.find((column) => column.key === "date_of_joining");
  assert.equal(convertCell(serialOf(2026, 3, 9), dateColumn).text, "2026-03-09");
  assert.equal(convertCell("2026/3/9", dateColumn).text, "2026-03-09");
  assert.equal(convertCell(20260309, dateColumn).text, "2026-03-09", "yyyymmdd typed as a number");
  assert.equal(convertCell(new Date(2026, 2, 9), dateColumn).text, "2026-03-09");
});

test("text cells: numbers never turn into scientific notation, leading zeros survive, long numbers are flagged", () => {
  const phone = TRANSFER_COLUMNS.find((column) => column.key === "cell_number");
  const bank = TRANSFER_COLUMNS.find((column) => column.key === "bank_ac_no");
  const salary = TRANSFER_COLUMNS.find((column) => column.key === "default_monthly_salary");
  assert.equal(numberToText(13800000001), "13800000001");
  assert.equal(numberToText(123456789012345), "123456789012345");
  assert.equal(numberToText(12000.5), "12000.5");
  assert.equal(numberToText(0.1 + 0.2), "0.3");
  assert.equal(numberToText(NaN), "");
  assert.deepEqual(convertCell(13800000001, phone), { text: "13800000001" });
  assert.deepEqual(convertCell("0012345", bank), { text: "0012345" });
  assert.deepEqual(convertCell("  6222 0000  ", bank), { text: "6222 0000" });
  assert.deepEqual(convertCell(" A001​", phone), { text: "A001" });
  const long = convertCell(6222000011112222333, bank);
  assert.match(long.problem, /银行卡号是数字格式且超过 15 位/);
  assert.deepEqual(convertCell(12000.5, salary), { text: "12000.5" });
  assert.deepEqual(convertCell("", salary), { text: "" });
  assert.deepEqual(convertCell(null, salary), { text: "" });
  assert.deepEqual(convertCell("¥1,200", salary), { text: "¥1,200" }, "money text is parsed by the server");
});

test("parsing: reordered columns, unknown columns, blank rows, row numbers and blank cells", () => {
  const table = [
    [],
    ["人员花名册（2026-10）"],
    ["姓名", "*员工号", "多余的列", "入职时间", "手机号", "所属单位", "部门"],
    ["南通工厂9", "A001", "x", serialOf(2026, 1, 5), 13800000001, "栖衡科技", "研发软件部"],
    ["", "", "", "", "", "", ""],
    ["演示员工146", "007", "", "2026/2/3", "", "示例研发中心", ""],
  ];
  const parsed = parseEmployeeTableRows(table);
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.headerRow, 3);
  assert.deepEqual(parsed.unknownHeaders, ["多余的列"]);
  assert.equal(parsed.dataRows, 2);
  assert.deepEqual(parsed.rows, [
    { _row: 4, employee_name: "南通工厂9", employee_number: "A001", date_of_joining: "2026-01-05", cell_number: "13800000001", company: "栖衡科技", department: "研发软件部" },
    { _row: 6, employee_name: "演示员工146", employee_number: "007", date_of_joining: "2026-02-03", company: "示例研发中心" },
  ]);
  assert.deepEqual(parsed.problems, []);
});

test("parsing: file-level errors (no header, header only, over 300 rows)", () => {
  assert.match(parseEmployeeTableRows([["a", "b"], [1, 2]]).errors[0], /没有找到表头/);
  assert.match(parseEmployeeTableRows([]).errors[0], /没有找到表头/);
  assert.deepEqual(parseEmployeeTableRows([["员工号", "姓名"]]).errors, ["表里只有表头，没有数据行。"]);
  const many = [["员工号", "姓名"], ...Array.from({ length: 301 }, (_, index) => [`N${index}`, `员工${index}`])];
  const tooMany = parseEmployeeTableRows(many);
  assert.equal(tooMany.dataRows, 301);
  assert.match(tooMany.errors[0], /301 行.*最多导入 300 行/);
  assert.deepEqual(tooMany.rows, []);
  const exactly = parseEmployeeTableRows([many[0], ...many.slice(1, 301)]);
  assert.deepEqual(exactly.errors, []);
  assert.equal(exactly.rows.length, 300);
});

test("parsing: a long number typed as a number is reported against its row", () => {
  const parsed = parseEmployeeTableRows([["员工号", "身份证号"], ["A001", 110101199001010090], ["A002", "110101199001010090"]]);
  assert.deepEqual(parsed.problems.map((item) => item.row), [2]);
  assert.match(parsed.problems[0].messages[0], /身份证号/);
  assert.equal(parsed.rows[1].id_card_number_cn, "110101199001010090");
});

// ---------- 预览 ----------
const previewRow = (row, status, extra = {}) => ({ row, status, employee_number: `N${row}`, employee_name: `员工${row}`, name: "", errors: [], warnings: [], changes: [], labels: [], ...extra });

test("preview summary counts, problem list (first 20 then more), update changes and confirm rules", () => {
  const rows = [
    ...Array.from({ length: 25 }, (_, index) => previewRow(index + 2, "error", { errors: [`问题${index}`] })),
    previewRow(30, "create"), previewRow(31, "create"),
    previewRow(32, "update", { changes: [{ field: "designation", label: "职位", old: "工程师", new: "财务主管", sensitive: false }] }),
    previewRow(33, "unchanged"),
  ];
  const preview = buildImportPreview({ unknownHeaders: ["多余"] }, { summary: {}, rows });
  assert.equal(preview.total, 29);
  assert.equal(preview.create, 2);
  assert.equal(preview.update, 1);
  assert.equal(preview.unchanged, 1);
  assert.equal(preview.error, 25);
  assert.equal(preview.problemsShown.length, PREVIEW_LIST_LIMIT);
  assert.equal(PREVIEW_LIST_LIMIT, 20);
  assert.equal(preview.problemsMore, 5);
  assert.equal(preview.canConfirm, false);
  assert.deepEqual(preview.unknownHeaders, ["多余"]);
  assert.equal(describeChange(preview.updates[0].changes[0]), "职位：工程师 → 财务主管");

  const clean = buildImportPreview({}, { rows: rows.slice(25) });
  assert.equal(clean.error, 0);
  assert.equal(clean.canConfirm, true);
  assert.equal(clean.problemsMore, 0);

  assert.equal(buildImportPreview({}, { rows: [previewRow(2, "unchanged")] }).canConfirm, false, "nothing to import");
  assert.equal(buildImportPreview({}, { rows: [] }).canConfirm, false);
  assert.equal(buildImportPreview({}, {}).total, 0);
});

test("preview: sensitive changes stay masked even if a masked value were missing, warnings are collected, local problems turn a row into an error", () => {
  const rows = [
    previewRow(2, "update", { changes: [{ field: "default_monthly_salary", label: "工资", old: "10000", new: "12000", sensitive: true }] }),
    previewRow(3, "update", { changes: [{ field: "default_monthly_salary", label: "工资", old: "（空）", new: "••••••", sensitive: true }], warnings: ["当前账号没有敏感信息权限，已忽略这些列：工资。"] }),
    previewRow(4, "create"),
  ];
  const preview = buildImportPreview({ problems: [{ row: 4, messages: ["身份证号是数字格式且超过 15 位"] }] }, { summary: { sensitive_ignored: true }, rows });
  assert.equal(describeChange(rows[0].changes[0]), "工资：•••••• → ••••••");
  assert.equal(describeChange(rows[1].changes[0]), "工资：（空） → ••••••");
  assert.equal(preview.sensitiveIgnored, true);
  assert.equal(preview.warningRows, 1);
  assert.equal(preview.error, 1);
  assert.equal(preview.create, 0);
  assert.equal(preview.problems[0].errors[0], "身份证号是数字格式且超过 15 位");
  assert.equal(preview.canConfirm, false);
  for (const text of JSON.stringify(preview).match(/1[02]000/g) || []) assert.fail(`unmasked value leaked into the preview: ${text}`);
});

test("import result note", () => {
  assert.equal(importResultText({ created: 3, updated: 2, unchanged: 1 }), "已新增 3 人、更新 2 人");
  assert.equal(importResultText({}), "已新增 0 人、更新 0 人");
});

test("only roles that can save employees see the import button", () => {
  assert.equal(canImportEmployees(["HR User"]), true);
  assert.equal(canImportEmployees(["System Manager"]), true);
  assert.equal(canImportEmployees(["HR Manager", "Employee"]), true);
  assert.equal(canImportEmployees(["Accounts User", "Employee"]), false);
  assert.equal(canImportEmployees([]), false);
  assert.equal(canImportEmployees(undefined), false);
  assert.match(backend, /RD_HR_WRITE = \("System Manager", "HR User", "HR Manager"\)/);
});

// ---------- 导出 ----------
const sampleRow = (extra = {}) => ({
  name: "HR-EMP-90001", company: "QIHENG Demo", employee_number: "007", employee_name: "南通工厂9", english_name: "Zhang San", gender: "Male",
  date_of_birth: "1995-01-15", cell_number: "13800000001", household_registration: "深圳", date_of_joining: "2026-01-05", relieving_date: null,
  department: "研发软件部 - RAY", designation: "工程师", reports_to: "HR-EMP-90009", employment_type: "劳动合同", rd_personnel_type: "全时研发",
  expense_account_category: "研发费用", archive_status: "待完善", probation_months: 3, first_contract_period_years: 0, status: "Active",
  default_monthly_salary: 12000.5, salary_months: 13, default_social_insurance_base: 0, default_housing_fund_base: 8000, social_insurance_number: "0012345",
  housing_fund_number: null, id_type_cn: "身份证", id_card_number_cn: "110101199001010090", bank_name: "招商银行", bank_ac_no: "0622000011112222",
  ...extra,
});

test("export columns: non-sensitive by default, sensitive only when ticked, offered and actually returned", () => {
  const rows = [sampleRow()];
  const plain = exportColumns({ rows });
  assert.deepEqual(plain.map((column) => column.label), TRANSFER_COLUMNS.filter((column) => !column.sensitive).map((column) => column.label));
  assert.ok(plain.every((column) => !column.sensitive));
  const withSensitive = exportColumns({ rows, includeSensitive: true });
  assert.deepEqual(withSensitive.map((column) => column.label), TRANSFER_HEADERS);
  // a masked account must never get the sensitive columns, even if ticked
  assert.equal(exportColumns({ rows, includeSensitive: true, sensitiveHidden: true }).length, plain.length);
  // fields the API did not return are not exported
  const partial = { ...sampleRow() };
  for (const key of ["default_social_insurance_base", "default_housing_fund_base", "social_insurance_number", "housing_fund_number"]) delete partial[key];
  const partialLabels = exportColumns({ rows: [partial], includeSensitive: true }).map((column) => column.label);
  assert.ok(partialLabels.includes("工资") && partialLabels.includes("银行卡号"));
  assert.ok(!partialLabels.includes("社保基数") && !partialLabels.includes("公积金账号"));
  // same headers as the template, so an export can be edited and imported again
  for (const column of plain) assert.equal(headerField(column.label), column.key);
});

test("sensitive checkbox is offered only with page access and returned sensitive fields", () => {
  assert.equal(canOfferSensitiveExport({ sensitiveHidden: false, rows: [sampleRow()] }), true);
  assert.equal(canOfferSensitiveExport({ sensitiveHidden: true, rows: [sampleRow()] }), false);
  const stripped = sampleRow();
  for (const key of SENSITIVE_KEYS) delete stripped[key];
  assert.equal(canOfferSensitiveExport({ sensitiveHidden: false, rows: [stripped] }), false);
  assert.equal(canOfferSensitiveExport({ sensitiveHidden: false, rows: [] }), false);
  assert.deepEqual(availableSensitiveKeys([stripped]), []);
  assert.equal(availableSensitiveKeys([sampleRow()]).length, SENSITIVE_KEYS.length);
});

test("export file name and the 含敏感信息 marker", () => {
  assert.equal(employeeExportFilename("2026-10-08"), "员工信息_2026-10-08.xlsx");
  assert.equal(employeeExportFilename("2026-10-08", true), "员工信息_2026-10-08_含敏感信息.xlsx");
  assert.equal(employeeExportFilename("2026-10-08", false), "员工信息_2026-10-08.xlsx");
});

test("export cells: ids and bank numbers are text, zeros are blank, names are shown the way the import reads them", () => {
  const byKey = (key) => TRANSFER_COLUMNS.find((column) => column.key === key);
  const row = sampleRow();
  const nameById = new Map([["HR-EMP-90009", "王主管"]]);
  const cell = (key) => exportCellValue(byKey(key), row, { nameById });
  assert.equal(cell("employee_number"), "007");
  assert.equal(typeof cell("employee_number"), "string");
  assert.equal(cell("bank_ac_no"), "0622000011112222");
  assert.equal(typeof cell("id_card_number_cn"), "string");
  assert.equal(cell("cell_number"), "13800000001");
  assert.equal(cell("company"), "栖衡科技");
  assert.equal(cell("gender"), "男");
  assert.equal(cell("department"), "研发软件部");
  assert.equal(cell("reports_to"), "王主管");
  assert.equal(exportCellValue(byKey("reports_to"), { reports_to: "HR-EMP-77" }, { nameById }), "HR-EMP-77");
  assert.equal(cell("default_monthly_salary"), 12000.5);
  assert.equal(cell("default_social_insurance_base"), "", "0 means not set");
  assert.equal(cell("first_contract_period_years"), "");
  assert.equal(cell("probation_months"), 3);
  assert.equal(cell("relieving_date"), "");
  assert.equal(cell("housing_fund_number"), "");
  assert.equal(cell("date_of_joining"), "2026-01-05");
  assert.equal(exportCellValue(byKey("date_of_joining"), { date_of_joining: "2026-01-05 10:11:12.123" }), "2026-01-05");
  assert.equal(exportCellValue(byKey("gender"), { gender: "Female" }), "女");
});

test("export rows: current filter ignores paging; all-active ignores department filters but honours the company filter", () => {
  const item = (name, company, left) => ({ row: { name, company }, left });
  const all = [item("a", "QIHENG Demo", false), item("b", "QIHENG Demo", true), item("c", "示例研发中心", false), item("d", "QIHENG Demo", false)];
  const filtered = [all[0], all[1]];
  assert.deepEqual(pickExportRows("current", { filtered, all, company: "" }).map((row) => row.name), ["a", "b"]);
  assert.deepEqual(pickExportRows("active", { filtered, all, company: "" }).map((row) => row.name), ["a", "c", "d"]);
  assert.deepEqual(pickExportRows("active", { filtered, all, company: "QIHENG Demo" }).map((row) => row.name), ["a", "d"]);
  assert.deepEqual(pickExportRows("active", { filtered, all, company: "示例研发中心" }).map((row) => row.name), ["c"]);
  assert.deepEqual(pickExportRows("current", {}), []);
});

test("export sheet shape: header row, one row per person, widths per column", () => {
  const sheet = buildEmployeeExportSheet({ rows: [sampleRow(), sampleRow({ employee_number: "008" })], nameById: new Map([["HR-EMP-90009", "王主管"]]) });
  assert.equal(sheet.name, TEMPLATE_SHEET);
  assert.equal(sheet.rows.length, 3);
  assert.deepEqual(sheet.rows[0], exportColumns({ rows: [sampleRow()] }).map((column) => column.label));
  assert.equal(sheet.widths.length, sheet.rows[0].length);
  assert.ok(!sheet.rows[0].includes("工资"));
  const sensitive = buildEmployeeExportSheet({ rows: [sampleRow()], includeSensitive: true });
  assert.ok(sensitive.rows[0].includes("工资") && sensitive.rows[0].includes("身份证号"));
});

// ---------- 真正的 xlsx 往返 ----------
test("a real xlsx round trip keeps ids and bank numbers as text cells and re-imports them unchanged", async () => {
  const XLSX = await loadXlsx();
  const sheet = buildEmployeeExportSheet({ rows: [sampleRow()], includeSensitive: true, nameById: new Map([["HR-EMP-90009", "王主管"]]) });
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(sheet.rows), sheet.name);
  const data = XLSX.write(workbook, { type: "array", bookType: "xlsx" });

  const written = XLSX.read(data, { type: "array" }).Sheets[TEMPLATE_SHEET];
  const columnIndex = (label) => sheet.rows[0].indexOf(label);
  const cellAt = (label) => written[XLSX.utils.encode_cell({ r: 1, c: columnIndex(label) })];
  for (const label of ["员工号", "银行卡号", "身份证号", "联系电话", "社保电脑号"]) {
    assert.equal(cellAt(label).t, "s", `${label} must be a text cell`);
  }
  assert.equal(cellAt("银行卡号").v, "0622000011112222");
  assert.equal(cellAt("员工号").v, "007");
  assert.equal(cellAt("工资").t, "n");

  const parsed = readEmployeeWorkbook(XLSX, data);
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.rows.length, 1);
  assert.equal(parsed.rows[0].employee_number, "007");
  assert.equal(parsed.rows[0].bank_ac_no, "0622000011112222");
  assert.equal(parsed.rows[0].id_card_number_cn, "110101199001010090");
  assert.equal(parsed.rows[0].company, "栖衡科技");
  assert.equal(parsed.rows[0].department, "研发软件部");
  assert.equal(parsed.rows[0].reports_to, "王主管");
  assert.equal(parsed.rows[0].default_monthly_salary, "12000.5");
  assert.equal(parsed.rows[0].gender, "男");
  assert.equal(parsed.rows[0].date_of_joining, "2026-01-05");
  assert.equal(parsed.rows[0].relieving_date, undefined);
  assert.deepEqual(parsed.problems, []);
});

test("the downloaded template workbook is read back from its 员工信息 sheet and the 填写说明 sheet is skipped", async () => {
  const XLSX = await loadXlsx();
  const workbook = XLSX.utils.book_new();
  // guide first on purpose: the importer must still pick the data sheet
  const [data, guide] = buildEmployeeTemplateSheets();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(guide.rows), guide.name);
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(data.rows), data.name);
  const parsed = readEmployeeWorkbook(XLSX, XLSX.write(workbook, { type: "array", bookType: "xlsx" }));
  assert.equal(parsed.sheetName, TEMPLATE_SHEET);
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.dataRows, 2);
  assert.deepEqual(parsed.rows.map((row) => row._row), [2, 3]);
  assert.deepEqual(parsed.unknownHeaders, []);
});

test("a real date cell and a numeric phone cell are read the way the page expects", async () => {
  const XLSX = await loadXlsx();
  const sheet = XLSX.utils.aoa_to_sheet([["员工号", "入职日期", "联系电话", "银行卡号"], ["A001", "x", 13800000001, "0001"]]);
  sheet.B2 = { t: "n", v: serialOf(2026, 10, 1), z: "yyyy-mm-dd" };
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "Sheet1");
  const parsed = readEmployeeWorkbook(XLSX, XLSX.write(workbook, { type: "array", bookType: "xlsx", cellStyles: true }));
  assert.deepEqual(parsed.errors, []);
  assert.equal(parsed.sheetName, "Sheet1");
  assert.deepEqual(parsed.rows[0], { _row: 2, employee_number: "A001", date_of_joining: "2026-10-01", cell_number: "13800000001", bank_ac_no: "0001" });
});

test("a workbook without an employee header is reported, not guessed", async () => {
  const XLSX = await loadXlsx();
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet([["凭证号", "金额"], ["V1", 100]]), "费用明细");
  const parsed = readEmployeeWorkbook(XLSX, XLSX.write(workbook, { type: "array", bookType: "xlsx" }));
  assert.match(parsed.errors[0], /没有找到表头/);
  assert.deepEqual(parsed.rows, []);
});
