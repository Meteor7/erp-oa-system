// 路由守卫要对用户说的话（例如"没有权限，已回到某某页"）。守卫在页面之外，所以放在这个小的共享状态里，
// 由 App.vue 显示一次（可关闭，几秒后自动消失）。
import { reactive } from 'vue';

export const routeNotice = reactive({ denied: '', fallback: '', at: 0 });

export function setDeniedNotice(denied, fallback) {
  routeNotice.denied = String(denied || '');
  routeNotice.fallback = String(fallback || '');
  routeNotice.at = Date.now();
}

export function clearRouteNotice() {
  routeNotice.denied = '';
  routeNotice.fallback = '';
}
