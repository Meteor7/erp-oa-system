<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { FeatherIcon, createResource } from 'frappe-ui';
import { canSee, currentUser, inMenu, roleLabel } from './lib/access';
import { deniedNoticeText, groupOwning, ownerOfPath, splitPath, stripAppPrefix } from './lib/navContext';
import { clearRouteNotice, routeNotice } from './lib/routeNotice';
const companyLogo = '/assets/' + 'rayher_hr_payroll/images/qiheng-logo.svg';

function navIcon(item) {
  const key = String(item.to || item.label || '').toLowerCase();
  const icons = [['attendance', 'calendar'], ['procurement', 'shopping-cart'], ['price', 'tag'], ['payment', 'credit-card'], ['personnel', 'users'], ['social', 'shield'], ['housing', 'home'], ['accommodation', 'key'], ['payroll', 'dollar-sign'], ['project', 'layers'], ['timesheet', 'clock'], ['expense', 'file-text'], ['allocation', 'pie-chart'], ['dashboard', 'grid']];
  return icons.find(([part]) => key.includes(part))?.[1] || 'folder';
}


const groups = [
  { label: '\u603b\u89c8', items: [{ to: '/dashboard', step: '', label: '\u6570\u636e\u770b\u677f' }] },
  { label: '审批中心', items: [
    // 分组名本身是考勤中心首页的入口（view=home），四个子项照旧；出差申请也在这里（报销、付款仍然按单号关联它）。
    { to: '/approval/attendance?view=home', step: '01', label: '请假/加班/调休/出差', children: [
      { to: '/approval/leave', label: '请假审批' },
      { to: '/approval/overtime', label: '加班审批' },
      { to: '/approval/comp-time', label: '调休审批' },
      { to: '/approval/travel', label: '出差申请' },
    ] },
    // 分组名本身是这一组的首页（我要处理的、我提交的、快捷新建，下面是看板统计），子项照旧。
    { to: '/approval/requests', step: '02', label: '采购/购买申请', children: [
      { to: '/approval/procurement', label: '采购申请' },
      { to: '/approval/procurement/price-approvals', label: '价格审批' },
      { to: '/approval/direct-purchase', label: '购买申请' },
    ] },
    { to: '/approval/payments', step: '03', label: '付款申请', children: [
      { to: '/approval/procurement-payment', label: '采购付款' },
      { to: '/approval/reimbursement', label: '付款/报销' },
      { to: '/approval/invoice-folder', label: '发票夹' },
      { to: '/approval/claim', label: '报销' },
      { to: '/approval/payment', label: '付款' },
    ] },
    { to: '/approval/material-progress', step: '04', label: '物料进度看板' },
  ] },
  { label: '人事中心', items: [
    { to: '/personnel', step: '01', label: '员工信息管理' },
    { to: '/social-insurance', step: '02', label: '社保信息管理' },
    { to: '/housing-fund', step: '03', label: '公积金信息管理' },
    { step: '04', label: '宿舍信息管理', children: [
      { to: '/accommodation', label: '宿舍看板' },
      { to: '/accommodation/master', label: '宿舍基本信息管理' },
      { to: '/accommodation/monthly', label: '当月费用管理' },
    ] },
    { to: '/payroll', step: '05', label: '薪酬计算' },
  ] },
  { label: '\u7814\u53d1\u53f0\u8d26', items: [
    { to: '/projects', step: '01', label: '\u9879\u76ee\u7ba1\u7406' },
    { to: '/entry', step: '02', label: '\u7814\u53d1\u5de5\u65f6\u586b\u62a5' },
    { to: '/timesheet', step: '03', label: '\u7814\u53d1\u5de5\u65f6\u62a5\u8868' },
    { to: '/expense', step: '04', label: '\u7814\u53d1\u8d39\u7528\u5bfc\u5165' },
    { to: '/foreign-rd', step: '05', label: '\u5883\u5916\u59d4\u6258\u7814\u53d1\u5de5\u65f6' },
    { to: '/foreign-rd-timesheet', step: '06', label: '\u5883\u5916\u7814\u53d1\u5de5\u65f6\u62a5\u8868' },
    { to: '/allocation', step: '07', label: '\u7814\u53d1\u8d39\u7528\u53f0\u8d26' },
    { to: '/allocation-dashboard', step: '08', label: '\u7814\u53d1\u8d39\u7528\u6c47\u603b' },
  ] },
];

