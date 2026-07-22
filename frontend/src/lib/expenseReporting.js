const STATISTICS_FIELDS = Object.freeze({
  fromDate: 'from_date',
  toDate: 'to_date',
  department: 'department',
  employee: 'employee',
  invoiceCategory: 'invoice_category',
  expenseItem: 'expense_item',
  projectName: 'project_name',
  workflowStatus: 'workflow_status',
  paymentStatus: 'payment_status',
  sourceType: 'source_type',
});

const APPROVAL_FIELDS = Object.freeze({
  requestKeyword: 'request_keyword',
  employee: 'employee',
  department: 'department',
  approver: 'approver',
  action: 'action',
  workflowStatus: 'workflow_status',
  fromDate: 'from_date',
  toDate: 'to_date',
});

function mappedParams(filters, fields) {
  const params = { view: 'all', limit: 1000 };
  for (const [clientKey, serverKey] of Object.entries(fields)) {
    const value = filters?.[clientKey];
    if (value === null || value === undefined) continue;
    const cleaned = typeof value === 'string' ? value.trim() : value;
    if (cleaned !== '') params[serverKey] = cleaned;
  }
  return params;
}

export function toExpenseStatisticsParams(filters) {
  return mappedParams(filters, STATISTICS_FIELDS);
}

export function toApprovalRecordParams(filters) {
  return mappedParams(filters, APPROVAL_FIELDS);
}

export function money(value) {
  const parsed = Number(value);
  const safe = Number.isFinite(parsed) ? parsed : 0;
  return `¥${safe.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function dateTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-';
}
