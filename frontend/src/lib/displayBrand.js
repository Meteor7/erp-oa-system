export function displayCompany(value) {
  const label = String(value ?? '').trim();
  if (/^rayher$/i.test(label)) return '示例总部';
  if (label === '示例研发中心') return '示例研发中心';
  return label;
}

export function displayDepartment(value) {
  return String(value ?? '').trim().replace(/\s*-\s*(RAY|SHGL)$/i, '');
}

export function displayUser(value) {
  const label = String(value ?? '').trim();
  return /^rayher\s+admin$/i.test(label) ? 'QIHENG DEMO 管理员' : label;
}
