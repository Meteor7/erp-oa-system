<script setup>
// 价格审批 + PO 与合同。一个页面三个栏目：PR 待比价物料 | 价格审批单 | PO 与合同。
// 用查询参数区分页面（通知和旧链接照常有效）：tab=po、view=source|approvals、request=<OA>（只看这张采购申请的链路）、
// approval=<PA>、po=<PO>、pr=<PR>。到货 / 验收 / 付款登记在"采购付款"里，这里只看进度。
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import '../../styles/expenseUi.css';
import '../../styles/priceUi.css';
import { canEditProcurementPrice, canSeeProcurementPO, canSeeProcurementPrice } from '../../lib/access';
import { extractFrappeError } from '../../lib/frappeError.js';
import {
  contextApprovals, contextPos, contextPrs, contextSummary, defaultTab, pendingLineCount, resolveTab, tabQuery, tabsFor,
} from '../../lib/priceView.js';
import { usePriceApi } from './usePriceApi.js';
import PriceSourceTab from './PriceSourceTab.vue';
import PriceApprovalList from './PriceApprovalList.vue';
import PriceApprovalDetail from './PriceApprovalDetail.vue';
import SupplierDrawer from './SupplierDrawer.vue';
import PoList from './PoList.vue';
import PoDetail from './PoDetail.vue';

const route = useRoute();
const router = useRouter();
const canPrice = canSeeProcurementPrice();
const canPo = canSeeProcurementPO();
const canEdit = canEditProcurementPrice();
const { loaders, actions, reload } = usePriceApi();

const banner = reactive({ ok: '', err: '' });
const busy = ref(false);
const loaded = ref(false);
const startTab = ref('');
const drawer = reactive({ open: false, supplier: '' });

const contextRequest = computed(() => String(route.query.request || '').trim());
const allPrs = computed(() => loaders.prs.data || []);
const allApprovals = computed(() => loaders.approvals.data || []);
const allPos = computed(() => loaders.pos.data || []);
const prs = computed(() => contextPrs(allPrs.value, contextRequest.value));
const approvals = computed(() => contextApprovals(allApprovals.value, contextRequest.value));
const pos = computed(() => contextPos(allPos.value, contextRequest.value));
const summary = computed(() => contextSummary({ request: contextRequest.value, prs: prs.value, approvals: approvals.value, pos: pos.value }));

const explicitTab = computed(() => resolveTab(route.query, { canPrice, canPo }));
const tab = computed(() => explicitTab.value || startTab.value);
const tabs = computed(() => tabsFor({
  canPrice, canPo, counts: { source: pendingLineCount(prs.value), approvals: approvals.value.length, po: pos.value.length },
}));

// 链接里指定了单据就打开那张；在某张采购申请的链路里只有一张时直接打开。
const wantedApproval = computed(() => String(route.query.approval || '').trim());
const wantedPo = computed(() => String(route.query.po || '').trim());
const activeApproval = computed(() => {
  if (wantedApproval.value) return allApprovals.value.find((item) => item.name === wantedApproval.value) || null;
  return contextRequest.value && approvals.value.length === 1 ? approvals.value[0] : null;
});
const activePo = computed(() => {
  if (wantedPo.value) return allPos.value.find((item) => item.name === wantedPo.value) || null;
  return contextRequest.value && pos.value.length === 1 ? pos.value[0] : null;
});
const missingTarget = computed(() => {
  if (!loaded.value) return '';
  if (tab.value === 'approvals' && wantedApproval.value && !activeApproval.value) return `找不到价格审批单 ${wantedApproval.value}（可能已不在你能看到的范围内）`;
  if (tab.value === 'po' && wantedPo.value && !activePo.value) return `找不到 PO ${wantedPo.value}（可能已不在你能看到的范围内）`;
  return '';
});
const loadError = computed(() => {
  const failed = [loaders.prs, loaders.approvals, loaders.pos].find((item) => item.error);
  return failed ? extractFrappeError(failed.error, '数据加载失败') : '';
});
const drawerApproval = computed(() => (drawer.open ? activeApproval.value : null));

function flash(ok = '', err = '') {
  banner.ok = ok;
  banner.err = err;
  if ((ok || err) && !drawer.open && typeof window !== 'undefined' && window.scrollTo) window.scrollTo({ top: 0, behavior: 'smooth' });
}

