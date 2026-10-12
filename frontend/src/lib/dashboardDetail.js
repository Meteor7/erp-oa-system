// 看板明细页（/dashboard/detail）的纯函数：地址 → 接口参数，清单 → 页面要显示的东西。
// 明细是点指标卡 / 提醒进去看到的清单：条数 / 合计和卡片上的数字一致，每一行再点进真实的单据。
import { fromValue, isInternalPath } from './navContext.js';

const one = (value) => String(Array.isArray(value) ? (value[0] ?? '') : (value ?? '')).trim();

export const DETAIL_PATH = '/dashboard/detail';

// 清单名只认字母、数字、点和下划线（后端按这个名字找清单，别的字符一律当没写）。
export function detailItem(query = {}) {
  const item = one(query.item);
  return /^[A-Za-z0-9_.]{1,80}$/.test(item) ? item : '';
}

export function detailPeriod(query = {}) {
  const period = one(query.period);
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(period) ? period : '';
}

// 接口参数：没有期间就不传（后端用当前月）。
export function detailParams(query = {}) {
  const params = { item: detailItem(query) };
  const period = detailPeriod(query);
  if (period) params.period = period;
  return params;
}

// 返回哪里：来自哪个页面就回哪个页面（站内路径），没有就回首页看板。
export function detailBack(query = {}) {
  const from = fromValue(query);
  return from && from !== 'list' && isInternalPath(from) ? from : '/dashboard';
}

// 表格里一列的对齐 class。
export function cellClass(column) {
  return column?.align === 'r' ? 'is-r' : '';
}

// 一行能不能点：有目标且目标页打得开。state 是 targetState 的结果。
export function rowClickable(state) {
  return state?.state === 'link';
}
