// 员工信息管理的纯逻辑：档案完整度、提醒、指标卡、筛选排序、部门分组、敏感字段遮挡。
// 页面（pages/Personnel.vue）只负责取数和展示；这里不碰网络、不碰 window，日期都以 "YYYY-MM-DD" 字符串传入。
import { displayDepartment } from "./displayBrand.js";

export const RD_TYPES = ["全时研发", "非全时研发", "研发辅助", "非研发"];
export const ARCHIVE_STATUSES = ["待完善", "待确认", "已归档"];
export const DEPARTMENT_GROUP_ORDER = ["客户运营", "研发", "运营", "职能"];
export const OTHER_GROUP = "其他";
export const EXPIRY_WINDOW_DAYS = 60;
export const NEW_EMPLOYEE_WINDOW_DAYS = 30;

// 抽屉里的五个页签。locked：含敏感信息，isHrSensitiveHidden() 时整页隐藏，其余默认遮挡。
export const PERSON_TABS = [
  { key: "basic", label: "基本信息", locked: false },
  { key: "job", label: "任职与合同", locked: false },
  { key: "edu", label: "学历", locked: false },
  { key: "pay", label: "薪酬与社保", locked: true },
  { key: "id", label: "证件与银行", locked: true },
];

// 档案完整度要求的字段。tab 对应上面的页签；kind: number 表示 0 也算没填。
export const REQUIRED_FIELDS = [
  { key: "employee_name", label: "姓名", tab: "basic" },
  { key: "employee_number", label: "员工号", tab: "basic" },
  { key: "date_of_birth", label: "出生日期", tab: "basic" },
  { key: "cell_number", label: "联系电话", tab: "basic" },
  { key: "household_registration", label: "户口信息", tab: "basic" },
  { key: "department", label: "部门", tab: "job" },
  { key: "designation", label: "职位", tab: "job" },
  { key: "reports_to", label: "直属主管", tab: "job" },
  { key: "employment_type", label: "合同类型", tab: "job" },
  { key: "labour_contract_start_date", label: "劳动合同开始日期", tab: "job" },
  { key: "rd_personnel_type", label: "研发人员类型", tab: "job" },
  { key: "education_level_cn", label: "最高学历", tab: "edu" },
  { key: "graduation_school", label: "毕业院校", tab: "edu" },
  { key: "default_monthly_salary", label: "工资", tab: "pay", kind: "number" },
  { key: "default_social_insurance_base", label: "社保基数", tab: "pay", kind: "number" },
  { key: "default_housing_fund_base", label: "公积金基数", tab: "pay", kind: "number" },
  { key: "social_insurance_number", label: "社保电脑号", tab: "pay" },
  { key: "housing_fund_number", label: "公积金账号", tab: "pay" },
  { key: "id_card_number_cn", label: "身份证号", tab: "id" },
  { key: "bank_name", label: "开户行", tab: "id" },
  { key: "bank_ac_no", label: "银行卡号", tab: "id" },
];

const LOCKED_TAB_KEYS = new Set(PERSON_TABS.filter((tab) => tab.locked).map((tab) => tab.key));

export function visibleTabs({ sensitiveHidden = false } = {}) {
  return PERSON_TABS.filter((tab) => !(sensitiveHidden && tab.locked));
}

// ---------- 日期 ----------
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

