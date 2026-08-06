export function hasAllocationData(payload) {
  return Boolean(payload && payload.has_data);
}

export function buildAllocationMatrixFilters({ scope, period, allocation, stage }) {
  if (scope === "year") {
    return { year: Number(String(period).slice(0, 4)), stage };
  }
  if (allocation) {
    return { allocation, stage };
  }
  const [year, month] = String(period).split("-").map(Number);
  return { year, month, stage };
}

export function allocationEmptyState({ hasData, mode }) {
  if (!hasData) return "no-data";
  return mode === "all" ? "no-detail" : "no-detail-for-mode";
}

export async function loadAllocationStageMatrices({
  scope,
  period,
  allocation,
  load,
}) {
  const stageMatrices = {};
  for (const stage of ["all", "capitalized", "expensed"]) {
    const data = await load(buildAllocationMatrixFilters({
      scope,
      period,
      allocation,
      stage,
    }));
    stageMatrices[stage] = {
      columns: data?.columns || [],
      result: data?.result || [],
    };
  }
  return stageMatrices;
}
