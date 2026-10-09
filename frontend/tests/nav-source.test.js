import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

// 导航整改（2026-10）的接线检查：这些页面都是 Vue 单文件，逻辑本身在 lib/navContext.js（有单测），
// 这里确认页面确实用了它，旧的写法没有留下。
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const exists = (path) => existsSync(new URL(path, import.meta.url));

const router = read("../src/router.js");
const app = read("../src/App.vue");
const claim = read("../src/components/claim/ClaimWorkbench.vue");
const travel = read("../src/components/travel/TravelWorkbench.vue");
const purchaseHome = read("../src/components/procurement/PurchaseHome.vue");
const procHome = read("../src/components/procurement/ProcHome.vue");
const procList = read("../src/components/procurement/ProcList.vue");
const procDetail = read("../src/components/procurement/ProcDetail.vue");
const procForm = read("../src/components/procurement/ProcForm.vue");
const procWorkbench = read("../src/components/procurement/ProcurementWorkbench.vue");
const legacy = read("../src/components/ExpenseWorkbench.vue");
const approvalDashboard = read("../src/pages/ApprovalDashboard.vue");
const tabs = read("../src/components/AccommodationTabs.vue");
const requestBoard = read("../src/pages/RequestBoard.vue");
const paymentBoard = read("../src/pages/PaymentBoard.vue");
const poDetail = read("../src/components/price/PoDetail.vue");
const priceWorkbench = read("../src/components/price/PriceWorkbench.vue");

// ---------------------------------------------------------------- router and shell

test("router: unauthorized deep links redirect with a notice, unknown paths get a 404 page, old prefixes still work (P2-11)", () => {
  assert.match(router, /setDeniedNotice\(to\.path, fallback\)/);
  assert.match(router, /return \{ path: fallback, replace: true \}/);
  assert.match(router, /to\.name === 'not-found'/, "the 404 page is never redirected by the permission guard");
  assert.match(router, /path: '\/:pathMatch\(\.\*\)\*', name: 'not-found'/);
  assert.match(router, /pages\/NotFound\.vue/);
  assert.ok(exists("../src/pages/NotFound.vue"));
  assert.match(read("../src/pages/NotFound.vue"), /页面不存在/);
  assert.match(read("../src/pages/NotFound.vue"), /firstVisiblePath/);
  // old notification links: /rayher/... and /planck-semicon/... keep path and query
  assert.match(router, /path: '\/rayher\/:rest\(\.\*\)\*'/);
  assert.match(router, /stripAppPrefix\(to\.fullPath\)/);
  // the catch-all must come after every real route
  assert.ok(router.indexOf("name: 'not-found'") > router.indexOf("path: '/foreign-rd-timesheet'"));
  // attendance routes stay (others implement the page)
  for (const path of ["/approval/leave", "/approval/overtime", "/approval/comp-time", "/approval/leave/:name", "/approval/overtime/:name", "/approval/comp-time/:name"]) {
    assert.ok(router.includes(`path: '${path}'`), path);
  }
});