export function todayIso(now = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function dayNumber(value) {
  const match = ISO_DATE.exec(String(value || ""));
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const time = Date.UTC(year, month - 1, day);
  const check = new Date(time);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
  return Math.round(time / 86400000);
}

export function daysBetween(from, to) {
  const a = dayNumber(from);
  const b = dayNumber(to);
  return a === null || b === null ? null : b - a;
}

function monthDay(value) {
  const match = ISO_DATE.exec(String(value || ""));
  return match ? `${match[2]}-${match[3]}` : "";
}

const isBlank = (value) => value === null || value === undefined || String(value).trim() === "";

// ---------- 在职 / 离职 ----------
// 与服务端 personnel_entry._employment_status 一致：离职日当天仍在职，第二天起离职；status 为 Left 也算离职。
export function isLeft(row, today) {
  if (String(row?.status || "") === "Left") return true;
  const relieving = row?.relieving_date;
  if (!relieving) return false;
  const gap = daysBetween(today, relieving);
  return gap !== null && gap < 0;
}

export function isRdType(type) {
  return RD_TYPES.includes(type) && type !== "非研发";
}

export const RD_GROUP = "研发";

// 新增员工没选研发人员类型时，按部门分组给默认值（与服务端 personnel_entry._default_rd_type 一致）：
// 研发组 → 全时研发，其他已知分组 → 非研发，不知道分组 → 不填。已有员工不会被改。
export function defaultRdType(group) {
  if (!group || group === OTHER_GROUP) return "";
  return group === RD_GROUP ? "全时研发" : "非研发";
}

// 司龄：入职日到今天（已离职算到离职日），"3 年 7 个月" / "7 个月" / "12 天" / "今天入职"
export function seniority(row, today) {
  const start = dayNumber(row?.date_of_joining);
  if (start === null) return "";
  const endDate = isLeft(row, today) && dayNumber(row?.relieving_date) !== null ? row.relieving_date : today;
  if (dayNumber(endDate) === null) return "";
  const gap = dayNumber(endDate) - start;
  if (gap < 0) return "尚未入职";
  if (gap === 0) return isLeft(row, today) ? "当天离职" : "今天入职";
  const a = ISO_DATE.exec(row.date_of_joining);
  const b = ISO_DATE.exec(endDate);
  let months = (Number(b[1]) - Number(a[1])) * 12 + (Number(b[2]) - Number(a[2]));
  if (Number(b[3]) < Number(a[3])) months -= 1;
  if (months < 1) return `${gap} 天`;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return [years ? `${years} 年` : "", rest ? `${rest} 个月` : ""].filter(Boolean).join(" ");
}

// ---------- 档案完整度 ----------
export function requiredFields({ sensitiveHidden = false } = {}) {
  return REQUIRED_FIELDS.filter((field) => !(sensitiveHidden && LOCKED_TAB_KEYS.has(field.tab)));
}

function fieldFilled(field, row) {
  const value = row?.[field.key];
  if (field.kind === "number") return Number(value || 0) > 0;
  return !isBlank(value);
}

// sensitiveHidden 时，薪酬/社保/证件/银行页签的字段既看不到也改不了，不计入完整度
export function completeness(row, { sensitiveHidden = false } = {}) {
  const fields = requiredFields({ sensitiveHidden });
  const missing = fields.filter((field) => !fieldFilled(field, row)).map(({ key, label, tab }) => ({ key, label, tab }));
  const total = fields.length;
  const filled = total - missing.length;
  return { total, filled, pct: total ? Math.round((filled / total) * 100) : 100, missing };
}

export function missingSummary(missing, limit = 3) {
  if (!missing.length) return "资料齐全";
  const names = missing.slice(0, limit).map((item) => item.label).join("、");
  return `还缺 ${missing.length} 项：${names}${missing.length > limit ? "…" : ""}`;
}

// ---------- 提醒 ----------
const REMINDER_RANK = { left: 0, leaving: 1, probation: 2, contract: 3, rdtype: 4, missing: 5 };

// 返回按优先级排好的提醒：已离职 > 即将离职 > 试用期到期 > 合同到期 > 缺资料。
// days：距今天数（到期类提醒用，越小越紧急）。
// rdGap：在职、属于研发部门、但研发人员类型没设置——他不会出现在研发工时填报里。
export function reminders(row, today, { sensitiveHidden = false, missingCount, rdGap = false } = {}) {
  const list = [];
  if (isLeft(row, today)) {
    const day = monthDay(row?.relieving_date);
    list.push({ key: "left", text: day ? `已离职 ${day}` : "已离职", tone: "", days: null });
    return list;
  }
  const leaveGap = row?.relieving_date ? daysBetween(today, row.relieving_date) : null;
  if (leaveGap !== null && leaveGap >= 0) {
    list.push({ key: "leaving", text: `${monthDay(row.relieving_date)} 离职`, tone: "warn", days: leaveGap });
  }
  const probationGap = row?.probation_end_date ? daysBetween(today, row.probation_end_date) : null;
  if (probationGap !== null && probationGap >= 0 && probationGap <= EXPIRY_WINDOW_DAYS) {
    list.push({ key: "probation", text: `试用期 ${monthDay(row.probation_end_date)} 到期`, tone: probationGap <= 7 ? "bad" : "warn", days: probationGap });
  }
  // 第二次合同到期日晚于第一次的，第一次视为已续签，不再提醒
  const first = row?.first_contract_end_date || "";
  const second = row?.second_contract_end_date || "";
  const firstSuperseded = first && second && (daysBetween(first, second) ?? 0) > 0;
  const ends = [firstSuperseded ? "" : first, second]
    .map((date) => ({ date, gap: date ? daysBetween(today, date) : null }))
    .filter((item) => item.gap !== null && item.gap >= 0 && item.gap <= EXPIRY_WINDOW_DAYS)
    .sort((a, b) => a.gap - b.gap);
  if (ends.length) {
    list.push({ key: "contract", text: `合同 ${monthDay(ends[0].date)} 到期`, tone: ends[0].gap <= 7 ? "bad" : "warn", days: ends[0].gap });
  }
  if (rdGap) list.push({ key: "rdtype", text: "研发类型未设置，不在工时填报里", tone: "warn", days: null });
  const missing = missingCount ?? completeness(row, { sensitiveHidden }).missing.length;
  if (missing > 0) list.push({ key: "missing", text: `缺 ${missing} 项资料`, tone: "info", days: null });
  return list.sort((a, b) => REMINDER_RANK[a.key] - REMINDER_RANK[b.key]);
}

// ---------- 列表行 ----------
export function archiveStatusOf(row) {
  return ARCHIVE_STATUSES.includes(row?.archive_status) ? row.archive_status : "待完善";
}

export function archiveTone(status) {
  return status === "已归档" ? "ok" : status === "待确认" ? "warn" : "";
}

export function rdTone(type) {
  return type === "全时研发" ? "info" : type === "非研发" ? "" : type ? "ok" : "";
}

export function avatarText(name) {
  const text = String(name || "").trim();
  if (!text) return "?";
  if (/[\u4e00-\u9fff]/.test(text)) return Array.from(text).slice(-2).join("");
  const words = text.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : text.slice(0, 2)).toUpperCase();
}

