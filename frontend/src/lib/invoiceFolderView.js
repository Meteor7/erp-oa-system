// 发票夹前端逻辑：状态分组、可操作性判断、上传后的轮询条件。
export const FOLDER_TABS = Object.freeze([
  { key: '', label: '全部' },
  { key: '识别中', label: '识别中' },
  { key: '待确认', label: '待确认' },
  { key: '可用', label: '可用' },
  { key: '已使用', label: '已使用' },
  { key: '疑似重复', label: '疑似重复' },
  { key: '识别失败', label: '识别失败' },
]);

export const FOLDER_TONES = Object.freeze({
  识别中: 'bg-blue-50 text-blue-700',
  待确认: 'bg-amber-50 text-amber-700',
  可用: 'bg-emerald-50 text-emerald-700',
  已使用: 'bg-gray-100 text-gray-600',
  疑似重复: 'bg-red-50 text-red-700',
  识别失败: 'bg-red-50 text-red-700',
  已排除: 'bg-gray-100 text-gray-500',
});

export function folderTone(status) {
  return FOLDER_TONES[String(status || '').trim()] || 'bg-gray-100 text-gray-700';
}

export function tabsWithCounts(counts = {}) {
  const total = FOLDER_TABS.slice(1).reduce((sum, tab) => sum + Number(counts[tab.key] || 0), 0);
  return FOLDER_TABS.map((tab) => ({ ...tab, count: tab.key ? Number(counts[tab.key] || 0) : total }));
}

export function canEditFields(invoice) {
  // OCR 识别不出来时也要能手工改，所以待确认和疑似重复都允许编辑。
  return ['待确认', '疑似重复'].includes(String(invoice?.folder_status || '').trim());
}

export function canConfirm(invoice) {
  return String(invoice?.folder_status || '').trim() === '待确认';
}

export function canRetry(invoice) {
  return String(invoice?.folder_status || '').trim() === '识别失败';
}

export function canUse(invoice) {
  return String(invoice?.folder_status || '').trim() === '可用';
}

export function stillRecognizing(invoices) {
  return (invoices || []).some((invoice) => String(invoice?.folder_status || '').trim() === '识别中');
}

export function missingFields(invoice) {
  const required = [
    ['invoice_category', '发票类别'],
    ['project_name', '项目名称'],
    ['issue_date', '开票日期'],
    ['invoice_number', '发票号码'],
    ['total_amount', '合计'],
    ['expense_description', '费用说明'],
  ];
  return required
    .filter(([field]) => {
      const value = invoice?.[field];
      if (field === 'total_amount') return !Number(value);
      return !String(value ?? '').trim();
    })
    .map(([, label]) => label);
}

export function confirmBlockers(invoice) {
  const missing = missingFields(invoice);
  return missing.length ? [`确认前请补全：${missing.join('、')}`] : [];
}

export function usedByText(invoice) {
  const used = invoice?.used_by;
  if (!used) return '';
  return [used.request_type, used.name, used.business_status || used.workflow_status].filter(Boolean).join(' · ');
}
