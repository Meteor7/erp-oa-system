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
  // 一张打开这一张，多张打开该类型"待我处理"的列表（逻辑在 lib/navContext.js 的 approvalTodoTarget，有单测）
  assert.match(source, /approvalTodoTarget\(item\)/);
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
  // 后端给的 query（价格审批 approval=、PO po=）优先，没有才是 request=单号（queueTarget）
  assert.match(source, /queueTarget\(item\)/);
});

test('every link out of the dashboard carries its context (2026-10 navigation audit)', () => {
  assert.match(source, /noteTarget\(item\)/);
  assert.match(source, /myRequestTarget\(item\)/);
  assert.match(source, /openMyRequest\(item\)/);
  assert.doesNotMatch(source, /@click="openQueueItem\(item\)">\{\{ item\.returned/, '"修改后重新提交" opens the draft, not the read-only detail');
  // 研发台账 had route '/ledger' (no page, no role rule): the row was silently hidden for everyone
  assert.doesNotMatch(source, /route: '\/ledger'/);
  assert.match(source, /route: '\/entry', n: '02', h: '研发台账'/);
});

test('notifications read as plain language, grouped per document', () => {
  assert.match(source, /get_my_notification_feed/);
  assert.match(source, /mark_notifications_read/);
  assert.match(source, /noteCategory/);
  assert.match(source, /只看未读/);
  assert.match(source, /该单据还有/);
  assert.match(source, /本类全部已读/);
});

test('period params exist before any auto-fetching resource is created', () => {
  // an auto resource calls makeParams immediately; a later const would throw and leave the tab empty
  const defined = source.indexOf('const currentPeriod = computed(');
  const firstResource = source.indexOf('createResource(');
  assert.ok(defined > -1 && firstResource > -1);
  assert.ok(defined < firstResource);
});

test('the cost block flags preview numbers with a small tag driven by the payload', () => {
  assert.match(source, /from '\.\.\/lib\/previewTags'/);
  assert.match(source, /costPreviewTag\(cost\.data\)/);
  assert.match(source, /costPreviewTag\(d\.data\)/);
  assert.match(source, /v-if="costPreview"/);
  assert.match(source, /:title="costPreview\.title"/);
  assert.match(source, /\{\{ costPreview\.text \}\}/);
});