function go(query = {}) {
  const next = { ...query };
  if (contextRequest.value && !next.request) next.request = contextRequest.value;
  router.push({ path: route.path, query: next });
  if (typeof window !== 'undefined' && window.scrollTo) window.scrollTo({ top: 0 });
}
function openTab(key) {
  flash();
  go(tabQuery(key, { request: contextRequest.value }));
}
function openApproval(name) { flash(); go({ view: 'approvals', approval: name }); }
function openPo(name) { flash(); go({ tab: 'po', po: name }); }
function clearFocusPr() { go({ view: 'source' }); }
const allChainLink = computed(() => ({ path: route.path, query: tabQuery(tab.value || 'approvals', {}) }));

async function reloadAll() {
  try {
    await reload({ price: canPrice, po: canPo });
  } catch (error) {
    flash('', extractFrappeError(error, '数据加载失败'));
  } finally {
    if (!loaded.value) {
      loaded.value = true;
      startTab.value = defaultTab({
        canPrice, canPo,
        hasPendingPr: pendingLineCount(prs.value) > 0,
        hasActionable: approvals.value.some((item) => ['草稿', '待审批'].includes(item.status)),
      });
    }
  }
}

// 统一执行一次写操作：成功就刷新数据并提示，失败显示服务端给的原因。
async function run(action, okText) {
  busy.value = true;
  flash();
  try {
    const result = await action();
    await reload({ price: canPrice, po: canPo });
    flash(typeof okText === 'function' ? okText(result) : okText);
    return { ok: true, result };
  } catch (error) {
    flash('', extractFrappeError(error, '操作失败'));
    return { ok: false, result: null };
  } finally {
    busy.value = false;
  }
}

// ---------------------------------------------------------------- PR source -> price approval
async function createApproval(lines) {
  const done = await run(
    () => actions.createApproval.submit({ lines: JSON.stringify(lines) }),
    (result) => `${result.name} 已生成，请维护候选供应商报价（可按实际询价结果部分填写）`,
  );
  if (done.ok && done.result?.name) go({ view: 'approvals', approval: done.result.name });
}

// ---------------------------------------------------------------- price approval
function openDrawer(supplier = '') {
  flash();
  drawer.supplier = supplier;
  drawer.open = true;
}
function closeDrawer() {
  drawer.open = false;
  drawer.supplier = '';
}
async function saveSupplier(payload) {
  const done = await run(() => actions.saveSupplier.submit(payload), `${payload.supplier} 的报价方案已保存（未报价物料保持空白）`);
  if (done.ok) closeDrawer();
}
async function deleteSupplier(supplier) {
  const done = await run(
    () => actions.deleteSupplier.submit({ price_approval: activeApproval.value.name, supplier }),
    `${supplier} 的报价已删除`,
  );
  if (done.ok) closeDrawer();
}
async function chooseSupplier(supplier) {
  await run(
    () => actions.chooseSupplier.submit({ price_approval: activeApproval.value.name, supplier }),
    `已选择 ${supplier}，有报价的物料进入 PO，没报价的物料退回 PR`,
  );
}
async function saveSummary(text) {
  const value = String(text || '').trim();
  if (!value) { flash('', '请填写采购比价总结'); return; }
  await run(() => actions.updateSummary.submit({ name: activeApproval.value.name, summary: value }), '采购比价总结已保存');
}
async function submitApproval(text) {
  const approval = activeApproval.value;
  const value = String(text || '').trim();
  if (!value) { flash('', '请填写采购比价总结'); return; }
  await run(async () => {
    await actions.updateSummary.submit({ name: approval.name, summary: value });
    return actions.submitApproval.submit({ name: approval.name });
  }, `${approval.name} 已提交副总经理审批`);
}
async function withdrawApproval() {
  await run(() => actions.withdrawApproval.submit({ name: activeApproval.value.name }), '已撤回，可修改后重新提交');
}
async function cancelApproval() {
  await run(() => actions.cancelApproval.submit({ name: activeApproval.value.name }), '价格审批单已取消，物料已退回 PR');
}
async function approveApproval() {
  await run(
    () => actions.approveApproval.submit({ name: activeApproval.value.name }),
    (result) => {
      const names = result?.po_names || [];
      return `审批通过，已按成交供应商生成 ${names.length} 张 PO 草稿${names.length ? `：${names.join('、')}` : ''}`;
    },
  );
}

