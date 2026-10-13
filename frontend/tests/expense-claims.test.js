import assert from "node:assert/strict";
import test from "node:test";
import {
  CLAIM_KINDS,
  accountBlockers,
  accountDraftFor,
  applicationLabel,
  claimDraftPayload,
  claimKind,
  claimTabs,
  displayStatus,
  isFinanceUser,
  maskAccount,
  pillClass,
  quotaOf,
  stepChips,
  money,
  overBudget,
  statusTone,
  submitBlockers,
  sumAmount,
  withDefaultProjects,
} from "../src/lib/expenseClaims.js";
import {
  canConfirm,
  editableByOwner,
  filterFolder,
  folderTabs,
  folderTabsFromCounts,
  retryState,
  duplicateText,
  tabStatuses,
  canEditFields,
  canRetry,
  confirmBlockers,
  folderTone,
  missingFields,
  stillRecognizing,
  tabsWithCounts,
  usedByText,
} from "../src/lib/invoiceFolderView.js";
import { canSee, firstVisiblePath, inMenu } from "../src/lib/access.js";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

const purchase = { name: "OA-1", request_type: "购买申请", subject: "打印纸", available_amount: 300 };
const travel = { name: "OA-2", request_type: "出差申请", subject: "北京展会", travel_destination: "北京", travel_start_date: "2026-10-21" };

function claimForm(overrides = {}) {
  return { source_request: "OA-1", subject: "办公用品报销", payment_method: "银行转账", ...overrides };
}

function paymentForm(overrides = {}) {
  return {
    source_request: "OA-1", subject: "服务费付款", payment_method: "银行转账",
    payee_name: "供应商", bank_name: "招商银行", account_no: "6225", ...overrides,
  };
}

const invoice = (name, total) => ({ name, total_amount: total, project_name: "办公用品", expense_description: "打印纸" });
const line = (amount, overrides = {}) => ({ project_name: "服务费", expense_description: "季度服务", total_amount: amount, ...overrides });

test("claim kinds map both ways and carry their route and flag", () => {
  assert.equal(claimKind("报销单"), CLAIM_KINDS.claim);
  assert.equal(claimKind("payment"), CLAIM_KINDS.payment);
  assert.equal(claimKind("费用付款申请"), null);
  assert.deepEqual([CLAIM_KINDS.claim.path, CLAIM_KINDS.claim.flag], ["/approval/claim", "reimbursement_request"]);
  assert.deepEqual([CLAIM_KINDS.payment.path, CLAIM_KINDS.payment.flag], ["/approval/payment", "payment_request"]);
  // 员工：我的 / 新建；财务：待我处理 / 全部（设计稿第 5 版），不再给所有人"我的 / 待我处理 / 全部可见"。
  assert.deepEqual(claimTabs("claim").map((tab) => tab.label), ["我的报销", "新建报销"]);
  // 财务：待我处理 / 全部，自己也要报销、付款，所以还有我的 / 新建
  assert.deepEqual(claimTabs("payment", true, { todo: 2, all: 9, list: 1 }).map((tab) => [tab.label, tab.count]),
    [["待我处理", 2], ["全部付款", 9], ["我的付款", 1], ["新建付款", undefined]]);
  assert.equal(claimTabs("claim").some((tab) => tab.label === "全部可见"), false);
});

test("amounts are summed in cents so 0.1 + 0.2 stays 0.30", () => {
  assert.equal(sumAmount([line(0.1), line(0.2)]), 0.3);
  assert.equal(sumAmount([invoice("INV-1", "120.55"), invoice("INV-2", 9.45)]), 130);
  assert.equal(money(1234.5), "1,234.50");
});

test("only 购买申请 has a cap", () => {
  assert.equal(overBudget(purchase, 300), false);
  assert.equal(overBudget(purchase, 300.01), true);
  assert.equal(overBudget(travel, 99999), false);
  assert.equal(overBudget(null, 10), false);
  assert.match(applicationLabel(purchase), /剩余 300.00 元/);
  assert.match(applicationLabel(travel), /北京/);
});

