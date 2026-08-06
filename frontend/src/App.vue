<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { createResource } from 'frappe-ui';
import { canSee, currentUser, roleLabel } from './lib/access';
const companyLogo = '/assets/' + 'rayher_hr_payroll/images/planck-semicon-logo.png';

const groups = [
  { label: '\u603b\u89c8', items: [{ to: '/dashboard', step: '', label: '\u6570\u636e\u770b\u677f' }] },
  { label: '\u5ba1\u6279', items: [
    { to: '/approval/leave', step: '01', label: '\u8bf7\u5047\u5ba1\u6279' },
    { to: '/approval/purchase', step: '02', label: '\u8d39\u7528\u4ed8\u6b3e/\u62a5\u9500' },
  ] },
  { label: '人事中心', items: [
    { to: '/personnel', step: '01', label: '员工信息管理' },
    { to: '/social-insurance', step: '02', label: '社保信息管理' },
    { to: '/housing-fund', step: '03', label: '公积金信息管理' },
    { step: '04', label: '宿舍信息管理', children: [
      { to: '/accommodation/master', label: '宿舍基本信息管理' },
      { to: '/accommodation/monthly', label: '当月费用管理' },
    ] },
    { to: '/payroll', step: '05', label: '薪酬计算' },
  ] },
  { label: '\u7814\u53d1\u53f0\u8d26', items: [
    { to: '/projects', step: '03', label: '\u9879\u76ee\u7ba1\u7406' },
    { to: '/entry', step: '04', label: '\u7814\u53d1\u5de5\u65f6\u586b\u62a5' },
    { to: '/timesheet', step: '05', label: '\u7814\u53d1\u5de5\u65f6\u62a5\u8868' },
    { to: '/expense', step: '06', label: '\u7814\u53d1\u8d39\u7528\u5bfc\u5165' },
    { to: '/foreign-rd', step: '07', label: '\u5883\u5916\u59d4\u6258\u7814\u53d1\u5de5\u65f6' },
    { to: '/foreign-rd-timesheet', step: '08', label: '\u5883\u5916\u7814\u53d1\u5de5\u65f6\u62a5\u8868' },
    { to: '/allocation', step: '08', label: '\u7814\u53d1\u8d39\u7528\u53f0\u8d26' },
    { to: '/allocation-dashboard', step: '09', label: '\u7814\u53d1\u8d39\u7528\u6c47\u603b' },
  ] },
];

const WIDE_PAGE_PATHS = new Set([
  '/personnel',
  '/social-insurance',
  '/housing-fund',
  '/accommodation',
  '/accommodation/master',
  '/accommodation/monthly',
  '/payroll',
  '/approval/purchase',
  '/projects',
  '/timesheet',
  '/expense',
  '/allocation',
  '/allocation-dashboard',
  '/foreign-rd',
]);
const route = useRoute();
const ACCOMMODATION_PATHS = new Set(['/accommodation/master', '/accommodation/monthly']);
const openNavGroups = reactive(new Set());
function isNavGroupOpen(item) { return openNavGroups.has(item.label); }
function toggleNavGroup(item) {
  if (openNavGroups.has(item.label)) openNavGroups.delete(item.label);
  else openNavGroups.add(item.label);
}
watch(() => route.path, (path) => {
  if (ACCOMMODATION_PATHS.has(path)) openNavGroups.add('宿舍信息管理');
}, { immediate: true });
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items
      .map((n) => n.children ? ({ ...n, children: n.children.filter((child) => canSee(child.to)) }) : n)
      .filter((n) => n.children ? n.children.length : canSee(n.to)) }))
    .filter((g) => g.items.length)
);
const allowed = computed(() => canSee(route.path));
const isWidePage = computed(() => WIDE_PAGE_PATHS.has(route.path));

const showPasswordDialog = ref(false);
const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
});
const passwordError = ref('');
const passwordSuccess = ref('');
const passwordUpdater = createResource({
  url: 'frappe.core.doctype.user.user.update_password',
});

function resetPasswordForm() {
  passwordForm.old_password = '';
  passwordForm.new_password = '';
  passwordForm.confirm_password = '';
  passwordError.value = '';
  passwordSuccess.value = '';
}

function openPasswordDialog() {
  resetPasswordForm();
  showPasswordDialog.value = true;
}

function closePasswordDialog() {
  showPasswordDialog.value = false;
  resetPasswordForm();
}

async function changePassword() {
  passwordError.value = '';
  passwordSuccess.value = '';
  if (!passwordForm.old_password || !passwordForm.new_password) {
    passwordError.value = '请输入当前密码和新密码';
    return;
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    passwordError.value = '两次输入的新密码不一致';
    return;
  }
  try {
    await passwordUpdater.submit({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
      logout_all_sessions: 1,
    });
    resetPasswordForm();
    passwordSuccess.value = '密码修改成功';
  } catch (error) {
    passwordError.value = error?.messages?.[0] || error?.message || '密码修改失败';
  }
}

