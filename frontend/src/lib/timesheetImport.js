function clean(value) {
  return String(value ?? '').trim();
}

function aliasKey(value) {
  return clean(value).replace(/[\s_\-:：()（）/\\.]+/g, '').toLowerCase();
}

function splitLine(line) {
  const text = String(line ?? '');
  if (text.includes('\t')) return text.split('\t').map(clean);
  if (text.includes(',')) return text.split(',').map(clean);
  if (text.includes('，')) return text.split('，').map(clean);
  const wide = text.split(/\s{2,}/).map(clean).filter(Boolean);
  return wide.length >= 4 ? wide : text.split(/\s+/).map(clean).filter(Boolean);
}

const HEADER_ALIASES = {
  employee_text: ['研发人员', '员工', '姓名', '员工编号', 'employee', 'employee_name'],
  project_code: ['项目代码', '项目编号', 'project_code', 'rd_project_code'],
  project_name: ['项目名称', 'project_name', 'rd_project_name'],
  hours: ['工时', '小时', '工时小时', '工时h', '工时(h)', 'hours'],
  occurrence_days: ['发生天数', '天数', 'days', 'occurrence_days'],
  remark: ['备注', '工作内容', '内容', '描述', 'remark', 'description'],
};

const REQUIRED_HEADERS = ['employee_text', 'project_code', 'project_name'];

function headerField(value) {
  const key = aliasKey(value);
  return Object.entries(HEADER_ALIASES).find(([, aliases]) => aliases.some((alias) => aliasKey(alias) === key))?.[0] || '';
}

function headerMap(cells) {
  const map = {};
  cells.forEach((cell, index) => {
    const field = headerField(cell);
    if (field && map[field] === undefined) map[field] = index;
  });
  // 工时（小时）和发生天数（老模板）至少有一列；两列都有时用小时
  return REQUIRED_HEADERS.every((field) => map[field] !== undefined) && (map.hours !== undefined || map.occurrence_days !== undefined) ? map : null;
}

function rowFromHeader(cells, map) {
  const pick = (field) => (map[field] === undefined ? '' : clean(cells[map[field]]));
  return {
    employee_text: pick('employee_text'),
    project_code: pick('project_code'),
    project_name: pick('project_name'),
    hours: pick('hours'),
    occurrence_days: pick('occurrence_days'),
    remark: pick('remark'),
  };
}

function rowFromPosition(cells) {
  const values = cells.map(clean);
  return {
    employee_text: values[0] || '',
    project_code: values[1] || '',
    project_name: values[2] || '',
    hours: values[3] || '',
    occurrence_days: '',
    remark: values.slice(4).join(' ').trim(),
  };
}

function employeeValues(employee) {
  return [employee?.name, employee?.employee_name].map(clean).filter(Boolean);
}

function findEmployee(value, employees = []) {
  const key = aliasKey(value);
  const matches = employees.filter((employee) => employeeValues(employee).some((item) => aliasKey(item) === key));
  return { employee: matches.length === 1 ? matches[0] : null, multiple: matches.length > 1 };
}

function projectCode(project) {
  return clean(project?.rd_project_code || project?.project_code || project?.name);
}

function projectName(project) {
  return clean(project?.project_name || project?.name);
}

function findProject(codeValue, nameValue, projects = []) {
  const code = clean(codeValue);
  const name = clean(nameValue);
  if (!code || !name) return null;
  return projects.find((project) => projectCode(project) === code && projectName(project) === name) || null;
}

// 小时（优先）或天数（老模板，按 1 天 = 8 小时换算）→ 小时。返回 { value: 小时或 null, precisionError, fromDays }
function parseHours(rawRow) {
  const hoursText = clean(rawRow.hours).replace(/小时|h/gi, '');
  const daysText = clean(rawRow.occurrence_days).replace(/天/g, '');
  const fromDays = !hoursText && Boolean(daysText);
  const text = fromDays ? daysText : hoursText;
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) {
    return { value: null, precisionError: /^\d+\.\d{3,}$/.test(text), fromDays };
  }
  const number = Number(text) * (fromDays ? 8 : 1);
  return { value: Number.isFinite(number) ? Math.round(number * 100) / 100 : null, precisionError: false, fromDays };
}

function monthHourLimit(period) {
  const match = clean(period).match(/^(\d{4})-(\d{2})$/);
  const days = match ? new Date(Number(match[1]), Number(match[2]), 0).getDate() : 31;
  return days * 8;
}

function rowKey(employee, project) {
  return `${aliasKey(employee)}|${aliasKey(project)}`;
}