test("a 报销单 needs an application, a subject and invoices", () => {
  assert.deepEqual(submitBlockers("claim", claimForm(), { invoices: [invoice("INV-1", 100)], application: purchase }), []);
  assert.deepEqual(submitBlockers("claim", claimForm({ source_request: "" }), { invoices: [invoice("INV-1", 100)] }), ["请选择关联申请"]);
  assert.deepEqual(submitBlockers("claim", claimForm({ subject: " " }), { invoices: [invoice("INV-1", 100)] }), ["请填写主题"]);
  assert.deepEqual(submitBlockers("claim", claimForm(), { invoices: [] }), ["请从发票夹选择至少一张发票"]);
  assert.deepEqual(submitBlockers("claim", claimForm(), { invoices: [invoice("INV-1", 0)] }), ["所选发票缺少合计金额，请先在发票夹补全"]);
  assert.deepEqual(submitBlockers("claim", claimForm(), { invoices: [invoice("INV-1", 400)], application: purchase }), ["发票合计超过关联购买申请的剩余额度"]);
});

test("a 付款单 needs lines, payee details and either invoices or a reason", () => {
  const withInvoice = { lines: [line(100)], invoices: [invoice("INV-1", 100)], application: purchase };
  assert.deepEqual(submitBlockers("payment", paymentForm(), withInvoice), []);
  assert.deepEqual(
    submitBlockers("payment", paymentForm(), { lines: [line(100)], invoices: [invoice("INV-1", 70)] }),
    ["发票合计与付款金额相差超过 0.02 元，请填写差异说明"],
  );
  assert.deepEqual(submitBlockers("payment", paymentForm({ invoice_difference_note: "余款下月开票" }), { lines: [line(100)], invoices: [invoice("INV-1", 70)] }), []);
  assert.deepEqual(submitBlockers("payment", paymentForm(), { lines: [line(100)], invoices: [invoice("INV-1", 99.98)] }), []);
  assert.deepEqual(submitBlockers("payment", paymentForm(), { lines: [line(100)] }), ["暂未取得发票时要填写原因和预计取票日期"]);
  assert.deepEqual(submitBlockers("payment", paymentForm({ no_invoice_reason: "月底开票", expected_invoice_date: "2026-10-30" }), { lines: [line(100)] }), []);
  assert.deepEqual(submitBlockers("payment", paymentForm({ payee_name: "" }), withInvoice), ["银行转账需要填写收款单位、开户行和银行账号"]);
  assert.deepEqual(submitBlockers("payment", paymentForm({ payment_method: "现金支付", payee_name: "" }), withInvoice), []);
  assert.deepEqual(submitBlockers("payment", paymentForm(), { lines: [line(0)], invoices: [invoice("INV-1", 0)] }), ["每行明细的金额必须大于 0"]);
  assert.deepEqual(submitBlockers("payment", paymentForm(), { lines: [line(10, { project_name: "" })], invoices: [invoice("INV-1", 10)] }), ["每行明细都要填写付款内容"]);
  assert.deepEqual(submitBlockers("payment", paymentForm(), { lines: [line(10, { expense_description: "" })], invoices: [invoice("INV-1", 10)] }), ["每行明细都要填写费用说明"]);
});

test("draft payloads only send what the server accepts for that kind", () => {
  const claim = claimDraftPayload("claim", claimForm(), { invoices: [invoice("INV-1", 100)], projects: { "INV-1": "PROJ-1" } });
  assert.deepEqual(claim.invoices, [{ invoice: "INV-1", claim_project: "PROJ-1" }]);
  assert.equal(claim.lines, undefined);
  assert.equal(claim.payee_name, undefined);
  const payment = claimDraftPayload("payment", paymentForm({ expected_invoice_date: "2026-10-30" }), {
    lines: [line(100, { line_key: "L1", claim_project: "PROJ-2" })], invoices: [invoice("INV-9", 100)],
  });
  assert.deepEqual(payment.invoices, ["INV-9"]);
  assert.deepEqual(payment.lines, [{
    line_key: "L1", project_name: "服务费", claim_project: "PROJ-2", issue_date: "",
    total_amount: 100, expense_description: "季度服务",
  }]);
  assert.equal(payment.payee_name, "供应商");
  assert.equal(payment.expected_invoice_date, "2026-10-30");
});

