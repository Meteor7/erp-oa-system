function clean(value) {
  return String(value || "").trim();
}

export function projectKey(row = {}) {
  const key = clean(row.rd_project_key);
  if (key) return key;
  const code = clean(row.rd_project_code);
  const name = clean(row.project_name);
  if (code && name) return `${code} | ${name}`;
  return code || name || clean(row.project);
}

export function projectDisplayCode(row = {}) {
  const code = clean(row.rd_project_code);
  if (code) return code;
  const key = clean(row.rd_project_key);
  if (key.includes("|")) return clean(key.split("|")[0]) || key;
  return clean(row.project) || key;
}

function projectContext(rows = []) {
  const ids = new Set();
  const labels = {};
  for (const row of rows || []) {
    const id = projectKey(row);
    if (!id) continue;
    ids.add(id);
    labels[id] = projectDisplayCode(row) || labels[id] || id;
  }
  const projectIds = [...ids].sort((left, right) => (labels[left] || left).localeCompare(labels[right] || right, "zh-CN"));
  return {
    projectIds,
    projects: projectIds.map((id) => ({ id, label: labels[id] || id })),
  };
}

export function buildEmployeeProjectPivot(rows = []) {
  const { projectIds, projects } = projectContext(rows);
  const employees = [];
  const cells = {};
  for (const row of rows || []) {
    const employee = clean(row.employee);
    const project = projectKey(row);
    if (!employee || !project) continue;
    if (!cells[employee]) {
      cells[employee] = {};
      employees.push({ id: employee, name: clean(row.employee_name) || employee });
    }
    cells[employee][project] = (cells[employee][project] || 0) + Number(row.hours || 0);
  }
  const data = employees.map((employee) => {
    const vals = projectIds.map((project) => cells[employee.id][project] || 0);
    return { id: employee.id, emp: employee.name, vals, total: vals.reduce((sum, value) => sum + value, 0) };
  });
  const projTotals = projectIds.map((project, index) => data.reduce((sum, row) => sum + row.vals[index], 0));
  const grand = projTotals.reduce((sum, value) => sum + value, 0);
  const rates = projTotals.map((value) => (grand ? Number((value / grand * 100).toFixed(2)) : 0));
  return { projects, data, projTotals, grand, rates };
}

function rowYearMonth(row = {}) {
  const match = clean(row.work_date).match(/^(\d{4})-(\d{2})/);
  return match ? { year: Number(match[1]), month: Number(match[2]) } : null;
}

export function buildMonthlyProjectRatePivot(rows = [], selectedYear) {
  const year = Number(selectedYear);
  const yearRows = (rows || []).filter((row) => rowYearMonth(row)?.year === year);
  const { projectIds, projects } = projectContext(yearRows);
  if (!projects.length) return { projects: [], data: [] };

  const monthlyHours = Array.from({ length: 12 }, () => ({}));
  for (const row of yearRows) {
    const period = rowYearMonth(row);
    const project = projectKey(row);
    if (!period || !project || period.month < 1 || period.month > 12) continue;
    const cells = monthlyHours[period.month - 1];
    cells[project] = (cells[project] || 0) + Number(row.hours || 0);
  }

  const data = monthlyHours.map((cells, index) => {
    const projectHours = projectIds.map((project) => cells[project] || 0);
    const monthTotal = projectHours.reduce((sum, value) => sum + value, 0);
    const vals = projectHours.map((value) => (monthTotal ? Number((value / monthTotal * 100).toFixed(2)) : 0));
    const monthNumber = String(index + 1).padStart(2, "0");
    return {
      id: `${year}-${monthNumber}`,
      month: `${year}\u5e74${monthNumber}\u6708`,
      vals,
      total: monthTotal ? 100 : 0,
    };
  });
  return { projects, data };
}

export function buildForeignEntityProjectPivot(rows = []) {
  return buildEmployeeProjectPivot((rows || []).map((row) => ({
    ...row,
    employee: clean(row.foreign_entity) || 'QIHENG DEMO OVERSEAS',
    employee_name: clean(row.foreign_entity) || 'QIHENG DEMO OVERSEAS',
    rd_project_code: clean(row.rd_project_code || row.project_code),
    rd_project_key: clean(row.rd_project_key) || [clean(row.project_code), clean(row.project_name)].filter(Boolean).join(' | '),
  })));
}