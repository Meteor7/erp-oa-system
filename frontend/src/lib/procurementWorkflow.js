const stripTags = (value) => String(value || "").replace(/<[^>]*>/g, "").trim();

export function normalizeServerError(error, fallback = "操作失败") {
  const values = Array.isArray(error?.messages) ? error.messages : [];
  const candidate = values.find(Boolean) || error?.message || error?._server_messages || fallback;
  return stripTags(candidate) || fallback;
}

export function organizationPreflightMessage(requestType, context = {}) {
  if (!["采购申请", "购买申请"].includes(requestType)) return "";
  if (!context?.employee) {
    return "当前账号未关联在职员工，不能提交；请使用真实申请人账号或先维护员工账号关联。";
  }
  if (!context?.supervisor_user && context?.supervisor_decision !== "skip") {
    return "当前员工未配置可用的直属上级审批账号，不能提交；请先维护员工直属上级及其登录账号。";
  }
  return "";
}

export function validateProcurementRequestForm(form = {}, requestType = "采购申请") {
  if (!["采购申请", "购买申请"].includes(requestType)) return "";
  const lines = Array.isArray(form.business_lines) ? form.business_lines : [];
  if (!lines.length) return "请至少添加一项采购明细";
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] || {};
    if (requestType === "采购申请") {
      const category = String(line.category_code || "").trim();
      if (category.split(".").filter(Boolean).length < 3) {
        return `第${index + 1}项物料编号至少选择到三级`;
      }
    }
    const required = requestType === "采购申请"
      ? [["物料名称", line.item_name], ["规格型号", line.specification], ["商品品牌", line.brand], ["计量单位", line.unit]]
      : [["购买物品", line.item_name], ["计量单位", line.unit]];
    const missing = required.filter(([, value]) => !String(value || "").trim()).map(([label]) => label);
    if (missing.length) return `第${index + 1}项物料资料不完整：${missing.join("、")}`;
    if (!(Number(line.quantity) > 0)) return `第${index + 1}项采购数量必须大于0`;
  }
  return "";
}
const commonPayload = (form) => ({
  subject: form.subject,
  reason: form.reason,
  urgency: form.urgency,
  asset_nature: form.asset_nature,
  fixed_asset_category: form.asset_nature === "固定资产" ? form.fixed_asset_category : "",
  expected_delivery_date: form.expected_delivery_date,
  purchaser_user: form.purchaser_user,
  business_lines: (form.business_lines || []).map((line) => ({
    material_code: line.material_code || "",
    category_code: line.category_code || "",
    category_path: line.category_path || "",
    item_name: line.item_name || "",
    specification: line.specification || "",
    product_desc: line.product_desc || "",
    brand: line.brand || "",
    product_name: line.product_name || "",
    product_desc_en: line.product_desc_en || "",
    brand_en: line.brand_en || "",
    material_attr: line.material_attr || "",
    quantity: line.quantity,
    unit: line.unit || "",
    unit_price: line.unit_price || 0,
    remarks: line.remarks || "",
  })),
});

// 非项目采购只按部门归属；费用类别由后端按所选部门的性质算，不由页面传。
const allocationPayload = (form) => ({
  project: "",
  non_project_allocation_type: "部门",
  non_project_cost_center: "",
  non_project_department: form.non_project_department || "",
});

export function buildApprovalCenterPayload(form, requestType) {
  const common = commonPayload(form);
  if (requestType === "采购申请") {
    return {
      ...common,
      applicant_employee: form.applicant_employee || "",
      procurement_scope: form.procurement_scope,
      ...(form.procurement_scope === "项目采购" ? { project: form.project } : allocationPayload({ ...form, project: "" })),
    };
  }
  if (requestType === "购买申请") {
    return { ...common, project: form.project || "", purchase_method: form.purchase_method };
  }
  if (requestType === "采购付款") {
    return {
      ...common,
      source_request: form.source_request,
      source_payment_plan_row: form.source_payment_plan_row,
      source_purchase_order: form.source_purchase_order,
      source_po_payment_plan_row: form.source_po_payment_plan_row,
      supplier: form.supplier,
      prepayment_percentage: Number(form.prepayment_percentage || 0),
      expected_arrival_date: form.expected_arrival_date,
      prepayment_risk_note: form.prepayment_risk_note,
    };
  }
  return common;
}

