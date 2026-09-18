import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages/Dashboard.vue", import.meta.url), "utf8");

test("personal approval todos render independently of company dashboard permission", () => {
  const personalTodos = source.indexOf("要我处理");
  const companyLoading = source.indexOf('v-if="d.loading"');
  const companyData = source.indexOf('v-else-if="d.data"');
  assert.ok(personalTodos > -1);
  assert.ok(personalTodos < companyLoading);
  assert.ok(personalTodos < companyData);
  assert.match(source, /oaTodos\.data\?\.total/);
  assert.match(source, /oaTodos\.error/);
});

test("dashboard presents personal queues as actionable categories", () => {
  assert.match(source, /todoCategories/);
  assert.match(source, /openApprovalTodo\(item\)/);
  assert.match(source, /item\.requests\?\./);
  assert.match(source, /我的待办与公司经营数据/);
  assert.match(source, /月度核算流程/);
  assert.match(source, /数据完整度/);
});

test("tabs appear only for the data the server says the user may see", () => {
  assert.match(source, /costVisible = computed\(\(\) => Boolean\(cost\.data\?\.visible\)\)/);
  assert.match(source, /hrVisible = computed\(\(\) => Boolean\(hr\.data\?\.visible\)\)/);
  assert.match(source, /key: 'biz', label: '经营看板', show: costVisible\.value/);
  assert.match(source, /key: 'hr', label: '人事看板', show: hrVisible\.value/);
  // a tab that disappears must never stay selected
  assert.match(source, /if \(!list\.some\(\(item\) => item\.key === tab\.value\)\) tab\.value = list\[0\]\?\.key/);
});

test("cost views follow the month or year period selector", () => {
  assert.match(source, /get_cost_overview/);
  assert.match(source, /get_project_cost_detail/);
  assert.match(source, /get_hr_overview/);
  assert.match(source, /get_my_leave_summary/);
  assert.match(source, /makeParams: \(\) => \(\{ scope: scope\.value, period: currentPeriod\.value \}\)/);
  assert.match(source, /watch\(\[scope, year\], reloadScope\)/);
});

test("charts import only the pieces the dashboard draws", () => {
  assert.match(source, /from 'echarts\/core'/);
  assert.match(source, /BarChart, LineChart, PieChart/);
  assert.match(source, /CanvasRenderer/);
  assert.doesNotMatch(source, /from 'echarts'/);
  assert.match(source, /chart\.dispose\(\)/);
});

test("personal leave balance is shown in days", () => {
  assert.match(source, /1 天 = 8 小时/);
  assert.match(source, /myLeave\.data\.annual\.available/);
  assert.match(source, /myLeave\.data\.comp\.available/);
});

test('the approval queue lists real requests with waiting time', () => {
  assert.match(source, /get_my_approval_queue/);
  assert.match(source, /get_my_requests/);
  assert.match(source, /queueItems/);
  assert.match(source, /已超时/);
  assert.match(source, /去审批/);
  assert.match(source, /修改后重新提交/);
});

test('the queue is one list covering approvals and hands-on tasks', () => {
  assert.match(source, /要我处理/);
  assert.match(source, /item\.reason/);
  assert.match(source, /'价格审批'/);
  assert.match(source, /'采购订单'/);
  assert.match(source, /item\.query \|\| \{ request: item\.name \}/);
});

test('notifications read as plain language, grouped per document', () => {
  assert.match(source, /get_my_notification_feed/);
  assert.match(source, /mark_notifications_read/);
  assert.match(source, /noteCategory/);
  assert.match(source, /只看未读/);
  assert.match(source, /该单据还有/);
  assert.match(source, /本类全部已读/);
});