test("the cashier has to classify every line", () => {
  assert.deepEqual(accountBlockers([{ expense_account_level_1: "管理费用", expense_account_level_2: "办公费" }]), []);
  assert.deepEqual(accountBlockers([{ expense_account_level_1: "管理费用", expense_account_level_2: "" }]), ["出纳需要为每行明细选择科目（有二级科目的要选到二级）"]);
  // 没有二级科目的一级科目（如办公费）只填一级即可，和服务端 normalize_account_pair 一致
  const tree = [{ level_1: "差旅费", level_2: ["飞机票"] }, { level_1: "办公费", level_2: [] }];
  assert.deepEqual(accountBlockers([{ expense_account_level_1: "办公费", expense_account_level_2: "" }], tree), []);
  assert.equal(accountBlockers([{ expense_account_level_1: "差旅费", expense_account_level_2: "" }], tree).length, 1);
  assert.equal(accountBlockers([{ expense_account_level_1: "", expense_account_level_2: "" }], tree).length, 1);
  assert.notEqual(statusTone("已付款·待补票"), statusTone("已完结"));
});

test("invoice folder status drives what the employee can do", () => {
  const pending = { folder_status: "待确认", invoice_category: "普通发票", project_name: "打印纸", issue_date: "2026-09-20", invoice_number: "123", total_amount: 100, expense_description: "办公" };
  assert.equal(canEditFields(pending), true);
  assert.equal(canConfirm(pending), true);
  assert.deepEqual(confirmBlockers(pending), []);
  assert.deepEqual(confirmBlockers({ ...pending, invoice_number: "", total_amount: 0 }), ["确认前请补全：发票号码、合计"]);
  // 发票类别可以留空（识别不出来也能确认），其余五项和后端 confirm_invoice 一致。
  assert.deepEqual(missingFields({ folder_status: "待确认" }), ["项目名称", "开票日期", "发票号码", "合计", "费用说明"]);
  assert.deepEqual(confirmBlockers({ ...pending, invoice_category: "" }), []);
  const used = { folder_status: "已使用", used_by: { name: "OA-9", request_type: "报销单", business_status: "已完结" } };
  assert.equal(canEditFields(used), false);
  assert.equal(canConfirm(used), false);
  assert.equal(usedByText(used), "报销单 · OA-9 · 已完结");
  assert.equal(canRetry({ folder_status: "识别失败" }), true);
  assert.equal(canEditFields({ folder_status: "疑似重复" }), true);
  assert.equal(stillRecognizing([{ folder_status: "可用" }, { folder_status: "识别中" }]), true);
  assert.equal(stillRecognizing([{ folder_status: "可用" }]), false);
  assert.notEqual(folderTone("可用"), folderTone("疑似重复"));
  const tabs = tabsWithCounts({ 可用: 2, 已使用: 1 });
  assert.equal(tabs[0].count, 3);
  assert.equal(tabs.find((tab) => tab.key === "可用").count, 2);
});

test("the new pages appear only once their type is switched on", () => {
  globalThis.window = { roles: ["Employee"], oa_access: { leave_approval: true } };
  assert.equal(canSee("/approval/travel"), false);
  assert.equal(canSee("/approval/claim"), false);
  assert.equal(canSee("/approval/payment"), false);
  assert.equal(canSee("/approval/invoice-folder"), false);
  globalThis.window = { roles: ["Employee"], oa_access: { travel_application: true, payment_request: true } };
  assert.equal(canSee("/approval/travel"), true);
  assert.equal(canSee("/approval/claim"), false);
  assert.equal(canSee("/approval/payment"), true);
  assert.equal(canSee("/approval/invoice-folder"), true, "发票夹 opens with either 报销单 or 付款单");
  globalThis.window = { roles: ["Accounts User"], oa_access: { reimbursement_request: true } };
  assert.equal(canSee("/approval/claim"), true);
  assert.equal(canSee("/approval/invoice-folder"), true);
  assert.equal(firstVisiblePath(), "/dashboard");
});

test("the cashier's account draft is built from the document, however it was opened", () => {
  assert.deepEqual(accountDraftFor([
    { line_key: "L1", expense_account_level_1: "差旅费", expense_account_level_2: "飞机票" },
    { line_key: "L2" },
    { expense_account_level_1: "no key" },
  ]), {
    L1: { expense_account_level_1: "差旅费", expense_account_level_2: "飞机票" },
    L2: { expense_account_level_1: "", expense_account_level_2: "" },
  });
  assert.deepEqual(accountDraftFor(undefined), {});
});

test("every selectable invoice starts as 非项目 but keeps a project already chosen", () => {
  assert.deepEqual(withDefaultProjects([{ name: "INV-1" }, { name: "INV-2" }], { "INV-2": "RD01" }), { "INV-1": "", "INV-2": "RD01" });
  assert.deepEqual(withDefaultProjects([], {}), {});
});