// 把一行员工数据加上列表和筛选要用的派生信息
// groupOf：部门展示名 → 分组名（departmentGroupMap(get_dept_options 的结果)）；没传就不判断研发类型缺口。
export function decorateEmployee(row, { today, sensitiveHidden = false, groupOf = null } = {}) {
  const progress = completeness(row, { sensitiveHidden });
  const left = isLeft(row, today);
  const department = displayDepartment(row.department);
  const rdGap = !left && !isBlank(department) && groupOf?.get(department) === RD_GROUP && isBlank(row?.rd_personnel_type);
  const list = reminders(row, today, { sensitiveHidden, missingCount: progress.missing.length, rdGap });
  return {
    row,
    key: row.name,
    left,
    department,
    group: groupOf?.get(department) || "",
    rdGap,
    archive: archiveStatusOf(row),
    rdType: row.rd_personnel_type || "",
    progress,
    reminders: list,
    urgent: list.some((item) => item.tone === "bad"),
    joined: row.date_of_joining || "",
    seniority: seniority(row, today),
  };
}

export function decorateEmployees(rows, ctx) {
  return (rows || []).map((row) => decorateEmployee(row, ctx));
}

// ---------- 指标卡 ----------
export function kpiCounts(items, today) {
  const month = String(today || "").slice(0, 7);
  const result = {
    active: 0, rd: 0, other: 0, rdGap: 0,
    joinedThisMonth: 0, onProbation: 0,
    leftThisMonth: 0, leftEffective: 0, leftPending: 0,
    fileOpen: 0, filePending: 0, fileConfirm: 0,
    expiring: 0, expiringProbation: 0, expiringContract: 0,
  };
  for (const item of items || []) {
    const row = item.row;
    if (month && String(row.date_of_joining || "").startsWith(month)) result.joinedThisMonth += 1;
    if (month && String(row.relieving_date || "").startsWith(month)) {
      result.leftThisMonth += 1;
      if (item.left) result.leftEffective += 1; else result.leftPending += 1;
    }
    if (item.left) continue;
    result.active += 1;
    if (isRdType(item.rdType)) result.rd += 1; else result.other += 1;
    if (item.rdGap) result.rdGap += 1;
    const probationGap = row.probation_end_date ? daysBetween(today, row.probation_end_date) : null;
    if (probationGap !== null && probationGap >= 0) result.onProbation += 1;
    if (item.archive === "待完善") result.filePending += 1;
    if (item.archive === "待确认") result.fileConfirm += 1;
    if (item.archive !== "已归档") result.fileOpen += 1;
    const hasProbation = item.reminders.some((reminder) => reminder.key === "probation");
    const hasContract = item.reminders.some((reminder) => reminder.key === "contract");
    if (hasProbation) result.expiringProbation += 1;
    if (hasContract) result.expiringContract += 1;
    if (hasProbation || hasContract) result.expiring += 1;
  }
  return result;
}

