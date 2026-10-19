// 员工信息的 Excel 导入 / 导出：列定义、表头识别、单元格整理、导入模板、预览汇总、导出内容。
// 纯逻辑，不碰网络和 window；页面（pages/Personnel.vue）负责取数、弹预览、调后端。
// 列的字段名 / 表头 / 是否敏感要和后端 api/personnel_entry.py 的 IMPORT_COLUMNS 一一对应（tests/personnel-transfer.test.js 对照过）。
import { displayCompany, displayDepartment } from "./displayBrand.js";

export const IMPORT_MAX_ROWS = 300;
export const TEMPLATE_SHEET = "员工信息";
export const GUIDE_SHEET = "填写说明";
export const SENSITIVE_EXPORT_LABEL = "包含薪资、证件、银行卡、社保公积金号等敏感信息";
export const EXAMPLE_PREFIX = "示例";

const ALL_HR = "人事账号都可以填";
const SENSITIVE_WHO = "只有有敏感信息权限的账号才生效；受限账号上传时这一列会被忽略（预览里有提示）";
const KEEP = "留空 = 保持原值，不会清空";

// kind: text | date | company | gender | household | department | designation | supervisor | employment_type | rd_type | expense | archive | money | months | int | float
// examples: [示例行 1, 示例行 2]；敏感列不放示例。
export const TRANSFER_COLUMNS = [
  { key: "company", label: "所属单位", kind: "company", width: 12, aliases: ["所属公司", "公司"], required: "新增必填", format: "文本", values: "示例总部、示例研发中心", blank: "已有员工可留空；填了必须和系统里一致", examples: ["示例总部", "示例研发中心"] },
  { key: "employee_number", label: "员工号", kind: "text", width: 12, aliases: ["工号", "员工编号"], required: "必填", format: "文本，按文本填写（保留前导 0）", values: "同一单位内不重复", blank: "不能留空：导入靠员工号判断是新增还是更新", examples: ["示例001", "示例002"] },
  { key: "employee_name", label: "姓名", kind: "text", width: 12, aliases: ["员工姓名"], required: "新增必填", format: "文本", values: "在职员工不能重名，重名请加区分如“演示员工130(研发)”", blank: KEEP, examples: ["示例员工甲", "示例员工乙"] },
  { key: "english_name", label: "英文名", kind: "text", width: 14, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["Demo A", ""] },
  { key: "gender", label: "性别", kind: "gender", width: 8, aliases: [], required: "选填", format: "文本", values: "男、女", blank: "新增时留空按“男”；已有员工保持原值", examples: ["男", "女"] },
  { key: "date_of_birth", label: "出生日期", kind: "date", width: 13, aliases: ["生日"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: "新增时留空且没填身份证号，按 1990-01-01；已有员工保持原值", examples: ["1995-01-15", ""] },
  { key: "cell_number", label: "联系电话", kind: "text", width: 14, aliases: ["手机号", "手机", "电话", "联系方式"], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["13800000001", ""] },
  { key: "household_registration", label: "户口信息", kind: "household", width: 16, aliases: ["户口", "户籍", "户籍信息"], required: "选填", format: "文本", values: "深圳、广东省内城镇、广东省内农村、广东省外城镇、广东省外农村，或明确的户籍地（如“湖北省襄阳市”）；无法判断深户/非深户的不接受", blank: KEEP, examples: ["深圳", ""] },
  { key: "date_of_joining", label: "入职日期", kind: "date", width: 13, aliases: ["入职时间", "入职日"], required: "新增必填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: KEEP, examples: ["2026-01-05", "2026-02-10"] },
  { key: "relieving_date", label: "离职日期", kind: "date", width: 13, aliases: ["离职时间", "离职日"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "离职日当天仍算在职，第二天起算已离职", blank: "留空不会取消离职；要恢复在职请在页面里编辑", examples: ["", ""] },
  { key: "department", label: "部门", kind: "department", width: 14, aliases: ["所属部门"], required: "选填", format: "文本", values: "该单位下已有的标准部门名，如“研发软件部”“财务部”", blank: KEEP, examples: ["研发软件部", "财务部"] },
  { key: "designation", label: "职位", kind: "designation", width: 14, aliases: ["岗位", "职务"], required: "选填", format: "文本", values: "系统「职位」列表里已有的名称", blank: KEEP, examples: ["工程师", ""] },
  { key: "reports_to", label: "直属主管", kind: "supervisor", width: 14, aliases: ["主管", "上级", "直属上级"], required: "选填", format: "文本", values: "主管的员工号，或在职主管的姓名；主管要先在系统里存在", blank: KEEP, examples: ["", ""] },
  { key: "employment_type", label: "合同类型", kind: "employment_type", width: 12, aliases: ["用工类型", "劳动合同类型"], required: "选填", format: "文本", values: "系统「合同类型」列表里已有的名称，如“劳动合同”", blank: KEEP, examples: ["劳动合同", ""] },
  { key: "rd_personnel_type", label: "研发人员类型", kind: "rd_type", width: 14, aliases: ["研发类型"], required: "选填", format: "文本", values: "全时研发、非全时研发、研发辅助、非研发", blank: KEEP, examples: ["全时研发", ""] },
  { key: "expense_account_category", label: "费用科目", kind: "expense", width: 12, aliases: ["费用科目类别"], required: "选填", format: "文本", values: "研发费用、管理费用、销售费用、生产成本", blank: KEEP, examples: ["研发费用", ""] },
  { key: "archive_status", label: "归档状态", kind: "archive", width: 12, aliases: ["档案状态"], required: "选填", format: "文本", values: "待完善、待确认、已归档（已归档要求身份证号至少 15 位、有入职日期和部门）", blank: KEEP, examples: ["待完善", ""] },
  { key: "labour_contract_start_date", label: "劳动合同开始日期", kind: "date", width: 18, aliases: ["合同开始日期", "劳动合同开始时间"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: KEEP, examples: ["2026-01-05", ""] },
  { key: "probation_months", label: "试用期（月）", kind: "int", width: 12, aliases: ["试用期", "试用期月数"], required: "选填", format: "非负整数", values: "", blank: KEEP, examples: [3, ""] },
  { key: "probation_end_date", label: "试用期到期日", kind: "date", width: 14, aliases: ["试用期到期", "试用期结束日期"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: KEEP, examples: ["2026-04-04", ""] },
  { key: "first_contract_period_years", label: "第一次合同期限（年）", kind: "float", width: 20, aliases: ["第一次合同期限"], required: "选填", format: "非负数字，如 3 或 1.5", values: "", blank: KEEP, examples: [3, ""] },
  { key: "first_contract_end_date", label: "第一次劳动合同到期日", kind: "date", width: 20, aliases: ["第一次合同到期日"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: KEEP, examples: ["2029-01-04", ""] },
  { key: "contract_renewal_status", label: "劳动合同续签情况", kind: "text", width: 18, aliases: ["续签情况"], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "second_contract_period_years", label: "第二次合同期限（年）", kind: "float", width: 20, aliases: ["第二次合同期限"], required: "选填", format: "非负数字", values: "", blank: KEEP, examples: ["", ""] },
  { key: "second_contract_end_date", label: "第二次劳动合同到期日", kind: "date", width: 20, aliases: ["第二次合同到期日"], required: "选填", format: "YYYY-MM-DD，或 Excel 日期格式", values: "", blank: KEEP, examples: ["", ""] },
  { key: "first_education_level", label: "第一学历", kind: "text", width: 12, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["本科", ""] },
  { key: "first_education_school", label: "第一学历学校", kind: "text", width: 16, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["示例大学", ""] },
  { key: "first_education_major", label: "第一学历专业", kind: "text", width: 16, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "education_level_cn", label: "最高学历", kind: "text", width: 12, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["本科", ""] },
  { key: "degree_cn", label: "学位", kind: "text", width: 10, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "education_completion_type", label: "学历完成形式", kind: "text", width: 14, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "graduation_school", label: "最高学历学校", kind: "text", width: 16, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["示例大学", ""] },
  { key: "major_cn", label: "最高学历专业", kind: "text", width: 16, aliases: [], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "default_monthly_salary", label: "工资", kind: "money", sensitive: true, width: 12, aliases: ["默认月基本工资", "基本工资", "月工资"], required: "选填", format: "非负数字，可带千分位", values: "", blank: KEEP, examples: ["", ""] },
  { key: "salary_months", label: "薪资月数", kind: "months", sensitive: true, width: 10, aliases: ["几薪"], required: "选填", format: "非负整数，如 12、13", values: "", blank: KEEP, examples: ["", ""] },
  { key: "default_social_insurance_base", label: "社保基数", kind: "money", sensitive: true, width: 12, aliases: [], required: "选填", format: "非负数字", values: "", blank: KEEP, examples: ["", ""] },
  { key: "default_housing_fund_base", label: "公积金基数", kind: "money", sensitive: true, width: 12, aliases: [], required: "选填", format: "非负数字", values: "", blank: KEEP, examples: ["", ""] },
  { key: "social_insurance_number", label: "社保电脑号", kind: "text", sensitive: true, width: 16, aliases: ["社保号"], required: "选填", format: "文本（整列设为文本格式，保留前导 0）", values: "", blank: KEEP, examples: ["", ""] },
  { key: "housing_fund_number", label: "公积金账号", kind: "text", sensitive: true, width: 16, aliases: ["公积金号"], required: "选填", format: "文本（整列设为文本格式，保留前导 0）", values: "", blank: KEEP, examples: ["", ""] },
  { key: "id_type_cn", label: "证件类型", kind: "text", sensitive: true, width: 10, aliases: [], required: "选填", format: "文本", values: "如“身份证”", blank: KEEP, examples: ["", ""] },
  { key: "id_card_number_cn", label: "身份证号", kind: "text", sensitive: true, width: 20, aliases: ["身份证号码", "证件号码", "身份证"], required: "选填", format: "文本（整列设为文本格式；数字格式的 18 位号码 Excel 会丢失后几位）", values: "", blank: KEEP, examples: ["", ""] },
  { key: "bank_name", label: "开户行", kind: "text", sensitive: true, width: 22, aliases: ["工资卡银行开户行及支行", "开户银行", "银行"], required: "选填", format: "文本", values: "", blank: KEEP, examples: ["", ""] },
  { key: "bank_ac_no", label: "银行卡号", kind: "text", sensitive: true, width: 22, aliases: ["工资卡银行账号", "银行账号", "银行卡号码"], required: "选填", format: "文本（整列设为文本格式，保留前导 0）", values: "", blank: KEEP, examples: ["", ""] },
];

export const TRANSFER_HEADERS = TRANSFER_COLUMNS.map((column) => column.label);
export const SENSITIVE_KEYS = TRANSFER_COLUMNS.filter((column) => column.sensitive).map((column) => column.key);
const COLUMN_BY_KEY = new Map(TRANSFER_COLUMNS.map((column) => [column.key, column]));
const NUMBER_KINDS = new Set(["money", "months", "int", "float"]);

// 导入按钮只给能保存员工的角色（和后端 save_employee 的 RD_HR_WRITE 一致）
export const IMPORT_ROLES = ["System Manager", "HR User", "HR Manager"];
export function canImportEmployees(roles) {
  return Array.isArray(roles) && roles.some((role) => IMPORT_ROLES.includes(role));
}

// ---------- 表头识别 ----------
function aliasKey(value) {
  return String(value ?? "")
    .replace(/[\s_\-:：|｜()（）*＊。.]/g, "")
    .toLowerCase();
}

const HEADER_LOOKUP = (() => {
  const lookup = new Map();
  for (const column of TRANSFER_COLUMNS) {
    for (const name of [column.label, column.key, ...column.aliases]) {
      const key = aliasKey(name);
      if (key && !lookup.has(key)) lookup.set(key, column.key);
    }
  }
  return lookup;
})();

export function headerField(value) {
  return HEADER_LOOKUP.get(aliasKey(value)) || "";
}

// 认得出表头（至少有“员工号”列，且认得 2 列以上）就返回 { 字段名: 列位置 }，否则 null。模板的表头行也走这里。
export function detectEmployeeHeader(cells = []) {
  const map = {};
  Array.from(cells || []).forEach((cell, index) => {
    const field = headerField(cell);
    if (field && map[field] === undefined) map[field] = index;
  });
  return map.employee_number !== undefined && Object.keys(map).length >= 2 ? map : null;
}

// ---------- 单元格整理 ----------
const isBlankCell = (value) => value === null || value === undefined || String(value).trim() === "";

function cleanText(value) {
  return String(value ?? "").replace(/[ ​﻿]/g, " ").trim();
}

function pad2(value) {
  return String(value).padStart(2, "0");
}

function validIso(year, month, day) {
  const time = Date.UTC(year, month - 1, day);
  const check = new Date(time);
  if (year < 1000 || check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return "";
  return `${String(year).padStart(4, "0")}-${pad2(month)}-${pad2(day)}`;
}

// Excel 日期序列号 -> YYYY-MM-DD（1900 日期系统）
export function excelSerialToIso(serial) {
  const number = Number(serial);
  if (!Number.isFinite(number) || number < 1 || number >= 2958466) return "";
  const date = new Date(Date.UTC(1899, 11, 30) + Math.floor(number) * 86400000);
  return `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`;
}

// 常见写法 -> YYYY-MM-DD；认不出来原样返回，由后端报“日期格式不对”
export function normalizeDateText(value) {
  const text = cleanText(value);
  const match = /^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?$/.exec(text)
    || /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (!match) return text;
  return validIso(Number(match[1]), Number(match[2]), Number(match[3])) || text;
}

// 数字 -> 不带科学计数法的文本（电话、员工号、各种号码被 Excel 存成数字时用）
export function numberToText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  if (Number.isInteger(number)) return Math.abs(number) < 1e21 ? String(number) : number.toLocaleString("en-US", { useGrouping: false });
  return String(Number(number.toFixed(10)));
}

// 一个单元格 -> 要发给后端的文本；problem 是导入前就能确定的问题
export function convertCell(value, column) {
  if (isBlankCell(value) || typeof value === "boolean") return { text: "" };
  if (value instanceof Date) {
    return { text: Number.isNaN(value.getTime()) ? "" : `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}` };
  }
  if (typeof value === "number") {
    if (column.kind === "date") return { text: excelSerialToIso(value) || normalizeDateText(numberToText(value)) };
    const text = numberToText(value);
    if (!NUMBER_KINDS.has(column.kind) && Math.abs(value) >= 1e15) {
      return { text, problem: `${column.label}是数字格式且超过 15 位，Excel 已经丢失了后面几位，请把这一列设为文本格式后重新填写。` };
    }
    return { text };
  }
  const text = cleanText(value);
  return { text: column.kind === "date" ? normalizeDateText(text) : text };
}

// ---------- 整张表 -> 导入行 ----------
// tableRows：sheet_to_json(header:1, raw:true) 的二维数组。返回：
// rows 发给后端的行（带 _row = Excel 行号）、problems 本地就能发现的问题 [{ row, messages }]、
// unknownHeaders 没认出来的列名、errors 整份文件的问题（有就不能继续）。
export function parseEmployeeTableRows(tableRows, { maxRows = IMPORT_MAX_ROWS } = {}) {
  const result = { rows: [], dataRows: 0, headerRow: 0, unknownHeaders: [], problems: [], errors: [] };
  let map = null;
  let seen = 0;
  (tableRows || []).forEach((inputRow, index) => {
    const cells = Array.from(inputRow || []);
    if (!cells.some((cell) => !isBlankCell(cell))) return;
    if (!map) {
      seen += 1;
      if (seen > 10) return;
      const detected = detectEmployeeHeader(cells);
      if (!detected) return;
      map = detected;
      result.headerRow = index + 1;
      result.unknownHeaders = cells
        .filter((cell) => !isBlankCell(cell) && !headerField(cell))
        .map((cell) => cleanText(cell));
      return;
    }
    result.dataRows += 1;
    const row = { _row: index + 1 };
    const messages = [];
    for (const [key, position] of Object.entries(map)) {
      const { text, problem } = convertCell(cells[position], COLUMN_BY_KEY.get(key));
      if (text) row[key] = text;
      if (problem) messages.push(problem);
    }
    if (messages.length) result.problems.push({ row: row._row, messages });
    result.rows.push(row);
  });
  if (!map) {
    result.errors.push("没有找到表头：表里需要有“员工号”等列名（建议用“下载导入模板”）。");
  } else if (!result.dataRows) {
    result.errors.push("表里只有表头，没有数据行。");
  } else if (result.dataRows > maxRows) {
    result.errors.push(`文件有 ${result.dataRows} 行数据，一次最多导入 ${maxRows} 行，请拆开分批导入。`);
    result.rows = [];
    result.problems = [];
  }
  return result;
}

// 选工作表：优先“员工信息”，其次第一张认得出表头的（跳过“填写说明”）
export function pickEmployeeSheet(workbook, utils) {
  const names = (workbook?.SheetNames || []).filter((name) => name !== GUIDE_SHEET);
  const ordered = [...names.filter((name) => name === TEMPLATE_SHEET), ...names.filter((name) => name !== TEMPLATE_SHEET)];
  for (const name of ordered) {
    const rows = utils.sheet_to_json(workbook.Sheets[name], { header: 1, raw: true, defval: "" });
    if (rows.some((row) => detectEmployeeHeader(Array.from(row || [])))) return { name, rows };
  }
  const first = ordered[0];
  return { name: first || "", rows: first ? utils.sheet_to_json(workbook.Sheets[first], { header: 1, raw: true, defval: "" }) : [] };
}

export function readEmployeeWorkbook(XLSX, data) {
  const workbook = XLSX.read(data, { type: "array" });
  if (!workbook.SheetNames?.length) return { rows: [], dataRows: 0, headerRow: 0, unknownHeaders: [], problems: [], errors: ["Excel 文件里没有工作表。"] };
  const sheet = pickEmployeeSheet(workbook, XLSX.utils);
  return { ...parseEmployeeTableRows(sheet.rows), sheetName: sheet.name };
}

export async function importEmployeeWorkbookFile(file) {
  const XLSX = await import("xlsx");
  return readEmployeeWorkbook(XLSX, await file.arrayBuffer());
}

// ---------- 预览汇总 ----------
export const PREVIEW_LIST_LIMIT = 20;

// 服务端已经把敏感字段的新旧值遮成 ••••••；这里再兜一层，敏感字段的值永远不会进到页面里
function maskChange(change) {
  if (!change?.sensitive) return change;
  const mask = (text) => (text && text !== "（空）" ? "••••••" : text || "（空）");
  return { ...change, old: mask(change.old), new: mask(change.new) };
}

export function describeChange(change) {
  const safe = maskChange(change);
  return `${safe.label}：${safe.old} → ${safe.new}`;
}

// parsed：parseEmployeeTableRows 的结果；response：preview_employee_import 的返回。
// 本地就能发现的问题（比如数字格式的长号码）并进对应行，行数统计全部按合并后的行重算。
export function buildImportPreview(parsed = {}, response = {}) {
  const local = new Map((parsed.problems || []).map((item) => [item.row, item.messages]));
  const rows = (response.rows || []).map((row) => {
    const extra = local.get(row.row) || [];
    return {
      ...row,
      status: extra.length ? "error" : row.status,
      errors: [...(row.errors || []), ...extra],
      warnings: row.warnings || [],
      changes: (row.changes || []).map(maskChange),
    };
  });
  const counts = { create: 0, update: 0, unchanged: 0, error: 0 };
  for (const row of rows) counts[row.status] = (counts[row.status] || 0) + 1;
  const problems = rows.filter((row) => row.status === "error");
  const updates = rows.filter((row) => row.status === "update");
  const warned = rows.filter((row) => row.warnings.length);
  return {
    total: rows.length,
    ...counts,
    warningRows: warned.length,
    sensitiveIgnored: Boolean(response.summary?.sensitive_ignored),
    problems,
    problemsShown: problems.slice(0, PREVIEW_LIST_LIMIT),
    problemsMore: Math.max(problems.length - PREVIEW_LIST_LIMIT, 0),
    updates,
    updatesShown: updates.slice(0, PREVIEW_LIST_LIMIT),
    updatesMore: Math.max(updates.length - PREVIEW_LIST_LIMIT, 0),
    warned,
    warnedShown: warned.slice(0, 5),
    warnedMore: Math.max(warned.length - 5, 0),
    unknownHeaders: parsed.unknownHeaders || [],
    canConfirm: rows.length > 0 && counts.error === 0 && counts.create + counts.update > 0,
  };
}

export function importResultText(result = {}) {
  return `已新增 ${Number(result.created) || 0} 人、更新 ${Number(result.updated) || 0} 人`;
}

// ---------- 导入模板 ----------
export function buildEmployeeTemplateSheets() {
  const example = (index) => TRANSFER_COLUMNS.map((column) => (column.sensitive ? "" : column.examples[index] ?? ""));
  const guide = [["列名", "是否必填", "格式", "可填的值", "留空时", "谁可以填"]];
  for (const column of TRANSFER_COLUMNS) {
    guide.push([column.label, column.required, column.format, column.values, column.blank, column.sensitive ? SENSITIVE_WHO : ALL_HR]);
  }
  guide.push(
    [],
    ["怎么匹配", "", "按“员工号”匹配：系统里已有这个员工号 → 更新这个人；没有 → 新增。已有员工号对应的所属单位必须和文件里一致。"],
    ["留空不会清空", "", "单元格留空表示“保持原值”，导入永远不会把已有内容清空。要清空某项，请在页面里编辑。"],
    ["先预览再导入", "", "选好文件后先出预览：新增、更新、无变化、有问题各几行，更新行会列出哪些字段变化。只要有一行有问题，整份都不能导入；确认后在一个事务里写入，中途出错会全部撤销。"],
    ["行数与示例", "", `一次最多 ${IMPORT_MAX_ROWS} 行。员工号以“${EXAMPLE_PREFIX}”开头的是模板里的示例行，导入时会被拦住，请删除或改成真实数据。`],
    ["日期", "", "写成 YYYY-MM-DD（如 2026-01-05），或用 Excel 的日期格式；2026/1/5、2026.1.5 也能识别。"],
    ["身份证号、银行卡号等", "", "请先把这几列的单元格格式设为“文本”再填；按数字格式填的 18 位号码，Excel 会丢失后几位，导入会拦住这样的行。"],
    ["敏感列", "", "标为敏感的列（工资、薪资月数、社保基数、公积金基数、社保电脑号、公积金账号、证件类型、身份证号、开户行、银行卡号）只有有敏感信息权限的账号才会生效；受限账号上传时这些列被忽略，预览里会提示。"],
    ["表头", "", `数据放在“${TEMPLATE_SHEET}”工作表，表头放第一行；列的顺序可以调整，表头名称不要改。没有的列可以整列删掉。`],
  );
  return [
    { name: TEMPLATE_SHEET, rows: [TRANSFER_HEADERS, example(0), example(1)], widths: TRANSFER_COLUMNS.map((column) => column.width) },
    { name: GUIDE_SHEET, rows: guide, widths: [22, 10, 34, 54, 44, 44] },
  ];
}

// ---------- 导出 ----------
// 返回这批行里实际带有的敏感字段（后端对受限账号会不返回社保公积金字段）
export function availableSensitiveKeys(rows) {
  const first = (rows || [])[0];
  if (!first || typeof first !== "object") return [];
  return SENSITIVE_KEYS.filter((key) => Object.prototype.hasOwnProperty.call(first, key));
}

// “包含敏感信息”勾选框只在页面有敏感权限、而且接口真的返回了这些字段时出现
export function canOfferSensitiveExport({ sensitiveHidden = false, rows = [] } = {}) {
  return !sensitiveHidden && availableSensitiveKeys(rows).length > 0;
}

export function exportColumns({ includeSensitive = false, sensitiveHidden = false, rows = [] } = {}) {
  const sensitive = new Set(includeSensitive && !sensitiveHidden ? availableSensitiveKeys(rows) : []);
  return TRANSFER_COLUMNS.filter((column) => !column.sensitive || sensitive.has(column.key));
}

export function exportCellValue(column, row, { nameById } = {}) {
  const value = row?.[column.key];
  if (isBlankCell(value)) return "";
  switch (column.kind) {
    case "company": return displayCompany(value);
    case "gender": return value === "Female" ? "女" : value === "Male" ? "男" : String(value);
    case "department": return displayDepartment(value);
    case "supervisor": return (nameById && nameById.get(value)) || String(value);
    case "date": return String(value).slice(0, 10);
    default:
      if (NUMBER_KINDS.has(column.kind)) {
        const number = Number(value);
        return Number.isFinite(number) && number > 0 ? number : "";
      }
      return String(value); // 员工号、电话、证件号、银行卡号一律导成文本，不会变科学计数法、不丢前导 0
  }
}

// 返回交给 exportSheetsWorkbook 的一演示员工17作表
export function buildEmployeeExportSheet({ rows = [], includeSensitive = false, sensitiveHidden = false, nameById } = {}) {
  const columns = exportColumns({ includeSensitive, sensitiveHidden, rows });
  return {
    name: TEMPLATE_SHEET,
    rows: [columns.map((column) => column.label), ...rows.map((row) => columns.map((column) => exportCellValue(column, row, { nameById })))],
    widths: columns.map((column) => column.width),
    columns,
  };
}

export function employeeExportFilename(today, includeSensitive = false) {
  return `员工信息_${today}${includeSensitive ? "_含敏感信息" : ""}.xlsx`;
}

// mode: "current" 当前筛选结果（不受分页影响）；"active" 全部在职（不看部门筛选等，只认公司筛选）
// items：decorateEmployees 的结果（{ row, left }）
export function pickExportRows(mode, { filtered = [], all = [], company = "" } = {}) {
  if (mode === "active") {
    return all.filter((item) => !item.left && (!company || item.row.company === company)).map((item) => item.row);
  }
  return filtered.map((item) => item.row);
}
