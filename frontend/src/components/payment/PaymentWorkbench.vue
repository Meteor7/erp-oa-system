<script setup>
// 采购付款（/approval/procurement-payment）。两个页签：
//   付款工作项：按 PO 办理——生产主管登记到货 / 验收 / 换货到货 / 退货发出，条件满足后采购提交付款审批；
//   付款审批单：付款 OA 的队列和审批页（财务逐级审批，总经理确认付款）。
// 用查询参数区分：?request= 直接打开某张付款审批单；?tab=approvals 打开审批单页签；?status= / ?po= 预置工作项筛选。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import '../../styles/paymentUi.css';
import { canEditProcurementPrice, canRecordPoFulfilment, canSeeProcurementPO } from '../../lib/access.js';
import { buildPoGroups, statusCounts } from '../../lib/paymentView.js';
import { OA_API, PROCUREMENT_API, errorText } from './paymentApi.js';
import PayApprovalsTab from './PayApprovalsTab.vue';
import PayWorkTab from './PayWorkTab.vue';

const route = useRoute();
const router = useRouter();

// 付款工作项需要 PO 查看权限（服务端 _require_po_view）；其他人（审批人、申请人）只用付款审批单页签。
const canWork = canSeeProcurementPO();
const canFulfil = canRecordPoFulfilment();
const canPurchase = canEditProcurementPrice();

const optionLoader = createResource({ url: OA_API + 'get_options', method: 'GET', auto: true });
const workLoader = createResource({ url: PROCUREMENT_API + 'list_payment_work_items', method: 'GET' });
const approvalsRef = ref(null);
const approvalsCount = ref(0);
const workError = ref('');

const tab = computed(() => (route.query.request || route.query.tab === 'approvals' || !canWork ? 'approvals' : 'work'));
const items = computed(() => workLoader.data || []);
const workReady = computed(() => workLoader.data !== null && workLoader.data !== undefined);
const groups = computed(() => buildPoGroups(items.value));
const unfinished = computed(() => statusCounts(items.value).unfinished);

async function reloadWork() {
  if (!canWork) return;
  workError.value = '';
  try { await workLoader.reload(); } catch (err) { workError.value = errorText(err, '付款工作项加载失败'); }
}
async function refreshAll() {
  await Promise.all([reloadWork(), approvalsRef.value?.refresh?.()]);
}
function showWork() { router.replace({ path: route.path, query: {} }); }
function showApprovals() { router.replace({ path: route.path, query: { tab: 'approvals' } }); }
async function openRequest(name) {
  await router.replace({ path: route.path, query: name ? { tab: 'approvals', request: name } : { tab: 'approvals' } });
  await approvalsRef.value?.refresh?.(); // 刚下推的付款单要出现在队列里
}

let timer = null;
function onVisible() { if (document.visibilityState === 'visible') refreshAll(); }
onMounted(() => {
  reloadWork();
  window.addEventListener('focus', refreshAll);
  document.addEventListener('visibilitychange', onVisible);
  timer = window.setInterval(refreshAll, 30000);
});
onBeforeUnmount(() => {
  window.removeEventListener('focus', refreshAll);
  document.removeEventListener('visibilitychange', onVisible);
  if (timer) window.clearInterval(timer);
});
</script>

<template>
  <div class="xp pay-root">
    <div class="ph">
      <div>
        <div class="crumb">审批中心 · 付款申请</div>
        <h3>采购付款</h3>
        <div class="muted">按 PO 办理：生产主管登记到货和验收 → 条件满足后采购提交付款审批 → 财务逐级审批、总经理确认付款。验收不是审批节点，只是付款的前置条件。</div>
      </div>
      <div class="head-actions">
        <router-link v-if="canWork" class="btn" to="/approval/procurement/price-approvals?tab=po">查看 PO 与合同</router-link>
        <button type="button" class="btn" :disabled="workLoader.loading" @click="refreshAll">刷新</button>
      </div>
    </div>

    <div class="tabs" role="tablist">
      <button v-if="canWork" type="button" role="tab" :aria-selected="tab === 'work'" @click="showWork">付款工作项<span class="c">{{ unfinished }}</span></button>
      <button type="button" role="tab" :aria-selected="tab === 'approvals'" @click="showApprovals">付款审批单<span class="c">{{ approvalsCount }}</span></button>
    </div>

    <PayWorkTab
      v-if="canWork"
      v-show="tab === 'work'"
      :items="items"
      :loading="workLoader.loading"
      :load-error="workError"
      :can-fulfil="canFulfil"
      :can-purchase="canPurchase"
      :reload="reloadWork"
      @open-request="openRequest"
    />
    <PayApprovalsTab
      v-show="tab === 'approvals'"
      ref="approvalsRef"
      :active="tab === 'approvals'"
      :options="optionLoader.data"
      :work-items="items"
      :work-ready="workReady"
      :groups="groups"
      :can-work="canWork"
      :reload-work="reloadWork"
      @count="(n) => (approvalsCount = n)"
    />
  </div>
</template>