// ---------- 筛选、排序 ----------
export const SORT_OPTIONS = [
  { value: "default", label: "默认（按姓名）" },
  { value: "alert", label: "提醒优先" },
  { value: "joined_desc", label: "入职最新" },
  { value: "joined_asc", label: "入职最早" },
  { value: "number", label: "员工号" },
];

export const NO_RD_TYPE = "__none__";

// filters: { company, department(展示名), status: active|left|all, rdType, archive, alertOnly, keyword }
export function filterEmployees(items, filters = {}) {
  const needle = String(filters.keyword || "").trim().toLowerCase();
  const status = filters.status || "all";
  return (items || []).filter((item) => {
    const row = item.row;
    if (filters.company && row.company !== filters.company) return false;
    if (status === "active" && item.left) return false;
    if (status === "left" && !item.left) return false;
    if (filters.department && item.department !== filters.department) return false;
    if (filters.rdType === NO_RD_TYPE ? item.rdType : filters.rdType && item.rdType !== filters.rdType) return false;
    if (filters.archive && item.archive !== filters.archive) return false;
    if (filters.alertOnly && !item.reminders.some((reminder) => reminder.key !== "left")) return false;
    if (!needle) return true;
    return [row.employee_number, row.employee_name, row.english_name, item.department, row.designation]
      .some((value) => String(value || "").toLowerCase().includes(needle));
  });
}

function alertScore(item) {
  const first = item.reminders.find((reminder) => reminder.key !== "left");
  if (!first) return Number.POSITIVE_INFINITY;
  const base = { leaving: 1000, probation: 2000, contract: 3000, rdtype: 4000, missing: 5000 }[first.key] ?? 6000;
  const urgency = item.urgent ? -2000 : 0;
  return base + urgency + (first.days ?? 0);
}

export function sortEmployees(items, mode = "default") {
  const list = [...(items || [])];
  if (mode === "alert") {
    return list.map((item, index) => ({ item, index })).sort((a, b) => alertScore(a.item) - alertScore(b.item) || a.index - b.index).map(({ item }) => item);
  }
  if (mode === "joined_desc" || mode === "joined_asc") {
    const sign = mode === "joined_desc" ? -1 : 1;
    return list.map((item, index) => ({ item, index })).sort((a, b) => {
      if (!a.item.joined && !b.item.joined) return a.index - b.index;
      if (!a.item.joined) return 1;
      if (!b.item.joined) return -1;
      return (a.item.joined < b.item.joined ? -1 : a.item.joined > b.item.joined ? 1 : 0) * sign || a.index - b.index;
    }).map(({ item }) => item);
  }
  if (mode === "number") {
    return list.map((item, index) => ({ item, index })).sort((a, b) => {
      const x = String(a.item.row.employee_number || "");
      const y = String(b.item.row.employee_number || "");
      if (!x && !y) return a.index - b.index;
      if (!x) return 1;
      if (!y) return -1;
      return x.localeCompare(y, "zh-CN", { numeric: true }) || a.index - b.index;
    }).map(({ item }) => item);
  }
  return list;
}

export function pageSlice(list, page, size) {
  const pageCount = Math.max(1, Math.ceil((list || []).length / size));
  const current = Math.min(Math.max(1, page), pageCount);
  return { page: current, pageCount, items: (list || []).slice((current - 1) * size, current * size) };
}

// ---------- 部门分组 ----------
// 部门展示名 → 分组名，decorateEmployees 用它判断「研发部门的人没设研发类型」。
export function departmentGroupMap(deptMeta) {
  const map = new Map();
  for (const meta of deptMeta || []) {
    const name = displayDepartment(meta.department_name || meta.name);
    if (name && meta.group_name && !map.has(name)) map.set(name, meta.group_name);
  }
  return map;
}