export function paymentPlanTotals(rows = []) {
  return rows.reduce((total, row) => ({
    percentage: total.percentage + Number(row.percentage || 0),
    amount: total.amount + Number(row.amount || 0),
  }), { percentage: 0, amount: 0 });
}

export function validatePriceApprovalForm(form = {}) {
  if (!String(form.supplier || "").trim()) return "请填写供应商";
  if (!(form.business_lines || []).length || form.business_lines.some((line) => Number(line.unit_price || 0) <= 0)) {
    return "请为每项采购明细填写有效单价";
  }
  if (!String(form.delivery_terms || "").trim() || !String(form.warranty_terms || "").trim()
    || !String(form.invoice_condition || "").trim()) {
    return "请完整填写交付、质保和开票条件";
  }
  const totals = paymentPlanTotals(form.payment_plan || []);
  const priceTotal = (form.business_lines || []).reduce(
    (sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0,
  );
  if (!(form.payment_plan || []).length) return "至少填写一期付款计划";
  if (Math.abs(totals.percentage - 100) > 0.0001) return "付款计划比例合计必须为100%";
  if (Math.abs(totals.amount - priceTotal) > 0.005) return "付款计划金额合计必须等于价格审批总额";
  if ((form.payment_plan || []).some((row) => !String(row.trigger_condition || "").trim())) {
    return "请填写每一期付款触发条件";
  }
  return "";
}

const hasAny = (types, required) => required.some((item) => types.includes(item));
const lifecycleReady = (request) => (
  (request?.request_type === "采购付款" && request?.workflow_status === "已付款")
  || (request?.request_type === "采购申请" && request?.workflow_status === "已完成")
);
export function canRecordArrival(request, documentTypes) {
  return lifecycleReady(request)
    && ["合同待登记", "合同已生效", "付款计划已生成", "采购执行中", "待到货", "部分到货", "预付款逾期", "催办中", "换货中"].includes(request?.business_status)
    && hasAny(documentTypes || [], ["送货单", "收料单", "入库单"]);
}

export function canRecordInspection(request, documentTypes) {
  return lifecycleReady(request)
    && ["全部到货", "关闭未交数量"].includes(request?.arrival_status)
    && ["待验收", "全部到货", "关闭未交数量", "验收不合格"].includes(request?.business_status)
    && (documentTypes || []).includes("验收资料");
}

export function canCompleteSupplierRefund(request, documentTypes) {
  return request?.request_type === "采购付款"
    && request?.workflow_status === "已付款"
    && ["供应商退款中", "退货中"].includes(request?.business_status)
    && (documentTypes || []).includes("退款回单");
}

export function canWriteoffPrepayment(request, documentTypes) {
  return request?.payment_stage === "预付款"
    && Number(request?.prepayment_percentage) === 100
    && request?.inspection_status === "验收通过"
    && ["发票", "验收资料"].every((item) => (documentTypes || []).includes(item));
}

export function canCloseProcurement(request, documentTypes) {
  return request?.request_type === "采购付款"
    && request?.workflow_status === "已付款"
    && request?.business_status !== "已关闭"
    && !Number(request?.has_balance_payment || 0)
    && request?.inspection_status === "验收通过"
    && (request?.prepayment_writeoff_status === "已核销" || Number(request?.prepayment_percentage || 0) !== 100)
    && ["发票", "验收资料", "采购完成报告"].every((item) => (documentTypes || []).includes(item));
}
