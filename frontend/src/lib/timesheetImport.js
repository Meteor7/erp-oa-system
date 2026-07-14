function clean(value) {
  return String(value ?? '').trim();
}

function aliasKey(value) {
  return clean(value)
    .replace(/[\s_\-:：()（）/\\.]+/g, '')
    .toLowerCase();
}

function splitLooseWhitespace(text) {
  return clean(text).split(/\s+/).map(clean).filter(Boolean);
}

function splitWideSpaces(cells) {
  return cells.flatMap((cell) => clean(cell).split(/\s{2,}/).map(clean).filter(Boolean));
}

function splitLine(line) {
  const text = String(line ?? '');
  let cells;
  if (text.includes('\t')) {
    cells = text.split('\t').map(clean);
  } else if (text.includes(',')) {
    cells = text.split(',').map(clean);
  } else if (text.includes('，')) {
    cells = text.split('，').map(clean);
  } else {
    cells = [clean(text)];
  }

  if (cells.length >= 7) return cells;

  const wideSpaceCells = splitWideSpaces(cells);
  if (wideSpaceCells.length >= 7) return wideSpaceCells;

  const looseCells = splitLooseWhitespace(text);
  return looseCells.length >= 7 ? looseCells : cells;
}

const HEADER_ALIASES = {
  work_date: ['日期', '填报日期', '工作日期', 'date', 'work_date'],
  employee_text: ['研发人员', '员工', '姓名', '员工编号', 'employee', 'employee_name'],
  project_code: ['项目代码', '项目编号', 'project_code', 'rd_project_code'],
  project_name: ['项目名称', 'project_name', 'rd_project_name'],
  activity_type: ['活动类型', 'activity_type'],
  hours: ['工时', '工时h', '小时', 'hours'],
  description: ['工作内容', '内容', '描述', 'description'],
};

const REQUIRED_HEADERS = ['work_date', 'employee_text', 'project_code', 'project_name', 'activity_type', 'hours'];

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
  return REQUIRED_HEADERS.every((field) => map[field] !== undefined) ? map : null;
}

function rowFromHeader(cells, map) {
  const pick = (field) => (map[field] === undefined ? '' : clean(cells[map[field]]));
  return {
    work_date: pick('work_date'),
    employee_text: pick('employee_text'),
    project_code: pick('project_code'),
    project_name: pick('project_name'),
    activity_type: pick('activity_type'),
    hours: pick('hours'),
    description: pick('description'),
  };
}

function rowFromPosition(cells) {
  const values = cells.map(clean);
  return {
    work_date: values[0] || '',
    employee_text: values[1] || '',
    project_code: values[2] || '',
    project_name: values[3] || '',
    activity_type: values[4] || '',
    hours: values[5] || '',
    description: values.slice(6).join(' ').trim(),
  };
}

function excelSerialToISO(value) {
  const serial = Number(value);
  if (!Number.isFinite(serial) || serial <= 0) return '';
  const utc = Date.UTC(1899, 11, 30) + Math.round(serial) * 24 * 60 * 60 * 1000;
  return new Date(utc).toISOString().slice(0, 10);
}

function parseDate(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString().slice(0, 10);
  }
  if (typeof value === 'number') return excelSerialToISO(value);
  const text = clean(value);
  if (!text) return '';
  if (/^\d+(\.\d+)?$/.test(text) && Number(text) > 20000) return excelSerialToISO(Number(text));
  const normalized = text
    .replace(/[年月/.]/g, '-')
    .replace(/日/g, '')
    .replace(/\s+.*/, '')
    .trim();
  const match = normalized.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (!match) return '';
  const [, year, month, day] = match;
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
}

