// 研发费用台账 / 汇总两个页面用的纯逻辑：台账矩阵按科目分组、汇总页的项目排行。
// 只整理服务端已经返回的数据，不新增任何后端字段。

export const STAGE_LABELS = {
  capitalized: "资本化",
  expensed: "费用化",
  unknown: "未判定",
};

export function stageLabel(stage) {
  return STAGE_LABELS[stage] || "";
}

function number(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n : 0;
}

function round2(value) {
  return Math.round(number(value) * 100) / 100;
}

function fieldKey(column = {}) {
  return column.fieldname || column.id;
}

export function isMoneyColumn(column = {}) {
  return column.fieldtype === "Currency";
}

/**
 * 把 `RD Allocation Matrix` 报表的行按 groupField（默认三级科目）分组。
 * - 分组顺序按第一次出现的顺序；同一科目的行即使不连续也归到一组。
 * - 每组的小计 = 该组各行在每个金额列上的合计（金额列即 fieldtype 为 Currency 的列，含「汇总」列）。
 * - 报表自带的「项目汇总」行（_is_total）不进分组，原样放在 totalRow。
 * - 列里没有 groupField 时 grouped=false，只返回一个不带表头的分组（页面按平铺显示）。
 */
export function groupAllocationRows({ columns = [], result = [], groupField = "account_level_3" } = {}) {
  const moneyKeys = (columns || []).filter(isMoneyColumn).map(fieldKey);
  const grouped = (columns || []).some((column) => fieldKey(column) === groupField);
  const rows = result || [];
  const totalRow = rows.find((row) => row && row._is_total) || null;
  const order = [];
  const byKey = new Map();
  for (const row of rows) {
    if (!row || row._is_total) continue;
    const label = grouped ? String(row[groupField] ?? "").trim() : "";
    let group = byKey.get(label);
    if (!group) {
      group = { key: label, label, rows: [], totals: {} };
      byKey.set(label, group);
      order.push(group);
    }
    group.rows.push(row);
    for (const key of moneyKeys) group.totals[key] = (group.totals[key] || 0) + number(row[key]);
  }
  for (const group of order) {
    for (const key of moneyKeys) group.totals[key] = round2(group.totals[key] || 0);
  }
  return { grouped, groups: order, totalRow, moneyKeys };
}

/** 汇总页：每个项目的金额。优先取总计行的 projects；没有总计行时把明细行加起来。 */
export function projectAmountTotals(rows = []) {
  const grand = (rows || []).find((row) => row && row.row_type === "grand_total");
  if (grand && grand.projects) return { ...grand.projects };
  const totals = {};
  for (const row of rows || []) {
    if (!row || row.row_type !== "detail") continue;
    for (const [project, value] of Object.entries(row.projects || {})) {
      totals[project] = (totals[project] || 0) + number(value);
    }
  }
  return totals;
}

/**
 * 汇总页「各项目承担」：金额从大到小取前 topN 个，其余合并成一条「其他」。
 * 金额为 0 的项目不列。share 是占全部项目金额合计的比例（0-1），width 是相对最长一条的百分比。
 */
export function rankProjects({ rows = [], projectColumns = [], topN = 8, otherLabel = "其他" } = {}) {
  const totals = projectAmountTotals(rows);
  const items = (projectColumns || [])
    .map((project) => ({
      key: project.project,
      code: project.project_code || project.project,
      name: project.project_name || "",
      value: round2(totals[project.project]),
      isOther: false,
    }))
    .filter((item) => item.value !== 0);
  items.sort((a, b) => b.value - a.value);
  const total = round2(items.reduce((sum, item) => sum + item.value, 0));
  const limit = Math.max(1, Number(topN) || 1);
  const shown = items.slice(0, limit);
  const rest = items.slice(limit);
  if (rest.length) {
    shown.push({
      key: "__other__",
      code: otherLabel,
      name: `${rest.length} 个项目`,
      value: round2(rest.reduce((sum, item) => sum + item.value, 0)),
      isOther: true,
    });
  }
  const max = Math.max(0, ...shown.map((item) => item.value));
  return {
    total,
    items: shown.map((item) => ({
      ...item,
      share: total ? item.value / total : 0,
      width: max > 0 ? Math.max(0, item.value) / max * 100 : 0,
    })),
  };
}
