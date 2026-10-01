<script setup>
// 一张采购付款审批单：头部和操作、本期付款条件复核、PO 物料与到货验收进度、履约记录（只读）、来源信息、
// 5 步审批进度、业务资料、操作记录。PO 下推的付款不显示到货 / 验收登记，旧数据（无来源 PO）保留旧流程。
import { computed, reactive, ref, watch } from 'vue';
import { createResource } from 'frappe-ui';
import { useRoute, useRouter } from 'vue-router';
import {
  approvalBanner, approveLabel, currentStepKey, defaultRejectTarget, findWorkItem, formatTime, isFinalPayStep,
  isPoSourced, liveReview, money, paymentFacts, poLinesView, regressionNote, rejectionTargets, requestRecords,
  requestTone, stepRows, validateReject,
} from '../../lib/paymentView.js';
import { OA_API, errorText } from './paymentApi.js';
import PayDocuments from './PayDocuments.vue';
import PayGateGrid from './PayGateGrid.vue';
import PayLegacyActions from './PayLegacyActions.vue';
import PayRecordList from './PayRecordList.vue';

const props = defineProps({
  request: { type: Object, required: true },
  workItems: { type: Array, default: () => [] },
  workReady: { type: Boolean, default: true },
  groups: { type: Array, default: () => [] },
  canWork: { type: Boolean, default: false },
  canManageExpense: { type: Boolean, default: false },
});
const emit = defineEmits(['changed']);

const route = useRoute();
const router = useRouter();
const actor = createResource({ url: OA_API + 'action_request' });
const withdrawer = createResource({ url: OA_API + 'withdraw_request' });

const documents = ref([]);
const actedSteps = reactive({});
const busy = ref(false);
const ok = ref('');
const error = ref('');
const actionNote = ref('');
const rejectTarget = ref('applicant');
const rejectReason = ref('');
const withdrawOpen = ref(false);
const withdrawReason = ref('');

const poSourced = computed(() => isPoSourced(props.request));
const review = computed(() => (poSourced.value && props.canWork
  ? liveReview(props.request, props.workItems, props.groups, documents.value)
  : { available: false, tiles: [], blockers: [], regressed: false, item: null, group: null }));
const item = computed(() => review.value.item || (props.canWork ? findWorkItem(props.workItems, props.request) : null));
const group = computed(() => review.value.group);
const lines = computed(() => poLinesView(props.request, group.value));
const records = computed(() => requestRecords(props.request, group.value));
const facts = computed(() => paymentFacts(props.request, item.value, group.value));
const steps = computed(() => stepRows(props.request));
const log = computed(() => [...(props.request.operation_log || [])].reverse());
const targets = computed(() => rejectionTargets(props.request));
const isDraft = computed(() => props.request.workflow_status === '草稿');
const stepKey = computed(() => currentStepKey(props.request));
const canApprove = computed(() => Boolean(props.request.can_approve) && actedSteps[props.request.name] !== stepKey.value);
const canReject = computed(() => Boolean(props.request.can_reject) && actedSteps[props.request.name] !== stepKey.value);
const canAct = computed(() => !isDraft.value && (canApprove.value || canReject.value));
const canWithdraw = computed(() => !isDraft.value && Boolean(props.request.can_withdraw));
const label = computed(() => approveLabel(props.request));
const finalPay = computed(() => isFinalPayStep(props.request));
const bannerBase = computed(() => approvalBanner(props.request, { canAct: canAct.value, finalPay: finalPay.value, review: review.value }));
const regressedText = computed(() => (review.value.regressed ? regressionNote(review.value.blockers) : ''));
const invoiceRequirement = computed(() => item.value?.invoice_requirement || '');
const trigger = computed(() => item.value?.trigger_condition || '');
const amountLabel = computed(() => money(props.request.amount));
// 最后一步“确认付款”：条件不满足（含缺发票）时按钮置灰并写明原因，服务端在这一步同样会拦下。
const payBlockedReason = computed(() => {
  if (!finalPay.value || !review.value.available) return '';
  if (review.value.blockers?.length) return `本期付款条件现在不满足：${review.value.blockers.join('；')}。`;
  if (review.value.tiles.some((tile) => tile.key === 'invoice' && tile.state === 0)) return '本期要求付款前提供发票，请申请人先上传发票。';
  return '';
});
// 条件不满足时，顶部提示不能再写“条件都满足，可以确认”。
const banner = computed(() => (canAct.value && payBlockedReason.value
  ? { tone: 'warn', text: `轮到你“确认付款”（最后一步），但现在还不能确认。${payBlockedReason.value}` }
  : bannerBase.value));