test("design helpers: status pills, progress steps, quota bar, masked accounts", () => {
  assert.equal(isFinanceUser(["Employee"]), false);
  assert.equal(isFinanceUser(["Employee", "Accounts User"]), true);
  assert.equal(pillClass("已付款·待补票"), "pill p-brand");
  assert.equal(pillClass("已完结"), "pill p-jade");
  assert.equal(pillClass("随便"), "pill p-gray");
  assert.equal(displayStatus({ workflow_status: "待审批", business_status: "待审批" }), "审批中");
  assert.equal(displayStatus({ workflow_status: "待办理", business_status: "待付款" }), "待付款");
  assert.equal(displayStatus({ workflow_status: "已付款", business_status: "待核验" }), "待核验");
  const chips = stepChips({ workflow_status: "待审批", current_step_index: 2, steps: [
    { step_index: 1, label: "出纳审核", status: "已通过" },
    { step_index: 2, label: "直属主管：演示员工155", status: "待审批" },
    { step_index: 3, label: "财务主管", status: "待流转" },
  ] });
  assert.deepEqual(chips.map((chip) => chip.state), ["d", "c", ""]);
  assert.deepEqual(quotaOf({ request_type: "购买申请", approved_amount: 1000, paid_amount: 200, reserved_amount: 300, available_amount: 500 }),
    { capped: true, pct: 50, remaining: 500, text: "剩余 500.00 元" });
  assert.deepEqual(quotaOf({ request_type: "出差申请" }), { capped: false, text: "出差申请不限金额" });
  assert.equal(maskAccount("6225 0000 1111 2222"), "6225 **** 2222");
  assert.equal(maskAccount("1234"), "1234");
});

test("invoice folder tabs follow the design for employees and finance", () => {
  const rows = [
    { name: "A", folder_status: "可用" }, { name: "B", folder_status: "识别中" }, { name: "C", folder_status: "待确认" },
    { name: "D", folder_status: "已使用" }, { name: "E", folder_status: "疑似重复" }, { name: "F", folder_status: "已排除" },
  ];
  assert.deepEqual(folderTabs(rows).map((tab) => [tab.label, tab.count]), [["全部", 6], ["待确认", 2], ["可用", 1], ["已使用", 1], ["疑似重复", 1]]);
  assert.deepEqual(folderTabs(rows, true).map((tab) => [tab.label, tab.count]), [["疑似重复待处理", 1], ["全部发票", 6]]);
  assert.deepEqual(filterFolder(rows, "todo").map((row) => row.name), ["B", "C"]);
  assert.deepEqual(filterFolder(rows, "list").map((row) => row.name), ["A", "B", "C", "D", "E"]);
  assert.equal(editableByOwner({ folder_status: "待确认" }), true);
  assert.equal(editableByOwner({ folder_status: "待确认" }, true), false);
  assert.equal(editableByOwner({ folder_status: "可用" }), false);
});

test("invoice folder tabs are counted by the server, not from the loaded page", () => {
  const counts = { 识别中: 1, 待确认: 2, 可用: 700, 已使用: 3, 疑似重复: 4, 识别失败: 1, 已排除: 9 };
  assert.deepEqual(folderTabsFromCounts(counts).map((tab) => [tab.key, tab.count]),
    [["list", 711], ["todo", 4], ["ok", 700], ["used", 3], ["dup", 4]]);
  assert.deepEqual(folderTabsFromCounts(counts, true).map((tab) => [tab.label, tab.count]), [["疑似重复待处理", 4], ["全部发票", 711], ["我的发票", 711]]);
  // 修复（2026-09-28）：财务的“我的发票”按本人发票计数。
  assert.deepEqual(folderTabsFromCounts(counts, true, { 待确认: 2, 可用: 1 }).map((tab) => [tab.key, tab.count]), [["dup", 4], ["allinv", 711], ["mine", 3]]);
  assert.deepEqual(tabStatuses("todo"), ["待确认", "识别中", "识别失败"]);
  assert.equal(tabStatuses("unknown").includes("已排除"), false);
});