function logout() {
  window.location.href = '/?cmd=web_logout';
}
</script>
<template>
  <div class='flex min-h-screen bg-gray-50 text-gray-900'>
    <aside class='w-60 bg-gray-900 text-gray-300 flex flex-col'>
      <div class='px-5 py-5 border-b border-white/10'>
        <img :src='companyLogo' alt='QIHENG DEMO' class='h-10 w-auto rounded bg-white object-contain mb-3' />
        <div class='text-white font-semibold'>&#x7814;&#x53d1;&#x6210;&#x672c;&#x7ba1;&#x7406;</div>
        <div class='text-xs text-gray-500 mt-1'>QIHENG DEMO</div>
      </div>
      <nav class='p-3 flex-1 overflow-y-auto'>
        <div v-for='g in visibleGroups' :key='g.label' class='mb-3'>
          <div class='px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-500 font-semibold'>{{ g.label }}</div>
          <template v-for='n in g.items' :key='n.to || n.label'>
            <div v-if='n.children'>
              <button type='button'
                class='flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-gray-300 hover:bg-white/5'
                :aria-expanded='isNavGroupOpen(n)' @click='toggleNavGroup(n)'>
                <span class='w-5 text-[10px] text-gray-500 text-center'>{{ n.step }}</span>
                <span class='flex-1'>{{ n.label }}</span>
                <span class='text-xs text-gray-500'>{{ isNavGroupOpen(n) ? '▾' : '▸' }}</span>
              </button>
              <div v-if='isNavGroupOpen(n)'>
                <router-link v-for='child in n.children' :key='child.to' :to='child.to'
                  class='ml-7 flex items-center rounded-md px-3 py-2 text-[13px] text-gray-400 hover:bg-white/5 hover:text-gray-200'
                  active-class='bg-white/10 text-white'>{{ child.label }}</router-link>
              </div>
            </div>
            <router-link v-else :to='n.to'
              class='flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-white/5'
              active-class='bg-white/10 text-white'>
              <span class='w-5 text-[10px] text-gray-500 text-center'>{{ n.step }}</span>{{ n.label }}
            </router-link>
          </template>
        </div>
      </nav>
    </aside>
    <main class='flex-1 min-w-0 flex flex-col'>
      <header class='h-14 bg-white border-b flex items-center px-6 gap-4'>
        <div class='text-sm text-gray-500 flex-1'>&#x7814;&#x53d1;&#x6210;&#x672c;&#x4e00;&#x4f53;&#x5316; &middot; &#x4eba;&#x4e8b; / &#x5ba1;&#x6279; / &#x5de5;&#x65f6; / &#x8d39;&#x7528; / &#x85aa;&#x916c;</div>
        <div class='flex items-center gap-3 text-sm'>
          <span class='inline-flex items-center rounded border border-gray-200 bg-gray-50 px-2 py-1 text-gray-700'>{{ roleLabel() }}</span>
          <span class='text-gray-600 max-w-[220px] truncate'>{{ currentUser() }}</span>
          <button type='button' class='rounded border border-gray-300 px-3 py-1.5 text-gray-700 hover:bg-gray-50' @click='openPasswordDialog'>修改密码</button>
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

    <div v-if='showPasswordDialog' class='fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4' @keydown.esc='closePasswordDialog'>
      <div class='w-full max-w-md rounded-lg bg-white p-5 shadow-xl' role='dialog' aria-modal='true' aria-label='修改密码'>
        <div class='mb-4 flex items-center justify-between'>
          <h2 class='text-base font-semibold text-gray-900'>修改密码</h2>
          <button type='button' class='text-xl leading-none text-gray-400 hover:text-gray-700' aria-label='关闭' @click='closePasswordDialog'>×</button>
        </div>
        <form class='space-y-3' @submit.prevent='changePassword'>
          <label class='block text-sm text-gray-700'>
            <span class='mb-1 block'>当前密码</span>
            <input v-model='passwordForm.old_password' type='password' autocomplete='current-password' class='w-full rounded border border-gray-300 px-3 py-2' />
          </label>
          <label class='block text-sm text-gray-700'>
            <span class='mb-1 block'>新密码</span>
            <input v-model='passwordForm.new_password' type='password' autocomplete='new-password' class='w-full rounded border border-gray-300 px-3 py-2' />
          </label>
          <label class='block text-sm text-gray-700'>
            <span class='mb-1 block'>确认新密码</span>
            <input v-model='passwordForm.confirm_password' type='password' autocomplete='new-password' class='w-full rounded border border-gray-300 px-3 py-2' />
          </label>
          <p v-if='passwordError' class='text-sm text-red-600'>{{ passwordError }}</p>
          <p v-if='passwordSuccess' class='text-sm text-green-600'>{{ passwordSuccess }}</p>
          <div class='flex justify-end gap-2 pt-2'>
            <button type='button' class='rounded border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50' @click='closePasswordDialog'>取消</button>
            <button type='submit' class='rounded bg-gray-900 px-3 py-2 text-sm text-white hover:bg-gray-800' :disabled='passwordUpdater.loading'>
              {{ passwordUpdater.loading ? '提交中…' : '确认修改' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
