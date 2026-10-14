// 一行工资的金额（决定 2026-10-14）：基本工资 × 实际工时 ÷ 当月总工时 + 补贴奖金其他 = 应付；
// 应付 − 社保 − 公积金 − 个税（累计预扣法，见 payrollTax.js）− 宿舍 − 已发放 = 实发。已保存（确认或别处生成）的以工资单为准。
import { computeTax } from './payrollTax.js';

const number = value => Number(value || 0);
const round2 = value => Math.round((number(value) + Number.EPSILON) * 100) / 100;
export const isSavedPayroll = row => row.amount_source === "salary_slip" || Number(row.docstatus) === 1;
// 工时：新数据按小时；旧数据只有天数时按天算（同一个比例）
export const payrollHours = row => (row.total_hours != null
  ? { total: number(row.total_hours), actual: number(row.actual_hours) }
  : { total: number(row.total_working_days), actual: number(row.payment_days) });
export const payrollAdjusted = row => isSavedPayroll(row) ? row.adjusted_base : number(row.base_salary) + number(row.salary_adjustment);
export const payrollProrated = row => {
  if (isSavedPayroll(row)) return row.prorated_base;
  const hours = payrollHours(row);
  return hours.total > 0 ? round2(payrollAdjusted(row) * hours.actual / hours.total) : 0;
};
export const payrollPayable = row => isSavedPayroll(row) ? row.payable_salary : payrollProrated(row) + number(row.company_subsidy) + number(row.bonus) + number(row.other_adjustment);
// 个税：已保存的以工资单为准；手动改过的用人事填的数；否则按累计预扣法现算（后端给了 tax_basis 才能算）
export const payrollTaxDetail = row => (isSavedPayroll(row) || !row.tax_basis ? null : computeTax(row.tax_basis, {
  payable: payrollPayable(row), social: row.social_insurance, fund: row.housing_fund, bonus: row.bonus, bonusSeparate: Boolean(row.bonus_separate),
}));
export const payrollTax = row => {
  if (isSavedPayroll(row) || row.tax_manual || !row.tax_basis) return number(row.income_tax);
  return payrollTaxDetail(row).total;
};
export const payrollNet = row => isSavedPayroll(row) ? row.net_pay : payrollPayable(row) - number(row.social_insurance) - number(row.housing_fund) - payrollTax(row) - number(row.accommodation) - number(row.advanced_paid);