// deptMeta：get_dept_options 的结果，用来知道部门属于哪个分组；人数按当前列表数据现算，
// 这样「在职 / 已离职」切换、公司切换后数字都对得上。
export function departmentGroups(items, deptMeta, { company = "", status = "active", order = DEPARTMENT_GROUP_ORDER } = {}) {
  const groupOf = new Map();
  const position = new Map();
  for (const meta of deptMeta || []) {
    const name = displayDepartment(meta.department_name || meta.name);
    if (!name || !meta.group_name) continue;
    if (!groupOf.has(name)) groupOf.set(name, meta.group_name);
    if (!position.has(name)) position.set(name, position.size);
  }
  const counts = new Map();
  const fills = new Map();
  for (const item of items || []) {
    if (company && item.row.company !== company) continue;
    if (status === "active" && item.left) continue;
    if (status === "left" && !item.left) continue;
    if (!item.department) continue;
    counts.set(item.department, (counts.get(item.department) || 0) + 1);
    if (isRdType(item.rdType)) fills.set(item.department, (fills.get(item.department) || 0) + 1);
  }
  const byGroup = new Map();
  for (const [name, count] of counts) {
    const group = groupOf.get(name) || OTHER_GROUP;
    if (!byGroup.has(group)) byGroup.set(group, []);
    byGroup.get(group).push({ name, group_name: group, employee_count: count, fill_count: fills.get(name) || 0 });
  }
  const rank = (name) => (position.has(name) ? position.get(name) : Number.MAX_SAFE_INTEGER);
  // fill：这个分组里研发人员类型是全时 / 非全时 / 辅助的人数，也就是会出现在研发工时填报里的人
  return [...order, OTHER_GROUP].map((groupName) => {
    const departments = (byGroup.get(groupName) || []).sort((a, b) => rank(a.name) - rank(b.name) || a.name.localeCompare(b.name, "zh-CN"));
    return {
      name: groupName, departments,
      total: departments.reduce((sum, department) => sum + department.employee_count, 0),
      fill: departments.reduce((sum, department) => sum + department.fill_count, 0),
    };
  }).filter((group) => group.departments.length);
}

// ---------- 敏感信息遮挡 ----------
export const MASKED_FIELDS = {
  default_monthly_salary: "money",
  salary_months: "plain",
  default_social_insurance_base: "money",
  default_housing_fund_base: "money",
  social_insurance_number: "number",
  housing_fund_number: "number",
  id_card_number_cn: "idcard",
  bank_ac_no: "bank",
};

export function isMaskedField(key) {
  return Object.prototype.hasOwnProperty.call(MASKED_FIELDS, key) && MASKED_FIELDS[key] !== "plain";
}

// 默认显示的遮挡文本。空值不遮挡，返回 ""（页面显示「未填写」，也不给显示按钮）。
export function maskValue(key, value) {
  if (isBlank(value)) return "";
  const text = String(value).trim();
  switch (MASKED_FIELDS[key]) {
    case "idcard":
      return text.length > 5 ? `${text.slice(0, 3)}${"*".repeat(text.length - 5)}${text.slice(-2)}` : "•".repeat(text.length);
    case "bank":
      return "•••• •••• ••••";
    case "number":
      return "•••• ••••";
    case "money":
      return "••••••";
    default:
      return text;
  }
}

export function formatMoney(value) {
  return Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function displayFieldValue(key, value, { reveal = false } = {}) {
  if (isBlank(value)) return "";
  if (isMaskedField(key) && !reveal) return maskValue(key, value);
  if (MASKED_FIELDS[key] === "money") return formatMoney(value);
  return String(value);
}

// ---------- 其他 ----------
export function genderLabel(value) {
  return value === "Female" ? "女" : value === "Male" ? "男" : value || "";
}

// "2026-10-06 16:20:45.123" -> "10-06 16:20"
export function lastModifiedText(row) {
  const match = /^\d{4}-(\d{2}-\d{2})[ T](\d{2}:\d{2})/.exec(String(row?.modified || ""));
  if (!match) return "";
  const who = String(row?.modified_by || "").trim();
  return `最近修改：${who ? who + " · " : ""}${match[1]} ${match[2]}`;
}

export function supervisorLabel(row, nameById) {
  if (!row?.reports_to) return "";
  return nameById.get(row.reports_to) || row.reports_to;
}
