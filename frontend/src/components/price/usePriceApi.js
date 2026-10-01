// 价格审批 / PO 工作台用到的接口。读取走 GET，写入走 POST；到货 / 验收 / 付款登记已移到"采购付款"，这里不再调用。
import { createResource } from 'frappe-ui';
import { API } from '../../lib/priceView.js';

const post = (method) => createResource({ url: API + method, method: 'POST' });
const get = (method) => createResource({ url: API + method, method: 'GET' });

export function usePriceApi() {
  const loaders = {
    prs: get('list_prs'),
    approvals: get('list_price_approvals'),
    pos: get('list_purchase_orders'),
  };
  const actions = {
    createApproval: post('create_price_approval'),
    saveSupplier: post('save_supplier_comparison'),
    deleteSupplier: post('delete_supplier_comparison'),
    updateSummary: post('update_price_approval_summary'),
    chooseSupplier: post('select_supplier_comparison'),
    submitApproval: post('submit_price_approval'),
    approveApproval: post('approve_price_approval'),
    withdrawApproval: post('withdraw_price_approval'),
    cancelApproval: post('cancel_price_approval'),
    updateDelivery: post('update_po_delivery'),
    confirmPo: post('confirm_po'),
    savePoContract: post('save_po_contract_information'),
    reviewPoContract: post('review_po_contract'),
    sealPoContract: post('seal_po_contract'),
    closePo: post('close_po'),
  };
  async function reload({ price = true, po = true } = {}) {
    const jobs = [];
    if (price) jobs.push(loaders.prs.reload(), loaders.approvals.reload());
    // 价格审批通过 / 撤回会改变 PO 和 PR 数量，只要有权限看 PO 就一起刷新。
    if (po) jobs.push(loaders.pos.reload());
    await Promise.all(jobs);
  }
  return { loaders, actions, reload };
}