const WIDE_PAGE_PATHS = new Set([
  '/dashboard',
  '/personnel',
  '/social-insurance',
  '/housing-fund',
  '/accommodation',
  '/accommodation/master',
  '/accommodation/monthly',
  '/payroll',
  '/approval/purchase',
  '/approval/procurement',
  '/approval/direct-purchase',
  '/approval/request-dashboard',
  '/approval/procurement-payment',
  '/approval/reimbursement',
  '/approval/corporate-payment',
  '/approval/invoice-folder',
  '/approval/claim',
  '/approval/payment',
  '/approval/expense-request-board',
  '/approval/expense-payment-board',
  '/approval/payment-dashboard',
  '/approval/material-progress',
  '/projects',
  '/entry',
  '/timesheet',
  '/expense',
  '/allocation',
  '/allocation-dashboard',
  '/foreign-rd',
  '/foreign-rd-timesheet',
]);
const route = useRoute();
const router = useRouter();
const openNavGroups = reactive(new Set());
const mobileNavOpen = ref(false);
function isNavGroupOpen(item) { return openNavGroups.has(item.label); }
function toggleNavGroup(item) {
  if (openNavGroups.has(item.label)) openNavGroups.delete(item.label);
  else openNavGroups.add(item.label);
}
// 侧栏的每一项都有"自己的"页面：详情、新建、编辑页（/approval/procurement/:name/pmc-edit 等）属于前缀对应的那一项。
const groupedItems = groups.flatMap((g) => g.items.filter((n) => n.children));
const allNavTargets = groups.flatMap((g) => g.items.flatMap((n) => (n.children ? [...n.children.map((child) => child.to), ...(n.to ? [n.to] : [])] : [n.to])));
const navLabels = Object.fromEntries(groups.flatMap((g) => g.items.flatMap((n) => [...(n.children || []), ...(!n.children || n.to ? [n] : [])].map((item) => [splitPath(item.to).path, item.label]))));
const activeNavPath = computed(() => ownerOfPath(route.path, allNavTargets));
const NAV_ACTIVE_CLASS = 'bg-[#E7F4F0] font-semibold text-[#0E615B]';
function isNavActive(to) { return splitPath(to).path === activeNavPath.value; }
watch(() => route.path, (path) => {
  const owner = groupOwning(path, groupedItems);
  if (owner) openNavGroups.add(owner.label);
}, { immediate: true });
watch(() => route.fullPath, () => { mobileNavOpen.value = false; });
const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items
      .map((n) => n.children ? ({ ...n, children: n.children.filter((child) => inMenu(child.to)) }) : n)
      .filter((n) => n.children ? n.children.length : inMenu(n.to)) }))
    .filter((g) => g.items.length)
);
const allowed = computed(() => route.name === 'not-found' || canSee(route.path));

// 没有权限的深链接被带回别的页面：顶部说一声（可关闭，十秒后自动消失）。
const noticeLabel = (path) => navLabels[ownerOfPath(path, allNavTargets)] || '';
const deniedText = computed(() => (routeNotice.denied ? deniedNoticeText(routeNotice.denied, routeNotice.fallback, noticeLabel) : ''));
let noticeTimer = null;
watch(() => routeNotice.at, () => {
  window.clearTimeout(noticeTimer);
  if (routeNotice.denied) noticeTimer = window.setTimeout(clearRouteNotice, 10000);
});
// 之后用户自己点去别的页面，提示就不再留着（刚被带回来的那一次不清）。
watch(() => route.fullPath, () => {
  if (routeNotice.denied && Date.now() - routeNotice.at > 1500) clearRouteNotice();
});
const isWidePage = computed(() => WIDE_PAGE_PATHS.has(route.path) || route.path.startsWith('/approval/procurement/'));

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
const notificationLoader = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.get_my_notifications',
  method: 'GET',
  makeParams: () => ({ limit: 40 }),
  auto: true,
});
const notificationMarker = createResource({
  url: 'rayher_hr_payroll.api.oa_entry.mark_my_notifications_read',
});
const notificationsOpen = ref(false);
const notifications = computed(() => notificationLoader.data?.items || []);
const unreadNotifications = computed(() => Number(notificationLoader.data?.unread || 0));
let notificationTimer = null;