test("app shell: notice banner, 404 is not a 403, notification links go through stripAppPrefix (P2-11)", () => {
  assert.match(app, /routeNotice/);
  assert.match(app, /deniedNoticeText\(/);
  assert.match(app, /data-testid='route-notice'/);
  assert.match(app, /clearRouteNotice/);
  assert.match(app, /route\.name === 'not-found' \|\| canSee\(route\.path\)/);
  assert.match(app, /stripAppPrefix\(item\.link, window\.location\.host\)/);
  assert.doesNotMatch(app, /startsWith\('\/planck-semicon\/'\)/, "the old prefix handling only knew /planck-semicon/");
});

test("sidebar: group header links to the attendance home, children highlight by path prefix, any group auto-expands (P3-13)", () => {
  assert.match(app, /\{ to: '\/approval\/attendance\?view=home', step: '01', label: '请假\/加班\/调休', children: \[/);
  assert.ok(app.includes("{ to: '/approval/leave', label: '请假审批' }"));
  assert.ok(app.includes("{ to: '/approval/overtime', label: '加班审批' }"));
  assert.ok(app.includes("{ to: '/approval/comp-time', label: '调休审批' }"));
  assert.match(app, /ownerOfPath\(route\.path, allNavTargets\)/);
  assert.match(app, /groupOwning\(path, groupedItems\)/);
  assert.match(app, /isNavActive\(child\.to\)/);
  assert.doesNotMatch(app, /ACCOMMODATION_PATHS/, "only the dorm group used to auto-expand");
  assert.doesNotMatch(app, /active-class=/, "highlight comes from the owning item, not from an exact link match");
});

test("naming: dorm tabs use the sidebar names; the PO tab says what it is (P3-16)", () => {
  assert.match(app, /label: '宿舍基本信息管理'/);
  assert.match(app, /label: '当月费用管理'/);
  assert.match(tabs, /label: '宿舍看板'/);
  assert.match(tabs, /label: '宿舍基本信息管理'/);
  assert.match(tabs, /label: '当月费用管理'/);
  assert.doesNotMatch(tabs, /房间管理|当月费用登记/);
  assert.match(priceWorkbench, /\{\{ pageTitle\(tab\) \}\}/);
});

// ---------------------------------------------------------------- claim / payment workbench

test("claim form: 上传新发票 opens a new tab, keeps the form, and the invoice list can be refreshed (P1-3)", () => {
  assert.doesNotMatch(claim, /router\.push\('\/approval\/invoice-folder'\)[^\n]*上传新发票/);
  assert.match(claim, /window\.open\(href, '_blank', 'noopener'\)/);
  assert.match(claim, /router\.resolve\(\{ path: '\/approval\/invoice-folder' \}\)/);
  assert.equal((claim.match(/@click="openInvoiceFolder"/g) || []).length >= 3, true, "supplement panel, claim step 1 and payment invoice panel");
  assert.match(claim, /刷新可用发票/);
  assert.match(claim, /window\.addEventListener\('focus', onWindowFocus\)/);
  assert.match(claim, /window\.removeEventListener\('focus', onWindowFocus\)/);
  // the refresh merges instead of replacing, so selected / draft invoices survive
  assert.match(claim, /\[\.\.\.draftInvoices\.value, \.\.\.pickedInvoices\.value, \.\.\.fresh\]/);
  assert.match(claim, /list_available_invoices/);
});

test("claim lists keep scope, bucket and search in the URL, and detail links carry them back (P2-4, P2-6)", () => {
  assert.match(claim, /resolveScope\(route\.query\.scope/);
  assert.match(claim, /role="status" data-testid="scope-notice"/);
  assert.match(claim, /normalizeBucket\(route\.query\.bucket\)/);
  assert.match(claim, /data-testid="bucket-filter"/);
  assert.match(claim, /bucket: 'draft'/);
  assert.match(claim, /bucket: 'review'/);
  assert.match(claim, /bucket: 'topay'/);
  assert.match(claim, /go\(\{ view: 'list', scope: 'all', bucket: bucket\.key \}\)/);
  assert.match(claim, /go\(detailQuery\(doc\.name, listFilters\)\)/);
  assert.match(claim, /go\(formQuery\(\{ view: 'new', draft: doc\.name \}, listFilters\)\)/);
  assert.match(claim, /@click="backToList">列表</);
  assert.doesNotMatch(claim, /@click="go\(\{ view: 'list', scope \}\)">列表/, "the 列表 crumb used to forget the filters");
  assert.match(claim, /query: \{ \.\.\.next, \.\.\.cleanQuery\(\{ q: search\.value/);
});

test("claim form: cancel returns to the origin and a dirty form asks before it is abandoned (P2-5)", () => {
  assert.match(claim, /useLeaveConfirm\(\(\) => dirty\.value\)/);
  assert.match(claim, /@click="goBack">取消</);
  assert.doesNotMatch(claim, /@click="go\(\{\}\)">取消</);
  assert.match(claim, /carryQuery\(route\.query\)/);
  assert.match(claim, /markClean\(\)/);
});

test("claim: pushing from an application asks before it creates a draft (P3-14)", () => {
  // the instant creation is gone from the page-entry path; it now lives behind a confirm button
  const enter = claim.slice(claim.indexOf("async function enterNewPage()"), claim.indexOf("function togglePicked"));
  assert.doesNotMatch(enter, /push_from_application/);
  const confirmFn = claim.slice(claim.indexOf("async function confirmSource()"), claim.indexOf("function cancelSource()"));
  assert.match(confirmFn, /push_from_application/);
  assert.match(claim, /pendingSource\.value = String\(route\.query\.source\)/);
  assert.match(claim, /data-testid="push-confirm"/);
  assert.match(claim, /pushConfirmText\(props\.kind, pendingSource\)/);
  assert.match(claim, /@click="confirmSource">确定创建</);
  assert.match(claim, /@click="cancelSource">取消</);
  assert.match(claim, /v-if="!pendingSource" class="new-grid"/);
  assert.doesNotMatch(claim, /window\.confirm/);
});

// ---------------------------------------------------------------- travel

test("travel: scope notice, status buckets, return to origin, leave confirm, honest heading (P2, P3-15)", () => {
  assert.match(travel, /travelScopeInfo\(route\.query\.scope, canAll\)/);
  assert.match(travel, /data-testid="scope-notice"/);
  assert.match(travel, /normalizeTravelBucket\(route\.query\.bucket\)/);
  assert.match(travel, /data-testid="bucket-filter"/);
  assert.match(travel, /go\(detailQuery\(row\.name, listFilters\)\)/);
  assert.match(travel, /@click="backToList">列表</);
  assert.doesNotMatch(travel, /scope: focusOwn \? 'mine' : 'todo' \}\)">列表/, "guessing the list is only the fallback now");
  assert.match(travel, /useLeaveConfirm\(/);
  assert.match(travel, /@click="goBack">取消</);
  assert.doesNotMatch(travel, /resetForm\(\); go\(\{\}\)/);
  assert.doesNotMatch(travel, /<b>全部出差申请<\/b>/, "that table only shows my first 8");
  assert.match(travel, /我的出差申请/);
});

// ---------------------------------------------------------------- procurement

test("购买申请首页: scope, status and search live in the URL; cards carry a status; list opens carry the state (P2-4, P2-6)", () => {
  assert.doesNotMatch(purchaseHome, /const scope = ref\(/, "scope used to be a local ref the URL knew nothing about");
  assert.match(purchaseHome, /const scope = computed\(\(\) => listScope\(route\.query, 'mine'\)\)/);
  assert.match(purchaseHome, /normalizePurchaseStatus\(route\.query\.status\)/);
  for (const status of ["'draft'", "'review'", "'topay'"]) assert.ok(purchaseHome.includes(`status: ${status}`), status);
  assert.match(purchaseHome, /ctx\.go\(detailQuery\(row\.name, listFilters\.value\)\)/);
  assert.match(purchaseHome, /ctx\.goNew\(formQuery\(\{ draft: row\.name \}, listFilters\.value\)\)/);
  assert.match(purchaseHome, /data-testid="status-filter"/);
  assert.match(purchaseHome, /setListQuery\(\{ status: '' \}\)/);
});

test("采购申请 cards filter the list with the same grouping they count by (P2-6)", () => {
  assert.match(procHome, /scope: 'all', stage: 'exec'/);
  assert.match(procHome, /scope: 'mine', stage: 'back'/);
  assert.match(procHome, /scope: 'mine', stage: 'exec'/);
  assert.match(procList, /STAGE_GROUP_FILTERS/);
  assert.match(procList, /normalizeStage\(route\.query\.stage\)/);
  assert.match(procList, /data-testid="stage-filter"/);
  assert.match(procList, /ctx\.go\(detailQuery\(row\.name, listFilters\.value\)\)/);
  // list filters change the URL, not the pane key: no remount on every keystroke
  assert.doesNotMatch(procWorkbench, /route\.query\.stage \|\| ''/);
  assert.match(procWorkbench, /view\.value === 'list' && isProcurement\.value \? \(route\.query\.scope \|\| ''\) : ''/);
});

test("procurement detail and forms go back where the user came from (P2-4, P2-5)", () => {
  assert.doesNotMatch(procDetail, /@click="ctx\.go\(\{ view: 'list' \}\)">列表/);
  assert.match(procDetail, /@click="backToList">列表</);
  assert.match(procDetail, /backLocation\(route\.path, route\.query\)/);
  assert.match(procForm, /useLeaveConfirm\(isDirty\)/);
  assert.match(procForm, /else goBack\(\);/);
  assert.doesNotMatch(procForm, /else ctx\.go\(\{\}\);/, "cancel used to always go home");
  assert.match(procForm, /\.\.\.carryQuery\(route\.query\)/);
  assert.match(procForm, /if \(wasClean\) markClean\(\)/, "system-filled defaults do not count as user edits");
});

test("PO links to 采购付款 carry the PO (P2-9)", () => {
  assert.match(poDetail, /paymentPoLink\(po\)/);
  assert.match(procDetail, /paymentPoLink\(po\)/);
  assert.match(procDetail, /paymentPoLink\(poRows\.length === 1 \? poRows\[0\] : null\)/);
  assert.doesNotMatch(procDetail, /<router-link to="\/approval\/procurement-payment"/);
});

// ---------------------------------------------------------------- legacy pages and boards

test("legacy 付款/报销 page opens the document from ?request= (P2-10)", () => {
  assert.match(legacy, /import \{ useRoute, useRouter \} from 'vue-router'/);
  assert.match(legacy, /watch\(\(\) => route\.query\.request, \(name\) => \{/);
  assert.match(legacy, /openRequest\(wanted\)/);
  assert.match(legacy, /\{ immediate: true \}/);
  // closing the dialog frees the same link to be opened again
  assert.match(legacy, /router\.replace\(\{ path: route\.path, query: \{\} \}\)/);
});

test("申请看板 / 付款看板 pages: unreachable cards are disabled; everything they open comes back to the board (P2-7)", () => {
  for (const board of [requestBoard, paymentBoard]) {
    assert.match(board, /boardAccess\(\)/);
    assert.match(board, /:disabled="!kpi\.to"/);
    assert.match(board, /v-if="kpi\.to" aria-hidden="true"/);
    assert.match(board, /hereAsFrom\(route\.path, route\.query\)/);
    assert.match(board, /withFrom\(kpi\.to,/);
  }
  assert.match(requestBoard, /requestKpis\(data\.value, access\)/);
  assert.match(paymentBoard, /paymentKpis\(data\.value, access\)/);
  assert.match(read("../src/components/expense-ui/ProcurementTab.vue"), /withFrom\(kpi\.to, here\(\)\)/);
});

test("old 看板 page shows the source_request filter and opens documents by their own type (P3-15)", () => {
  assert.match(approvalDashboard, /const linkedRequest = computed\(/);
  assert.match(approvalDashboard, /data-testid="linked-filter"/);
  assert.match(approvalDashboard, /boardRoute\(row\.request_type\)/);
  assert.match(approvalDashboard, /from: hereAsFrom\(route\.path, route\.query\)/);
});
