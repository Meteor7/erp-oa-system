const number = value => Number(value || 0);
export const isSavedPayroll = row => row.amount_source === "salary_slip" || Number(row.docstatus) === 1;
export const payrollAdjusted = row => isSavedPayroll(row) ? row.adjusted_base : number(row.base_salary) + number(row.salary_adjustment);
export const payrollProrated = row => isSavedPayroll(row) ? row.prorated_base : number(row.total_working_days) > 0 ? payrollAdjusted(row) * number(row.payment_days) / number(row.total_working_days) : 0;
export const payrollPayable = row => isSavedPayroll(row) ? row.payable_salary : payrollProrated(row) + number(row.company_subsidy) + number(row.bonus) + number(row.other_adjustment);
export const payrollNet = row => isSavedPayroll(row) ? row.net_pay : payrollPayable(row) - number(row.social_insurance) - number(row.housing_fund) - number(row.income_tax) - number(row.accommodation) - number(row.advanced_paid);