watch(() => props.request.name, () => {
  ok.value = '';
  error.value = '';
  actionNote.value = '';
  rejectReason.value = '';
  withdrawOpen.value = false;
  withdrawReason.value = '';
  rejectTarget.value = defaultRejectTarget(props.request);
}, { immediate: true });
watch(targets, (list) => {
  if (!list.some((t) => t.target === rejectTarget.value)) rejectTarget.value = defaultRejectTarget(props.request);
});

async function act(action) {
  if (busy.value) return;
  ok.value = '';
  error.value = '';
  if (action === 'reject') {
    const problem = validateReject({ reason: rejectReason.value, target: rejectTarget.value });
    if (problem) { error.value = problem; return; }
  }
  const name = props.request.name;
  busy.value = true;
  try {
    const params = {
      name, action,
      note: action === 'reject' ? rejectReason.value.trim() : actionNote.value.trim(),
      expected_step_key: props.request.current_step_key || '',
    };
    if (action === 'reject') params.reject_target = rejectTarget.value;
    await actor.submit(params);
    actedSteps[name] = stepKey.value;
    rejectReason.value = '';
    actionNote.value = '';
    ok.value = action === 'reject' ? `${name} 已定向驳回` : (finalPay.value ? `${name} 已确认付款` : `${name} 已${label.value === '办理完成' ? '办理完成' : '审批通过'}`);
    emit('changed');
  } catch (err) {
    error.value = errorText(err, '审批操作失败');
    emit('changed');
  } finally { busy.value = false; }
}

async function withdraw() {
  if (busy.value) return;
  ok.value = '';
  error.value = '';
  busy.value = true;
  try {
    await withdrawer.submit({ name: props.request.name, note: withdrawReason.value.trim() });
    ok.value = `${props.request.name} 已撤回，付款期次回到“可提交付款审批”`;
    withdrawOpen.value = false;
    withdrawReason.value = '';
    emit('changed');
  } catch (err) {
    error.value = errorText(err, '撤回申请失败');
    emit('changed');
  } finally { busy.value = false; }
}

function onDocuments(rows) { documents.value = rows; }
function openWork() {
  router.push({ path: route.path, query: { po: props.request.source_purchase_order || '' } });
}
</script>

