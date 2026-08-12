const LEVEL_FIELDS = ['account_level_1', 'account_level_2', 'account_level_3', 'account_level_4'];

export const EXPENSE_ACCOUNT_PATHS = [
  ['研发支出', '人员人工费用', '工资、奖金、补助等', ''],
  ['研发支出', '人员人工费用', '社会保险费用（单位）', '养老保险'],
  ['研发支出', '人员人工费用', '社会保险费用（单位）', '医疗保险'],
  ['研发支出', '人员人工费用', '社会保险费用（单位）', '生育保险'],
  ['研发支出', '人员人工费用', '社会保险费用（单位）', '工伤保险'],
  ['研发支出', '人员人工费用', '社会保险费用（单位）', '失业保险'],
  ['研发支出', '人员人工费用', '住房公积金（单位）', ''],
  ['研发支出', '人员人工费用', '外聘人员劳务费', ''],
  ['研发支出', '直接投入费用', '研发材料', ''],
  ['研发支出', '直接投入费用', '电费', ''],
  ['研发支出', '直接投入费用', '水费', ''],
  ['研发支出', '直接投入费用', '试制模具、工艺装备开发及制造费', ''],
  ['研发支出', '直接投入费用', '不构成固定资产的样品、样机及一般测试手段购置费', ''],
  ['研发支出', '直接投入费用', '检验检测费', ''],
  ['研发支出', '直接投入费用', '仪器、设备的运行维护、调整、检验、维修等费用', ''],
  ['研发支出', '直接投入费用', '仪器、设备租赁费', ''],
  ['研发支出', '折旧费用', '仪器仪表折旧（研发）', ''],
  ['研发支出', '折旧费用', '专用设备折旧（研发）', ''],
  ['研发支出', '折旧费用', '电子设备折旧（研发）', ''],
  ['研发支出', '折旧费用', '办公家具、工具及器具折旧（研发）', ''],
  ['研发支出', '折旧费用', '使用权资产折旧（研发）', ''],
  ['研发支出', '无形资产摊销', '无形资产摊销', ''],
  ['研发支出', '其他相关费用', '差旅费', ''],
  ['研发支出', '其他相关费用', '会议费', ''],
  ['研发支出', '其他相关费用', '专家咨询费', ''],
  ['研发支出', '其他相关费用', '知识产权的申请费、注册费、代理费', ''],
  ['研发支出', '其他相关费用', '办公耗材', ''],
  ['研发支出', '其他相关费用', '职工福利费', '员工工服'],
  ['研发支出', '其他相关费用', '职工福利费', '日常零食'],
  ['研发支出', '其他相关费用', '职工福利费', '集体宿舍'],
  ['研发支出', '其他相关费用', '职工福利费', '团建活动'],
  ['研发支出', '其他相关费用', '职工福利费', '节日福利'],
  ['研发支出', '其他相关费用', '职工福利费', '员工聚餐'],
  ['研发支出', '其他相关费用', '地方补充养老（单位）', ''],
  ['研发支出', '其他相关费用', '快递费', ''],
  ['研发支出', '其他相关费用', '装修费', ''],
  ['研发支出', '其他相关费用', '资料费', ''],
  ['研发支出', '其他相关费用', '市内交通费', ''],
  ['研发支出', '其他相关费用', '搬运费', ''],
  ['研发支出', '委托研发', '境内', ''],
  ['研发支出', '委托研发', '境外', 'QIHENG DEMO OVERSEAS'],
  ['研发支出', '委托研发', '境外', 'Kontron AIS GmbH'],
  ['研发支出', '委托研发', '境外', 'Sabri费用'],
].map(([account_level_1, account_level_2, account_level_3, account_level_4]) => ({
  account_level_1,
  account_level_2,
  account_level_3,
  account_level_4,
}));

function clean(value) {
  return String(value ?? '').trim();
}

function valueAt(path, level) {
  return clean(path[LEVEL_FIELDS[level - 1]]);
}

function rowValue(row, level) {
  return clean(row?.[LEVEL_FIELDS[level - 1]]);
}