function buildExistingState(existingRows = []) {
  const keys = new Set();
  const totals = new Map();
  existingRows.forEach((row) => {
    const employee = clean(row?.employee);
    const project = clean(row?.project);
    if (employee && project) keys.add(rowKey(employee, project));
    if (employee) totals.set(employee, (totals.get(employee) || 0) + Number(row?.hours || 0));
  });
  return { keys, totals };
}

function normalizeRawRow(rawRow, options, lineNo, state) {
  const errors = [];
  const employeeMatch = findEmployee(rawRow.employee_text, options.employees || []);
  if (employeeMatch.multiple) {
    errors.push(`第 ${lineNo} 行：研发人员“${clean(rawRow.employee_text)}”匹配到多个员工`);
  } else if (!employeeMatch.employee) {
    errors.push(`第 ${lineNo} 行：研发人员“${clean(rawRow.employee_text)}”未匹配`);
  }

  const project = findProject(rawRow.project_code, rawRow.project_name, options.projects || []);
  if (!project) errors.push(`第 ${lineNo} 行：项目代码和项目名称未匹配`);

  const parsed = parseHours(rawRow);
  if (parsed.precisionError) {
    errors.push(`第 ${lineNo} 行：${parsed.fromDays ? '发生天数' : '工时'}最多保留两位小数`);
  } else if (parsed.value === null) {
    errors.push(`第 ${lineNo} 行：${parsed.fromDays ? '发生天数' : '工时'}必须是有效数字`);
  } else if (parsed.value <= 0) {
    errors.push(`第 ${lineNo} 行：${parsed.fromDays ? '发生天数' : '工时'}必须大于 0`);
  }

  if (employeeMatch.employee && project && parsed.value !== null && parsed.value > 0) {
    const employee = employeeMatch.employee.name;
    const key = rowKey(employee, project.name);
    if (state.seenKeys.has(key)) errors.push(`第 ${lineNo} 行：导入内容中存在重复的员工和项目`);
    if (state.existingKeys.has(key)) errors.push(`第 ${lineNo} 行：系统中已存在相同员工和项目的月度工时`);

    const total = Math.round(((state.totals.get(employee) || 0) + parsed.value) * 100) / 100;
    if (total > state.hourLimit) {
      errors.push(`第 ${lineNo} 行：${employeeMatch.employee.employee_name || employee}当月累计工时不能超过 ${state.hourLimit} 小时`);
    }

    if (!errors.length) {
      state.seenKeys.add(key);
      state.totals.set(employee, total);
      return {
        row: {
          employee,
          employee_name: employeeMatch.employee.employee_name || employee,
          project: project.name,
          project_code: projectCode(project),
          project_name: projectName(project),
          hours: parsed.value,
          occurrence_days: Math.round((parsed.value / 8) * 100) / 100,
          remark: clean(rawRow.remark),
        },
        errors: [],
      };
    }
  }
  return { row: null, errors };
}

export function parseTimesheetTableRows(tableRows, options = {}) {
  const rows = [];
  const errors = [];
  const existing = buildExistingState(options.existingRows || []);
  const state = {
    existingKeys: existing.keys,
    seenKeys: new Set(),
    totals: existing.totals,
    hourLimit: monthHourLimit(options.period),
  };
  let map = null;
  let seenContentRow = false;

  tableRows.forEach((inputRow, index) => {
    const cells = Array.from(inputRow || []).map(clean);
    if (!cells.some(Boolean)) return;
    const possibleHeader = headerMap(cells);
    if (!seenContentRow && possibleHeader) {
      map = possibleHeader;
      return;
    }
    seenContentRow = true;
    const result = normalizeRawRow(map ? rowFromHeader(cells, map) : rowFromPosition(cells), options, index + 1, state);
    if (result.errors.length) errors.push(...result.errors);
    else rows.push(result.row);
  });

  if (!rows.length && !errors.length) errors.push('请粘贴或导入至少一行月度工时。');
  return { rows: errors.length ? [] : rows, errors };
}

export function parseTimesheetPaste(text, options = {}) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  return parseTimesheetTableRows(lines.map(splitLine), options);
}

export async function importTimesheetWorkbookFile(file, options = {}) {
  const XLSX = await import('xlsx');
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array' });
  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) return { rows: [], errors: ['Excel 文件没有工作表'] };
  const tableRows = XLSX.utils.sheet_to_json(workbook.Sheets[firstSheetName], { header: 1, defval: '', raw: false });
  return parseTimesheetTableRows(tableRows, options);
}
