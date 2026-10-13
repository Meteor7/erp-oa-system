// 薪酬计算页的筛选：地址 <-> 页面状态、草稿工资条的判断（纯函数，页面负责绑定，见 urlFilterState.js）。
//   ?status=draft       只看草稿工资条
//   ?status=submitted   只看已确认的工资条（看板「人工成本 · 工资」只算已确认的，点进来对得上；审查 2026-10-13）
import { queryText } from "./urlFilterState.js";

export const PAYROLL_QUERY_KEYS = ["status"];
const STATUSES = ["draft", "submitted"];

export function parsePayrollQuery(query) {
  const status = queryText(query, "status");
  return { status: STATUSES.includes(status) ? status : "" };
}

export function payrollQueryOf(filters = {}) {
  return STATUSES.includes(filters.status) ? { status: filters.status } : {};
}

// 草稿 = 已生成工资条、还没提交（docstatus 0）。与看板「草稿工资条」同口径；已提交（1）和未生成（没有工资条）不算。
export function isDraftSlip(row) {
  return Boolean(row?.salary_slip) && Number(row.docstatus) === 0;
}

// 已确认 = 工资条已提交（docstatus 1）。
export function isSubmittedSlip(row) {
  return Boolean(row?.salary_slip) && Number(row.docstatus) === 1;
}

export function filterPayrollRows(rows, status) {
  const list = rows || [];
  if (status === "draft") return list.filter(isDraftSlip);
  if (status === "submitted") return list.filter(isSubmittedSlip);
  return list;
}
