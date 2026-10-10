// 采购链路里"不是 OA 审批节点"的待办（提 PR、比价、价格审批、用印、提交付款）：从 PR、价格审批、PO 里汇总。
// 和采购申请首页（ProcHome）用的是同一批接口和同一套整理函数；分组首页也要这些待办，所以单独放一份给它。
// 每一组各自取，没有权限（403）或功能没开就只是不显示这一组。
import { approvalWorkItems, paymentWorkItems, poWorkItems, prWorkItems, priceWorkItems } from '../../lib/procurementView.js';
import { canCreatePr, canEditPrice, canSeePo, canSeePrice, isViceManager } from './access.js';
import { apiGet, loadPurchaseOrders, settle } from './procData.js';

export function emptyWork() {
  return { pr: [], price: [], po: [], approvals: [], payment: [], poStatus: {}, loaded: false };
}

export async function loadProcurementWork(work = emptyWork()) {
  const isPmc = canCreatePr();
  const isBuyer = canEditPrice();
  const isVice = isViceManager();
  const jobs = [];
  if (isPmc) {
    jobs.push(settle(async () => {
      const result = await apiGet('material_progress.list_material_progress', { limit: 200 });
      work.pr = prWorkItems(result?.items || []);
    }));
  }
  if (isBuyer) {
    jobs.push(settle(async () => {
      const [prs, drafts] = await Promise.all([
        settle(() => apiGet('procurement_chain.list_prs', { limit: 200 })),
        settle(() => apiGet('procurement_chain.list_price_approvals', { status: '草稿', limit: 200 })),
      ]);
      work.price = priceWorkItems({ prs, drafts });
    }));
    jobs.push(settle(async () => {
      work.payment = paymentWorkItems(await apiGet('procurement_chain.list_payment_work_items', { limit: 500 }));
    }));
  }
  if (canSeePo() || canSeePrice()) {
    jobs.push(settle(async () => {
      const orders = await loadPurchaseOrders();
      work.poStatus = Object.fromEntries(orders.map((po) => [po.name, po.status]));
      work.po = poWorkItems(orders, { manage: isBuyer, seal: isVice });
    }));
  }
  if (isVice) {
    jobs.push(settle(async () => {
      work.approvals = approvalWorkItems(await apiGet('procurement_chain.list_price_approvals', { status: '待审批', limit: 200 }));
    }));
  }
  await Promise.all(jobs);
  work.loaded = true;
  return work;
}
