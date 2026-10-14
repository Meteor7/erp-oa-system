// 工资薪金个税：累计预扣法（和后端 income_tax.py、payroll_inputs.compute_tax 同一个算法）。
// 抽屉里改数字时当场重算给人看；保存时以后端算的为准。工资次月发，按发放月累计（后端给的 tax_basis 已经按这个口径汇总好之前的月份）。
const n = (value) => Number(value || 0);
const r2 = (value) => Math.round((n(value) + Number.EPSILON) * 100) / 100;

// 个人所得税预扣率表一：[累计应纳税所得额上限, 预扣率 %, 速算扣除数]
export const ANNUAL_TABLE = Object.freeze([
  [36000, 3, 0], [144000, 10, 2520], [300000, 20, 16920], [420000, 25, 31920],
  [660000, 30, 52920], [960000, 35, 85920], [Infinity, 45, 181920],
]);
// 按月换算后的综合所得税率表（全年一次性奖金单独计税）
export const MONTHLY_TABLE = Object.freeze([
  [3000, 3, 0], [12000, 10, 210], [25000, 20, 1410], [35000, 25, 2660],
  [55000, 30, 4410], [80000, 35, 7160], [Infinity, 45, 15160],
]);
export const MONTHLY_BASIC = 5000;
export const LOW_INCOME_BASIC = 60000;

export function bracket(amount, table) {
  const hit = table.find(([upper]) => amount <= upper) || table[table.length - 1];
  return { rate: hit[1], quick: hit[2] };
}

export function cumulativeTax(taxable) {
  const value = r2(taxable);
  if (value <= 0) return { rate: 0, quick: 0, tax: 0 };
  const { rate, quick } = bracket(value, ANNUAL_TABLE);
  return { rate, quick, tax: r2(value * rate / 100 - quick) };
}

export function bonusTax(bonus) {
  const value = r2(bonus);
  if (value <= 0) return { rate: 0, quick: 0, tax: 0 };
  const { rate, quick } = bracket(value / 12, MONTHLY_TABLE);
  return { rate, quick, tax: r2(Math.max(value * rate / 100 - quick, 0)) };
}

// current：本月 {income, tax_free, special, special_additional, other}；prior：之前月份的累计 {months, income, …, tax}
export function withholding(current, prior = {}, lowIncome = false) {
  const months = Math.trunc(n(prior.months)) + 1;
  const cum = {};
  ['income', 'tax_free', 'special', 'special_additional', 'other'].forEach((key) => { cum[key] = r2(n(prior[key]) + n(current[key])); });
  const basic = Math.max(lowIncome ? LOW_INCOME_BASIC : 0, MONTHLY_BASIC * months);
  const taxable = cum.income - cum.tax_free - basic - cum.special - cum.special_additional - cum.other;
  const { rate, quick, tax: cumTax } = cumulativeTax(taxable);
  const priorTax = r2(prior.tax);
  return {
    months, cum_income: cum.income, cum_tax_free: cum.tax_free, cum_basic: basic, cum_special: cum.special,
    cum_special_additional: cum.special_additional, cum_other: cum.other, cum_taxable: r2(Math.max(taxable, 0)),
    rate, quick, cum_tax: cumTax, prior_tax: priorTax, tax: r2(Math.max(cumTax - priorTax, 0)),
  };
}

// 本月个税：累计预扣（不含单独计税的年终奖）+ 年终奖单独计税。basis 是后端给的 tax_basis。
export function computeTax(basis, { payable, social, fund, bonus, bonusSeparate }) {
  const bonusPart = bonusSeparate ? n(bonus) : 0;
  const current = {
    income: r2(n(payable) - bonusPart), tax_free: 0, special: r2(n(social) + n(fund)),
    special_additional: n(basis?.special_additional), other: n(basis?.other),
  };
  const result = withholding(current, basis?.prior || {}, Boolean(basis?.low_income));
  const bonusPartTax = bonusTax(bonusPart);
  return {
    ...result, income: current.income, special: current.special, special_additional: current.special_additional, other: current.other,
    bonus_rate: bonusPartTax.rate, bonus_quick: bonusPartTax.quick, bonus_tax: bonusPartTax.tax,
    total: r2(result.tax + bonusPartTax.tax), tax_period: basis?.tax_period || '',
  };
}
