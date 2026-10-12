function clean(value) {
  return String(value ?? '').trim();
}

function splitLine(line) {
  const text = String(line ?? '');
  if (text.includes('\t')) return text.split('\t').map(clean);
  if (text.includes(',')) return text.split(',').map(clean);
  const wide = text.split(/\s{2,}/).map(clean).filter(Boolean);
  return wide.length >= 4 ? wide : text.split(/\s+/).map(clean).filter(Boolean);
}

const HEADERS = {
  foreign_entity: ['主体', '研发主体', '境外主体', 'foreign_entity', 'entity'],
  project_code: ['项目代码', '项目编号', 'project_code', 'rd_project_code'],
  project_name: ['项目名称', 'project_name'],
  hours: ['工时', '小时', '工时小时', '工时h', '工时(h)', 'hours'],
  occurrence_days: ['发生天数', '天数', 'occurrence_days', 'days'],
  remark: ['备注', '工作内容', 'remark', 'description'],
};

function headerKey(value) {
  return clean(value).replace(/[\s_\-:：()（）/\\.]+/g, '').toLowerCase();
}

function headerField(value) {
  const key = headerKey(value);
  return Object.entries(HEADERS).find(([, aliases]) => aliases.some((alias) => headerKey(alias) === key))?.[0] || '';
}

function headerMap(cells) {
  const map = {};
  cells.forEach((cell, index) => {
    const field = headerField(cell);
    if (field && map[field] === undefined) map[field] = index;
  });
  // 工时（小时）和发生天数（老模板）至少有一列；两列都有时用小时。
  const required = ['foreign_entity', 'project_code', 'project_name'].every((field) => map[field] !== undefined);
  return required && (map.hours !== undefined || map.occurrence_days !== undefined) ? map : null;
}

function rawRow(cells, map) {
  const pick = (field, fallback) => (map && map[field] === undefined ? '' : clean(cells[map ? map[field] : fallback]));
  return {
    foreign_entity: pick('foreign_entity', 0),
    project_code: pick('project_code', 1),
    project_name: pick('project_name', 2),
    // 没有表头时第 4 列是工时（小时）。
    hours: pick('hours', 3),
    occurrence_days: map ? pick('occurrence_days', 3) : '',
    remark: pick('remark', 4),
  };
}

function projectCode(project) {
  return clean(project?.rd_project_code || project?.project_code || project?.name);
}

function projectName(project) {
  return clean(project?.project_name || project?.name);
}

function findProject(code, name, projects) {
  return (projects || []).find((project) => projectCode(project) === clean(code) && projectName(project) === clean(name)) || null;
}

// 小时（优先）或天数（老模板，按 1 天 = 8 小时换算）→ 小时；最多两位小数。
function parseHours(raw) {
  const hoursText = clean(raw.hours).replace(/小时|h$/giu, '');
  const daysText = clean(raw.occurrence_days).replace(/天$/u, '');
  const fromDays = !hoursText && Boolean(daysText);
  const text = fromDays ? daysText : hoursText;
  if (!/^\d+(?:\.\d{1,2})?$/.test(text)) {
    return { value: null, precision: /^\d+\.\d{3,}$/.test(text), fromDays };
  }
  return { value: Math.round(Number(text) * (fromDays ? 8 : 1) * 100) / 100, precision: false, fromDays };
}

function monthHourLimit(period) {
  const match = clean(period).match(/^(\d{4})-(\d{2})$/);
  return (match ? new Date(Number(match[1]), Number(match[2]), 0).getDate() : 31) * 8;
}

function rowKey(entity, project) {
  return `${headerKey(entity)}|${clean(project)}`;
}

export function parseForeignRdTableRows(tableRows, options = {}) {
  const rows = [];
  const errors = [];
  const allowedEntities = options.foreignEntities || ['QIHENG DEMO OVERSEAS'];
  const existingKeys = new Set((options.existingRows || []).map((row) => rowKey(row.foreign_entity || 'QIHENG DEMO OVERSEAS', row.project)));
  const seenKeys = new Set();
  let map = null;
  let seenContent = false;

  tableRows.forEach((input, index) => {
    const cells = Array.from(input || []).map(clean);
    if (!cells.some(Boolean)) return;
    const possibleHeader = headerMap(cells);
    if (!seenContent && possibleHeader) {
      map = possibleHeader;
      return;
    }
    seenContent = true;
    const raw = rawRow(cells, map);
    const line = index + 1;
    const rowErrors = [];
    if (!allowedEntities.includes(raw.foreign_entity)) rowErrors.push(`第 ${line} 行：主体“${raw.foreign_entity}”未匹配`);
    const project = findProject(raw.project_code, raw.project_name, options.projects || []);
    if (!project) rowErrors.push(`第 ${line} 行：项目代码和项目名称未匹配`);
    const parsed = parseHours(raw);
    const unit = parsed.fromDays ? '发生天数' : '工时';
    if (parsed.precision) rowErrors.push(`第 ${line} 行：${unit}最多保留两位小数`);
    else if (parsed.value === null || parsed.value <= 0) rowErrors.push(`第 ${line} 行：${unit}必须大于 0`);
    else if (parsed.value > monthHourLimit(options.period)) rowErrors.push(`第 ${line} 行：工时不能超过当月自然日数 × 8 小时`);
    if (project) {
      const key = rowKey(raw.foreign_entity, project.name);
      if (seenKeys.has(key)) rowErrors.push(`第 ${line} 行：导入内容中存在重复的主体和项目`);
      if (existingKeys.has(key)) rowErrors.push(`第 ${line} 行：系统中已存在相同主体和项目`);
      if (!rowErrors.length) {
        seenKeys.add(key);
        rows.push({
          foreign_entity: raw.foreign_entity,
          project: project.name,
          project_code: projectCode(project),
          project_name: projectName(project),
          hours: parsed.value,
          occurrence_days: Math.round((parsed.value / 8) * 100000) / 100000,
          remark: raw.remark,
        });
      }
    }
    errors.push(...rowErrors);
  });

  if (!rows.length && !errors.length) errors.push('请粘贴或导入至少一行境外月度工时。');
  return { rows: errors.length ? [] : rows, errors };
}

export function parseForeignRdPaste(text, options = {}) {
  const lines = String(text ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
  return parseForeignRdTableRows(lines.map(splitLine), options);
}

export async function importForeignRdWorkbookFile(file, options = {}) {
  const XLSX = await import('xlsx');
  const data = await file.arrayBuffer();
  const workbook = XLSX.read(data, { type: 'array' });
  const firstSheet = workbook.SheetNames[0];
  if (!firstSheet) return { rows: [], errors: ['Excel 文件没有工作表'] };
  const rows = XLSX.utils.sheet_to_json(workbook.Sheets[firstSheet], { header: 1, defval: '', raw: false });
  return parseForeignRdTableRows(rows, options);
}