function uniqueInOrder(values) {
  const seen = new Set();
  const result = [];
  values.forEach((value) => {
    const text = clean(value);
    if (text && !seen.has(text)) {
      seen.add(text);
      result.push(text);
    }
  });
  return result;
}

function matchesPrefix(path, row, beforeLevel) {
  for (let level = 1; level < beforeLevel; level += 1) {
    const selected = rowValue(row, level);
    if (selected && selected !== valueAt(path, level)) return false;
  }
  return true;
}

export function accountOptions(row = {}, level = 1, paths = EXPENSE_ACCOUNT_PATHS) {
  const targetLevel = Number(level);
  if (targetLevel < 1 || targetLevel > 4) return [];
  return uniqueInOrder(
    paths
      .filter((path) => matchesPrefix(path, row, targetLevel))
      .map((path) => valueAt(path, targetLevel))
  );
}

function exactThirdLevelPaths(row, paths) {
  return paths.filter((path) => [1, 2, 3].every((level) => rowValue(row, level) === valueAt(path, level)));
}

function levelError(lineNo, level, message) {
  return '第 ' + lineNo + ' 行：' + level + '级费用科目' + message;
}

export function validateExpenseAccount(row = {}, lineNo = 1, paths = EXPENSE_ACCOUNT_PATHS, allowUnknown = false) {
  const errors = [];
  for (let level = 1; level <= 3; level += 1) {
    if (!rowValue(row, level)) errors.push(levelError(lineNo, level, '不能为空'));
  }
  if (errors.length) return errors;

  for (let level = 1; level <= 2; level += 1) {
    const options = accountOptions(row, level, EXPENSE_ACCOUNT_PATHS);
    const value = rowValue(row, level);
    if (!options.includes(value)) {
      errors.push(levelError(lineNo, level, level === 1 ? '不在固定分类中' : '不属于固定的上级费用科目'));
      return errors;
    }
  }

  const matchingThird = exactThirdLevelPaths(row, paths);
  if (!matchingThird.length) {
    return allowUnknown ? [] : [levelError(lineNo, 3, '不在分类表中')];
  }

  const fourthValue = rowValue(row, 4);
  const exact = matchingThird.some((path) => valueAt(path, 4) === fourthValue);
  if (exact) return [];

  if (allowUnknown) return [];
  const fourthOptions = uniqueInOrder(matchingThird.map((path) => path.account_level_4));
  if (!fourthValue && fourthOptions.length) {
    return [levelError(lineNo, 4, '必须选择：' + fourthOptions.join('、'))];
  }
  if (fourthValue) {
    return [levelError(lineNo, 4, '不属于所选3级费用科目' + (fourthOptions.length ? '，可选：' + fourthOptions.join('、') : ''))];
  }
  return [levelError(lineNo, 4, '应为空')];
}

export function unknownExpenseAccountPaths(rows = [], paths = EXPENSE_ACCOUNT_PATHS) {
  const known = new Set(paths.map((path) => LEVEL_FIELDS.map((_, index) => valueAt(path, index + 1)).join('\u001f')));
  const seen = new Set();
  const result = [];
  rows.forEach((row) => {
    if (validateExpenseAccount(row, 1, paths, true).length) return;
    const normalized = Object.fromEntries(LEVEL_FIELDS.map((field, index) => [field, rowValue(row, index + 1)]));
    const key = LEVEL_FIELDS.map((field) => normalized[field]).join('\u001f');
    if (!known.has(key) && !seen.has(key)) {
      seen.add(key);
      result.push(normalized);
    }
  });
  return result;
}

export function clearInvalidLowerLevels(row = {}, changedLevel = 1, paths = EXPENSE_ACCOUNT_PATHS) {
  for (let level = Number(changedLevel) + 1; level <= 4; level += 1) {
    const field = LEVEL_FIELDS[level - 1];
    const value = rowValue(row, level);
    if (!value) continue;
    const options = accountOptions(row, level, paths);
    if (!options.includes(value)) row[field] = '';
  }
}