test("boards open for the positions the server grants, and the menu shows one set of pages", () => {
  const access = { reimbursement_request: true, payment_request: true, expense_reimbursement: true, procurement_application: true, procurement_payment: true };
  globalThis.window = { roles: ["Employee"], oa_access: access, position_access: { vice_manager: true } };
  assert.equal(canSee("/approval/expense-request-board"), true);
  globalThis.window = { roles: ["Employee"], oa_access: access, position_access: {} };
  assert.equal(canSee("/approval/expense-request-board"), false);
  globalThis.window = { roles: ["Accounts User"], oa_access: access };
  assert.equal(canSee("/approval/reimbursement"), true, "legacy page still opens for in-flight documents");
  assert.equal(inMenu("/approval/reimbursement"), false);
  assert.equal(inMenu("/approval/claim"), true);
});

test("review fixes 2026-09-23 stay wired into the pages", () => {
  const workbench = read("../src/components/claim/ClaimWorkbench.vue");
  assert.match(workbench, /v-if="focusDoc\.can_approve \|\| focusDoc\.can_edit_expense_items"/, "cashier can approve while filling accounts");
  assert.match(workbench, /Promise\.allSettled/, "one failing lookup no longer blanks the form");
  assert.match(workbench, /expense_claim_entry\.list_verify_queue/);
  assert.match(workbench, /expense_claim_entry\.list_claim_projects/);
  assert.doesNotMatch(workbench, /list_approval_center_projects/);
  const folder = read("../src/pages/InvoiceFolder.vue");
  assert.doesNotMatch(folder, /hydrate\(selected\.value\);\n\s*if \(poller\)/, "polling must not refill the form");
  assert.match(folder, /statuses: tabStatuses\(tab\.value\)/);
  assert.match(folder, /alive = false/);
  const app = read("../src/App.vue");
  assert.match(app, /inMenu\(child\.to\)/);
  assert.doesNotMatch(read("../src/pages/TravelRequest.vue"), /list_approval_center_projects/);
});

test("invoice folder: retries stop after three failures and stuck recognitions can be retried (2026-09-28)", () => {
  assert.equal(retryState({ folder_status: "识别失败", retry_count: 1 }), "retry");
  assert.equal(retryState({ folder_status: "识别失败", retry_count: 3 }), "retry");
  assert.equal(retryState({ folder_status: "识别失败", retry_count: 4 }), "exhausted");
  const now = Date.parse("2026-09-28T10:30:00");
  assert.equal(retryState({ folder_status: "识别中", modified: "2026-09-28 10:00:00.123456" }, now), "stuck");
  assert.equal(retryState({ folder_status: "识别中", modified: "2026-09-28 10:25:00" }, now), "");
  assert.equal(retryState({ folder_status: "可用" }, now), "");
});

test("invoice folder: the duplicate message comes from the server reason (2026-09-28)", () => {
  assert.equal(duplicateText({ duplicate_reason: "发票号码与已确认发票 OIR-1 相同，但开票日期或合计不同，请核对是否为同一张发票" }),
    "发票号码与已确认发票 OIR-1 相同，但开票日期或合计不同，请核对是否为同一张发票");
  assert.equal(duplicateText({ duplicate_reason: "duplicate-override:v2:abc:ok", duplicate_of: "OIR-2" }), "发票号码与已确认发票 OIR-2 相同");
});

test("invoice folder: finance can upload and confirm their own invoices (2026-09-28)", () => {
  const source = read("../src/pages/InvoiceFolder.vue");
  assert.doesNotMatch(source, /<label v-if="!finance" class="btn pri"/);
  assert.match(source, /const ownView = computed\(\(\) => !finance \|\| tab\.value === 'mine'\)/);
  assert.match(source, /editableByOwner\(selected\.value, !ownView\.value\)/);
  assert.match(source, /view: ownView\.value \? 'mine' : 'all'/);
});

