// 采购页面的接口辅助：统一错误文字、"取不到就当没有"的包装、PO 汇总的短时缓存。
import { callApi } from '../../lib/expenseClaims.js';
import { extractFrappeError } from '../../lib/frappeError.js';

export const apiGet = (path, args = {}) => callApi(path, args, { method: 'GET' });
export const apiPost = (path, args = {}) => callApi(path, args);

export function errText(error, fallback = '操作失败') {
  return extractFrappeError(error, fallback);
}

// 某一类待办取不到（没有权限、功能没开）时只是不显示这一组，不影响页面其他部分。
export async function settle(job, fallback = []) {
  try {
    const value = await job();
    return value ?? fallback;
  } catch (_error) {
    return fallback;
  }
}

let poCache = { at: 0, promise: null };

// 价格审批 / PO / 付款计划只有采购、PMC、副总、财务看得到；其他人调用会被后端拒绝，这里返回空。
export function loadPurchaseOrders({ force = false } = {}) {
  const now = Date.now();
  if (!force && poCache.promise && now - poCache.at < 20000) return poCache.promise;
  poCache = { at: now, promise: settle(() => apiGet('procurement_chain.list_purchase_orders', { limit: 200 })) };
  return poCache.promise;
}
