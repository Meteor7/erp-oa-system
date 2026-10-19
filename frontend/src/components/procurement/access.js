// 采购页面用到的权限判断，都来自 lib/access.js（岗位 / 角色），这里只给页面起短名字。
import {
  canCreateProcurementPr, canEditProcurementPrice, canMaintainProcurementCatalog, canOpenMaterialBoard,
  canSeeProcurementPO, canSeeProcurementPrice,
} from '../../lib/access.js';

export const canSeePrice = () => canSeeProcurementPrice();
export const canSeePo = () => canSeeProcurementPO();
export const canCreatePr = () => canCreateProcurementPr();
export const canEditPrice = () => canEditProcurementPrice();
export const canOpenBoard = () => canOpenMaterialBoard();
export const canMaintainCatalog = () => canMaintainProcurementCatalog();

// 能看供应商 / 单价 / 金额的人；申请人只看数量和状态。
export const isInsider = () => canSeePrice() || canSeePo();

// 副总经理：价格审批选成交供应商、PO 电子用印都找他（access.js 没有单独的函数，按岗位判断）。
export function isViceManager() {
  const positions = (typeof window !== 'undefined' && window.position_access) || {};
  const roles = (typeof window !== 'undefined' && Array.isArray(window.roles)) ? window.roles : [];
  return positions.vice_manager === true || roles.includes('System Manager');
}
