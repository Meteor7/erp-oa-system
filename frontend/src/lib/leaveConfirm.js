// 表单离开确认（2026-10 导航整改）：表单改过还没保存时，点取消 / 面包屑 / 侧栏 / 浏览器后退，或关闭、刷新标签页，
// 先问一声，避免填了一半的内容悄悄丢掉。
//   useLeaveConfirm(isDirty)  在表单组件的 setup 里调用；isDirty 是返回布尔值的函数（读响应式数据）。
import { onBeforeUnmount, onMounted } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';

export const LEAVE_MESSAGE = '表单还没有保存，离开后填写的内容会丢失。确定要离开吗？';

// 纯函数，方便测试：没改过直接放行，改过就问（ask 返回 true = 确定离开）。
export function allowLeave(dirty, ask) {
  if (!dirty) return true;
  return Boolean(ask());
}

// 用 JSON 比较表单有没有改过；baseline 是打开 / 保存后的快照。
export function isFormDirty(current, baseline) {
  return String(current) !== String(baseline);
}

export function useLeaveConfirm(isDirty, { message = LEAVE_MESSAGE } = {}) {
  const ask = () => (typeof window === 'undefined' || typeof window.confirm !== 'function' ? true : window.confirm(message));
  const guard = () => allowLeave(isDirty(), ask);
  // 换页面（侧栏、深链接）和同一页内换视图（新建 → 列表）走不同的守卫，两个都要挂。
  onBeforeRouteLeave(guard);
  onBeforeRouteUpdate(guard);
  const beforeUnload = (event) => {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = '';
  };
  onMounted(() => window.addEventListener('beforeunload', beforeUnload));
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload));
}
