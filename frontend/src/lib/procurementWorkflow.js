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

const commonPayload = (form) => ({
  subject: form.subject,
  reason: form.reason,
  urgency: form.urgency,
  asset_nature: form.asset_nature,
  fixed_asset_category: form.asset_nature === "固定资产" ? form.fixed_asset_category : "",
  expected_delivery_date: form.expected_delivery_date,
  purchaser_user: form.purchaser_user,
  business_lines: (form.business_lines || []).map((line) => ({ ...line })),
});

const allocationPayload = (form) => ({
  project: form.project || "",
  non_project_allocation_type: form.project ? "" : form.non_project_allocation_type,
  non_project_cost_center: !form.project && form.non_project_allocation_type === "成本中心" ? form.non_project_cost_center : "",
  non_project_department: !form.project && form.non_project_allocation_type === "部门" ? form.non_project_department : "",
});

export function buildApprovalCenterPayload(form, requestType) {
  const common = commonPayload(form);
  if (requestType === "采购申请") {
    return {
      ...common,
      procurement_scope: form.procurement_scope,
      ...(form.procurement_scope === "项目采购" ? { project: form.project } : allocationPayload({ ...form, project: "" })),
    };
  }
  if (requestType === "购买申请") {
    return { ...common, ...allocationPayload(form), purchase_method: form.purchase_method };
  }
  if (requestType === "采购付款") {
    return {
      ...common,
      source_request: form.source_request,
      supplier: form.supplier,
      prepayment_percentage: Number(form.prepayment_percentage || 0),
      expected_arrival_date: form.expected_arrival_date,
      prepayment_risk_note: form.prepayment_risk_note,
    };
  }
  return common;
}

const hasAny = (types, required) => required.some((item) => types.includes(item));
const lifecycleReady = (request) => (
  (request?.request_type === "采购付款" && request?.workflow_status === "已付款")
  || (request?.request_type === "采购申请" && request?.workflow_status === "已完成")
);
export function canRecordArrival(request, documentTypes) {
  return lifecycleReady(request)
    && ["合同待登记", "采购执行中", "待到货", "部分到货", "预付款逾期", "催办中"].includes(request?.business_status)
    && hasAny(documentTypes || [], ["送货单", "收料单", "入库单"]);
}

export function canRecordInspection(request, documentTypes) {
  return lifecycleReady(request)
    && ["全部到货", "关闭未交数量"].includes(request?.arrival_status)
    && (documentTypes || []).includes("验收资料");
}

export function canWriteoffPrepayment(request, documentTypes) {
  return request?.payment_stage === "预付款"
    && Number(request?.prepayment_percentage) === 100
    && request?.inspection_status === "验收通过"
    && ["发票", "验收资料"].every((item) => (documentTypes || []).includes(item));
}

export function canCloseProcurement(request, documentTypes) {
  return !Number(request?.has_balance_payment || 0)
    && request?.inspection_status === "验收通过"
    && (request?.prepayment_writeoff_status === "已核销" || Number(request?.prepayment_percentage || 0) !== 100)
    && ["发票", "验收资料", "采购完成报告"].every((item) => (documentTypes || []).includes(item));
}