test("invoice folder: own unused confirmed invoices can be un-confirmed, and excluding your own invoice needs no reason (2026-10-09)", () => {
  const folder = read("../src/pages/InvoiceFolder.vue");
  assert.match(folder, /unconfirmInvoice\(selected\.value\.name/);
  assert.match(folder, /ownView && selected\.folder_status === '可用'/);
  assert.match(folder, /ownView && selected\.folder_status === '已使用'/);
  assert.match(folder, /exclude\('确认是重复发票，请填写排除原因', \{ required: true \}\)/);   // 财务确认重复仍要写原因
  assert.match(folder, /window\.prompt\(reasonPrompt, required \? '' : '传错了'\)/);
});

test("supplemental attachment calls send the parameter name the server expects (2026-09-28)", () => {
  // R3-49-X1：前端发 attachment_name，后端参数叫 attachment，删除和预览补充附件一直失败。
  const source = read("../src/lib/invoiceOcr.js");
  assert.doesNotMatch(source, /attachment_name:/);
  assert.equal((source.match(/\battachment: attachmentName/g) || []).length, 2);
});


test("claim pages: home, list, detail and a separate new page share one address (2026-09-30)", async () => {
  const { claimView, waitedDays, canQuickApprove, statusBuckets, stepTimeline } = await import("../src/lib/claimView.js");
  assert.equal(claimView({}), "home");
  assert.equal(claimView({ view: "list", scope: "todo" }), "list");
  assert.equal(claimView({ request: "BX-1" }), "detail", "notification links keep opening the document");
  assert.equal(claimView({ tab: "new" }), "new");
  assert.equal(claimView({ source: "OA-1" }), "new", "push from an application still works");
  assert.equal(claimView({ view: "new", draft: "BX-2" }), "new");
  const now = Date.parse("2026-09-30T12:00:00");
  assert.equal(waitedDays({ steps: [{ acted_on: "2026-09-26 09:00:00" }, { acted_on: null }] }, now), 4);
  assert.equal(waitedDays({ creation: "2026-09-30 08:00:00" }, now), 0);
  assert.equal(waitedDays({}, now), null);
  // 按日历日期算，和数据看板同一个口径：10-09 23:30 到 10-12 00:30 是 3 天（满 24 小时只有 2 天），不会是负数
  assert.equal(waitedDays({ submitted_on: "2026-10-09 23:30:00" }, Date.parse("2026-10-12T00:30:00")), 3);
  assert.equal(waitedDays({ submitted_on: "2026-10-13 09:00:00" }, Date.parse("2026-10-12T10:00:00")), 0);
  assert.equal(canQuickApprove({ can_approve: true }), true);
  assert.equal(canQuickApprove({ can_approve: true, current_step_mode: "handle" }), false, "confirming payment happens on the detail page");
  assert.equal(canQuickApprove({ can_approve: false, can_edit_expense_items: true }), false, "the cashier fills accounts on the detail page");
  const buckets = statusBuckets([{ workflow_status: "草稿" }, { workflow_status: "待审批", amount: 10 }, { workflow_status: "已付款", business_status: "已完结", amount: 5 }]);
  assert.deepEqual(buckets.map((bucket) => bucket.count), [1, 1, 0, 1, 0]);
  const timeline = stepTimeline({ workflow_status: "待审批", current_step_index: 2, steps: [
    { step_index: 1, label: "直属主管", status: "已通过", acted_on: "2026-09-26 15:40:00", mode: "approve" },
    { step_index: 2, label: "财务主管", status: "待审批" },
    { step_index: 3, label: "出纳付款", status: "待审批", mode: "handle" },
  ] });
  assert.deepEqual(timeline.map((item) => item.state), ["done", "now", "todo"]);
  assert.equal(timeline[0].sub, "已同意 · 2026-09-26 15:40");
});

test("claim pages keep every action on the detail page (2026-09-30)", () => {
  const workbench = read("../src/components/claim/ClaimWorkbench.vue");
  for (const action of ["approve(focusDoc)", "reject(focusDoc)", "withdraw(focusDoc)", "verify(focusDoc)", "returnInvoices(focusDoc)", "withdrawPayment(focusDoc)", "openSupplement(focusDoc)", "submitSupplement(focusDoc)"]) {
    assert.ok(workbench.includes(action), action);
  }
  assert.match(workbench, /save\(\{ submit: true \}\)/);
  assert.match(workbench, /push_from_application/);
  assert.doesNotMatch(workbench, /role="tablist"/, "no more top tabs");
});


test("invoice folder opens on a home page with sections; the list keeps the review panel (2026-09-30)", async () => {
  const { folderStatusBar } = await import("../src/lib/invoiceFolderView.js");
  const bar = folderStatusBar({ 已使用: 3, 可用: 1 });
  assert.deepEqual(bar.slice(0, 2).map((item) => [item.label, item.count, item.width]), [["已使用", 3, "75.0%"], ["可用", 1, "25.0%"]]);
  const folder = read("../src/pages/InvoiceFolder.vue");
  assert.match(folder, /view === 'home'/);
  assert.match(folder, /class="drop-zone"/);
  assert.match(folder, /go\(\{ view: 'list', tab: item\.key \}\)/);
});