function parseHours(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  const text = clean(value).replace(/小时|h/gi, '').replace(/,/g, '');
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function employeeValues(employee) {
  return [employee?.name, employee?.employee_name].map(clean).filter(Boolean);
}

function findEmployee(value, employees = []) {
  const text = clean(value);
  if (!text) return { employee: null, multiple: false };
  const key = aliasKey(text);
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

function activityName(activity) {
  return clean(activity?.name || activity);
}

function findActivity(value, activityTypes = []) {
  const text = clean(value);
  if (!text) return '';
  return activityTypes.map(activityName).find((name) => name === text) || '';
}

function rowKey({ employee, work_date, project_code, project_name, activity_type }) {
  return [employee, work_date, project_code, project_name, activity_type].map(aliasKey).join('|');
}

function dailyKey(employee, workDate) {
  return `${clean(employee)}|${clean(workDate)}`;
}

function addDailyTotal(totals, employee, workDate, hours) {
  const key = dailyKey(employee, workDate);
  totals.set(key, (totals.get(key) || 0) + Number(hours || 0));
  return totals.get(key);
}

function existingProjectCode(row) {
  return clean(row?.rd_project_code || row?.project_code || row?.project);
}

function existingProjectName(row) {
  return clean(row?.project_name || row?.rd_project_name || row?.project);
}

function buildExistingState(existingRows = []) {
  const keys = new Set();
  const dailyTotals = new Map();
  existingRows.forEach((row) => {
    const workDate = parseDate(row?.work_date || row?.date);
    if (row?.employee && workDate) {
      addDailyTotal(dailyTotals, row.employee, workDate, Number(row.hours || 0));
    }
    const key = rowKey({
      employee: row?.employee,
      work_date: workDate,
      project_code: existingProjectCode(row),
      project_name: existingProjectName(row),
      activity_type: row?.activity_type,
    });
    if (row?.employee && workDate && existingProjectCode(row) && existingProjectName(row) && clean(row?.activity_type)) {
      keys.add(key);
    }
  });
  return { keys, dailyTotals };
}

function normalizeRawRow(rawRow, options, lineNo, state) {
  const employees = options.employees || [];
  const projects = options.projects || [];
  const activityTypes = options.activityTypes || [];
  const period = clean(options.period);
  const rowErrors = [];

  const workDate = parseDate(rawRow.work_date);
  if (!workDate) {
    rowErrors.push(`第 ${lineNo} 行：日期格式不正确`);
  } else if (period && !workDate.startsWith(`${period}-`)) {
    rowErrors.push(`第 ${lineNo} 行：日期必须在当前会计期间 ${period} 内`);
  }

  const employeeMatch = findEmployee(rawRow.employee_text, employees);
  if (employeeMatch.multiple) {
    rowErrors.push(`第 ${lineNo} 行：研发人员“${clean(rawRow.employee_text)}”匹配到多个员工`);
  } else if (!employeeMatch.employee) {
    rowErrors.push(`第 ${lineNo} 行：研发人员“${clean(rawRow.employee_text)}”未匹配`);
  }

  const project = findProject(rawRow.project_code, rawRow.project_name, projects);
  if (!project) {
    rowErrors.push(`第 ${lineNo} 行：项目代码和项目名称未匹配`);
  }

  const activity = findActivity(rawRow.activity_type, activityTypes);
  if (!activity) {
    rowErrors.push(`第 ${lineNo} 行：活动类型“${clean(rawRow.activity_type)}”不存在`);
  }

  const hours = parseHours(rawRow.hours);
  if (hours === null || hours <= 0 || hours > 8) {
    rowErrors.push(`第 ${lineNo} 行：工时必须大于 0，且单日不超过 8 小时`);
  }

  const description = clean(rawRow.description);
  if (!description) {
    rowErrors.push(`第 ${lineNo} 行：工作内容不能为空`);
  }

  if (employeeMatch.employee && project && activity && workDate) {
    const normalized = {
      work_date: workDate,
      employee: employeeMatch.employee.name,
      employee_name: employeeMatch.employee.employee_name || employeeMatch.employee.name,
      project: project.name,
      project_code: projectCode(project),
      project_name: projectName(project),
      activity_type: activity,
      hours,
      description,
    };
    const key = rowKey(normalized);
    if (state.seenKeys.has(key)) {
      rowErrors.push(`第 ${lineNo} 行：导入内容中存在重复的员工/日期/项目/活动类型`);
    }
    if (state.existingKeys.has(key)) {
      rowErrors.push(`第 ${lineNo} 行：系统中已存在相同员工/日期/项目/活动类型工时`);
    }
    if (hours !== null && hours > 0 && hours <= 8) {
      const total = (state.dailyTotals.get(dailyKey(normalized.employee, normalized.work_date)) || 0) + hours;
      if (total > 8) {
        rowErrors.push(`第 ${lineNo} 行：${normalized.employee_name} ${normalized.work_date} 工时合计超过 8 小时`);
      }
    }
    if (!rowErrors.length) {
      state.seenKeys.add(key);
      addDailyTotal(state.dailyTotals, normalized.employee, normalized.work_date, hours);
      return { row: normalized, errors: [] };
    }
  }

  return { row: null, errors: rowErrors };
}

export function parseTimesheetTableRows(tableRows, options = {}) {
  const rows = [];
  const errors = [];
  let map = null;
  let seenContentRow = false;
  const existing = buildExistingState(options.existingRows || []);
  const state = {
    existingKeys: existing.keys,
    dailyTotals: existing.dailyTotals,
    seenKeys: new Set(),
  };

  tableRows.forEach((inputRow, index) => {
    const cells = Array.from(inputRow || []).map(clean);
    if (!cells.some(Boolean)) return;

    const possibleHeader = headerMap(cells);
    if (!seenContentRow && possibleHeader) {
      map = possibleHeader;
      return;
    }

    seenContentRow = true;
    const lineNo = index + 1;
    const rawRow = map ? rowFromHeader(cells, map) : rowFromPosition(cells);
    const result = normalizeRawRow(rawRow, options, lineNo, state);
    if (result.errors.length) {
      errors.push(...result.errors);
      return;
    }
    rows.push(result.row);
  });

  if (!rows.length && !errors.length) {
    errors.push('请粘贴或导入至少一行工时。');
  }
  return { rows: errors.length ? [] : rows, errors };
}

export function parseTimesheetPaste(text, options = {}) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  const tableRows = lines.map(splitLine);
  return parseTimesheetTableRows(tableRows, options);
}

export async function importTimesheetWorkbookFile(file, options = {}) {
  const XLSX = await import('xlsx');
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array', cellDates: true });
  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) return { rows: [], errors: ['Excel 文件没有工作表'] };
  const worksheet = workbook.Sheets[firstSheetName];
  const tableRows = XLSX.utils.sheet_to_json(worksheet, { header: 1, defval: '', raw: false });
  return parseTimesheetTableRows(tableRows, options);
}