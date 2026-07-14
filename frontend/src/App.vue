<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { canSee, currentUser, roleLabel } from './lib/access';

const groups = [
  { label: '\u603b\u89c8', items: [{ to: '/dashboard', step: '', label: '\u6570\u636e\u770b\u677f' }] },
  { label: '\u5ba1\u6279', items: [
    { to: '/approval/leave', step: '01', label: '\u8bf7\u5047\u5ba1\u6279' },
    { to: '/approval/purchase', step: '02', label: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500' },
  ] },
  { label: '\u4eba\u4e8b\u4e2d\u5fc3', items: [
    { to: '/personnel', step: '01', label: '\u4eba\u4e8b\u4fe1\u606f\u7ba1\u7406' },
    { to: '/accommodation', step: '02', label: '\u5bbf\u820d\u4f4f\u5bbf\u8d39\u7528' },
  ] },
  { label: '\u7814\u53d1\u53f0\u8d26', items: [
    { to: '/projects', step: '03', label: '\u9879\u76ee\u7ba1\u7406' },
    { to: '/entry', step: '04', label: '\u7814\u53d1\u5de5\u65f6\u586b\u62a5' },
    { to: '/timesheet', step: '05', label: '\u7814\u53d1\u5de5\u65f6\u62a5\u8868' },
    { to: '/expense', step: '06', label: '\u7814\u53d1\u8d39\u7528\u5bfc\u5165' },
    { to: '/foreign-rd', step: '07', label: '\u5883\u5916\u59d4\u6258\u7814\u53d1\u5de5\u65f6' },
    { to: '/allocation', step: '08', label: '\u7814\u53d1\u8d39\u7528\u53f0\u8d26' },
    { to: '/allocation-dashboard', step: '09', label: '\u7814\u53d1\u8d39\u7528\u6c47\u603b' },
  ] },
];

const WIDE_PAGE_PATHS = new Set([
  '/personnel',
  '/accommodation',
  '/approval/purchase',
  '/projects',
  '/timesheet',
  '/expense',
  '/allocation',
  '/allocation-dashboard',
  '/foreign-rd',
]);
const route = useRoute();
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((n) => canSee(n.to)) }))
    .filter((g) => g.items.length)
);
const allowed = computed(() => canSee(route.path));
const isWidePage = computed(() => WIDE_PAGE_PATHS.has(route.path));

function logout() {
  window.location.href = '/?cmd=web_logout';
}
</script>
<template>
  <div class='flex min-h-screen bg-gray-50 text-gray-900'>
    <aside class='w-60 bg-gray-900 text-gray-300 flex flex-col'>
      <div class='px-5 py-5 border-b border-white/10'>
        <div class='text-white font-semibold'>&#x7814;&#x53d1;&#x6210;&#x672c;&#x7ba1;&#x7406;</div>
        <div class='text-xs text-gray-500 mt-1'>Rayher &middot; frappe-ui</div>
      </div>
      <nav class='p-3 flex-1 overflow-y-auto'>
        <div v-for='g in visibleGroups' :key='g.label' class='mb-3'>
          <div class='px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 font-semibold'>{{ g.label }}</div>
          <router-link v-for='n in g.items' :key='n.to' :to='n.to'
            class='flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-white/5'
            active-class='bg-white/10 text-white'>
            <span class='w-5 text-[10px] text-gray-500 text-center'>{{ n.step }}</span>{{ n.label }}
          </router-link>
        </div>
      </nav>
    </aside>
    <main class='flex-1 min-w-0 flex flex-col'>
      <header class='h-14 bg-white border-b flex items-center px-6 gap-4'>
        <div class='text-sm text-gray-500 flex-1'>&#x7814;&#x53d1;&#x6210;&#x672c;&#x4e00;&#x4f53;&#x5316; &middot; &#x4eba;&#x4e8b; / &#x5ba1;&#x6279; / &#x5de5;&#x65f6; / &#x8d39;&#x7528; / &#x85aa;&#x916c;</div>
        <div class='flex items-center gap-3 text-sm'>
          <span class='inline-flex items-center rounded border border-gray-200 bg-gray-50 px-2 py-1 text-gray-700'>{{ roleLabel() }}</span>
          <span class='text-gray-600 max-w-[220px] truncate'>{{ currentUser() }}</span>
          <button type='button' class='rounded border border-gray-300 px-3 py-1.5 text-gray-700 hover:bg-gray-50' @click='logout'>&#x9000;&#x51fa;&#x767b;&#x5f55;</button>
        </div>
      </header>
      <div :class="['p-7 w-full mx-auto flex-1', isWidePage ? 'max-w-[1900px]' : 'max-w-6xl']">
        <router-view v-if='allowed' />
        <div v-else class='flex flex-col items-center justify-center py-24 text-center'>
          <div class='text-3xl mb-3'>403</div>
          <div class='text-gray-700 font-medium'>&#x60a8;&#x6ca1;&#x6709;&#x8bbf;&#x95ee;&#x8be5;&#x9875;&#x9762;&#x7684;&#x6743;&#x9650;</div>
          <div class='text-gray-400 text-sm mt-1'>&#x8be5;&#x6a21;&#x5757;&#x4ec5;&#x5bf9;&#x6388;&#x6743;&#x5c97;&#x4f4d;&#x5f00;&#x653e;&#xff0c;&#x8bf7;&#x8054;&#x7cfb;&#x7cfb;&#x7edf;&#x7ba1;&#x7406;&#x5458;&#x3002;</div>
        </div>
      </div>
    </main>
  </div>
</template>
