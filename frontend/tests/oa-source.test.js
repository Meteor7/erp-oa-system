import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const routerSource = readFileSync(new URL('../src/router.js', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const accessSource = readFileSync(new URL('../src/lib/access.js', import.meta.url), 'utf8');
const pageSource = readFileSync(new URL('../src/pages/OAApprovals.vue', import.meta.url), 'utf8');
const workbenchSource = readFileSync(new URL('../src/components/ExpenseWorkbench.vue', import.meta.url), 'utf8');
const apiSource = readFileSync(new URL('../../rayher_hr_payroll/api/oa_entry.py', import.meta.url), 'utf8');

test('rayher SPA registers split approval pages', () => {
  assert.match(routerSource, /path:\s*['\"]\/approval\/leave['\"]/);
  assert.match(routerSource, /path:\s*['\"]\/approval\/purchase['\"]/);
  assert.match(routerSource, /path:\s*['\"]\/oa['\"],\s*redirect:\s*['\"]\/approval\/leave['\"]/);
  assert.match(accessSource, /['\"]\/approval\/leave['\"]/);
  assert.match(accessSource, /['\"]\/approval\/purchase['\"]/);
  assert.match(appSource, /\\u5ba1\\u6279/);
  assert.match(appSource, /\\u8bf7\\u5047\\u5ba1\\u6279/);
  assert.match(appSource, /\\u8d39\\u7528\\u4ed8\\u6b3e\/\\u62a5\\u9500/);
});

test('approval page fixes request type from route and filters lists by type', () => {
  assert.match(pageSource, /useRoute/);
  assert.match(pageSource, /PAGE_CONFIG/);
  assert.match(pageSource, /\/approval\/leave/);
  assert.match(pageSource, /\/approval\/purchase/);
  assert.match(pageSource, /request_type:\s*currentRequestType\.value/);
  assert.doesNotMatch(pageSource, /<select\s+v-model='form\.request_type'/);
  assert.match(pageSource, /preview\.data = null/);
  assert.match(pageSource, /function previewPayload/);
  assert.match(pageSource, /supervisor:\s*leaveForm\.supervisor\.trim\(\)\s*\|\|\s*T\.supervisor/);
});

test('approval page supports leave plus expense board and consumption pushdown actions', () => {
  assert.match(pageSource, /ExpenseWorkbench/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.preview_route/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.create_request/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.list_requests/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.action_request/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.list_consumption_details/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.save_consumption_detail/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.add_invoice/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.push_consumption_to_request/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.submit_request/);
  assert.match(pageSource, /rayher_hr_payroll\.api\.oa_entry\.mark_paid/);
  assert.match(pageSource, /\\u8bf7\\u5047\\u7533\\u8bf7/);
  assert.match(pageSource, /\\u8d39\\u7528\\u4ed8\\u6b3e\\u7533\\u8bf7/);
  assert.match(pageSource, /\\u5ba1\\u6279\\u6d41\\u7a0b/);
  assert.match(pageSource, /STATUS_COLUMNS/);
  assert.match(pageSource, /purchaseTab\s*=\s*ref\('board'\)/);
  assert.match(pageSource, /kanban_status/);
  assert.match(pageSource, /pushSelection/);
  assert.match(pageSource, /selectedConsumption/);
  assert.match(pageSource, /\\u4ed8\\u6b3e\/\\u62a5\\u9500\\u5355\\u770b\\u677f/);
  assert.match(pageSource, /\\u6d88\\u8d39\\u660e\\u7ec6/);
  assert.match(pageSource, /\\u4e0b\\u63a8\\u751f\\u6210\\u4ed8\\u6b3e\\u5355/);
  assert.match(pageSource, /\\u6807\\u8bb0\\u5df2\\u4ed8\\u6b3e/);
  assert.match(pageSource, /\\u884c\\u653f\\u56fa\\u5b9a\\u8d44\\u4ea7/);
  assert.match(pageSource, /\\u0049\\u0054\\u7c7b\\u56fa\\u5b9a\\u8d44\\u4ea7/);
});

test('expense workbench implements the five reference-platform views with a horizontal kanban', () => {
  for (const label of ['付款/报销单', '消费明细', '审批流配置', '费用统计', '审批记录']) {
    assert.ok(workbenchSource.includes(label));
  }
  assert.match(workbenchSource, /STATUS_COLUMNS/);
  assert.match(workbenchSource, /grid-cols-5/);
  assert.match(workbenchSource, /总申请数/);
  assert.match(workbenchSource, /本月申请总额/);
  assert.match(workbenchSource, /已付款总额/);
  assert.match(workbenchSource, /批量下推/);
  assert.match(workbenchSource, /发票查看限制/);
  assert.match(workbenchSource, /费用分类汇总/);
  assert.match(workbenchSource, /审批记录列表/);
});

test('expense workbench uses real APIs for files, approvals, payment and export', () => {
  assert.match(workbenchSource, /\/api\/method\/upload_file/);
  assert.match(workbenchSource, /invoice_file/);
  assert.match(workbenchSource, /push_consumption_to_request/);
  assert.match(workbenchSource, /action_request/);
  assert.match(workbenchSource, /mark_paid/);
  assert.match(workbenchSource, /exportTableWorkbook/);
  assert.match(workbenchSource, /preview_route/);
});

test('approval API exposes expense reimbursement board and pushdown endpoints', () => {
  assert.match(apiSource, /def list_requests\(view=["']mine["'], limit=50, request_type=None\):/);
  assert.match(apiSource, /request_type and request_type not in REQUEST_TYPES/);
  assert.match(apiSource, /filters\[['"]request_type['"]\] = request_type/);
  assert.match(apiSource, /def list_consumption_details\(view=["']mine["'], status=None, limit=100\):/);
  assert.match(apiSource, /def save_consumption_detail\(name=None, title=None, category=None, expense_date=None, amount=None, department=None, description=None\):/);
  assert.match(apiSource, /def add_invoice\(/);
  assert.match(apiSource, /def push_consumption_to_request\(consumption_names, payment_info=None, submit=0\):/);
  assert.match(apiSource, /if not doc\.invoices:/);
  assert.match(apiSource, /source_type=SOURCE_PUSH/);
  assert.match(apiSource, /def mark_paid\(name, note=None\):/);
  assert.match(apiSource, /doc\.workflow_status = STATUS_PAID/);
  assert.match(apiSource, /["']creation["']:\s*doc\.creation/);
});
