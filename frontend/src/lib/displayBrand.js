export function displayCompany(value) {
  const label = String(value ?? '').trim();
  if (/^(qiheng(?: demo)?|示例企业032有限公司|示例总部)$/i.test(label)) return '栖衡科技';
  if (label === 'QIHENG DEMO OVERSEAS') return '栖衡海外研发';
  if (label === '示例研发中心') return '栖衡研发';
  return label;
}

export function displayDepartment(value) {
  return String(value ?? '').trim().replace(/\s*-\s*(RAY|SHGL)$/i, '');
}

export function displayUser(value) {
  const label = String(value ?? '').trim();
  return /^qiheng(?: demo)?\s+admin$/i.test(label) ? '栖衡 管理员' : label;
}
