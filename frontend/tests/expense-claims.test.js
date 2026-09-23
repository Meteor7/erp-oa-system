import assert from "node:assert/strict";
import test from "node:test";
import {
  CLAIM_KINDS,
  accountBlockers,
  applicationLabel,
  claimDraftPayload,
  claimKind,
  claimTabs,
  money,
  overBudget,
  statusTone,
  submitBlockers,
  sumAmount,
} from "../src/lib/expenseClaims.js";
import {
  canConfirm,
  canEditFields,
  canRetry,
  confirmBlockers,
  folderTone,
  missingFields,
  stillRecognizing,
  tabsWithCounts,
  usedByText,
} from "../src/lib/invoiceFolderView.js";
import { canSee, firstVisiblePath } from "../src/lib/access.js";

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
  assert.deepEqual(claimTabs("claim").map((tab) => tab.label), ["我的报销", "待我处理", "全部可见"]);
  assert.deepEqual(claimTabs("payment").map((tab) => tab.key), ["mine", "pending", "all"]);
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
  assert.deepEqual(accountBlockers([{ expense_account_level_1: "管理费用", expense_account_level_2: "" }]), ["出纳需要为每行明细选择一、二级科目"]);
  assert.notEqual(statusTone("已付款·待补票"), statusTone("已完结"));
});

test("invoice folder status drives what the employee can do", () => {
  const pending = { folder_status: "待确认", invoice_category: "普通发票", project_name: "打印纸", issue_date: "2026-09-20", invoice_number: "123", total_amount: 100, expense_description: "办公" };
  assert.equal(canEditFields(pending), true);
  assert.equal(canConfirm(pending), true);
  assert.deepEqual(confirmBlockers(pending), []);
  assert.deepEqual(confirmBlockers({ ...pending, invoice_number: "", total_amount: 0 }), ["确认前请补全：发票号码、合计"]);
  assert.deepEqual(missingFields({ folder_status: "待确认" }), ["发票类别", "项目名称", "开票日期", "发票号码", "合计", "费用说明"]);
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