function refreshNotifications() {
  if (!notificationLoader.loading) notificationLoader.reload();
}

function notificationText(item) {
  return String(item?.subject || '新消息').replace(/\s*\[[^\]]+\]\s*$/, '');
}

async function openNotification(item) {
  notificationsOpen.value = false;
  if (item?.name && !item.read) {
    try {
      await notificationMarker.submit({ names: [item.name] });
      await notificationLoader.reload();
    } catch (error) {
      // Keep navigation usable even when a read receipt is temporarily unavailable.
    }
  }
  if (item?.link) {
    // /planck-semicon/... 和旧的 /rayher/... 都去掉前缀，查询参数原样保留。
    const target = stripAppPrefix(item.link, window.location.host);
    if (target) router.push(target);
  }
}

async function markAllNotificationsRead() {
  if (!unreadNotifications.value) return;
  try {
    await notificationMarker.submit({ all_notifications: 1 });
    await notificationLoader.reload();
  } catch (error) {
    // Surface the existing loader error state rather than interrupting the shell.
  }
}

onMounted(() => {
  notificationTimer = window.setInterval(refreshNotifications, 30000);
});
onBeforeUnmount(() => {
  if (notificationTimer) window.clearInterval(notificationTimer);
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
  <div class='qh-workspace flex min-h-screen min-w-0 overflow-x-clip bg-[#F2F6F5] text-[#1A2130]'>
    <aside class='qh-sidebar fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col border-r border-gray-200 bg-white text-gray-700 transition-transform duration-200 md:static md:translate-x-0' :class="mobileNavOpen ? 'translate-x-0' : '-translate-x-full'">
      <div class='qh-brand border-b border-gray-100 px-4 py-4'>
        <img :src='companyLogo' alt='栖衡 QIHENG' class='mb-2.5 h-9 w-auto object-contain' />
        <div class='text-xs text-gray-400'>ERP / OA · 运营协同工作台</div>
      </div>
      <nav class='p-2 flex-1 overflow-y-auto'>
        <div v-for='g in visibleGroups' :key='g.label' class='mb-2'>
          <div class='px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-gray-500'>{{ g.label }}</div>
          <template v-for='n in g.items' :key='n.to || n.label'>
            <div v-if='n.children'>
              <div v-if='n.to' class='flex items-center rounded-lg hover:bg-gray-50'>
                <router-link :to='n.to' class='flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium text-gray-700' :class='isNavActive(n.to) ? NAV_ACTIVE_CLASS : ""' @click='openNavGroups.add(n.label)'>
                  <FeatherIcon :name='navIcon(n)' class='qh-nav-icon' />
                  <span class='flex-1'>{{ n.label }}</span>
                </router-link>
                <button type='button' class='px-2 py-2 text-xs text-gray-400 hover:text-gray-700' :aria-expanded='isNavGroupOpen(n)' :aria-label="'展开或收起' + n.label" @click='toggleNavGroup(n)'>{{ isNavGroupOpen(n) ? '▾' : '▸' }}</button>
              </div>
              <button v-else type='button'
                class='flex w-full items-center gap-1.5 rounded-lg px-2 py-2 text-left text-sm font-medium text-gray-700 hover:bg-gray-50'
                :aria-expanded='isNavGroupOpen(n)' @click='toggleNavGroup(n)'>
                <FeatherIcon :name='navIcon(n)' class='qh-nav-icon' />
                <span class='flex-1'>{{ n.label }}</span>
                <span class='text-xs text-gray-400'>{{ isNavGroupOpen(n) ? '▾' : '▸' }}</span>
              </button>
              <div v-if='isNavGroupOpen(n)'>
                <router-link v-for='child in n.children' :key='child.to' :to='child.to'
                  class='ml-6 flex items-center rounded-lg px-2 py-1.5 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  :class='isNavActive(child.to) ? NAV_ACTIVE_CLASS : ""' :aria-current='isNavActive(child.to) ? "page" : undefined'>{{ child.label }}</router-link>
              </div>
            </div>
            <router-link v-else :to='n.to'
              class='flex items-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50'
              :class='isNavActive(n.to) ? NAV_ACTIVE_CLASS : ""' :aria-current='isNavActive(n.to) ? "page" : undefined'>
              <FeatherIcon :name='navIcon(n)' class='qh-nav-icon' />{{ n.label }}
            </router-link>
          </template>
        </div>
      </nav>
    </aside>
    <button v-if='mobileNavOpen' type='button' class='fixed inset-0 z-30 bg-black/40 md:hidden' aria-label='关闭导航' @click='mobileNavOpen = false'></button>
    <main class='flex min-w-0 flex-1 flex-col'>
      <header class='qh-topbar flex min-h-14 items-center gap-3 border-b border-gray-200 bg-white px-3 py-2 sm:px-4 md:px-6'>
        <button type='button' class='inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-gray-300 text-gray-700 md:hidden' aria-label='打开导航' @click='mobileNavOpen = true'><FeatherIcon name='menu' class='h-4 w-4' /></button>
        <div class='hidden flex-1 text-sm text-gray-500 lg:block'><strong>栖衡 ERP / OA</strong><span class="qh-topbar-subtitle">人员 · 审批 · 采购 · 研发</span></div>
        <div class='relative ml-auto flex min-w-0 items-center gap-2 text-sm sm:gap-3'>
          <div class='relative'>
            <button type='button' class='relative inline-flex h-9 w-9 items-center justify-center rounded border border-gray-300 text-gray-700 hover:bg-gray-50' aria-label='消息通知' :aria-expanded='notificationsOpen' @click='notificationsOpen = !notificationsOpen'>
              <FeatherIcon name='bell' class='h-4 w-4' />
              <span v-if='unreadNotifications' class='absolute -right-1 -top-1 min-w-4 rounded-full bg-red-600 px-1 text-center text-[10px] leading-4 text-white'>{{ unreadNotifications > 99 ? '99+' : unreadNotifications }}</span>
            </button>
            <div v-if='notificationsOpen' class='absolute right-0 top-11 z-50 w-[min(360px,calc(100vw-24px))] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl'>
              <div class='flex items-center justify-between border-b border-gray-200 px-4 py-3'>
                <span class='font-medium text-gray-900'>消息通知</span>
                <button type='button' class='text-xs text-gray-500 hover:text-gray-900' :disabled='!unreadNotifications' @click='markAllNotificationsRead'>全部已读</button>
              </div>
              <div class='max-h-80 overflow-y-auto'>
                <button v-for='item in notifications' :key='item.name' type='button' class='flex w-full gap-3 border-b border-gray-100 px-4 py-3 text-left hover:bg-gray-50' @click='openNotification(item)'>
                  <span class='mt-1 h-2 w-2 shrink-0 rounded-full' :class='item.read ? "bg-gray-200" : "bg-red-500"'></span>
                  <span class='min-w-0 flex-1'>
                    <span class='block truncate text-sm' :class='item.read ? "text-gray-600" : "font-medium text-gray-900"'>{{ notificationText(item) }}</span>
                    <span class='mt-1 block text-xs text-gray-400'>{{ item.creation }}</span>
                  </span>
                </button>
                <div v-if='!notifications.length' class='px-4 py-8 text-center text-sm text-gray-500'>暂无消息</div>
              </div>
            </div>
          </div>
          <span class='inline-flex items-center rounded-lg bg-[#E7F4F0] px-2 py-1 font-medium text-[#0E615B]'>{{ roleLabel() }}</span>
          <span class='hidden max-w-[220px] truncate text-gray-600 sm:inline'>{{ currentUser() }}</span>
          <button type='button' class='hidden rounded-lg border border-gray-200 px-3 py-1.5 text-gray-700 hover:border-[#147B73] hover:text-[#0E615B] sm:inline-flex' @click='openPasswordDialog'>修改密码</button>
          <button type='button' class='rounded-lg border border-gray-200 px-2 py-1.5 text-gray-700 hover:border-[#147B73] hover:text-[#0E615B] sm:px-3' @click='logout'>&#x9000;&#x51fa;&#x767b;&#x5f55;</button>
        </div>
      </header>
      <div :class="['w-full min-w-0 flex-1 p-3 sm:p-4 md:p-7', isWidePage ? 'max-w-[1900px]' : 'mx-auto max-w-6xl']">
        <div v-if='deniedText' class='mb-3 flex items-start justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800' role='status' data-testid='route-notice'>
          <span>{{ deniedText }}</span>
          <button type='button' class='shrink-0 text-lg leading-none text-amber-700 hover:text-amber-900' aria-label='关闭提示' @click='clearRouteNotice()'>×</button>
        </div>
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
