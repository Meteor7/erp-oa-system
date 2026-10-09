// 薪酬计算页的筛选：地址 <-> 页面状态、草稿工资条的判断（纯函数，页面负责绑定，见 urlFilterState.js）。
//   ?status=draft   只看草稿工资条
import { queryText } from "./urlFilterState.js";

export const PAYROLL_QUERY_KEYS = ["status"];

export function parsePayrollQuery(query) {
  return { status: queryText(query, "status") === "draft" ? "draft" : "" };
}

export function payrollQueryOf(filters = {}) {
  return filters.status === "draft" ? { status: "draft" } : {};
}

// 草稿 = 已生成工资条、还没提交（docstatus 0）。与看板「草稿工资条」同口径；已提交（1）和未生成（没有工资条）不算。
export function isDraftSlip(row) {
  return Boolean(row?.salary_slip) && Number(row.docstatus) === 0;
}

export function filterPayrollRows(rows, status) {
  const list = rows || [];
  return status === "draft" ? list.filter(isDraftSlip) : list;
}