// ---------------------------------------------------------------- PO / contract
async function saveDelivery(lines) {
  await run(() => actions.updateDelivery.submit({ name: activePo.value.name, lines: JSON.stringify(lines) }), '合同交期已保存');
}
async function confirmPo(lines) {
  const po = activePo.value;
  await run(async () => {
    await actions.updateDelivery.submit({ name: po.name, lines: JSON.stringify(lines) });
    return actions.confirmPo.submit({ name: po.name });
  }, `${po.name} 已确认，进入合同复核`);
}
async function generateContract(payload) {
  await run(() => actions.savePoContract.submit(payload), 'PO 合同草稿已生成，请核对后复核');
}
async function reviewContract() {
  await run(() => actions.reviewPoContract.submit({ name: activePo.value.name }), 'PO 合同已复核，等待副总经理电子用印');
}
async function sealContract() {
  await run(() => actions.sealPoContract.submit({ name: activePo.value.name }), 'PO 已完成电子用印并生效');
}
async function closePo() {
  const po = activePo.value;
  await run(() => actions.closePo.submit({ name: po.name }), `${po.name} 已完成到货、验收和付款并关闭`);
}

onMounted(reloadAll);
</script>

<template>
  <div class="xp pa">
    <div class="ph">
      <div>
        <div class="crumb">审批中心 · 采购/购买申请</div>
        <h3>价格审批</h3>
        <div class="muted">采购从 PR 里挑物料发起比价，录入各家报价；副总经理选一家成交，没报价的物料退回 PR。</div>
      </div>
      <div class="head-actions">
        <button type="button" class="btn" :disabled="busy || loaders.prs.loading || loaders.approvals.loading || loaders.pos.loading" @click="reloadAll">刷新</button>
      </div>
    </div>

    <div v-if="!drawer.open && banner.ok" class="banner ok" role="status">{{ banner.ok }}</div>
    <div v-if="!drawer.open && banner.err" class="banner err" role="alert">{{ banner.err }}</div>
    <div v-if="loadError" class="banner err" role="alert">{{ loadError }}</div>
    <div v-if="missingTarget" class="banner err" role="alert">{{ missingTarget }}</div>

    <div v-if="contextRequest" class="pa-context">
      <div><b>当前仅查看这张采购申请的完整链路</b><span class="muted">{{ summary }}</span></div>
      <router-link :to="allChainLink" class="link strong">查看全部采购链路</router-link>
    </div>

    <div v-if="!tabs.length" class="panel empty">你的账号没有查看价格审批或 PO 的权限。</div>
    <template v-else>
      <nav class="tabs" role="tablist" aria-label="价格审批与 PO">
        <button v-for="item in tabs" :key="item.key" type="button" role="tab" :aria-selected="tab === item.key" @click="openTab(item.key)">
          {{ item.label }}<span class="pa-badge">{{ item.count }}</span>
        </button>
      </nav>

      <div v-if="!loaded" class="panel empty">正在加载…</div>

      <PriceSourceTab
        v-else-if="tab === 'source'"
        :prs="prs" :approvals="allApprovals" :pos="allPos" :can-edit="canEdit" :busy="busy"
        :focus-pr="String(route.query.pr || '')" :context-request="contextRequest"
        @create="createApproval" @clear-focus="clearFocusPr"
      />

      <template v-else-if="tab === 'approvals'">
        <PriceApprovalDetail
          v-if="activeApproval" :key="activeApproval.name"
          :approval="activeApproval" :pos="allPos" :can-edit="canEdit" :busy="busy"
          @back="openTab('approvals')" @open-po="openPo"
          @save-summary="saveSummary" @submit="submitApproval" @cancel="cancelApproval" @withdraw="withdrawApproval"
          @approve="approveApproval" @select="chooseSupplier" @edit="openDrawer" @delete="deleteSupplier"
        />
        <PriceApprovalList v-else :approvals="approvals" :loading="loaders.approvals.loading" @open="openApproval" />
      </template>

      <template v-else-if="tab === 'po'">
        <PoDetail
          v-if="activePo" :key="activePo.name" :po="activePo" :busy="busy"
          @back="openTab('po')" @open-approval="openApproval"
          @save-delivery="saveDelivery" @confirm="confirmPo" @generate="generateContract"
          @review="reviewContract" @seal="sealContract" @close="closePo"
        />
        <PoList v-else :pos="pos" :loading="loaders.pos.loading" @open="openPo" />
      </template>
    </template>

    <SupplierDrawer :open="drawer.open" :approval="drawerApproval" :supplier="drawer.supplier" :busy="busy" :error="banner.err" @save="saveSupplier" @delete="deleteSupplier" @close="closeDrawer" />
  </div>
</template>
