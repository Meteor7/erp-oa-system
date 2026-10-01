// 采购 / 购买申请页面各个子组件共用的上下文（由 ProcurementWorkbench 提供）。
import { inject } from 'vue';

export const PROC_CTX = Symbol('procurement-context');

export function useProc() {
  return inject(PROC_CTX);
}
