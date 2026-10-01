<script setup>
// 付款工作项：左边 PO 列表，右边选中的 PO（到货与验收 + 各付款期次）。预置筛选：?status= 和 ?po=。
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute } from 'vue-router';
import {
  REFUND_NOTICE, STATUS_FILTERS, STATUS_TONE, buildPoGroups, filterGroups, groupHeader, installmentView, money,
  sortGroups, statusCounts,
} from '../../lib/paymentView.js';
import { PROCUREMENT_API, errorText } from './paymentApi.js';
import PayFulfilmentPanel from './PayFulfilmentPanel.vue';
import PayInstallmentCard from './PayInstallmentCard.vue';

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  loadError: { type: String, default: '' },
  canFulfil: { type: Boolean, default: false },
  canPurchase: { type: Boolean, default: false },
  reload: { type: Function, required: true },
});
const emit = defineEmits(['open-request']);

const route = useRoute();
const pusher = createResource({ url: PROCUREMENT_API + 'push_po_payment_request', method: 'POST' });

// ?status= 预置状态筛选；只带 ?po= 时显示全部状态（否则已付清的 PO 会被“未完成”筛掉）。
const presetStatus = (query) => (STATUS_FILTERS.includes(String(query.status || '')) ? String(query.status) : (query.po ? '全部' : '未完成'));
const statusFilter = ref(presetStatus(route.query));
const search = ref(String(route.query.po || ''));
const selectedPo = ref(String(route.query.po || ''));
const notice = ref('');
let noticeTimer = null;
onBeforeUnmount(() => clearTimeout(noticeTimer));
const error = ref('');
const pushingKey = ref('');

watch(() => [route.query.status, route.query.po], () => {
  statusFilter.value = presetStatus(route.query);
  search.value = String(route.query.po || '');
  if (route.query.po) selectedPo.value = String(route.query.po);
});

const groups = computed(() => sortGroups(buildPoGroups(props.items), { canFulfil: props.canFulfil }));
const filtered = computed(() => filterGroups(groups.value, statusFilter.value, search.value));
const active = computed(() => filtered.value.find((group) => group.po === selectedPo.value) || filtered.value[0] || null);
const counts = computed(() => statusCounts(props.items));
const header = computed(() => (active.value ? groupHeader(active.value) : null));
const installments = computed(() => (active.value
  ? active.value.items.map((item, index) => installmentView(item, active.value, { canPurchase: props.canPurchase }))
  : []));

function chipCount(status) {
  if (status === '未完成') return counts.value.unfinished;
  if (status === '全部') return counts.value.all;
  return counts.value.counts[status] || 0;
}
function pick(group) { selectedPo.value = group.po; notice.value = ''; error.value = ''; }

async function refresh() {
  try { await props.reload(); } catch (err) { error.value = errorText(err, '付款工作项加载失败'); }
}
async function onFulfilmentChanged() {
  notice.value = '';
  await refresh();
}
async function pushPayment(view) {
  if (pushingKey.value) return;
  notice.value = '';
  error.value = '';
  pushingKey.value = view.key;
  try {
    const result = await pusher.submit({ name: view.po, payment_plan_row: view.planRow });
    notice.value = `已生成采购付款 ${result.payment_request} 并进入审批`;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { notice.value = ''; }, 8000);
    await refresh();
    emit('open-request', result.payment_request);
  } catch (err) {
    error.value = errorText(err, '提交付款审批失败');
    await refresh();
  } finally { pushingKey.value = ''; }
}
</script>

<template>
  <div class="pay-work">
    <div v-if="notice" class="banner ok" role="status">{{ notice }}</div>
    <div v-if="error || loadError" class="banner err" role="alert">{{ error || loadError }}</div>

    <div class="filter-bar pay-filters">
      <button v-for="status in STATUS_FILTERS" :key="status" type="button" class="chip" :class="{ on: statusFilter === status }" @click="statusFilter = status">
        {{ status }}<span class="pay-chip-n">{{ chipCount(status) }}</span>
      </button>
      <input v-model="search" type="search" class="pay-search" placeholder="搜索 PO、供应商、期次" aria-label="搜索付款工作项" />
    </div>

    <div class="pay-split">
      <aside class="panel flush pay-po-list">
        <div class="pt pay-po-title"><span>PO <span class="muted">（有待办的排前面）</span></span></div>
        <button v-for="group in filtered" :key="group.po" type="button" class="pay-po" :class="{ on: active && active.po === group.po }" @click="pick(group)">
          <span class="split"><b>{{ group.po }}</b><span class="pill" :class="`p-${groupHeader(group).tone}`">{{ group.po_status || '—' }}</span></span>
          <span class="pay-po-sup">{{ group.supplier }}</span>
          <span class="muted">到货 {{ groupHeader(group).recvText }} · 验收 {{ groupHeader(group).inspText }} · 已付 {{ money(group.paid, group.currency) }}</span>
          <span class="pay-po-chips">
            <span v-for="(ev, index) in group.evaluated" :key="ev.item.payment_plan_row || index" class="pill pay-mini" :class="`p-${STATUS_TONE[ev.ev.status] || 'gray'}`">{{ ev.item.installment_name }} {{ ev.ev.status }}</span>
          </span>
        </button>
        <div v-if="!filtered.length" class="empty">{{ loading ? '正在加载…' : '当前筛选下没有付款期次' }}</div>
      </aside>

      <div v-if="active" class="pay-main">
        <section class="panel pay-po-head">
          <div class="title-line">
            <h3>{{ header.po }}</h3>
            <span class="pill" :class="`p-${header.tone}`">{{ header.status || '—' }}</span>
          </div>
          <div class="muted">
            {{ header.supplier }}<template v-if="header.source"> · 来源 {{ header.source }}</template>
            <template v-if="active.source_price_approvals"> · 价格审批 {{ active.source_price_approvals }}</template>
            <template v-if="active.contract_status"> · 合同 {{ active.contract_status }}</template>
            · PO 总额 {{ money(header.total, header.currency) }} · 已付 {{ money(header.paid, header.currency) }}
          </div>
        </section>

        <PayFulfilmentPanel :group="active" :can-fulfil="canFulfil" :can-purchase="canPurchase" @changed="onFulfilmentChanged" />

        <section class="panel">
          <div class="pt"><span>付款期次 <span class="muted">条件按整张 PO 判断（全部到货 / 全部验收通过），和本期比例无关；暂不支持分批到货</span></span></div>
          <PayInstallmentCard v-for="view in installments" :key="view.key" :view="view" :currency="active.currency" :busy="pushingKey === view.key" @push="pushPayment" @open="(name) => emit('open-request', name)" />
          <p class="muted pay-foot">审批过程中如果又登记了新的到货、或验收结果变成换货 / 退货，这期会出现“条件已回退”提醒；到最后“总经理确认付款”时系统会拦下，不会错付。{{ REFUND_NOTICE }}。</p>
        </section>
      </div>
      <div v-else class="panel empty pay-main">选择左边的 PO 查看到货验收和付款期次</div>
    </div>
  </div>
</template>