<template>
  <div class="pay-approval">
    <section class="panel pay-approval-head">
      <div class="detail-head">
        <div class="grow-col">
          <div class="title-line">
            <h3>{{ request.subject || request.name }}</h3>
            <span class="pill" :class="`p-${requestTone(request.workflow_status)}`">{{ request.workflow_status_label || request.workflow_status }}</span>
          </div>
          <div class="muted">
            {{ request.name }} · 申请人 {{ request.employee_name || '-' }} · {{ request.supplier || '-' }}
            <template v-if="request.source_purchase_order"> · 来源 {{ request.source_purchase_order }}</template>
            <template v-else> · 来源 {{ request.source_request || '旧付款计划' }}</template>
          </div>
        </div>
        <div class="amount-block"><span class="muted">本期付款金额</span><b>{{ amountLabel }}</b></div>
        <div class="head-buttons">
          <button v-if="canWithdraw" type="button" class="btn danger" :disabled="busy" @click="withdrawOpen = !withdrawOpen">撤回申请</button>
          <button v-if="canReject" type="button" class="btn danger" :disabled="busy" @click="act('reject')">驳回</button>
          <button v-if="canApprove" type="button" class="btn pri lg" :disabled="busy || Boolean(payBlockedReason)" :aria-describedby="payBlockedReason ? 'pay-blocked-hint' : undefined" @click="act('approve')">{{ label }}</button>
        </div>
      </div>

      <div id="pay-blocked-hint" class="pay-banner" :class="`is-${banner.tone}`">{{ banner.text }}</div>
      <div v-if="ok" class="banner ok" role="status">{{ ok }}</div>
      <div v-if="error" class="banner err" role="alert">{{ error }}</div>

      <div v-if="withdrawOpen && canWithdraw" class="pay-act-form pay-withdraw">
        <div class="f s2">
          <label for="pay-withdraw-reason">撤回原因（可选）</label>
          <input id="pay-withdraw-reason" v-model="withdrawReason" type="text" placeholder="可不填" />
        </div>
        <div class="head-actions">
          <button type="button" class="btn danger" :disabled="busy" @click="withdraw">确认撤回</button>
          <button type="button" class="btn" @click="withdrawOpen = false">取消</button>
        </div>
      </div>

      <div v-if="canAct" class="pay-act-form">
        <div v-if="canApprove" class="f">
          <label for="pay-note">审批意见（可选）</label>
          <input id="pay-note" v-model="actionNote" type="text" :placeholder="finalPay ? '确认付款时可留言' : '同意时可留言'" />
        </div>
        <div v-if="canReject" class="f">
          <label for="pay-target">驳回到</label>
          <select id="pay-target" v-model="rejectTarget">
            <option v-for="target in targets" :key="target.target" :value="target.target">{{ target.label }}</option>
            <option v-if="!targets.length" value="applicant">申请人</option>
          </select>
        </div>
        <div v-if="canReject" class="f">
          <label for="pay-reject-reason">驳回原因<b>*</b>（驳回时必填）</label>
          <input id="pay-reject-reason" v-model="rejectReason" type="text" placeholder="写清楚要改什么" />
        </div>
      </div>
    </section>

    <div class="detail-grid">
      <div>
        <section v-if="poSourced" class="panel pay-review">
          <div class="pt">
            <span>本期付款条件复核 <span class="muted">和付款工作项里同一套判断，实时重算</span></span>
            <button v-if="canWork" type="button" class="link" @click="openWork">去看到货与验收 →</button>
          </div>
          <template v-if="review.available">
            <div class="pay-trigger">触发条件：<b>{{ trigger || '无附加条件' }}</b> · 阶段 {{ request.payment_stage || item?.payment_stage || '-' }} · 发票要求 {{ invoiceRequirement || '未约定' }}</div>
            <PayGateGrid :tiles="review.tiles" />
            <div v-if="regressedText" class="banner pay-regress" role="alert">{{ regressedText }}</div>
          </template>
          <p v-else-if="canWork && !workReady" class="muted" aria-live="polite">正在加载付款条件…</p>
          <p v-else class="muted">{{ canWork ? '在付款工作项里没有找到这一期，无法实时核对条件。' : '你没有 PO 查看权限，不能实时核对条件；下面仍显示来源 PO 的到货、验收记录。' }}</p>
          <p class="muted">系统只在最后一步“总经理确认付款”时再检查一次条件和发票；前面几级审批你要自己看这里，别等到最后被拦下。</p>
        </section>

        <section class="panel">
          <div class="pt"><span>{{ poSourced ? 'PO 物料与到货验收进度' : '采购付款明细' }} <span class="muted">{{ poSourced ? '整张 PO 的物料；本期只付其中一期，金额见右上' : '关联物料范围' }}</span></span></div>
          <div class="tbl">
            <table class="pay-lines">
              <thead><tr><th>物品 / 规格</th><th class="r">订购</th><th class="r">已到</th><th>验收</th><th class="r">金额</th></tr></thead>
              <tbody>
                <tr v-for="line in lines" :key="line.key">
                  <td><b>{{ line.name }}</b><div class="muted">{{ line.spec }}</div></td>
                  <td class="r num">{{ line.qty }}</td>
                  <td class="r num">{{ line.recv }}</td>
                  <td>
                    <span v-if="line.state" class="pill" :class="`p-${line.state.tone}`">{{ line.state.label }}</span>
                    <span v-else class="muted">—</span>
                    <div v-if="line.hint" class="muted pay-reason-text">{{ line.hint }}</div>
                  </td>
                  <td class="r num strong">{{ money(line.amount) }}</td>
                </tr>
                <tr v-if="!lines.length"><td colspan="5" class="empty">没有明细</td></tr>
              </tbody>
            </table>
          </div>
          <h4>到货、验收、换货、退货记录（只读）</h4>
          <PayRecordList :records="records" empty-text="还没有到货、验收记录。" />
        </section>

        <PayLegacyActions :request="request" :documents="documents" :can-manage-expense="canManageExpense" @changed="emit('changed')" />

        <section class="panel">
          <div class="pt"><span>付款来源</span></div>
          <div class="pay-facts">
            <div v-for="fact in facts" :key="fact.k"><span class="muted">{{ fact.k }}</span><b>{{ fact.v }}</b></div>
          </div>
        </section>
      </div>

      <aside>
        <section class="panel">
          <div class="pt"><span>审批进度</span></div>
          <div v-for="step in steps" :key="step.key" class="tl" :class="step.state">
            <div class="rail"><i></i><span></span></div>
            <div class="body">
              <b>{{ step.index }}. {{ step.label }}</b>
              <span class="muted">{{ step.sub }}{{ step.state === 'now' && step.mode === 'handle' && finalPay ? ' · 确认付款' : '' }}</span>
              <div v-if="step.note" class="note">意见：{{ step.note }}</div>
            </div>
          </div>
          <p v-if="poSourced" class="muted">5 步都是这个顺序，和付款阶段无关。前 4 步“审批通过”，最后一步总经理“确认付款”才算付出去。</p>
        </section>

        <PayDocuments :request="request" :invoice-requirement="invoiceRequirement" @loaded="onDocuments" />

        <section v-if="log.length" class="panel">
          <div class="pt"><span>操作记录</span></div>
          <div v-for="(event, index) in log" :key="index" class="pay-log">
            <span class="muted">{{ formatTime(event.acted_on) }}</span>
            <span>{{ event.action }} · {{ event.actor }}<template v-if="event.note"> · {{ event.note }}</template></span>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
